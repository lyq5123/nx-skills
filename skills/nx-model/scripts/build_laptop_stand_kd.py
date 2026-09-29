# =============================================================================
#  NX Open Python journal  -  laptop stand knock-down KIT (piece builder)
#
#  One journal builds whichever piece the spec's "piece" names:
#    plate  top plate + lip, D9x3 head pockets in the TOP face, D5.5 clearance
#           holes through, cable hole and R3 blends kept from the mono-block
#    rib    one side rib (centred on y=0; the assembly places it twice), with
#           the D36 lightening hole and two D5.5x10 pilots cut normal to the
#           incline from the rib's top face
#    screw  one M5 pan-head screw, head top at the origin, shank along -Z
#
#  build_laptop_stand_kit.py then assembles the three files. The joint rules
#  (stack clearance, pocket/tap fit, hole-vs-hole clearances) live in the
#  recipe's validate; the analytic volumes it is checked against live in the
#  recipe's metrics - both in nx_recipes.py, shared with verify_part.py.
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

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")

DEFAULT_SPEC = {
    "part_name": "laptop_stand_v3_plate",
    "out_dir": OUT_DIR,
    "part": "laptop_stand_kd",
    "params": {
        "piece": "plate",
        "width": 280.0, "run": 250.0, "angle": 18.0,
        "plate_t": 8.0, "rib_t": 10.0, "front_h": 12.0,
        "lip_len": 15.0, "lip_h": 15.0,
        "rib_hole_d": 36.0, "cable_hole_d": 30.0, "blend_r": 3.0,
        "screw_u1": 60.0, "screw_u2": 200.0,
    },
    "export": {"step": True, "log_file": True},
}


def xz_loop(part, points):
    pts = [NXOpen.Point3d(x, 0.0, z) for x, z in points]
    n = len(pts)
    return [part.Curves.CreateLine(pts[i], pts[(i + 1) % n]) for i in range(n)]


def incline_circle(part, params, u, y, dia, v_offset=0.0):
    """A circle of `dia` in the plane parallel to the incline at v=v_offset,
    centred at (u, y) in the incline frame. Returns (curve, centre_point)."""
    a = math.radians(params["angle"])
    ca, sa = math.cos(a), math.sin(a)
    cx = u * ca - v_offset * sa
    cy = y
    cz = params["front_h"] + u * sa + v_offset * ca
    curve = nxj.arc(part, (cx, cy, cz), dia / 2.0, 0.0, 360.0,
                    x_dir=(ca, 0.0, sa), y_dir=(0.0, 1.0, 0.0))
    return curve, NXOpen.Point3d(cx, cy, cz)


