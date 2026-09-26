# nx-model tests

Regression suite for the `nx-model` skill. Runs with **any Python 3** - it never imports `NXOpen`,
it only shells out to `run_journal.exe`. NX must be installed.

```bash
python run_tests.py          # all tests, ~3.5 min
python run_tests.py T4       # one test by prefix
```

Exit code 0 means everything passed. Nothing is left behind in the user's normal output directory
except by T1, which deliberately exercises the no-argument default path and therefore writes to the
product's default `out_dir`.

## What is covered

| Test | Asserts |
| --- | --- |
| T1 | No arguments still builds the original part - the backward-compatibility path. Volume and face count checked against values computed outside the skill. |
| T2 | A spec file overrides the built-in parameters, and the resulting volume matches an independently computed value (`200*100*12 - 4*pi*4.5^2*12 - pi*20^2*12 - 4*(8^2 - pi*8^2/4)*12`). |
| T3 | `verify_part.py` agrees with the part the build produced. |
| T4 | **Negative control**: verifying `t2_plate.prt` against `plate_w=210` must FAIL. Without this, a verifier that always passes would look green. |
| T5 | All five parameter-conflict fixtures are refused before NX is touched, with the expected message, and leave no `.prt`/`.step` behind. |
| T6 | A missing spec path and a malformed JSON spec both fail with a clear message rather than a traceback. |
| T7 | The exported STEP contains a `MANIFOLD_SOLID_BREP`, not just a plausible file. |
| T8 | The recipe rules and analytic formulas, in 0.01 s and with no NX involved. |
| T9 | **Every registered shape** - flange, bracket and the generic profile - builds a correct solid and passes the independent verifier. |

## Layout

```
tests/
  run_tests.py           the harness
  test_recipes.py        the recipe rules and formulas (runs standalone, no NX)
  specs/                 fixtures; five of them are expected to be REJECTED
    plate_ok.json          valid, deliberately non-default dimensions
    flange_ok.json         valid flange, non-default
    bracket_ok.json        valid bracket, non-default
    profile_ok.json        valid generic outline (a hexagon), non-default
    bad_hole_outside.json  hole breaks through the plate edge
    bad_hole_centreline.json  holes at the centreline -> the four coincide
    bad_bore_overlap.json  bore overlaps the corner holes
    bad_fillet_hole.json   corner fillet collides with a hole
    bad_type.json          plate_w given as a string
  out/                   products of this run (git-ignorable)
  tmp/                   specs materialised with test-local out_dir
```

## Adding a test

Add a function `T8_whatever()` that calls `check(cond, msg)` and raise `AssertionError` on failure,
then append it to `TESTS`. Two habits worth keeping:

- **Assert on `result.json`, not only on stdout.** A journal can print cheerful lines and still write
  the wrong solid.
- **Reset the result file before asserting** (`reset_result`). Otherwise a run that fails to write its
  result is graded against the previous run's file, and a broken build passes.
