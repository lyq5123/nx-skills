# =============================================================================
#  NX Open Python journal  -  inclined laptop stand
#  Built on the same plumbing as build_plate.py (NX 2406).
#
#  RUN
#    headless, defaults:  "$UGII_BASE_DIR/NXBIN/run_journal.exe" build_laptop_stand.py
#    headless, from spec: ".../run_journal.exe" build_laptop_stand.py -args my_spec.json
#    then show it:        python show_in_nx.py my_spec.json
#
#  Geometry: three profiles drawn in the XZ plane (the stand's side silhouette)
#  and extruded along +Y, united into one solid:
#    * the plate  - a band of thickness plate_t lying on the incline line,
#    * the lip    - a lip_len x lip_h band standing normal to the plate at its
#                   front edge (it is what stops the laptop sliding off),
#    * two ribs   - the ground-to-incline trapezoids at each end of the width.
#  The unions are face-to-face (rib tops touch the plate underside, the lip base
#  touches the plate top), so the analytic volume in nx_recipes carries no
#  overlap term.
#
#  Optional features (spec params, default 0 = off - see the recipe comment):
#    rib_hole_d   one lightening/handle hole through each rib
#    cable_hole_d a hole normal to the plate near its rear, for cables
#    blend_r      R on the lip top edge and both plate-top side edges
#
#  All dimensions are MILLIMETRES, `angle` in degrees. Lengths reach the API as
#  strings via RightHandSide - assigning a float to a length's .Value applies a
#  silent 25.4x unit conversion.
# =============================================================================
import math
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

import nx_common as nxc
import nx_journal as nxj
import nx_recipes as nxr

# -----------------------------------------------------------------------------
# parameters (mm, angle in degrees) - the defaults used when no spec is given
# -----------------------------------------------------------------------------
WIDTH = 280.0             # overall Y width
RUN = 250.0               # horizontal front-to-back depth of the incline
ANGLE = 18.0              # incline above horizontal, degrees
PLATE_T = 8.0             # top plate thickness (normal to the incline)
RIB_T = 6.0               # side rib thickness
FRONT_H = 12.0            # rib height at the front edge = plate underside there
LIP_LEN = 15.0            # stop lip length along the incline
LIP_H = 15.0              # stop lip height above the plate surface
RIB_HOLE_D = 36.0         # lightening/handle hole through each rib, 0 = skip
CABLE_HOLE_D = 30.0       # cable hole normal to the plate, 0 = skip
BLEND_R = 3.0             # lip top + plate top side edges, 0 = skip

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "laptop_stand"

DEFAULT_SPEC = {
    "part_name": PART_NAME,
    "out_dir": OUT_DIR,
    "part": "laptop_stand",
    "params": {
        "width": WIDTH,
        "run": RUN,
        "angle": ANGLE,
        "plate_t": PLATE_T,
        "rib_t": RIB_T,
        "front_h": FRONT_H,
        "lip_len": LIP_LEN,
        "lip_h": LIP_H,
        "rib_hole_d": RIB_HOLE_D,
        "cable_hole_d": CABLE_HOLE_D,
        "blend_r": BLEND_R,
    },
    "export": {"step": True, "log_file": True},
}


def xz_loop(part, points):
    """A closed polyline in the XZ plane (y=0) through (x, z) pairs."""
    pts = [NXOpen.Point3d(x, 0.0, z) for x, z in points]
    n = len(pts)
    return [part.Curves.CreateLine(pts[i], pts[(i + 1) % n]) for i in range(n)]


