# NX 2406 NX Open Python - verified API reference

Every signature here was read from the stubs shipped with the installed NX 2406:

```
$UGII_BASE_DIR/UGOPEN/pythonStubs/NXOpen/__init__.pyi
$UGII_BASE_DIR/UGOPEN/pythonStubs/NXOpen/Features/__init__.pyi
```

If a call you need is not here, grep the stubs - do not guess and do not trust online snippets,
which are usually for a different release. `pythonStubs` exist from NX 2406 onward; on older NX you
have nothing but prose docs, so treat every signature as unverified.

## Session and parts

```python
theSession  = NXOpen.Session.GetSession()
workPart    = theSession.Parts.Work        # None when no part is open
displayPart = theSession.Parts.Display
```

```python
PartCollection.FileNew()                                    -> FileNew
PartCollection.NewBaseDisplay(name: str, units: BasePart.Units) -> BasePart
PartCollection.NewDisplay(name: str, units: Part.Units)         -> Part
PartCollection.OpenBaseDisplay(filename: str)               -> Tuple[BasePart, PartLoadStatus]
PartCollection.OpenDisplay(filename: str)                   -> Tuple[Part, PartLoadStatus]
PartCollection.SetDisplay(part: BasePart, maintain_work_part: bool, set_entire_part: bool)
                                                            -> Tuple[PartCollection.SdpsStatus, PartLoadStatus]
```

`NewBaseDisplay` is the headless one-step "new part". It **refuses to overwrite an existing file** -
delete the target first. Note the trap: `NewBaseDisplay` takes `BasePart.Units` and `NewDisplay`
takes `Part.Units`. These are **different enum types with identical member names**; passing the
wrong one gives "Second parameter is invalid."

Creating a part the recorded-journal (File > New) way:

```python
fn = theSession.Parts.FileNew()
fn.TemplateFileName         = "model-plain-1-mm-template.prt"
fn.ApplicationName          = "ModelTemplate"
fn.Units                    = NXOpen.Part.Units.Millimeters
fn.TemplatePresentationName = "Model"
fn.NewFileName              = r"C:\path\part.prt"
fn.MakeDisplayedPart        = True
fn.Commit()
fn.Destroy()
workPart = theSession.Parts.Work
```

Saving:

```python
BasePart.Save(save_component_parts: BasePart.SaveComponents,
              close: BasePart.CloseAfterSave) -> PartSaveStatus
BasePart.SaveAs(new_file_name: str) -> PartSaveStatus
```

```python
part.Save(NXOpen.BasePart.SaveComponents.TrueValue, NXOpen.BasePart.CloseAfterSave.FalseValue)
```

## Units

`Part.Units` / `BasePart.Units` members: `Inches, Millimeters, Mix, Meters, Micrometers`.

- `Expression.Value` and `.NumberValue` are in **base part units** - part-specific, not global.
  They are mm only because the part was created metric.
- `Expression.RightHandSide` / `.SetFormula(str)` take a string and are the safe way to drive sizes.
- `Point3d` and curve coordinates are base part units.
- The stubs explicitly advise against `Expression.Value` for new code (angle expressions break it).

```python
UnitCollection.FindObject(name: str) -> Unit
UnitCollection.GetBase(measure_name: str) -> Unit          # "Mass", "Length", ...
UnitCollection.Convert(initial_unit_type: Unit, target_unit_type: Unit, initial_value: float) -> float
```

`GetBase("Mass")` is how you feed `NewMassProperties`.

## Curves (the simple alternative to the sketcher)

For prismatic parts you do not need the interactive sketcher at all. Build a closed loop of curves
and hand it to an extrude section. This is shorter and far more robust than driving sketch
constraints.

```python
CurveCollection.CreateLine(start_point: Point3d, end_point: Point3d) -> Line
CurveCollection.CreateLine(start_point: Point,   end_point: Point)   -> Line
CurveCollection.CreateArc(center: Point3d, x_direction: Vector3d, y_direction: Vector3d,
                          radius: float, start_angle: float, end_angle: float) -> Arc   # radians
CurveCollection.CreateArc(start_point: Point3d, point_on: Point3d, end_point: Point3d,
                          alternate_solution: bool) -> Tuple[Arc, bool]
```

