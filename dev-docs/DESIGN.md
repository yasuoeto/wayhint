# wayhint — Design

[日本語](DESIGN.ja.md)

Based on the design document §12–§14, §45, §50–§59; writes only what is decided. Anything
undecided is marked "undecided".

## Overview

A resident daemon (`wayhintd`) holds a single GTK4 + gtk4-layer-shell overlay window and is
operated from the CLI (`wayhint toggle|show|hide|refresh|validate`) over a Unix domain socket.
A compositor keybinding (labwc `rc.xml` / `wayfire.ini`) runs `wayhint toggle`. On show, the
context is resolved once, and the matching sheet (+ tag filtering from the parent sheet) is
rendered.

```text
compositor keybind ─→ wayhint toggle ─(unix socket)─→ wayhintd
                                                        │ show/refresh
                                                        ▼
                                              ContextResolver
                     WaylandContextProvider(foreign-toplevel)→ ProcAdapter / HerdrContextProvider
                     (fallback: WayfireContextProvider)
                                                        │ ResolvedContext
                                                        ▼
                                                 HintWindow(layer-shell overlay)
```

## Architecture

- **adapter isolation**: only `context/wayland.py` and `context/workspace.py` call pywayland,
  only `context/wayfire.py` calls PyWayfire, only `context/herdr.py` calls the `herdr` CLI.
  Calling them directly from any other module is forbidden.
- **one-way dependency**: `ui/` receives only `ResolvedContext` and sheet data. The UI never
  queries the compositor / Herdr.
- **snapshot**: context is resolved and fixed at show/refresh time. A live-update config item
  exists but is always `false` in V1.
- **event-driven**: no idle polling. File watching uses `Gio.FileMonitor`.
- **no plugin system is built**: only the `NestedContextProvider` interface exists, with two V1
  implementations, `ProcAdapter` and `HerdrContextProvider`. They fall into two groups by how
  they decide — **terminal introspection** (look at the app_id and find the foreground process
  yourself: `ProcAdapter`) and **nested resolver** (ask the host application: `HerdrContextProvider`)
  — but share one interface. `ContextResolver` asks each in registration order whether it
  `applies_to`, and asks only the first match's `foreground_process(app_id)`. The single place
  that decides registration order is `daemon._nested_providers()`. Multi-stage resolution
  (terminal → multiplexer → command) was deferred in DECISIONS 0027. Tmux/SSH/EditorMode can be
  added under the same interface in the future.
- **window → process is resolved by the app_id suffix**: neither the Wayland protocol nor labwc
  passes a toplevel's pid to the client, so if a terminal has two windows, `/proc` alone cannot
  tell them apart. The convention is that the window itself declares `--app-id foot.p<pid>`, and
  the pid is read back from the app_id the compositor returns (`matcher.strip_pid_suffix`,
  DECISIONS 0027). For an app_id without a suffix, it answers only when that terminal has exactly
  one process. Sheet matching/creation and the overlay display use the base with the suffix
  stripped, while `ResolvedContext.desktop_app` keeps the suffixed form (a different window means
  a different context). Sheet matching lets `app_specificity` consider **both** the app_id and the
  base as candidates (a suffixed window matches a `^foot$` sheet — not restricted to base only, so
  as not to break a rule meant for an app_id that happens to end in `.p<digits>`). Because there is
  exactly **one** foreground process per pty, if a terminal's descendants turn up more than one tty
  (tab / split / tmux), it is **left unresolved** rather than guessed by depth or PID. Terminal and
  launcher setup steps are in `docs/TERMINALS.md`.

## Modules

The design document's §53 layout, adapted to `wayhint`. This is a guide to responsibility
boundaries; modules with little implementation may be merged (avoid over-splitting).

```text
src/wayhint/
  cli.py                          `wayhint validate|toggle|show|hide|refresh|reload|ping`
  daemon.py                       `wayhintd`: Gtk.Application, UDS server, Gio.FileMonitor(debounce)
  config.py                       global config(overlay/appearance/editor/nested/context/search/logging)
  models.py                       Hint, HintSheet, MatchRule, DisplayConfig, Size, Margin,
                                  ResolvedContext, ProcessInfo, OutputInfo, SourceLocation
  yaml_store.py                   ruamel.yaml load, line numbers, validation(Issue), SheetStore(last-known-good)
  matcher.py                      app_id / argv / cmdline regex matching, priority → specificity → file order
  selection.py                    4-stage replacement of parent hints(0034), favorite/category sort, search
  context/base.py                 DesktopContextProvider / NestedContextProvider(Protocol)
  context/resolver.py             ContextResolver(the §56 flow, output priority order)
  context/wayland.py              pywayland isolation: active toplevel/output via wlr-foreign-toplevel, activate
  context/_wlr_foreign_toplevel.py  generated (protocols/*.xml → scripts/gen-protocol)
  context/wayfire.py              PyWayfire isolation(optional backend): focused view/output, set_focus
  context/select.py               selection and auto fallback of `context.backend` auto|wayland|wayfire
  context/workspace.py            pywayland isolation: watches active workspace via ext-workspace-v1, decides toggle/switch
  ResolvedContext.target_key() in models.py  the comparison key for what the overlay is currently showing (title excluded)
  context/herdr.py                herdr CLI isolation: pane current → process-info --pane
  context/proc.py                 /proc isolation: foreground process from the terminal's descendants(pgrp == tpgid)
  context/process.py              ProcessInfo normalization
  ui/geometry.py                  anchor → layer-shell edges + margin, px/% resolution,
                                  resize_delta(drag on a grabbed corner → new size)(pure, tested)
  i18n.py                         UI string catalog(en/ja), locale detection(pure, tested)
  ui/window.py, ui/style.py       HintWindow(list/detail/search/toolbar), CSS
  editor.py                       edit_target(decides which file/line to open, pure), placeholder substitution + Popen(shell=False)
  clipboard.py                    GDK clipboard
  ipc.py                          socket path, JSON encode/decode, client, handle_request
```

`matcher/`, `ui/hint_list.py`, etc. from the design document's §53 were merged into the above
because their implementation is small.

## Data model

- `Hint`: `id`, `title` (required); `kind`, `key`, `command`, `category`, `tags`, `favorite`,
  `copy`, `remark`, `source`, `learned`; `location: SourceLocation(file, line)`.
- `HintSheet`: `version`, `id`, `title`, `priority`, `match: MatchRule`, `display: DisplayConfig`
  (partial, inherits from global), `inherit.parent_tags`, `nested.export_tags` (`export_tags`, the
  tags of hints passed to children as a parent; unspecified means `None` = all), `hints: list[Hint]`, `path`.
- `MatchRule`: `wayland.app_id_regex[]` (the old spelling `wayfire` is also read), `process.argv_regex[]`, `process.cmdline_regex[]`.
- `ResolvedContext`: `desktop_app`, `desktop_title`, `output: OutputInfo(name, width, height)`,
  `view_ref` (the focus-restore target after search; an opaque backend-specific string), `parent_context` (parent sheet id),
  `foreground_process: ProcessInfo | None`, `active_sheet`, `error` (the message shown when the desktop context cannot be obtained).
- `ProcessInfo`: `pid`, `name`, `argv`, `cmdline`, `cwd`.
- Config files: `$XDG_CONFIG_HOME/wayhint/config.yaml`, `style.css`, `hints/<lang>/*.yaml` (`.yml` too,
  read in filename order). The schema is fixed in Phase 1 based on the design document §21, §43 (DECISIONS 0006).
