# =============================================================================
#  NX Open Python journal  -  generic extruded profile
#
#  Any straight-sided part: a closed polygon extruded to a thickness, with circular
#  through-holes. Use this for a drawing that is not one of the named parts -
#  brackets, covers, gussets, channels, link plates and most flat components are
#  exactly this shape.
#
#  The volume is exact (shoelace area x thickness - hole cylinders), so the same
#  numeric verification applies as for every other recipe.
#
#  RUN
#    ".../run_journal.exe" build_profile.py                       # built-in defaults
#    ".../run_journal.exe" build_profile.py -args my_spec.json    # from a spec
#  Then:  python show_in_nx.py my_spec.json
#
#  SPEC SHAPE (structured, unlike the named recipes)
#    {
#      "part": "extruded_profile",
#      "params": {
#        "points":    [[0,0],[80,0],[80,12],[10,12],[10,60],[0,60]],
#        "thickness": 40,
#        "holes":     [[20,6,6],[60,6,6]]
#      }
#    }
#  The outline is taken as CLOSED - do not repeat the first point at the end.
#  Straight edges only: a curved outline needs a named recipe with its own formula.
# =============================================================================
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

import nx_common as nxc
import nx_journal as nxj

# -----------------------------------------------------------------------------
# defaults (mm) - the L-bracket outline, so the no-argument run builds something
# meaningful and comparable with build_bracket.py
# -----------------------------------------------------------------------------
POINTS = [[0.0, 0.0], [80.0, 0.0], [80.0, 12.0], [10.0, 12.0], [10.0, 60.0], [0.0, 60.0]]
THICKNESS = 40.0
HOLES = [[20.0, 6.0, 6.0], [60.0, 6.0, 6.0]]

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "extruded_profile_demo"

DEFAULT_SPEC = {
    "part_name": PART_NAME,
    "out_dir": OUT_DIR,
    "part": "extruded_profile",
    "params": {
        "points": POINTS,
        "thickness": THICKNESS,
        "holes": HOLES,
    },
    "export": {"step": True, "log_file": True},
}


def build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()

    points = [(float(x), float(y)) for x, y in params["points"]]
    thickness = float(params["thickness"])
    holes = [(float(h[0]), float(h[1]), float(h[2]))
             for h in (params.get("holes") or []) if float(h[2]) > 0]

    part = nxj.new_metric_part(session, p["prt"], log)
    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType

    # ---- the outline: one closed loop through the given points -------------
    loop = nxj.closed_loop(part, points)
    log.ok("outline: %d points, %.1f mm thick" % (len(points), thickness))

    # seed the chain from the centroid of the first triangle of the outline - it is
    # inside a simple polygon, unlike (0,0) which may sit outside a concave one
    sx = sum(x for x, _y in points) / float(len(points))
    sy = sum(y for _x, y in points) / float(len(points))
    feat = nxj.extrude(part, session, loop, NXOpen.Point3d(sx, sy, 0.0),
                       0.0, thickness, bb.Create, name="profile")
    body = feat.GetBodies()[0]
    body.SetName("Profile")
    log.ok("extrude -> body '%s'" % body.Name)

    # ---- through-holes, cut in ONE subtract extrude ------------------------
    if holes:
        curves = [nxj.circle(part, hx, hy, dia) for hx, hy, dia in holes]
        nxj.extrude(part, session, curves, NXOpen.Point3d(holes[0][0], holes[0][1], 0.0),
                    -1.0, thickness + 1.0, bb.Subtract, target=body, name="holes")
        log.ok("%d through-hole(s) cut" % len(holes))

    nxj.check_geometry(part, body, spec, log, result)

    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_profile (NX 2406)")
