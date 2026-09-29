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

- **`part`** picks the shape: `mounting_plate` (the default when omitted), `circular_flange`
  (`flange`), `l_bracket` (`bracket`), `extruded_profile` (`profile`), or `composed` (`compose`).
  Each takes a different set of `params` - see the tables under "Building from a drawing" above - and
  each has its own builder.
- **`extruded_profile` takes structured params**, not scalars: `"thickness": number`,
  `"holes": [[x, y, dia], ...]` (optional), and the boundary as either
  - `"outline"`: an ordered list of segments, each
    - `["line", x1, y1, x2, y2]`, or
    - `["arc", xs, ys, xm, ym, xe, ye]` - start, a point ON the arc, end.

    Arcs are **three points**, not centre/radius/angles: an angle pair plus a direction flag cannot
    distinguish the short arc from the long one between the same two angles, so it has to be read
    twice to be got right. Three points are unambiguous and are what a drawing shows. The segments
    must join end to end, in order, into one closed loop.
  - `"points": [[x, y], ...]` (the older straight-edge form, still accepted) - **do not repeat the
    first point**.

  The outline may mix straight edges and circular arcs, so rounded corners, slots and rounded ends
  are all expressible; each arc contributes its exact area by Green's theorem, not an approximation.
  The validator rejects an outline that is not a closed loop, zero-length lines, collinear arc points,
  holes outside the outline, holes crossing an edge (arcs included), and overlapping holes.
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

### Looking closely at the image (the mechanics)

