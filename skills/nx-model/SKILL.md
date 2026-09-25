---
name: nx-model
description: Build parametric 3D parts in Siemens NX (formerly UG / Unigraphics) by generating an NX Open Python journal, running it headless, and verifying the result numerically. Use when the user wants a part or a .prt/.step file produced from given dimensions, wants the same part rebuilt at new sizes, wants a batch of parts, or wants an existing NX journal parameterized or debugged - including when they only describe the part in plain words without naming NX Open. Do NOT use this to drive the NX GUI by hand; use the nx-gui skill when the user wants to watch the model being built in their open NX session or asks you to operate NX's interface.
---

# NX parametric modeling

You build NX parts by **writing an NX Open Python journal, running it, and measuring the result**.
A model that merely "ran without error" is not a deliverable; a model whose volume and topology
match the hand-computed values is.

**Route check before you start.** This skill produces a *file*, headless - it does not appear in a
window the user may have open. If they want to watch it being built, or asked you to "operate NX",
that is the `nx-gui` skill instead (and read its limits first: menus and dropdowns are not
automatable). Otherwise you are in the right place.

The tracked workflow:

1. Get the part geometry and dimensions from the user (or their drawing).
2. Write a spec (or edit the parameter block) - **all lengths in millimetres**.
3. **Run the journal headless** and read its exit code, log and result JSON.
4. **Verify numerically** - a separate journal opens the saved part and compares against analytic
   values you compute yourself.
5. Surface the part in the user's NX if they have one open, then report what was built.

Do not skip steps 3 and 4. They are the difference between this skill and guessing at API calls.

## Environment

Verified on NX 2406. Detect the install rather than hardcoding it:

```bash
echo "$UGII_BASE_DIR"                    # set by NX; typically
                                         #   Windows: C:\Program Files\Siemens\NX<version>
ls -d "/c/Program Files/Siemens/NX"* "/d/Program Files/Siemens/NX"*   # if it is unset
```

Everything below reads `UGII_BASE_DIR` at runtime, so no version is baked into the code. On a
different NX release, re-check the API against that install's stubs (§ "The stubs are the source of
truth") — several builders were renamed between releases.

| Path under `$UGII_BASE_DIR` | What it is |
| --- | --- |
| `NXBIN/ugraf.exe` | the NX GUI |
| `NXBIN/run_journal.exe` | headless journal runner |
| `NXBIN/python/` | bundled CPython 3.10 + the `NXOpen*.pyd` modules |
| `UGOPEN/pythonStubs/NXOpen/*.pyi` | **authoritative API signatures for this exact version** |
| `UGII/templates/model-plain-1-mm-template.prt` | the metric part template |
| `STEP214UG/step214ug.exe` | CLI STEP translator, the working export path |

The bundled interpreter is Python **3.10** and ships **no third-party packages**. Write stdlib-only
journals; there is no `site-packages`. Sibling imports *do* work - `sys.path[0]` is the script's own
directory and `__file__` is defined (verified), which is why `nx_common.py` can be shared.

## The stubs are the source of truth

Signatures differ a lot between NX releases, and snippet code found online is usually for a different
version. When unsure about a call, read the stub for the installed version:

```bash
grep -n "def CreateExtrudeBuilder\|class ExtrudeBuilder" \
  "$UGII_BASE_DIR/UGOPEN/pythonStubs/NXOpen/Features/__init__.pyi"
```

`references/nxopen-api.md` carries the signatures already verified against NX 2406 stubs - check
there first, fall back to grepping the stubs.

## The spec file - how parameters are passed

A spec is a JSON object. Copy `tests/specs/plate_ok.json` as a starting point:

```json
{
  "part_name": "plate_ok",
  "out_dir": "~/nx_out",
  "part": "mounting_plate",
  "params": {
    "plate_w": 200.0, "plate_h": 100.0, "plate_t": 12.0,
    "hole_d": 9.0, "hole_inset": 20.0,
    "bore_d": 40.0, "fillet_r": 8.0
  },
  "export": { "step": true, "log_file": true }
}
```

