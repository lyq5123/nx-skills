# =============================================================================
#  nx_journal - the NX-side plumbing every builder journal shares
#
#  A builder journal should contain GEOMETRY and nothing else: which curves, which
#  booleans, in what order. Session handling, undo marks, the STEP export, the
#  self-check and the result file all live here so a second part type does not mean
#  a second copy of them.
#
#  Everything here talks to NXOpen, so this module only works inside a journal.
#  The pure-logic side (spec, validation, analytic metrics) is nx_common/nx_recipes
#  and stays importable by plain Python.
#
#  Helpers marked VERIFIED were exercised on NX 2406; the export path in particular
#  is not interchangeable - see export_step().
# =============================================================================
import math
import os
import subprocess
import sys
import time

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

import nx_common as nxc


# -----------------------------------------------------------------------------
# curves
# -----------------------------------------------------------------------------
def circle(part, cx, cy, dia, z=0.0):
    """A full circle as a curve. VERIFIED - arc angles are in RADIANS."""
    return part.Curves.CreateArc(
        NXOpen.Point3d(cx, cy, z),
        NXOpen.Vector3d(1.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 1.0, 0.0),
        dia / 2.0, 0.0, 2.0 * math.pi)


def arc(part, centre, radius, start_deg, end_deg,
        x_dir=(1.0, 0.0, 0.0), y_dir=(0.0, 1.0, 0.0)):
    """A partial arc, for profiles that are not all straight edges.

    `centre` is a 3D point, and x_dir/y_dir span the plane the arc lies in, so an
    arc can be placed in XZ (a cradle groove) as easily as in XY.
    Angles are in DEGREES here - the API takes radians, and mixing the two is a
    silent way to get the wrong sweep.
    """
    return part.Curves.CreateArc(
        NXOpen.Point3d(*centre),
        NXOpen.Vector3d(*x_dir),
        NXOpen.Vector3d(*y_dir),
        radius, math.radians(start_deg), math.radians(end_deg))


def closed_loop(part, points, z=0.0):
    """A closed polyline through (x, y) pairs, last point joined back to the first.

    Used for any straight-sided profile - the plate's rectangle, the bracket's L.
    """
    pts = [NXOpen.Point3d(x, y, z) for x, y in points]
    n = len(pts)
    return [part.Curves.CreateLine(pts[i], pts[(i + 1) % n]) for i in range(n)]


# -----------------------------------------------------------------------------
# finding geometry again after a feature was built (never by index - order is
# not stable across rebuilds)
# -----------------------------------------------------------------------------
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def edges_along(body, axis, tol=1e-6):
    """Edges parallel to a global axis, found by geometry. VERIFIED.

    Never by index - edge order is not stable across rebuilds. `axis` is "x", "y"
    or "z": an edge qualifies when the two components across that axis vanish and
    the component along it does not.
    """
    idx = _AXIS_INDEX[axis]
    others = [i for i in range(3) if i != idx]
    out = []
    for e in body.GetEdges():
        p0, p1 = e.GetVertices()
        c = (abs(p1.X - p0.X), abs(p1.Y - p0.Y), abs(p1.Z - p0.Z))
        if c[idx] > tol and all(c[i] < tol for i in others):
            out.append(e)
    return out


def vertical_edges(body, tol=1e-6):
    """Edges parallel to Z. VERIFIED - kept as the name the plate builder reads."""
    return edges_along(body, "z", tol)


def circular_edges_on_ring(body, radius, z, tol=1e-4):
    """Circular edges lying on the circle of `radius` at height `z`. VERIFIED.

    Both endpoints of a circular edge lie on its circle, so radius and Z classify
    it stably, wherever the seam happens to fall.
    """
    out = []
    for e in body.GetEdges():
        if e.SolidEdgeType != NXOpen.Edge.EdgeType.Circular:
            continue
        p0, p1 = e.GetVertices()
        r0, r1 = math.hypot(p0.X, p0.Y), math.hypot(p1.X, p1.Y)
        if (abs(r0 - radius) < tol and abs(r1 - radius) < tol
                and abs(p0.Z - z) < tol and abs(p1.Z - z) < tol):
            out.append(e)
    return out