def build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()

    w = params["width"]
    rn = params["run"]
    a = math.radians(params["angle"])
    pt = params["plate_t"]
    rt = params["rib_t"]
    fh = params["front_h"]
    ll = params["lip_len"]
    lh = params["lip_h"]
    rd = params.get("rib_hole_d") or 0.0
    cd = params.get("cable_hole_d") or 0.0
    br = params.get("blend_r") or 0.0

    # ---- profile geometry in XZ --------------------------------------------
    ca, sa, ta = math.cos(a), math.sin(a), math.tan(a)
    A = (0.0, fh)                       # incline line, front end (plate underside)
    B = (rn, fh + rn * ta)              # incline line, rear end
    nx_pt = (-sa, ca)                   # unit normal to the incline, pointing up
    dx = (ca, sa)                       # unit vector along the incline

    def off(pt0, k, u):                 # pt0 + u * k, as (x, z)
        return (pt0[0] + k[0] * u, pt0[1] + k[1] * u)

    plate_pts = [A, B, off(B, nx_pt, pt), off(A, nx_pt, pt)]
    lip_base = off(A, nx_pt, pt)
    lip_pts = [lip_base, off(lip_base, dx, ll),
               off(off(lip_base, dx, ll), nx_pt, lh), off(lip_base, nx_pt, lh)]
    rib_pts = [(0.0, 0.0), (rn, 0.0), B, A]

    part = nxj.new_metric_part(session, p["prt"], log)
    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType

    # ---- plate: band on the incline, full width ----------------------------
    plate_loop = xz_loop(part, plate_pts)
    feat = nxj.extrude(part, session, plate_loop,
                       NXOpen.Point3d(A[0], 0.0, A[1]), 0.0, w, bb.Create,
                       direction=(0.0, 1.0, 0.0), name="plate")
    body = feat.GetBodies()[0]
    body.SetName("LaptopStand")
    log.ok("plate %.1f x %.1f mm at %.1f deg -> body '%s'"
           % (rn / ca, w, math.degrees(a), body.Name))

    # ---- stop lip: stands on the plate's front edge ------------------------
    lip_loop = xz_loop(part, lip_pts)
    feat = nxj.extrude(part, session, lip_loop,
                       NXOpen.Point3d(lip_pts[0][0], 0.0, lip_pts[0][1]),
                       0.0, w, bb.Unite, target=body,
                       direction=(0.0, 1.0, 0.0), name="lip")
    body = feat.GetBodies()[0]
    log.ok("lip %.1f x %.1f mm united" % (ll, lh))

    # ---- two side ribs ------------------------------------------------------
    for tag, y0 in (("front", 0.0), ("rear", w - rt)):
        rib_loop = xz_loop(part, rib_pts)
        feat = nxj.extrude(part, session, rib_loop,
                           NXOpen.Point3d(0.0, 0.0, 0.0),
                           y0, y0 + rt, bb.Unite, target=body,
                           direction=(0.0, 1.0, 0.0), name="rib_" + tag)
        body = feat.GetBodies()[0]
        log.ok("rib %s united (y %.1f..%.1f)" % (tag, y0, y0 + rt))

    # ---- lightening/handle hole through each rib ---------------------------
    if rd > 0:
        hx, hz = nxr.laptop_stand_rib_hole(params)
        hole = nxj.arc(part, (hx, 0.0, hz), rd / 2.0, 0.0, 360.0,
                       x_dir=(1.0, 0.0, 0.0), y_dir=(0.0, 0.0, 1.0))
        feat = nxj.extrude(part, session, [hole],
                           NXOpen.Point3d(hx, 0.0, hz), -1.0, w + 1.0,
                           bb.Subtract, target=body,
                           direction=(0.0, 1.0, 0.0), name="rib_holes")
        body = feat.GetBodies()[0]
        log.ok("rib holes D%.1f cut at x=%.1f" % (rd, hx))

    # ---- cable hole, normal to the plate near its rear ---------------------
    if cd > 0:
        centre, axis, radius = nxr.laptop_stand_cable_hole(params)
        hole = nxj.arc(part, centre, radius, 0.0, 360.0,
                       x_dir=(ca, 0.0, sa), y_dir=(0.0, 1.0, 0.0))
        feat = nxj.extrude(part, session, [hole],
                           NXOpen.Point3d(*centre), -1.0, pt + 1.0,
                           bb.Subtract, target=body,
                           direction=axis, name="cable_hole")
        body = feat.GetBodies()[0]
        log.ok("cable hole D%.1f cut at (%.1f, %.1f, %.1f)"
               % (cd, centre[0], centre[1], centre[2]))

    # ---- blends: lip top edge + both plate-top side edges ------------------
    if br > 0:
        # classify edges by the (u, v) incline-frame coordinates of their end
        # vertices: u along the incline, v normal to it. The lip's top-front
        # edge is the only edge lying at (u=0, v=plate_t+lip_h); the plate top
        # keeps exactly two side edges at v=plate_t, at y=0 and y=width.
        tol = 1e-5

        def uv(p):
            return (p.X * ca + (p.Z - fh) * sa, -p.X * sa + (p.Z - fh) * ca, p.Y)

        def on_side(y):
            return abs(y) < tol or abs(y - w) < tol

        lip_top = pt + lh
        edges = []
        for e in body.GetEdges():
            pts = [uv(v) for v in e.GetVertices()]
            if all(abs(u) < tol and abs(v - lip_top) < tol for u, v, _y in pts):
                edges.append(e)
            elif (all(abs(v - pt) < tol for _u, v, _y in pts)
                  and (all(abs(y) < tol for _u, _v, y in pts)
                       or all(abs(y - w) < tol for _u, _v, y in pts))):
                # both ends on the SAME side - otherwise the plate top's own
                # front and rear boundary edges (which run across the width,
                # one end at y=0 and the other at y=width) would match too
                edges.append(e)
        log.chk("found %d edge(s) to blend, expected 3" % len(edges))
        if len(edges) != 3:
            log.err("edge selection for the blends found %d edges, expected 3"
                    % len(edges))
        else:
            feat = nxj.blend_edges(part, session, edges, br)
            body = feat.GetBodies()[0]
            log.ok("blends R%.1f applied on 3 edges" % br)

    # ---- self-check: volume and face count against the recipe -------------
    nxj.check_geometry(part, body, spec, log, result)

    # placement check: the analytic bounding box from the same recipe. Body has
    # no GetBoundingBox at runtime on 2406, so take the extremes over the edge
    # vertices - exact here because every face of this solid is planar.
    exp_min, exp_max = nxr.laptop_stand_bbox(params)
    got = [1e30, 1e30, 1e30, -1e30, -1e30, -1e30]
    for e in body.GetEdges():
        for v in e.GetVertices():
            for k, c in enumerate((v.X, v.Y, v.Z)):
                got[k] = min(got[k], c)
                got[k + 3] = max(got[k + 3], c)
    got = tuple(got)
    exp = (exp_min[0], exp_min[1], exp_min[2], exp_max[0], exp_max[1], exp_max[2])
    result["checks"]["bbox"] = {"actual": [round(v, 6) for v in got],
                                "expected": [round(v, 6) for v in exp]}
    log.chk("bbox min (%.3f, %.3f, %.3f) expected (%.3f, %.3f, %.3f)"
            % (got[:3] + exp[:3]))
    log.chk("bbox max (%.3f, %.3f, %.3f) expected (%.3f, %.3f, %.3f)"
            % (got[3:] + exp[3:]))
    for i, axis in enumerate(("X min", "Y min", "Z min", "X max", "Y max", "Z max")):
        # with blends on, the true extreme can lie on a blend cylinder where no
        # vertex sits, so the vertex sampling may miss it by up to br*(1-cos a)
        slack = br * (1.0 - ca) + 1e-3 if br > 0 else 1e-3
        if abs(got[i] - exp[i]) > slack:
            log.err("bounding box %s drifted: got %.4f, expected %.4f"
                    % (axis, got[i], exp[i]))

    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_laptop_stand (NX 2406)")
