# =============================================================================
#  Test harness for the nx-model skill.
#
#  Run with ANY Python 3 (it only shells out to NX, it never imports NXOpen):
#      python run_tests.py            # all tests
#      python run_tests.py T4         # one test by prefix
#
#  Exit code 0 = all passed. Every test asserts on the exit code AND on the
#  structured result JSON, because a journal can write a wrong part and still
#  look fine on stdout.
# =============================================================================
import glob
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
SPECS = os.path.join(HERE, "specs")
OUT = os.path.join(HERE, "out")
TMP = os.path.join(HERE, "tmp")

sys.path.insert(0, SCRIPTS)
import nx_common as nxc          # stdlib-only, so the harness can import it

# The no-argument test exercises the product's real default path, which writes to
# the default out_dir rather than tests/out - so read the result from there.
DEFAULT_OUT = nxc.DEFAULT_PLATE["out_dir"]
DEFAULT_NAME = nxc.DEFAULT_PLATE["part_name"]

# analytic values for the default spec (120x80x10, 4x D6.6, D30 bore, no fillet),
# computed independently of the skill
DEFAULT_VOLUME = 87562.93877
DEFAULT_FACES = 11

# analytic volume of specs/plate_ok.json, computed independently of the skill:
#   200*100*12  - 4*pi*4.5^2*12  - pi*20^2*12  - 4*(8^2 - pi*8^2/4)*12
PLATE_OK_VOLUME = 221207.47023063523
PLATE_OK_FACES = 15


def find_run_journal():
    cands = []
    base = os.environ.get("UGII_BASE_DIR")
    if base:
        cands.append(os.path.join(base, "NXBIN", "run_journal.exe"))
    for pat in (r"D:\Program Files\Siemens\NX*\NXBIN\run_journal.exe",
                r"C:\Program Files\Siemens\NX*\NXBIN\run_journal.exe"):
        cands.extend(sorted(glob.glob(pat), reverse=True))
    for c in cands:
        if os.path.isfile(c):
            return c
    raise SystemExit("run_journal.exe not found; set UGII_BASE_DIR")


RUN_JOURNAL = find_run_journal()


def run(script, args=()):
    """Run a journal. Returns (returncode, combined stdout)."""
    cmd = [RUN_JOURNAL, os.path.join(SCRIPTS, script)]
    if args:
        cmd += ["-args"] + list(args)
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=SCRIPTS, timeout=600)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def spec_path(fixture, name=None, out_dir=None, params=None):
    """Materialise a fixture into tmp/ with test-local output paths.

    `params` is an explicit mapping merged into spec["params"]. It must NOT be
    collected via **kwargs: calling this with params={...} would then arrive as
    {"params": {...}} and silently set nothing.
    """
    with open(os.path.join(SPECS, fixture), "r", encoding="utf-8") as fh:
        spec = json.load(fh)
    spec["out_dir"] = out_dir or OUT
    spec["part_name"] = name or os.path.splitext(fixture)[0]
    if params:
        spec.setdefault("params", {}).update(params)
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, spec["part_name"] + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2)
    return path


def result_of(part_name, verify=False, out_dir=None):
    suffix = ".verify.result.json" if verify else ".result.json"
    path = os.path.join(out_dir or OUT, part_name + suffix)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def discard(path):
    """Remove a file so the next run has to recreate it.

    Returns None when it is gone - the normal case - or the file's mtime when the
    delete was refused. On a machine where the OS refuses the delete (read-only
    directory, the file held open, a fail-closed sandbox that cannot use the
    recycle bin) a bare os.remove raises and the test aborts BEFORE it runs, which
    reads as a skill failure when nothing is wrong. The caller compares the
    returned mtime, so "the file is there" cannot be mistaken for "this run wrote
    it".
    """
    if not os.path.exists(path):
        return None
    try:
        os.remove(path)
        return None
    except OSError:
        return os.path.getmtime(path)


