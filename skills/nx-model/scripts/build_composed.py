# =============================================================================
#  NX Open Python journal  -  composed part (a SEQUENCE of features)
#
#  The named builders each hard-code one shape. This one executes a LIST of
#  operations, in order, which is what most real drawings are: a plate, then a
#  boss on it, then holes through both, then rounds on the outside.
#
#  RUN
#    ".../run_journal.exe" build_composed.py                    # built-in example
#    ".../run_journal.exe" build_composed.py -args my_spec.json
#  Then:  python show_in_nx.py my_spec.json
#
#  SPEC SHAPE
#    {
#      "part": "composed",
#      "params": {"features": [ ... ]}
#    }
#  Each feature is one of profile / hole / boss / blend / chamfer - the full
#  description, the plane conventions and the edge selectors are in nx_compose.py,
#  which is also what validates the list before NX is touched.
#
#  WHAT IS AND IS NOT VERIFIED HERE - read this before trusting a composed build.
#    * The solid operations (profile / hole / boss) are checked against a volume
#      computed by an independent Monte-Carlo sampler that never asks NX. It is a
#      ~1% check, not the exact one the named recipes get, because a feature list
#      has no closed-form volume. The width of that band is printed on every run.
#    * BLENDS AND CHAMFERS ARE NOT MODELLED BY THE SAMPLER. So they cannot be
#      verified against a reference value, and a blend that silently failed would
#      NOT be caught by the volume check. What IS checked: the selector must match
#      at least one edge, the feature must remove a positive amount of material,
#      and the amount is printed. The material they remove is added back before the
#      volume comparison (check_geometry's volume_offset) so the two things do not
#      contaminate each other - which is also why this run must never claim the
#      volume check covered the rounds.
#    * Face counts are not asserted: there is no honest derivation for an arbitrary
#      feature list, and a number copied from a previous run is self-consistency,
#      not verification.
# =============================================================================
import os
import sys

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

import nx_common as nxc
import nx_compose as nxcmp
import nx_journal as nxj

# -----------------------------------------------------------------------------
# default: a plate, a hole through it, and a boss overlapping it - the smallest
# list that exercises add, cut and a second add on top of the first body.
# -----------------------------------------------------------------------------
PLATE = [["line", 0.0, 0.0, 200.0, 0.0],
         ["line", 200.0, 0.0, 200.0, 160.0],
         ["line", 200.0, 160.0, 0.0, 160.0],
         ["line", 0.0, 160.0, 0.0, 0.0]]

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "composed_demo"

DEFAULT_SPEC = {
    "part_name": PART_NAME,
    "out_dir": OUT_DIR,
    "part": "composed",
    "params": {
        "features": [
            {"op": "profile", "plane": "xy", "thickness": 20.0, "outline": PLATE},
            {"op": "hole", "axis": "z", "at": [30.0, 30.0], "dia": 20.0,
             "through": True},
            {"op": "boss", "axis": "z", "at": [100.0, 80.0], "dia": 55.0,
             "height": 25.0},
        ]
    },
    "export": {"step": True, "log_file": True},
}

# -----------------------------------------------------------------------------
# placing a profile outline in space
#
# (x_dir, y_dir) span the plane the ARC angles are measured in, and the third
# vector is the extrusion direction. For the XZ plane the frame is (x, z) with y
# as the normal - the same convention build_cradle.py uses for its groove, and the
# only one that puts a "counter-clockwise in the drawing" arc on the right side.
# -----------------------------------------------------------------------------
_FRAME = {
    "xy": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "xz": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "yz": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
}


def _xyz(feature, u, v, off):
    """A 3D point from an outline coordinate pair plus the plane offset."""
    ua, va, na = nxcmp.plane_axes(feature["plane"])
    d = {"x": 0.0, "y": 0.0, "z": 0.0}
    d[ua] = u
    d[va] = v
    d[na] = off
    return (d["x"], d["y"], d["z"])


def _point(feature, u, v, off):
    return NXOpen.Point3d(*_xyz(feature, u, v, off))


def _curves(part, feature, off):
    """The feature's outline as NX curves, placed in its plane at `off`."""
    x_dir, y_dir, _n = _FRAME[feature["plane"]]
    disc = feature.get("_disc")
    if disc is not None:
        # A hole or a boss is a real circle, not the 48-gon the sampler tests -
        # otherwise the "hole" comes out of the kernel as a faceted prism and the
        # log reports zero cylindrical faces, which is exactly how this was caught.
        cx, cy, r = disc
        return [nxj.arc(part, _xyz(feature, cx, cy, off), r, 0.0, 360.0,
                        x_dir=x_dir, y_dir=y_dir)]
    curves = []
    for s in feature["_segments"]:
        if s[0] == "line":
            _k, x1, y1, x2, y2 = s
            curves.append(part.Curves.CreateLine(_point(feature, x1, y1, off),
                                                 _point(feature, x2, y2, off)))
        else:
            _k, cx, cy, r, a1, sweep = s
            # NX sweeps counter-clockwise from start to end, so a clockwise segment
            # is handed over as its reversed (equal) counter-clockwise arc
            lo, hi = (a1, a1 + sweep) if sweep > 0 else (a1 + sweep, a1)
            curves.append(nxj.arc(part, _xyz(feature, cx, cy, off), r, lo, hi,
                                  x_dir=x_dir, y_dir=y_dir))
    return curves


def _direction(feature):
    return _FRAME[feature["plane"]][2]


