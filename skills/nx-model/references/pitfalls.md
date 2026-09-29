# Pitfalls, indexed by symptom

Find your error string, read the cause. The NX error text is usually the fastest route to the fix,
so always log the exact string rather than a generic "failed".

## "Expecting double"

An integer was passed where a float is required. `NXOpen.Point3d(0, 0, 0)` fails;
`NXOpen.Point3d(0.0, 0.0, 0.0)` works. Same for arc radii and angles. Python has no implicit
numeric coercion across the binding boundary - write every literal as a float.

## Model is 25.4x too big or too small

You assigned a float to a length's `.Value` instead of setting the expression string.
`Expression.Value` is in base part units and assigning it on a length triggers a conversion.
Always drive lengths as strings:

```python
ext.Limits.EndExtend.Value.RightHandSide = "25"
cyl.Diameter.SetFormula(str(d))
ebb.AddChainset(col, "8")                 # radius here is a str too
```

Related: "base part units" are **part-specific**. The number 25 means mm in a metric part and inches
in an inch part. `NewBaseDisplay`/`FileNew` with `Millimeters` is what makes mm true.

## "Second parameter is invalid" from NewBaseDisplay / NewDisplay

You passed the wrong units enum. `NewBaseDisplay` wants `BasePart.Units`, `NewDisplay` wants
`Part.Units`. Same member names, different types. Pick the one matching the method you called.

## "cannot access local variable 'NXOpen'"

An `import NXOpen.Something` appears inside a function, which shadows the module-level `NXOpen` for
that scope. Move **all** `NXOpen.*` imports to the top of the file.

## Feature "succeeded" but the solid is unchanged / a body is missing

Two usual causes:

1. `CommitFeature()` was not followed by `session.UpdateManager.DoUpdate(mark)`. The model does not
   advance until you update, so the next feature attaches to stale geometry.
2. A boolean feature (extrude-subtract, cylinder-unite, hole) got no target body.
   `BooleanOperation.SetTargetBodies([body])` is required for every feature except the first solid.

Check `[b for b in part.Bodies]` when you expect exactly one solid - an untargeted boolean leaves
orphans. Do not reach for `len()`; see the entry on it below.

## "Missing target body"

`SetTargetBodies` was skipped or given `NXOpen.Body.Null` on a non-first feature. `Body.Null` is only
correct for the very first solid feature (with `BooleanType.Create`).

## "Tolerance error" / "Angle tolerance is too small"

A builder defaulted to a zero tolerance and you never set it. Set `HolePackageBuilder.Tolerance = 0.01`
and `Draft.FrontDraftAngle`-style angles to something nonzero. Section tolerances
`CreateSection(0.0095, 0.01, 0.5)` are the recorded values.

## "Tolerance Specification requires three numbers"

Hole-package geometry ambiguous. For a through-hole use `HoleDepthLimitOption = Value` with a
diameter, a depth and a tip angle all set, or sidestep it entirely with a subtract extrude.

## A retried builder fails with a confusing follow-up error

A builder whose `Commit()` raised is **poisoned** - reusing the same object fails again differently.
Recreate the builder from scratch. Same for the session after "Modeler error: please report fault" -
that one is unrecoverable and needs an NX restart.

## A builder object can't be reused after Destroy()

`builder.Destroy()` after `CommitFeature()` is correct and necessary, but then the builder is gone.
Create a fresh one for the next feature even if the parameters are identical.

## Faces/edges selected by index give the wrong result after a rebuild

`body.GetFaces()[0]` and `body.GetEdges()[3]` are not stable. Classify geometrically - see the
`vertical_edges` helper in `recipes.md` - and assert the count you expected before using the list.
Also re-fetch faces/edges **after** the `DoUpdate` that created them; references held across a
rebuild can be stale.

## The .step file exists but contains no geometry

The most dangerous failure in this skill, because everything looks fine: the creator validates
(`Validate()` returns True), commits without raising, and writes a plausible-sized file. Open it and
you find 0 `MANIFOLD_SOLID_BREP`, 0 `ADVANCED_FACE`.

`DexManager.CreateStepCreator()` + `Commit()` **does not export solids under `run_journal.exe`.**
Reproduced on a plain `BlockFeatureBuilder` solid with no construction curves, across
`ExportAs` Ap203/Ap214/Ap242, `ExportFrom` DisplayPart/ExistingPart, every `SelectionScope`
including explicit `SelectionComp.Add(body)`, with and without `ExportDestination`. IGES fails the
same way.

Fix: run the bundled CLI translator from inside the journal - see the STEP section of
`nxopen-api.md`, or just call the `export_step()` helper in `scripts/build_plate.py`.

Then prove it:

```bash
python scripts/check_step.py out/part.step     # exit 0 = geometry present
```

## "the export must have worked, I just checked the file too early"

This theory is how the empty-export bug above stays hidden, so be suspicious of it. Yes, some NX
output is flushed asynchronously seconds after the journal process exits, so an early `os.path.exists()`
can report False on a good export. But the same early check reports True on an empty one.

The CLI translator in `scripts/build_plate.py` is driven by `subprocess.run(...)`, which does not
return until the translator has finished - so with the recommended path there is no timing game at
all. If you are on the recommended path, the file being absent means the translation failed; read
its log. Either way: **open the file and count the solids.**

## `len(part.Bodies)` raises TypeError

Collections are not sized. `object of type 'NXOpen.BodyCollection' has no len()`. Use
`[b for b in part.Bodies]`, `part.Bodies.GetData()`, or `.Length`. This matters because it fails
*after* your features committed - so a script that measured fine can die before it saves.

## `CreateStep214Creator` / `Step214Creator` does not exist

