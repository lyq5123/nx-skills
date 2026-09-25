# NX skills for AI coding agents

Two agent skills for **Siemens NX** (formerly UG / Unigraphics), verified against **NX 2406** on
Windows.

| Skill | What it does |
| --- | --- |
| [`nx-model`](skills/nx-model) | Builds parametric parts from a JSON spec by generating and running an NX Open Python journal, then **verifies the result numerically**. Exports `.prt` and STEP. Headless — no GUI needed. |
| [`nx-gui`](skills/nx-gui) | Operates NX's own interface through Computer Use (clicks the ribbon, fills dialogs, draws sketches). Includes a measured capability matrix of what is and is not automatable. |

These are `SKILL.md` bundles for agent harnesses that read `.agents/skills/` (ZCode, Claude-style
skill loaders). They are also just Markdown + Python, so you can read and lift the code directly.

---

## The idea

An agent that "runs a script without error" has not built a part. This skill is built around the
opposite habit: **every model is measured, and a model whose volume and face count do not match the
analytic values fails the run.**

That matters because NX fails quietly in several ways that were each found the hard way:

- A feature can silently no-op. The journal still exits 0.
- `DexManager.CreateStepCreator()` validates cleanly, commits without raising, writes a
  plausibly-sized file — containing **zero solids**. The working export path is the bundled CLI
  translator instead.
- Assigning a float to a length's `.Value` applies a **silent 25.4× conversion**.
- A degenerate parameter set (e.g. holes landing on the centreline) builds a *wrong* solid while
  announcing the discrepancy in its own log and returning success.

[`docs/design-notes.md`](docs/design-notes.md) records all of these, with the observed error text and
what each one cost. Read it before changing any code here.

---

## Requirements

- Siemens **NX 2406** installed, with `UGII_BASE_DIR` set.
- Windows (paths and the STEP translator invocation are Windows-tested; the Python is portable).
- Python 3 for the test harness only. **The journals themselves need no Python packages** — NX ships
  CPython 3.10 with no `site-packages`, so the skill is stdlib-only by design.

The skill reads NX API signatures from the stubs inside your own NX install
(`$UGII_BASE_DIR/UGOPEN/pythonStubs/`). It does **not** redistribute any Siemens files.

## Install

Copy a skill directory into your skills folder:

```bash
cp -r skills/nx-model ~/.agents/skills/
cp -r skills/nx-gui   ~/.agents/skills/
```

## Quick start

Write a spec:

```json
{
  "part_name": "mounting_plate",
  "out_dir": "~/nx_out",
  "params": {
    "plate_w": 120.0, "plate_h": 80.0, "plate_t": 10.0,
    "hole_d": 6.6, "hole_inset": 12.0,
    "bore_d": 30.0, "fillet_r": 8.0
  }
}
```

Build it, then check it with a **separate** journal opening the saved part:

```bash
"$UGII_BASE_DIR/NXBIN/run_journal.exe" skills/nx-model/scripts/build_plate.py  -args my_spec.json
"$UGII_BASE_DIR/NXBIN/run_journal.exe" skills/nx-model/scripts/verify_part.py -args my_spec.json
```

The verifier computes the expected volume from the same analytic formula the build used, so the two
cannot drift apart. Verified results for the shipped fixtures:

| Part | Volume (mm³) | Faces |
| --- | --- | --- |
| 120×80×10, 4× D6.6, D30 bore, no fillet | 87562.939 | 11 |
| the same with R8 corner fillets | 87013.558 | 15 |

Change one number and rebuild — no editing of source files required.

### What a run produces

| File | Notes |
| --- | --- |
| `<name>.prt` | the part |
| `<name>.step` | AP214 solid |
| `<name>.run.log` | full run log |
| `<name>.result.json` | machine-readable outcome: `status`, `params`, `checks`, `files`, `errors` |

**Exit code 0 means built and self-checked; non-zero means something failed.** The exact code is not
propagated by `run_journal.exe`, so `result.json` carries the detail.

Parameter conflicts — holes breaking through an edge, holes past the centreline, a bore overlapping
the corner holes, a fillet colliding with a hole, non-numeric values — are **refused before NX is
touched**, with a message naming the value and the limit.

## Tests

```bash
python skills/nx-model/tests/run_tests.py     # ~4 min, needs NX installed
python skills/nx-model/tests/run_tests.py T4  # a single test
```

Seven tests, including a **negative control** (the verifier must *reject* a part built to different
dimensions — otherwise a verifier that always passes looks green) and five conflict fixtures that
must all be rejected. Any Python 3 can run the harness; it only shells out to NX.

## What this does not do

Stated plainly, because the honest scope is more useful than an optimistic one:

- **It cannot read a drawing.** The code's input is numbers; interpreting a drawing, photo or
  screenshot is the *agent's* job. `skills/nx-model/SKILL.md` documents the discipline for that
  (transcribe → confirm with the user → build) and, importantly, why the numeric verification **cannot
  catch a misread dimension**: it compares NX's measurement against a value derived from the same
  spec, so a wrong number moves both sides together and the run stays green.
- **No drafting.** No drawing sheets, projected views, annotations, PDF or DWG.
- **Only one part recipe.** `plate_metrics()` / `validate_plate()` are specific to the mounting-plate
  geometry. Adding a part type means adding both its geometry formula and its validation rules, or
  the verifier will compare against wrong expectations. A recipe registry is the natural next step.
- **`nx-gui` cannot reach menus.** Pull-down menus, dropdown contents and graphics-area filter bars
  are invisible to both screenshots and accessibility on NX 2406, so commands behind them have to be
  done by hand. Selecting an existing sketch's curves as an extrude section is unsolved; the
  documented `绘制截面` route is verified only as far as the sketch opening in a normal view.
- **One NX version.** Everything was measured on NX 2406. Signatures change between releases — check
  the stubs (`grep` them) rather than trusting any snippet, including the ones here.

## License

MIT — see [LICENSE](LICENSE).
