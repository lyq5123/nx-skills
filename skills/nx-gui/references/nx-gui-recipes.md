# NX GUI recipes - verified against NX 2406

## Preconditions - check these before clicking anything

**1. Can you read the screenshot?** If the raster is much smaller than the window, every coordinate
you read is scaled down and your error is scaled *up*. Measured case: a **2560x1440** display gave a
`1280x768` raster from a `2582x1550` window - a 2x downscale. In that raster the ribbon's tab row and
its tool row sat about **9 pixels apart**, and a 5-pixel misread landed on the neighbouring tab
instead of the icon. Everything below still works, but only if you derive coordinates by the method
in the next section rather than eyeballing them.

**2. Which ribbon tab is active?** An icon that is not on the current tab *does not exist* - you are
clicking empty background. Symptoms of this are subtle: the status bar reads `没有预览`, and the
click appears to do nothing or highlights an unrelated icon. When a click does nothing, check the tab
before concluding the command is unavailable. This cost more time than any other failure in testing.

**3. Is the window minimized or off-screen?** Bounds of `[-32000, -32000, ...]` mean minimized;
`include_screenshot: true` restores it, but on Windows that takes the user's focus. A window wider or
taller than the physical screen means it is spanning monitors and the raster will be downscaled.

## Deriving click coordinates (do not use a raster table)

**The ribbon is left-aligned and top-anchored at fixed offsets in *native* pixels.** It does not
reflow when the window is resized. The raster is that window scaled, so convert every time:

```
raster_x = native_x * (raster_width  / window_width)
raster_y = native_y * (raster_height / window_height)
```

Native anchors measured on the default theme, 100% DPI, main window with 主页 active:

| Target | native (x, y) | how solid |
| --- | --- | --- |
| `拉伸` (Extrude) | (187, 129) | **verified** - derived value opened 拉伸 |
| `草图` (Sketch) | (57, 168) | derived from a session where it worked in raster form |
| `矩形` (Rectangle, in the sketch task) | (388, 152) | x/y derived; the click landed in the correct row |
| `完成` (Finish sketch) | (54, 105) | derived from a session where it worked in raster form |
| `菜单(M)` | (119, 235) | **unusable, see below** |

Verified end to end: at raster 1280x768 from a 2582x1550 window, `拉伸` predicted `(93, 64)` and it
opened the 拉伸 dialog. Eyeballing that same raster gave `(148, 70)`, which opened **孔** - the anchor
method is the difference between the two.

Treat only the top row as confirmed. The rest were derived by the same arithmetic from sessions where
the raster-form coordinate worked, which is sound but not separately re-tested.

These anchors are theme- and DPI-dependent. If a derived coordinate misses, read the label positions
off the current raster once to recalibrate, then convert from native again for the rest of the session.
Note the ribbon **tab row** is the least reliable target of all - rather than deriving it, read the tab
labels off the current raster and click the text centre, then confirm the tab actually changed.

**Never reuse coordinates from an earlier screenshot.** The window can be restored, maximized or
resized under you. A stale frame fails with
`app/window geometry changed after frame ...` - re-observe and re-derive.

## Bind the session

```js
const apps = await agent.computerUse.listApps();
// NX: name "NX - 建模", bundle_id "...\\NXBIN\\ugraf.exe", pid <n>
const main = await agent.computerUse.getApp({ pid, window_id: <main window id> });
const wins  = await agent.computerUse.computer.list_windows({ app_ref: { pid } });
```

The window title tracks the active task - `NX - 建模`, `NX - 草图`. Bind by `window_id`, not title.

**Dialog window ids are recycled.** In one session `window_id 11012772` served, in order, the 拉伸
dialog, the 孔 dialog, and the 创建草图 dialog. Never cache a dialog's id across commands - re-run
`list_windows` and pick the window whose tree contains the fields you expect. Error boxes reuse the
command's title too (`拉伸` for both the dialog and its error), so when two windows share a title,
separate them by `bounds`: an error box is short (observed 404x161), a dialog is tall (435x855+).

## Rule: confirm which dialog opened

After every ribbon command click, `list_windows` and check the title matches what you asked for.
This is cheap and it is the only way to catch a misclick, because a misclick silently opens the
*neighbouring* command instead. It caught exactly this during testing.

## Rule: the selection counter is your verification

Dialogs expose selection state as text: `image "选择曲线 (8)"`, `image "选择草图平面或面 (1)"`. Read it
after every graphics pick. It is the only trustworthy answer to "did I pick the right thing" - eyes
cannot tell a face from its boundary edges in a 3/4 view.

