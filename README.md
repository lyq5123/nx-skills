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

Build it, then check it with a **separate** journal opening the saved part, then show it in NX:

```bash
"$UGII_BASE_DIR/NXBIN/run_journal.exe" skills/nx-model/scripts/build_plate.py  -args my_spec.json
"$UGII_BASE_DIR/NXBIN/run_journal.exe" skills/nx-model/scripts/verify_part.py -args my_spec.json
python skills/nx-model/scripts/show_in_nx.py my_spec.json
```

`show_in_nx.py` is plain Python (no `NXOpen` import) and hands the `.prt` to the OS, so **the part opens
in the NX session that is already running** - or starts NX if none is. Any agent that can run a command
can do that step; it needs no Computer Use and no clicking. The part appears with its full feature tree
in the part navigator.

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

## Shapes

A spec names one with `"part"` (aliases in brackets). Every shape is verified against NX on this
build; the numbers are what the tests assert.

| `part` | Parameters (mm) | Verified sample |
| --- | --- | --- |
| `mounting_plate` (default) | `plate_w` `plate_h` `plate_t` `hole_d` `hole_inset` `bore_d` `fillet_r` | 120×80×10, 4× D6.6, D30 bore → 87562.939 mm³, 11 faces; with R8 corner fillets → 87013.558, 15 faces |
| `circular_flange` (`flange`) | `od` `id` `thk` `bcd` `n_bolts` `bolt_d` `chamfer` | OD160 / ID60 / t20 / BCD120 / 6× D14 / C2 → 325108.763 mm³, 12 faces, 8 cylinders + 2 cones |
| `l_bracket` (`bracket`) | `base_l` `base_t` `wall_t` `total_h` `width` `hole_d` `hole_inset_x` | 80/12/10/60 wide 40, 2× D6 → 55338.053 mm³, 10 faces |
| `shaft_cradle` (`cradle`) | base plate + block with a semicircular groove, ears with cross-holes, rounded corners (a **multi-feature** example, not a single extrusion; its default dimensions come from a drawing reading that is provisional) | see `nx_recipes.py` |
| `extruded_profile` (`profile`) | **any outline of lines and circular arcs**: `outline` `[["line",x1,y1,x2,y2], ["arc",xs,ys,xm,ym,xe,ye], …]` (or the older `points` form), `thickness`, `holes` `[[x,y,dia],…]` | a hexagon 100/140/80 wide 6 with 2× D12 → 65842.832 mm³, 10 faces; a 120×80×10 plate with four R10 corners and 2× D12 → 92879.646 mm³, 12 faces |
| `composed` (`compose`) | **any ordered list of operations** in `features`: `profile` (outline extruded on plane `xy`/`xz`/`yz`, `mode` add or cut), `hole` / `boss` (`axis` x/y/z, `at`, `dia`, `through` or `thickness`/`height`), `blend` (`r`), `chamfer` (`c`) — the last two taking an `edges` selector: `from_feature`, `parallel_to`, `mid_at` | 200×160×20 plate + cross hole D16 + boss D55×25 + R12 on four corners + C3 on the boss rim → 616487.755 mm³, 14 faces, 6 cylinders + 1 cone; the sampler's own reference for it is 619145 ± 2326 |

`extruded_profile` is the general-purpose one for **flat** parts: most components on a drawing —
brackets, covers, gussets, link plates, channels — are an outline extruded to a thickness, and rounded
corners, slots and rounded ends are all expressible because the outline takes circular arcs as well as
lines (each arc's area is exact, by Green's theorem). It reproduces the named recipes exactly when their
outline is written the same way, and there is a test asserting that. What it cannot do is a **spline or
other non-circular curve** in the outline, a **revolved** part, or anything that is **not a
constant-thickness extrusion** (step, pocket, boss, shell, draft).

`composed` is the general-purpose one for **the rest of that list**: a list of operations executed in
order, on any of the three planes, adding and cutting. The last operation covering a point wins, so a
boss placed after a hole fills it back in. Blends and chamfers take their edges from a **geometric
selector**, never an index:

```json
{"part": "composed", "params": {"features": [
  {"op": "profile", "plane": "xy", "thickness": 20, "outline": [["line", 0,0,200,0], "…"]},
  {"op": "blend", "r": 12, "edges": {"parallel_to": "z", "mid_at": {"z": 10}}},
  {"op": "hole",  "axis": "y", "at": [40, 10], "dia": 16, "through": true},
  {"op": "boss",  "axis": "z", "at": [100, 80], "dia": 55, "height": 25},
  {"op": "chamfer", "c": 3, "edges": {"from_feature": 3, "mid_at": {"z": 25}}}
]}}
```

Its volume has **no closed form**, so the reference value is an independent **Monte-Carlo sample** of
the same feature list: a real check — it never asks NX, so a bad boolean or a missing feature shows up
— but a **~1% band rather than an equality**, with the sampling error printed on every run. Blends and
chamfers are not modelled by that reference at all (they cannot be, in general), so the run measures
what each round actually removed, asserts it is not zero, and adds it back before the comparison.
Face counts are not asserted for this shape, for the same reason. Every one of those limits is in the
run log, and `skills/nx-model/SKILL.md` says what it means for reporting a part.

Each shape has its own builder (`build_plate.py`, `build_flange.py`, `build_bracket.py`,
`build_cradle.py`, `build_profile.py`, `build_composed.py`) and its own
entry in `nx_recipes.py` holding three things: the parameters it takes, the rules that reject bad
combinations, and the analytic volume/face-count the verifier measures against. Adding a shape means
adding a row there and a builder beside it — **the existing journals do not change.**

Set a feature off with `0`: `hole_d: 0` skips holes, `bore_d: 0` skips the bore, `chamfer: 0` skips
the chamfer, and so on. `part` omitted means `mounting_plate`, which keeps old specs working.

## Tests

```bash
python skills/nx-model/tests/run_tests.py     # ~7 min, needs NX installed
python skills/nx-model/tests/run_tests.py T4  # a single test
```

Ten tests, including a **negative control** (the verifier must *reject* a part built to different
dimensions — otherwise a verifier that always passes looks green), conflict fixtures that must all be
rejected, and a five-operation composed part whose blends, selectors and analytic volume are each
asserted. Any Python 3 can run the harness; it only shells out to NX.

## What this does not do

Stated plainly, because the honest scope is more useful than an optimistic one:

- **It cannot read a drawing.** The code's input is numbers; interpreting a drawing, photo or
  screenshot is the *agent's* job. `skills/nx-model/SKILL.md` documents the discipline for that
  (transcribe → confirm with the user → build) and, importantly, why the numeric verification **cannot
  catch a misread dimension**: it compares NX's measurement against a value derived from the same
  spec, so a wrong number moves both sides together and the run stays green.
- **No drafting.** No drawing sheets, projected views, annotations, PDF or DWG.
- **Six shapes, two of them general.** The registry covers a rectangular plate, a circular flange, an
  L bracket, a shaft cradle, `extruded_profile` — any outline of lines and arcs, extruded to a
  thickness — and `composed` — any ordered list of extrusions, holes, bosses, blends and chamfers (see
  [Shapes](#shapes) below). Together the two general ones cover most of what a drawing shows.
  Outside them: splines and other non-circular curves, revolved parts, and swept, lofted or helical
  features (threads, springs, impeller blades). Those need a new recipe — geometry formula, validation
  rules, builder — and the formula matters as much as the geometry, because the verifier compares
  against it; a recipe with a wrong formula fails its own build.
- **`composed` is verified to ~1%, not to 0.0000.** Its volume reference is sampled and it does not
  model blends or chamfers; the named recipes and `extruded_profile` are exact. If a composed part
  needs to be *proved* rather than *checked*, write it as a named recipe or an `extruded_profile` where
  a closed form exists.
- **Rounds on a composed part are checked for effect, not for position.** The run proves a blend
  removed material from the edges its selector matched; that the selector named the *right* edges is a
  reading of the drawing, which is the agent's job, not the code's.
- **`nx-gui` cannot reach menus.** Pull-down menus, dropdown contents and graphics-area filter bars
  are invisible to both screenshots and accessibility on NX 2406, so commands behind them have to be
  done by hand. Selecting an existing sketch's curves as an extrude section is unsolved; the
  documented `绘制截面` route is verified only as far as the sketch opening in a normal view.
- **One NX version.** Everything was measured on NX 2406. Signatures change between releases — check
  the stubs (`grep` them) rather than trusting any snippet, including the ones here.

## License

MIT — see [LICENSE](LICENSE).
