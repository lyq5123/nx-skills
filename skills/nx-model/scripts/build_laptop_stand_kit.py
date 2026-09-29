# =============================================================================
#  NX Open Python journal  -  assemble the laptop-stand knock-down kit
#
#  Creates TWO assembly files from the three verified piece parts:
#    <kit>.prt            everything in its working position
#    <kit>_exploded.prt   the same components displaced along the plate normal,
#                         so the 拆装 stacking order is visible
#
#  Pieces are placed by COORDINATE (origin + orientation), not by constraint
#  solving: every placement below is derived from the same recipe geometry the
#  parts were built to, so the screws land inside their holes by construction.
#  In the GUI the components can be removed/re-added freely; positions stay
#  exact because they come from nx_recipes, not from clicking.
#
#  Components:
#    plate  x1  identity at the origin (the plate piece is modelled in place)
#    rib    x2  modelled centred on y=0, placed at y=+rib_t/2 and y=-rib_t/2
#               ... in WORLD terms: y=rib_t/2 and y=width-rib_t/2
#    screw  x4  head-top at the world seat point, local +Z rotated onto the
#               plate normal, so the shank (-Z) points into the joint
#
#  This is NOT a recipe build (an assembly has no volume of its own); the
#  self-check counts components and their names, and the pieces themselves are
#  verified by their own journals + verify_part.py.
# =============================================================================
import json
import math
import os
import sys
import time

import NXOpen
import NXOpen.Assemblies

import nx_common as nxc
import nx_journal as nxj
import nx_recipes as nxr

OUT_DIR = os.path.join(os.path.expanduser("~"), "nx_out")

DEFAULT_SPEC = {
    "part_name": "laptop_stand_v3_kit",
    "out_dir": OUT_DIR,
    "part": "laptop_stand_kit",
    "params": {
        "width": 280.0, "run": 250.0, "angle": 18.0,
        "plate_t": 8.0, "rib_t": 10.0, "front_h": 12.0,
        "lip_len": 15.0, "lip_h": 15.0,
        "screw_u1": 60.0, "screw_u2": 200.0,
    },
    "plate_part": "laptop_stand_v3_plate",
    "rib_part": "laptop_stand_v3_rib",
    "screw_part": "laptop_stand_v3_screw",
    "explode": 40.0,
}

REFSETS = ("MODEL", "Entire Part", "TRUE")


def _matrix(rows):
    m = NXOpen.Matrix3x3()
    (m.Xx, m.Xy, m.Xz, m.Yx, m.Yy, m.Yz, m.Zx, m.Zy, m.Zz) = rows
    return m


def _identity():
    return _matrix((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))


def add_component(session, asm, part_file, name, origin, matrix, log, cache):
    """Add one component, trying the reference sets NX commonly carries.

    Parts already loaded in this session are reused: OpenBaseDisplay on the
    same file twice raises "File already exists" (the kit places the rib and
    screw parts more than once)."""
    if part_file in cache:
        base = cache[part_file]
    else:
        base, _status = session.Parts.OpenBaseDisplay(part_file)
        cache[part_file] = base
    last = None
    for ref in REFSETS:
        try:
            comp, _ls = asm.ComponentAssembly.AddComponent(
                base, ref, name, NXOpen.Point3d(*origin), matrix, 0)
            return comp, base
        except Exception as exc:                     # noqa: BLE001 - fallback path
            last = exc
    raise RuntimeError("AddComponent failed for %s: %s" % (name, last))


def children_of(asm):
    return list(asm.ComponentAssembly.RootComponent.GetChildren())


