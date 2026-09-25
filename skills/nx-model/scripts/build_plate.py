# =============================================================================
#  NX Open Python journal  -  parametric mounting plate
#  Verified on NX 2406 (built, measured, and STEP-exported).
#
#  RUN
#    headless, defaults:  "$UGII_BASE_DIR/NXBIN/run_journal.exe" build_plate.py
#    headless, from spec: ".../run_journal.exe" build_plate.py -args my_spec.json
#    in the GUI:          Developer > Play
#
#  Two ways to set dimensions, same result:
#    1. edit the parameter block below  (running with no arguments uses it)
#    2. pass a JSON spec file with -args, which overrides any of those values
#
#  All dimensions are MILLIMETRES. Lengths reach the API as strings via
#  RightHandSide / SetFormula - assigning a float to a length's .Value applies a
#  silent 25.4x unit conversion.
#
#  Exits non-zero and writes <part>.result.json if anything failed. A journal that
#  reports a problem can no longer look like a success.
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
# parameters (mm) - the defaults used when no spec file is given
# -----------------------------------------------------------------------------
PLATE_W = 120.0            # overall X
PLATE_H = 80.0             # overall Y
PLATE_T = 10.0             # extrude thickness

HOLE_D = 6.6               # corner hole diameter, 0 = skip
HOLE_INSET = 12.0          # hole centre distance from the edge

BORE_D = 30.0              # central bore diameter, 0 = skip

FILLET_R = 0.0             # corner fillet radius, 0 = off

# Where the .prt / .step / logs go. Defaults to ~/nx_out; a spec's "out_dir"
# overrides it. `~` and relative paths are resolved by nx_common.resolve_out_dir.
OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "mounting_plate_demo"

DEFAULT_SPEC = {
    "part_name": PART_NAME,
    "out_dir": OUT_DIR,
    "part": "mounting_plate",
    "params": {
        "plate_w": PLATE_W,
        "plate_h": PLATE_H,
        "plate_t": PLATE_T,
        "hole_d": HOLE_D,
        "hole_inset": HOLE_INSET,
        "bore_d": BORE_D,
        "fillet_r": FILLET_R,
    },
    "export": {"step": True, "log_file": True},
}


# -----------------------------------------------------------------------------
# geometry helpers
# -----------------------------------------------------------------------------
def circle(part, cx, cy, dia, z=0.0):
    """A full circle as a curve: arc angles are in RADIANS."""
    return part.Curves.CreateArc(
        NXOpen.Point3d(cx, cy, z),
        NXOpen.Vector3d(1.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 1.0, 0.0),
        dia / 2.0, 0.0, 2.0 * math.pi)


def vertical_edges(body, tol=1e-6):
    """Edges parallel to Z, found by geometry - index order is not stable."""
    out = []
    for e in body.GetEdges():
        p0, p1 = e.GetVertices()
        if abs(p0.X - p1.X) < tol and abs(p0.Y - p1.Y) < tol and abs(p1.Z - p0.Z) > tol:
            out.append(e)
    return out


def extrude(part, session, curves, seed_point, depth_start, depth_end, boolean,
            target=None, name="extrude"):
    """One extrude commit wrapped in its own undo mark."""
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


