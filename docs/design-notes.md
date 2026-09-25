# Design notes

Why this code looks the way it does. Several things here look over-cautious or outright odd until you
know what they cost to find. If you are changing something, start here — the entries below are the
ones that will silently break behaviour rather than fail loudly.

Everything was measured on **NX 2406** on Windows.

---

## 1. STEP export must not use the in-process Dex API

`DexManager.CreateStepCreator()` looks like the right call. It validates (`Validate()` returns
`True`), commits without raising, and writes a file of plausible size — **containing no geometry**:
0 `MANIFOLD_SOLID_BREP`, 0 `ADVANCED_FACE`, 1 `CARTESIAN_POINT`.

Reproduced across every `ExportAs` (`Ap203`/`Ap214`/`Ap242`), every `ExportFrom`
(`DisplayPart`/`ExistingPart`), and every `SelectionScope` including an explicit
`SelectionComp.Add(body)`. IGES fails identically, so the whole in-process Dex layer emits nothing
under `run_journal.exe`.

The working path is the CLI translator that NX itself drives for *File > Export > STEP*:

```
$UGII_BASE_DIR/STEP214UG/step214ug.exe <part.prt> o=<out.step> l=<out.log> d=<ugstep214.def>
```

Two details that are easy to get wrong:

- **It must be launched from inside the journal.** Started from a plain shell it dies on
  `libccov.dll`, because the NX runtime directories are not on `PATH`.
- **It must be launched with `cwd=<out_dir>`.** It also writes a second log by a *relative* path, so
  running it from the script directory scatters `ugstep214.log` there.

**The lesson generalises:** prove an exporter by opening its output and counting the geometry in it.
File existence proves nothing — the empty shell and a real export are both plausible `.step` files.

## 2. Our run log is `<name>.run.log`, not `<name>.log`

`step214ug.exe` owns `<name>.log` as its sidecar. Holding a file handle to that same path breaks the
export:

```
PermissionError: [WinError 32] The process cannot access the file because it is
being used by another process
```

The collision existed before there was a log file of our own — it was latent until the run log
started holding a handle.

## 3. Failure must be visible, and exit codes cannot carry the detail

`run_journal.exe` exits 0 even when a feature silently did nothing. Before this design, a degenerate
parameter set produced a wrong solid, printed the discrepancy in its own log, and returned **exit 0**
— so any caller reading only the exit code treated it as fine. That is the single most dangerous
behaviour this code exists to prevent.

Measured exit-code behaviour:

| How it fails | Shell exit code |
| --- | --- |
| reaches the end normally | 0 |
| `sys.exit(3)` | **1** (the number is not propagated) |
| raises an exception | 1 |
| `os._exit(4)` | 4 — exact, but skips NX teardown, so deliberately unused |

So the exit code is a **binary** signal, and `<name>.result.json` carries the detail (`status`,
`errors[]`, `checks`, `files`). Do not try to encode error classes in exit codes; do not remove the
result file.

## 4. Lengths must go through the string form

```python
ext.Limits.EndExtend.Value.RightHandSide = "25"      # correct
cyl.Diameter.SetFormula("20")                        # correct
ebb.AddChainset(col, "8")                            # radius is a str too

ext.Limits.EndExtend.Value = 25                      # WRONG: silent 25.4x conversion
ext.Limits.EndExtend.Value = depth                   # equally wrong
```

`Expression.Value` is in **base part units** and is part-specific: millimetres only because the part
was created metric. The stubs themselves advise against `Expression.Value` in new code (angle
expressions break it). Note that assigning a *variable* is just as wrong as assigning a literal —
this is why a check that only looks for numeric literals misses it.

## 5. NX fails through renames, so read the stubs

Signatures differ between NX releases and snippet code found online is usually for a different one.
The authority is your own install:

```bash
grep -n "def CreateExtrudeBuilder\|class ExtrudeBuilder" \
  "$UGII_BASE_DIR/UGOPEN/pythonStubs/NXOpen/Features/__init__.pyi"
```

APIs that do **not** exist on NX 2406, though older code and blog posts use them:

