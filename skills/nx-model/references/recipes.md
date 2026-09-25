# Recipes

Working code shapes for NX 2406. Everything here follows the rules in `SKILL.md`: strings for
lengths, objects kept from return values, `DoUpdate` per step, floats written as floats.

## Skeleton every journal starts with

```python
# NX Open Python journal  -  NX 2406
import math
import os
import sys

import NXOpen
import NXOpen.Features                # submodules at MODULE TOP, never inside a function
import NXOpen.GeometricUtilities

# ---------------------------------------------------------------------------
# parameters (millimetres)
# ---------------------------------------------------------------------------
PLATE_W = 120.0
PLATE_H = 80.0
PLATE_T = 10.0

OUT_DIR   = os.path.join(os.path.expanduser("~"), "nx_out")
PART_NAME = "mounting_plate_demo"


def log(msg):
    print(msg)
    sys.stdout.flush()


def main():
    session = NXOpen.Session.GetSession()

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    prt_path = os.path.join(OUT_DIR, PART_NAME + ".prt")
    for stale in (prt_path, os.path.join(OUT_DIR, PART_NAME + ".step")):
        if os.path.exists(stale):
            os.remove(stale)          # NewBaseDisplay refuses to overwrite

    part = session.Parts.NewBaseDisplay(prt_path, NXOpen.BasePart.Units.Millimeters)
    if isinstance(part, tuple):
        part = part[0]                # defensive: some releases return a tuple

    ...                               # build here

    part.Save(NXOpen.BasePart.SaveComponents.TrueValue,
              NXOpen.BasePart.CloseAfterSave.FalseValue)
    log("[ok] saved " + prt_path)


if __name__ == "__main__":
    main()
```

`run_journal.exe` calls `main()` for you; the `__main__` guard keeps the file importable for
linting and lets you run it with the bundled interpreter directly during development.

## Prismatic part from a closed curve loop, then holes by subtract

This is the workhorse. It needs no sketcher and no sketch constraints. Verified end to end.

```python
w, h, t = PLATE_W, PLATE_H, PLATE_T

# --- outer profile: four dumb lines, closed -------------------------------
corners = [
    (NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Point3d(w, 0.0, 0.0)),
    (NXOpen.Point3d(w, 0.0, 0.0), NXOpen.Point3d(w, h, 0.0)),
    (NXOpen.Point3d(w, h, 0.0), NXOpen.Point3d(0.0, h, 0.0)),
    (NXOpen.Point3d(0.0, h, 0.0), NXOpen.Point3d(0.0, 0.0, 0.0)),
]
rect = [part.Curves.CreateLine(a, b) for a, b in corners]

# --- add the plate --------------------------------------------------------
mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "plate")
ext = part.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
sec = part.Sections.CreateSection(0.0095, 0.01, 0.5)
ext.Section = sec
ext.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create
ext.BooleanOperation.SetTargetBodies([NXOpen.Body.Null])
ext.Limits.StartExtend.Value.RightHandSide = "0"
ext.Limits.EndExtend.Value.RightHandSide   = str(t)
rule = part.ScRuleFactory.CreateRuleCurveDumb(rect)
sec.AddToSection([rule], rect[0], NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                 NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Section.Mode.Create, False)
ext.Direction = part.Directions.CreateDirection(
    NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0),
    NXOpen.SmartObject.UpdateOption.WithinModeling)
plate_feat = ext.CommitFeature()
ext.Destroy()
session.UpdateManager.DoUpdate(mark)

body = plate_feat.GetBodies()[0]      # <-- identity of feature 1 for feature 2
body.SetName("Plate")
```

Then cut every hole in **one** subtract extrude. Circles are arcs with angles in radians:

