# wayhint — Product

[日本語](PRODUCT.ja.md)

Source: "Context-dependent hint overlay for Wayfire — design document" (2026-09-16, hereafter
"the design document"). The names `context-hint` / `context_hint` / `~/.config/context-hint/`
used in the design document are read as `wayhint` / `wayhint` / `~/.config/wayhint/` in this
repository (DECISIONS 0002).

## Problem

When you forget how to do something in a Wayland environment, you end up repeating web searches
or manual lookups. Frequently used operations do not live in a fixed place, so your eyes have
nowhere steady to land, and operations, tips, and caveats you looked up in the past never
accumulate. In a nested environment like Herdr, you need hints for the app running inside
(Claude Code, Codex, ...) rather than for the outer terminal.

## Users and use cases

- There is exactly one user: yourself. This is your own **context-aware personal cheatsheet**,
  not a general shortcut list.
- How it is used: the moment you forget an operation, press the hotkey (default `Super+?`) →
  information for the current context appears, for you, always in the same place (default: top
  right of the screen) → press the same hotkey again once you are done reading, to dismiss it.
- Operations you look up get appended to YAML and the sheet grows over time. Additions, edits,
  and deletions are done entirely from the overlay's edit mode; when you need to revise a whole
  sheet, the overlay's "Edit in editor" opens the file at the right line in an external editor
  (gvim).

### Most important principle (design document §1.1 / §81)

> "The moment you forget an operation, looking at the same place you always look shows the
> information you personally need for that context."

Stable positioning, accurate context detection, controlling the amount of information, easy
updates, and not getting in the way of the foreground application take priority over adding
features. When in doubt about scope, come back to this.

## Scope

### In scope

- Supported environment (official V1 target): Linux / Wayland (wlroots family: labwc, Wayfire) /
  Python 3 / GTK4 / PyGObject / gtk4-layer-shell / pywayland (wlr-foreign-toplevel) / YAML.
  Wayfire IPC (PyWayfire) is an optional fallback.
- Hierarchy of context detection: the compositor's active toplevel → application → (for Herdr)
  focused pane → foreground process. V1 goes as far as the foreground process.
- Nested display: hints from the child sheet (e.g. Claude Code) plus hints from the parent sheet
  (Herdr). Both are shown by default. Filtering happens only when a tag is written on the parent
  side (`nested.export_tags`) or on the child side / in config (`parent_tags`) (DECISIONS 0034).
- One YAML file per application/context (`~/.config/wayhint/hints/*.yaml`).
- Search (normal display does not grab the keyboard; it becomes interactive only once search
  starts).
- Detail view (remark / source / learned / tags appear only in the detail view; id / kind are
  never shown). Clipboard copy. The detail view also shows what would be copied whenever it is
  not exactly the command on the row, control characters written out.
- Editing via an external editor (Edit in editor: opens the sheet and jumps to the matching
  line), automatic reload on YAML save, keeping the last-known-good state on invalid YAML.
- daemon + CLI (`wayhint toggle|show|hide|refresh|validate`), Unix domain socket IPC, the hotkey
  is delegated to the compositor's own keybinding.
- Display position (9 anchors), size in px/%, margin, manual resize with the mouse (saved to
  config.yaml in px), multi-monitor (automatic active-output selection + override), font
  selection, GTK CSS override.

### Out of scope (not implemented in V1 — design document §75)

- Guaranteed support for X11 / GNOME / KDE (compositor dependence is isolated in the adapter;
  porting to anything outside the wlroots family that exposes wlr-foreign-toplevel and
  layer-shell is out of requirements)
- AI-generated hints, automatic hint retrieval from the web, cloud sync, hint usage analytics
- **Automatic command execution** (the `command` field in YAML is for display and copy only)
- Inferring context by terminal screen scraping
- Detecting Vim mode / Claude Code's internal mode / Codex's internal mode / an app's internal
  dialog state
- A dynamic plugin system (loader, entry points, marketplace)
- Editing YAML directly as text in the GUI. Structured editing at the level of a single hint is
  in scope under 0014. Changes to sheet metadata, match rules, or ordering remain external-editor
  only
- Live polling while idle (context is fetched only on toggle/show/refresh)

## Requirements

### Functional

The design document's §3–§60 is the body of the requirements. Summary:

1. **toggle**: hotkey → fetch context → show; pressing the same hotkey again while shown →
   hide (§3).
2. **focus**: `keyboard_mode = none` in normal display. Input to the original app is never
   blocked (§3.2). Only becomes interactive when search starts (ON_DEMAND, EXCLUSIVE if needed),
   and always returns to none on exit, attempting to restore focus to the previous view (§4, §47,
   §48).
3. **layer-shell**: `layer: overlay`, `exclusive_zone: 0`, default anchor top-right. Does not
   reserve screen area (§6). Position is anchor + margin + size; absolute coordinates are not the
   primary method (§7, §9).
4. **size**: px and % can be mixed. % is relative to the logical size of the target output (§8).
5. **multi-monitor**: display target priority = sheet output override → the active view's output
   → the compositor's focused output (when obtainable) → global fallback (§10).
6. **context snapshot**: the context at the moment the overlay opens stays fixed while it is
   shown (`context.live_update: false`). Re-detection happens on close/reopen, pressing the
   hotkey again, `wayhint refresh`, or an explicit reload (§11).