def reset_result(part_name, verify=False, out_dir=None):
    """Drop a previous result file so a stale one cannot mask a failure.

    Where the delete is refused, poison the file instead of skipping it: the
    sentinel carries no "status": "ok", so a run that fails to write still cannot
    be read as a passing one. Silently leaving the old file alone would defeat the
    only thing this function is for.
    """
    suffix = ".verify.result.json" if verify else ".result.json"
    path = os.path.join(out_dir or OUT, part_name + suffix)
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as exc:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"status": "stale", "errors": '
                         '["previous result could not be removed: %s"]}' % exc)
        except OSError as exc2:
            # Nothing left to try: say so loudly rather than let a stale "ok" stand.
            print("[WARN] cannot remove or neuter the stale result %s: %s" % (path, exc2))


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# -----------------------------------------------------------------------------
# tests
# -----------------------------------------------------------------------------
def T1_build_default():
    """No arguments must still build the original part (backward compatibility)."""
    obsoleted = {}
    for f in (DEFAULT_NAME + ".prt", DEFAULT_NAME + ".step"):
        p = os.path.join(DEFAULT_OUT, f)
        obsoleted[p] = discard(p)
    reset_result(DEFAULT_NAME, out_dir=DEFAULT_OUT)
    rc, out = run("build_plate.py")
    check(rc == 0, "expected exit 0, got %d\n%s" % (rc, out[-1500:]))
    r = result_of(DEFAULT_NAME, out_dir=DEFAULT_OUT)
    check(r is not None, "no result json in %s" % DEFAULT_OUT)
    check(r["status"] == "ok", "status=%s errors=%s" % (r["status"], r["errors"]))
    check(r["spec_source"] == "built-in defaults",
          "no-argument run reported spec source %r" % r["spec_source"])
    got = r["checks"]["volume"]["actual"]
    check(abs(got - DEFAULT_VOLUME) < 1e-3,
          "volume %.6f != independently computed %.6f" % (got, DEFAULT_VOLUME))
    check(r["checks"]["faces"]["actual"] == DEFAULT_FACES,
          "faces=%s expected %s" % (r["checks"]["faces"]["actual"], DEFAULT_FACES))
    for p, before in obsoleted.items():
        base = os.path.basename(p)
        check(os.path.isfile(p), "%s missing" % base)
        # Where the delete was refused, mere existence proves nothing - the file
        # may be the previous run's. A newer mtime is what proves this run wrote it.
        if before is not None:
            check(os.path.getmtime(p) > before, "%s was not rewritten" % base)


def T2_build_from_spec():
    """A spec file overrides the built-in parameters and builds the right solid."""
    spec = spec_path("plate_ok.json", name="t2_plate", params={"fillet_r": 8.0})
    rc, out = run("build_plate.py", [spec])
    check(rc == 0, "expected exit 0, got %d\n%s" % (rc, out[-1500:]))
    r = result_of("t2_plate")
    check(r is not None and r["status"] == "ok", "status=%s" % (r and r.get("status")))
    check(r["spec_source"].endswith("t2_plate.json"), "spec not recorded: %s" % r["spec_source"])
    got, exp = r["checks"]["volume"]["actual"], PLATE_OK_VOLUME
    check(abs(got - exp) < 1e-3, "volume %.6f != independently computed %.6f" % (got, exp))
    check(r["checks"]["faces"]["actual"] == PLATE_OK_FACES,
          "faces=%s expected %s" % (r["checks"]["faces"]["actual"], PLATE_OK_FACES))


def T3_verify_spec():
    """The independent verifier agrees with the built part."""
    spec = spec_path("plate_ok.json", name="t2_plate")
    reset_result("t2_plate", verify=True)
    rc, out = run("verify_part.py", [spec])
    check(rc == 0, "expected exit 0, got %d\n%s" % (rc, out[-1500:]))
    r = result_of("t2_plate", verify=True)
    check(r is not None and r["status"] == "ok", "verify status=%s" % (r and r.get("status")))
    check(r["checks"]["faces"]["expected"] == PLATE_OK_FACES, "expected faces mismatch")


def T4_verify_detects_wrong_part():
    """Negative control: verifying t2_plate against different dimensions must FAIL.

    Without this, a verifier that always passes would look green.
    """
    spec = spec_path("plate_ok.json", name="t2_plate", params={"plate_w": 210.0})
    reset_result("t2_plate", verify=True)
    rc, out = run("verify_part.py", [spec])
    check(rc != 0, "verifier accepted a part built to different dimensions.\n%s"
                   % out[-1200:])
    r = result_of("t2_plate", verify=True)
    check(r is not None, "verify wrote no result json")
    check(r["status"] == "failed", "status=%s" % r["status"])
    check(any("volume mismatch" in e for e in r["errors"]),
          "expected a volume mismatch, got %s" % r["errors"])