- **The three file categories** (DECISIONS 0033): content lives in `hints/` (written by humans), config in
  `config.yaml` (written by humans; only resizing is written back by the daemon), state in
  `$XDG_STATE_HOME/wayhint/state.yaml` (written only by the daemon).

### state.yaml (implementation: `state.py`, DECISIONS 0033)

Defaults to `~/.local/state/wayhint/state.yaml`. Holds the per-sheet filter (the search box string).

```yaml
version: 1
filters:
  claude-code: "pane"
  herdr: "#session"
```

- The key is the id of the active (child) sheet. The value is the filter applied to the whole
  list including parent/include contributions.
- Only the daemon writes it, and only when it differs from what it last wrote, at the moment
  `search` is exited, via a temp file + rename. An empty filter removes the key. It is not watched.
  A filter for a context with no active sheet is kept in memory only.
- **Never blocks startup even if broken**: missing / unreadable / invalid YAML / top-level is not a
  mapping / `version` ≠ 1 / over 64 KiB → starts with no filters and a single WARN line. No `⚠` is
  shown in the UI, and no `.bak` is made (the next write overwrites it). An entry whose value is
  not a string, whose sheet id doesn't match `^[A-Za-z0-9][A-Za-z0-9._-]*$`, or whose value is over
  200 characters is dropped, entry by entry. From the 257th entry on, entries are dropped. Unknown
  sheet ids are kept; unknown keys are dropped on write-back. A duplicate sheet id: the later one
  wins. A write failure is a WARN, and the in-memory value keeps being used.
  `wayhint validate` does not look at it.
- The filter string is only used for the existing substring + token AND matching; it is never
  treated as regex, a path, shell, or markup. Unicode `Cc` is stripped both on input and on load.
  The WARN never includes the filter contents.

### config.yaml (implementation: `config.py`)

The full description of every item, for users, is in `docs/CONFIG.md`. When adding or changing an
item, fix both.

```yaml
overlay:    {anchor: top-right, width: 420px, height: 60%, margin: {top: 24, right: 24}, output: null}
appearance: {style: style.css, show_category: true, language: auto}   # language: auto(locale) | en | ja
editor:     {command: [gvim, --remote-silent, "+{line}", "{file}"], schema_modeline: false,
             schema_path: ~/.config/wayhint/schema.json}
nested:     {parent_tags: null, parent_categories: null}   # null = not written. [] opts the whole thing out(docs/SHEETS.md §3)
context:    {live_update: false, backend: auto, workspace: current}  # backend: auto|wayland|wayfire
                                                                     # workspace: current|all
search:     {max_results: 50}
logging:    {level: warning}
include:    []          # sheets mixed in by default for every sheet(id, or {sheet, tags, categories}. 0026 / 0039); a sheet's own include wins
```

- Every item is optional, and the file itself may be absent (the above are the defaults). An
  unknown section/key is an error.
- size: an integer (px), `"420px"`, or `"30%"` (0–100). margin: an integer (all sides) or
  `{top,right,bottom,left}`.
- `editor.command` is an argv list. The only placeholders are `{file}` `{line}` `{hint_id}`,
  and `{file}` is required. An unknown `{...}` is an error. Expansion is plain string
  substitution and never goes through a shell.
- `editor.schema_modeline`: if true, new sheets and `format` add a
  `# yaml-language-server: $schema=` line at the top (DECISIONS 0014 D6).
- `editor.schema_path`: the path written into the modeline's `$schema=`, and the default output
  destination of `wayhint schema --write`.

### hints/<lang>/*.yaml (implementation: `yaml_store.py`)

The full description of every item, for users, is in `docs/SHEET-FORMAT.md`. When changing the
schema, fix both.

The placement is one directory per language (DECISIONS 0024). `hints/<lang>/` → `hints/en/` →
`hints/*.yaml` (flat, for a single language or a pre-migration layout) are tried in order, and
**only the first one found** is read. `<lang>` uses the same `resolve_language()` as the UI
(config `appearance.language` → locale → `en` if unknown). Reading, writing, creating new files,
and watching are all done against that one directory, and it is re-read when the language setting
changes.


```yaml
version: 1              # optional, only 1
id: claude              # required ^[A-Za-z0-9][A-Za-z0-9._-]*$, same as filename(stem), unique across all sheets
title: Claude Code      # required
priority: 10            # optional int, default 0
match:                                                 # optional. A sheet without one never becomes active
  wayland: {app_id_regex: [...]}                       # old spelling wayfire: means the same
  process: {argv_regex: [...], cmdline_regex: [...]}   # must compile as Python re
include: [wm, {sheet: git, tags: [daily], categories: [basics]}]   # sheets to mix in. defaults to the global include if omitted
display: {anchor, width, height, margin, output}       # partial, inherits from global overlay
inherit: {parent_tags: [terminal, ai], parent_categories: [pane]}   # filter on parent hints. see below for the order used when omitted
nested: {export_tags: [pane], export_categories: [pane]}   # hints passed to children as a parent. all, if omitted
hints:
  - {id, title,            # required. id unique within the sheet
     kind: shortcut|command|tip|note, key, command, category, tags: [], favorite: false,
     copy, remark, source, learned}
```

- How hints from other sheets get mixed in (a parent sheet and `include`) is collected in
  `docs/SHEETS.md`. Implementation of each section there: §1 deciding the active/parent sheet is
  `context/resolver.py`'s `ContextResolver.resolve`; §2 assembling the list is
  `selection.visible_hints` → `selection.sort_hints`; §3 filtering parent hints is
  `selection.effective_parent_tags` / `effective_parent_categories` and `models.HintFilter`; §4
  include is `yaml_store.resolve_includes` (a filtered sheet is a copy with only `hints` reduced;
  the hints themselves stay the original objects); §6 checking is `selection.explain_filters`
  (`wayhint inspect` / `context --shown`); §7 the owning file is
  `hint.location.file`. In short:
  - **`include`** (DECISIONS 0026 / 0039): an element is either a sheet id (everything) or
    `{sheet, tags, categories}` (filtered). A sheet's own `include` **replaces** the config's
    `include`. An include target's own include is not followed. Unresolvable ids and
    self-references are ignored one by one, with a warning.
  - **Parent hint filtering** (DECISIONS 0034 / 0039): for tags, the child's `inherit.parent_tags` →
    config's `nested.parent_tags` → parent's `nested.export_tags` → everything, four stages, and
    only the first stage that is actually written is used. category resolves the same rule
    independently via `parent_categories` / `export_categories`.
  - **Combining tag and category** (0039): OR of whichever is written. If either is `[]`, the
    result is 0 regardless of the other (so that config's `nested.parent_tags: []` keeps acting as
    a global opt-out. 0036). A hint with no category never matches any category.
- **`match` is optional**. A sheet without `match` never becomes active for any context, and
  appears in the list only via `include` (for shared hints). Even a sheet with `match` can be an
  include target.
- The list is concatenated in the order active → parent sheet (filtered) → include (in written
  order, filtered), and then the D7 sort is applied. When the same hint arrives by two routes, it
  collapses to one by `(file, id)` (0019).
- Everything except `id` and `title` is optional. Hints written by GUI/CLI/format output all 12
  fields, nulls included, in canonical order (`id` `title` `kind` `key` `command` `category`
  `tags` `favorite` `copy` `remark` `source` `learned`). Reading does not care about key order or
  omission (DECISIONS 0014 D2).
- Display order: the favorite block (in YAML order, category ignored) → the non-favorite block
  (category first-seen order, **numbered using only the non-favorite hints** → YAML order). A
  null category forms one group in first-seen order, labeled as a pseudo-category (DECISIONS
  0014 D7).