```python
def circle(part, cx, cy, dia, z=0.0):
    return part.Curves.CreateArc(
        NXOpen.Point3d(cx, cy, z),
        NXOpen.Vector3d(1.0, 0.0, 0.0),
        NXOpen.Vector3d(0.0, 1.0, 0.0),
        dia / 2.0, 0.0, 2.0 * math.pi)

holes = [circle(part, x, y, HOLE_D) for x, y in
         [(i, i), (w - i, i), (w - i, h - i), (i, h - i)]]   # i = HOLE_INSET
holes.append(circle(part, w / 2.0, h / 2.0, BORE_D))

mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "holes")
cut = part.Features.CreateExtrudeBuilder(NXOpen.Features.Feature.Null)
csec = part.Sections.CreateSection(0.0095, 0.01, 0.5)
cut.Section = csec
cut.BooleanOperation.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Subtract
cut.BooleanOperation.SetTargetBodies([body])           # the body from the previous feature
cut.Limits.StartExtend.Value.RightHandSide = "-1"      # overshoot so the cut is unambiguous
cut.Limits.EndExtend.Value.RightHandSide   = str(t + 1.0)
crule = part.ScRuleFactory.CreateRuleCurveDumb(holes)
csec.AddToSection([crule], holes[0], NXOpen.NXObject.Null, NXOpen.NXObject.Null,
                  NXOpen.Point3d(w / 2.0, h / 2.0, 0.0), NXOpen.Section.Mode.Create, False)
cut.Direction = part.Directions.CreateDirection(
    NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Vector3d(0.0, 0.0, 1.0),
    NXOpen.SmartObject.UpdateOption.WithinModeling)
cut.CommitFeature()
cut.Destroy()
session.UpdateManager.DoUpdate(mark)
```

Why subtract instead of the hole package: one section rule and one commit, no position-point
plumbing, no `Tolerance` default trap, and it generalises to any profile - slots, obrounds, pockets.
Reach for `HolePackageBuilder` when you need a counterbore/countersink/thread or depth semantics
that would be tedious to model by hand.

## Corner fillets - select by geometry

```python
mark = session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "fillet")

def vertical_edges(b, tol=1e-6):
    out = []
    for e in b.GetEdges():
        p0, p1 = e.GetVertices()
        if abs(p0.X - p1.X) < tol and abs(p0.Y - p1.Y) < tol and abs(p1.Z - p0.Z) > tol:
            out.append(e)
    return out

verts = vertical_edges(body)
if len(verts) != 4:
    log("[warn] expected 4 vertical edges, found %d - fillet skipped" % len(verts))
else:
    ebb = part.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
    col = part.ScCollectors.CreateCollector()
    col.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(verts)], False)
    ebb.AddChainset(col, str(FILLET_R))
    ebb.CommitFeature()
    ebb.Destroy()
    session.UpdateManager.DoUpdate(mark)
```

The count assertion matters: the vertical-edge filter also matches the edges of any vertical hole,
so on a part with through-holes in the walls you must filter harder (compare edge length, or keep a
`Z` range). Do not silently blend whatever came back.

## Chamfer

```python
cb  = part.Features.CreateChamferBuilder(NXOpen.Features.Feature.Null)
col = part.ScCollectors.CreateCollector()
col.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(edges)], False)
cb.SmartCollector = col
cb.Option       = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
cb.FirstOffset  = "2"
cb.CommitFeature()
cb.Destroy()
```

## Revolve / cylinder boss

For a plain boss on an existing body, the cylinder builder is less code than a revolve:

```python
cyl = part.Features.CreateCylinderBuilder(NXOpen.Features.Feature.Null)
cyl.Type = NXOpen.Features.CylinderBuilder.Types.AxisDiameterAndHeight
origin = part.Points.CreatePoint(NXOpen.Point3d(40.0, 30.0, 30.0))
zdir   = part.Directions.CreateDirection(
    NXOpen.Point3d(40.0, 30.0, 30.0), NXOpen.Vector3d(0.0, 0.0, 1.0),
    NXOpen.SmartObject.UpdateOption.WithinModeling)
cyl.Axis = part.Axes.CreateAxis(origin, zdir, NXOpen.SmartObject.UpdateOption.WithinModeling)
cyl.Diameter.SetFormula("20")
cyl.Height.SetFormula("25")
cyl.BooleanOption.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Unite
cyl.BooleanOption.SetTargetBodies([body])          # required to fuse
cyl.CommitFeature()
cyl.Destroy()
```

`body` must come from a feature you already committed and updated. A cylinder with `Type = Create`
and no target produces a separate body - check `[b for b in part.Bodies]` if you expect one solid
(the collection has no `len()`, so wrap it in a list).

## Block, for a quick starting solid

```python
bb = part.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
bb.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
bb.SetOriginAndLengths(NXOpen.Point3d(0.0, 0.0, 0.0), "80", "60", "30")   # strings
bb.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType.Create, NXOpen.Body.Null)
feat = bb.CommitFeature()
bb.Destroy()
```