def T5_bad_specs_rejected():
    """Every parameter conflict must be refused before NX is touched."""
    cases = [
        ("bad_hole_outside.json", "break through the plate edge"),
        ("bad_hole_centreline.json", "centreline"),
        ("bad_bore_overlap.json", "overlaps the corner holes"),
        ("bad_fillet_hole.json", "collides with the hole"),
        ("bad_type.json", "must be a number"),
    ]
    for fixture, needle in cases:
        name = "t5_" + os.path.splitext(fixture)[0]
        spec = spec_path(fixture, name=name)
        rc, out = run("build_plate.py", [spec])
        check(rc != 0, "%s was accepted (exit 0)" % fixture)
        check(needle in out, "%s: expected %r in output:\n%s" % (fixture, needle, out[-800:]))
        check("spec rejected" in out, "%s: not rejected at the entry point" % fixture)
        for ext in (".prt", ".step"):
            check(not os.path.isfile(os.path.join(OUT, name + ext)),
                  "%s: produced %s despite being rejected" % (fixture, ext))


def T6_missing_and_malformed_spec():
    """Unusable spec files give a clear message, not a traceback."""
    missing = os.path.join(TMP, "does_not_exist.json")
    rc, out = run("build_plate.py", [missing])
    check(rc != 0 and "spec file not found" in out, "missing spec: rc=%d %s" % (rc, out[-400:]))

    os.makedirs(TMP, exist_ok=True)
    broken = os.path.join(TMP, "broken.json")
    with open(broken, "w", encoding="utf-8") as fh:
        fh.write('{"part_name": "broken", "params": {')
    rc, out = run("build_plate.py", [broken])
    check(rc != 0 and "not valid JSON" in out, "malformed spec: rc=%d %s" % (rc, out[-400:]))

    # A stray option must NOT be ignored. Silently dropping it fell through to the
    # built-in defaults, so `-arg spec.json` (one dash) quietly built the default
    # part instead of the one asked for - a silent wrong model.
    rc, out = run("build_plate.py", ["-arg", os.path.join(SPECS, "plate_ok.json")])
    check(rc != 0 and "unexpected option" in out,
          "stray option not rejected: rc=%d %s" % (rc, out[-400:]))
    check("plate_ok" not in out,
          "a stray option still built something: %s" % out[-300:])


def T7_step_contains_geometry():
    """The STEP file must hold a solid, not just exist."""
    step = os.path.join(OUT, "t2_plate.step")
    check(os.path.isfile(step), "no STEP to check")
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "check_step.py"), step],
                       capture_output=True, text=True)
    check(p.returncode == 0, "check_step said:\n%s" % (p.stdout + p.stderr))
    check("MANIFOLD_SOLID_BREP" in p.stdout, "no solid reported")


def T8_recipe_unit_tests():
    """Pure-logic tests for the part recipes, the registry and the output contract.

    Fast and NX-free, so the rules can be checked without paying ~30 s per
    journal run. Each file runs in its own process to keep its imports out of the
    harness's namespace.
    """
    for unit_file in ("test_recipes.py", "test_output_contract.py"):
        p = subprocess.run([sys.executable, os.path.join(HERE, unit_file)],
                           capture_output=True, text=True, cwd=HERE)
        if p.returncode != 0:
            raise AssertionError("%s failed:\n%s"
                                 % (unit_file,
                                    ((p.stdout or "") + (p.stderr or ""))[-2500:]))