- Each hint's `location` is the 1-based start line of the list element. `learned` dates are
  normalized to an ISO string.
- Validation collects every problem within a file and returns them as `Issue(file, line,
  message)`. If there is even one, the sheet is not adopted. `SheetStore` holds the adopted sheet
  (last-known-good) and replaces it only the next time it parses clean.

## Interfaces

- **CLI ↔ daemon**: a Unix domain socket, `$XDG_RUNTIME_DIR/wayhint.sock`. No network socket is
  used. Messages are newline-terminated JSON, one request per connection (DECISIONS 0008): the
  client sends `{"cmd": "<name>"}\n` once and closes the write side, and the daemon returns one
  `{"ok": true, ...}` or `{"ok": false, "error": "..."}` and disconnects. Limit 4096 bytes; an
  unknown `cmd` is an error.
- **Wayland (default)**: `wlr-foreign-toplevel-management-unstable-v1` (pywayland, connecting
  fresh on each call). Obtains: the activated toplevel's app_id / title / output (wl_output v4's
  name, mode ÷ scale). Focus is restored with `activate(seat)`. Handles do not survive across
  connections, so `view_ref = "<app_id>\t<title>"` is re-resolved (exact match → single app_id
  match → give up). The focused output is not in the protocol, and is filled in only when there
  is a single output.
- **Wayfire (fallback / explicit)**: PyWayfire (requires the IPC plugin). Obtains: the active
  view, its output, app-id, title. Focus is restored with `set_focus`. With
  `context.backend: auto`, it is used only when there is no foreign-toplevel and `WAYFIRE_SOCKET`
  is set.
- **workspace**: `ext-workspace-v1` (pywayland). Connects only while the overlay is open on some
  workspace, and recomputes the active workspace on every `done` from the manager. The daemon puts
  the connection's fd on the GLib main loop, and once it's readable does
  `flush → read → dispatch` to drain the socket (`dispatch` alone doesn't read the socket, leaving
  the fd readable and the watch firing repeatedly). There is no polling. The daemon keeps a
  workspace key → `ResolvedContext` dict, and re-displays only that workspace's entry on a switch.
  The overlay's "Close" and a close-request both call the daemon's `close`, which drops that
  workspace's entry (`wayhint hide` is the same as `toggle`'s hide. DECISIONS 0037).
  `HintWindow.hide_overlay` only hides the surface, used when hiding on a workspace switch.
- **Herdr**: `herdr pane current`, `herdr pane process-info --pane <id>`. The output format is
  confirmed on real hardware and absorbed inside the adapter. **Precondition**: the adapter is
  chosen only for a window whose app_id matches `app_id_pattern`
  (default `herdr`, substring match) — this is not a config item but a default of
  `HerdrContextProvider`. It pairs with `herdr.yaml`'s `app_id_regex`; a window that satisfies
  neither (e.g. running `herdr` in a plain kitty) falls through to the `/proc` route, which can
  only tell that "a process named `herdr` is running." That state is logged at INFO via
  `proc.SELF_REPORTING`. **Call convention** (DECISIONS 0028): called with environment variables
  starting with `HERDR_` stripped out — `pane current` returns the pane named by
  `HERDR_PANE_ID` if set, so a daemon started from inside a Herdr pane would get pinned to that
  pane. `pane list` is called as a fallback only when `pane current` returns `focused: false`, and
  only adopted when exactly one pane has `focused: true`. The time budget is spent against a
  deadline set at the start of lookup, and each call gets `min(CALL_TIMEOUT, remaining time)`
  (the total across up to 3 calls still stays within `LOOKUP_BUDGET`).
- **editor**: substitutes `{file}` `{line}` `{hint_id}` in the `editor.command` argv and `Popen`s
  it. Where to open is decided by `edit_target(sheet, hint)` (pure, tested). **When a hint is
  selected, the hint's `location` takes priority over the sheet's**: because nested display mixes
  in hints from a parent sheet, using the active sheet's file would open the wrong file at the
  wrong line. Only when there is no hint does it fall back to the sheet's file:1.
- **layer-shell**: layer overlay, exclusive_zone 0. keyboard_mode is derived from state: normal =
  none, search / edit = exclusive. The one place it is set is `_sync_keyboard_mode()`.
  Anchor names (9 kinds) are converted to layer-shell anchor + margin.
- **manual resize**: since a layer surface has no compositor-side frame / interactive resize, a
  grip is overlaid with `Gtk.Overlay` on the side opposite the anchor and grabbed with
  `Gtk.GestureDrag`. Corners (`.wayhint-grip-both`, 16px) resize both axes; the free-edge bands
  (`.wayhint-grip-x` / `-y`, 6px) resize width-only or height-only. A band zeroes the delta of the
  axis it doesn't move and feeds the same `resize_delta`. Where they overlap, whichever corner was
  added later with `add_overlay` wins. During drag, `set_size_request` is used; when the drag
  ends, the daemon writes `overlay.width` / `height` back into `config.yaml` in px
  (DECISIONS 0018). Since it's pointer-only, keyboard_mode is untouched. The size math is
  `geometry.resize_delta` (pure).

## Edit mode (Phase 7)

The spec text is DECISIONS 0014; see 0014 for the reasoning behind it. The three hotkeys'
per-state behavior and when the overlay disappears are collected, with diagrams, in
`docs/HOTKEYS.md`. Implemented in `daemon.py`'s `toggle` / `enter_search_mode` /
`enter_edit_mode` / `hide` / `close`; "was the screen showing when it was entered" is
`WorkspaceView.mode_entered_hidden`.

### 1. States and keyboard_mode

| state | keyboard_mode | entry | exit |
|---|---|---|---|
| `normal` | NONE | show / toggle | hide, leaving the workspace |
| `search` | EXCLUSIVE | the search button, IPC `search-mode` | Esc, `Enter`, the list's `c` (after copying), `search-mode` again (returns to the display state at entry), the close button, leaving the workspace |
| `edit` | EXCLUSIVE | IPC `edit-mode` (compositor keybinding), the toolbar button | Esc, `edit-mode` again (returns to the display state at entry), the close button, leaving the workspace |

- The one place that sets `keyboard_mode` directly is `_sync_keyboard_mode()`, called on every
  state change. hide / leaving the workspace drop it to `NONE` while keeping the state; show /
  returning re-applies it according to state.
- Why EXCLUSIVE: with `ON_DEMAND`, the compositor does not hand keyboard focus over until the
  surface is clicked again, so pressing the search button alone leaves input going to the app
  below (confirmed on labwc 0.20.2).
- **Filtering is a property of the list; `search` only layers an input box and a grab on top**
  (DECISIONS 0033). The list is drawn by one code path, and filtering applies to `normal`'s
  display too (favorite block included). Every way of exiting `search` only drops the grab and
  keeps the filter, and `normal` shows the active filter as a chip (cleared with `×`).
  Re-entering fills the box with the saved filter and selects it all. `Enter` and `Esc` return to
  `normal` without copying. `↓` in the search box moves to the list (`↑` on the first row returns
  to the box), and `c` on the list copies the selected hint's `copy` → `command` and returns to
  `normal`. If there is nothing to copy, it returns without copying (DECISIONS 0039). All keys are
  read at the window's capture phase, not relying on the list's focus (`editmode.search_action`).
  While searching, a line of key hints is shown below the list (the same `_help` as edit).
  `search-mode` while in `edit` is refused, with the reason shown.