Note the arc angle arguments are **radians**. A full circle is `CreateArc(center, xdir, ydir, r, 0.0, 2*math.pi)`.

`CreateLine` produces real curve features in the part tree, not inert geometry. If you need a "clean"
dumb solid afterwards, delete the construction curves and call
`Features.CreateRemoveParametersBuilder()`.

## Sections

```python
SectionCollection.CreateSection(chaining_tolerance: float, distance_tolerance: float,
                                angle_tolerance: float) -> Section
SectionCollection.CreateSection(curve: NXObject) -> Section
SectionCollection.CreateSectionsUsingCurves(curves, loop_option, chain_tol, dist_tol, angle_tol)
                                                          -> List[Section]
Section.SetAllowedEntityTypes(types: Section.AllowTypes)   # OnlyCurves, OnlyPoints, ...
Section.AddToSection(rules, seed, start_connector, end_connector, help_point,
                     mode: Section.Mode, chain_within_feature: bool)
Section.AllowSelfIntersection(bool)
```

The tolerances are meaningful, not decoration - the recorded journals use `0.0095, 0.01, 0.5`.

Selection-intent rules (all on `part.ScRuleFactory`), verified for NX 2406:

```python
CreateRuleCurveDumb(curves: List[Curve]) -> CurveDumbRule
CreateRuleCurveDumbFromPoints(points: List[Point]) -> CurveDumbRule
CreateRuleCurveFeature(features: List[NXOpen.Features.Feature]) -> CurveFeatureRule
CreateRuleEdgeDumb(edges: List[Edge]) -> EdgeDumbRule
CreateRuleRegionBoundary(seed_obj: DisplayableObject, curves: List[ICurve],
                         seed_point: Point3d, distance_tolerance: float) -> RegionBoundaryRule
CreateRuleBodyDumb(bodies: List[Body]) -> BodyDumbRule
```

Prefer `CreateRuleCurveDumb` for standalone curves. `CreateRuleBaseCurveDumb` is the deprecated
older spelling - `CreateRuleCurveDumb` is the current one.

## Directions

```python
DirectionCollection.CreateDirection(origin: Point3d, vector: Vector3d,
                                    update: SmartObject.UpdateOption) -> Direction
```

This is the one you want for a straight prismatic extrude - no reference object needed. There are
~20 other overloads (along an edge, on a face, from a datum axis); grep `def CreateDirection` in the
stub if you need one. Use `NXOpen.SmartObject.UpdateOption.WithinModeling` for features.

## Extrude

```python
FeatureCollection.CreateExtrudeBuilder(NXOpen.Features.Feature.Null) -> ExtrudeBuilder
```

Builder members (all confirmed in the Features stub):

| Member | Type |
| --- | --- |
| `Section` | `Section` |
| `Direction` | `Direction` |
| `Limits` | `GeometricUtilities.Limits` |
| `BooleanOperation` | `GeometricUtilities.BooleanOperation` |
| `Draft` | `GeometricUtilities.MultiDraft` |
| `Offset` | `GeometricUtilities.FeatureOffset` |
| `DistanceTolerance` | `float` |
| `ParentFeatureInternal` | `bool` |
| `AllowSelfIntersectingSection(bool)` | method |
| `CommitFeature()` | -> `Feature` |

Limits are reached through `Limits.StartExtend.Value` / `Limits.EndExtend.Value`, each an
`NXOpen.Expression`. Set them as strings:

```python
ext.Limits.StartExtend.Value.RightHandSide = "0"
ext.Limits.EndExtend.Value.RightHandSide   = "10"
```

Boolean:

```python
b = ext.BooleanOperation
b.Type = NXOpen.GeometricUtilities.BooleanOperation.BooleanType.Create   # Create / Unite / Subtract / Intersect
b.SetTargetBodies([NXOpen.Body.Null])          # first solid feature
b.SetTargetBodies([target_body])               # every later feature - omit it and you get
                                               # "Missing target body"
```

## Primitive builders