def T9_other_shapes_build_and_verify():
    """Every registered shape builds a correct solid and passes the verifier.

    The registry is only worth having if a second shape actually works end to end,
    so each one gets a real build and a real independent check.
    """
    for fixture, name, exp_vol, exp_faces in (
            ("flange_ok.json", "t9_flange", 631516.672039, 14),
            ("bracket_ok.json", "t9_bracket", 128638.274876, 10),
            ("profile_ok.json", "t9_profile", 65842.831974, 10),
            ("outline_arcs_ok.json", "t9_arcs", 92879.645943, 12),
            ("cradle_ok.json", "t9_cradle", 57465.466, None)):
        spec = spec_path(fixture, name=name)
        reset_result(name)
        journal = {"t9_flange": "build_flange.py",
                   "t9_bracket": "build_bracket.py",
                   "t9_profile": "build_profile.py",
                   "t9_arcs": "build_profile.py",
                   "t9_cradle": "build_cradle.py"}[name]
        rc, out = run(journal, [spec])
        check(rc == 0, "%s: build exit %d\n%s" % (name, rc, out[-900:]))
        r = result_of(name)
        check(r is not None and r["status"] == "ok",
              "%s: status=%s errors=%s" % (name, r and r.get("status"),
                                           r and r.get("errors")))
        got = r["checks"]["volume"]["actual"]
        check(abs(got - exp_vol) < 1e-3,
              "%s: volume %.6f != independently computed %.6f" % (name, got, exp_vol))
        if exp_faces is not None:            # cradle has no derivable face count
            check(r["checks"]["faces"]["actual"] == exp_faces,
                  "%s: faces=%s expected %s"
                  % (name, r["checks"]["faces"]["actual"], exp_faces))
        # the alias must resolve to one identity in the output
        check(r["part"] != "flange" and r["part"] != "bracket",
              "%s: alias not canonicalised in result.json (%s)" % (name, r["part"]))

        reset_result(name, verify=True)
        rc, out = run("verify_part.py", [spec])
        check(rc == 0, "%s: verify exit %d\n%s" % (name, rc, out[-900:]))
        check(result_of(name, verify=True)["status"] == "ok",
              "%s: independent verify failed" % name)


def T10_composed_features_build_in_order():
    """The feature-list recipe: five operations, the selectors, and the checks.

    This is the only test that exercises a part NX builds as a SEQUENCE - a plate,
    a blend on four edges found by geometry, a cross hole, a boss, and a chamfer on
    one edge picked out of the boss's own edges. Every number below is computed here
    from the geometry, independently of the skill:

        plate            200 x 160 x 20
        R12 x 4 corners  (r^2 - pi r^2/4) * thickness, each
        D16 hole         through 160, along Y
        D55 boss         only its 5 mm above the plate counts as added material

    Two things make this worth its runtime. The blend and the chamfer remove material
    the reference value does not model, so the run must report what each removed and
    add it back before comparing - the total has to land on the analytic volume
    anyway. And the rounds are the one part of a composed feature list that a volume
    check cannot see, so the removed amounts are asserted here instead.
    """
    name = "t10_composed"
    spec = spec_path("composed_cover.json", name=name)
    reset_result(name)
    rc, out = run("build_composed.py", [spec])
    check(rc == 0, "build exit %d\n%s" % (rc, out[-1500:]))
    r = result_of(name)
    check(r is not None and r["status"] == "ok",
          "status=%s errors=%s" % (r and r.get("status"), r and r.get("errors")))

    plate = 200.0 * 160.0 * 20.0
    rounds = 4.0 * (12.0 ** 2 - math.pi * 12.0 ** 2 / 4.0) * 20.0
    cross_hole = math.pi * 8.0 ** 2 * 160.0
    boss = math.pi * 27.5 ** 2 * 5.0
    # the reference value models no blend or chamfer, and the run adds back what they
    # removed - so what has to match this sum is the volume BEFORE the rounds
    expected = plate - cross_hole + boss

    vol = r["checks"]["volume"]["actual"]
    rounded = r["checks"]["volume"].get("rounded_off", 0.0)
    check(abs(vol + rounded - expected) < 0.5,
          "volume %.3f + %.3f rounded off != independently computed %.3f"
          % (vol, rounded, expected))

    # the reported rounds: 4 corner edges and the boss's top circle
    blends = r["checks"].get("blends")
    check(blends and len(blends) == 2, "blends not recorded: %r" % (blends,))
    check(blends[0]["edges"] == 4 and blends[1]["edges"] == 1,
          "selector edge counts %r, expected 4 then 1" % ([b["edges"] for b in blends],))
    check(abs(blends[0]["removed"] - rounds) < 0.01,
          "R12 corners removed %.3f, expected %.3f" % (blends[0]["removed"], rounds))
    check(all(b["removed"] > 0 for b in blends), "a blend removed nothing: %r" % (blends,))

    # the reference value must declare itself sampled, with a band, not a formula
    ref = r["checks"]["reference"]
    check(ref["sampled"] and ref["samples"] > 0 and ref["sigma"] > 0,
          "the sampled reference is not reported: %r" % (ref,))

    # 4 corner rounds + the cross hole + the boss; the chamfer is a cone, not a
    # cylinder, so it is not in this count
    cyl = r["checks"]["cylindrical_faces"]["actual"]
    check(cyl == 6, "cylindrical faces=%d, expected 6 (4 rounds + hole + boss)" % cyl)

    reset_result(name, verify=True)
    rc, out = run("verify_part.py", [spec])
    check(rc == 0, "verify exit %d\n%s" % (rc, out[-1200:]))
    check(result_of(name, verify=True)["status"] == "ok",
          "the independent verifier rejected the composed part")

    # --- negative control for the SAMPLED path -------------------------------
    # A sampled reference models no blend, so its volume check is one-sided: a
    # round makes the part SHORT of the reference and must not be failed for it.
    # That leaves one failure direction to test - material the part should not
    # have. Without this, the one-sided branch would only ever run in the direction
    # that passes, which is the "verifier that always passes" trap this suite
    # exists to avoid.
    #
    # The mismatch has to come from a spec that does NOT describe the part on disk:
    # editing the build's own spec cannot produce one, because the reference value
    # is computed from that same spec (see the note in SKILL.md - a wrong number
    # moves both sides together and the run stays green). So the part stays as
    # built, with its D16 cross hole, and the verifier is handed a spec that says
    # D30 - a bigger hole than the one in the part, so NX finds material that spec
    # does not allow.
    with open(spec, "r", encoding="utf-8") as fh:
        wrong = json.load(fh)
    for f in wrong["params"]["features"]:
        if f.get("op") == "hole" and f.get("dia") == 16.0:
            f["dia"] = 30.0
    # same part_name and out_dir as the built part, so this spec resolves to the
    # .prt that is actually on disk - the whole point is the CONTENT mismatch
    wrong["part_name"] = name
    wrong["out_dir"] = OUT
    wrong_path = os.path.join(TMP, "t10_wrong_spec.json")
    with open(wrong_path, "w", encoding="utf-8") as fh:
        json.dump(wrong, fh, indent=2)

    reset_result(name, verify=True)
    rc, out = run("verify_part.py", [wrong_path])
    check(rc != 0, "the verifier PASSED a part with material its spec forbids\n%s"
                   % out[-900:])
    check("should not have" in out,
          "the verifier failed it for the wrong reason:\n%s" % out[-900:])
    check(result_of(name, verify=True)["status"] != "ok",
          "the verify result file says ok after a mismatch")


