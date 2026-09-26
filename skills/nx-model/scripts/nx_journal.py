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
def vertical_edges(body, tol=1e-6):
    """Edges parallel to Z, found by geometry. VERIFIED."""
    out = []
    for e in body.GetEdges():
        p0, p1 = e.GetVertices()
        if abs(p0.X - p1.X) < tol and abs(p0.Y - p1.Y) < tol and abs(p1.Z - p0.Z) > tol:
            out.append(e)
    return out


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
            target=None, name="extrude"):
    """One extrude commit wrapped in its own undo mark. VERIFIED.

    Lengths reach the API as STRINGS via RightHandSide: assigning a float to a
    length's .Value applies a silent 25.4x conversion.
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
        NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0),
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
    for stale in (prt_path,):
        if os.path.exists(stale):
            os.remove(stale)
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


def check_geometry(part, body, spec, log, result):
    """Compare the kernel against the recipe's analytic values.

    This is the whole point of the skill: a part that was built wrong must FAIL the
    run, not exit 0. Expected values come from the same recipe the verifier uses, so
    the two can never drift apart.
    """
    vol, n_faces, n_edges = measure(part, body)
    exp_vol, exp_faces = nxc.part_metrics(spec)
    exp_cyl = nxc.cylindrical_faces(spec)
    cyl = cylindrical_face_count(body)

    result["checks"]["volume"] = {"actual": round(vol, 6), "expected": round(exp_vol, 6),
                                  "delta": round(abs(vol - exp_vol), 6)}
    result["checks"]["faces"] = {"actual": n_faces, "expected": exp_faces}
    result["checks"]["edges"] = {"actual": n_edges}
    result["checks"]["cylindrical_faces"] = {"actual": cyl, "expected": exp_cyl}

    log.chk("volume %.3f mm^3  expected %.3f  delta %.4f"
            % (vol, exp_vol, abs(vol - exp_vol)))
    log.chk("faces=%d (expected %d)  edges=%d" % (n_faces, exp_faces, n_edges))
    log.chk("cylindrical faces=%d (expected %d)" % (cyl, exp_cyl))

    if abs(vol - exp_vol) >= 1e-3:
        log.err("volume does not match the analytic value - the model is wrong")
    if n_faces != exp_faces:
        log.err("face count %d, expected %d - a feature did not apply as intended"
                % (n_faces, exp_faces))
    if cyl != exp_cyl:
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
