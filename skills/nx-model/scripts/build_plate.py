# =============================================================================
#  NX Open Python journal  -  parametric mounting plate
#  Verified on NX 2406 (built, measured, and STEP-exported).
#
#  RUN
#    headless, defaults:  "$UGII_BASE_DIR/NXBIN/run_journal.exe" build_plate.py
#    headless, from spec: ".../run_journal.exe" build_plate.py -args my_spec.json
#    in the GUI:          Developer > Play
#
#  Then show the result in the user's NX:
#      python show_in_nx.py my_spec.json
#
#  Two ways to set dimensions, same result:
#    1. edit the parameter block below  (running with no arguments uses it)
#    2. pass a JSON spec file with -args, which overrides any of those values
#
#  All dimensions are MILLIMETRES. Lengths reach the API as strings via
#  RightHandSide / SetFormula - assigning a float to a length's .Value applies a
#  silent 25.4x unit conversion.
#
#  Geometry only lives here; session handling, the self-check, saving and the STEP
#  export are in nx_journal.py, shared with the other part builders.
#
#  Exits non-zero and writes <part>.result.json if anything failed. A journal that
#  reports a problem can no longer look like a success.
# =============================================================================
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

import nx_common as nxc
import nx_journal as nxj

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


def build(spec, params, p, log, result):
    """Rectangle -> extrude -> subtract the holes -> optional corner fillets."""
    session = NXOpen.Session.GetSession()

    w = params["plate_w"]
    h = params["plate_h"]
    t = params["plate_t"]
    hole_d = params["hole_d"]
    hole_inset = params["hole_inset"]
    bore_d = params["bore_d"]
    fillet_r = params["fillet_r"]

    part = nxj.new_metric_part(session, p["prt"], log)

    # ---- outer profile: a closed rectangle ---------------------------------
    loop = nxj.closed_loop(part, [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)])
    log.ok("outer profile %.1f x %.1f mm" % (w, h))

    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
    plate_feat = nxj.extrude(part, session, loop, NXOpen.Point3d(0.0, 0.0, 0.0),
                             0.0, t, bb.Create, name="plate")
    body = plate_feat.GetBodies()[0]
    body.SetName("Plate")
    log.ok("extrude %.1f mm -> body '%s'" % (t, body.Name))

    # ---- holes: corners + centre bore, cut in ONE subtract extrude ---------
    holes = []
    centres = []
    if hole_d > 0:
        i = hole_inset
        for x, y in ((i, i), (w - i, i), (w - i, h - i), (i, h - i)):
            holes.append(nxj.circle(part, x, y, hole_d))
            centres.append((x, y))
        log.ok("4 corner holes D%.1f, %.1f mm inset" % (hole_d, hole_inset))
    if bore_d > 0:
        holes.append(nxj.circle(part, w / 2.0, h / 2.0, bore_d))
        centres.append((w / 2.0, h / 2.0))
        log.ok("central bore D%.1f" % bore_d)

    if holes:
        # seed the chain on a real hole centre rather than assuming the centre bore
        # exists - with bore_d=0 the plate centre is not on any curve
        seed = NXOpen.Point3d(centres[0][0], centres[0][1], 0.0)
        nxj.extrude(part, session, holes, seed, -1.0, t + 1.0, bb.Subtract,
                    target=body, name="holes")
        log.ok("holes cut")

    # ---- optional corner fillets, selected by geometry --------------------
    if fillet_r > 0:
        verts = nxj.vertical_edges(body)
        log.chk("found %d vertical edge(s), expected 4" % len(verts))
        if len(verts) != 4:
            log.err("expected 4 vertical edges for the fillet, found %d" % len(verts))
        else:
            nxj.blend_edges(part, session, verts, fillet_r)
            log.ok("fillet R%.1f" % fillet_r)

    # ---- self-check: geometry, not just "no exception" --------------------
    nxj.check_geometry(part, body, spec, log, result)

    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_plate (NX 2406)")