## Sketch in place (only when you actually need sketch constraints)

Driving the sketcher from a script is much more verbose than dumb curves and buys you nothing unless
the part must be dimension-driven and editable in the GUI. If you do need it, this is the recorded
NX 2406 shape:

```python
sip = part.Sketches.CreateSketchInPlaceBuilder2(NXOpen.Sketch.Null)
plane = part.Planes.CreatePlane(NXOpen.Point3d(0.0, 0.0, 0.0),
                                NXOpen.Vector3d(0.0, 0.0, 1.0),
                                NXOpen.SmartObject.UpdateOption.WithinModeling)
sip.PlaneReference = plane
sketch = sip.Commit()                      # creates the sketch FEATURE
sketch.Activate(NXOpen.Sketch.ViewReorient.TrueValue)
sip.Destroy()
plane.DestroyPlane()

line = part.Curves.CreateLine(NXOpen.Point3d(0.0, 0.0, 0.0), NXOpen.Point3d(100.0, 0.0, 0.0))
session.ActiveSketch.AddGeometry(line, NXOpen.Sketch.InferConstraintsOption.InferNoConstraints)
# ... more geometry, then constraints via session.ActiveSketch.CreateDimension(...)

session.ActiveSketch.Update()
session.ActiveSketch.Deactivate(NXOpen.Sketch.ViewReorient.TrueValue,
                                NXOpen.Sketch.UpdateLevel.Model)
sketch_feature = sketch.Feature        # feed this to an extrude section
```

Note there is no plain `CreateSketchInPlaceBuilder` in NX 2406 - it is `CreateSketchInPlaceBuilder2`,
`CreateNewSketchInPlaceBuilder`, or `CreateSimpleSketchInPlaceBuilder`. Sketching is also where you
use `CreateRuleCurveFeature([sketch_feature])` for the section instead of `CreateRuleCurveDumb`.

## Verify numerically - always do this

```python
import math

mp = part.MeasureManager.NewMassProperties(
    [part.UnitCollection.GetBase("Mass")], 0.99, [body])
vol = mp.Volume

expect = w * h * t
expect -= 4 * math.pi * (HOLE_D / 2.0) ** 2 * t
expect -= math.pi * (BORE_D / 2.0) ** 2 * t
expect -= 4 * (FILLET_R ** 2 - math.pi * FILLET_R ** 2 / 4.0) * t     # corner round-off

log("volume %.3f  expected %.3f  delta %.4f" % (vol, expect, abs(vol - expect)))
log("faces=%d edges=%d" % (len(body.GetFaces()), len(body.GetEdges())))
```

Face count is a cheap topology check: a rectangular plate with 4 corner fillets, 4 corner holes and a
centre bore has exactly 15 faces (2 flat + 4 fillet cylinders + 4 hole cylinders + 1 bore + 4 flats).
If you get 11, the fillets did not apply; if you get 19, the holes cut twice.

Run this as a **separate** journal that opens the saved `.prt`. Verifying inside the build journal
hides errors, because the in-memory body can differ from what was written to disk.

## STEP export

`DexManager.CreateStepCreator()` does not work under `run_journal.exe` - it writes a geometry-less
shell. Use the bundled CLI translator, wrapped as `export_step()` in `scripts/build_plate.py`:

```python
import os
import subprocess

def export_step(part, step_path):
    base = os.environ["UGII_BASE_DIR"]
    log_path = os.path.splitext(step_path)[0] + ".log"
    for f in (step_path, log_path):
        if os.path.exists(f):
            os.remove(f)
    r = subprocess.run(
        [os.path.join(base, "STEP214UG", "step214ug.exe"), part.FullPath,
         "o=" + step_path, "l=" + log_path,
         "d=" + os.path.join(base, "STEP214UG", "ugstep214.def")],
        capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(step_path):
        log("[err] STEP translation failed")
        return False
    text = open(step_path, "r", encoding="latin-1", errors="replace").read()
    solids, faces = text.count("MANIFOLD_SOLID_BREP("), text.count("ADVANCED_FACE(")
    log("[chk] STEP solids=%d faces=%d" % (solids, faces))
    return solids > 0            # a file that exists is not a file that has geometry
```

Two things that bite: it must be launched **from inside the journal** (else `libccov.dll` is
missing from `PATH`), and the result must be checked for `MANIFOLD_SOLID_BREP`, not for existence.