7. **matcher**: `match.wayland.app_id_regex` (formerly `match.wayfire`) /
   `match.process.{argv_regex,cmdline_regex}`. When several match, resolve by priority → matcher
   specificity → file order (§16, §59).
8. **Herdr adapter**: gets the foreground process (name/argv/cmdline/pid/cwd) from
   `herdr pane current` / `herdr pane process-info --pane <id>`. Does not rely on name alone;
   also matches against the argv basename (`node /path/to/codex`). On lookup failure, falls back
   to Herdr's own hints only (§14, §15).
9. **parent tag filtering**: what is shown is decided by tag and category, not by favorite. The
   child sheet's `inherit.parent_tags` → global `nested.parent_tags` → the parent sheet's
   `nested.export_tags` → everything: use the first of these stages that is written, in that
   order; category is decided the same way via `*_categories`, and writing both is an OR.
   Global is for a blanket opt-out (`[]`). Elements of `include` can also be narrowed with
   `{sheet, tags, categories}` (§17–§19, §29, DECISIONS 0034 / 0036 / 0039, `docs/SHEETS.md`).
10. **hint schema**: `id` and `title` are required. Optional: `kind (shortcut|command|tip|note)`,
    `key`, `command`, `category`, `tags`, `favorite`, `copy`, `remark`, `source`, `learned`
    (§21–§26). Everything but `id` and `title` may be omitted. Any hint written by the GUI / CLI /
    formatter outputs all 12 fields, with nulls included.
11. **sort**: within the favorite section, YAML order; within the non-favorite section, first
    appearance order of category → then YAML order (§29).
12. **search**: matches against title/key/command/category/tags/remark, case-insensitive
    substring + token AND (§31). Input (search mode, while the keyboard is grabbed) and filtering
    (the list's state) are kept separate; the filter persists after leaving search and is saved
    per sheet to `state.yaml`. Entry points are the search button and `wayhint search-mode`
    (DECISIONS 0033).
13. **copy**: `copy` → `command` (`key` is never copied). GTK/GDK clipboard (§32). While
    searching, `c` on the list copies and leaves search. `Enter` leaves without copying (0033,
    0039).
14. **editor**: substitutes the configured argv's placeholders `{file}` `{line}` `{hint_id}` and
    runs `subprocess.Popen(argv, shell=False)` (§34–§38).
15. **reload**: event-driven watching (e.g. Gio.FileMonitor) → debounce → parse → validate → UI
    update. On parse failure, keeps the last-known-good state, shows `⚠ YAML error`, and recovers
    automatically once fixed (§39, §40).
16. **validate CLI**: YAML syntax / duplicate sheet id / duplicate hint id / invalid regex /
    invalid size / invalid anchor / invalid editor placeholder / unknown required field. Exit
    code is non-zero on error (§60).
17. **failure policy**: desktop context unavailable → show an error, do not crash. Herdr
    unavailable → fall back to desktop context. Editor missing → show an error in the GUI (§63).

### Non-functional

- **Security** (§33, §62): `os.system` / `shell=True` are forbidden. Strings coming from YAML,
  `/proc`, or Herdr are data and are never executed as commands. The editor is the only thing run,
  and only with its configured argv.
- **Performance** (§64, §65): no idle polling. Context is fetched only when displaying. File
  watching is event-driven.
- **Logging** (§61): standard `logging`, default level warning. Never logs personal information
  or terminal buffer contents.
- **Structure** (§77): compositor dependence is isolated in `context/wayland` (+ fallback
  `context/wayfire`), Herdr dependence in `context/herdr`. The UI only ever receives a
  `ResolvedContext`; it never calls the compositor or the Herdr CLI directly. The YAML schema is
  not changed without reason. When an external API differs from what was assumed, the adapter's
  internals change, not the upstream spec.

## Success criteria

- All items of the design document's §74 Acceptance Criteria.
- Real-hardware tests §69 (Test 1–11, on both labwc and Wayfire; procedure is the real-hardware
  checklist in `dev-docs/DESIGN.md`): top-right display, input keeps reaching the original app,
  toggle, launching from a different output, output override, px/% sizing, input possible only
  during Search, no grab left behind after Search, gvim Edit in editor (sheet opens and jumps to
  the right line).
- Herdr real-hardware tests §70: bash → Herdr hints; Claude Code / Codex → their own hints plus
  the tag designated for Herdr; unknown foreground → Herdr hints.
- §71 editor line jump, §72 reload without closing, §73 broken YAML does not crash and keeps
  last-known-good → recovers once fixed.

## Open questions

- The dependency check (§78) was done on 2026-09-16; results are in `dev-docs/PHASE0.md`. Not yet
  installed at that time: gtk4-layer-shell (apt), PyWayfire (PyPI name `wayfire`), ruamel.yaml
  (PyPI). pywayland was added on 2026-09-16 and getting toplevels plus `activate` via
  foreign-toplevel was confirmed on labwc. Wayfire was not running, so its IPC socket was not
  confirmed.
- Whether layer-shell `ON_DEMAND` gets focus as expected on labwc / Wayfire (§47). Undecided
  until confirmed on real hardware.
- Whether restoring focus via foreign-toplevel `activate` / Wayfire IPC also works safely through
  the UI (§48).