def build_plate(params, session, part, log, bb):
    w = params["width"]
    rn = params["run"]
    a = math.radians(params["angle"])
    pt = params["plate_t"]
    fh = params["front_h"]
    ll = params["lip_len"]
    lh = params["lip_h"]
    cd = params.get("cable_hole_d") or 0.0
    br = params.get("blend_r") or 0.0
    ca, sa, ta = math.cos(a), math.sin(a), math.tan(a)

    A = (0.0, fh)
    B = (rn, fh + rn * ta)
    nx_pt = (-sa, ca)
    dx = (ca, sa)

    def off(p0, k, u):
        return (p0[0] + k[0] * u, p0[1] + k[1] * u)

    plate_pts = [A, B, off(B, nx_pt, pt), off(A, nx_pt, pt)]
    lip_base = off(A, nx_pt, pt)
    lip_pts = [lip_base, off(lip_base, dx, ll),
               off(off(lip_base, dx, ll), nx_pt, lh), off(lip_base, nx_pt, lh)]

    feat = nxj.extrude(part, session, xz_loop(part, plate_pts),
                       NXOpen.Point3d(A[0], 0.0, A[1]), 0.0, w, bb.Create,
                       direction=(0.0, 1.0, 0.0), name="plate")
    body = feat.GetBodies()[0]
    body.SetName("StandPlate")
    feat = nxj.extrude(part, session, xz_loop(part, lip_pts),
                       NXOpen.Point3d(lip_pts[0][0], 0.0, lip_pts[0][1]),
                       0.0, w, bb.Unite, target=body,
                       direction=(0.0, 1.0, 0.0), name="lip")
    body = feat.GetBodies()[0]
    log.ok("plate + lip united")

    if cd > 0:
        curve, centre = incline_circle(part, params, 0.8 * rn / ca, w / 2.0, cd)
        feat = nxj.extrude(part, session, [curve], centre, -1.0, pt + 1.0,
                           bb.Subtract, target=body, direction=(-sa, 0.0, ca),
                           name="cable_hole")
        body = feat.GetBodies()[0]
        log.ok("cable hole D%.1f cut" % cd)

    if br > 0:
        # lip's top edge only - see the recipe: the plate-top side blends would
        # sit exactly where the head pockets are cut
        tol = 1e-5

        def uv(p):
            return (p.X * ca + (p.Z - fh) * sa, -p.X * sa + (p.Z - fh) * ca, p.Y)

        lip_top = pt + lh
        edges = []
        for e in body.GetEdges():
            pts = [uv(v) for v in e.GetVertices()]
            if all(abs(u) < tol and abs(v - lip_top) < tol for u, v, _y in pts):
                edges.append(e)
        log.chk("found %d edge(s) to blend, expected 1" % len(edges))
        if len(edges) != 1:
            log.err("blend edge selection found %d edges, expected 1" % len(edges))
        else:
            feat = nxj.blend_edges(part, session, edges, br)
            body = feat.GetBodies()[0]
            log.ok("blend R%.1f applied on the lip's top edge" % br)

    # screw joints: D9x3 head pockets in the TOP face, then D5.5 through
    y = nxr._kd_screw_y(params)
    hd = nxr._kd_hole_dia()
    cb_curves, cb_seeds = [], []
    th_curves, th_seeds = [], []
    for u in (params["screw_u1"], params["screw_u2"]):
        for yy in (y, w - y):
            c, s = incline_circle(part, params, u, yy, nxr.KD_CB_D, v_offset=pt)
            cb_curves.append(c)
            cb_seeds.append(s)
            c, s = incline_circle(part, params, u, yy, hd)
            th_curves.append(c)
            th_seeds.append(s)
    feat = nxj.extrude(part, session, cb_curves, cb_seeds[0], -1.0,
                       nxr.KD_CB_H, bb.Subtract, target=body,
                       direction=(sa, 0.0, -ca), name="head_pockets")
    body = feat.GetBodies()[0]
    log.ok("4 head pockets D%.1fx%.1f cut" % (nxr.KD_CB_D, nxr.KD_CB_H))
    feat = nxj.extrude(part, session, th_curves, th_seeds[0], -1.0, pt + 1.0,
                       bb.Subtract, target=body, direction=(-sa, 0.0, ca),
                       name="clearance_holes")
    body = feat.GetBodies()[0]
    log.ok("4 clearance holes D%.1f cut" % hd)
    return body