# -----------------------------------------------------------------------------
# edge selectors - geometric, never an index into a face list
# -----------------------------------------------------------------------------
def _select_edges(body, sel, built, log):
    """The body edges a blend or chamfer should act on. Empty list = nothing matched."""
    cands = list(body.GetEdges())
    n_in = len(cands)

    if "from_feature" in sel:
        n = sel["from_feature"]
        own = built.get(n)
        if own is None:
            log.err("selector names feature %d, which this build did not create" % n)
            return []
        tags = {e.Tag for e in own.GetEdges()}
        cands = [e for e in cands if e.Tag in tags]
        if not cands:
            # GetEntities() is the obvious call here and returns NOTHING - use
            # GetEdges()/GetFaces(), verified on NX 2406.
            log.err("feature %d contributed no edges to the body - it may have been "
                    "consumed by a later operation" % n)
            return []

    if "parallel_to" in sel:
        axis = sel["parallel_to"]
        idx = "xyz".index(axis)
        others = [i for i in range(3) if i != idx]
        keep = []
        for e in cands:
            p0, p1 = e.GetVertices()
            c = (abs(p1.X - p0.X), abs(p1.Y - p0.Y), abs(p1.Z - p0.Z))
            if c[idx] > 1e-6 and all(c[i] < 1e-6 for i in others):
                keep.append(e)
        cands = keep

    if "mid_at" in sel:
        keep = []
        for e in cands:
            p0, p1 = e.GetVertices()
            ok = True
            for axis, want in sel["mid_at"].items():
                got = (getattr(p0, axis.upper()) + getattr(p1, axis.upper())) / 2.0
                if abs(got - want) > 1e-4:
                    ok = False
                    break
            if ok:
                keep.append(e)
        cands = keep

    log.chk("  selector %s -> %d of the body's %d edges" % (sel, len(cands), n_in))
    if not cands:
        log.err("the selector matched no edge - nothing would be rounded, and a "
                "missing blend is the one thing the volume check cannot see")
    return cands


def build(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()
    bb = NXOpen.GeometricUtilities.BooleanOperation.BooleanType

    bad = []
    features = nxcmp.parse_features(params.get("features"), bad)
    if bad:                                     # validate_part already rejected these
        log.err("features did not parse: %s" % "; ".join(bad))
        return

    # how far a "through" cut has to reach: the whole part plus a margin
    whole = nxcmp.bounding_box(features)
    reach = {}
    for i, axis in enumerate("xyz"):
        reach[axis] = (whole[1][i] - whole[0][i]) + 5.0

    part = nxj.new_metric_part(session, p["prt"], log)

    body = None
    built = {}
    rounded_off = 0.0
    blends = []

    for f in features:
        op = f["op"]
        label = "%s[%d]" % (op, f["index"])
        if op in nxcmp._SOLID_OPS:
            base = f["at_offset"] + f["start"]
            curves = _curves(part, f, base)
            if f["thickness"] is None:                      # "through"
                d = reach[nxcmp.plane_axes(f["plane"])[2]]
                lo, hi = -d, d
            else:
                lo, hi = 0.0, f["thickness"]
            cut = f["mode"] == "cut"
            if body is None:
                boolean = bb.Create
            else:
                boolean = bb.Subtract if cut else bb.Unite
            seed_u, seed_v = nxcmp.seed_point(f)

            feat = nxj.extrude(part, session, curves, _point(f, seed_u, seed_v, base),
                               lo, hi, boolean, target=body, name=label,
                               direction=_direction(f))
            body = feat.GetBodies()[0]
            built[f["index"]] = feat
            log.ok("%s: %s in %s, %s" % (label, "cut" if cut else "add", f["plane"],
                                         "through" if f["thickness"] is None
                                         else "%.1f deep" % f["thickness"]))
            nxj.stage_volume(part, body, log, label)
        else:
            edges = _select_edges(body, f["edges"], built, log)
            if not edges:
                return                             # log.err already recorded why
            before = nxj.measure(part, body)[0]
            if op == "blend":
                feat = nxj.blend_edges(part, session, edges, f["r"])
            else:
                feat = nxj.chamfer_edges(part, session, edges, f["c"])
            built[f["index"]] = feat
            after = nxj.measure(part, body)[0]
            removed = before - after
            entry = {"feature": f["index"], "op": op, "edges": len(edges),
                     "removed": round(removed, 6)}
            blends.append(entry)
            if removed <= 1e-9:
                log.err("%s removed no material - the edges it was given are not the "
                        "ones the drawing rounds" % label)
            else:
                rounded_off += removed
                log.ok("%s: %.1f on %d edge(s), removed %.3f mm^3"
                       % (label, f.get("r", f.get("c")), len(edges), removed))
            nxj.stage_volume(part, body, log, label)

    rep = nxcmp.composed_report(params)
    log.chk("reference volume %.1f is SAMPLED: %d points, +-%.1f (%.2f%%)"
            % (rep["volume"], rep["samples"], rep["sigma"],
               rep["relative_sigma"] * 100.0))
    log.chk("  that band, not 0.0000, is the agreement this shape can be held to")
    result["checks"]["reference"] = {
        "sampled": True, "samples": rep["samples"],
        "sigma": round(rep["sigma"], 3),
        "relative_sigma": round(rep["relative_sigma"], 6)}
    if blends:
        result["checks"]["blends"] = blends
        log.warn("blends/chamfers are NOT modelled by the reference value - a round "
                 "that removed material is checked, one that was not applied at all "
                 "would not be caught by the volume comparison")

    nxj.check_geometry(part, body, spec, log, result, volume_offset=rounded_off)

    nxj.save_part(part, p["prt"], log, result)
    if spec.get("export", {}).get("step", True):
        if nxj.export_step(part, p["step"], log):
            log.ok("exported " + p["step"])
            result["files"]["step"] = p["step"]
            result["files"]["step_bytes"] = os.path.getsize(p["step"])
    log.info("DONE")


if __name__ == "__main__":
    nxj.run(build, DEFAULT_SPEC, sys.argv, "build_composed (NX 2406)")
