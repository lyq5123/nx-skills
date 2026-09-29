# nx-model tests

Regression suite for the `nx-model` skill. Runs with **any Python 3** - it never imports `NXOpen`,
it only shells out to `run_journal.exe`. NX must be installed.

```bash
python run_tests.py            # all tests, ~10-15 min (every NX test boots NX)
python run_tests.py T4         # one test
python run_tests.py T1         # careful: this is a PREFIX match, so T1 also runs T10
python test_recipes.py         # ~2 s, no NX
python test_output_contract.py # ~0.02 s, no NX
```

Exit code 0 means everything passed. `T1` deliberately exercises the no-argument default path, so it
is the one test that writes to the product's own `out_dir` (`~/nx_out`) instead of `tests/out`.

**Why the prefix match matters:** `run_tests.py T1` selects every test whose id *starts with* `T1` -
i.e. T1 **and** T10. It is a convenience for running T9's five shapes or T5's fixtures, not an exact
selector; pass the full id when you want exactly one.

## What is covered

| Test | Asserts |
| --- | --- |
| T1 | No arguments still builds the original part - the backward-compatibility path. Volume and face count checked against values computed outside the skill. |
| T2 | A spec file overrides the built-in parameters, and the resulting volume matches an independently computed value (`200*100*12 - 4*pi*4.5^2*12 - pi*20^2*12 - 4*(8^2 - pi*8^2/4)*12`). |
| T3 | `verify_part.py` agrees with the part the build produced. |
| T4 | **Negative control**: verifying `t2_plate.prt` against `plate_w=210` must FAIL. Without this, a verifier that always passes would look green. |
| T5 | Five bad fixtures are refused before NX is touched, with the expected message, and leave no `.prt`/`.step` behind. Four are parameter *conflicts* (bore overlapping the corner holes, a hole through an edge, holes at the centreline, holes outside the outline); the fifth, `bad_type.json`, is a *type* error - `plate_w` given as a string - which is the same code path but not a geometry conflict. |
| T6 | A missing spec path and a malformed JSON spec both fail with a clear message rather than a traceback. |
| T7 | The exported STEP contains a `MANIFOLD_SOLID_BREP`, not just a plausible file. |
| T8 | The pure-logic unit tests, with no NX involved: `test_recipes.py` (recipes, validation, analytic formulas) and `test_output_contract.py` (what a run leaves on disk and what it exits with). |
| T9 | **Every registered shape** - flange, bracket, the generic profile, the arc outline and the shaft cradle - builds a correct solid and passes the independent verifier. |
| T10 | The **composed** recipe: a five-operation feature list builds in order, the geometric edge selectors match the expected number of edges, the material each blend/chamfer removed is checked against hand arithmetic, and the cylindrical-face count confirms every round and hole applied. Also carries the negative control for the sampled reference: verifying the built part against a spec claiming a **larger** cross hole must fail. |

## Layout

```
tests/
  run_tests.py             the harness (boots NX; the only thing that needs it)
  test_recipes.py          recipe rules and formulas (standalone, no NX)
  test_output_contract.py  result-file contract: a run must not exit 0 without a verdict
  specs/                   fixtures
    plate_ok.json            valid, deliberately non-default dimensions
    flange_ok.json           valid flange, non-default
    bracket_ok.json          valid bracket, non-default
    profile_ok.json          valid generic outline (a hexagon), non-default
    cradle_ok.json           valid shaft cradle (multi-feature)
    outline_arcs_ok.json     valid outline containing circular arcs
    composed_cover.json      valid composed feature list (plate, hole, boss, rounds, chamfer)
    bad_hole_outside.json    hole breaks through the plate edge
    bad_hole_centreline.json holes at the centreline -> the four coincide
    bad_bore_overlap.json    bore overlaps the corner holes
    bad_fillet_hole.json     corner fillet collides with a hole
    bad_type.json            plate_w given as a string
  out/                     products of this run (git-ignorable)
  tmp/                     specs materialised with test-local out_dir
```

Six of the twelve fixtures are expected to be **rejected** (`bad_*`); the rest must build.

## Keeping a stale artefact from being read as this run's result

Every test deletes its previous artefacts first, because the alternative - grading this run against
the last one's file - makes a broken build look green. Two helpers do that, and both exist because
the naive version failed:

- `reset_result(part_name)` removes `<name>.result.json`. Where the OS **refuses** the delete
  (read-only directory, file held open, a sandbox with no recycle bin) it writes a
  `{"status": "stale"}` sentinel instead of skipping - skipping would defeat the whole point, and
  raising would abort the test at 0.0 s looking like a geometry failure.
- `discard(path)` returns `None` when a file is gone, or its **mtime** when the delete was refused.
  T1 uses that mtime to require the artefact to have been *rewritten*, since mere existence proves
  nothing once a delete can silently fail.

The same principle is tested directly in `test_output_contract.py`, which covers the sibling bug found
in `nx_common.finish()`: an unwritable `result.json` used to leave the previous run's green verdict on
disk while the process exited 0.

## Adding a test

Add a function `T11_whatever()` that calls `check(cond, msg)` and raises `AssertionError` on failure,
then append it to `TESTS`. Three habits worth keeping:

- **Assert on `result.json`, not only on stdout.** A journal can print cheerful lines and still write
  the wrong solid.
- **Reset the result file before asserting** (`reset_result`), and where the delete can be refused,
  prove the file was rewritten rather than assuming it.
- **Add the negative control.** A check that is only ever exercised in the direction that passes is
  the "always green" failure this suite exists to prevent - T4 and T10 both carry one.