def build_rib(params, session, part, log, bb):
    """One rib, CENTRED on y=0 (the assembly places it at y=rib_t/2 and
    width-rib_t/2). Lightening hole through, two pilots cut normal to the
    incline from the rib's top face."""
    w = params["width"]
    rn = params["run"]
    a = math.radians(params["angle"])
    rt = params["rib_t"]
    fh = params["front_h"]
    rd = params.get("rib_hole_d") or 0.0
    ca, sa, ta = math.cos(a), math.sin(a), math.tan(a)

    A = (0.0, fh)
    B = (rn, fh + rn * ta)
    rib_pts = [(0.0, 0.0), (rn, 0.0), B, A]
    half = rt / 2.0

    feat = nxj.extrude(part, session, xz_loop(part, rib_pts),
                       NXOpen.Point3d(0.0, 0.0, 0.0), -half, half, bb.Create,
                       direction=(0.0, 1.0, 0.0), name="rib")
    body = feat.GetBodies()[0]
    body.SetName("StandRib")
    log.ok("rib trapezoid %.1f x %.1f mm extruded, centred on y=0" % (rn, rt))

    if rd > 0:
        hx, hz = nxr.laptop_stand_rib_hole(params)
        hole = nxj.arc(part, (hx, 0.0, hz), rd / 2.0, 0.0, 360.0,
                       x_dir=(1.0, 0.0, 0.0), y_dir=(0.0, 0.0, 1.0))
        feat = nxj.extrude(part, session, [hole], NXOpen.Point3d(hx, 0.0, hz),
                           -(half + 1.0), half + 1.0, bb.Subtract, target=body,
                           direction=(0.0, 1.0, 0.0), name="lightening_hole")
        body = feat.GetBodies()[0]
        log.ok("lightening hole D%.1f cut" % rd)

    # pilots: cut DOWNWARD (along -normal) from the rib's top face, in the
    # rib's own frame the screw sits at local y = +0.5 (mid-rib + 0.5)
    hd = nxr._kd_hole_dia()
    y_local = 0.5
    for u in (params["screw_u1"], params["screw_u2"]):
        curve, centre = incline_circle(part, params, u, y_local, hd)
        feat = nxj.extrude(part, session, [curve], centre, 0.0,
                           nxr.KD_TAP_DEPTH, bb.Subtract, target=body,
                           direction=(sa, 0.0, -ca), name="pilot_u%.0f" % u)
        body = feat.GetBodies()[0]
    log.ok("2 pilots D%.1f x %.1f cut normal to the incline" % (hd, nxr.KD_TAP_DEPTH))
    return body


def build_screw(params, session, part, log, bb):
    """M5 pan-head screw: head top at the origin, shank along -Z. Threads are
    not modelled; the shank is the nominal D5."""
    head_d, head_h = nxr.KD_HEAD_D, nxr.KD_HEAD_H
    sd, slen = nxr.KD_SCREW_D, nxr.KD_SCREW_LEN
    af, dep = nxr.KD_SOCKET_AF, nxr.KD_SOCKET_DEP

    feat = nxj.extrude(part, session,
                       [nxj.circle(part, 0.0, 0.0, head_d, z=0.0)],
                       NXOpen.Point3d(0.0, 0.0, 0.0), -head_h, 0.0, bb.Create,
                       name="head")
    body = feat.GetBodies()[0]
    body.SetName("StandScrew")
    feat = nxj.extrude(part, session, [nxj.circle(part, 0.0, 0.0, sd, z=0.0)],
                       NXOpen.Point3d(0.0, 0.0, 0.0),
                       -(head_h + slen), -head_h, bb.Unite, target=body,
                       name="shank")
    body = feat.GetBodies()[0]
    log.ok("head D%.1f x %.1f + shank D%.1f x %.1f united" % (head_d, head_h, sd, slen))

    # hex socket, across flats `af`, depth `dep`, from the head top
    circ_r = af / math.sqrt(3.0)
    hex_pts = [(circ_r * math.cos(math.radians(60.0 * i)),
                circ_r * math.sin(math.radians(60.0 * i))) for i in range(6)]
    hex_loop = []
    pts = [NXOpen.Point3d(x, y, 0.0) for x, y in hex_pts]
    for i in range(6):
        hex_loop.append(part.Curves.CreateLine(pts[i], pts[(i + 1) % 6]))
    feat = nxj.extrude(part, session, hex_loop,
                       NXOpen.Point3d(0.0, 0.0, 0.0), -dep, 0.0, bb.Subtract,
                       target=body, name="hex_socket")
    body = feat.GetBodies()[0]
    log.ok("hex socket AF%.1f x %.1f cut" % (af, dep))
    return body


def build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()
    part = nxj.new_metric_part(session, p["prt"], log)
    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType
    piece = params["piece"]
    log.info("piece: %s" % piece)

    if piece == "plate":
        body = build_plate(params, session, part, log, bb)
    elif piece == "rib":
        body = build_rib(params, session, part, log, bb)
    else:
        body = build_screw(params, session, part, log, bb)

    nxj.check_geometry(part, body, spec, log, result)
    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_laptop_stand_kd (NX 2406)")