def cylindrical_face_count(body):
    return len([f for f in body.GetFaces()
                if f.SolidFaceType == NXOpen.Face.FaceType.Cylindrical])


# -----------------------------------------------------------------------------
# features
# -----------------------------------------------------------------------------
def extrude(part, session, curves, seed_point, depth_start, depth_end, boolean,
            target=None, name="extrude", direction=(0.0, 0.0, 1.0)):
    """One extrude commit wrapped in its own undo mark. VERIFIED.

    Lengths reach the API as STRINGS via RightHandSide: assigning a float to a
    length's .Value applies a silent 25.4x conversion.

    `direction` defaults to +Z and the profile is normally drawn in XY. A groove
    whose axis is horizontal (a shaft cradle) needs both parts changed together:
    the curves placed in the plane perpendicular to the cut, and the direction set
    to match - e.g. curves in XZ at y=y0 with direction (0, 1, 0).
    """
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, name)
    ext = part.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
    sec = part.Sections.CreateSection(0.0095, 0.01, 0.5)
    ext.Section = sec
    ext.BooleanOperation.Type = boolean
    ext.BooleanOperation.SetTargetBodies([target if target is not None else NXOpen.Body.Null])
    ext.Limits.StartExtend.Value.RightHandSide = str(depth_start)
    ext.Limits.EndExtend.Value.RightHandSide = str(depth_end)
    rule = part.ScRuleFactory.CreateRuleCurveDumb(curves)
    sec.AddToSection([rule], curves[0], NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                     seed_point, NXOpen.Section.Mode.Create, False)
    ext.Direction = part.Directions.CreateDirection(
        NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(*direction),
        NXOpen.SmartObject.UpdateOption.WithinModeling)
    feat = ext.CommitFeature()
    ext.Destroy()
    session.UpdateManager.DoUpdate(mark)
    return feat


def blend_edges(part, session, edges, radius):
    """Edge blend. AddChainset takes (collector, radius_string) - not (edge, index)."""
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "blend")
    ebb = part.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
    col = part.ScCollectors.CreateCollector()
    col.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(edges)], False)
    ebb.AddChainset(col, str(radius))
    feat = ebb.CommitFeature()
    ebb.Destroy()
    session.UpdateManager.DoUpdate(mark)
    return feat


def chamfer_edges(part, session, edges, offset):
    """Symmetric chamfer on the given edges."""
    mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "chamfer")
    cb = part.Features.CreateChamferBuilder(NXOpen.Features.Feature.Null)
    col = part.ScCollectors.CreateCollector()
    col.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(edges)], False)
    cb.SmartCollector = col
    cb.Option = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
    cb.FirstOffset = str(offset)
    cb.Tolerance = 0.01                 # default 0 raises "Tolerance error"
    feat = cb.CommitFeature()
    cb.Destroy()
    session.UpdateManager.DoUpdate(mark)
    return feat


# -----------------------------------------------------------------------------
# part lifecycle
# -----------------------------------------------------------------------------
def new_metric_part(session, prt_path, log):
    """A fresh millimetre part. NewBaseDisplay refuses to overwrite an existing file."""
    if os.path.exists(prt_path):
        try:
            os.remove(prt_path)
        except OSError as exc:
            # The commonest cause by far is the user's own NX session holding the
            # .prt open - show_in_nx.py opens it there on purpose. Name that cause
            # instead of letting a bare PermissionError traceback be the whole story.
            # Then re-raise: a builder cannot continue without a part, and a run that
            # carries on would be worse than one that stops.
            log.err("cannot overwrite the existing part %s: %s" % (prt_path, exc))
            log.info("       if NX has it open, close it (or build under another "
                     "part_name) and run again")
            raise
    part = session.Parts.NewBaseDisplay(prt_path, NXOpen.BasePart.Units.Millimeters)
    if isinstance(part, tuple):          # some releases return a tuple
        part = part[0]
    log.ok("new part: " + prt_path)
    return part


