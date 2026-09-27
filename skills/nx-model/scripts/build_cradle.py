# =============================================================================
#  NX Open Python journal  -  shaft cradle block  (StudyCADCAM 3D exercise 16)
#
#  A base plate with two rounded corners and two vertical holes, carrying a
#  cradle: an upper block, full length, with a semicircular groove across it for a
#  shaft, two ears with horizontal holes, and rounded top-outer corners.
#
#  This is the first builder that is NOT a single extrusion along Z:
#    * the cradle groove is cut along +Y, so its profile is drawn in XZ
#    * the groove profile contains an ARC, not only lines
#    * the corner rounds sit on edges that do not all run along Z
#
#  READING OF THE DRAWING IS PROVISIONAL. Every dimension I could not read with
#  certainty is a parameter, so a correction is a spec change and not a rewrite.
#  The ones to check against the drawing first:
#    base_hole_x / base_hole_y   hole position in the base is NOT dimensioned that I
#                               could find - assumed concentric with the R10 corners
#    top_setback                which side of the 40-deep base the 35-deep top is
#                               set back from (assumed the front, y=0 side)
#    ear_hole_z                 height of the horizontal ear holes (assumed mid-ear)
#    saddle_w vs saddle_r       see the note in build()
#
#  All dimensions are MILLIMETRES. Lengths reach the API as strings (see nx_journal).
# =============================================================================
import math
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
BASE_L = 80.0              # overall length (X)
BASE_W = 40.0              # overall depth (Y)
BASE_T = 10.0              # base plate thickness (Z)

CORNER_R = 10.0            # R10 on the two FRONT corners (y = 0), 0 = square

TOP_L = 80.0               # upper block length (X)
TOP_W = 35.0               # upper block depth (Y)
TOP_H = 20.0               # upper block height above the base (Z)
TOP_SETBACK = 5.0          # how far the upper block is set back from y = 0

SADDLE_W = 40.0            # width of the cradle opening (X)
SADDLE_R = 15.0            # cradle radius; the groove is tangent to the base top

EAR_R = 8.0                # R8 on the two upper outer corners, 0 = square

HOLE_D = 8.0               # every hole in this part is D8
BASE_HOLE_X = 10.0         # base hole centre, from each end
BASE_HOLE_Y = 10.0         # base hole centre, from the front edge
EAR_HOLE_X = 10.0          # ear hole centre, from each end
EAR_HOLE_Z = 20.0          # ear hole centre height

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "cradle_demo"

DEFAULT_SPEC = {
    "part_name": PART_NAME,
    "out_dir": OUT_DIR,
    "part": "shaft_cradle",
    "params": {
        "base_l": BASE_L,
        "base_w": BASE_W,
        "base_t": BASE_T,
        "corner_r": CORNER_R,
        "top_l": TOP_L,
        "top_w": TOP_W,
        "top_h": TOP_H,
        "top_setback": TOP_SETBACK,
        "saddle_w": SADDLE_W,
        "saddle_r": SADDLE_R,
        "ear_r": EAR_R,
        "hole_d": HOLE_D,
        "base_hole_x": BASE_HOLE_X,
        "base_hole_y": BASE_HOLE_Y,
        "ear_hole_x": EAR_HOLE_X,
        "ear_hole_z": EAR_HOLE_Z,
    },
    "export": {"step": True, "log_file": True},
}