def export_step(part, step_path, log):
    """Export REAL solid geometry via the bundled CLI translator.

    DexManager.CreateStepCreator() writes an EMPTY shell under run_journal.exe, so
    it is not used here. See the skill's nxopen-api.md.
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
                # a locked sidecar is not fatal; the translator will overwrite it
                log.warn("cannot remove stale %s: %s" % (os.path.basename(f), exc))

    try:
        # cwd=out_dir: the translator also writes its configured sidecar log by a
        # RELATIVE path, so running it from the script directory scatters logs there.
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
# main
# -----------------------------------------------------------------------------
def main():
    started = time.time()

    # ---- spec + validation, before NX is touched at all -------------------
    try:
        spec, source = nxc.load_spec(sys.argv, DEFAULT_SPEC)
    except nxc.SpecError as exc:
        print("[FAIL] %s" % exc)
        sys.stdout.flush()
        sys.exit(1)

    params = spec["params"]
    problems = nxc.validate_part(spec)
    if problems:
        print("[FAIL] spec rejected, nothing was built:")
        for p in problems:
            print("       - %s" % p)
        sys.stdout.flush()
        sys.exit(1)

    nxc_paths = nxc.paths_for(spec)
    out_dir = nxc_paths["out_dir"]
    if not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir)
        except OSError as exc:
            print("[FAIL] cannot create out_dir %s: %s" % (out_dir, exc))
            sys.exit(1)

    use_log_file = bool(spec.get("export", {}).get("log_file", True))
    log = nxc.Log(nxc_paths["log"] if use_log_file else None)

    result = {
        "part": spec.get("part", "mounting_plate"),
        "part_name": spec["part_name"],
        "spec_source": source,
        "params": params,
        "files": {},
        "checks": {},
        "ugii_base_dir": os.environ.get("UGII_BASE_DIR", ""),
    }

    try:
        _build(spec, params, nxc_paths, log, result)
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        log.err("unhandled %s: %s" % (type(exc).__name__, exc))
        for line in traceback.format_exc().splitlines():
            log.info(line)
    finally:
        nxc.finish(log, nxc_paths["result"], result, started)


def _build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()
    log.info("=== build_plate (NX 2406) ===")
    log.info("spec from %s" % result["spec_source"])

    w = params["plate_w"]
    h = params["plate_h"]
    t = params["plate_t"]
    hole_d = params["hole_d"]
    hole_inset = params["hole_inset"]
    bore_d = params["bore_d"]
    fillet_r = params["fillet_r"]

    for stale in (p["prt"], p["step"]):
        if os.path.exists(stale):
            os.remove(stale)

    # ---- new metric part ---------------------------------------------------
    part = session.Parts.NewBaseDisplay(p["prt"], NXOpen.BasePart.Units.Millimeters)
    if isinstance(part, tuple):
        part = part[0]
    log.ok("new part: " + p["prt"])

    # ---- outer profile: four dumb lines, closed ----------------------------
    corners = [
        (NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Point3d(w, 0.0, 0.0)),
        (NXOpen.Point3d(w, 0.0, 0.0), NXOpen.Point3d(w, h, 0.0)),
        (NXOpen.Point3d(w, h, 0.0), NXOpen.Point3d(0.0, h, 0.0)),
        (NXOpen.Point3d(0.0, h, 0.0), NXOpen.Point3d(0.0, 0.0, 0.0)),
    ]
    rect = [part.Curves.CreateLine(a, b) for a, b in corners]
    log.ok("outer profile %.1f x %.1f mm" % (w, h))

    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
    plate_feat = extrude(part, session, rect, NXOpen.Point3d(0.0, 0.0, 0.0),
                         0.0, t, bb.Create, name="plate")
    body = plate_feat.GetBodies()[0]
    body.SetName("Plate")
    log.ok("extrude %.1f mm -> body '%s'" % (t, body.Name))

    # ---- holes: corners + centre bore, cut in one subtract extrude ---------
    holes = []
    if hole_d > 0:
        i = hole_inset
        for x, y in ((i, i), (w - i, i), (w - i, h - i), (i, h - i)):
            holes.append(circle(part, x, y, hole_d))
        log.ok("4 corner holes D%.1f, %.1f mm inset" % (hole_d, hole_inset))
    if bore_d > 0:
        holes.append(circle(part, w / 2.0, h / 2.0, bore_d))
        log.ok("central bore D%.1f" % bore_d)

    if holes:
        extrude(part, session, holes, NXOpen.Point3d(w / 2.0, h / 2.0, 0.0),
                -1.0, t + 1.0, bb.Subtract, target=body, name="holes")
        log.ok("holes cut")

    # ---- optional corner fillets, selected by geometry --------------------
    if fillet_r > 0:
        mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "fillet")
        verts = vertical_edges(body)
        log.chk("found %d vertical edge(s), expected 4" % len(verts))
        if len(verts) != 4:
            log.err("expected 4 vertical edges for the fillet, found %d" % len(verts))
        else:
            ebb = part.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
            col = part.ScCollectors.CreateCollector()
            col.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(verts)], False)
            ebb.AddChainset(col, str(fillet_r))
            ebb.CommitFeature()
            ebb.Destroy()
            session.UpdateManager.DoUpdate(mark)
            log.ok("fillet R%.1f" % fillet_r)

    # ---- self-check: geometry, not just "no exception" --------------------
    mp = part.MeasureManager.NewMassProperties(
        [part.UnitCollection.GetBase("Mass")], 0.99, [body])
    vol = mp.Volume
    n_faces = len(body.GetFaces())
    n_edges = len(body.GetEdges())
    exp_vol, exp_faces = nxc.part_metrics(spec)

    result["checks"]["volume"] = {"actual": round(vol, 6), "expected": round(exp_vol, 6),
                                 "delta": round(abs(vol - exp_vol), 6)}
    result["checks"]["faces"] = {"actual": n_faces, "expected": exp_faces}
    result["checks"]["edges"] = {"actual": n_edges}
    result["checks"]["bodies"] = len(list(part.Bodies))

    log.chk("volume %.3f mm^3  expected %.3f  delta %.4f"
            % (vol, exp_vol, abs(vol - exp_vol)))
    log.chk("faces=%d (expected %d)  edges=%d" % (n_faces, exp_faces, n_edges))

    if abs(vol - exp_vol) >= 1e-3:
        log.err("volume does not match the analytic value - the model is wrong")
    if n_faces != exp_faces:
        log.err("face count %d, expected %d - a feature did not apply as intended"
                % (n_faces, exp_faces))
    if result["checks"]["bodies"] != 1:
        log.err("expected exactly 1 solid body, found %d" % result["checks"]["bodies"])

    # ---- save --------------------------------------------------------------
    part.Save(NXOpen.BasePart.SaveComponents.TrueValue,
              NXOpen.BasePart.CloseAfterSave.FalseValue)
    if os.path.exists(p["prt"]):
        log.ok("saved " + p["prt"])
        result["files"]["prt"] = p["prt"]
        result["files"]["prt_bytes"] = os.path.getsize(p["prt"])
    else:
        log.err("save reported success but %s does not exist" % p["prt"])

    # ---- STEP --------------------------------------------------------------
    if spec.get("export", {}).get("step", True):
        if export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])

    log.info("DONE")


if __name__ == "__main__":
    main()