Old-NX API (NX 10/11); the `ExportAs` enum replaced it. But do not "fix" this by switching to
`CreateStepCreator()` - that is the path that silently writes empty files. Use the CLI translator
(`$UGII_BASE_DIR/STEP214UG/step214ug.exe`), which is the working export on NX 2406.

## `CreateSketchInPlaceBuilder` does not exist

Also old API. Use `CreateSketchInPlaceBuilder2`, `CreateNewSketchInPlaceBuilder`, or
`CreateSimpleSketchInPlaceBuilder`.

## `EdgeBlendBuilder.AddChainset(edge, index)` fails

Wrong overload. The signature is `AddChainset(collector: ScCollector, radius: str)`. Build an
`ScCollector`, `ReplaceRules([CreateRuleEdgeDumb(edges)], False)`, then add the chainset with a
string radius.

## `CreateRuleBaseCurveDumb` is deprecated

Use `CreateRuleCurveDumb`. The `Base` spelling is the legacy name.

## The script does nothing when run, with no error

Likely nothing is open: `session.Parts.Work` is `None`. Guard it and create or open a part first.
Under `run_journal.exe` there is no graphics window, so any view/screenshot work silently has
nowhere to go - that is expected, not a bug.

## Runs fine headless, fails in the GUI (or vice versa)

The API is identical; the environment is not. Headless has no graphics window and no display part
until you make one. Conversely a GUI session may already have a part open, so `NewBaseDisplay` on an
existing path fails - delete the target file first. Make journals independent of what is already
open.

## `run_journal.exe` exits 0 but the model is wrong

Exit code reflects whether the journal raised, not whether the geometry is right. A feature can
silently no-op. Always measure volume and face count and compare against analytic values
(`recipes.md`). This is the single most valuable habit in this skill - and it applies to exports
too: a `.step` that exists is not a `.step` that has a solid in it.

## Numbers are right but the part looks wrong in NX

Check the direction sense of the extrude. `CreateDirection(origin, Vector3d(0,0,1), ...)` extrudes
toward +Z from the curve plane. Curves at Z=0 with a start limit of "-1" and an end above the body
is the safe overshoot pattern for cuts. Also confirm the part was created metric.

## Which Python version do I have?

NX 2406 bundles CPython 3.10 (`NXBIN/python/python310.dll`). No `site-packages`, so third-party
imports fail. To use numpy etc. you must point NX at a matching external interpreter via
`UGII_PYTHON_LIBRARY_DIR` / `UGII_PYTHONPATH`, and the **minor version must match** or you get
"Error loading libraries needed to run a journal". For modeling work, stdlib is enough - do not
introduce that dependency.

## A run whose result file cannot be written used to exit 0

`result.json` is the caller's only verdict - `run_journal.exe` turns any `sys.exit(n)` into exit 1,
so the exit code carries no detail and an agent reads the JSON. `write_result()` removed the old file
before renaming the new one over it, and `finish()` ignored its return value. So if the delete was
refused (read-only directory, the `.prt` held open by the user's own NX session, a sandbox without a
recycle bin), the OSError was swallowed, the **previous** run's `{"status": "ok"}` stayed on disk,
and the process exited 0. The caller then reads a stale green verdict that may describe entirely
different dimensions - the exact "it ran fine and the model is wrong" failure this skill exists to
prevent.

Fixed 2026-09-29: `os.replace()` overwrites atomically with no separate delete step, and `finish()`
exits non-zero when the write did not land, even with a clean geometry log. Guarded by
`tests/test_output_contract.py` (6 tests, no NX) - one of them makes the destination a *directory*,
so it holds for any implementation that fails, not just the one that shipped.

## `os.remove` refusal during the test suite aborted tests before they ran

Symptom: several tests ERROR at **0.0 s** with an `OSError` from the cleanup, which reads like a
geometry failure while nothing was actually built. The suite deletes the previous run's artefacts
before each test precisely so a stale one cannot mask a failure, so the cleanup must not be the thing
that breaks.

Observed 2026-09-29 in a sandbox whose recycle bin is unavailable (`[safe-delete]
[SAFE_DELETE_FAIL_CLOSED] ... windows-sandbox-recycle-bin-unavailable`); it does not reproduce in a
normal Windows session, where `os.remove` always succeeds. Mitigated rather than merely tolerated:
`reset_result()` now **poisons** the stale result with a `{"status": "stale"}` sentinel when the
delete is refused (silently skipping the delete would defeat the function), `discard()` returns the
mtime so T1 can require the file to have been *rewritten* rather than merely present, and the
sentinel writer is itself guarded so a doubly-refused cleanup reports instead of raising. If this
error returns, look for a new bare `os.remove` in the harness, not for a geometry bug.

## `/c/Users/...` reaches Windows Python when MSYS path conversion does not run

The plain-Python helpers (`check_step.py`, `show_in_nx.py`) take a path straight from `sys.argv`.
Under Git Bash, MSYS normally rewrites a `~`-expanded argument into `C:/Users/...` and everything
works - verified here on 2026-09-29. It goes wrong when that conversion is off: with
`MSYS_NO_PATHCONV=1` or `MSYS2_ARG_CONV_EXCL` set, or when the argument passes through a wrapper that
skips it, Python receives the POSIX form `/c/Users/lu/nx_out/part.step`, resolves it against the
current drive and looks for `C:/c/Users/...`, which does not exist. The file is there; the argument is
wrong. Reported from another environment where it did happen.

Fix: pass a Windows-style path to the helpers.

```bash
python scripts/check_step.py "C:/Users/lu/nx_out/part.step"    # not ~/nx_out/part.step
```

The journals are unaffected - they expand `~` themselves through `resolve_out_dir()`.