## Circular flange with a bolt circle and a chamfer

Verified pattern (D160 OD, D60 bore, 20 thick, 6x D14 on a D120 bolt circle, C2 outer chamfer ->
325108.763 mm³, 12 faces, and 2 `CONICAL_SURFACE` in the STEP for the two chamfers).

The profile is one full circle, so the whole part is a circle extrude plus a subtract extrude of
the bore and bolt holes together - the same two-step shape as the plate.

```python
# outer circle as a single closed curve (angles in RADIANS)
outer = part.Curves.CreateArc(NXOpen.Point3d(0.0, 0.0, 0.0),
                              NXOpen.Vector3d(1.0, 0.0, 0.0),
                              NXOpen.Vector3d(0.0, 1.0, 0.0),
                              OD / 2.0, 0.0, 2.0 * math.pi)
feat = extrude(part, session, [outer], NXOpen.Point3d(0.0, 0.0, 0.0),
               0.0, THK, bb.Create, name="disc")
body = feat.GetBodies()[0]

# bore + bolt holes in one cut; the bolt circle is plain trigonometry
holes = [circle(part, 0.0, 0.0, ID)]
r_bc = BCD / 2.0
for k in range(N_BOLTS):
    a = 2.0 * math.pi * k / N_BOLTS
    holes.append(circle(part, r_bc * math.cos(a), r_bc * math.sin(a), BOLT_D))
extrude(part, session, holes, NXOpen.Point3d(0.0, 0.0, 0.0),
        -1.0, THK + 1.0, bb.Subtract, target=body, name="holes")
```

Chamfering the outer rim needs the outer circular edges, which are NOT at the outer radius once the
part has bolt holes - so filter by **both** radius and Z. Both endpoints of a circular edge lie on
its circle, so those two classifiers are stable wherever the seam falls:

```python
def circular_edges_on_ring(body, radius, z, tol=1e-4):
    """Circular edges lying on the circle of `radius` at height `z`."""
    out = []
    for e in body.GetEdges():
        if e.SolidEdgeType != NXOpen.Edge.EdgeType.Circular:
            continue
        p0, p1 = e.GetVertices()
        r0, r1 = math.hypot(p0.X, p0.Y), math.hypot(p1.X, p1.Y)
        if (abs(r0 - radius) < tol and abs(r1 - radius) < tol
                and abs(p0.Z - z) < tol and abs(p1.Z - z) < tol):
            out.append(e)
    return out

edges = circular_edges_on_ring(body, OD / 2.0, 0.0)      # bottom rim
edges += circular_edges_on_ring(body, OD / 2.0, THK)     # top rim
if len(edges) != 2:
    log("[warn] expected 2 rim edges, found %d - chamfer SKIPPED" % len(edges))
else:
    cb = part.Features.CreateChamferBuilder(NXOpen.Features.Feature.Null)
    col = part.ScCollectors.CreateCollector()
    col.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(edges)], False)
    cb.SmartCollector = col
    cb.Option = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
    cb.FirstOffset = str(CHAMFER)     # str, per rule 1
    cb.Tolerance = 0.01               # default 0 raises "Tolerance error"
    cb.CommitFeature()
    cb.Destroy()
    session.UpdateManager.DoUpdate(mark)
```

Chamfering **both** rim edges is the symmetric-deburr reading of "chamfer C2". If the drawing means
one face only, select one edge and expect the volume to differ (top-only is 326105.695 mm³ for
these dimensions) - worth confirming with the user rather than assuming.

The C2 chamfer shows up in the STEP as 2 `CONICAL_SURFACE` entries, which is a satisfying
independent confirmation that the feature is real geometry and not a cosmetic annotation.

## Running

Headless, the normal development loop:

```bash
"$UGII_BASE_DIR/NXBIN/run_journal.exe" build_plate.py
```

With arguments (`-args` passes the rest to `main`'s argv):

```bash
"$UGII_BASE_DIR/NXBIN/run_journal.exe" build_plate.py -args out.prt
```

If you need real Python 3.10 semantics while iterating on pure logic, the bundled interpreter is at
`$UGII_BASE_DIR/NXBIN/python/` - but it has no `NXOpen` unless NX sets it up, so only use it for
syntax checks and maths, never to test the NX calls.