```python
FeatureCollection.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null) -> BlockFeatureBuilder
FeatureCollection.CreateCylinderBuilder(NXOpen.Features.Feature.Null)     -> CylinderBuilder
FeatureCollection.CreateHolePackageBuilder(NXOpen.Features.HolePackage.Null) -> HolePackageBuilder
FeatureCollection.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)    -> EdgeBlendBuilder
FeatureCollection.CreateChamferBuilder(NXOpen.Features.Feature.Null)      -> ChamferBuilder
```

```python
BlockFeatureBuilder.Types              # OriginAndEdgeLengths, TwoPointsAndHeight, DiagonalPoints
BlockFeatureBuilder.SetOriginAndLengths(origin: Point3d, length: str, width: str, height: str)
BlockFeatureBuilder.SetBooleanOperationAndTarget(NXOpen.Features.Feature.BooleanType, NXOpen.Body)

CylinderBuilder.Types                  # AxisDiameterAndHeight, ArcAndHeight
CylinderBuilder.Axis, .Diameter, .Height, .BooleanOption

ChamferBuilder.Option                  # SymmetricOffsets, TwoOffsets, OffsetAndAngle
ChamferBuilder.SmartCollector          # edges go here (-> ScCollector)
ChamferBuilder.FirstOffset / .SecondOffset / .Angle    # all str
```

Note the offset/radius/diameter arguments are **strings**, and `FirstOffsetExp` is read-only.

## Edge blend (fillet) - the classic wrong-signature trap

```python
EdgeBlendBuilder.AddChainset(collector: ScCollector, radius: str) -> int
EdgeBlendBuilder.AddChainset(collector, sectionType, conicMethod, rhoType,
                             radius: str, center: str, rho: str) -> int
```

It is **not** `AddChainset(edge, index)`. Build the collector first:

```python
ebb  = part.Features.CreateEdgeBlendBuilder(NXOpen.Features.Feature.Null)
col  = part.ScCollectors.CreateCollector()
col.ReplaceRules([part.ScRuleFactory.CreateRuleEdgeDumb(edges)], False)
ebb.AddChainset(col, "8")
feature = ebb.CommitFeature()
ebb.Destroy()
```

`ScCollector.ReplaceRules(rules: List[SelectionIntentRule], create_rules_wo_update: bool)`.

## Hole package

```python
HolePackageBuilder.HoleType                    # Simple, Counterbored, Countersink, Tapered, Threaded, Series
HolePackageBuilder.GeneralSimpleHoleDiameter   # -> Expression
HolePackageBuilder.GeneralSimpleHoleDepth      # -> Expression
HolePackageBuilder.GeneralTipAngle             # -> Expression
HolePackageBuilder.HoleDepthLimitOption        # HoleDepthLimitOptions.Value, ...
HolePackageBuilder.HolePosition                # -> Section (allowed types: OnlyPoints)
HolePackageBuilder.Tolerance                   # float - set it, default 0 raises "Tolerance error"
HolePackageBuilder.BooleanOperation            # must get a target body
```

A hole needs a target body **and** a position point through a section rule built with
`CreateRuleCurveDumbFromPoints`. For a plain through-hole in a plate, a subtract extrude of circle
curves is usually less code and fewer failure modes - see `recipes.md`.

## Selecting geometry without clicking

```python
Body.GetFaces() -> List[Face]
Body.GetEdges() -> List[Edge]
Edge.GetFaces() -> List[Face]
Edge.GetVertices() -> Tuple[Point3d, Point3d]      # endpoints, not Vertex objects
Edge.GetBody()   -> Body
TaggedObject.Tag -> int
```

Index order is **not** stable across rebuilds. Classify geometrically instead. The helper you will
reuse constantly:

```python
def vertical_edges(body, tol=1e-6):
    """Edges that run parallel to Z."""
    out = []
    for e in body.GetEdges():
        p0, p1 = e.GetVertices()
        if abs(p0.X - p1.X) < tol and abs(p0.Y - p1.Y) < tol and abs(p1.Z - p0.Z) > tol:
            out.append(e)
    return out
```

Faces carry a surface type too, so cylindrical faces (hole and boss walls) are classifiable the same
way without touching the UF layer:

```python
NXOpen.Face.FaceType    # Rubber, Planar, Cylindrical, Conical, Spherical,
                        # SurfaceOfRevolution, Parametric, Blending, Offset, Swept,
                        # Convergent, Undefined

def cylindrical_faces(body):
    return [f for f in body.GetFaces()
            if f.SolidFaceType == NXOpen.Face.FaceType.Cylindrical]
```

This tells you *what kind* of surface a face is, which is usually all you need. It does **not** give
you the axis or radius - for those, use the circular edge boundaries (above) rather than a UF call,
since UF has no stubs to verify against.

Sanity check on the sample plate with R8 corner fillets: 15 faces come back as 6 `Planar`
(top, bottom, and the four side flats) and 9 `Cylindrical` (4 fillets + 4 corner holes + the bore).
If your counts differ, the feature you think applied did not.

Note `BodyCollection` (and the other collections) **do not support `len()`** - it raises
`TypeError: object of type 'NXOpen.BodyCollection' has no len()`. Use a list comprehension
(`[b for b in part.Bodies]`) or `GetData()`.

For distinguishing curve types, use the edge's own type rather than the UF layer:

```python
NXOpen.Edge.EdgeType    # Rubber, Linear, Circular, Elliptical, Intersection, Spline,
                        # SpCurve, Foreign, ConstantParameter, TrimmedCurve, Convergent, Undefined

edge.SolidEdgeType == NXOpen.Edge.EdgeType.Circular
```

Combined with `GetVertices()`, that is enough to pick "the two outer circular edges of a flange of
outer radius R" out of eight circular edges:

```python
def circular_edges_at_radius(body, radius, tol=1e-6):
    """Circular edges whose endpoints sit at the given radius from the Z axis."""
    out = []
    for e in body.GetEdges():
        if e.SolidEdgeType != NXOpen.Edge.EdgeType.Circular:
            continue
        p0, p1 = e.GetVertices()
        r0 = math.hypot(p0.X, p0.Y)
        r1 = math.hypot(p1.X, p1.Y)
        if abs(r0 - radius) < tol and abs(r1 - radius) < tol:
            out.append(e)
    return out
```

The UF layer (`NXOpen.UF.UFSession.GetUFSession()`, `ufs.Modeling.AskFaceData(...)`) is real at
runtime - `NXBIN/python/NXOpen_UF.pyd` exists - but **no `.pyi` stubs are shipped for it**
(`UGOPEN/pythonStubs/NXOpen/` has no `UF` directory). Prefer the `NXOpen` classes above, whose
signatures you can actually verify.

## Getting the entities a feature created

`Feature.GetEdges()` / `GetFaces()` / `GetBodies()` return **that feature's own** entities, not the
whole body's - verified on NX 2406: a block extrude gives 12 edges and 6 faces, a hole cut gives the
2 circular edges and 1 cylindrical face, a boss unite gives its 2 circular edges. The same answer as
diffing edge tags before and after, and the references **stay valid after a later feature** (checked
by blending after the fact), so "blend the edges that feature 3 created" is a workable selector for a
declarative spec.

`GetEntities()` is NOT the same thing - it returned 0 in every case. Do not use it for this.

```python
feat = nxj.extrude(...)               # CommitFeature() inside
body = feat.GetBodies()[0]
for e in feat.GetEdges():             # this feature's edges only
    ...
```

## Measuring

`MeasureManager` is a property of the **part**, not the session:

```python
mp = part.MeasureManager.NewMassProperties([part.UnitCollection.GetBase("Mass")], 0.99, [body])
mp.Volume    # -> float
mp.Area      # -> float
mp.Mass      # -> float
mp.Centroid  # -> Point3d
```

`NewMassProperties` overloads take either `accuracy: float` or `tolerances: List[float]`, and accept
either an `ScCollector` or a `List[IBody]`.

## Update and undo

```python
Session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, name: str) -> int
UpdateManager.DoUpdate(undo_mark: int) -> int
UpdateManager.AddToDeleteList(objects: List[NXObject]) -> int
UpdateManager.AddObjectsToDeleteList(objects: List[TaggedObject]) -> int
Session.UndoToMark(mark: int, name: str)
```

