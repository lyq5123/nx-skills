---
name: nx-gui
description: Operate Siemens NX (UG) hands-on through its own GUI with Computer Use - click ribbon commands, fill dialogs, pick faces and edges in the graphics area, draw sketches - so the user watches the model being built in the NX session they already have open. Use only when the user asks you to drive/operate NX or UG by hand, wants the model drawn in their open NX window rather than produced as a file, says "动手操作 NX", "在我打开的 NX 里画", or explicitly rejects a script-only approach. Do NOT use this when the user just wants a part built to given dimensions, a batch of parts, or a .prt/.step produced - use the nx-model skill instead, which is headless, exact and repeatable; this one cannot even reach the menu bar.
---

# Driving NX's GUI

This skill is for **hands-on operation of a running NX session**. Its companion `nx-model` skill
generates parts through NX Open journals, which is exact and repeatable but invisible - the model
appears as a file, not in the window the user is looking at. Use this skill when the user wants to
watch it happen.

Everything below was measured against a running **NX 2406**. Where something does not work, it says
so - do not rediscover it.

## Three preconditions. Check them before clicking.

Almost every failure in testing traced back to one of these, not to the technique.

**The screenshot must be legible.** If the raster is much smaller than the window, the UI is
downscaled and your reading error is scaled *up*. On a 2560x1440 display the raster was capped at
1280x768 for a 2582x1550 window - a **2x downscale**, which put the ribbon's tab row and its tool row
about **9 pixels apart**. A 5-pixel misread then lands on the neighbouring tab. See
`references/nx-gui-recipes.md` for the conversion that makes this safe.

**Know which ribbon tab is active.** An icon that is not on the current tab does not exist - you are
clicking empty background. This is the single most time-costing trap observed: several clicks "did
nothing" because the ribbon was on 分析 while the target was a 主页 icon. The tell is the status bar
reading `没有预览`, or an unrelated icon lighting up.

**Confirm the window is where you think it is.** `bounds` at `[-32000, -32000, ...]` means minimized
(`include_screenshot: true` restores it, but that takes the user's focus on Windows). A window wider
than the physical screen means it spans monitors and the raster will be downscaled.

## Capability matrix (measured, NX 2406)

| Capability | Status |
| --- | --- |
| Clicking ribbon commands by coordinate | **Works**, once coordinates are derived properly. |
| Reading and writing dialog fields via accessibility | **Works.** Text/number fields, checkboxes, OK/Apply/Cancel. |
| Screenshots of the main window and of dialogs | **Works**, renders accurately. |
| Picking faces/edges in the graphics area | **Works.** Large faces are reliable; thin curves are not. |
| `Escape` when the window is focused | **Works** to leave a command. |
| Pull-down menus (`菜单(M)`, the `文件` backstage) | **Not usable.** Idle click, no window, nothing in accessibility, invisible in screenshots. |
| Popup lists, dropdown contents, graphics-area filter bars | **Not usable.** Same three failures. Comboboxes are therefore read-only in practice. |
| `Ctrl+O` (open a part), `Ctrl+Z` | **Do not work.** Byte-identical state afterwards. Open files from the shell. |
| Drawing a sketch and creating a `草图` feature | **Works** (verified end to end). |
| Picking an existing sketch's curves as an extrude section | **Not solved.** See below. |

The practical consequence: **ribbon commands are yours to drive; anything behind a menu or a dropdown
list is not.** Plan around that instead of fighting it.

## The mental model

NX is two UI technologies in one window:

- The **main window's ribbon** is custom-drawn (`UGS::UITools::...`). Accessibility sees opaque `pane`
  nodes with no actions, so click it **by coordinate**. The ribbon is left-aligned and top-anchored at
  fixed offsets in **native** pixels; convert to raster coordinates every time, never reuse a table
  from an earlier screenshot.
- **Dialogs opened from the ribbon are ordinary native controls** - `textfield`, `checkbox`,
  `combobox`, `button` with real `AXPress` / `AXSetValue`. Drive these through accessibility and
  prefer `setValue` over clicking.

Some dialogs are **inline** (they live in the *main* window's element tree - the 创建草图 dialog when
it appears that way, the 矩形 options) and some are **separate windows** (拉伸). After firing a
ribbon command, always `list_windows` to find out which you got. Dialog window ids are **recycled**
between commands, so re-resolve them rather than caching.

## Rules that came out of getting this wrong

**1. Confirm which dialog opened before doing anything else.** A misclick silently opens the
*neighbouring* command. During testing, a click aimed at 拉伸 opened 孔, and only `list_windows`
revealed it. This check is cheap and it is the only defence.

**2. Verify every graphics pick with the accessibility counter.** Dialogs expose selection state as
text: `image "选择曲线 (8)"`, `image "选择草图平面或面 (1)"`. Eyes on a 3/4 view cannot distinguish a
face from its boundary edges; the counter can.

**3. Prefer commands that consume faces over commands that consume curve chains.** Face picks are
large targets and worked every time. Picking a specific line of a foreshortened sketch is guesswork.

**4. Re-observe after every action.** Never chain three blind clicks. A stale frame fails with
`app/window geometry changed after frame ...`.

**5. Never leave the session dirty.** Close the dialogs you opened, and tell the user exactly what you
left unsaved. Note that `Escape` does not reliably unwind a whole task - three Escapes can leave the
window still titled `NX - 草图`.

## Reaching an extrude section without picking curves

The blocker is section selection from existing sketch geometry (details and the three failed remedies
are in `references/nx-gui-recipes.md`). The way around it is the `绘制截面` button inside the 拉伸
dialog: it creates the section sketch *inside* the feature and opens it **normal to the plane**, which
removes the foreshortening that defeats curve picking. That flow is documented step by step in the
reference and verified as far as the sketch opening in a normal view.

## Making a result visible (the reliable path)

Opening a part is the one thing NX's own UI will not let you automate. The shell will:

```bash
cmd //c start "" "C:\path\to\part.prt"
```

This loaded the part into the **already-running** NX session - no second process - and it became the
displayed part. Combine it with `nx-model`: generate exact geometry by journal, then surface it this
way. That pairing is fully reliable; hand-driving the modeler is not.

## Reporting back

Say plainly which steps you drove and which you handed back, and why. If a required command is
menu-only, that is a real limit of the environment - state it rather than improvising. Tell the user
what is on screen and what is unsaved.

The definitive check on a finished part is not visual: measure it with `nx-model`'s
`scripts/verify_part.py` and compare volume and face count against hand-computed values.

`references/nx-gui-recipes.md` has the coordinate derivation, the native anchor table, the verified
sketch flow, and the exact failure signatures.
