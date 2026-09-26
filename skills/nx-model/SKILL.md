---
name: nx-model
description: Build parametric 3D parts in Siemens NX (formerly UG / Unigraphics) by generating an NX Open Python journal, running it headless, and verifying the result numerically. Use when the user wants a part or a .prt/.step file produced from given dimensions, wants the same part rebuilt at new sizes, wants a batch of parts, hands over a drawing, photo or screenshot to model from (照着图纸建模, 按图做零件), or wants an existing NX journal parameterized or debugged - including when they only describe the part in plain words without naming NX Open. Do NOT use this to drive the NX GUI by hand; use the nx-gui skill when the user wants to watch the model being built in their open NX session or asks you to operate NX's interface.
---

# NX parametric modeling

You build NX parts by **writing an NX Open Python journal, running it, and measuring the result**.
A model that merely "ran without error" is not a deliverable; a model whose volume and topology
match the hand-computed values is.

**Route check before you start.** This skill builds geometry headlessly and then **opens the result in
the user's NX session** (step 5) - so the user does end up looking at the part, with its feature tree,
without anyone clicking through NX. What it does *not* do is animate the build: if the user wants to
watch features appear one at a time, or asked you to "operate NX", that is the `nx-gui` skill instead
(read its limits first - menus and dropdowns are not automatable, and no in-session playback API
exists). Otherwise you are in the right place.

The tracked workflow:

1. Get the part geometry and dimensions from the user (or their drawing).
2. Write a spec (or edit the parameter block) - **all lengths in millimetres**.
3. **Run the journal headless** and read its exit code, log and result JSON.
4. **Verify numerically** - a separate journal opens the saved part and compares against analytic
   values you compute yourself.
5. **`python show_in_nx.py <spec>`** so the part appears in the user's NX, then report what was built.

Do not skip steps 3, 4 or 5. 3 and 4 are the difference between this skill and guessing at API calls;
5 is the difference between handing someone a filename and showing them the part.

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

## Building from a drawing, a photo or a screenshot

Triggered by things like "照着这张图建模", "按图纸做", or any request that hands over a drawing rather
than a list of numbers.

**Reading the drawing is your job, not this skill's.** The code's input is numbers; keep it that way.
Do not try to make the journals read an image: NX ships CPython 3.10 with **no `site-packages`**, so
there is no PIL/OpenCV/Tesseract to call, and engineering drawings carry tolerances, thread callouts
and GD&T that generic OCR reads unreliably. A model reads a drawing well; deterministic code should
stay deterministic.

### The blind spot you must cover yourself

**The verifier cannot catch a misread dimension.** It compares what NX measured against the analytic
value computed *from the same spec*. Read 120 as 210 and both sides move together: the run stays
green, the volume "matches", and the part is wrong. Verification proves *NX faithfully built what you
wrote* - never that what you wrote matches the drawing.

Only you can close that gap, and only by checking with the user.

### Mandatory: transcribe, then confirm, then build

1. **Write out every dimension as a table** before touching the skill - parameter name, value, unit,
   and where on the drawing it came from (view, title block, callout).
2. **Show it to the user and get confirmation.** Do not build first and report after.
3. **Anything illegible is a question, not a guess.** List it and ask. Never round to a "sensible"
   value, and never infer a dimension the drawing does not state.

### Cross-checks to run while transcribing

These catch a real share of misreads, and they are free:

- **Chain vs overall.** A string of segments must sum to the stated overall dimension.
- **Same dimension twice.** If a size appears in a view and again in the title block, they must agree.
- **Count consistency.** `6×` on a bolt circle means six positions; the number of hole callouts must
  match the number of holes you wrote into the spec. On a plate the verifier's *cylindrical face
  count* is a partial check on this after the build.
- **Symmetry.** A part that is obviously symmetric should yield symmetric numbers; if one inset is 12
  and its mirror is 21, you transposed digits.
- **Unit sanity.** Find the drawing's unit note (mm vs inch) and check plausibility: a 120 mm plate is
  not 120 inches, and a thickness should be small relative to length.
- **Never scale off the pixels.** Printed dimensions only. A photo's pixel measurements mean nothing
  without a known scale and an undistorted view.

### If the drawing is not a supported shape, say so first

This skill currently has exactly one geometry recipe - the rectangular plate with corner holes, a
central bore and corner fillets (see `references/` and `nx_recipes.py`). If the drawing is a flange,
a bracket, a turned part, or anything with a pocket, step or slot, **stop and say that before doing
any work**: no amount of careful transcription will build it. Adding a shape means adding a recipe -
geometry formula, validation rules and a builder - not editing the existing ones.

### When reporting a finished part

Put the measured values next to the drawing's values so a discrepancy is visible at a glance: the
overall size, the feature count, and the volume the verifier computed. And state plainly which
dimensions you read off the drawing versus which the user supplied as numbers.


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

A journal builds a file; it does not appear in a window the user is looking at. **Always close that gap
after a successful build and verify** - it is a documented step, not an afterthought:

```bash
python show_in_nx.py my_spec.json      # or: python show_in_nx.py path/to/part.prt
```

It resolves `out_dir`/`part_name` from the spec and hands the `.prt` to the operating system
(`os.startfile`, with `xdg-open`/`open` fallbacks), so **NX opens it in the session already running** -
or starts NX if none is. Plain Python 3, no `NXOpen` import, no Computer Use, no clicking: any agent
that can run a command can do this. Verified - NX shows the part in the graphics area with its full
feature tree in the part navigator (`模型历史记录 → 拉伸(0) → 拉伸(1) → 边倒圆(2)` for the sample plate).

### Why not drive NX's own UI for this

Three separate dead ends, all measured; do not spend time rediscovering them:

- **NX exposes no API to start journal playback in a live session.** `JournalManager` has
  `IsJournalRunning` / `StartRecordingJournal` / `PauseJournal` - and no `PlayJournal`/`ExecuteJournal`.
- **`run_journal.exe` cannot attach to a running session.** Its options are `-pim`, `-r=`, `-args`,
  `-allow_redo`, `-help`; every one of them runs a *separate* batch session.
- **NX's `Ctrl+O` is swallowed, and the `文件` backstage / `菜单(M)` pull-down are invisible** to both
  screenshots and accessibility. The `nx-gui` skill has the full capability matrix.

### Watched-building vs. appears-finished - be straight with the user

Opening the part shows the **finished model and its feature tree**, not the features appearing one at a
time. Nothing in this skill can animate it: playback needs a GUI trigger, which means either a user
action (Developer > Play) or desktop automation that only works if the calling agent has Computer Use.
Do not promise a live, animated build - describe what the user will actually see.

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
| `scripts/show_in_nx.py` | opening the built part in the user's NX (run with plain Python, not as a journal) |
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
