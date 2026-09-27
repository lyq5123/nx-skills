# =============================================================================
#  NX Open Python journal  -  independent geometry check of a saved part
#
#  Run as a SEPARATE journal from the one that built the part: the in-memory body
#  can differ from what was written to disk, so checking inside the build journal
#  hides exactly the errors you are looking for.
#
#  RUN
#    ".../run_journal.exe" verify_part.py                          # built-in defaults
#    ".../run_journal.exe" verify_part.py -args my_spec.json       # same spec as the build
#
#  Passing the SAME spec the build used is what makes this a real check: the
#  expected values come from nx_common.plate_metrics, the same function the build
#  self-check uses, so the two can never drift apart. It exits non-zero when the
#  measured part disagrees with the spec.
# =============================================================================
import math
import os
import sys
import time

import NXOpen

import nx_common as nxc

# Which part to check when no spec is given. Point it at any saved .prt; the
# default matches what build_plate.py writes with its defaults.
PRT = os.path.join(nxc.DEFAULT_OUT_DIR, "mounting_plate_demo.prt")

DEFAULT_SPEC = dict(nxc.DEFAULT_PLATE)
DEFAULT_SPEC["out_dir"] = os.path.dirname(PRT)
DEFAULT_SPEC["part_name"] = os.path.splitext(os.path.basename(PRT))[0]


def main():
    started = time.time()

    try:
        spec, source = nxc.load_spec(sys.argv, DEFAULT_SPEC)
    except nxc.SpecError as exc:
        print("[FAIL] %s" % exc)
        sys.stdout.flush()
        sys.exit(1)

    params = spec["params"]
    problems = nxc.validate_part(spec)
    if problems:
        print("[FAIL] spec is not valid, cannot compute expected values:")
        for p in problems:
            print("       - %s" % p)
        sys.stdout.flush()
        sys.exit(1)

    p = nxc.paths_for(spec)
    log = nxc.Log(None)          # stdout only; the build owns the log file
    result = {
        "role": "verify",
        "part_name": spec["part_name"],
        "spec_source": source,
        "params": params,
        "checks": {},
    }

    try:
        _verify(spec, params, p, log, result)
    except Exception as exc:
        import traceback
        log.err("unhandled %s: %s" % (type(exc).__name__, exc))
        for line in traceback.format_exc().splitlines():
            log.info(line)
    finally:
        nxc.finish(log, p["result_verify"], result, started)


def _verify(spec, params, p, log, result):
    session = NXOpen.Session.GetSession()

    if not os.path.isfile(p["prt"]):
        log.err("part not found: %s" % p["prt"])
        log.info("       this verifier fell back to its default spec. Pass the SAME spec")
        log.info("       the build used:  verify_part.py -args my_spec.json")
        return

    part, _status = session.Parts.OpenBaseDisplay(p["prt"])
    session.Parts.SetDisplay(part, False, False)
    log.info("part : %s" % part.FullPath)
    log.info("units: %s   (1 = mm)" % part.PartUnits)

    bodies = [b for b in part.Bodies]      # collections have no len()
    result["checks"]["bodies"] = len(bodies)
    log.chk("bodies: %d (expect 1)" % len(bodies))
    if len(bodies) != 1:
        log.err("expected exactly 1 solid body, found %d" % len(bodies))

    exp_vol, exp_faces = nxc.part_metrics(spec)
    mass_unit = part.UnitCollection.GetBase("Mass")

    for b in bodies:
        mp = part.MeasureManager.NewMassProperties([mass_unit], 0.99, [b])
        vol = mp.Volume
        n_faces = len(b.GetFaces())
        n_edges = len(b.GetEdges())
        delta = abs(vol - exp_vol)

        result["checks"]["volume"] = {"actual": round(vol, 6),
                                     "expected": round(exp_vol, 6),
                                     "delta": round(delta, 6)}
        result["checks"]["faces"] = {"actual": n_faces, "expected": exp_faces}
        result["checks"]["edges"] = {"actual": n_edges}

        log.info("  '%s'" % b.Name)
        log.chk("  volume=%.3f  expected=%.3f  delta=%.6f" % (vol, exp_vol, delta))
        if exp_faces is None:
            log.chk("  faces=%d (not asserted for this shape)  edges=%d"
                    % (n_faces, n_edges))
        else:
            log.chk("  faces=%d (expect %d)  edges=%d" % (n_faces, exp_faces, n_edges))

        if delta >= 1e-3:
            log.err("volume mismatch: off by %.6f mm^3" % delta)
        if exp_faces is not None and n_faces != exp_faces:
            log.err("face count mismatch: %d vs expected %d" % (n_faces, exp_faces))

        # topology cross-check: cylindrical faces trace holes, bore and fillets.
        # Counting them comes from the recipe, so it follows the part type.
        cyl = [f for f in b.GetFaces()
               if f.SolidFaceType == NXOpen.Face.FaceType.Cylindrical]
        exp_cyl = nxc.cylindrical_faces(spec)
        result["checks"]["cylindrical_faces"] = {"actual": len(cyl), "expected": exp_cyl}
        log.chk("  cylindrical faces=%d (expect %d)" % (len(cyl), exp_cyl))
        if len(cyl) != exp_cyl:
            log.err("cylindrical face count %d, expected %d - a hole or fillet is missing"
                    % (len(cyl), exp_cyl))

    # STEP presence, if the build was asked to export one
    if spec.get("export", {}).get("step", True):
        if os.path.isfile(p["step"]):
            with open(p["step"], "r", encoding="latin-1", errors="replace") as fh:
                text = fh.read()
            solids = text.count("MANIFOLD_SOLID_BREP(")
            result["checks"]["step_solids"] = solids
            log.chk("STEP solids=%d" % solids)
            if solids == 0:
                log.err("STEP file contains no solid geometry")
        else:
            log.err("STEP file missing: %s" % p["step"])

    log.info("VERDICT: %s" % ("OK" if not log.errors else "FAILED"))
    log.info("DONE")


if __name__ == "__main__":
    main()