def build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()
    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType

    base_l = params["base_l"]
    base_w = params["base_w"]
    base_t = params["base_t"]
    corner_r = params["corner_r"]
    top_l = params["top_l"]
    top_w = params["top_w"]
    top_h = params["top_h"]
    setback = params["top_setback"]
    sad_w = params["saddle_w"]
    sad_r = params["saddle_r"]
    ear_r = params["ear_r"]
    hole_d = params["hole_d"]
    bhx = params["base_hole_x"]
    bhy = params["base_hole_y"]
    ehx = params["ear_hole_x"]
    ehz = params["ear_hole_z"]

    part = nxj.new_metric_part(session, p["prt"], log)

    # ---- base plate -------------------------------------------------------
    base = nxj.closed_loop(part, [(0.0, 0.0), (base_l, 0.0), (base_l, base_w), (0.0, base_w)])
    feat = nxj.extrude(part, session, base, NXOpen.Point3d(base_l / 2.0, base_w / 2.0, 0.0),
                       0.0, base_t, bb.Create, name="base")
    body = feat.GetBodies()[0]
    body.SetName("Cradle")
    log.ok("base plate %.0f x %.0f x %.0f" % (base_l, base_w, base_t))
    nxj.stage_volume(part, body, log, "base")

    # ---- R10 on the two front corners -------------------------------------
    if corner_r > 0:
        front = [e for e in nxj.edges_along(body, "z")
                 if _edge_mid_y(e) < base_w / 2.0]
        log.chk("front vertical corners found: %d (expected 2)" % len(front))
        if len(front) != 2:
            log.err("expected 2 front vertical edges, found %d" % len(front))
        else:
            nxj.blend_edges(part, session, front, corner_r)
            log.ok("R%.1f on the two front corners" % corner_r)
            nxj.stage_volume(part, body, log, "corner_r")

    # ---- two D8 holes through the base ------------------------------------
    # Cut BEFORE the upper block goes on. If the block were already there, a base
    # hole with an overshoot would also gouge the block; and with the block on top
    # the hole is anyway only open from below.
    if hole_d > 0:
        base_holes = [nxj.circle(part, x, bhy, hole_d) for x in (bhx, base_l - bhx)]
        nxj.extrude(part, session, base_holes, NXOpen.Point3d(bhx, bhy, 0.0),
                    -1.0, base_t + 1.0, bb.Subtract, target=body, name="base_holes")
        log.ok("2 base holes D%.1f at y=%.1f" % (hole_d, bhy))
        nxj.stage_volume(part, body, log, "base_holes")

    # ---- upper block, united on top ---------------------------------------
    y0 = setback
    y1 = setback + top_w
    block = nxj.closed_loop(part, [(0.0, y0), (top_l, y0), (top_l, y1), (0.0, y1)])
    feat = nxj.extrude(part, session, block, NXOpen.Point3d(top_l / 2.0, (y0 + y1) / 2.0, 0.0),
                       base_t, base_t + top_h, bb.Unite, target=body, name="upper_block")
    body = feat.GetBodies()[0]
    log.ok("upper block %.0f x %.0f x %.0f from z=%.0f" % (top_l, top_w, top_h, base_t))
    nxj.stage_volume(part, body, log, "upper_block")

    # ---- the cradle groove, cut along +Y ----------------------------------
    # The groove is the opening rectangle MINUS the material that stays below the
    # arc. When saddle_w > 2*saddle_r the arc does not reach the opening's walls,
    # so there is a flat floor and a short vertical face on each side; with
    # saddle_w == 2*saddle_r the groove is a clean半圆 and those pieces vanish.
    if sad_r > 0:
        cx = base_l / 2.0
        z0 = base_t                       # groove floor level = base top
        ztop = base_t + top_h
        left, right = cx - sad_w / 2.0, cx + sad_w / 2.0
        yp = y0                           # profile plane

        def pt(x, z):
            return NXOpen.Point3d(x, yp, z)

        curves = []
        if sad_w > 2.0 * sad_r:
            curves.append(part.Curves.CreateLine(pt(left, z0), pt(cx - sad_r, z0)))
            curves.append(part.Curves.CreateLine(pt(cx - sad_r, z0), pt(cx - sad_r, z0 + sad_r)))
            curves.append(part.Curves.CreateLine(pt(cx + sad_r, z0 + sad_r), pt(cx + sad_r, z0)))
            curves.append(part.Curves.CreateLine(pt(cx + sad_r, z0), pt(right, z0)))
            log.warn("saddle_w=%.1f > 2*saddle_r=%.1f: the groove has a %.1f mm flat "
                     "floor and a vertical step on each side"
                     % (sad_w, 2 * sad_r, (sad_w - 2 * sad_r) / 2.0))
        # the lower half of the groove circle, from x=cx-r round through the
        # bottom back up to x=cx+r
        curves.append(nxj.arc(part, (cx, yp, z0 + sad_r), sad_r, 180.0, 360.0,
                              x_dir=(1.0, 0.0, 0.0), y_dir=(0.0, 0.0, 1.0)))
        curves.append(part.Curves.CreateLine(pt(left, ztop), pt(right, ztop)))
        curves.append(part.Curves.CreateLine(pt(right, ztop), pt(right, z0)))
        curves.append(part.Curves.CreateLine(pt(left, z0), pt(left, ztop)))
        log.ok("cradle groove: opening %.1f wide, R%.1f, cut along +Y" % (sad_w, sad_r))

        nxj.extrude(part, session, curves, pt(cx, (z0 + ztop) / 2.0),
                    -1.0, top_w + 1.0, bb.Subtract, target=body, name="saddle",
                    direction=(0.0, 1.0, 0.0))
        log.ok("groove cut through the %.1f mm depth" % top_w)
        nxj.stage_volume(part, body, log, "saddle")

    # ---- R8 on the two upper outer corners --------------------------------
    if ear_r > 0:
        top_edges = [e for e in nxj.edges_along(body, "y")
                     if abs(_edge_mid_z(e) - (base_t + top_h)) < 1e-6
                     and (_edge_mid_x(e) < top_l / 2.0 or _edge_mid_x(e) > top_l / 2.0)
                     and min(abs(_edge_mid_x(e)), abs(_edge_mid_x(e) - top_l)) < 1e-6]
        log.chk("upper outer edges found: %d (expected 2)" % len(top_edges))
        if len(top_edges) != 2:
            log.err("expected 2 upper outer edges, found %d" % len(top_edges))
        else:
            nxj.blend_edges(part, session, top_edges, ear_r)
            log.ok("R%.1f on the two upper outer corners" % ear_r)
            nxj.stage_volume(part, body, log, "ear_r")

    # ---- two D8 holes through the ears, along Y ---------------------------
    if hole_d > 0:
        ear_holes = [nxj.arc(part, (x, yp, ehz), hole_d / 2.0, 0.0, 360.0,
                             x_dir=(1.0, 0.0, 0.0), y_dir=(0.0, 0.0, 1.0))
                     for x in (ehx, top_l - ehx)]
        nxj.extrude(part, session, ear_holes, NXOpen.Point3d(ehx, yp, ehz),
                    -1.0, top_w + 1.0, bb.Subtract, target=body, name="ear_holes",
                    direction=(0.0, 1.0, 0.0))
        log.ok("2 ear holes D%.1f at z=%.1f, along Y" % (hole_d, ehz))
        nxj.stage_volume(part, body, log, "ear_holes")

    nxj.check_geometry(part, body, spec, log, result)

    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


def _edge_mid_y(edge):
    p0, p1 = edge.GetVertices()
    return (p0.Y + p1.Y) / 2.0


def _edge_mid_z(edge):
    p0, p1 = edge.GetVertices()
    return (p0.Z + p1.Z) / 2.0


def _edge_mid_x(edge):
    p0, p1 = edge.GetVertices()
    return (p0.X + p1.X) / 2.0


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_cradle (NX 2406)")