| Not present | Use instead |
| --- | --- |
| `DexManager.CreateStep214Creator`, `Step214Creator` | `CreateStepCreator()` + `ExportAs` — or better, the CLI translator (§1) |
| `SketchCollection.CreateSketchInPlaceBuilder` | `...Builder2` / `CreateNewSketchInPlaceBuilder` / `CreateSimpleSketchInPlaceBuilder` |
| `CreateRuleBaseCurveDumb` | `CreateRuleCurveDumb` |
| `len(part.Bodies)` | collections have no `__len__` — use `[b for b in part.Bodies]` |

`EdgeBlendBuilder.AddChainset` takes `(collector: ScCollector, radius: str)` — **not**
`(edge, index)`.

## 6. The model does not advance until you update it

`session.UpdateManager.DoUpdate(mark)` after every `CommitFeature()`. Skip it and later features
attach to stale geometry and fail confusingly. One undo mark per logical step keeps a multi-feature
journal debuggable.

Select geometry **by shape, never by index** — `body.GetEdges()[3]` is not stable across rebuilds.
The vertical-edge helper in `references/recipes.md` exists for exactly this.

## 7. Verify from a separate process

`verify_part.py` runs as its **own** journal opening the saved `.prt`, because the in-memory body can
differ from what was written to disk. Checking inside the build journal hides the errors you are
looking for.

Expected values come from the same analytic function the build self-check uses (`plate_metrics`), so
the two cannot drift. Face count catches what volume can miss: the sample plate has 11 faces
un-filleted and 15 with corner fillets — if you expected fillets and got 11, they never applied.

## 8. Running a journal: the environment facts

Probed rather than assumed:

- `sys.argv` is clean under `-args`: `[script_path, 'spec.json', ...]`. NX does **not** inject its own
  arguments, and a quoted value with spaces arrives as one argument.
- `__file__` is defined and `sys.path[0]` is the script's own directory, so a **sibling import
  works**. That is why `nx_common.py` can be shared rather than duplicated.
- The interpreter is CPython **3.10 with no `site-packages`** — stdlib only, no pip. Do not repackage
  into a module tree with relative imports.

## 9. Testing habits that keep the suite honest

- **Assert on `result.json`, not on stdout.** A journal can print cheerful lines and write the wrong
  solid.
- **Reset the result file before asserting.** A run that fails to write its result would otherwise be
  graded against the previous run's file, and a broken build would pass.
- **Keep the negative control.** One test verifies that a part built to different dimensions is
  *rejected*. Without it, a verifier that always passes looks green.

## 10. Driving the GUI is a different problem (see `nx-gui`)

Measured on NX 2406, and this shapes what `nx-gui` can do:

- The **ribbon is custom-drawn**. Accessibility sees opaque `pane` nodes with no actions, so ribbon
  commands need **coordinate** clicks.
- The ribbon is left-aligned and top-anchored at fixed offsets in **native** pixels, while a
  Computer Use screenshot is a downscale of the window. Coordinates must be derived as
  `native_anchor × (raster_size / window_size)` every time. A stored table of raster coordinates
  breaks silently whenever the window is resized.
- **Pull-down menus, dropdown contents and graphics-area filter bars are invisible to both
  screenshots and accessibility.** Commands behind them are not automatable — hand them to the user.
- Dialogs opened from the ribbon *are* ordinary native controls, fully readable and writable.
- `Ctrl+O` and `Ctrl+Z` do nothing in the main window; `Escape` works. `Escape` does not necessarily
  unwind a whole task.

One more environment trap worth knowing: on a 2560×1440 display the raster came back capped at
1280×768 — a **2× downscale**, which put the ribbon's tab row and its tool row about **9 pixels
apart**. A small misreading then lands on the neighbouring tab.

---

## Verified vs unverified

Kept honest on purpose, so nobody builds on sand.

**Verified by running it:** the build → self-check → save → STEP chain; volumes matching analytic
values exactly (87562.939 / 11 faces and 87013.558 / 15 faces); the test suite; the `-args` argv
shape; sibling imports; exit-code behaviour; conflict rejection for five classes with no files
produced; and, for `nx-gui`, that ribbon clicks open the intended dialog, that dialogs are fully
readable/writable, that graphics face picks work, and that a sketch can be created end to end.

**Not verified:** anything about drafting (there is none); the `绘制截面` route past the point where
the sketch opens; extrude-section selection from existing sketch curves; and the
`UGII_BASE_DIR`-missing guard, which cannot be exercised end to end because `run_journal.exe` always
sets that variable — it was unit-tested by calling `base_dir()` from plain Python instead.