## Verified flow: sketch created inside a feature via 绘制截面

This is the route to prefer, because it avoids picking thin 3D curves in the graphics area. Verified
as far as the sketch opening in a normal view; the final commit was not reached (see below).

1. `拉伸` (native 187, 129). Confirm via `list_windows` that 拉伸 opened.
2. In the 拉伸 dialog's tree, find `button "绘制截面"` and press it. A **创建草图** dialog opens as
   its own window; the main window title becomes `NX - 草图`.
3. Pick a plane: click a face in the graphics area. Prefer a **large flat face** - face picking is
   reliable, thin curve picking is not. Verify: `image "选择草图平面或面 (1)"`.
4. Press `确定`. The view rotates **normal to the plane** - this is the key benefit: sketch geometry
   is no longer foreshortened, so lines become long and axis-aligned instead of 1-2 px.
5. Draw with `矩形` (native 388, 152). Two graphics clicks give a rectangle.
6. `Escape` ends the tool; then `完成` (native 54, 105).
7. Back in the 拉伸 dialog the section should already be populated. Set the distance, then `确定`.

The equivalent standalone flow (sketch first, then extrude) was verified end to end as far as
creating the `草图` feature: `草图` -> pick a face -> `确定` -> `矩形` -> two clicks -> `完成`, which
produced a real sketch row in the part navigator.

## Known blocker: picking an existing sketch's curves as an extrude section

Still unsolved, and it is why the flow above uses 绘制截面 instead.

Clicking a sketch curve in the graphics area with the section filter at `自动判断曲线` produced **8**
curves for a 4-line rectangle - the click landed inside the region and the rule chained the region's
boundary as well. `确定` then raised a short error box titled `拉伸`:

```
[1] image 无法拉伸。截面与方向可能不兼容。
```

Three remedies were tried and all failed:

- **Change the curve-rule filter.** The filter bar lives in the graphics area, is absent from
  accessibility, and its dropdown does not render in screenshots. Unreachable.
- **Select the `草图` feature row in the 部件导航器.** The row highlights, so the click lands, but the
  section counter stayed at `(0)` - a feature click is not consumed by the section step.
- **Zoom in and re-click.** The sketch is small and foreshortened in a 3/4 view; aiming at a 1-2 px
  line is guesswork.

So: for an existing sketch, either hand the section pick to the user, or rebuild the feature through
绘制截面, or build it from a journal with the `nx-model` skill.

## Reading and driving a dialog

```js
const st = await dlg.getAXState({ emit: false });
```

Patterns from the 拉伸 dialog:

```
[4]   button "< 确定 >"        actions=[AXPress]
[19]  textfield "公差 = 0.01"  (editable) actions=[AXSetValue]
[53]  combobox "= 自动判断"    (editable has_menu) actions=[AXSetValue,AXExpand,AXCollapse]
[104] image "选择曲线 (8)"      # selection counter - not actionable
```

Numeric entry works and reads back:

```js
await dlg.setValue(70, "30");     // re-read the tree: "textfield = 30"
```

Prefer `setValue`. A field present but not `editable` is read-only - do not fight it. Comboboxes
advertise `AXExpand`, but the expanded list is one of the invisible popups, so treat a combobox as
read-only-in-practice: you can read its value, you cannot pick a different option.

## Keyboard

Bind to the app, and only when it is frontmost; raw keys to a background app are refused with
`frontmost_pid_mismatch`.

`Escape` works and is the universal "leave this command" - it closed the rectangle tool cleanly. It
does **not** necessarily leave a task: after creating a sketch via 绘制截面, three Escapes left the
window still titled `NX - 草图`. Do not rely on Escape to unwind a whole task.

Do not lean on shortcuts for commands. `Ctrl+O` produced byte-identical state - indistinguishable
from a no-op. `Ctrl+Z` also did not undo a sketch.

## Putting a result in front of the user

Opening a part is the one thing NX's own UI will not let you automate; the shell will:

```bash
cmd //c start "" "C:\path\to\part.prt"
```

Verified to load the part into the **already-running** session (no second `ugraf.exe`), where it
becomes the displayed part. Use this at the end so the user sees the result, and pair it with
`nx-model` for anything dimensional - the journal route is exact and verifiable, this route is not.

## When to hand a step back

If the step needs a menu, a popup list, or a dropdown, stop and give the user the exact menu path in
their language. A user told "菜单 → 插入 → 设计特征 → 长方体" has a part in ten seconds; a user
watching you guess coordinates gets nothing. Say plainly which steps you drove and which you handed
back, and leave the session clean: close dialogs you opened, and tell them what is unsaved.