- **Any subset of `params` may be given**; omitted keys fall back to the journal's built-in defaults.
- `params` must be numbers, not strings. `"plate_w": "200"` is rejected.
- Set a feature off with `0`: `hole_d: 0` skips the corner holes, `bore_d: 0` skips the bore,
  `fillet_r: 0` skips the fillets.
- `export.log_file: false` suppresses the run log; `export.step: false` skips the STEP export.
- **`out_dir` defaults to `~/nx_out`.** `~` and environment variables are expanded, and a relative
  path is resolved against the current directory — which under `run_journal.exe` is the *script's own
  directory*, so prefer `~/something` or an absolute path over a bare name.

**Conflicts are refused before NX is touched** - hole breaking through the edge, holes at or past the
centreline, adjacent holes overlapping, bore overlapping the corner holes, fillet colliding with a
hole, non-numeric values. Each gives a specific message and a non-zero exit.

## Running a journal

```bash
# built-in defaults (equivalent to editing the parameter block in the file)
"$UGII_BASE_DIR/NXBIN/run_journal.exe" build_plate.py

# from a spec
"$UGII_BASE_DIR/NXBIN/run_journal.exe" build_plate.py -args my_spec.json

# the independent check, with the SAME spec
"$UGII_BASE_DIR/NXBIN/run_journal.exe" verify_part.py -args my_spec.json
```

`sys.argv` is clean under `-args`: `[script_path, 'my_spec.json', ...]`. NX does not inject its own
arguments, and quoted values with spaces arrive as one argument (verified).

Inside the GUI the same file runs via **Developer > Play** (older UIs: Tools > Journal > Play, or
File > Execute > NX Open). Recorded journals default to another language - set
**File > Preferences > User Interface > Journal Language = Python** to record in Python.

Prefer running headless yourself: you can iterate on errors in seconds that way.

## What a run produces, and how you know it worked

Four files land in `out_dir`, all named after `part_name`:

| File | Notes |
| --- | --- |
| `<name>.prt` | the part |
| `<name>.step` | AP214 solid, via the CLI translator |
| `<name>.run.log` | the full run log - **not** `.log` |
| `<name>.result.json` | machine-readable outcome: status, params, checks, files, errors, seconds |

`verify_part.py` writes `<name>.verify.result.json` instead, so it never clobbers the build's result.

Two more files are `step214ug.exe`'s own doing, not ours: `<name>.log` and `ugstep214.log`. The
translator is run with its working directory set to `out_dir` on purpose - otherwise it scatters those
sidecar logs into the skill's `scripts/` directory, because it writes them by relative path.

**Exit code is the contract.** 0 = built and self-checked; non-zero = something failed. Note that
under `run_journal.exe` the *exact* code is not propagated - `sys.exit(3)` surfaces as 1 (verified) -
so read `result.json` for detail rather than distinguishing failures by number. A failed run always
has `"status": "failed"` and a non-empty `errors` array.

The run log is deliberately not `<name>.log`: `step214ug.exe` writes its own sidecar log at that path
next to the `.step`, and holding a handle to the same file breaks the export.

Self-check failures are reported, not swallowed: a wrong volume, a wrong face count, a missing body,
a save that wrote nothing, or a geometry-less STEP all become errors that fail the run. This matters -
before, a degenerate part could exit 0 and look fine.

## Verify the output, don't trust the exit code

`run_journal.exe` exits 0 even when a feature silently did nothing, and an export can write a
plausible-looking file with no geometry in it. **Never report a file as produced on the strength of it
existing.** Open it and measure.

`verify_part.py` runs as a **separate journal** opening the saved `.prt` - checking inside the build
journal hides errors, because the in-memory body can differ from what was written. Give it the same
spec so the expected values come from the same function the build used, and it cannot drift.

Expected values for the built-in defaults, computed by hand:

| Variant | Volume (mm³) | Faces |
| --- | --- | --- |
| 120x80x10, 4x D6.6, D30 bore, no fillet | 87562.939 | 11 |
| the same with R8 corner fillets | 87013.558 | 15 |
| `tests/specs/plate_ok.json` (200x100x12, 4x D9, D40, R8) | 221207.470 | 15 |

