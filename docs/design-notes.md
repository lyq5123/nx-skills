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

Expected values come from the same analytic function the build self-check uses - `nxc.part_metrics`,
which dispatches to the recipe registered for the spec's shape - so the two cannot drift. That is also
why a new shape must arrive with its formula: the verifier measures against it. Face count catches what volume can miss: the sample plate has 11 faces
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

## 11. A part as a list of operations, and how to verify one

`composed` (in `nx_compose.py` + `build_composed.py`) executes a feature list instead of hard-coding a
shape. Four things in it were learned the hard way.

**A circle is not a polygon.** The reference volume for a feature list is a Monte-Carlo sample, and a
sample needs a yes/no inside test — so a hole was first modelled as a 48-sided polygon. Handing that
same polygon to NX built a **faceted prism where a cylinder belongs**: `cylindrical faces = 0`, and the
volume was off by only 0.003%, which no volume check would ever have noticed. The fix is two-track —
NX gets a real 360° arc, the sampler gets an exact **disc** test. The lesson generalises: a numerical
reference and the geometry it is compared against must not share an approximation. What caught it was
the *topology count*, not the number.

**Blends cannot be in the reference, so they cannot be silently absent either.** No closed form covers
an arbitrary set of rounded edges, so the sampler ignores blends and chamfers entirely. Left there, a
heavily rounded part would fail the volume check for being correctly rounded, and a part whose blend
never applied would pass looking perfect. So the build measures what each round actually removed,
requires it to be **greater than zero**, adds it back before the volume comparison, and prints it. That
catches "the feature did not apply"; it cannot catch "it applied to the wrong edges" — which is a
reading of the drawing, and is stated as the user's call rather than dressed up as verification.

**Tolerance belongs to the recipe, not to the checker.** The named recipes have closed forms and agree
with NX to ~1e-11; the composed one is sampled and deserves ~1%. `register(..., tolerance=...)` carries
that, and the self-check and the independent verifier both read it. One constant for all shapes would
either fail every composed build (1e-9) or let a wrong named-shape build pass (1%).
`verify_part.py` prints the band when it is loose, so "delta 2657" is not read as a near miss on a
shape whose whole allowance is ±2326.

**A spec that states a contradiction is rejected, not overruled.** `"op": "boss", "mode": "cut"` and
`"hole", "mode": "add"` are refused. Rewriting the mode silently is the wrong default: someone who
wrote the opposite of what the shape does was thinking of something else, and quietly building what
they did not ask for is how a drawing gets misread without anyone noticing. The same reason puts
`"through": true` off limits for anything that adds material — an addition with no end extends without
limit, and the sampler would have filled its entire bounding box with solid.

## 12. An assembly is not a part, so it is verified differently

`build_laptop_stand_kit.py` places verified pieces into two assembly files - one in working position,
one exploded along the plate normal. Five things the first live run taught, none of them obvious from
the API stubs:

- **An assembly has no volume of its own.** Every other shape here is verified by measuring the solid
  the kernel produced; a kit cannot be. `verify_kit.py` opens the SAVED assemblies and checks
  **component counts and names** instead, and the pieces are measured individually by
  `verify_part.py` - so the pieces carry the numeric proof and the assembly carries the structure.
- **`OpenBaseDisplay` on a file that is already open raises "File already exists".** A kit that places
  the same rib twice and the same screw four times must cache loaded parts and reuse them.
- **NX uppercases component names.** Compare `.upper()` when checking them.
- **`Matrix3x3` columns are the images of the local axes**, so column 3 maps local +Z. With the screw's
  shank modelled along local −Z, the shank direction is *minus* column 3 - test the column, not the
  row index that happens to look like Z.
- **Placement is by coordinate, not constraint solving.** Origins and orientations are derived from the
  same recipe geometry the pieces were built to, so the screws land in their holes by construction and
  the positions stay exact no matter how the assembly is manipulated afterwards - while the components
  remain freely removable in the GUI.

The joint itself is where the design work went, and it is a reminder that a fastener is a *system*:

- **Pockets in the plate's top face beat countersinks.** A 45-degree seat needs the head cone to match
  and sat 0.85 mm proud; a flat D9x3 pocket puts the head flush so the laptop slides over it.
- **The under-head length must exceed plate thickness + tap depth with at least 1 mm spare.** A 16 mm
  screw was 2 mm short of making the joint; 20 mm works.
- **Overlapping removals break an analytic volume.** A D5.5 through-hole only cuts material *below* the
  D9 pocket, so its term is `pi*r^2*(plate_t - pocket_h)` and not `pi*r^2*plate_t`. And a side-edge
  blend sat exactly where the pockets are cut, so the kit plate keeps only the lip's top-edge blend.
  Both were caught by the volume not matching, not by looking at the model.
- **The fastener constants are deliberately not spec'd.** They form a system, and letting a spec change
  one silently breaks the joint - so the validation rules enforce the joint, not just the piece.

---

## Verified vs unverified

Kept honest on purpose, so nobody builds on sand.

**Verified by running it:** the build → self-check → save → STEP chain; volumes matching analytic
values exactly (87562.939 / 11 faces and 87013.558 / 15 faces); the test suite; the `-args` argv
shape; sibling imports; exit-code behaviour; conflict rejection for five classes with no files
produced; and, for `nx-gui`, that ribbon clicks open the intended dialog, that dialogs are fully
readable/writable, that graphics face picks work, and that a sketch can be created end to end.

**Verified for the stand and the knock-down kit:** the inclined stand (three XZ profiles along Y,
united face to face) at 790296.093 mm^3 / 22 faces / 6 cylinders, delta 0.0000; the kit's plate
644384.609 / 22 faces, rib 120883.479 / 11, screw 524.829 / 12, each delta 0.0000; the assembled kit
and its exploded twin placed by coordinate - `verify_kit` VERDICT OK on both, with the seven components
(1 plate + 2 ribs + 4 screws) counted in the saved files.

**Verified for `composed`, against hand-computed numbers:** a 200x160x20 plate, a blend on the four
corner edges found by selector (removed 2472.213, hand value 2472.213), a D16 cross hole along Y
(32169.909 vs 32169.911), a D55 boss (11879.147 vs 11879.147), and a C3 chamfer on one edge of the
boss's own edge set (749.270) — total within 0.002 mm^3 of the independently computed volume, with
`Feature.GetEdges()` still returning a feature's own edges after later booleans. The **sampled**
reference for that part is 619145 +/- 2326.

**Not verified for `composed`:** whether a *selector* names the edges the drawing intends (only that
it matched some edge, and that rounding them removed material); the ordering of operations that cut
and re-fill the same region in ways the sampler and the kernel could disagree about; and any part whose
sampled reference lands near the 1% boundary, where the answer is "rerun with more samples", not a
verdict.

**Not verified:** anything about drafting (there is none); the `绘制截面` route past the point where
the sketch opens; extrude-section selection from existing sketch curves; and the
`UGII_BASE_DIR`-missing guard, which cannot be exercised end to end because `run_journal.exe` always
sets that variable — it was unit-tested by calling `base_dir()` from plain Python instead.