Dimension text on a downloaded drawing is usually too small to read at the size the image arrives,
and the machine may have **no image tooling at all** (measured here 2026-09-30: no PIL, no cv2, no
ffmpeg, no ImageMagick - the `convert` on PATH is Windows' filesystem tool). Two routes, both with no
extra install:

**`scripts/pngcrop.py` - stdlib only, works anywhere Python does.**

```bash
python scripts/pngcrop.py in.png out.png 120 120 460 380 2   # X Y W H [SCALE]
```

It crops to that region and upscales by an integer factor, so the text can be read. What it accepts,
measured rather than assumed:

| input | result |
| --- | --- |
| 8-bit PNG, colour types 0/2/3/4/6 | **works** - a palette (type 3) image is expanded through its PLTE/tRNS |
| 16-bit PNG | refused, naming the depth |
| interlaced (Adam7) PNG | refused, naming the interlace |
| JPEG / GIF / BMP / TIFF / PDF | refused as "not a PNG"; it never guesses |

It scales by **nearest neighbour, never interpolating** - the cautious default for an image you then
reason about. It never writes to the input file.

**On Windows, PowerShell's `System.Drawing` reads, crops and scales every common format**, and its
bicubic scaling makes small text easier to read than nearest-neighbour. Use it when the drawing is not
a PNG, or when you want the smoother upscale:

```powershell
Add-Type -AssemblyName System.Drawing
$src  = [System.Drawing.Image]::FromFile('C:\path\to\drawing.jpg')
$rect = New-Object System.Drawing.Rectangle 120,120,460,380
$dst  = New-Object System.Drawing.Bitmap 920,760
$g = [System.Drawing.Graphics]::FromImage($dst)
$g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g.DrawImage($src, (New-Object System.Drawing.Rectangle 0,0,920,760), $rect, [System.Drawing.GraphicsUnit]::Pixel)
$g.Dispose(); $dst.Save('C:\path\to\crop.png', [System.Drawing.Imaging.ImageFormat]::Png)
$a.Dispose(); $dst.Dispose()
```

**The discipline that matters more than the tooling:**

- **Read the printed numbers, never measure the picture.** Pixel measurements mean nothing on a photo
  (unknown scale, lens distortion) and are not much better on an isometric. Zooming is for reading
  text; it is not a ruler.
- **Transcribe into a table with a confidence per value**, and hand the low-confidence ones to the user
  to confirm before building. That table is the artefact they can actually check - see the note below
  for why the run cannot check it for you.
- **When two readings of the same feature agree, that is the strongest evidence available.** An R25
  outer with an R15 bore and a separately dimensioned 10 mm wall agreeing with each other is worth
  more than either number alone; when they disagree, say so instead of quietly picking one.
- **A drawing's own notes can contradict its dimensions.** One exercise here says "both sides similar"
  while its two ends are R25 and R20. Record the conflict for the user rather than resolving it
  silently in either direction.

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

### Which shape, and when to say you cannot build it

Read this before transcribing, because it decides whether the job is even possible.

**Named recipes** (in `nx_recipes.py`) - convenient parameter names and shape-specific rules:

| `part` | Shape | Parameters |
| --- | --- | --- |
| `mounting_plate` (default) | rectangular plate, corner holes, centre bore, corner fillets | `plate_w` `plate_h` `plate_t` `hole_d` `hole_inset` `bore_d` `fillet_r` |
| `circular_flange` (`flange`) | disc, centre bore, bolt circle, rim chamfers | `od` `id` `thk` `bcd` `n_bolts` `bolt_d` `chamfer` |
| `l_bracket` (`bracket`) | L profile extruded, two through-holes | `base_l` `base_t` `wall_t` `total_h` `width` `hole_d` `hole_inset_x` |
| `shaft_cradle` (`cradle`) | base plate + upper block with a semicircular groove, ears with cross-holes, rounded upper corners | 16 params - see `nx_recipes.py`; **read the caveat below** |
| `laptop_stand` (`stand`) | inclined top plate + front stop lip + two side ribs, with optional rib lightening holes, a cable hole and blends | `width` `run` `angle` `plate_t` `rib_t` `front_h` `lip_len` `lip_h` (`rib_hole_d` `cable_hole_d` `blend_r` optional, 0 = off) |
| `laptop_stand_kd` | **the same stand as a knock-down kit** - separate pieces that screw together: `piece` = `plate` / `rib` / `screw` | `piece` + the stand's params + `screw_u1` `screw_u2` |

`shaft_cradle` is a **multi-feature** recipe: it is not a single extrusion, and it exists as a
worked example of the pattern (extrude a base, unite a block, cut a groove along Y, blend edges on
planes other than Z, drill along two axes). Its DEFAULT PARAMETERS come from a drawing whose reading is
**provisional** - the source drawing is internally inconsistent under the reading used, and the
uncertain values are exposed as parameters (`top_setback`, `base_hole_*`, `ear_hole_z`, and how
`saddle_w` relates to `2*saddle_r`). Its *geometry and volume formula* are verified (delta 0.0000
against the kernel); its *defaults* are not confirmed against the drawing. Treat it as a template, not
as "exercise 16 answered".

`laptop_stand` is the second multi-feature recipe: three XZ profiles (plate, lip, two
ribs) extruded along Y and united face to face, with an exact volume and face count -
verified 280/250/18°/8/6/12/15/15 + optional holes and R3 blends → 790296.093 mm³, 22 faces.

`laptop_stand_kd` is the same stand **split so it can be taken apart**, and it is the only part
type here whose spec describes **one piece of an assembly** rather than a whole part:

| `piece` | what it is | verified |
| --- | --- | --- |
| `plate` | top plate + stop lip, with a D9x3 head pocket in the TOP face (heads sit flush so the laptop slides over them) and a D5.5 clearance hole, at `u = screw_u1`/`screw_u2` | 644384.609 mm³, 22 faces |
| `rib` | one side rib (modelled centred on y=0, placed twice), lightening hole, D5.5x10 threaded pilot cut normal to the incline as a plain hole | 120883.479 mm³, 11 faces |
| `screw` | one M5 pan-head screw - head D8.5x3, hex socket AF4x2.75, shank D5x20 under the head | 524.829 mm³, 12 faces |

`build_laptop_stand_kit.py` then creates **two assembly files** from the three verified pieces:
`<kit>.prt` in working position and `<kit>_exploded.prt` with the components displaced along the
plate normal so the disassembly order is visible. Components are placed by **coordinate** (origin +
orientation), not by constraint solving - each placement is derived from the same recipe geometry the
pieces were built to, so the screws land in their holes by construction and stay exact however the
assembly is manipulated afterwards. An assembly has no volume of its own, so `verify_kit.py` checks
**component counts and names** in the saved assembly instead, and the pieces are measured by
`verify_part.py` like any other part.

The fastener constants (M5, head D8.5x3, socket AF4x2.75, pocket D9x3, clearance +0.5) are
deliberately **not** spec'd: they are a system, and the validate rules enforce the joint rather than
the piece - the stack `plate_t` + tap depth has to fit under the head with at least 1 mm spare.

**And then the two general ones, which are the usual answer:**

| `part` | Shape | Parameters |
| --- | --- | --- |
| `extruded_profile` (`profile`) | **any outline of lines and circular arcs** extruded to a thickness, with through-holes | `outline` = `[["line",..], ["arc",..], ...]` or `points`, `thickness`, `holes` |
| `composed` (`compose`) | **any ordered list of operations** - extrusions on any of the three planes, holes and bosses along any axis, blends and chamfers on edges picked by geometry | `features` = `[{"op": ...}, ...]` - see below |

`extruded_profile` covers most flat components on a drawing - brackets, covers, gussets, link plates,
channels, gaskets, and anything with rounded corners, slots or rounded ends. Its volume is exact (shoelace area ×
thickness − hole cylinders), so it gets the same verification as everything else, and it reproduces
the named recipes exactly when their outline is written as points (there is a test asserting that).

`composed` is the one to reach for when the part is neither flat nor one of the named shapes - a
**step, a pocket, a boss, a plate with something growing out of it**. It is a list of operations,
executed in order:

```json
{"part": "composed", "params": {"features": [
  {"op": "profile", "plane": "xy", "thickness": 20, "outline": [["line", 0,0,200,0], ...]},
  {"op": "profile", "plane": "xz", "at": 40, "mode": "cut", "thickness": 8,
   "outline": [["line", 20,20,30,20], ...]},
  {"op": "hole",  "axis": "y", "at": [100, 10], "dia": 16, "through": true},
  {"op": "boss",  "axis": "z", "at": [100, 80], "dia": 55, "height": 25},
  {"op": "blend", "r": 12, "edges": {"parallel_to": "z"}},
  {"op": "chamfer", "c": 3, "edges": {"from_feature": 4, "mid_at": {"z": 25}}}
]}}
```

- **`plane`** is `xy`, `xz` or `yz`; `at` is that plane's offset along its normal. A hole/boss takes
  an **`axis`** instead, and `at` is then `[u, v]` in the plane perpendicular to it - a hole along Y
  is a circle drawn in XZ; the two are two views of the same thing.
- **`op`** is `profile`, `hole`, `boss`, `blend` or `chamfer`. A **boss always adds** and a **hole
  always removes**; only a `profile` chooses, with `"mode": "add"` (default) or `"cut"`. Saying
  `"mode": "cut"` on a boss is **rejected**, not quietly ignored.
- **`through: true`** cuts right through the body. It is refused on anything that adds material - an
  addition with no end would extend without limit. Otherwise give a `thickness` (a boss may say
  `height`), and `start` to begin somewhere other than the plane's own offset.
- **`edges`** picks the edges a blend or chamfer acts on, by geometry and never by index:
  `{"from_feature": n}` (the edges feature *n* created), `{"parallel_to": "x"|"y"|"z"}`,
  `{"mid_at": {"z": 20}}` (an edge whose midpoint is at that coordinate). The keys combine with AND,
  so `{"from_feature": 4, "mid_at": {"z": 25}}` is "the top rim of that boss". A selector that
  matches nothing **fails the run**.
- **Order matters.** The operations are applied in sequence and the last one covering a point wins -
  a boss placed after a hole fills it back in.

**What is verified for a `composed` part, and what is not** - read this before reporting one:

- The volume check compares NX's measurement against an **independent Monte-Carlo sample** of the same
  feature list - not a closed form, because a list of operations has none. It is a **~1% band, not an
  equality**: the run prints the sampling error it actually got, and the check demands 1%.
- **Blends and chamfers are not modelled by that reference**, and in general they cannot be. So the run
  adds back what they removed before comparing (otherwise a heavily rounded part would fail for being
  correctly rounded), and it reports each round's edge count and removed volume. A round that removed
  nothing fails the run; a round applied to the *wrong* edges would not be caught by the volume - check
  it against the drawing yourself.
- Face counts are **not asserted** for a composed part: there is no honest count for an arbitrary
  feature list, and a number copied from a previous run is self-consistency, not verification.

**Say you cannot build it, before doing any work, when the part is:**

- **outlined by anything other than lines and circular arcs** - a spline, an ellipse, a gear tooth, a
  freeform curve. Circular arcs are fine (see `outline` above); other curve types are not, because
  there is no exact area formula behind them.
- **revolved** - a shaft, bushing, or anything drawn as a lathe part. No recipe, and its volume needs
  a different formula.
- **built from a swept, lofted or helical feature** - a screw thread, a spring, an impeller blade.
- **threaded, splined, geared, or heat-treated in ways the model must show.**

Adding one of those means writing a recipe (geometry formula + validation rules) plus a builder that
calls `nx_journal.run()` - not editing the existing journals. It is a real task, not a config change;
say so instead of attempting it silently.

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
python tests/run_tests.py          # ~10-15 min, needs NX installed; any Python 3
python tests/run_tests.py T4        # one test by prefix
python tests/test_recipes.py        # ~2 s, no NX: the recipe rules and formulas
python tests/test_output_contract.py  # ~0.02 s, no NX: what a run leaves on disk
```

Ten tests cover the no-argument path (backward compatibility), a spec-driven build with an
**independently** computed volume, the verifier agreeing, the verifier *rejecting* a part built to
other dimensions (the negative control - without it a verifier that always passes looks green), each
parameter-conflict class, bad invocations, STEP content, the recipe unit tests, **every registered
shape building and verifying end to end** - which includes the stand and all three knock-down
pieces - and a **five-operation composed part** whose blends, selectors and analytic volume are each
asserted. Exit code 0 = all passed. Run it after touching any
script.

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
| `scripts/nx_common.py` | the shared spec loader, validator, logger and path resolver (plain Python) |
| `scripts/nx_recipes.py` | **the per-shape rules**: parameters, validation, analytic volume and face counts (plain Python) |
| `scripts/nx_journal.py` | the NX-side plumbing every builder shares: session, extrude/blend/chamfer, self-check, save, STEP export |
| `scripts/build_plate.py` | the plate builder - geometry only; copy it to start a new shape |
| `scripts/build_flange.py` / `build_bracket.py` | the other two named shapes |
| `scripts/build_profile.py` | the generic one: any outline of lines and circular arcs, extruded |
| `scripts/build_laptop_stand.py` | the inclined stand: three XZ profiles extruded along Y, united face to face |
| `scripts/build_laptop_stand_kd.py` | one piece of the knock-down kit (dispatches on `piece`) |
| `scripts/build_laptop_stand_kit.py` | **the assembly builder**: three verified pieces → a working-position and an exploded assembly |
| `scripts/verify_kit.py` | checking a saved assembly's components, since an assembly has no volume to measure |
| `scripts/nx_compose.py` | the feature-list recipe: operations, planes, edge selectors, and the Monte-Carlo reference volume (plain Python) |
| `scripts/build_composed.py` | the executor for a feature list - multi-plane extrusions, unites and cuts, blends/chamfers by selector |
| `scripts/verify_part.py` | measuring a finished part against its spec, whatever shape it is |
| `scripts/show_in_nx.py` | opening the built part in the user's NX (plain Python, not a journal) |
| `scripts/pngcrop.py` | cropping and zooming a drawing so its dimension text can be read (stdlib PNG decoder) |
| `scripts/check_step.py` | proving a STEP export actually contains geometry |
| `tests/run_tests.py` | regression suite; run it after any change to a script |
| `tests/test_recipes.py` | the recipe rules and formulas, in 0.01 s, no NX needed |
| `tests/specs/*.json` | working examples, including five that must be rejected |

## Reporting back

Tell the user: the dimensions used, the paths of the `.prt` and `.step`, the measured volume against
the analytic value, and whether `result.json` says `ok`. Say which parts you actually ran versus which
you only wrote. If a feature is unverified, say so explicitly rather than implying it works - the user
would rather hear "the fillet is unverified" than discover it later.

When you hand over a `.step`, quote what `check_step.py` reported - "1 solid, 15 faces" - not just
that the file is there. Give it a **Windows-style path** (`C:/.../part.step`): the plain-Python
helpers take the path straight from `sys.argv`, so if MSYS path conversion is off (`MSYS_NO_PATHCONV`)
or an argument passes through a wrapper that skips it, Windows Python receives `/c/Users/...` and
cannot open it. The journals are unaffected - they expand `~` themselves.