def measure(part, body):
    """(volume, face count, edge count) straight from the kernel."""
    mp = part.MeasureManager.NewMassProperties(
        [part.UnitCollection.GetBase("Mass")], 0.99, [body])
    return mp.Volume, len(body.GetFaces()), len(body.GetEdges())


def stage_volume(part, body, log, label):
    """Log the running volume after one feature.

    When the final self-check disagrees, this is what tells you WHICH feature is
    responsible instead of leaving you to guess at the total. Each stage's delta
    can be compared with the matching term of the recipe's decomposition.
    """
    vol = measure(part, body)[0]
    log.chk("  stage %-14s volume %.3f" % (label, vol))
    return vol


def check_geometry(part, body, spec, log, result, volume_offset=0.0):
    """Compare the kernel against the recipe's analytic values.

    This is the whole point of the skill: a part that was built wrong must FAIL the
    run, not exit 0. Expected values come from the same recipe the verifier uses, so
    the two can never drift apart.

    `volume_offset` is material the reference value does not model - in practice the
    edges a blend or chamfer rounded off, which no closed form covers for an
    arbitrary feature list. It is ADDED to what the kernel measured before the
    comparison, so the check stays on the geometry the reference does describe, and
    it is reported separately rather than folded in silently.
    """
    vol, n_faces, n_edges = measure(part, body)
    exp_vol, exp_faces = nxc.part_metrics(spec)
    exp_cyl = nxc.cylindrical_faces(spec)
    cyl = cylindrical_face_count(body)
    compare = vol + volume_offset

    result["checks"]["volume"] = {"actual": round(vol, 6), "expected": round(exp_vol, 6),
                                  "delta": round(abs(compare - exp_vol), 6)}
    if volume_offset:
        result["checks"]["volume"]["rounded_off"] = round(volume_offset, 6)
        result["checks"]["volume"]["compared"] = round(compare, 6)
    result["checks"]["faces"] = {"actual": n_faces, "expected": exp_faces}
    result["checks"]["edges"] = {"actual": n_edges}
    result["checks"]["cylindrical_faces"] = {"actual": cyl, "expected": exp_cyl}

    log.chk("volume %.3f mm^3  expected %.3f  delta %.4f"
            % (vol, exp_vol, abs(compare - exp_vol)))
    if volume_offset:
        log.chk("  of which %.3f was removed by blend/chamfer - the reference value "
                "does not model those, so it is added back before comparing"
                % volume_offset)
    if exp_faces is None:
        # Some shapes have no face count that can be derived honestly (the cradle
        # block: several blends and a groove meet on shared faces). Asserting a
        # number copied from a previous run would be self-consistency dressed up as
        # verification, so it is reported and NOT asserted.
        log.chk("faces=%d edges=%d  (face count not asserted for this shape)"
                % (n_faces, n_edges))
    else:
        log.chk("faces=%d (expected %d)  edges=%d" % (n_faces, exp_faces, n_edges))
    if exp_cyl is None:
        # an arbitrary feature list has no derivable cylinder count either; assert
        # nothing rather than assert a number copied from a previous run
        log.chk("cylindrical faces=%d (not asserted for this shape)" % cyl)
    else:
        log.chk("cylindrical faces=%d (expected %d)" % (cyl, exp_cyl))

    tol = nxc.part_tolerance(spec)
    if abs(compare - exp_vol) > tol * max(abs(exp_vol), 1.0):
        log.err("volume is off by %.6f, beyond the %.1g relative agreement this shape "
                "allows (sampled references are looser than closed forms)"
                % (abs(compare - exp_vol), tol))
    if exp_faces is not None and n_faces != exp_faces:
        log.err("face count %d, expected %d - a feature did not apply as intended"
                % (n_faces, exp_faces))
    if exp_cyl is not None and cyl != exp_cyl:
        log.err("cylindrical face count %d, expected %d - a hole or blend is missing"
                % (cyl, exp_cyl))
    return body


def save_part(part, prt_path, log, result):
    part.Save(NXOpen.BasePart.SaveComponents.TrueValue,
              NXOpen.BasePart.CloseAfterSave.FalseValue)
    if os.path.exists(prt_path):
        log.ok("saved " + prt_path)
        result["files"]["prt"] = prt_path
        result["files"]["prt_bytes"] = os.path.getsize(prt_path)
        return True
    log.err("save reported success but %s does not exist" % prt_path)
    return False


