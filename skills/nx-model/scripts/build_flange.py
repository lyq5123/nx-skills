# =============================================================================
#  NX Open Python journal  -  circular flange
#
#  Disc -> central bore + bolt circle (one subtract) -> chamfer both outer rims.
#  Verified on NX 2406: OD160 / ID60 / t20 / BCD120 / 6x D14 / C2 gives
#  325108.763 mm^3, 12 faces, 8 cylindrical faces (STEP: 8 cylinders + 2 cones).
#
#  RUN
#    ".../run_journal.exe" build_flange.py                        # built-in defaults
#    ".../run_journal.exe" build_flange.py -args my_spec.json     # from a spec
#  Then:  python show_in_nx.py my_spec.json
#
#  All dimensions are MILLIMETRES; lengths reach the API as strings (see nx_journal).
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
OD = 160.0                 # outer diameter
ID = 60.0                  # central bore diameter, 0 = no bore
THK = 20.0                 # thickness

BCD = 120.0                # bolt circle diameter
N_BOLTS = 6                # number of bolt holes, 0 = none
BOLT_D = 14.0              # bolt hole diameter

CHAMFER = 2.0              # chamfer on both outer rims, 0 = off

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "flange_demo"

DEFAULT_SPEC = {
    "part_name": PART_NAME,
    "out_dir": OUT_DIR,
    "part": "circular_flange",
    "params": {
        "od": OD,
        "id": ID,
        "thk": THK,
        "bcd": BCD,
        "n_bolts": N_BOLTS,
        "bolt_d": BOLT_D,
        "chamfer": CHAMFER,
    },
    "export": {"step": True, "log_file": True},
}


def build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()

    od = params["od"]
    idia = params["id"]
    thk = params["thk"]
    bcd = params["bcd"]
    n_bolts = int(round(params["n_bolts"]))
    bolt_d = params["bolt_d"]
    chamfer = params["chamfer"]

    part = nxj.new_metric_part(session, p["prt"], log)
    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType

    # ---- the disc: one full circle -----------------------------------------
    disc = nxj.circle(part, 0.0, 0.0, od)
    log.ok("outer circle D%.1f" % od)
    feat = nxj.extrude(part, session, [disc], NXOpen.Point3d(0.0, 0.0, 0.0),
                       0.0, thk, bb.Create, name="disc")
    body = feat.GetBodies()[0]
    body.SetName("Flange")
    log.ok("extrude %.1f mm -> body '%s'" % (thk, body.Name))

    # ---- bore + bolt circle, cut in ONE subtract extrude -------------------
    holes = []
    centres = []
    if idia > 0:
        holes.append(nxj.circle(part, 0.0, 0.0, idia))
        centres.append((0.0, 0.0))
        log.ok("centre bore D%.1f" % idia)
    if n_bolts > 0 and bolt_d > 0:
        r_bc = bcd / 2.0
        for k in range(n_bolts):
            a = 2.0 * math.pi * k / n_bolts
            x, y = r_bc * math.cos(a), r_bc * math.sin(a)
            holes.append(nxj.circle(part, x, y, bolt_d))
            centres.append((x, y))
        log.ok("%d bolt holes D%.1f on BCD %.1f" % (n_bolts, bolt_d, bcd))

    if holes:
        seed = NXOpen.Point3d(centres[0][0], centres[0][1], 0.0)
        nxj.extrude(part, session, holes, seed, -1.0, thk + 1.0, bb.Subtract,
                    target=body, name="holes")
        log.ok("holes cut")

    # ---- chamfer both outer rims -------------------------------------------
    if chamfer > 0:
        # both endpoints of a circular edge lie on its circle, so radius + Z
        # classify it stably wherever the seam falls
        edges = (nxj.circular_edges_on_ring(body, od / 2.0, 0.0)
                 + nxj.circular_edges_on_ring(body, od / 2.0, thk))
        log.chk("outer rim edges found: %d (expected 2 - top and bottom)" % len(edges))
        if len(edges) != 2:
            log.err("expected 2 outer rim edges for the chamfer, found %d" % len(edges))
        else:
            nxj.chamfer_edges(part, session, edges, chamfer)
            log.ok("chamfer C%.1f on both outer rims" % chamfer)

    nxj.check_geometry(part, body, spec, log, result)

    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_flange (NX 2406)")