def build_assembly(session, spec, params, prt_path, explode_offset, log, cache):
    """One assembly file. explode_offset=0 -> working positions; else every
    component is displaced along the plate normal by a per-part multiple."""
    part = nxj.new_metric_part(session, prt_path, log)
    p_dir = nxc.paths_for(spec)

    a = math.radians(params["angle"])
    ca, sa = math.cos(a), math.sin(a)
    n_up = (-sa, 0.0, ca)               # plate normal, up-forward
    E = explode_offset

    placements = []                     # (piece_part_key, name, origin, matrix)
    placements.append(("plate_part", "plate", (0.0, 0.0, 0.0), _identity()))
    rt = params["rib_t"]
    w = params["width"]
    for tag, yy in (("rib_front", rt / 2.0), ("rib_rear", w - rt / 2.0)):
        placements.append(("rib_part", tag, (0.0, yy, 0.0), _identity()))
    screw_m = _matrix(nxr.laptop_stand_kd_screw_matrix(params))
    for i, origin in enumerate(nxr.laptop_stand_kd_screw_origins(params)):
        placements.append(("screw_part", "screw_%d" % (i + 1), origin, screw_m))

    for key, name, origin, matrix in placements:
        file_name = spec[key] + ".prt"
        part_file = os.path.join(p_dir["out_dir"], file_name)
        if not os.path.isfile(part_file):
            log.err("piece part missing: %s" % part_file)
            continue
        if E:
            mult = {"plate": 1.0, "rib_front": -0.6, "rib_rear": -0.6}.get(name, 2.0)
            origin = tuple(origin[k] + E * mult * n_up[k] for k in range(3))
        comp, _base = add_component(session, part, part_file, name, origin,
                                    matrix, log, cache)
        log.ok("component %-10s at (%.2f, %.2f, %.2f)" % (name, origin[0],
                                                          origin[1], origin[2]))

    kids = children_of(part)
    # NX uppercases component names on creation - compare insensitive
    names = sorted(c.Name.upper() for c in kids)
    expected = sorted(["PLATE", "RIB_FRONT", "RIB_REAR",
                       "SCREW_1", "SCREW_2", "SCREW_3", "SCREW_4"])
    log.chk("components: %d (%s)" % (len(kids), ", ".join(names)))
    if len(kids) != 7:
        log.err("expected 7 components, found %d" % len(kids))
    elif names != expected:
        log.err("component names %s != expected %s" % (names, expected))
    return part


def main():
    started = time.time()
    try:
        spec, source = nxc.load_spec(sys.argv, DEFAULT_SPEC)
    except nxc.SpecError as exc:
        print("[FAIL] %s" % exc)
        sys.stdout.flush()
        sys.exit(1)

    p = nxc.paths_for(spec)
    if not os.path.isdir(p["out_dir"]):
        os.makedirs(p["out_dir"])
    log = nxc.Log(p["log"])
    result = {
        "part": "laptop_stand_kit",
        "part_name": spec["part_name"],
        "spec_source": source,
        "params": spec["params"],
        "files": {},
        "checks": {},
        "ugii_base_dir": os.environ.get("UGII_BASE_DIR", ""),
    }
    try:
        session = NXOpen.Session.GetSession()
        params = spec["params"]
        cache = {}                      # loaded piece parts, reused across both assemblies

        asm = build_assembly(session, spec, params, p["prt"], 0.0, log, cache)
        if not log.errors:
            nxj.save_part(asm, p["prt"], log, result)
            result["files"]["prt"] = p["prt"]

        exp_name = spec["part_name"] + "_exploded"
        spec_e = dict(spec)
        spec_e["part_name"] = exp_name
        p_e = nxc.paths_for(spec_e)
        asm_e = build_assembly(session, spec_e, params, p_e["prt"],
                               spec.get("explode", 40.0), log, cache)
        if not log.errors:
            nxj.save_part(asm_e, p_e["prt"], log, result)
            result["files"]["prt_exploded"] = p_e["prt"]

        session.Parts.SetDisplay(asm, False, False)
        log.info("display part set to the assembled kit")
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        log.err("unhandled %s: %s" % (type(exc).__name__, exc))
        for line in traceback.format_exc().splitlines():
            log.info(line)
    finally:
        nxc.finish(log, p["result"], result, started)


if __name__ == "__main__":
    main()
