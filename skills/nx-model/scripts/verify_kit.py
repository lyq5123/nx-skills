# =============================================================================
#  NX Open Python journal  -  independent check of the knock-down assemblies
#
#  Opens the kit and the exploded kit SAVED ON DISK and counts their
#  components, mirroring what build_laptop_stand_kit.py asserts in memory.
#  Run with the same kit spec:
#    ".../run_journal.exe" verify_kit.py -args kit_spec.json
#
#  The pieces themselves are measured by verify_part.py (each piece's part
#  type is laptop_stand_kd and the recipe dispatches on "piece").
# =============================================================================
import os
import sys
import time

import NXOpen

import nx_common as nxc

DEFAULT_SPEC = {
    "part_name": "laptop_stand_v3_kit",
    "out_dir": os.path.join(os.path.expanduser("~"), "nx_out"),
    "part": "laptop_stand_kit",
    "params": {},
}

EXPECTED = sorted(["PLATE", "RIB_FRONT", "RIB_REAR",
                   "SCREW_1", "SCREW_2", "SCREW_3", "SCREW_4"])


def check_one(session, prt, log, result, tag):
    if not os.path.isfile(prt):
        log.err("%s assembly not found: %s" % (tag, prt))
        return
    part, _status = session.Parts.OpenBaseDisplay(prt)
    kids = list(part.ComponentAssembly.RootComponent.GetChildren())
    names = sorted(c.Name.upper() for c in kids)   # NX uppercases component names
    result["checks"][tag] = {"components": len(kids), "names": names}
    log.chk("%s: %d components (%s)" % (tag, len(kids), ", ".join(names)))
    if len(kids) != 7:
        log.err("%s: expected 7 components, found %d" % (tag, len(kids)))
    elif names != EXPECTED:
        log.err("%s: component names %s != expected %s" % (tag, names, EXPECTED))


def main():
    started = time.time()
    try:
        spec, source = nxc.load_spec(sys.argv, DEFAULT_SPEC)
    except nxc.SpecError as exc:
        print("[FAIL] %s" % exc)
        sys.stdout.flush()
        sys.exit(1)

    p = nxc.paths_for(spec)
    log = nxc.Log(None)
    result = {"role": "verify_kit", "part_name": spec["part_name"],
              "spec_source": source, "checks": {}}
    try:
        session = NXOpen.Session.GetSession()
        check_one(session, p["prt"], log, result, "kit")
        spec_e = dict(spec)
        spec_e["part_name"] = spec["part_name"] + "_exploded"
        p_e = nxc.paths_for(spec_e)
        check_one(session, p_e["prt"], log, result, "kit_exploded")
        log.info("VERDICT: %s" % ("OK" if not log.errors else "FAILED"))
    except Exception as exc:
        import traceback
        log.err("unhandled %s: %s" % (type(exc).__name__, exc))
        for line in traceback.format_exc().splitlines():
            log.info(line)
    finally:
        nxc.finish(log, p["result_verify"], result, started)


if __name__ == "__main__":
    main()