Face count catches what volume can miss: if you expected fillets and got 11 faces instead of 15, they
never applied. `verify_part.py` also counts cylindrical faces (holes + bore + fillets), which is the
quickest way to spot a missing hole.

## Tests

```bash
python tests/run_tests.py          # ~3.5 min, needs NX installed; any Python 3
python tests/run_tests.py T4       # one test by prefix
```

Seven tests cover the no-argument path (backward compatibility), a spec-driven build with an
**independently** computed volume, the verifier agreeing, the verifier *rejecting* a part built to
other dimensions (the negative control - without it a verifier that always passes looks green), each
parameter-conflict class, missing/malformed spec files, and STEP content. Exit code 0 = all passed.
Run it after touching any script.

## Showing the part in the user's open NX session

A journal builds a file; it does not appear in a window the user already has open. If they expect to
see it - and they usually do - the shell opens it into the running session:

```bash
cmd //c start "" "C:\path\to\part.prt"
```

Verified: this loaded the part into the **already-running** NX 2406 session (no second `ugraf.exe`
process) and it became the displayed part. Use it after every build rather than telling the user to go
find the file.

Do not try to open it from NX's own UI. `Ctrl+O` is swallowed, and the `文件` backstage plus the
`菜单(M)` pull-down are invisible to both screenshots and accessibility. See the `nx-gui` skill for
what is and is not drivable by hand.

## Non-negotiable rules

These cause almost every failure. Each has a reason, not just a rule:

**1. Lengths go through the expression string, never a float.**
`ExtrudeBuilder.Limits.EndExtend.Value.RightHandSide = "25"` and `Diameter.SetFormula("20")`.
Assigning the float `.Value` on a length applies a silent 25.4× unit conversion. Values are in
**base part units** - millimetres only because you created a metric part.

**2. Keep the objects the API returns; select geometry by shape, not by index.**
There is no clicking in a script. `CommitFeature()` returns the feature; `feature.GetBodies()[0]`
gives you the solid to pass into the next builder's `BooleanOperation.SetTargetBodies([body])`.
`body.GetEdges()[3]` is not stable across rebuilds - filter by geometry instead.

**3. Re-fetch geometry after every update.**
Call `session.UpdateManager.DoUpdate(mark)` after each `CommitFeature()`. The model does not advance
until you do, and a `Face`/`Edge` reference held across a rebuild can go stale. One undo mark per
logical step.

**4. Import all `NXOpen.*` submodules at module top.**
`import NXOpen.Features` inside a function makes `NXOpen` function-local and the next call fails with
"cannot access local variable 'NXOpen'".

**5. Write floats as floats.**
`Point3d(0.0, 0.0, 0.0)`, not `Point3d(0, 0, 0)` - integers raise "Expecting double".

## Files in this skill

| File | Read it when |
| --- | --- |
| `references/nxopen-api.md` | you need an exact signature or enum for NX 2406 |
| `references/recipes.md` | you need the code shape for sketch, revolve, hole, blend, chamfer, pattern, boolean, measure, or the geometry-selection helpers |
| `references/pitfalls.md` | something failed and you want the cause - error strings are indexed here |
| `scripts/nx_common.py` | the shared spec loader, validator, logger, and the analytic metrics both journals use |
| `scripts/build_plate.py` | copy this to start a new part; parameter block at the top, spec-driven |
| `scripts/verify_part.py` | measuring a finished part against its spec |
| `scripts/check_step.py` | proving a STEP export actually contains geometry |
| `tests/run_tests.py` | regression suite; run it after any change to a script |
| `tests/specs/*.json` | working examples, including five that must be rejected |

## Reporting back

Tell the user: the dimensions used, the paths of the `.prt` and `.step`, the measured volume against
the analytic value, and whether `result.json` says `ok`. Say which parts you actually ran versus which
you only wrote. If a feature is unverified, say so explicitly rather than implying it works - the user
would rather hear "the fillet is unverified" than discover it later.

When you hand over a `.step`, quote what `check_step.py` reported - "1 solid, 15 faces" - not just
that the file is there.
