# =============================================================================
#  NX Open Python journal  -  L bracket
#
#  An L-shaped profile extruded across its width, with two through-holes along the
#  extrusion direction for mounting. The profile is one closed loop of six lines -
#  the shape to reach for when the profile is not a rectangle, and it needs no
#  sketcher.
#
#  Verified on NX 2406: 80/12/10/60 wide 40, two D6 holes inset 20 gives
#  55338.053 mm^3, 10 faces (6 profile sides + 2 ends + 2 hole cylinders).
#
#  RUN
#    ".../run_journal.exe" build_bracket.py                       # built-in defaults
#    ".../run_journal.exe" build_bracket.py -args my_spec.json    # from a spec
#  Then:  python show_in_nx.py my_spec.json
#
#  All dimensions are MILLIMETRES; lengths reach the API as strings (see nx_journal).
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
BASE_L = 80.0              # horizontal leg length (X)
BASE_T = 12.0              # horizontal leg thickness (Y)
WALL_T = 10.0              # vertical leg thickness (X)
TOTAL_H = 60.0             # overall height of the vertical leg (Y)
WIDTH = 40.0               # extrusion width (Z)

HOLE_D = 6.0               # mounting hole diameter, 0 = none
HOLE_INSET_X = 20.0        # hole centre distance from the free end and from the wall

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "l_bracket_demo"

DEFAULT_SPEC = {
    "part_name": PART_NAME,
    "out_dir": OUT_DIR,
    "part": "l_bracket",
    "params": {
        "base_l": BASE_L,
        "base_t": BASE_T,
        "wall_t": WALL_T,
        "total_h": TOTAL_H,
        "width": WIDTH,
        "hole_d": HOLE_D,
        "hole_inset_x": HOLE_INSET_X,
    },
    "export": {"step": True, "log_file": True},
}


def build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()

    base_l = params["base_l"]
    base_t = params["base_t"]
    wall_t = params["wall_t"]
    total_h = params["total_h"]
    width = params["width"]
    hole_d = params["hole_d"]
    inset_x = params["hole_inset_x"]

    part = nxj.new_metric_part(session, p["prt"], log)
    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType

    # ---- the L profile: one closed loop of six lines -----------------------
    loop = nxj.closed_loop(part, [
        (0.0, 0.0),
        (base_l, 0.0),
        (base_l, base_t),
        (wall_t, base_t),
        (wall_t, total_h),
        (0.0, total_h),
    ])
    area = base_l * base_t + wall_t * (total_h - base_t)
    log.ok("L profile: 6 lines, %.1f x %.1f mm, area %.1f mm^2"
           % (base_l, total_h, area))

    feat = nxj.extrude(part, session, loop, NXOpen.Point3d(base_t / 2.0, base_t / 2.0, 0.0),
                       0.0, width, bb.Create, name="bracket")
    body = feat.GetBodies()[0]
    body.SetName("L_Bracket")
    log.ok("extrude %.1f mm -> body '%s'" % (width, body.Name))

    # ---- two mounting holes, through the extrusion -------------------------
    if hole_d > 0:
        y = base_t / 2.0                       # centred across the leg thickness
        holes = [nxj.circle(part, x, y, hole_d)
                 for x in (inset_x, base_l - inset_x)]
        nxj.extrude(part, session, holes, NXOpen.Point3d(inset_x, y, 0.0),
                    -1.0, width + 1.0, bb.Subtract, target=body, name="holes")
        log.ok("2 mounting holes D%.1f at x=%.1f and %.1f"
               % (hole_d, inset_x, base_l - inset_x))

    nxj.check_geometry(part, body, spec, log, result)

    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_bracket (NX 2406)")