- Entry condition for `edit`: the active sheet must not be showing last-known-good (refused while
  `⚠ YAML error` is shown, with the reason).
- The error line is shared. A YAML error and a context-fetch failure are shown for as long as they
  hold; a one-off answer to an action (e.g. a refusal reason) **is cleared on the next mode
  change** and reverts to the former (e.g. a `search-mode` refusal shown during edit disappears
  once edit is exited).
- The hotkey (`toggle`) during `edit` and `search` is hide / show (an exception to 0013; for
  search, since 2026-09-23). The mode is kept, only the grab is dropped, and show restores it.
  `wayhint hide` does the same (DECISIONS 0037). The `Close` button actually closes (search is
  exited with the filter saved, edit's draft is discarded).
- **A second press of a mode hotkey returns to the display state at entry** (0014 D4 amend,
  2026-09-23). If entered while hidden, it exits the mode and hides (NONE, focus restored to the
  previous view). If entered while showing, it exits the mode and keeps showing `normal`.
  "Entered while hidden" is held in the view's `mode_entered_hidden` (memory only) and cleared on
  exiting the mode. It is not cleared by `toggle`'s hide/show, and edit keeps it across leaving and
  returning to the workspace (search doesn't keep it, since it's exited on leaving the workspace).
  `Esc` only exits the mode without changing the display.
- Launching the editor ("Edit in editor") does not hide the overlay (DECISIONS 0023), so results
  curated in the editor can be seen via reload after each save. When in `edit` / `search`, it
  returns to `normal` via the same path as Escape (keyboard_mode NONE, focus restored to the
  previous view), so the editor can receive input. In `normal`, nothing happens. Any open draft is
  kept on the view and reopened on the next `edit-mode`. If launching fails, an error is shown
  without changing mode.
- Edit state (mode, open form, form field values, target hint id, destination sheet for adding) is
  kept at the same granularity as the per-workspace context dict. Memory only.
- Mode changes and form cancellation go through the daemon, and the UI just renders that state.
  If the view returned to has no form, it is explicitly closed, so another workspace's form is
  never left behind. The search button is disabled while editing; search after finishing editing.
  `edit-mode` on a hidden edit screen redisplays the kept draft. `edit-mode` from `normal`
  re-fetches context, same as `search-mode` (0035).
- **The state after saving depends on the action** (DECISIONS 0021).

  | action | after completion |
  |---|---|
  | quick add form (`a` → Enter) | `normal` (keyboard_mode NONE, focus restored to previous view) |
  | edit form (Enter → Enter) | `normal` (same as above) |
  | `f` / `J` `K` / `d` `d` / `u` | stays in `edit` |
  | form's `Esc` (discard input) | stays in `edit` |
  | validation failure | stays in `edit`, form left open |

  The order of operations for saving a form is: file write succeeds → mode changes to `normal` →
  `_sync_keyboard_mode()` → focus restored (same path as exiting search). If the write fails, the
  mode is not changed. Quick add that also creates a new sheet (§7) returns to `normal` the same
  way. No separate "save and stay" key or config item is provided.

### 2. Key bindings (while in edit)

| key | action |
|---|---|
| `a` | opens the quick add form (destination is the selected hint's sheet, §3) |
| `Enter` | opens the edit form for the selected hint |
| `d` `d` | deletes the selected hint (first press shows a confirmation, second confirms; any other key cancels) |
| `u` | restores the last deleted hint to the end of its original sheet (holds 1 item in memory, session only) |
| `f` | toggles favorite |
| `J` / `K` | swaps with the hint below / above on screen (constraints in §5). Disabled while filtered (0033) |
| `↑` `↓` | moves the selection (`KP_Up` / `KP_Down` do the same. handled by CAPTURE, like the single-key bindings) |
| `Esc` | closes the open form (discarding input) if one is open, otherwise exits `edit` |

Single-key bindings in the list and `Tab` / `Shift+Tab` are handled by an `EventControllerKey` at
the CAPTURE phase (to run before the ListBox's row handling or Tab's focus movement). `Enter` /
`Esc` in text fields go to the input method first and are handled at the bubble phase (so as not
to steal IME commit/cancel).

`↑` `↓` are handled through the same path (changed 2026-09-23; originally "use the GTK default").
In a layer surface grabbing the keyboard with EXCLUSIVE, focus given to the list by the window
does not stick — `grab_focus()` returns true, but AT-SPI reports no row as focused, and the first
arrow key just "enters the list" and is consumed (measured on labwc 0.20.2). The result had been
that **without a mouse, `f` / `J` / `K` / `Enter` / `d` `d` never reached the second row on**.
Moving the selection is decided by the pure function `editmode.next_selection()`, which does not
wrap at the ends. In a text field, arrows move the cursor, so they are not intercepted while
`editable`.

The list's keys are handled only with no modifier. `Ctrl+d` and the like belong to another app or
widget, and using them for delete confirmation would trigger an action nobody intended.
`Tab` / `Shift+Tab` / `Ctrl+P`, which are also intercepted in a text field, **go to the input
method while composing (preedit present)** (used for candidate selection/navigation). Preedit
presence is tracked via `GtkText::preedit-changed`.

While in edit, this key list is shown at the bottom of the overlay in 1-2 lines (i18n en/ja).

Inside a form: `Enter` saves, `Esc` discards, `Tab` / `Shift+Tab` moves between fields, `Ctrl+P`
toggles the destination to the parent sheet (quick add only).

### 3. Form (quick add and edit share the same form)

| field | required | notes |
|---|---|---|
| title | ✓ | |
| kind | ✓ | `shortcut` / `command` / `tip` / `note`. quick add default is `shortcut` |
| key / command | – | decided by kind. `shortcut` → `key`, `command` → `command`, `tip` → **both**, `note` → **neither**. tip and note are memos |
| category | – | empty means null (shown as the pseudo-category `inbox`; `未定義` in Japanese) |
| remark | – | |

- The edit form is prefilled with existing values. `id` is display-only.
- Auto-set on save (quick add only): `id` (slug of title, collision → `-2`…, `q-YYYYMMDD-HHMMSS`
  if it can't be generated), `learned` (today), `favorite: false`, everything else null. When a
  parent sheet destination is given, the tag from `effective_parent_tags` is attached (only when
  stages 1-3 of 0034 have decided a filter; not attached when everything is passed through).
- Validated before saving. On failure, the error is shown inside the form and nothing is written
  (stays in `edit`, form stays open).
- On successful save, the form closes, `edit` is exited, and it returns to `normal` (see §1's
  table). To keep adding, call `wayhint edit-mode` → `a` again.
- Destination: **the selected hint's owning sheet** (DECISIONS 0025). Since the list mixes in
  parent-sheet hints, an addition goes into the same sheet as what's being looked at. With
  nothing selected, or if the owning file is gone, the active sheet is used, and failing that,
  a new sheet is created per §7. `Ctrl+P` switches the destination to the parent sheet. The form's
  heading shows the destination sheet's name. Editing a mixed-in hint writes to its owning sheet
  (0014 D9). However, **if the foreground app's sheet is missing or empty**, the addition goes to
  the foreground app's sheet regardless of selection (creating one per §7 if needed) (DECISIONS
  0041), because every row in the list is then from a parent/include and the first one gets
  auto-selected.

### 4. Writing back (yaml_store)

Implemented as pure functions, importing neither GTK nor pywayland.

| function | content |
|---|---|
| `write_document(path, doc)` | temp file (extension other than `.yaml`/`.yml`, same directory, **a distinct name per writer**) → validate → copy `st_mode` → `os.replace` |
| `build_hint(fields) -> CommentedMap` | 12 fields in canonical order, unset as null, `tags` in flow style |
| `append_hint(doc, hint)` | appends to the end of `hints` |
| `update_hint(doc, id, fields)` | rebuilds the matching hint in canonical order. `HintNotFoundError` if not found |
| `delete_hint(doc, id) -> removed` | also removes the preceding block comment. returns the removed node (for undo) |
| `swap_hints(doc, id_a, id_b)` | swaps position. re-attaches the preceding comment in `ca.items` |
| `set_favorite(doc, id, value)` | |
| `ensure_modeline(doc, schema_path)` | adds a modeline at the top. does nothing if already present |
| `match_rule_for_context(ctx) -> (match, warning)` | §7. the warning is shown by the caller (UI/CLI) |
| `create_sheet(ctx, first_hint, config, hints_dir=None, existing_ids=(), now=None)` | §7. returns `(path, doc)`. `hints_dir` / `now` are injectable, defaulting to `config_dir()/hints` and the current time |
| `normalize_sheet(doc, modeline_path=None)` | format: puts every hint in canonical order, all 12 fields. sheet metadata untouched |
| `slug(text, existing=(), now=None)` | id / filename. collision → `-2`, `q-YYYYMMDD-HHMMSS` if none can be generated |

Exceptions are `SheetWriteError` (write failure, or validation failure; carries `.issues`), and
its subclass `HintNotFoundError`. Constants: `CANONICAL_HINT_KEYS` / `DUMP_WIDTH` /
`MODELINE_PREFIX`.

Reading and writing use the existing `read_document`, and `_yaml()` adds
`indent(mapping=2, sequence=4, offset=2)` and a `width` that prevents wrapping. Load and dump
share the same settings. The 12 canonical fields are in Data model, "hints/*.yaml".
`json_schema() -> dict` (generated from the validation definitions) lives in the new module
`schema.py`.

### 5. Display order and reordering

Display order is described in Data model, "hints/*.yaml". Labels are pseudo-categories.

`J` / `K` constraints:
- Swaps only when the neighbor is in the same group (within the favorite block, or the same
  category within the non-favorite block) and the same sheet. Same sheet is decided by
  `hint.location.file`.
- Otherwise does nothing (no sound or display change).
- Does nothing while filtered (the on-screen neighbor and the YAML neighbor would diverge.
  DECISIONS 0033).
- CLI's `move` exits with an error across a group/sheet boundary; the GUI does nothing (message
  only).

### 6. Delete and undo

- `d` `d` confirms. Pressing any other key first cancels.
- Only 1 deleted node is held in memory. `u` appends it to the end of its original sheet. If the
  sheet is gone, an error is shown.

### 7. Creating a new sheet

- path: `~/.config/wayhint/hints/<lang>/<slug>.yaml` (the directory for the current display
  language, 0024). slug is derived from the app name / process name. On sheet id collision, `-2`.
- content: a leading comment (generation timestamp, `desktop_app`, `parent_context`,
  `foreground_process.name`, the regex adopted); if `editor.schema_modeline` is true, a
  `# yaml-language-server: $schema=<the absolute path from expanding editor.schema_path>` line at
  the top; `id` `title` `priority` (default) `match` `hints: [first_hint]`.
- Generating `match`:
  - `foreground_process is None` → app_id match
  - `foreground_process` present → `process.argv_regex: ["^<name>$"]`. Decided by the foreground
    process rather than `parent_context`: a terminal usually has no sheet of its own
    (`parent_context` is `null`), and a rule built from its app_id would match every command run
    in that terminal (0027)
  - if `name` is a generic name (constant `GENERIC_PROCESS_NAMES`, in `matcher.py`) → candidates
    are the basenames of `argv[1:]` (candidate generation follows the same rule as matcher's
    `process_candidates` / `argv_basenames`). Arguments starting with `-` (options) are excluded
    as candidates. If there are no non-generic candidates, a warning is shown in the form
  - the app_id-match regex is a `re.escape`d exact match (e.g. `^org\.inkscape\.Inkscape$`)
  - warnings are returned via `match_rule_for_context`'s return value; the UI/CLI display them
- The new sheet is picked up by the FileMonitor reload immediately after creation.

### 8. Concurrent editing and reload

- Last write wins. No mtime comparison.
- Temp names are separated per writer (`<name>.<pid>-<seq>.tmp`). Since GUI and CLI, or two CLI
  invocations, may write the same sheet, sharing a temp name would let one side's read / replace /
  unlink race the other's, breaking "last write wins."
- If the target id is missing at save time, an error is shown and it's left to reload.
- Reload of one's own write is not suppressed. `_after_reload` restores the selection by hint id,
  falling back to index if not found. Scroll position is not saved by pixel; it just scrolls the
  restored selected hint into view (to the top if it can't be restored). The scrollbar is always
  shown (the overlay scrollbar is not used).
- A hint id is unique only within its sheet. GUI edit/delete/favorite/move/selection-restore use
  `(owning file, hint id)`. The edit form also holds the owning file, and does not substitute
  another sheet if the target disappears.
- A sheet's `id` must match its filename stem. A file whose id doesn't match is not read as hints
  and becomes an Issue instead (so a rename or backup copy doesn't multiply files claiming
  someone else's id. DECISIONS 0020).
- Even so, `x.yaml` and `x.yml` can still collide, so on duplication only the one read first in
  filename order is used, and the rest are not put in the store but become Issues (both filenames
  included). This avoids leaving the choice to chance when ambiguous (design document §59).
- Old gvim buffers are left to the editor (W11).

### 9. category filter (search state)

- If the first token of the search string starts with `#`, it's a category filter; the rest is a
  text search. The two are ANDed. `#-` is the pseudo-category for "no category" (a spelling that
  doesn't depend on language. DECISIONS 0033).
- `Tab` / `Shift+Tab` cycles: show all → category first-seen order (pseudo-categories included) →
  show all. If `#` input is partial, it completes. Cycling rewrites the leading `#<category> `
  token in the box (the box's string *is* the filter).
- Filter state is shown as a chip. The box's string is kept per sheet in state.yaml (0033,
  formerly "for the display session only").
- Implementation: the window's CAPTURE-phase controller handles `Tab` / `Shift+Tab` while
  searching (to keep the key path in one place).

### 10. IPC / CLI

Additional commands (added to `ipc.COMMANDS`):

| cmd | response |
|---|---|
| `context` | `{active_sheet, parent_context, desktop_app, process: {name, argv_basenames}, include, chain, error}`. The full argv is not included. `include` is the list of resolved mixed-in sheet ids (0026). `chain` is the list of **the nested providers' class names that were queried** (in order; currently 0 or 1 elements. A provider that answered `null` is included too — showing where to look). `error` is the reason context could not be obtained (shown by `wayhint context` as the reason a sheet is missing) |
| `shown` | not a subcommand; only `wayhint context --shown` sends it (`ipc.QUERIES`). Returns the current workspace's view's context **without re-resolving it**, the same items as `context` + `visible` `mode` + `filters` (`selection.explain_filters`: parent tag/category and where each came from — the key, file, and count — plus per-include-element filters and counts). `{ok: false}` if there is no view (0040) |
| `edit-mode` | enters edit mode (showing first if not already; even if already shown, re-fetches context and swaps the window if different — unless a draft kept from launching the editor exists, in which case it is not swapped. 0035). Calling again while in edit mode exits it (closing an open form first, if any). `{visible, mode, sheet, error}` |
| `search-mode` | enters search mode (showing first if not already; even if already shown, re-fetches context, swapping the window as in `toggle` if different). Calling again while searching exits it (keeping the filter). Refused while in `edit` (`{ok: false, error}`). `{visible, mode, sheet}` (0033) |

CLI (writes to files itself, not via the daemon; mutating commands require `--sheet ID`,
DECISIONS 0038) argument list is in the README's "CLI" section. `wayhint schema`, if PATH is
omitted, uses `editor.schema_path`; without `--write`, prints to stdout. `wayhint format
--modeline`'s path is `editor.schema_path`.

### 11. config additions

Adds `editor.schema_modeline`. Default and meaning are in Data model, "config.yaml".

### 12. i18n

New labels are added to both EN (key and value) and JA. Applies to: form field names and kind's
display, the key-binding help, pseudo-categories (`inbox`; `未定義` in Japanese), errors (validation
failure, id not found, editing disabled during YAML error, sheet missing), delete confirmation,
the generic process name warning.

Changing `appearance.language` **takes effect without restarting the daemon** (0024's "1
language = 1 directory" applies to UI text as well as sheets). Strings redrawn on every context
lookup automatically follow because they call `self._tr` each time, but **strings written once
when a widget was built** (the toolbar's 5 buttons, the search box's placeholder, the form's
field names and `Kind`) do not. Only these are tracked by `HintWindow._fixed()` as
`(setter, key)`, and `set_language()` re-applies them.
On the daemon side, `_reload_config` watches for a change in `appearance.language` and calls it
(a change in `hints_dir` can't be used to detect it — `ja` and `auto` can both resolve to the same
`hints/en/`).

### 13. Tests

Pure functions (`./scripts/check`):
- golden: every sheet in the repo (`examples/hints/<lang>/*.yaml`, `tests/fixtures/good/*.yaml`) +
  dirty fixtures (keys in random order, comments before/after a hint, trailing comments, blank
  lines between hints, mixed quoting, flow-style tags and match, a valueless `remark:`) — load →
  dump byte-for-byte match. Also an opt-in test against `*.yaml` in the directory pointed to by
  the environment variable `WAYHINT_GOLDEN_EXTRA_DIR` (skipped if unset; unset in CI)
- `swap_hints`: moving a commented hint keeps the comment attached
- `delete_hint`: the preceding comment is removed, the following comment stays
- `build_hint` / `update_hint`: canonical order, null notation, flow-style tags
- `create_sheet`: the three cases — app_id resolution / process resolution / generic name
- slug generation: collision, Japanese fallback, regex conformance
- `normalize_sheet`: an already-formatted sheet byte-matches after re-formatting; parse results
  are equal before and after formatting
- sort: the favorite block ignores category; the position of a null category
- `json_schema`: a sheet that passes validation also passes the schema

The manual real-machine checklist is listed below as T13-T24.

## Failure modes

| situation | behavior |
|---|---|
| desktop context unavailable (no protocol / IPC unavailable) | shows an error in the overlay. does not crash |
| Herdr unavailable / pane fetch fails | falls back to the desktop context (Herdr sheet) |
| foreground process unknown | Herdr hints only. never guessed via screen scraping |
| sheet YAML is invalid | keeps showing last-known-good with a `⚠ YAML error` (file/line/error). recovers automatically on fix |
| an id in `include` cannot be resolved / self-reference | ignores just that id and shows the sheet. surfaced as `Issue(severity="warning")` in the overlay and `wayhint validate`, but validate's exit code stays 0 |
| editor missing / launch fails | shows an error in the GUI |
| focus restore fails at end of search | keyboard_mode is still always dropped to none (never leave a grab behind) |
| the window to return focus to is not unique (same app_id and title on multiple windows) | gives up restoring focus and logs it. never grabs a different window |
| the workspace-watch connection drops | only the watching stops; the view being shown (mode, draft) is carried over to a single slot. Esc / the close button always exits it |
| YAML is not UTF-8 | treated as any other read failure Issue. keeps last-known-good |

## Testing strategy

- **unit** (§66): YAML parse, schema validation, size parse, % conversion, anchor conversion,
  app/process matcher, match priority, parent tag filter, favorite sort, search, editor argv
  expansion, source line mapping.
- **context tests** (§67, §68): mock desktop provider (Inkscape/Chromium/Herdr), mock Herdr
  process-info (bash/claude/codex/`node /path/to/codex`). nested: Herdr+Claude → Claude sheet +
  tag-intersected Herdr hints. favorite is unaffected.
- **real hardware** (§69-§73): not automated. verified with the manual checklist below.
- **contract tests**: connects the resolver to the **real** providers. Relying only on fakes would
  let every call pass even if a provider's signature diverged from what the resolver calls (the
  resolver's `except Exception` swallows `TypeError`, so on real hardware it would just silently
  stop answering). The nested side is `tests/test_context.py`'s `RealProviderContractTest`; the
  desktop side is `tests/test_desktop_providers.py`.
- **adapter tests** (`tests/test_desktop_providers.py`): the signature, and "becomes
  `ContextError` when there is no compositor," always run headless. In a session with a
  compositor, it actually connects and checks the shape of the snapshot / `find_output`, and that
  GTK + the gtk4-layer-shell typelib load in the order from DECISIONS 0009 (via `_load_gui()` in a
  child process). If there is none, it's skipped.
- **keyboard grab** (`tests/test_window_grab.py`): `keyboard_grab` itself is pure and already
  verified headless, but **whether the widget side actually applies it** used to be checked only
  by the manual checklist (T6 / T13 / T24). When a compositor is present, a real `HintWindow` is
  built and it's confirmed that the layer surface's `keyboard_mode` matches `keyboard_grab` in
  every state, and that hide drops the grab while keeping the mode. **The surface is never
  mapped** (`present()` is not called; `get_visible` is stubbed instead), so nothing appears
  on screen.
- **rendering** (`tests/test_window_render.py`): calls `HintWindow.lay_out()` (= `present_context`
  minus `set_visible` / `present`), and checks that the list matches
  `sort_hints(visible_hints(...))`, the `parent › child` heading and context label (app_id with
  the suffix stripped), the display with no sheet, and that the layer surface's anchor / margin /
  size match `geometry.placement` (both global setting and sheet override), and that filtering by
  search and exiting restores it. The surface is not mapped here either.
- **daemon → window** (`tests/test_daemon_window.py`): pushes one line arriving at the socket
  through `ipc.handle_request` → `dispatch` → the **real `HintWindow`**. `test_daemon_edit` fakes
  the window, and `test_window_render` builds context by hand, so only the seam between them had
  gone unwatched. Whatever the caller is (compositor keybind / CLI / a future path), it's
  normalized to the same `{"cmd": ...}` before reaching here, so this is where "did the right
  thing come out" gets decided. The surface is not mapped here either (`present` / `set_visible`
  are stubbed, and `get_visible` returns whatever was passed to `set_visible`, so the keyboard
  rules can observe visibility changes).
- **headless GUI** (`tests/test_gui_headless.py`, entry point `./scripts/check-gui`): brings up a
  compositor with `WLR_BACKENDS=headless`, runs `wayhintd` inside it, and measures the actually
  mapped surface (DECISIONS 0030). Session startup/teardown and grim / AT-SPI / wtype calls live
  in `tools/headless.py`; `tests/headless.py` just adds unittest opt-in and skip on top (shared
  with the demo generator `scripts/demo`). Since a layer surface is a *request* to the compositor,
  how anchor and margin were interpreted can't be seen from inside the process. **Position** is
  read from the bounding box of the diff between a frame with the overlay shown and one without
  (font-independent); **content** is read via AT-SPI's accessible name. Full baseline-image
  comparison is not used (0030). Input injection (compositor keybind → CLI → IPC) only runs where
  `wtype` is available. The user's own session is never touched — a dedicated
  `XDG_RUNTIME_DIR` / `XDG_CONFIG_HOME` / `HOME` / session bus is given instead.
- `./scripts/check` is the sole entry point that runs the unit/context tests. Imports depending on
  GTK/pywayland/PyWayfire are kept out of tests, so they run headless (skipped where real
  hardware is needed — see adapter tests above). Anything needing a headless compositor goes to
  `./scripts/check-gui`, skipped unless `WAYHINT_GUI_TESTS=1` is set (the default `check` stays a
  few hundred ms with no dependencies).
- The daemon's GUI import is deferred until startup. `tests/test_daemon_edit.py` fakes the
  boundary between the window and the workspace, and goes through the real daemon / SheetStore /
  YAML save to check the target file and edit state.

## Demo generation

The intro videos are generated by `./scripts/demo --showcase <name> --record` from
`demo/showcases/<name>/02_<name>_scenario.yaml` (DECISIONS 0031, 0032). Built on the same
foundation as the tests:

```
tools/headless.py ──┬── tests/headless.py ── tests/test_gui_headless.py   (./scripts/check-gui)
 (compositor /      │
  daemon / grim /   └── tools/demo/session.py ── tools/demo/__main__.py    (./scripts/demo)
  AT-SPI / wtype)
```

`tools/headless.py` is the headless session itself (a dedicated `XDG_RUNTIME_DIR` /
`XDG_CONFIG_HOME` / `HOME` / session bus, starting/tearing down the compositor and `wayhintd`,
grim, AT-SPI, wtype). `tests/headless.py` is a thin layer adding only unittest opt-in and skip,
and `tools/demo/` adds 2 keybinds, `windowRules`, and a working copy of the fixtures to the same
session. **Changing this affects both `./scripts/check-gui` and the demo.**

`tools/demo/`'s division of labor: showcase (resolving the directory and role files), scenario
(loading and validation, duration calculation), session (checking prerequisites, placing
fixtures, isolated startup/stop of Herdr), actions (running an action and judging `wait_for`),
capture (frame-stepping and the contact sheet), encode (ffmpeg and SRT). Duration is decided by
rounding the scenario's `hold` to a number of frames, capturing 1 frame per step and duplicating
it. How to write a scenario is in `demo/README.md`.

### Showcase and variant (DECISIONS 0032)

One video is a **showcase**, self-contained under `demo/showcases/<name>/`. Files inside are
found by the role at the end of their name (`<NN>_<showcase>_<role>.<ext>`; `storyboard` is the
script, `scenario` is for execution). A warning if the middle part differs from the directory
name, an error if the same role appears twice. Output goes to `out/<lang>/<variant>/` and is not
tracked.

One scenario defines each step once, and a **variant** (`60s` / `3min` / `5min`) lists its ids in
sequence. A variant is *a complete sequence that stands on its own when run from a clean session*;
no state carries over between variants. `--dry-run` checks each variant's planned duration against
`target ± tolerance` and stops if it's off.

### Isolating Herdr (DECISIONS 0032)

The `herdr` showcase runs **the real Herdr**. `tools/demo/session.py` writes a minimal
`config.toml` into the session's `XDG_CONFIG_HOME` (turning off onboarding and theme selection,
version checks, and tab-name prompts, and fixing the shell and window title), and
`HeadlessSession.env()` **strips `HERDR_*`** — without that, the herdr client inside the session
would connect to the real user's server. Herdr's server daemonizes and leaves the session's
process group, so `herdr server stop` is called **before** tearing down the session, and if any
remain, only herdr processes whose `/proc/*/environ` `HOME` matches the session's are killed.

### Language

Only `hints/<lang>/` and `caption.<lang>` are per-language; `config.yaml` is single. The recorder
writes `appearance.language` into the session's copy, leaving the repository fixture untouched.
Japanese comes first, and `--validate` requires only the ja captions.

### Real-hardware checklist (§69-§73, manual)

Out of scope for `./scripts/check`. Run in both a labwc and a Wayfire session, and **record the
result in `STATUS.md`, dated**. This list only defines the items; it carries no pass/fail. Since
the same item can come out differently per compositor, the record is kept in one place.

- T1 shown at top-right on hotkey, input keeps going to the original app (no keyboard grab)
  (position and the hotkey path are checked headless by `./scripts/check-gui`; on real hardware
  check "input keeps going to the original app")
- T2 hidden by the same hotkey (toggle) (same as above)
- T3 launched from an app on a different output → appears on that app's output (multiple outputs
  aren't set up headless, so this stays on real hardware)
- T4 a sheet's `display.output` override works
- T5 `width: 30%` / `height: 60%` are based on the target output's logical size
  (`./scripts/check-gui` checks this on a single output; on real hardware, check with a rotated or
  scaled output)
- T6 input is received only while searching, and after finishing / Esc no grab remains and focus
  returns to the previous view
- T7 edit in editor: the selected hint's sheet opens and jumps to that line; with nothing
  selected, the shown sheet's start
- T8 Herdr with bash → Herdr hints; with `claude` → the Claude sheet + tagged Herdr hints
- T9 Herdr with an unknown process → Herdr hints only
- T10 edit the YAML while shown → updates without closing
- T11 break the YAML → doesn't crash, shows last-known-good + `⚠ YAML error`, recovers on fix
- T12 after closing with "Close," it doesn't reappear even after switching workspaces back and forth
- T13 `wayhint edit-mode` → EXCLUSIVE, Esc returns to NONE and focus returns to the previous
  view. Calling `wayhint edit-mode` again also exits (if a form is open, the first call just
  closes the form). From working (hidden) via `Super+Ctrl+H` → `Super+Ctrl+H` again, the overlay
  disappears and **input goes straight through to the original app**
  **(confirmed 2026-09-24)**
- T14 leaving the workspace during edit → NONE; returning re-applies the grab with input intact
- T15 the hotkey during edit → hide / show, input intact
- T16 quick add in a context with no sheet → a new sheet is created, and right after saving, that
  hint appears in the list (without waiting for the next hotkey). After saving, the overlay stays
  shown, back in `normal`, and input reaches the original app. To keep adding, `wayhint
  edit-mode` → `a` again (appended to the same sheet) **(confirmed 2026-09-19)**
- T17 actions that stay in `edit` (`f` / `J` `K` etc.) → reload doesn't close the overlay and
  keeps the selection position. If the selected hint scrolls off screen, it scrolls back into
  view. The scrollbar shows when the list doesn't fit. For a form save, confirm the same in the
  list back in `normal` **(confirmed 2026-09-19)**
- T17b `↑` `↓` move the selection one row at a time, stopping at the ends. `f` affects the row
  moved to (no mouse) **(confirmed 2026-09-23)**
- T18 open in gvim, then save via GUI → gvim gets W11
- T19 `Tab` / `Shift+Tab` in search → cycles category, focus never leaves the overlay. From
  working (hidden) via `Super+Shift+H` → `Super+Shift+H` again, the overlay disappears and
  **input goes straight through to the original app** **(confirmed 2026-09-24)**
- T20 partial `#` input + Tab → completes
- T21 `wayhint edit-mode` during `⚠ YAML error` → refusal message, no grab
- T22 `d` `d` → deletes, `u` → restores
- T22b press `f` twice in a row → favorite is set then unset. press `J` twice in a row → moves
  down two **(confirmed 2026-09-19)**
- T23 edit a mixed-in hint (from a parent sheet) → the parent sheet's file is updated
- T23c select a mixed-in hint (from a parent sheet) and press `a` → the form's heading becomes
  the parent sheet, and saving appends to the parent sheet's file. Pressing `a` with nothing
  selected uses the active sheet as the destination
- T23d a parent sheet exists, and the foreground process has no sheet (or `hints: []`), and with
  a parent hint selected, press `a` → the heading becomes "→ new sheet" (or that name if the
  sheet is empty), and saving goes into the foreground process's sheet. `Ctrl+P` switches to
  the parent (0041)
- T23b copy a sheet under another name (`claude.yaml` → `claude-backup.yaml`) → the list doesn't
  grow, and a filename/id mismatch `⚠` appears **(confirmed 2026-09-19)**
- T30 switch `appearance.language` between `ja` / `en` (or change `LANG` and start the daemon) →
  the UI text switches along with `hints/ja/` and `hints/en/`. A language missing one falls back
  to `en`; if neither exists, `hints/*.yaml` is read. **Rewriting config.yaml while the overlay is
  shown switches the buttons and field names too, without restarting** (automated test:
  `tests/test_daemon_window.py`; on real hardware check the rewrite-while-open case)
- T31 a sheet's `include` shows another sheet's hints at the end of the list; editing one updates
  its owning file (the detail pane's `File:` shows the write destination)
- T32 config's `include` applies to every sheet that doesn't write its own `include`, and is
  replaced in a sheet that does write `include:` (`include: []` mixes in nothing)
- T33 a sheet without `match` is never shown standalone, only via `include`
- T34 writing an unresolvable id into `include` still shows the sheet, with a warning in the
  overlay's `⚠` and in `wayhint validate` (validate's exit code stays 0)
- T35 `wayhint context`'s response includes `include`
- T24 input reaches the original app after every action (no grab left behind; shared check across
  existing items)
- T25 drag a corner/edge grip → follows and resizes, and on release config.yaml is rewritten in
  px. Same size after closing and reopening, and after restarting the daemon
  **(confirmed 2026-09-18)**
- T26 when key and title are each one line, their baselines align. When either wraps, the
  one-line one sits at the vertical center of the row's height (change the overlay's width via
  the grip to make the title wrap) **(confirmed 2026-09-18)**
- T27 `Tab` / `Ctrl+P` while composing with IME → candidate operations work and are not stolen for
  field movement or the parent-sheet toggle. After commit, back to normal field movement
  **(confirmed 2026-09-19)**
- T28 "Edit in editor" → the overlay stays shown, input reaches the editor (pressed from `edit` /
  `search`, it returns to `normal`). Saving in the editor updates the overlay's list in place. Any
  open draft returns on the next `wayhint edit-mode`. If the editor fails to launch, mode doesn't
  change and an error is shown **(confirmed 2026-09-19)**
- T29 with the output rotated 90 degrees, `width: 50%` → placed based on the post-rotation logical
  size (not done — needs a monitor that can rotate)
- T38 keybinding → `wayhint search-mode` shows the overlay with focus in the search box, and
  Japanese IME input works **(confirmed 2026-09-23)**
- T39 type a word and `Enter` → focus returns to the original app. the overlay stays filtered, in
  `normal` **(confirmed 2026-09-23. At the time, `Enter` also copied; 0039 moved copying to
  T47's `c`)**
- T40 `Esc` exits with the filter kept, and a chip is shown. the chip's `×` returns to the full list
  **(confirmed 2026-09-23)**
- T41 the same filter applies to the same sheet even after restarting the daemon **(automated:
  `tests/test_search_checklist.py`'s `T41RestartTest`)**
- T42 corrupt state.yaml (`foo: [`) → the daemon starts with a single WARN and no filter. Once
  search is next exited, valid content is written back **(automated: `T42BrokenStateTest`)**
- T43 `edit-mode` while filtered → `J` / `K` do nothing, `a` / `Enter` / `d` `d` / `f` work
  **(automated: `T43EditWhileFilteredTest`, real `HintWindow`)**
- T44 opening the same sheet in a different workspace shows the same filter **(automated:
  `T44WorkspaceTest`)**
- T45 `search-mode` again while in `search` → returns to `normal`, input reaches the original app
  **(automated: `tests/test_gui_headless.py`'s `SearchChecklistTest`, check-gui)**. Also via the
  real `rc.xml` keybind (`W-S-h`), and from an overlay left open in a different window
  **(confirmed 2026-09-23)**
- T46 rewriting a sheet's content via another route while in `search` → the box's string, cursor,
  focus, and filter are kept **(automated: `T46aReloadWhileSearchingTest`)**. "Edit in editor"
  while in `search` → returns to `normal`, and the filtered list updates on every save
  **(automated: `SearchChecklistTest`, both in-place and rename-style saves)**. Also with real
  gvim **(confirmed 2026-09-23)**
- T47 while searching, a line of key hints is shown below the list. Type a word, `↓`, then `c` →
  the selected hint's command goes to the clipboard and can be pasted into the original app. `c`
  on a key-only hint → returns to the original app without copying. `↑` at the top of the list →
  back to the search box **(the key handling and copy target are automated:
  `SearchKeysOnTheWindowTest`; clipboard contents and pasting are not confirmed on real hardware)**

## Known limits and future work

- V1's limits are as in PRODUCT.md's "Out of scope".
- **Display across workspaces**: since a layer surface belongs to an output, not a workspace, the
  overlay by default keeps showing across a workspace switch. `context.workspace: current`
  (default) watches the active workspace with `ext_workspace_manager_v1` and opens/closes the
  overlay per workspace (DECISIONS 0012). **Wayfire is not supported.** Whether it exposes the
  protocol is unconfirmed for lack of real hardware, and what can't be confirmed isn't written
  down as supported. On a compositor without the protocol, it doesn't watch, and shows on every
  workspace as before.
- **Logical size under fractional scaling**: since `wl_output.scale` only holds an integer, at
  scales like 1.5x the logical size is an approximation (`mode / ceil(scale)`). Getting it exactly
  would require binding `xdg_output`'s `logical_size`, but this isn't added since the main
  environment (labwc) doesn't use fractional scaling (DECISIONS 0020). If a need arises, it will
  be raised separately as: use `xdg_output_manager`, falling back to the current calculation if
  absent. Rotation (`wl_output.geometry.transform`) and `mode`'s CURRENT flag are already handled.
- **Synchronous context-fetch calls**: Herdr (subprocess) and Wayland (roundtrip) both run
  synchronously on GTK's main loop. Measured at 2-3ms for 2 herdr round trips and 0-18ms for a
  Wayland snapshot, but an unresponsive peer stalls both rendering and IPC. On the Herdr side, the
  time cap for a single context fetch is kept shorter than `ipc.CLIENT_TIMEOUT`
  (`herdr.LOOKUP_BUDGET`), so nothing ever completes late after the CLI has given up. The Wayland
  side's roundtrip has no time limit. Making it async would change the adapter contract, so it's
  judged separately.
- Room for extension (§76, not included in V1): in-app modes (Vim/shell), SSH remote, tmux pane,
  terminal title detector, AI agent lifecycle state, per-context styling, usage frequency,
  recently learned, an explicit executable flag for running commands.
- Implementation order follows the design document's §79 Phase 1-9. Starting from Phase 1 (config
  loader / YAML model / validation), with Phase 0 as the §78 dependency check.
</content>
</invoke>