The discipline that keeps a multi-feature script debuggable: one undo mark per logical step, commit
the features, `DoUpdate(mark)`, and `UndoToMark(mark)` in the failure path.

## STEP export

### The in-process Dex API does NOT work headless

`DexManager.CreateStepCreator()` builds, validates (`Validate()` returns True), commits without
raising, and writes a file of plausible size - which under `run_journal.exe` contains **no geometry**:
0 `MANIFOLD_SOLID_BREP`, 0 `ADVANCED_FACE`, 1 `CARTESIAN_POINT`. It fails this way for every
`ExportAs` (`Ap203`/`Ap214`/`Ap242`), every `ExportFrom` (`DisplayPart`/`ExistingPart`), every
`SelectionScope` including an explicit `SelectionComp.Add(body)`, and with or without
`ExportDestination`. IGES fails identically, so the whole in-process Dex layer emits nothing here.
Do not use it, and do not let a file's existence convince you it worked.

The API surface, for reference only:

```python
StepCreator.ExportAs             # ExportAsOption: Ap203, Ap214, Ap242, Ap242ED2
StepCreator.ExportFrom           # ExportFromOption: DisplayPart, ExistingPart
StepCreator.InputFile / OutputFile  # str, on BaseCreator
StepCreator.ObjectTypes          # .Solids, .Surfaces, .Curves, .Annotations
StepCreator.ExportSelectionBlock # ObjectSelector; .SelectionScope = Scope.*
StepCreator.Commit()
```

There is no `Step214Creator` class and no `CreateStep214Creator()` in NX 2406 - that is old NX
(10/11); the `ExportAs` enum replaced it.

### Use the CLI translator instead

NX itself drives these executables for File > Export > STEP. They are the supported, working path:

| Version | Executable | Def file |
| --- | --- | --- |
| AP203 | `$UGII_BASE_DIR/STEP203UG/step203ug.exe` | `ugstep203.def` |
| AP214 | `$UGII_BASE_DIR/STEP214UG/step214ug.exe` | `ugstep214.def` |
| AP242 | `$UGII_BASE_DIR/TRANSLATORS/step242/` | `ugstep242.def` |

Invocation, from **inside the journal** via `subprocess`:

```python
base = os.environ["UGII_BASE_DIR"]
cmd = [os.path.join(base, "STEP214UG", "step214ug.exe"),
       part.FullPath,
       "o=" + step_path,                                        # output
       "l=" + os.path.splitext(step_path)[0] + ".log",          # translator log
       "d=" + os.path.join(base, "STEP214UG", "ugstep214.def")]  # config
subprocess.run(cmd, capture_output=True, text=True, timeout=300)
```

It must run **from inside the journal** so it inherits NX's environment. Launched from a plain
shell it dies immediately on `libccov.dll`, because the NX runtime directories are not on `PATH`.

`ugstep214.def` ships with `MODULES_MASK = Solids` and `CHOOSE_DIRECTION = UG to STEP`, which is
what you want for parts. The translator prints a `SUMMARY-` block - `Body: 1` means one solid was
translated. Its stdout also reaches the journal's console.

`scripts/build_plate.py` wraps this as `export_step()`; prefer calling that over re-deriving it.

### Always check the file's contents

```bash
python scripts/check_step.py out/part.step
```

It counts `MANIFOLD_SOLID_BREP` / `ADVANCED_FACE` and exits non-zero on a geometry-less file. A
correct export of the sample plate is 1 solid and 11 faces (15 with corner fillets). File size alone
proves nothing: the empty shell and the real export are both plausible `.step` files.

## Logging

```python
lw = NXOpen.Session.GetSession().ListingWindow
lw.Open()
lw.WriteLine("...")
lw.WriteFullline("...")       # yes, three l's - that is the real shipped spelling
lw.Close()
```

`print()` also reaches the console under `run_journal.exe`. Simplest reliable choice is `print()`
plus `sys.stdout.flush()`, since NX buffers.

For a dialog: `NXOpen.UI.GetUI().NXMessageBox.Show(title, NXOpen.NXMessageBox.DialogType.Information, text)`.