TESTS = [
    ("T1", "build with no arguments (backward compatibility)", T1_build_default),
    ("T2", "build from a spec file, volume checked independently", T2_build_from_spec),
    ("T3", "independent verifier agrees with the part", T3_verify_spec),
    ("T4", "verifier REJECTS a part that does not match the spec", T4_verify_detects_wrong_part),
    ("T5", "parameter conflicts rejected before NX is touched", T5_bad_specs_rejected),
    ("T6", "missing / malformed spec files and stray options fail clearly", T6_missing_and_malformed_spec),
    ("T7", "exported STEP contains real geometry", T7_step_contains_geometry),
    ("T8", "unit tests: recipes + the output contract (no NX needed)",
     T8_recipe_unit_tests),
    ("T9", "every registered shape builds and verifies end to end", T9_other_shapes_build_and_verify),
    ("T10", "a composed feature list builds in order, rounds included",
     T10_composed_features_build_in_order),
]


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else None
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    print("run_journal : %s" % RUN_JOURNAL)
    print("out dir     : %s\n" % OUT)

    failed = 0
    started = time.time()
    for tid, desc, fn in TESTS:
        if wanted and not tid.startswith(wanted):
            continue
        t0 = time.time()
        try:
            fn()
            print("PASS  %s  %-52s %5.1fs" % (tid, desc, time.time() - t0))
        except AssertionError as exc:
            failed += 1
            print("FAIL  %s  %-52s %5.1fs" % (tid, desc, time.time() - t0))
            print("      %s" % str(exc).replace("\n", "\n      "))
        except Exception as exc:
            failed += 1
            print("ERROR %s  %-52s %5.1fs" % (tid, desc, time.time() - t0))
            print("      %s: %s" % (type(exc).__name__, exc))

    total = sum(1 for t in TESTS if not wanted or t[0].startswith(wanted))
    print("\n%d/%d passed in %.1fs" % (total - failed, total, time.time() - started))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