def export_step(part, step_path, log):
    """Export REAL solid geometry via the bundled CLI translator. VERIFIED.

    DexManager.CreateStepCreator() validates, commits, and writes a plausibly-sized
    file containing NO geometry under run_journal.exe - do not go back to it. Two
    details that matter: the translator must be launched from inside the journal
    (else libccov.dll is missing from PATH), and with cwd=out_dir (it also writes a
    sidecar log by a relative path).
    """
    base = nxc.base_dir()
    exe = os.path.join(base, "STEP214UG", "step214ug.exe")
    deff = os.path.join(base, "STEP214UG", "ugstep214.def")
    log_path = os.path.splitext(step_path)[0] + ".log"
    for f in (exe, deff):
        if not os.path.isfile(f):
            log.err("STEP translator missing: %s" % f)
            return False
    for f in (step_path, log_path):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError as exc:
                log.warn("cannot remove stale %s: %s" % (os.path.basename(f), exc))

    try:
        r = subprocess.run([exe, part.FullPath, "o=" + step_path, "l=" + log_path,
                            "d=" + deff], capture_output=True, text=True, timeout=300,
                           cwd=os.path.dirname(step_path) or None)
    except Exception as exc:
        log.err("STEP translator could not run: %s: %s" % (type(exc).__name__, exc))
        return False

    if r.returncode != 0:
        log.err("step214ug.exe exit %s: %s" % (r.returncode, (r.stderr or "")[:300]))
        return False
    if not os.path.exists(step_path):
        log.err("translator reported success but wrote no file")
        return False

    with open(step_path, "r", encoding="latin-1", errors="replace") as fh:
        text = fh.read()
    solids = text.count("MANIFOLD_SOLID_BREP(")
    faces = text.count("ADVANCED_FACE(")
    log.chk("STEP solids=%d faces=%d  (%d bytes)"
            % (solids, faces, os.path.getsize(step_path)))
    if solids == 0 or faces == 0:
        log.err("STEP contains no solid geometry - export is a shell")
        return False
    return True


# -----------------------------------------------------------------------------
# the shared main(): spec -> validate -> build -> self-check -> save -> export
# -----------------------------------------------------------------------------
def run(build_fn, default_spec, argv, title):
    """Run one builder journal end to end.

    build_fn(spec, params, paths, log, result) should create the geometry and call
    check_geometry(). Everything around it - argument handling, validation, logging,
    the result file, and a non-zero exit on any failure - is the same for every
    part type and lives here.
    """
    started = time.time()

    try:
        spec, source = nxc.load_spec(argv, default_spec)
    except nxc.SpecError as exc:
        print("[FAIL] %s" % exc)
        sys.stdout.flush()
        sys.exit(1)

    problems = nxc.validate_part(spec)
    if problems:
        print("[FAIL] spec rejected, nothing was built:")
        for p in problems:
            print("       - %s" % p)
        sys.stdout.flush()
        sys.exit(1)

    p = nxc.paths_for(spec)
    if not os.path.isdir(p["out_dir"]):
        try:
            os.makedirs(p["out_dir"])
        except OSError as exc:
            print("[FAIL] cannot create out_dir %s: %s" % (p["out_dir"], exc))
            sys.exit(1)

    log = nxc.Log(p["log"] if spec.get("export", {}).get("log_file", True) else None)
    result = {
        "part": nxc.part_type_of(spec),
        "part_name": spec["part_name"],
        "spec_source": source,
        "params": spec["params"],
        "files": {},
        "checks": {},
        "ugii_base_dir": os.environ.get("UGII_BASE_DIR", ""),
    }

    try:
        log.info("=== %s ===" % title)
        log.info("spec from %s" % source)
        build_fn(spec, spec["params"], p, log, result)
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        log.err("unhandled %s: %s" % (type(exc).__name__, exc))
        for line in traceback.format_exc().splitlines():
            log.info(line)
    finally:
        nxc.finish(log, p["result"], result, started)
