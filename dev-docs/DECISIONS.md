# wayhint — Decisions

[日本語](DECISIONS.ja.md)

Lightweight ADRs. Newest last. One entry per decision that took discussion; a decision that was
obvious does not need one.

## 0001 — Implementation language: Python 3 + GTK4 / PyGObject / gtk4-layer-shell / PyWayfire

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: We need a layer-shell overlay on top of Wayfire, Wayfire IPC (PyWayfire), Herdr CLI
  integration, and preservation of YAML line numbers. There is a single user, and being able to
  grow the tool quickly matters more than anything else.
- **Decision**: Python 3. GUI with GTK4 + gtk4-layer-shell, compositor integration with PyWayfire,
  YAML with ruamel.yaml.
- **Alternatives**: Rust/C (richer GTK/layer-shell bindings, but slower to iterate on for a
  personal tool); web technology (does not run on Wayland layer-shell).
- **Consequences**: The target machine needs PyGObject and the gtk4-layer-shell Python binding
  installed (checking this dependency is Phase 0, §78). Startup cost is absorbed by keeping the
  daemon resident.

## 0002 — Name is wayhint (changed from the design doc's context-hint)

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: The design doc uses `context-hint` / `context_hint` / `~/.config/context-hint/`,
  but the working directory had already been created as `wayhint`.
- **Decision**: Use `wayhint` everywhere — repository, package, command, config directory (daemon
  is `wayhintd`, socket is `$XDG_RUNTIME_DIR/wayhint.sock`).
- **Alternatives**: Create a new directory named `context-hint` as the design doc says. There was
  no value in adding a directory just for naming consistency.
- **Consequences**: Read the design doc's naming as `wayhint` when referring to it. The rename
  convention is spelled out at the top of `dev-docs/PRODUCT.md`.

## 0003 — YAML loader is ruamel.yaml

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: "Edit hint" needs to jump the editor to a hint's definition line, so the parse
  result must carry line numbers.
- **Decision**: Use ruamel.yaml (round-trip loader) and keep each hint's start line in
  `SourceLocation`. The GUI does not write back.
- **Alternatives**: PyYAML (getting line numbers requires extending the Loader, and it cannot
  preserve comments either).
- **Consequences**: One more dependency. Also helps later if GUI editing is added, since structure
  is preserved.
- **Amended**: The part about "the GUI does not write back" is superseded by 0014. The choice of
  ruamel itself stands.

## 0004 — Hotkeys are delegated to the compositor; CLI ↔ daemon talk over a Unix domain socket

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: Capturing a global hotkey from the Wayland client side is difficult; it is natural
  for the compositor to own it. We want a single fixed entry point for toggling.
- **Decision**: The compositor's keybinding (initially Wayfire, labwc too from 0010 on) runs
  `wayhint toggle`. The CLI just sends to `$XDG_RUNTIME_DIR/wayhint.sock`. No network socket.
- **Alternatives**: D-Bus (adds dependencies and boilerplate); the daemon capturing the keybinding
  itself (not possible / not reliable on Wayland).
- **Consequences**: Keybindings must be configured per compositor (README "Compositor setup").
  The socket path depends on the runtime dir.

## 0005 — `command` is display/copy only; it is never executed

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: YAML is data the user frequently edits by hand in an editor. We do not want to
  create a path where it gets executed by accident.
- **Decision**: V1 has neither UI nor API to execute `command`. `shell=True` / `os.system` are
  banned across the codebase. The only thing that gets executed is the configured editor argv.
- **Alternatives**: Allow execution behind an `executable: true` flag (kept as a future extension
  candidate).
- **Consequences**: We give up the convenience of "run a command straight from a hint" in V1. The
  security boundary is reduced to the single point of the editor argv.

## 0006 — Finalize YAML schema details in Phase 1

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: The design doc (§21/§43) only lists field names; types, defaults, error conditions,
  and uniqueness scope were undecided. Implementing the validate CLI (PRODUCT requirement 16)
  needed these settled.
- **Decision**: As in `dev-docs/DESIGN.md` Data model. Key points: (a) size is one of three forms
  only — int=px / `Npx` / `N%` (0–100). (b) margin is an int or a 4-side mapping. (c) hint id is
  unique **within a sheet**; sheet id is globally unique (editor jump uses file+line, so global
  uniqueness of hint id is not required). (d) an unknown key is an error, not a warning (so a
  typo is noticed immediately). (e) `editor.command` requires `{file}`. (f) `version` is optional
  and fixed at 1. (g) YAML date scalars are normalized to ISO strings.
- **Alternatives**: Ignore unknown keys (more forgiving of future extension, but hides typos);
  make hint id globally unique (rejected, since the same hint name naturally recurs across
  sheets).
- **Consequences**: Extending the schema requires updating both validation and this entry. Since
  unknown keys are errors, adding a new key later makes old versions unreadable (distinguish via
  `version`).

## 0007 — Matcher specificity is "number of matched patterns"; category order is order of first
appearance

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: PRODUCT requirement 7's "priority → matcher specificity → file order" and
  requirement 11's "category order" left what counts as specificity / category order undefined.
- **Decision**: Specificity = the number of regex patterns in that sheet's match rule that
  actually matched (`argv_regex` is evaluated against name, each argv element, and the basename
  of argv[0]; `cmdline_regex` is evaluated against the full cmdline). Ties break by sheet load
  order (filename order). Category order is the order categories first appear in the displayed
  hint column (so as not to add another config item). 
- **Alternatives**: Compare by regex length (regex length does not reflect specificity);
  configure category order via config (V1's policy is not to add more config).
- **Consequences**: Use `priority` to favor a particular sheet. To change category order, change
  the order of hints inside the YAML.

## 0008 — IPC messages are one-request-per-connection, newline-terminated JSON

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: DECISIONS 0004 settled on UDS, but the message format (plain-text line vs. JSON)
  was still open.
- **Decision**: The client sends a single `{"cmd": "<toggle|show|hide|refresh|reload|ping>"}\n`,
  closes the write side, and the daemon returns a single `{"ok": true, ...}` or
  `{"ok": false, "error": "..."}` and disconnects. Cap at 4096 bytes. Unknown `cmd` is an error.
- **Alternatives**: A plain-text line (`toggle\n`). Choosing JSON avoids a redesign later when
  arguments like `show --sheet X` are added. A long-lived connection with event push is not
  needed for V1.
- **Consequences**: One CLI invocation = one connection. The daemon accepts via a GLib IO watch and
  reads asynchronously.

## 0009 — gtk4-layer-shell is loaded via ctypes before GTK

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: In a smoke test under a labwc session, importing `Gtk4LayerShell` before Gtk still
  made `is_supported()` return False and produced the "GtkWindow is not a layer surface" warning.
  gtk4-layer-shell hooks libwayland-client, so it needs to be loaded in-process before that, but
  PyGObject's typelib import order does not guarantee this.
- **Decision**: At the top of `daemon.py`, run
  `ctypes.CDLL("libgtk4-layer-shell.so.0", RTLD_GLOBAL)` before importing gi. Do not require the
  user to set `LD_PRELOAD`.
- **Alternatives**: Set `LD_PRELOAD` via a wrapper script or systemd unit (more configuration on
  the user's side, and it does not reproduce when `wayhintd` is invoked directly).
- **Consequences**: Depends on the library's soname. If it is not found, `Daemon.start` detects
  this via `is_supported()` and exits.

## 0010 — Desktop context defaults to wlr-foreign-toplevel, with Wayfire IPC as fallback

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: The real machine was moved from X11 to Wayland and now boots labwc natively;
  Wayfire is not running. labwc has no IPC to query windows. We want the same code to run on both
  compositors.
- **Decision**: `context/wayland.py` gets the activated toplevel's app_id / title / output using
  `wlr-foreign-toplevel-management-unstable-v1` (pywayland; generated code is vendored from
  `protocols/*.xml` via `scripts/gen-protocol` into `_wlr_foreign_toplevel.py`), and returns focus
  via `activate`. `context.backend: auto` (default) uses wayland, and only falls back to
  `context/wayfire.py` when the protocol is absent and `WAYFIRE_SOCKET` is set.
  `ResolvedContext.view_id: int` is changed to a backend-opaque `view_ref: str` (wayland:
  `"<app_id>\t<title>"`; wayfire: the view id string). YAML's `match.wayfire` is renamed to
  `match.wayland`, and the old spelling is still accepted as a synonym.
- **Alternatives**: `ext-foreign-toplevel-list-v1` (no activated state and no activate request);
  keeping a persistent connection and holding handles (adds more event-loop integration, and goes
  stale on compositor restart — kept consistent with the per-call-connection policy of 0001);
  a labwc-only adapter (no query mechanism).
- **Consequences**: pywayland becomes a required dependency; PyWayfire stays optional. Since pid
  cannot be obtained, desktop-level matching stays app_id-only (as before). Focus restoration can
  fail when several windows share an app_id and the title changes. Focused output is not in the
  protocol, and when there is no active toplevel on multiple outputs it falls back to the global
  case. pywayland proxies must be explicitly destroyed before the display disconnects or they
  segfault on GC, so `_Session.close()` destroys them explicitly.

## 0011 — Daemon start/stop is left to the compositor's autostart; not registered with a service
manager

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: We want `wayhintd` to start together with the session and to be reliably stopped
  when the compositor exits. We considered registering it as a systemd user unit tied to
  `graphical-session.target`.
- **Decision**: Start it as an ordinary process from the compositor's autostart, and leave
  stopping it to the compositor's shutdown handling. wayhint does not ship a service unit and it
  is not part of the install instructions.
- **Alternatives**:
  - A persistent user unit with `WantedBy=graphical-session.target`: labwc does not ship a
    `labwc-session.target`, and session configurations that never start the target are common; in
    that case the unit simply never starts. Whether it starts depending on configuration outside
    the compositor means the hotkey fails silently (no response).
  - A transient unit (`systemd-run --user -p Restart=on-failure`): only adds auto-restart. Since
    the overlay crashing does not block other work, monitoring's value does not outweigh masking
    crashes. Reconsider if crashes are actually observed in use (a few lines in autostart would
    suffice at that point).
- **Consequences**: Start/stop follows each compositor's autostart convention. There is no
  automatic recovery after an abnormal exit — the hotkey stays unresponsive until the next
  session. The socket is removed on SIGTERM; if killed, it is reclaimed by stale-socket detection
  on the next startup.

## 0012 — Overlay visibility is kept per workspace; the watcher connects only while it is open

- **Date**: 2026-09-17
- **Status**: accepted
- **Context**: A layer surface belongs to an output and has no workspace, so the overlay stays
  shown even after switching workspaces. There was a request to only see it on the workspace it
  was opened from. The first implementation just hid it on switch, but on the real machine, going
  back to the original workspace left it hidden and required reopening, which was inconvenient.
  Visibility is correctly a property of the workspace, not of the window.
- **Decision**: The daemon keeps a dict from workspace key to `ResolvedContext`. `show` adds an
  entry for the current workspace; `hide` removes only the current workspace's entry. When the
  active workspace changes, if that workspace has an entry it is shown again with the same
  context; if not, the window is hidden (the dict is left untouched). `toggle` decides based on
  "does this workspace have an entry", not on the window's visibility. The context shown is the
  snapshot taken at open time, replayed as-is (same treatment as the freezing in requirement 6; 
  update it if you want it refreshed). The watcher connects only while at least one entry exists,
  and disconnects once all are closed. The default is `context.workspace: current`; `all` restores
  the previous behavior.
- **Alternatives**:
  - Just hide on switch (the first implementation): stays hidden on return, so it cannot be left
    open per workspace.
  - Re-resolve context on return: switching workspaces back and forth increases round trips to
    Wayland and Herdr, and what was being viewed can change. Replaying the snapshot is more
    consistent with existing policy.
  - Decide `toggle` from the window's visibility: the hotkey path (socket) and workspace-change
    path (Wayland connection) differ and ordering is not guaranteed. A delayed event yields
    "pressed it but nothing showed".
  - Always-on connection to watch: keeps a connection and event handling alive even while nothing
    is open.
  - Have the compositor confine the layer surface to a workspace: labwc has no such setting, and
    the protocol itself scopes layer surfaces to the output, not a workspace.
- **Consequences**: Two modules now import pywayland (`wayland.py` and `workspace.py`).
  Compositors that do not emit `ext-workspace-v1` keep the old behavior regardless of config.
  Wayfire is unverified and treated as unsupported. The workspace identifier is the protocol's
  `id`, falling back to `name`; labwc 0.20.2 only sends `name`. If the compositor removes a
  workspace, its entry is also dropped. Opening/closing the overlay is called from inside the
  watcher's event dispatch, so it is deferred to a GLib idle. The fd must be drained with `read`;
  `dispatch` alone leaves the fd readable and the watch spins the CPU.
- **Amended**: Amended by 0014 (behavior during edit mode).

## 0013 — A hotkey press from a different window swaps rather than closes

- **Date**: 2026-09-17
- **Status**: accepted
- **Context**: If you show window1's hint, then move focus to window2 and press the hotkey, the
  hint just closed, and seeing window2's hint required pressing again. The meaning of the hotkey
  is "the hint for what I am looking at now"; closing should only happen when the same thing is
  already shown.
- **Decision**: `toggle` resolves the context at the moment it is pressed and compares it to what
  is currently shown. If they match, close; if they differ, swap. If nothing is shown, show it.
  The comparison uses `ResolvedContext.target_key()` = (active_sheet, parent_context, desktop_app,
  foreground process name).
- **Alternatives**:
  - Identify the window by an identifier: the only thing available is `view_ref`, made of app_id
    and title, and terminals rewrite the title with the running command. It would misjudge
    "different window" every few seconds.
  - Use `ext-foreign-toplevel-list-v1`'s stable identifier: labwc emits it, but this protocol has
    no focus state. Focus lives in `wlr-foreign-toplevel`, and the only way to correlate the two
    is app_id and title, so we are back to the same problem.
  - Always swap (never close): the hotkey would no longer be able to close.
- **Consequences**: `toggle` resolves context once even when it ends up closing (a Wayland round
  trip, and one `herdr` call when Herdr is in use). Between two windows that resolve to the same
  sheet, the result is an ordinary close rather than a swap. The shown content is identical so
  there is no visible glitch, but this is not window-level behavior.
- **Amended**: Amended by 0014 (behavior during edit mode).

## 0014 — Structured, per-hint editing from the GUI (edit mode) and the CLI

- **Date**: 2026-09-18
- **Status**: accepted
- **Supersedes**: the part of 0003 that says "the GUI does not write back", and PRODUCT.md's
  Out-of-scope item "editing YAML directly in the GUI"
- **Amends**: 0012 (per-workspace visibility state), 0013 (hotkey swaps)
- **Alternatives**:
  - Append-only quick add only (edit/delete stay in the editor): still leaves the burden of
    opening the editor for fixing typos and removing unneeded hints.
  - Inline editing in the detail pane: a 12-field form does not fit in a 420px width, and editing
    an existing hint is infrequent anyway.
  - A regular (non layer-shell) window for editing: departs from the "always the same place"
    principle and removes the distinction from the editor.
  - Don't build it, strengthen gvim instead (snippets/templates): does not solve the capture-time
    switching cost or the guesswork of match rules. However, the CLI route inherits this idea and
    was adopted.

### Context

When ruamel.yaml was adopted in 0003, the only motivation for writing back was "fixing an
existing hint", and an external editor was better suited to that. So we decided "the GUI does not
write back", and PRODUCT.md also put GUI editing in V1's Out of scope.

Since then, context resolution became layered — compositor → application → Herdr pane →
foreground process — and the weight of the cost of adding a hint shifted from "typing YAML" to
these two things:

1. **The switching cost at the moment of capture.** Right after investigating an operation, you
   want to leave a hint, but opening the editor, finding the end of `hints:`, recalling the YAML
   shape, and writing it is heavy as a "mental context switch". Editor snippets/templates only
   shave off "recalling the shape"; the switch itself remains as long as it means going to an
   editor.
2. **The cost of writing the first hint for a context that has no sheet yet.** What is heavy is
   not the YAML shape but the `match` rule — the human has to guess, from other sheets, "was this
   context determined by app_id, or by a process inside Herdr, and what regex would match". The
   daemon already has this answer as `ResolvedContext`, and an editor-side template can never fill
   it in.

So we scope write-back to "per-hint operations that can be filled in with information the daemon
already has" and place that on the daemon side. This is not "editing YAML directly in the GUI"; it
is structured editing that never makes the user think about YAML.

Checking against the principles: it satisfies "easy updates" (capture down to a few seconds,
automatic new-sheet creation) and "stable location" (self-contained inside the overlay). As for
"do not get in the way of the foreground application", we accept it by limiting how much keyboard
is grabbed to edit mode itself, on the reasoning that the moment of editing is a moment when you
are not touching the original app anyway.

### Decision

#### D1. Scope of operations

Both the GUI (edit mode) and the CLI perform the following per-hint operations, using the same
pure functions.

| Operation | GUI | CLI |
|---|---|---|
| Add (quick add) | `a` | `wayhint add` |
| Edit (5 fields) | `Enter` | `wayhint edit ID ...` |
| Delete | `d` `d` | `wayhint remove ID` |
| Favorite toggle | `f` | `wayhint favorite ID [--off]` |
| Reorder (swap with neighbor) | `J` `K` | `wayhint move ID up\|down` |

The fields handled by GUI/CLI are the five: **title / kind / key or command / category / remark**,
plus favorite. Everything else (`id` `tags` `copy` `source` `learned`, sheet metadata, `match`,
category ordering) is changed only via an external editor.

Add helper commands `wayhint format` (normalize) and `wayhint schema` (emit JSON Schema).

#### D2. Write-back rules

- ruamel.yaml round-trip: `typ="rt"`, `preserve_quotes=True`,
  `indent(mapping=2, sequence=4, offset=2)`, with `width` large enough that no wrapping happens.
- **When writing, emit all 12 fields in canonical order (`id` `title` `kind` `key` `command`
  `category` `tags` `favorite` `copy` `remark` `source` `learned`), with unset fields as null
  (just `key:`).** When reading, key order and omission do not matter.
- Only the hint being operated on is normalized. Other hints, sheet metadata, comments, blank
  lines, quote style, and flow style are left untouched.
- A new hint's `tags` is emitted in flow style (`tags: [a]`).
- Writes go to a tmp file in the same directory (extension other than `.yaml` / `.yml`, e.g.
  `<name>.yaml.tmp`), **passed through the existing validation (unknown keys / duplicate ids /
  invalid regex, etc.) first**, then `os.replace`d in. If validation fails, nothing is written and
  an error is shown.
- An existing sheet's file gets its `st_mode` copied from the original. A new sheet is left to
  umask.
- Concurrent edits: last write wins. No mtime comparison. If the target hint's `id` is not found
  at save time, show an error saying it was changed externally, and leave it to reload.
- Re-parsing triggered by our own write via the FileMonitor is not suppressed. After reload,
  selection and scroll position are restored by hint `id`; if the `id` is gone, fall back to
  index.
- Comment handling: when a hint is moved, its preceding block comment (`ca.items`) moves with it
  to the new location. On delete, the preceding block comment is deleted along with it (following
  the convention that a hint's preceding comment is its description). A trailing same-line
  comment belongs to the hint and follows it.
- While broken YAML is shown via last-known-good (the `⚠ YAML error` state), entry into edit mode
  is refused, with the reason shown, since round-tripping is not possible.

#### D3. Keyboard grab and state transitions

- The overlay has three states, `normal` / `search` / `edit`, and `keyboard_mode` is set only by
  **a single function derived from the state** (the equivalent of `_sync_keyboard_mode()`).
  `normal` = NONE, `search` / `edit` = EXCLUSIVE (`ON_DEMAND` requires the compositor to hand
  focus over via a re-click on the surface, so even clicking the search button sends input to the
  app below — confirmed on labwc 0.20.2). Every path — hide, leaving the workspace, Esc, hotkey —
  goes through this function. The invariant "no leftover grab" is enforced here.
- Single-key presses in the list, and `Tab` / `Shift+Tab`, are received in the CAPTURE phase via
  `EventControllerKey`, processed before GTK's built-ins (ListBox row navigation, Tab focus
  movement). `Enter` / `Esc` in text fields are handed to the input method first and received in
  the bubble phase (so as not to steal composition confirm/cancel).
- The entry point into edit mode is **primarily the compositor keybinding → `wayhint edit-mode`**
  (a new IPC command), with a toolbar button alongside it. Normal display is NONE, so it cannot be
  entered via a key on the overlay itself.
- While in edit mode, the key assignments are shown at the bottom.
- Saving keeps you in edit mode. `Esc` exits it.

#### D4. Relationship with 0012 / 0013 (amend)

- **Workspace switching (extension of 0012)**: edit state and unsaved drafts are kept per
  workspace. Leaving hides the overlay and returns it to `NONE`; returning re-establishes the grab
  and restores the in-progress edit content. Drafts are memory-only, never written to a file.
- **Hotkey (exception to 0013)**: during edit mode, the hotkey means **hide/show** of the overlay,
  not "swap". The hotkey's meaning is "the hint for what I am looking at now", but while writing,
  that is interpreted as "what I am writing now". The only path that discards input is `Esc`.
- **(2026-09-23 amend) The second press of a mode hotkey returns to the display state it was
  entered from.** For the second press of `edit-mode` and `search-mode`: if it was entered while
  hidden, exit the mode and hide (NONE, focus returns to the previous view); if entered while
  shown, exit the mode and keep showing `normal`. "Entered while hidden" is tracked per workspace
  view as a single bool (`mode_entered_hidden`, memory-only), cleared once the mode is exited. It
  is not cleared by `toggle`'s hide/show (edit survives leaving and returning to the workspace).
  When a form is open, the first press of `edit-mode` just closes the form; the next press exits
  and returns (a draft is never discarded by a single press). `toggle` and `Esc` are unchanged.
  Cross-mode presses (`search-mode` while in edit is rejected; `edit-mode` while in search goes
  straight to edit) are unchanged too. The path that exits and hides just calls the existing
  mode-exit and existing hide in sequence; only `_sync_keyboard_mode()` touches `keyboard_mode`.
  Rationale: someone who pressed it while hidden expects the same key to return them to their
  work. `toggle` restores visibility, `edit-mode` / `search-mode` restore the mode — each "undoes
  as much as was pressed".

#### D5. Quick add

- Fields: title (required) / kind (choice, default `shortcut`) / key and command (determined by
  kind: `shortcut` → `key`, `command` → `command`, `tip` → both, `note` → neither. tip and note
  are memos; tip can hold "press this, or run this" in a single hint. Amended 2026-09-18) /
  category (optional) / remark (optional).
- Auto-set fields: `id` is slugged from the title (matching `^[A-Za-z0-9][A-Za-z0-9._-]*$`, with
  `-2` `-3` on collision, and `q-YYYYMMDD-HHMMSS` if the slug would be empty); never changed by
  the GUI afterward. `learned` is today's date; also never changed by the GUI afterward.
  `favorite: false`; everything else null.
- An empty category (null) is treated as a mark of "not yet curated" and grouped at the end under
  a pseudo-category with an i18n label (en `inbox` / ja `未定義`) on display. **The value written
  to YAML never depends on locale.**
- The destination is the current context's active sheet. `Ctrl+P` toggles to the parent sheet, in
  which case the `effective_parent_tags` tags are attached to `tags`.
- In a context with no active sheet, a new sheet is created (D6).

#### D6. Automatic sheet creation

- The file is `~/.config/wayhint/hints/<slug>.yaml`. `id` / `title` are generated from the
  context's app name or process name; on sheet id collision, append `-2`. `priority` uses the
  default; `version` is omitted.
- `match` is generated from `ResolvedContext`. If `parent_context` is None, match on app_id; if
  `parent_context` is set and it was resolved via a process, use
  `process.argv_regex: ["^<name>$"]`.
- If the process name is a generic one (`python3` `python` `node` `sh` `bash`, etc. — the list is
  kept in one constant), candidates are formed from the basename of `argv[1:]` using the same rule
  as the matcher. A warning is shown only when there is not even one non-generic candidate.
- A regex built from app_id is an exact match on `re.escape` (needed for app_ids containing `.`).
- When generating candidates for a generic name, arguments starting with `-` (options) are
  excluded from candidates (so `bash -l` does not produce `^-l$`).
- The generated file's header is left with a comment recording the generation time, the context
  info used for the decision, and the regex adopted.
- The generated sheet becomes the `active_sheet` of the view currently shown. `active_sheet` is
  only decided when context is resolved (on show), so without this, even a reload from the file
  monitor would not show it in the list, and the next quick add would create a second sheet.
- If config `editor.schema_modeline: bool` (default false) is true, a
  `# yaml-language-server: $schema=...` header line is added. The path written after `$schema=` is
  config `editor.schema_path` (default `~/.config/wayhint/schema.json`). `wayhint format` also
  honors the same setting.

#### D7. Change to display order

Before: favorite → category order of first appearance → YAML order.
After: **within the favorite section, category is ignored and YAML order is used**; in the
non-favorite section, category order of first appearance is computed from the non-favorite hints
alone → then YAML order.
This lets favorites be reordered across categories. Reordering is implemented as a position swap
in the YAML, and a swap does not change the relative order of other hints.
Side effect: making the first hint of a category a favorite can move that category's position
within the non-favorite section (accepted, since making it a favorite is a deliberate action).

#### D8. Reordering constraints

- `J` `K` swap with the on-screen neighbor. If the neighbor is in a different group (favorite vs.
  non-favorite, or a different category within the non-favorite section), nothing moves. To change
  category, edit the category field instead.
- If the neighbor belongs to a different sheet (a hint pulled in from a parent sheet), nothing
  moves. There is no cross-file move.
- ~~`J` `K` also work while searching or filtering by category.~~ **Retracted (0020)**. While
  searching, the input field has focus, and the usual pattern is to keep adding or removing words
  even after the filter narrows things down, so letting `J` `K` reach the list would mean taking
  focus away from the input field. Reordering happens after search is finished.

#### D9. Hints pulled in from a parent sheet

Edit/delete/favorite write to the file of the hint's owning sheet. Ownership is determined by
`hint.location.file`. Reordering, per D8, never crosses sheets.

#### D10. Category filter

Inside search mode, provide both a `#category` syntax (leading token only) and `Tab` /
`Shift+Tab` cycling. Both write to the same single filter state. `Tab` while typing `#` is
completion. Cycle order: show all → category order of first appearance (including the pseudo
category) → show all.
Filter state is volatile — it lasts only for the display session.

#### D11. IPC / CLI

- Add `context` (returns only the fields of `ResolvedContext` needed) and `edit-mode` (enters edit
  mode) to the IPC.
- The CLI decides the sheet from the `context` result and **writes to the file itself, without
  going through the daemon**; the adapter stays on the daemon side, and the write function is
  shared with the GUI. The FileMonitor picks up the change and the overlay updates.

### Consequences

- Docs to update: PRODUCT.md Out of scope, DESIGN.md (schema table, display order, real-machine
  checklist, edit-mode spec), README's field table and compositor setup examples, AGENTS.md §4's
  "ui/ receives only ResolvedContext" brought in line with reality, STATUS.md.
- "Beyond that, write only what you want to write" becomes "Optional. GUI / CLI / format always
  emit all 12 fields, including nulls." Existing hand-written sheets are normalized in bulk by
  hand via `wayhint format`.
- Add dump paths and pure hint-operation functions to yaml_store.py, plus golden tests (round-trip
  byte equality, moving/deleting a hint with a comment, null notation, preserving flow style). GUI
  parts go to the real-machine checklist.
- 0003's "the GUI does not write back" is superseded. The decision to adopt ruamel itself stands.
- Wayfire remains unverified while the area of keyboard grab grows. Check it in the real-machine
  checklist items.
- Candidates for future work: reordering of parent-sheet-derived hints, contention with Tab's
  focus movement, persisting the filter.
- **Fix (2026-09-23): `↑` `↓` selection movement is handled ourselves, not by GTK's default.** The
  original spec was "use GTK's default", but on a layer surface holding keyboard EXCLUSIVE, focus
  given to the list by the window does not stick — `grab_focus()` returns true, yet AT-SPI reports
  no row as focused, and the first arrow-key press just "enters the list" and is consumed
  (measured on labwc 0.20.2). As a result, **without a mouse, `f` / `J` / `K` / `Enter` / `d` `d`
  never reach rows past the first** — not workable for an overlay that is opened via a hotkey. It
  is now routed through the same CAPTURE path as the other single-key presses, and the
  destination is decided by `editmode.next_selection()` (no wraparound at the ends — returning to
  the top of a short list would be indistinguishable from "nothing happened"). Text fields do not
  receive it, since there it means cursor movement. Found while scripting the introduction video
  (B-7). Verified by `tests/test_gui_headless.py`'s `EditModeKeyboardTest` — against a real
  compositor, send `↓` and check both that the selection moved and that the next `f` hit **that**
  row.

## 0015 — Colors matching labwc are shipped as `examples/style.css`, not the default CSS

- **Date**: 2026-09-18
- **Status**: accepted
- **Context**: The default CSS (`ui/style.py`'s `DEFAULT_CSS`) is Catppuccin Mocha-ish (purplish
  `#1e1e2e`, 10px rounded corners), which stood out against the real machine's labwc (theme
  `Syscrash`, `cornerRadius` 0, and a `themerc-override` that makes the OSD black-based, matching
  waybar). The overlay plays the same role as the compositor's OSD, so we want it to match. On the
  other hand, rewriting the default CSS would pin the app's "look with no configuration" to a
  single machine's theme. There are two CSS layers, and `style.css` is loaded at `PRIORITY_USER`,
  which beats the default.
- **Decision**: Keep the default CSS neutral, unchanged. Ship the labwc colors as
  `examples/style.css` in the repository; the real deployment copies it to
  `~/.config/wayhint/style.css`. Colors are sourced from Syscrash's themerc and labwc's OSD colors,
  with the mapping left in comments inside the CSS (panel = `osd.bg.color`, header = a vertical
  gradient of `window.active.label.bg`, selected row = `menu.items.active`, button =
  `window.active.button.*`, accent = `#9fbfc1`). For warning/critical, which the theme has no
  matching color for, we use the desktop's own `#ffcc00` / `#f53c3c`.
- **Alternatives**:
  - Rewrite the default CSS (the first implementation): fits labwc with no config file, but pins
    the repository's default to one theme. Rejected per the user's judgment.
  - Use GTK theme colors (`@theme_bg_color`, etc.): the real machine's GTK theme is light Adwaita,
    too bright for a layer-shell overlay and does not match labwc's OSD either.
  - Read themerc at runtime and derive colors: Openbox gradients and GTK CSS do not map
    one-to-one, and a fallback would still be needed for environments without a theme. The gain is
    only staying in sync, which is not worth it for V1.
- **Consequences**: The real deployment lives outside the repository, so fixing
  `examples/style.css` does not automatically change `~/.config/wayhint/style.css` (it must be
  copied again). `style.css` is read only once, at daemon startup, so a change requires a restart.
  Since the default CSS remains underneath, the overriding side must explicitly restore
  properties that "come on by default", such as `opacity` (example: `.wayhint-context`'s
  `opacity: 1`). `cp -r examples/. ~/.config/wayhint/` also brings in style.css, so remove it if
  you want to keep the default colors. Color verification cannot be automated; all
  `./scripts/check` verifies is that the default CSS parses.

## 0016 — Remove the toolbar's "refresh" button (IPC/CLI `refresh` stays)

- **Date**: 2026-09-18
- **Status**: accepted
- **Amends**: 0012 ("update it if you want it refreshed"), 0013 (hotkey swaps)
- **Context**: `refresh` means "if shown, redo `show()`" — i.e. re-resolve context, not re-read
  YAML (that is the file monitor's automatic reload). It only matters in the case "the overlay
  was left open while moving to a different window", and 0013 had already made pressing the
  hotkey again achieve the same thing. Among seven toolbar buttons, it had become one whose
  purpose was hard to explain.
- **Decision**: Remove "refresh" from the toolbar and remove `HintWindow`'s `on_refresh` too. Keep
  the IPC `refresh` and the CLI `wayhint refresh` (for mouse-only situations and scripts).
- **Alternatives**:
  - Keep it and explain via tooltip: does not change the fact that the reason to press it
    overlaps with the hotkey.
  - Remove `refresh` entirely: removes any way to re-resolve context from the CLI, which is
    useful when you want to check without closing the overlay (including in real-machine
    testing).
- **Consequences**: There is no longer a mouse-only way to re-resolve context from the overlay
  itself (use a terminal's `wayhint refresh`, or the hotkey). The README's toolbar table and
  PRODUCT.md §11's description of "re-resolution" were rewritten to point at the hotkey/CLI. The
  i18n `Refresh` string was removed from both catalogs.


## 0017 — Consolidate the external-editor entry point into one button for curating the whole sheet

- **Date**: 2026-09-18
- **Status**: accepted
- **Amends**: 0014 (division of roles between edit mode and the external editor)
- **Context**: With 0014, per-hint add/fix/delete/reorder became possible inside the overlay, and
  the motivation to open an external editor shifted from "fix one entry" to "review the whole
  sheet". Even so, the toolbar still had both "Edit hint" and "Edit sheet". They open the same
  file — the only difference is whether it jumps to the relevant line (since 0014, "Edit sheet"
  also opens the selected hint's sheet).
- **Decision**: Merge the two into a single **"Edit in editor"**. If a hint is selected, open its
  file at that line; if nothing is selected, open the current sheet from the top.
  `editor.edit_target` already implements "the hint's location wins over the sheet's", so passing
  both is enough.
- **Alternatives**:
  - Keep only "Edit sheet": line-jump matters more the longer a sheet gets. No reason to drop it.
  - Keep only "Edit hint": becomes an unpressable button when nothing is selected (indeed, its
    sensitivity was already toggled based on selection).
- **Consequences**: The toolbar now has 5 buttons: search / copy / edit in editor / edit / close.
  There is no longer a way to choose separately between "open only the selected hint" and "always
  open the sheet from the top". The i18n strings `Edit hint` / `Edit sheet` were replaced by
  `Edit in editor`, and the logic toggling the editor button's sensitivity based on selection was
  removed.


## 0018 — Manual resize via corner grips; size is written back to config.yaml

- **Date**: 2026-09-18
- **Status**: accepted
- **Context**: Width/height could only be changed via `config.yaml`'s `overlay.width` / `height`,
  requiring repeated "edit → save → reopen" cycles to find the right size. A layer surface has
  neither a compositor-side frame nor interactive resize, so grabbing a handle has to be drawn by
  the app itself. Size needs to be persisted for "it always opens at the same size" (the
  top-priority principle of stable location).
- **Decision**: Overlay a grip on the side opposite the anchor with `Gtk.Overlay`, grabbed and
  dragged via `Gtk.GestureDrag`. The corner (16px) resizes both dimensions at once; two 6px bands
  on the free edges change width only or height only. At drag end, the daemon writes
  `overlay.width` / `height` in `config.yaml` back **in px**. The write uses the same atomic write
  + pre-validation as the sheet (`write_config`), and being ruamel round-trip, hand-written
  comments are preserved. The file monitor reloads it, so the size stays the same on the next
  show and after a restart. It applies globally (not per sheet).
- **Alternatives**:
  - Keep size in a separate state file (`~/.local/state/wayhint/`): separates config from runtime
    state, but hand-editing config.yaml would be overridden by state, making it unclear which one
    is in effect.
  - Keep it in memory only: reverts on daemon restart. Fails "always the same size".
  - Save per sheet: size would change every time the sheet is switched, contrary to stable
    location.
  - Leave resizing to the compositor: not available for layer surfaces. Making it a regular window
    would break "always the same place" (a premise going back before 0011).
- **Consequences**: Even if you had written `60%` by hand, grabbing and releasing once turns it
  into px (revert to % by hand). GUI operation now writes to `config.yaml`. When config.yaml is
  broken, it shows `⚠` instead of writing. The grip is an overlay child so it steals hit-testing:
  the 16px corner, and 6px-wide bands on the two free edges. The toolbar's bottom padding was
  widened from 6px to 12px so the band does not overlap the buttons. When a sheet has its own
  `display` override, the write-back applies to the global side, so the sheet's own setting keeps
  winning (manual resize appears not to take effect for that sheet).


## 0019 — Operate without losing a hint's ownership or a workspace's edit state

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014 D2 / D3 / D4 / D9
- **Context**: Implementation audit F1/F2 found a mis-update that picks a target by hint id alone
  across all sheets, form contamination on workspace return, and draft discard via the search
  button.
- **Decision**: Hint operations, forms, and selection restoration all keep the pair of owning file
  and id. Mode changes and cancellation go through the daemon, and restoration also applies
  whether a form was present. The search button is disabled while editing; to search, end editing
  first. `edit-mode` on a hidden edit screen does not re-fetch context; it redisplays the draft.
- **Consequences**: The YAML schema is unchanged. Simultaneous use of search and edit is not
  added; D8's unimplemented "J/K while filtering" remains a separate open item. The daemon's GUI
  import is deferred to startup, and headless save/state-transition tests using a fake window were
  added.


## 0020 — Policy on remaining audit items (D8 retraction, duplicate sheet ids, scroll, adapter
failure distinction, and others)

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014 D8 (retracted), consistency of 0008 / 0012's description
- **Context**: Implementation audit F3–F11 and things around it left points where spec and
  implementation disagreed, and points where the spec itself was undecided. This gathers the
  results after separating what implementation could decide (bugs) from what needed a usage
  judgment, and putting the latter to the user. As a premise, this project is Wayland-only and its
  primary environment is **labwc**. Anything Wayfire-specific is treated as one adapter
  implementation among others, and real-machine verification and the F7/F10 decisions treat labwc
  as authoritative.
- **Decision**:
  1. **`J` `K` while searching/filtering (0014 D8) will not be implemented.** That one sentence of
     D8 is retracted. Since the usual pattern is still changing the filter contents even after it
     is narrowed down, we do not adopt a spec that takes focus away from the input field.
  2. **Scroll after reload does not restore a pixel position.** It only moves enough for the
     restored selected hint to be visible; if the selection cannot be restored, show the top. The
     scrollbar is always shown (do not use the overlay scrollbar).
  3. **A sheet's `id` must match its file's stem**; a file that does not match is not loaded as a
     hint source (turned into an Issue, not shown in the list). This is so that as renames or
     backup copies accumulate files claiming someone else's id, which one wins never depends on
     the filename. At audit time, every sheet already in generated output, fixtures, examples, and
     the real deployment already matched (`create_sheet` creates `<slug>.yaml`, so the generating
     side always matches). Even so, pairs with the same stem, like `x.yaml` and `x.yml`, remain
     possible, so **on duplication, only the one file read first, in filename ascending order, is
     used**; the rest are excluded from the store and turned into an Issue shown in the GUI
     (naming both files in the message — ambiguity is never left to chance, design doc §59).
  4. **A debounce-pending reload is applied before an edit operation.** Favorite toggle flips the
     file's value. Reproduced via a headless test with rapid presses within 200ms ("the second
     press does not take effect / reordering reverts") and then fixed.
  5. **`xdg_output` is not bound for fractional scaling.** Since `wl_output.scale` is an integer,
     logical size stays an approximation, recorded in DESIGN as a known limitation. If real use of
     fractional scaling comes up, using `xdg_output_manager` (falling back to the current
     computation if absent) is filed as a separate item. Axis swap via transform and the `mode`
     CURRENT flag are implemented.
  6. **Abnormal termination of the editor after launch is not monitored.** Launch failure is still
     shown in the GUI as before.
  7. **The Wayfire adapter distinguishes an IPC failure from the absence of a window.** A failure
     of a call essential to the snapshot is a `ContextError` (the overlay does not crash, shows an
     error); `None` is treated as "no window is focused" and falls back to desktop context (design
     doc §63).
  8. **Contradictions in the documents are fixed in the documents.** DESIGN's "IPC message format
     is undecided" is replaced with the content of 0008. AGENTS's "only the editor runs
     subprocess" is amended to note the Herdr adapter as an exception (fixed argv, `shell=False`,
     with timeout, never passing YAML-derived strings as arguments).
  9. **STATUS** is not rewritten by guesswork about real-machine verification or residency status.
- **Alternatives**: Implement D8 (moving focus to the list once a filter is settled — rejected
  since changing the narrowing is the main usage); read both duplicate sheets (unclear which one
  took effect); save scroll position in pixels (weak value, since row order can change after
  reload); bind `xdg_output` now (not yet needed on the real machine); ignore Wayfire failures as
  before (cannot tell whether context is empty or broken).
- **Consequences**: The YAML schema is unchanged. A sheet whose id disagrees with its filename,
  and the second and later of duplicate ids, are "not read", so such configurations change what is
  displayed (the Issue shows the reason and the rename target). When renaming a file by hand, `id`
  must be changed along with it. Wayfire IPC failures will now surface as errors going forward
  (previously a silently empty context).

## 0021 — Saving a form ends edit mode (single-key operations stay in it)

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014 (overrides DESIGN "edit mode" §1's "stays in `edit` after saving". 0014 itself
  is left as is; this entry references it)
- **Context**: `edit` is an EXCLUSIVE grab, so time spent staying in it is time spent getting in
  the way of the underlying app (design doc §81). The typical flow is "forgot an operation →
  looked it up → wrote one entry → went back to work", and the need is met the moment the save
  happens. On the other hand, favorite / reorder / delete / undo are "tidy up several entries at
  once" operations, and `u` can only be pressed while in `edit`.
- **Decision**: On a successful save of a form (quick add or edit), return to `normal`, set
  keyboard_mode to NONE, and return focus to the previous view. The order is "write succeeds →
  mode change → `_sync_keyboard_mode()` → focus restored", the same path as exiting search. When
  the write fails, validation fails, or the form is discarded with `Esc`, the mode does not
  change. Single-key operations (`f` / `J` `K` / `d` `d` / `u`) still stay in `edit` as before.
  Quick add that creates a new sheet (§7) also returns to `normal`.
- **Alternatives**: stay in `edit` for every operation (current behaviour; even writing a single
  entry requires pressing Esc, and forgetting leaves the grab held); exit `edit` for every
  operation (`u` could no longer be pressed, so bulk tidy-up operations would not work); make
  "save and stay" selectable via a separate key (`Ctrl+Enter`) or config (start with the simple
  form and decide once the need arises).
- **Consequences**: to keep adding, press `wayhint edit-mode` → `a` again. The self-write reload
  after 200ms runs against the `normal` list, but `_after_reload`'s selection restoration still
  works as is. Change the help text at the bottom of the form to "Enter to save and exit" (en/ja).

## 0022 — "Edit in editor" hides the overlay in every mode

- **Date**: 2026-09-19
- **Status**: superseded by 0023
- **Context**: the F9 fix made the overlay hide only in `edit` / `search` (because with the
  EXCLUSIVE grab still held, the editor cannot receive input), but in `normal` it stayed shown.
  In real use, the same button behaving differently depending on the current mode is confusing.
  Opening the editor is a "go look at this file" operation, and there is no reason the overlay
  needs to remain on top of the editor.
- **Decision**: on successful launch, hide the overlay in every mode. Mode and draft are kept and
  restored on the next hotkey. On restore, if it is the same context, show what had been open
  again as is; if pressed from a different window, replace as in 0013 (extending "if a hotkey
  arrives while hidden, open rather than close" to every mode). If launch fails, do not hide;
  show an error instead.
- **Alternatives**: keep it shown only in `normal` (current behaviour; the button's meaning
  changes with mode); do not hide, only drop the grab (input reaches the editor in `edit` /
  `search`, but the overlay stays on top of the editor).
- **Consequences**: after closing the editor, one hotkey press is needed to see hints again.
  **Detecting when the editor closes and returning automatically cannot be implemented with the
  current editor setting (`gvim --remote-silent`)**: if gvim is already running, the launched
  process exits immediately; if not, that process becomes gvim itself, so a child process's exit
  does not mean "the editor was closed". If automatic return is needed, a different signal would
  have to be chosen (e.g. a file-monitor event on save), and this is left unresolved.

## 0023 — "Edit in editor" does not hide the overlay either (only drops the grab)

- **Date**: 2026-09-19
- **Status**: accepted
- **Supersedes**: 0022 (and the "hide only in `edit` / `search`" behaviour added in F9)
- **Context**: using this on real hardware, opening the external editor is almost always curating
  a whole sheet, and you want to check the rewritten result right away. If the overlay is hidden,
  the round trip becomes save → hotkey → check → back to the editor, more often. The file monitor
  detects the save and reloads, so as long as the overlay is showing, the result appears on
  screen immediately.
- **Decision**: "Edit in editor" does not hide the overlay. When in `search` / `edit`, return to
  `normal` via the same path as Escape (set keyboard_mode to NONE and return focus to the
  previous view), so the editor can receive input. In `normal`, do nothing. Any open draft stays
  in the view and is reopened on the next `edit-mode`. When the sheet is updated (the file
  monitor picks up the editor's save), update the shown overlay in place — this uses the existing
  reload path as is; no extra mechanism is needed.
- **Alternatives**: hide in every mode (0022; the result is invisible while curating); hide and
  detect the editor's exit to return (cannot be built with `gvim --remote-silent` because a child
  process's exit does not mean "the editor was closed"; see 0022's Consequences); keep it shown
  while holding the grab (the editor cannot receive input; F9).
- **Consequences**: every time the editor saves, the overlay's list updates (after a 200ms
  debounce). The overlay stays on top of the editor, so if the editor window overlaps it, part of
  it is hidden; use the hotkey to dismiss it if that matters. Pressing it from `search` / `edit`
  ends edit mode (the draft is kept).

## 0024 — hint sheets live in per-language directories; only the one matching the UI language is read

- **Date**: 2026-09-19
- **Status**: accepted
- **Context**: the UI switches between en / ja with `appearance.language` (`auto` follows locale),
  but hints have only a single `hints/`, so placing a Japanese sheet there shows Japanese even
  when the UI is in English. In fact the repository's `examples/hints/` is English while the real
  deployment is Japanese, and sheets with the same id were duplicated across languages. There are
  also cases (like the intro video) where you want to switch between the en and ja versions to
  show both.
- **Decision**: make `hints/<lang>/` one directory per language, and **read only the directory for
  the display language**. The resolution order is `hints/<lang>/` → `hints/en/` →
  `hints/*.yaml` (flat). The language comes from the same `resolve_language()` as the UI (config →
  locale → en if unknown), so UI and hint language never drift apart. All reads and writes go to
  this directory (creating a new sheet, `wayhint format`'s default target, the file monitor).
  Changing the language setting re-reads on config reload, and re-attaches the watch too.
  `hints/` itself is also watched, so a language directory created later is noticed.
- **Alternatives**: mix both languages under `hints/*.yaml` and dispatch by a sheet's `lang:`
  (clashes with the filename = id rule, 0020); a base plus an overlay layer of `hints/<lang>/`
  (can auto-fill sheets with no translation, but mixes two languages on one screen); per-hint
  `title: {ja:…, en:…}` (bloats schema and the edit form). Dropping the flat layout is not taken,
  since it would break the existing deployment and single-language use.
- **Consequences**: the same sheet has to be written once per language (there is no mechanism to
  keep translations in sync; editing only one is not detected as drift). `examples/hints/` was
  split into `en/` and `ja/`. The real deployment has already been moved to
  `~/.config/wayhint/hints/ja/`. The `id` = filename rule (0020) holds per directory, so
  `ja/claude.yaml` and `en/claude.yaml` do not clash.

## 0025 — quick add writes to the sheet of the currently selected hint

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014 (DESIGN "edit mode" §3's "add target: active sheet")
- **Context**: with `nested.parent_tags` set, the list mixes hints from the active sheet with
  hints from the parent sheet. In that state, placing the cursor on a parent-sheet hint and
  pressing `a` added to a different sheet (the active sheet) than the one being looked at. Edit,
  delete, favorite, and reorder already act on "the file the selected hint belongs to" (0019), so
  add alone was operating on a different rule.
- **Decision**: quick add's target is **the sheet the selected hint belongs to**. If nothing is
  selected, or its file has disappeared, fall back to the active sheet, and failing that, create a
  new sheet on save as before (0014 D6). Since where an entry ends up depends on the selection,
  show the target sheet's name in the form's heading (also updates when `Ctrl+P` switches to the
  parent sheet).
- **Alternatives**: keep it on the active sheet (inconsistent with the other edit operations'
  rule); show a UI to choose the target (too much choice for just adding one entry).
- **Consequences**: pressing `a` while looking at a parent-sheet hint adds to the parent sheet. To
  add to the active sheet, select one of its hints first, or clear the list selection. The heading
  shows which it is.

## 0026 — the single way to mix in another sheet's hints is the sheet-side `include`

- **Date**: 2026-09-19
- **Status**: accepted
- **Context**: the display was fixed to two layers, the active sheet and the nested parent sheet,
  with no way to mix in an unrelated sheet. Three requests surfaced — (A) common hints such as WM
  operations or IME, shown on every sheet, (B) a specific combination (show git too when looking
  at claude), (C) a shared role (the common part of terminal-family sheets). The plumbing for a
  mixed-in hint already exists (identified by (file, id), 0019; edited by owning file, 0014 D9;
  `J`/`K` never crosses files, D8; display order, D7), so all that was missing was a way to
  specify what to mix in.
- **Decision**: add `include: [sheet-id, ...]` to a sheet, and this one field covers all three.
  The top-level `include: []` in config.yaml is the default for a sheet that omits `include`
  (same relationship as `inherit.parent_tags` and `nested.parent_tags`: **replacement, not
  addition**). Hints from an included sheet are not filtered by tag, all are taken in; keep the
  volume down by making shared sheets small. Multi-level include is not followed. Duplicates are
  dropped by (file, id). A sheet with no `match` is allowed; it never becomes active and only
  appears via `include`. An unresolvable id or a self-reference is a **warning**
  (`Issue.severity`); only that id is ignored and the sheet is still shown. Display looks the same
  as the current parent hints, unmarked. The IPC `context` response gains the resolved `include`.
  The detail pane shows the owning filename (a marker for which file gets rewritten).
- **Alternatives**: writing `applies_to` on the providing side (hard to trace back from the
  screen); a tag-based `always_tags` (hard to see at a glance which hints appear everywhere, and
  gives two paths for mixing-in); a per-element tag filter on include
  (`{sheet: x, tags: [...]}`, too heavy a notation; splitting the shared sheet is enough);
  multi-level include (needs cycle detection with no use case yet); a dedicated header for
  include-derived hints (no reason to treat them differently from parent hints).
- **Consequences**: the list tends to grow longer (no cap on count is introduced). Edit-mode rules
  are unchanged, so edit / delete / favorite of an include-derived hint is written to its owning
  file, `J`/`K` never cross files, and quick add's target stays the selected hint's sheet (0025).
  Now that `Issue` has severity, `wayhint validate` exits 1 only on error.

## 0027 — take a terminal's foreground process from `/proc`, and decouple nested resolution from whether a desktop sheet exists

- **Date**: 2026-09-19
- **Status**: accepted
- **Context**: only Herdr could answer nested context; a plain terminal emulator like foot could
  not tell more than "a terminal window". A terminal does not report what it is running, but
  `/proc` has the answer — among a terminal's descendants, the one in the tty's foreground process
  group (`pgrp == tpgid`) is exactly the command the user is touching right now. Two premises
  surfaced at the same time. (1) `ContextResolver` only called the nested provider **when a
  desktop sheet existed**. `herdr.yaml` always exists for Herdr, so this constraint had never bit
  before, but almost nobody writes a sheet for a terminal, so ProcAdapter would never run.
  (2) `match_rule_for_context` used `parent_context is None` as the test for "decided by app_id",
  so quick-adding on top of foot generated a sheet matching foot's own app_id.
- **Decision**: add `ProcAdapter` to `context/proc.py` (keeping the current
  `NestedContextProvider` interface; `applies_to` is the constant
  `TERMINAL_APP_IDS = {"foot", "footclient"}`; `foreground_process` reads `/proc` directly via
  pathlib, no subprocess). Nested resolution is decided **only by app_id** — drop the "only when a
  desktop sheet exists" condition from `ContextResolver`, and only set `parent_context` when a
  desktop sheet exists. Change what `match_rule_for_context` and `create_sheet` use from
  `parent_context` to `foreground_process`. The one place that decides registration order is
  `daemon.nested_providers()`, with the two groups (terminal introspection / nested resolver)
  commented there. Add `chain` (the classes of providers queried, in order) to IPC `context`.
  Only this one module reads `/proc` (add this to AGENTS.md's isolation rule).
- **Alternatives**: **rework `NestedContextProvider` into `supports(ctx)` / `resolve(ctx)` and make
  the resolver a depth-aware loop** — could cover multi-level chains like
  `foot → tmux → herdr → claude` in the future, but the two providers needed now both just "look
  at app_id and return the foreground process", which fits the current contract, and there is no
  multi-level need yet. Rework the interface once multi-level is actually needed (until then, one
  level fixed, `chain` has 0 or 1 element). **A dedicated adapter per terminal**
  (WezTerm / Kitty / foot control protocols) — decide whether `/proc` suffices after trying it on
  real hardware. **Reading title via ShellIntegration** — keep title for a future tie-break use
  only. **Tmux / Ssh resolver** — deferred for the same multi-level-interface reason as above.
  **Make `HerdrContextProvider.applies_to` also true by foreground process name** — this is a
  multi-level-premised change, not taken this time. A 2026-09-20 real-hardware check found a case
  where this matters: starting `herdr` from plain kitty / Ghostty means the app_id does not
  contain `herdr`, so it does not go through the Herdr path, and the `/proc` path can only say
  "a process named `herdr` is running". For now, work around it by **putting `herdr` in the
  window's app_id** (`docs/TERMINALS.md`'s Herdr section), with just an INFO log line from
  `proc.SELF_REPORTING` so it is noticeable. Even with multi-level added, Herdr's `focused: true`
  is one per whole session, so there is no guarantee it is correct with two windows open
  (0028's `[to decide]`). Decide after measuring that. **Turning `TERMINAL_APP_IDS` into config** —
  the condition is a program property ("a terminal emulator that runs a command as a
  descendant"), not a preference. **Narrowing down the window in foot's server mode (one process,
  many windows)** — `/proc` alone cannot map a window to a process. If two or more processes share
  a name, return **no match** (`None`). A wrong sheet is worse than no sheet showing. If window
  narrowing is needed, reconsider it together with a terminal-specific adapter. **Keeping a foot
  sheet in examples as a guard** — whether context resolution changes depending on whether a sheet
  has been written contradicts the principle that context is resolved correctly regardless.
- **Decision (addendum 2026-09-20, following real-hardware checks)**: the original "no match unless
  exactly one same-named process" never fired in practice. On the author's machine, foot windows number
  3–4 at all times, and Herdr's window is also foot (with `--app-id=foot-herdr`), so `comm` is the
  same `foot`. "A terminal has multiple windows as the norm" was the correct premise. Investigation
  established that **labwc has no way to know the pid of the focused toplevel** — neither
  `zwlr_foreign_toplevel_manager_v1` (v3) nor `ext_foreign_toplevel_list_v1` carries a pid
  (confirmed with `wayland-info` on real hardware), labwc 0.20.2 has no IPC (confirmed via
  `--help` / man), and foot has no query interface either. So instead, **the window declares
  itself by convention**: the launcher starts it as `exec foot --app-id "foot.p$$"`, and the
  adapter reads the pid back out of the app_id the compositor returns with `\.p(\d+)$`
  (`matcher.APP_ID_PID_RE` / `strip_pid_suffix`; pure, so it can also be used from `yaml_store`).
  The pid read back is cross-checked against `comm` before use — once a window closes its app_id
  belongs to nobody, and the number gets reused by another process. The match rule is unified into
  one ("the base itself, or the base's last dot-separated component", `_is_process_of`), and the
  same function is used for "is there exactly one process for this terminal" when the app_id has
  no suffix (`com.mitchellh.ghostty`'s `comm` is `ghostty`; `comm` is truncated to 15 characters,
  so a reverse-DNS form never matches in full anyway). Add `app_id: str | None = None` to
  `NestedContextProvider.foreground_process` (default value, so existing callers are unchanged).
  `ResolvedContext.desktop_app` keeps the suffixed form (a different window means a different
  context), and **sheet generation and overlay display use the base** — a `^foot\.p12345$` rule
  would only ever match that one window, and there is no point exposing the launcher's internal
  bookkeeping in a context label. Process `name` prefers **the basename of `argv[0]`** over `exe`
  (dropping a login shell's leading `-`; if argv is empty, fall back to `exe` → `comm`). Via
  Debian's alternatives, `exe` becomes `/usr/bin/vim.gtk3`, which would make it impossible to write
  a sheet for the `vi` the user actually typed. Cases that want to match the real binary have
  `cmdline_regex`.
- **Alternatives (addendum)**: **telling window contents apart by title** — `vim` / `neovim` emit
  a title via OSC but `top` / `htop` / `less` / `more` do not. It fails exactly where it matters
  most, so not taken. Keep title for a future tie-break use only. **Having the shell's preexec /
  PROMPT_COMMAND announce the running command via title** — fills the gap above, but a TUI that
  does emit a title (`vim` etc.) overwrites it right after startup, so that case is lost instead.
  It would also need shell-side configuration. Not taken. **Restricting supported terminals to
  ones that can answer for themselves** (kitty's `kitty @ ls`, WezTerm's
  `wezterm cli list-clients` → `tty_name`) — confirmed both work on real hardware. kitty directly
  returns `foreground_processes` per pid, so it does not even need `/proc`, but it requires adding
  three lines (`allow_remote_control` / `listen_on` / `single_instance`) to kitty.conf (a second
  kitty process cannot bind the same socket and is invisible to `@ ls`). Ghostty 1.3.1 has no query
  interface (the full man page mentions IPC only in one line about `new-window`; the D-Bus service
  is launch-only too). The app_id convention covers every terminal with one mechanism, so this is
  the one taken this time — kitty too can vary app_id per window with `--class` (one process per
  window by default), so it follows the convention, and neither `kitty @ ls` nor
  `allow_remote_control` / `listen_on` nor a config item pointing at them is needed anymore.
  **Including WezTerm this time** — WezTerm cannot vary app_id per window, so it does not follow
  the convention. Next time this is touched, use the path
  `wezterm cli list-clients` → pane's `tty_name` → `/proc` (confirmed down to
  `/dev/pts/30 → vim` on real hardware, no terminal-side config needed). Lua's
  `pane:get_foreground_process_name()` can only be called from inside config Lua, and embedding it
  in the title needs terminal-side config, so not taken.
- **Decision (addendum 2026-09-20, following review feedback)**: an independent review raised three
  points. (1) **misanswered when one terminal has multiple ptys underneath**. A foreground process
  exists per pty, so even knowing the terminal's PID does not tell `/proc` which of a tab / split /
  `tmux` / `ssh -t` is on screen. Taking "deepest, highest PID" from among descendants ends up
  picking the inner pty's `top` over the outer pty's `vi` (reproduced with a fake `/proc`). **Return
  no match when multiple ttys are found**. Also exclude the root process itself from candidates —
  a terminal launched in the foreground from another terminal only sits in *that* terminal's
  foreground process group, unrelated to what it itself is running.
  (2) **a suffixed app_id did not match the terminal's own sheet**.
  `match_app([^foot$], "foot.p12345")` was `None` (reproduced). Sheet generation and UI display
  used the base, but matching was passed the raw app_id. Make `app_specificity` treat **both** the
  app_id and the base as candidates — not normalizing to base alone, so as not to break a rule that
  happened to be written for an app_id that ends in `.p<number>`. Adding a candidate still counts
  one pattern as one, so specificity ordering does not change.
  (3) **the verification procedure itself changed the target being observed**. Running
  `wayhint context` inside a terminal makes that `wayhint` itself the terminal's foreground
  process. `vi memo &` runs in the background too, so it is not in the foreground process group
  either. The procedure was replaced with watching the overlay's context label, and running from a
  compositor keybind and writing to a file (`docs/TERMINALS.md`).
- **[To decide] (addendum)**: narrowing down by title / cwd matching when a suffixless app_id has
  several same-named processes. Not added this time; left as no-match.
- **Not doing (addendum)**: **narrowing a pty within a window that has tabs / splits**. Would need
  an adapter that asks the terminal itself for focus (kitty's `kitten @ ls`, WezTerm's
  `wezterm cli list-clients`). `/proc` alone cannot decide this, so it is not guessed. Neither a
  multi-level resolver nor a new config item nor a new dependency is added.
- **Consequences**: even without writing a terminal sheet, the sheet of the command inside it now
  gets picked. With no parent, no parent-tag mixing happens; only that sheet's own hints show.
  **A terminal window started without going through the wrapper only resolves when that terminal
  has exactly one process** (README "multiple terminal windows"). `ProcAdapter` scans `/proc` once
  per show / refresh (no polling). In environments where `/proc` is not visible (containers,
  hidepid), it is always no-match, unchanged from before. The IPC `context` response grows a bit
  with `chain` (well within the 4096-byte limit). Once multi-level resolution is actually needed,
  `NestedContextProvider` will need reworking.

## 0028 — call Herdr with `HERDR_*` stripped from the environment, and resolve the focused pane

- **Date**: 2026-09-20
- **Status**: accepted
- **Context**: with tabs for claude / codex / vi / lv / top laid out in a Herdr workspace, **only
  the hints for the pane that started wayhintd showed, no matter which tab was switched to**.
  Investigation on real hardware showed that `herdr pane current` returns that pane when the
  `HERDR_PANE_ID` environment variable is set, and only returns the focused pane when it is not
  (`--current` makes no difference). Starting wayhintd from inside a Herdr pane inherits
  `HERDR_PANE_ID`, so the adapter treats that pane as "current" for the whole session. The real
  wayhintd's environment did indeed have `HERDR_PANE_ID=wH:p1`. `pane process-info --pane <id>`
  returns the right process given the right id, so only pane identification was broken.
- **Decision**: strip variables starting with `HERDR_` from the environment the adapter uses to
  call herdr (`_herdr_env`, a pure function). This makes `pane current` return the actual focused
  pane. **As a safety net**, only when `pane current` returns `focused: false`, call `pane list`,
  and take the pane with `focused: true` if there is exactly one (with 0 or 2+, treat the pane as
  unknown and fall back as before to Herdr-sheet-only). `pane list` is not made the everyday path —
  `pane current` costs one call and answers correctly once the environment is fixed. Since call
  count goes from 2 to at most 3, the time budget is spent against a **deadline decided at the
  start of the lookup**, not per call. Each call gets `min(CALL_TIMEOUT, remaining time)`, and is
  not made if nothing remains. `LOOKUP_BUDGET`'s value is unchanged, so its relationship to
  `ipc.CLIENT_TIMEOUT` is unchanged too. The change is confined to `context/herdr.py`.
- **Alternatives**: **unset all `HERDR_*` at daemon startup** — rewriting the whole daemon's
  environment has wide-reaching effects; an adapter's concerns should stay in the adapter.
  **Drop `pane current` and always find the focused pane from `pane list`** — equally
  environment-independent, but forces returning every pane every time (26 panes on real hardware).
  `pane current` answers correctly in one call as long as the environment is fixed, so it stays the
  main path, with `pane list` only as a safety net. **Run wayhintd from outside Herdr as a matter
  of practice** — a workaround, not a fix. The design flaw of context resolution depending on
  where the daemon was started is itself wrong. **Choose a sheet by `pane list`'s `agent` field
  (`claude` / `codex`)** — `vi` / `lv` / `top` do not appear in `agent`, so `process-info` would
  still be needed. No benefit to having two paths.
- **Consequences**: no matter where wayhintd is started, and no matter which Herdr tab is switched
  to, that tab's foreground-process sheet shows. Confirmed on real hardware (resolved the focused
  `wH:p1`'s `claude` while `HERDR_PANE_ID=w9:p3` was inherited). Herdr lookups can now be up to 3
  subprocesses, but total time stays within the same cap as before. `Runner`'s signature gained a
  timeout (`Callable[[Sequence[str], float], str]`).
- **[To decide] → resolved (2026-09-20)**: "when two or more Herdr windows are open, does the
  focused pane belong to the window that is active on the Wayland side" turned out to be **a
  question that does not apply**. Herdr's client windows mirror the same session; opening a second
  one on a different tab makes the first one follow that tab too. A state where each window shows
  a different tab cannot exist, so the focused pane Herdr reports is correct no matter which window
  it's viewed from. The narrow remaining gap is **running several named sessions at once**, each
  with its own socket (`herdr session list`). Since the adapter strips `HERDR_*` including
  `HERDR_SOCKET_PATH`, it always asks the default session. Focusing a window of a non-default
  session still returns the default session's answer. Not addressed for now, since only one
  session is used in practice. Also, on real hardware **the safety-net path (`pane list`) never
  fired even once** (the daemon log never shows `answered an unfocused pane`), so this branch is
  close to dead code. Removing it is an option next time it is touched.

## 0029 — configure terminals with a script, and never rewrite launcher config the user maintains

- **Date**: 2026-09-20
- **Status**: accepted
- **Context**: enabling the `.p<pid>` convention (0027) requires making a wrapper and pointing
  **every path that launches a terminal** at it, and the `docs/TERMINALS.md` procedure is long.
  Since it's a one-time task, documentation alone seemed like it might suffice, but the manual work
  would repeat both (a) when someone else uses this repository and (b) when setting it up again on
  another machine. Meanwhile, the target files split into two kinds — ones wayhint generates
  (wrappers, `.desktop` overrides) and ones the user maintains by hand (bar config, compositor
  menu).
- **Decision**: add `scripts/setup-terminals`. In addition to files it generates (wrappers,
  `.desktop` overrides), **it also rewrites the relevant lines in bar and compositor config**.
  Reporting-only for the latter was considered at first — JSON with comments and XML carry
  provenance comments (real-hardware `waybar/config.jsonc` has lines like
  `// 2026-09-16: was U+F120 ...`), and mechanical rewriting would lose those. But that concern
  only applies when **reading the file back and re-writing it whole**; since detection already
  pins down "which lines, which range", **replacing only that range** needs no parsing or
  re-serialization, and comments and formatting are left untouched. A copy is taken as
  `<filename>.wayhint-backup-<timestamp>` before rewriting. Terminals can be selected via
  arguments, default is "every installed terminal". **Default is a dry run; writing only happens
  with `--apply`** (regardless of whether a terminal is specified) — what a script writing into the
  user's home does the first time should be readable before it runs. While work remains it returns
  exit 1, so a dry run doubles as a health check. Generated files carry a marker comment, and
  **files without the marker are never touched** (so it never clobbers a wrapper the user wrote
  themselves). Terminal detection only looks at "the first word of the value being executed as a
  command" — searching by name across whole lines hit comments and tooltip strings on real
  hardware, 14 false positives out of 19. A mismatch with `TERMINAL_APP_IDS` is checked at startup
  and aborts.
- **Alternatives**: **leave it as documentation** — even though one-time in principle, it repeats
  on distribution and on re-setup. **report launcher config only** (the original decision) —
  "someone else clones and runs one command" would not hold, and manual work across four file
  formats would remain. Scoped replacement plus a backup lowers the risk of breaking things.
  **build only a `--check`** — good for diagnosis but not enough for handing to someone else.
  **fold into `./scripts/check`** — `check` validates the repository; the state of the user's
  desktop is out of scope. Keep a separate entry point (stated in `AGENTS.md` too).
- **Consequences**: `scripts/` now has, for the first time, a script that writes outside the
  repository (into the user's home). Because of this every path is taken from environment
  variables, and `tests/test_setup_terminals.py` treats a temp directory as HOME to verify
  (including cases with existing files — latest and stale generated artifacts, hand-written ones,
  and launcher lines already pointing at the wrapper). Only the 8 files in `LAUNCHERS` are
  examined; a launch line embedded in a single shell command is out of scope. kitty's
  `single_instance` and Ghostty's `gtk-single-instance` are disabled by the wrapper via arguments,
  so users no longer need to touch those config files themselves.

## 0030 — automated GUI tests split into two layers: "in-process" and "headless compositor"

- **Date**: 2026-09-20
- **Status**: accepted
- **Context**: overlay display, placement, and widget state were only ever checked by the manual
  checklist (T1–T5, T13, T24–T26). Four approaches were tried in practice (environment:
  labwc 0.20.2 / wlroots 0.20.2 / GTK 4.22.4). a: in-process widgets, b: headless compositor plus
  screen capture, c: AT-SPI, d: input injection. sway / cage / wtype / ydotool were not on this
  machine, but **labwc itself can start with `WLR_BACKENDS=headless`**, so b and c worked with no
  extra installs. d was verified after installing `wtype`.
- **Decision**: **adopt a, b, and d, and c as the read-out method used inside b**. d only runs in
  environments that have `wtype` (skip just that one if absent). a (without mapping a surface)
  goes into `./scripts/check`. b/c/d are split into `./scripts/check-gui`, skipped unless
  `WAYHINT_GUI_TESTS=1` is set. **Full baseline-image comparison is not adopted**. On the same
  machine, capture reproduces exactly (AE=0 across frames, after hide/show, and across a re-created
  session), but it means nothing on a different machine with a different font and theme. Instead,
  measure position and width from the **bounding box of the diff** between a frame with the overlay
  shown and one without (font-independent), and read contents via **AT-SPI's accessible name**.
- **Alternatives**: **do everything with a** — a layer surface is a *request* to the compositor,
  so how anchor and margin were actually interpreted is invisible from in-process. Indeed
  `width: 25%` (320px) was shown at 356px, losing to the button row's required width, and this
  cannot be detected by a. **install sway / cage** — labwc already suffices, and measuring against
  the actual compositor in use is worth more. **baseline images** (above). **put everything into
  `./scripts/check`** — takes 8 seconds and requires a compositor binary plus grim / ImageMagick;
  keep the default validation at a few hundred ms with no dependencies. **input injection with
  ydotool** — needs `/dev/uinput` permission changes and a resident daemon. wtype uses the
  `zwp_virtual_keyboard_manager_v1` labwc exposes, so no permissions are needed.
- **Consequences**: `tests/headless.py` starts a process outside the repository. To avoid
  collateral incidents, the compositor is given its own `XDG_RUNTIME_DIR` / `XDG_CONFIG_HOME` /
  `HOME` / session bus (in an early attempt, the user's labwc autostart launched waybar and a
  second `wayhintd` inside the headless session). `XDG_RUNTIME_DIR` is created with a short name
  next to the real runtime dir, because of AF_UNIX's 108-byte limit. `./scripts/check` gains 5
  more skips (doubling as an announcement of the GUI tests' existence and entry point). Since
  measurement is diff-based, **anything else moving mixes in**: the probe window's cursor blink is
  stopped, and hotkey tests do one toggle round trip before measuring to let focus-driven redraws
  settle first. Also, "a diff exists" alone is weak — an unbound key reaches the window underneath
  and the terminal echoes it, which also shows as a diff, so **position and width** are checked
  too (confirmed by deliberately unbinding a keybind).

## 0031 — generate demo videos with scenario-driven frame-stepping on a headless compositor

- **Date**: 2026-09-21
- **Status**: accepted
- **Context**: manually screen-recording intro videos makes hint content, timing, window layout,
  and language drift every time, and every feature fix means re-recording. Reproducibility is
  thought of in three tiers — (1) frame-identical on the same machine, (2) matching content, order
  and length on a different machine (pixels may differ by font / theme), (3) length is decided by
  frame counts written in the scenario, not wall-clock time. 0030 already had the foundation of
  running labwc with `WLR_BACKENDS=headless`, capturing with grim, and reading with AT-SPI, and had
  already confirmed capture reproduces exactly (AE=0) on the same machine. Measurement environment:
  labwc 0.20.2 / wlroots 0.20.2 / GTK 4.22.4 / at-spi2-core 2.62.0 / foot 1.28.0 / grim 1.5.0 /
  ImageMagick 7.1.2 / wtype 0.4 / ffmpeg 9.0.2.
- **Decision**: `./scripts/demo --record` reads `demo/scenario.yaml` (the script) and plays it back
  and records it inside the same headless session as 0030. Implementation lives in `tools/demo/`
  (outside the product package). **Real-time capture is not used** — each step polls until its
  `wait_for` condition is satisfied (a toplevel appearing, overlay visibility, a label / button /
  row count read via AT-SPI), takes exactly **one frame** with grim once the screen has settled,
  and duplicates it `hold × fps` times to build the duration. ffmpeg only concatenates the frame
  list, so **length is decided by the file, and machine speed is irrelevant**. Buttons are pressed
  via AT-SPI's Action interface (role `button`, action `click`); keys are sent via wtype to the
  compositor's keybinds. The scenario is data: the executable actions are a fixed set with fixed
  argv, and only two substitutions exist, `{demo_bin}` and `{lang}` (`shell=True` is not used).
  Besides the video (mp4 / webm), also produce **a contact sheet and a still per step** — so
  content can be checked even by an agent / CI that cannot play video.
- **Alternatives**: **real-time capture with something like wf-recorder** — length and frame count
  become machine-speed dependent, breaking both (1) and (3) above. **run the real Claude Code /
  Codex** — output differs every time, not reproducible. A stub was placed under `demo/bin/`,
  matched to the real thing only through `/proc` (argv[0]'s basename). **pointer injection** —
  needs `/dev/uinput` permission or a resident daemon; AT-SPI Actions were enough. **full baseline
  image comparison** — not taken, same reason as 0030 (meaningless on a different machine with a
  different font / theme). **import `tests/headless.py` directly** — would drag the test's skip
  logic and opt-in into the demo. The session part was moved to `tools/headless.py`, with the tests
  side made a thin layer.
- **Consequences**: headless constraints (single output, scale 1, default 1280×720) carry over to
  the demo too. Changes to `tools/headless.py` affect both `./scripts/check-gui` and the demo.
  Recording needs ffmpeg / grim / ImageMagick / foot / Noto fonts, but `./scripts/check`'s
  dependencies have not grown (confined to `scripts/demo`). **Videos are not committed**
  (`demo/out/` is in `.gitignore`). Reproducibility requires stopping every on-screen motion: foot
  needs `cursor.unfocused-style=unchanged` in addition to `cursor.blink=no` (cursor rendering
  changes on focus in/out), and the overlay's text caret cannot be stopped because **GTK 4.22 does
  not read `gtk-cursor-blink` from `settings.ini`**, so recording waits for it to settle naturally
  about 8 seconds after the last keypress (capture requires "the same frame 7 times in a row").
  Working copies of fixtures live at a **fixed path**
  (`/tmp/wayhint-demo-<uid>-<lang>`) — the YAML-error scene shows this path on the overlay, so a
  `mkdtemp`-style name would change frames every time.
- **What Phase A (investigation) changed from the draft**: embedding `{pid}` in `spawn`'s argv does
  not work (the pid is only decided after exec), so the same wrapper as README's "multiple terminal
  windows" (`demo/bin/foot-wayhint`) is used. AT-SPI Actions **worked**, so no downgrade to `cli:`
  was needed. However `do_action` does not wait for the action to complete, so a `press` must
  always be followed by a `wait_for` before proceeding. The contents of the search box and forms
  cannot be read from AT-SPI, so effects (row counts, labels) are checked instead. Output
  resolution is left at the default 1280×720; recording fails if the first frame's size doesn't
  match the scenario. One step is one action (`press` and `type` are separate steps, because of the
  waiting rule above); window layout is written by name in the scenario's `windows:` and lowered
  into labwc's `windowRules`. wtype is only required for a scenario containing `key:` / `type:`, and
  fails outright if absent (not silently replaced by the CLI, since showing the hotkey path is the
  point).

## 0032 — build intro videos per-showcase from the demo generation system, running only Herdr for real, isolated

- **Date**: 2026-09-21
- **Status**: accepted
- **Context**: with 0031's generation system in place, build the actual intro videos (60 seconds /
  3 minutes / 5 minutes, captions only, silent, Japanese version). The original idea was to run
  `wf-recorder` on real-hardware labwc. Since the subject matter will keep growing (Herdr, terminal
  emulators, GUI apps), one video should be one self-contained unit. The three centerpiece scenes
  (watch it switch as you look deep inside Herdr / it never steals focus / write it down on the
  spot and grow it) **only work inside Herdr** — the crux is that switching Herdr panes swaps the
  sheet, which a stub cannot show at all, since it needs the `HerdrContextProvider` path itself.
  Measurement environment (measured under C-A): herdr 0.8.2 / labwc 0.20.2 / GTK 4.22.4 /
  foot 1.28.0 / ffmpeg 9.0.2.
- **Decision**: one video is a **showcase**, and script, scenario, and generated output for it are
  confined to `demo/showcases/<name>/`. A showcase's identity is its directory name; the files
  inside are found by the role suffix in their name (`<NN>_<showcase>_<role>.<ext>`). The number is
  only there for people to order the workflow; tools ignore it. **`01_*_storyboard.md`
  (hand-written script) is the source of truth for the pitch, scenes, and order**;
  **`02_*_scenario.yaml` is the source of truth for actions, `hold`, and the actual captions**.
  Captions and length are worked out in the scenario first and then carried back to the storyboard.
  If the scene itself needs to change, that is reported and paused rather than edited into the
  storyboard silently.
  **Only Herdr runs for real** (this overrides 0031's "do not run the real Claude Code / Codex /
  Herdr", for Herdr only). But it runs only inside a session-private
  `HOME` / `XDG_CONFIG_HOME` / `XDG_RUNTIME_DIR`, and **`HERDR_*` is stripped from the session's
  environment** — without that, a recorder launched from a Herdr pane inherits
  `HERDR_SOCKET_PATH`, and a client inside the session connects to **that person's own Herdr**
  (measured under C-A). Claude Code / Codex remain stubs, with only the executable filename under
  `demo/bin/` and `prctl(PR_SET_NAME)` made to resemble the real thing.
  The scenario can only call herdr subcommands **on an allow-list** through a `herdr:` action.
  Arguments are validated too: `pane run`'s launch command is limited to executable names present
  in `demo/bin` (no `/`, no `..`, existence checked), generator commands like `tab create` accept
  only `--focus` / `--no-focus`, with `--cwd` / `--env` / `--label` reserved to the recorder.
  `server stop` is only for the recorder's own teardown and cannot be called from a scenario. One
  video is a **variant** (`60s` / `3min` / `5min`), and each must be *a complete action sequence
  that stands on its own, run in order starting from a clean session*. Variants do not carry state
  across each other, and there is no hidden setup or automatic dependency resolution. If the same
  operation is wanted at a different length, the step is duplicated. Language is **ja first**: the
  default `--lang` is ja, `--validate` only requires ja captions, and missing en fails only under
  `--record --lang en`.
- **Alternatives**: **`wf-recorder` on real-hardware labwc** — re-recording goes back to manual
  work, timecodes get typed by hand, and there is room for an accident involving the production
  daemon and keybinds. The very reason 0031 was built is the reason this is rejected.
  **stub Herdr too** — the centerpiece scene is "switching Herdr's pane swapped the sheet"; faking
  Herdr removes that scene's evidentiary value.
  **also run the real Claude Code / Codex** — output differs every time, not reproducible. In
  fact, a PATH misconfiguration once let the real thing launch and captured the first-run theme
  picker screen (from that experience, `DemoSession` now confirms before launch that `pane run`'s
  resolved target is inside `demo/bin`). **put the storyboard under `docs/`** — the storyboard is a
  per-showcase working file, and `docs/` would grow by one file per video as subjects multiply.
  **fold Herdr into `cli:`** — `cli:` is wayhint's own CLI, with a different notion of allow-list
  (only fixed command names); mixing it in would leak Herdr's argument validation into `cli:` too.
  **override `hold` per variant** — allowing "this step is 2 seconds only in the 60-second version"
  would make it impossible to tell what gets recorded just by reading the scenario. Step
  duplication is redundant, but it is redundancy that reads clearly.
- **Consequences**: **if Herdr's CLI output format changes, the demo breaks**. `pane current` /
  `pane process-info` are also used by the product's adapter, so a break there would be noticed on
  the product side too. The JSON of `tab create` / `pane run` is read only by the demo.
  **Fixtures are one set shared across showcases**, so when a later showcase adds a sheet, the
  earlier video's list row count changes (noticed when `wait_for`'s `hints` fails). Whether to
  split them is decided once this becomes inconvenient. **The scenario grows long from step
  duplication** (currently 61 steps, 3 variants). Recording starts an independent session per
  variant, so the three together take about 15 minutes. **`demo/fixtures/hints/en/` was deleted** —
  it was English sheets made for 0031's six scenes, and it does not fit this showcase's subject
  matter. An English version is a separate task that creates `hints/en/` afresh. What 0031 called
  `demo/scenario.yaml` and `demo/out/` moved to
  `demo/showcases/<name>/02_<name>_scenario.yaml` and `demo/showcases/<name>/out/` respectively.
  `{demo_bin}`, which used to refer to the program inside the script, is gone too; only the name is
  written and the recorder resolves it (review fix below).
- **Review fixes (2026-09-21)**: plugged the gaps a Codex review surfaced. **no shell in the
  session** — `default_shell` is set to `demo/bin/idle`. Since the script types characters into
  terminals, a shell sitting in a pane would let the script run arbitrary commands. `idle` only
  reacts to the neighboring stub's name and discards anything else typed at it. `spawn`'s argv is
  also limited to names only (absolute paths and `..` rejected), resolved by the recorder.
  **restrict names to file-name-safe form** — showcase name, variant name, and step id are
  `[a-z0-9-]` only. Before deleting an output location, `resolve()` it and confirm it is under
  `out/`. **restrict numbers to finite values** — `.nan` / `.inf` silently pass comparisons, and the
  first visible symptom would be the frame count. **give the session bus the session's own
  environment** — this had not been done, so the AT-SPI launcher was creating a socket in the real
  `XDG_RUNTIME_DIR`. **tear down even on a failed startup** — a failure before `__enter__` returns
  means `with` never started, so `__exit__` never runs; both sessions were assembled with
  `ExitStack`. **0031's scene 4 (starting two foot windows under the `.p<pid>` convention, and the
  sheet swapping as focus follows) was dropped from the demo and moved into one GUI test in
  `tests/test_gui_headless.py`**. As a subject for the video it overlaps with switching Herdr panes,
  but it is worth keeping as a regression test of product behaviour. This test uses the `demo/bin/`
  stubs and wrapper, so **the test depends on the demo** (not the other way around).
  `./scripts/check-gui` went from 5 tests to 6, and run time grew from 16.8 to 18.6 seconds.
- **Threat model (2026-09-21 addendum)**: reviews of the demo generation system are scoped as
  follows. **Untrusted (treated as data)** — scenario contents, `./scripts/demo`'s CLI arguments,
  strings sent via `type:`, the state of `out/` (including symlinks and pre-existing files — a
  person may deliberately point it at another disk). **Trusted (treated as code)** — `tools/`, the
  contents of `demo/bin/`, `demo/fixtures/`, and the Herdr and foot binaries. Anyone able to tamper
  here could rewrite `tools/` itself, so it is not defended against. **What must hold** — (a)
  untrusted input can never reach a shell, (b) nothing outside `out/` is ever deleted, (c) the real
  user's environment (`~/.config/*`, `~/.claude*`, the real `XDG_RUNTIME_DIR`) is never read or
  written. Anything that doesn't fall into these three, e.g. a route via a tampered symlink placed
  in `demo/bin/`, is a trusted-side concern and out of scope for later reviews. The symlink
  rejection in `demo/bin/idle` (below) was added only because the fix was a few lines, not because
  the scope was widened.
- **Re-review fixes (2026-09-21, second round)**: plugged 6 more issues against the threat model
  above. **never follow symlinks under `out/`** — right before deletion, check
  `out/` / `out/<lang>/` / `out/<lang>/<variant>/` *before resolving them*, and abort without
  recording if any is a symlink. Pointing `out/` at another disk is a normal thing to do, and
  following it would move the deletion target there too. Use `--out-dir` (below) to place it
  elsewhere. **allow-list the terminal wrapper's arguments** — `spawn`'s argv is restricted to the
  wrapper name (`foot-wayhint` or `foot-herdr`, enumerated individually rather than by prefix
  match), `--app-id=foot-<name>`, and, only for `foot-wayhint`, the form `-e <stub>`. A `foot`
  invoked with no command opens a login shell, which was the last hole in "no shell in the
  session". The wrapper side stopped passing `"$@"` straight through to foot too, gated by the same
  list. **pass Herdr's absolute path to the wrapper via an environment variable**
  (`WAYHINT_DEMO_HERDR_BIN`) — `foot-herdr` used to end in bare `herdr`, leaving room for it to pick
  up `demo/bin` at the head of PATH. If unset, the wrapper exits 1. **statically list the names
  `idle` is allowed to exec** — enumerating a directory only answers "what's next to it", a
  different question from "what may a pane launch". Symlinks are rejected too (a few lines, though
  out of scope since it's trusted-side). **unify name validation into one place** —
  `tools/demo/names.py`'s `validate_name` is used by the scenario, the showcase, and the CLI
  (`--showcase` `--variant` `--only` `--from`). Switched from `re.match` to `fullmatch`, since
  `re.match` allows a trailing newline. **tear down in the reverse of startup order** —
  `HeadlessSession` brings up bus → compositor → daemon in that order, but the stop list was built
  as `[*_procs, _bus]`, so the bus went down first. Pulling the session bus out from under a live
  compositor is the shape that hangs an AT-SPI client on exit.
- **Fixes to align captions with the screen (2026-09-21, B-7)**: watching the three generated
  videos surfaced places where the caption pointed at an event not visible on the frame, and these
  were fixed. **The session's working directory is `/tmp/wayhint-demo/<showcase>-<lang>/`** — no
  uid. This path shows up on screen as a YAML-error banner, so it's part of the video, and
  `…-1000-…` looks like an accident to a viewer. Two people recording simultaneously on the same
  machine is not supported (exits 1 if the directory already exists, rather than clearing it).
  **The single-key-operation scenes were fixed to match product behaviour instead** — since saving
  a form ends edit mode (0021), `f` / `J` / `K` are placed **before** the save. In the first draft
  they were placed after, so they never reached the overlay and were typed as characters into the
  Codex pane instead. Furthermore edit mode has **no key that moves the selected row**
  (measured: neither `Down` nor `Tab`+`Down` works), so a single-key operation can only be shown
  against whichever row was selected on entering edit mode, i.e. the first row. So `favorite` was
  removed from `codex.yaml` and the first row made a plain hint — to leave a star for `f` to add.
  **`demo/bin/vi` actually reads and displays the given sheet's contents** — when it used to show a
  fixed excerpt, the 4 frames / 32 seconds talking about `match` / `inherit` / `include` overlaid a
  screen with none of those lines. It can only open the session fixtures' copy
  (`WAYHINT_DEMO_CONFIG`), so the scenario can never put an arbitrary file on screen. **`J` / `K` are
  sent via `type:`** — neither `wtype -k J` nor `-M shift -k j` reached the window as uppercase;
  uppercase only arrives in text mode (measured).
- **Fixes from watching the result (2026-09-22, B-8)**: decisions people made after watching the
  three generated videos. **The GUI-app scene is shot with a GTK4 stub `notes`** — no real app
  (like gedit) is used. Output differs every time, and it would also borrow a real logo and
  wording. The stub is just a label, with no entry and no scrolled window (caret and scrollbar
  change over time). The window is sized to cover the terminal beneath it — this scene's subject is
  the GUI window, and a peeking terminal behind it is confusing about what to look at. The sheet is
  matched to the app_id via `match.wayland`, and the point is that the overlay's sub-header shows
  no process name. Conversely the "terminal with no Herdr" scene was dropped (it says the same
  thing as the scene right before it). **Caption-band rows are reserved by layout** — rather than
  hiding by making the band opaque, the window and overlay are both stopped above the band. The
  band's geometry is decided by `caption_band_top` / `caption_text_top` in
  `tools/demo/encode.py`, top edge at 638 for 720p. The window is sized via `windows`' `height` in
  the scenario, and the overlay via `overlay.height` in `config.yaml` (measured: window 624 /
  overlay 628 / edit form 628). labwc's `<margin>` is not used — `rc.xml` is written by
  `tools/headless.py`, and demo-only concerns should not be brought into it. **the shared sheet
  (`wm`) holds operations on the window itself** — "show/hide this overlay (`Super+H`)" would not
  count as a hint otherwise. Anyone who's forgotten it can't even open this list.
- **Storyboard and scenario are cross-checked, not generated (2026-09-22)**: generating
  `02_*_scenario.yaml` from `01_*_storyboard.md` is not adopted — the storyboard would need step
  ids and actions in it, turning it into an alternate YAML notation and losing its role as "the
  place a human thinks through the pitch". Instead, `--validate` only checks the storyboard's
  claims about the scenario (captions, per-section seconds, section-heading range, total seconds)
  (`tools/demo/storyboard.py`). **Let the machine watch what used to be hand-synced** — during B-7
  and B-8, scenes were added and removed and the storyboard's seconds were fixed by hand each time,
  and all three passes missed something (13 issues were found right after this check was added).
  Which variant a section belongs to is marked with `<!-- variant: <name> -->`. A step whose
  `wait_for` asserts nothing is only a **warning** — a step that correctly changes nothing on
  screen exists (like `pause:`), and a machine cannot tell the two apart.
- **How the 17 warnings were cleared (2026-09-23)**: "a `wait_for` that asserts nothing" split into
  ones that could get a condition added and ones that couldn't. **For the ones that could**, two new
  conditions were introduced — `first_hint` (the list's first row) is for watching `J` / `K`
  reordering, which `label` cannot see (the set of rows is unchanged even as rows move). `text` (the
  input field's contents) is for checking whether what was typed into the form reached the overlay;
  it only reads nodes with an `EditableText` interface (label also has a text interface, so reading
  all of them would just be a weaker copy of `label`). **For the ones that couldn't** — a step that
  just types characters into a terminal, a step where only the caption advances — write
  `wait_for.unchecked: "<reason>"`. Made it a **sentence** rather than a flag, so the next person
  asking "why is this one an exception" has an answer (under 10 characters exits 1). While
  implementing this, it turned out a list row (`list item`) **has no name** — key, title, and
  category all live on the child label, so the first row is read between the first and second lines
  of a depth-first dump.
- **`--out-dir` only accepts "your own directory" (2026-09-23)**: keeping the ban on turning `out/`
  into a symlink, `--out-dir <path>` was added for anyone wanting output elsewhere. Recording
  **deletes** `<path>/<lang>/<variant>` before starting, so what it accepts is limited to **an empty
  directory, or one this tool wrote here before** (marked by `.wayhint-demo-out`). Someone else's
  non-empty directory is refused, not deleted — `--out-dir ~/Videos` is a plausible typo, and
  `~/Videos/ja/3min` a plausible pre-existing real directory. `out/` inside the repo needs no
  marker (the repo names it, and nothing else goes there). Only the wrapper's argument checking is
  a shell script, so `./scripts/check`'s test **actually launches the wrapper as a subprocess**.
  What does not get launched is **foot and Herdr** — every case stops a few lines before
  `exec /usr/bin/foot`, so neither a compositor nor a server is needed, and it sits alongside the
  pure-parsing tests. **Regexes are matched with `fullmatch`** — `$` also matches just before a
  trailing newline, so with `re.match`, `--app-id=foot\n` or `w1:p1\n` would pass (Codex's third
  finding).

## 0033 — split search into "typing" and "filtering"; persist filtering per sheet to state.yaml

- **Date**: 2026-09-23
- **Status**: accepted
- **Amends**: 0014 (D3's state-transition table: entry/exit of `search`. D10's "filter state lasts
  only the display session"). Design doc §4 / §30 / §47 / §48, DESIGN "state and keyboard_mode"'s
  `search` row, and §9 category filter.
- **Context**: entering search, copying, and leaving search all need the mouse. The only way to
  move focus into the search box is the search button, since normal display is NONE and an
  overlay-side key cannot reach it (same circumstance as `edit-mode`, 0014 D3). On top of that,
  leaving search clears the filter and returns to showing everything. In actual use there are cases
  like "I only want pane-related hints while I'm doing this task", where you want to stay filtered
  and look for a long time. The current design conflates **the time a key grab is held** (which
  should be short) with **the filter's lifetime** (which should last for the whole task).

- **Decision**:

  **A. Make the entry point of search mode an IPC.** Add `wayhint search-mode`, called from a
  compositor keybinding (README's example is `W-S-h`). If hidden, show and resolve context, then
  enter `search`; if already shown, go straight to `search`. A second `search-mode` while in
  `search` returns to `normal` via the same path as Esc (keyboard_mode NONE → focus returned to the
  previous view). No new exits are added. `search-mode` while in `edit` is refused in keeping with
  "no searching while editing" (0014), with the reason shown. The search button stays.
  **(2026-09-23 addendum) `toggle` while in search also just hides/shows.** As with `edit` (0014
  D4), a hotkey while searching hides the overlay keeping search intact, and a second press brings
  it back with the search box's contents restored. Of the original C's "hide is an exit from
  `search`", the `toggle`-driven hide is removed here (`Close` and `wayhint hide` still exit and
  close as before, as does leaving the workspace). This matches the same-day amendment to 0014 D4
  about a second press of the mode hotkey returning to the shown state at entry. If `search-mode`
  arrives while hidden mid-search, it shows again and keeps searching, same as `edit`.
  **(2026-09-23 addendum) Context is re-resolved even while shown.** When pressed from a different
  window, just like `toggle`, replace the contents without closing the overlay, then enter
  `search`. Same window: nothing changes. In real-hardware T45, pressing this from a different foot
  running vi, while an overlay opened in a Herdr window stayed shown, searched Herdr's hints, and
  on exit returned focus to Herdr. Since the hotkey means "hints for what I'm looking at right now"
  (README), the original wording that reused the shown context was wrong. `edit-mode` means editing
  what is shown, so it is not re-resolved (**withdrawn in 0035**).

  **B. `Enter` in the search box means "copy and go back".** Run the same processing as the existing
  "Copy" button (resolving `copy → command → key`, then GDK clipboard) against the selected hint
  (the first result row is auto-selected), then return to `normal` via the same path as Esc. When
  the list has focus, `c` and `Enter` do the same thing. When there are zero results, or the hint
  has nothing copyable (e.g. `note`), do nothing, show the reason, and stay in `search`. No paste
  (key injection) into the underlying app is done.

  **C. Separate "search mode" from "filtering".** Every exit from `search` (Esc /
  `Enter` / `c` / pressing `search-mode` again / hide) **only drops the grab; the filter is kept**.
  `normal` shows the filtered list as is. List rendering is unified into one; filtering applies to
  the normal display (favorite section, category headings included). The separate rendering where
  "search results show only title/key/command" (design doc §30) is retired. `normal` shows a chip
  while filtered, whose `×` clears it (mouse only). Clearing via keyboard is
  "`search-mode` → empty the box → exit". That is, **the box's contents on exit are the filter**,
  and no dedicated clear key exists. `#category` and Tab-cycling change the box's text, so they are
  part of filtering (Tab rewrites the box's leading token `#<category> `). The pseudo-category
  "none" is written as **`#-`** in the box (language-independent, so switching
  `appearance.language` never changes what a saved filter means; the chip shows the translated
  "inbox" / "未定義"). On re-entry, the saved filter is put in the box and fully selected (typing
  replaces it, `End` appends, leaving with Esc unchanged as is).

  **D. Filtering is persisted keyed by sheet id.** It lives at
  `$XDG_STATE_HOME/wayhint/state.yaml` (default `~/.local/state/wayhint/state.yaml`). Format:

  ```yaml
  version: 1
  filters:
    claude-code: "pane"
    herdr: "#session"
  ```

  The key is the active (child) sheet's id, and it applies to the whole list including
  parent-hints mixed in via nested / include. When leaving `search`, if it differs from before, a
  temp file plus rename writes it; if empty, that key is removed. This file is not watched (only
  the daemon writes it). It survives hide/show, workspace switches, and daemon restart, so the same
  sheet has the same filter in any workspace. In a context with no active sheet, `search` can still
  be entered but the filter is not saved (memory-only, cleared when context changes).
  `wayhint refresh` and reload re-read and re-apply using the re-resolved sheet's key. When a reload
  arrives during `search` (from something like a `git checkout` or a sync tool, not a human hand),
  only the list is redrawn and the search box is left untouched (text, cursor, IME preedit, focus
  all preserved); the filter is **re-applied from the box's text**, not from state.yaml, and the
  selected row is restored by id (or the first row if it's gone). "Edit in editor" just returns to
  `normal` per 0023, and the filter is kept, so every gvim save updates the still-filtered list.

  This is where **the three-way split of files is made explicit**: content is `hints/` (people
  write it), settings are `config.yaml` (people write it, only resize gets written back by the
  daemon), and state is `state.yaml` (only the daemon writes it).

  **E. Never stop on breakage.** If state.yaml is missing / unreadable / broken YAML / its top level
  is not a mapping / `version` is not 1 / it exceeds 64 KiB, **start with no filters** and emit one
  WARN line. No `⚠` is shown in the UI (would be indistinguishable from broken hints). There is no
  last-known-good and no `.bak`; the next write overwrites it with valid content. A partially wrong
  entry (a non-string value, a sheet id not matching `^[A-Za-z0-9][A-Za-z0-9._-]*$`, a value over
  200 characters) is dropped, just that entry. Entries beyond 256 are dropped. Unknown sheet ids
  are kept (only an explicit clear removes them). Unknown keys are ignored and disappear on the
  next write-back. A duplicate sheet id is **last-wins** (ruamel's safe loader errors on duplicate
  keys by default, so `allow_duplicate_keys = True` is set explicitly). A write failure keeps using
  the in-memory filter with a WARN, retried on the next change (same as config saving).
  `wayhint validate` does not look at state.yaml.

  **F. The filter string is never interpreted.** It is never treated as regex, path, shell, or
  Pango markup — only the existing case-insensitive substring plus token-AND is used (and would
  stay so even if replaced by RapidFuzz or similar later). No character-set restriction (searching
  remarks in Japanese is a primary use case). The cap is 200, both for the input field's
  `max_length` and on read (over that is dropped, not truncated). Unicode category `Cc` is dropped
  both on input and on read. The chip is shown via `set_text`. WARN never logs the filter's
  contents. state.yaml is **read leaning untrusted, the same as "contents of a directory people can
  touch", like hints** (write it yourself, doubt it when reading). 0032's threat model is scoped to
  the demo generation system, so this is not added there.

  **G. Relationship with edit mode.** `edit` can be entered while filtered. `J` / `K` are
  **disabled while filtered**, since on-screen neighbor and YAML-order neighbor diverge (nothing
  happens, same as with a different group of hints). `a` / `Enter` / `dd` / `u` / `f` are
  unaffected.

- **Alternatives**:
  writing the filter into the sheet file (a filter is view state, not content; it would leak into
  `format` / schema / validate / examples; `hints/`'s file monitor would pick up its own write,
  needing a "my own write" exception on the watcher side; gvim having the sheet open would trigger
  W11; dotfiles management would show a diff); memory-only per workspace (same granularity as
  0012/0014 D4, cleared on restart, and the same sheet in a different workspace would get a
  different filter); dropping the filter when context changes (keying by sheet just looks at a
  different key instead, no need to drop); keeping the same hide/show retention as `edit` for the
  `search` hotkey (the filter is persisted separately, so nothing is lost on exiting `search`);
  restricting the copy target to "a hint with `command`" (would duplicate the existing
  `copy → command → key` rule); a dedicated clear key or CLI `clear-filter` (emptying the box and
  exiting is enough); disallowing `edit` while filtered (there are cases where you want to look at
  a filtered view while editing, and only `J`/`K` cause trouble); character-set restriction (would
  break Japanese search); making state.yaml's path configurable, multiple daemons, writes from
  other processes (not part of current usage; **deferred**).

- **Consequences**:
  the list may look short in `normal`, but the chip explains it (added to README troubleshooting).
  Entering search mode fills the box with the previous filter, so typing a new term means typing
  over it (already fully selected). The known limitation on focus restoration (multiple same
  app_id plus title changes leave the destination undetermined, README) applies the same way to
  the keyboard flow, and a click is needed if it gets stuck there. `search`'s state-transition
  table becomes "exits: Esc, Enter / c, `search-mode`, hide, leaving workspace" / "entries: search
  button, `search-mode`". DESIGN §30's "result list shows only title/key/command" is deleted.
  i18n (en/ja) gains the chip's label and "nothing to copy". Manual checks added to DESIGN's
  real-hardware checklist as T38–T46: keybinding → `search-mode` → `Enter` copies and returns
  focus / the filter survives after Esc / it survives a daemon restart / corrupting state.yaml
  still starts, with one WARN line / `J`/`K` do nothing in `edit` while filtered / the same
  filter applies to the same sheet in a different workspace / pressing `search-mode` again
  returns to `normal` / rewriting a sheet through another path during `search` leaves the box's
  text, focus, and filter untouched / "Edit in editor" during `search` returns to `normal`, and
  the filtered list updates after gvim saves.
  README gains an `rc.xml` example (`W-S-h` → `wayhint search-mode`), state.yaml added to the
  file-layout table, and the three-way file split (content / settings / state) documented.

## 0034 — parent hints default to "unspecified = all"; filtering leans on the parent sheet's `nested.export_tags`

- **Date**: 2026-09-23
- **Status**: accepted
- **Supersedes**: design doc §18's default `nested-common`. 0025's Context premise "with
  `nested.parent_tags` set" (read as: mixing in parent hints requires writing something).
- **Context**: when a child sheet is selected (Claude Code inside Herdr, vi inside foot), it was
  expected that parent-sheet hints would mix in even with nothing written in either config.yaml or
  the sheet. In the implementation, global `nested.parent_tags` defaulted to `()`, and if neither
  the child nor global wrote anything, parent hints numbered **zero**. This is the reverse default
  both from the no-sheet-matches-foreground case (show every parent hint) and from `include`
  (no tag filtering, take everything, 0026). On top of that, the vocabulary for how much to pass
  through was held by the child and global, not the parent, so a role reversal existed: Herdr's own
  sheet could not decide how much of Herdr's hints to show to a child.
  `dev-docs/PRODUCT.md`'s "default `nested-common`" also disagreed with the implementation (`()`).
- **Decision**:
  **D1. Resolution order is a single replacement rule (no intersection).**
  1. child sheet's `inherit.parent_tags` (explicit)
  2. config.yaml's `nested.parent_tags` (explicit)
  3. parent sheet's `nested.export_tags` (explicit)
  4. none specified → all of the parent sheet's hints

  Use **only the first level found explicit**, looking no further down. At any level, an explicit
  `[]` means **zero** (opt-out). "Unspecified" is the key being absent (`null` counts as
  unspecified too), represented as `None`, distinct from `[]`. If levels 1–3 have a non-empty list,
  filter as before with `wanted ∩ hint.tags`.
  **D2. Left untouched.** Showing every parent hint when the foreground has no sheet. `include`
  (no tag filtering, replacement, no multi-level). `export_tags` only affects the nested-parent
  path; it is not consulted for hints pulled in via `include`. How the parent is decided (the
  resolver). The global `nested.parent_tags` key itself is kept, only its default changes from
  `()` to `None` (removing the key would break existing config.yaml with an unknown-key error).
  The tag attached by quick add / `wayhint add --parent` to a hint written into the parent sheet
  follows the same rule, and none is attached when passing everything through (`None`).
- **Alternatives**:
  **a child-side `inherit.parents` that varies the filter per parent** (deferred). Draft:

  ```yaml
  inherit:
    parents: {herdr: [pane], foot: []}   # parent sheet id → tags to accept from that parent
  ```

  A parent is fixed to one per window, so this waits for a concrete case where the same child wants
  a different filter per parent. There is also no settled notation for "sheet name only, no tag
  filter" (`all` / `null`). **A tag filter on `include`**
  (`include: [{sheet: x, tags: [...]}]`) and a cross-cutting `always_tags`: already rejected in
  0026, not reopened. **Removing global `nested.parent_tags`**: deferred for compatibility (D2
  above). **Making `TERMINAL_APP_IDS` configurable**: 0027 stands; this round's motivation was a
  misread default, not a new terminal requirement.
- **Consequences**: a large parent sheet makes the child's list long; if a filter is wanted, write
  `export_tags` on the parent. Whether to add a separator heading before parent hints will be
  decided after looking at length on real hardware (0026's "unmarked" stands for now).
  `examples/` dropped `config.yaml`'s `nested.parent_tags` and moved it into `herdr.yaml`'s
  `nested: {export_tags: [terminal]}`. The demo fixtures set it explicitly via config, so the
  videos are unchanged.

## 0035 — `edit-mode` also re-resolves context while shown, replacing first if from a different window

- **Date**: 2026-09-23
- **Status**: accepted
- **Amends**: the last sentence of 0033 A's addendum ("`edit-mode` is not re-resolved").
- **Context**: with the overlay shown from Herdr's codex tab, moving to the claude tab and pressing
  `edit-mode` (`W-C-h`) entered edit mode still on codex's sheet (user report, confirmed in the
  daemon log that `edit-mode` had arrived). The overlay stays shown across a tab switch, so "edit
  what is shown" is indistinguishable, to a user, from "hints for what I'm looking at now". Same
  mismatch that 0033 A fixed for `search-mode`.
- **Decision**: when `edit-mode` arrives while shown in the `normal` view, re-resolve context the
  same as `search-mode`, and if `target_key` differs, replace first the same as `toggle`, then
  enter `edit`. Two cases are not re-resolved: already in `edit` (0014 D4, a second press exits /
  if hidden, the draft is shown again), and a view that returned to `normal` from launching the
  editor while holding a draft (0023; the draft belongs to the on-screen sheet, and replacing would
  lose it).
- **Alternatives**: not re-resolving, and making the on-screen sheet's name more prominent instead —
  even if noticed right after pressing, the hotkey would still need pressing again, so not taken.
- **Consequences**: every `edit-mode` while shown now costs one extra context resolution (same as
  `toggle` / `search-mode`). A view holding a draft still does not get replaced by a press from a
  different window, as before.

## 0036 — config's `nested.parent_tags` is positioned as a global opt-out; the resolution order stays as in 0034

- **Date**: 2026-09-24
- **Status**: accepted
- **Context**: in 0034 the basis for filtering moved to the parent sheet's `nested.export_tags`,
  and global `nested.parent_tags` was kept only for compatibility, with no stated purpose. Using it
  to decide tag conventions in one place isn't much different in effort from `export_tags`, since
  almost the only parents are terminals or multiplexers. And since global sits above the parent
  level, writing it makes every parent's `export_tags` get ignored the moment it's set.
- **Decision**: position global as a way to **stop everything with `[]` (mix no parent's hints into
  any child) globally**. Filtering by tag is done via the parent's `export_tags`. The resolution
  order (child → global → parent → all) is unchanged. The rule is documented in `docs/SHEETS.md`.
- **Alternatives**: **change the resolution order to "child → parent → global"** — global would
  then naturally mean "the default when the parent writes nothing", but a parent that does write
  `export_tags` would then be immune to global's `[]`, no longer an opt-out.
  **deprecate and remove** — removing it would break existing config.yaml with an unknown-key
  error, and the one-line opt-out would be gone.
- **Consequences**: no code change. Writing a non-empty list into global is not forbidden but not
  recommended (`docs/SHEETS.md` §3). To stop everything globally while still passing something to
  one particular child, write that child's `inherit.parent_tags`.

## 0037 — `wayhint hide` behaves like `toggle`'s hide; only the Close button actually closes

- **Date**: 2026-09-24
- **Status**: accepted
- **Amends**: 0014 D4 / 0033 (`Close` button and `wayhint hide` close; hide is an exit from search).
- **Context**: pressing `Super+h` during search / edit hides while keeping mode and draft, but
  `wayhint hide` closed just like the Close button, discarding the edit draft. A "put it away"
  operation from the CLI produced a different result than the hotkey.
- **Decision**: make `wayhint hide` behave the same as `toggle`'s removal from screen — during
  search / edit it releases the keyboard and just hides, keeping mode, search box, and draft
  (restored by the next `toggle` or mode hotkey). If already hidden, do nothing. In `normal` it
  closes. The Close button and close-request still close as before, discarding the edit draft
  (the daemon's `close`).
- **Alternatives**: keep `hide` always closing — no reason for CLI and hotkey to differ. Have the
  Close button keep the draft too — one explicit "close" means is needed (user's judgment).
- **Consequences**: `wayhint hide` during search is no longer an exit from search, and at that
  point state.yaml is not written (the filter is saved on actual exit, or on leaving the
  workspace).

## 0038 — CLI hint edits require `--sheet`; `--parent` is removed

- **Date**: 2026-09-24
- **Status**: accepted
- **Amends**: 0014 D11 ("the CLI decides the sheet from `context`'s result"), 0034 D2 (the tag
  attached by `wayhint add --parent`).
- **Context**: `add` and similar commands, when `--sheet` was omitted, asked the daemon for
  `context` to decide the sheet. But typed from a terminal, the terminal's own foreground process
  turns out to be `wayhint` itself. `add` then created a new `^wayhint$` sheet, writing into
  Herdr's own sheet when run inside Herdr (reproduced 2026-09-24 in `match_rule_for_context`). A
  guard was tried first ("stop if the foreground process is yourself", adding a pid to IPC
  `context`), but the user decided the sheet should always be specified instead.
- **Decision**: make `--sheet` required for `add` `edit` `remove` `favorite` `move` (argparse exits
  2 if missing). The CLI asks the daemon nothing. `add --parent` is removed; write to a parent
  sheet with `--sheet <parent's id>` instead. There is no longer a path for the CLI to create a new
  sheet (only quick add in edit mode and the editor can create one). IPC `context` is unchanged (no
  pid added).
- **Alternatives**: **a guard stopping when the foreground process is yourself** — leaves a feature
  that only guesses correctly when run from a keybind, and needs a pid added to IPC too.
  **require it only for `add`** — the same guessing hole remains for the other commands.
  **keep `--parent` and decide the parent from the child sheet's config** — the parent is decided
  by context (the window's app_id), not a fixed relationship between sheets.
- **Consequences**: the CLI now works even while the daemon is stopped. "Add one entry to whatever
  sheet I'm looking at" from a keybind is no longer possible (use edit mode's quick add instead). To
  attach `export_tags`' tag to a hint written into the parent, add it via the editor or YAML.

## 0039 — copying during search is only the list's `c`; `Enter` just exits. `key` is dropped from what can be copied

- **Date**: 2026-09-24
- **Status**: accepted
- **Amends**: 0033 B ("Enter" in the box or "c" in the list means "copy and go back"; staying with
  a reason shown if there's nothing to copy). Partially reverses 0033's Alternatives rejection of
  "restrict the copy target".
- **Context**: under the `copy → command → key` rule, a key-only hint copied the key string
  itself (e.g. `Ctrl+Shift+V`). A key is something you press, not something you paste, and putting
  it on the clipboard achieves nothing. Also, since `Enter` means "copy and go back", just reading a
  found hint and going back overwrote the clipboard anyway. Pointed out by the user while watching
  the demo (2026-09-24).
- **Decision**:
  - The copy target is `copy`, else `command`. `key` is never copied (`Hint.copy_text`). The
    "Copy" button follows the same rule; it is disabled if there is no target.
  - `Enter` during search (from either the box or the list) and `Esc` return to `normal` without
    copying. The filter still persists as in 0033 C.
  - `c` in the list copies the selected hint and returns to `normal`. If there's no target, it
    returns without copying (no warning shown).
  - `↓` in the box moves to the list; `↑` / `↓` in the list move the selection; `↑` on the first
    row returns to the box. Keys are read at the window's capture stage (since a layer surface can
    lose the list's own focus, this doesn't rely on the list itself).
  - While searching, key help is shown below the list, in the same form as edit mode.
- **Alternatives**: **restrict the copy target to `command` only** — `copy` is a value written
  explicitly when display and copy content should differ, with no reason to ignore it (user's
  judgment). **leave the "Copy" button as before** — no reason for `c` and the button to differ.
  **`Enter` in the box moves to the list** — would split `Enter`'s meaning into "move" versus "go
  back" depending on location; `↓` is just the same downward motion through the list, adding
  nothing new to remember. **stay and show a reason when there's no target (as in 0033 B)** —
  `c` doubles as "I've read this, go back", so staying would need an extra `Esc` just to return.
- **Consequences**: there is no longer a way to copy directly from the box; it's two keystrokes,
  `↓` `c`. 0033's T39 ("Enter" copies) becomes just a check that `Enter` returns; copying is
  checked in T47 instead. Sheet format is unchanged (only the explanation of `copy`'s default
  changes).

## 0039 — `include` can also filter by tag; both `nested` and `include` can also filter by category

- **Date**: 2026-09-24
- **Status**: accepted
- **Amends**: 0026 (hints from an included sheet are not tag-filtered, taken in whole;
  `{sheet: x, tags: [...]}` rejected), 0034 ("a tag filter on `include`" not reopened).
- **Context**: keeping shared sheets small alone doesn't let you mix in just part of one sheet
  (only a frequently-used category, or only a specific tag) into another. Parent-sheet hints could
  only be filtered by tag, with a request to be able to carve out by category too. The user's
  judgment reverses 0026's rejection.
- **Decision**: **include**: an element can be a sheet id (everything) or
  `{sheet, tags, categories}` (filtered). config's `include` takes the same form. **nested**:
  filter by category as well as tag. Resolve child `inherit.parent_categories` → config's
  `nested.parent_categories` → parent's `nested.export_categories` → everything, by the same rule
  as tags, independently of tags. **Combination**: tag and category are OR'd, whichever is written
  (user's judgment). If either is `[]`, the result is zero regardless of the other — so that
  config's `nested.parent_tags: []` still works as the global opt-out (0036). Category match is
  exact, and a hint without a category matches no category. **Implementation**: include's
  filtering happens at load time, returning a copy of the sheet with only `hints` reduced (hints
  are the original objects, so the edit target is unchanged; nothing downstream changes).
- **Alternatives**: **filter with a separate key (`include_filter:`)** — separates the sheet being
  mixed in from its filter, harder to read. **filter by kind** — this is where implementation
  actually started, but category was what was wanted (user correction). **AND** — doesn't fit
  wanting to catch by either one (user's judgment). **have `[]` follow OR too** — would break the
  global opt-out via the parent's `export_categories`.
- **Consequences**: quick add into a parent sheet still auto-attaches only tags, not a value
  matching the category filter (the form's category is written as is). If a parent filters by
  category, a hint added with a non-matching category will not appear in the child's list.

## 0040 — show how filtering behaves via `wayhint inspect` and `wayhint context --shown`; no warnings or UI added

- **Date**: 2026-09-24
- **Status**: accepted
- **Context**: a hint dropped by a parent's `export_*` or by `include`'s `tags` / `categories`
  (0039) shows no reason either on screen or in `wayhint context`. `wayhint context` re-resolves the
  instant it's run, so typing it in a terminal ends up looking at `wayhint` itself, unable to
  inspect what's actually on screen. Since the parent is decided by the window, not the sheet's own
  setting, a static check with a specified sheet cannot tell what nested would be.
- **Decision**: add two commands. **`wayhint inspect SHEET [--parent ID]`**: from files, without
  using the daemon, show include's per-element filter and counts, and, with `--parent`, the assumed
  parent's tag / category and where they came from (which level's key, and which file), plus
  counts. **`wayhint context --shown`**: add `shown` to IPC (not a subcommand; `ipc.QUERIES`),
  returning the shown view's context with the same explanation, without re-resolving. Both share
  one explanation routine, `selection.explain_filters`.
- **Alternatives**: **warn via `validate` / `⚠` for a filter matching nothing** — an empty sheet or
  a filter matching nothing is a normal thing to have, and would become a warning that just sits
  there (user's judgment). **show counts or dropped hints on the hint screen itself** — would make
  everyday display noisier, and touches on edit mode's meaning of "on-screen neighbor" too;
  reconsider if this proves insufficient in use. **`wayhint context --sheet`** — `context` is "what
  would resolve right now"; mixing in a static check would blur its meaning.
- **Consequences**: counts are before duplicates are removed. `inspect`'s `--parent` is an
  assumption, so results differ if the real parent differs (use `--shown` for the actual screen).
  IPC's response grows a little for the filter explanation, well within the 4096-byte limit.

## 0041 — quick add, when the foreground app has none of its own hints, adds to that app's sheet

- **Date**: 2026-09-24
- **Status**: accepted
- **Amends**: 0025
- **Context**: opening the list auto-selects the first row (`restore_index`). When the foreground
  app has no sheet, or an empty one, every row in the list is a parent or included hint, so pressing
  `a` added to **a different app's sheet**, per 0025. When the foreground process inside a terminal
  has no sheet, the resolver shows the terminal's own sheet as active
  (`active_sheet == parent_context`), so even with the selection cleared, it still added to the
  parent, never reaching the path that creates a sheet for the foreground process (0014 D6).
- **Decision**: when the foreground app's sheet is missing or empty, make the add target **the
  foreground app's sheet** regardless of selection. If it doesn't exist, create it on save (0014
  D6, matched from the foreground process). `Ctrl+P` can still switch to the parent as before. If
  the foreground app has its own hints, 0025 still applies (the selected hint's sheet). "The
  foreground app has no sheet" is judged only when `active_sheet == parent_context`, the foreground
  process is resolvable, and the parent sheet doesn't match that process. When the process isn't
  resolvable (the terminal itself is the foreground), creating one would match every command run
  inside that terminal (0027).
- **Alternatives**: have the resolver set active to `None` when the foreground process has no sheet
  (this would also change display, output destination selection, and `wayhint context`; only the
  add target is the actual problem); drop the auto-selection (opening a parent hint with `Enter`
  would need one more step).
- **Consequences**: pressing `a` while a shell prompt is the foreground inside Herdr creates a
  sheet for the shell (with the generic-process warning, 0027). Use `Ctrl+P` to add to the parent
  instead. The form's heading reads "→ new sheet" so it's visible at a glance.

## 0042 — split the common intro video into 4 content variants (overview / search / edit / sheets)

- **Date**: 2026-09-24
- **Status**: accepted
- **Context**: common was a single 192-second video, twice as long as the three "how wayhint finds
  it" videos combined (47–105 seconds). Fixing one caption meant re-recording all 192 seconds, and
  192 seconds is long for an intro sitting at the top of README besides. The storyboard was already
  split into the three centerpiece scenes and a writing-style section. B-9's decision, "no
  length-only variants (a short cut gets recorded separately)", is unchanged.
- **Decision**: keep the showcase as common, but give it 4 content variants. `overview` (the
  problem, always the same place, switching after looking deep inside), `search` (never steals
  focus, search and copy), `edit` (write it on the spot, undo if broken), `sheets` (how to write a
  sheet, what it doesn't do). Each stands alone as one complete video, starting from launching Herdr
  and Claude Code. All but overview start with an uncaptioned `boot-*`, without repeating overview's
  problem-statement caption.
- **Alternatives**: split into 4 separate showcases (would duplicate the same premises — fixtures,
  staging, storyboard — across 4 places); keep the 192-second version, fixing only captions
  (a fix means re-recording everything).
- **Consequences**: the shared ending ("the moment you forget, always the same place…",
  "Wayland (labwc) / …") uses the same step across variants. A video combining these 4 and the
  three "how it finds it" ones into one is planned for `demo/showcases/all/`, not yet built.

## 0043 — the full-run intro video is showcase `all` with 60 / 180 / 300-second variants, scenes copied from the source showcases

- **Date**: 2026-09-24
- **Status**: accepted
- **Context**: with scenes and captions revisited across common's 4 videos and the three
  how-it-finds-it videos (herdr / terminal / gui), a combined full-run video is needed (60 seconds
  for SNS/README, 180 for an introduction, 300 for a full walkthrough). 0042 already decided this
  would go into `demo/showcases/all/`. Steps in the scenario cannot be shared across showcases, and
  `hold` can only be written once per step.
- **Decision**: give showcase `all` three variants, `60s` / `180s` / `300s`. Each is a complete
  video recorded from a clean session, none cut down from a longer one (0032). Scenes and captions
  are copied from the source showcases, with length-specific scenes as separate steps prefixed
  `m-` (180 seconds) / `q-` (60 seconds). Within one video, state carries across chapters (a hint
  added earlier still shows in later chapters' lists), and a narrowed filter is reset back to the
  fixture at the chapter's end. The 60-second version also produces a square output.
- **Alternatives**: stitch the 7 outputs together afterward with ffmpeg (each would start from
  launching Herdr, repeating the same opening at every seam); add a mechanism to the recorder for
  sharing steps across showcases (the script would no longer be readable as one file, and fixing a
  source showcase would silently change `all`).
- **Consequences**: captions now exist in two places, the source showcase and `all`. A fix must be
  made in both (documented in the storyboard). The 300-second version opens and closes Herdr,
  terminal, and GUI windows within one session, so window layout is unified in `all`'s script into
  one set (`vi` uses Herdr's position).

## 0044 — Documents are English under their own name, with a Japanese version as `<name>.ja.md`

- **Date**: 2026-09-25
- **Status**: accepted
- **Context**: The repository is going public on GitHub, and every document was written in
  Japanese. A reader who does not read Japanese could not install or use wayhint from them.
- **Decision**: `<name>.md` is English and `<name>.ja.md` is the Japanese version beside it, for
  README, `docs/`, `dev-docs/`, `demo/README.md` and the demo storyboards. Each pair links to the
  other on the line after its title. A change goes into both in the same commit. `STATUS.md` and
  `AGENTS.md` stay in one language. The demo storyboards follow the same naming, and each is
  checked against the captions in its own language. `scripts/setup-terminals` prints in the
  locale's language, the rule wayhint's interface follows.
- **Alternatives**: a `ja/` directory per document tree (every link to a Japanese document moves,
  and the pair is not next to each other on GitHub); English only (the Japanese text was the
  original and is what the author maintains first).
- **Consequences**: Two copies to keep in step. Links inside a `.ja.md` point at the other
  `.ja.md` files.

## 0045 — The author's coding-agent configuration and working log are not published

- **Date**: 2026-09-25
- **Status**: accepted
- **Context**: Before the first push to GitHub, the repository tracked the author's agent setup
  (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/`, `.agents/`, `scripts/agent-hooks/`) and the
  Japanese working log `STATUS.md`. None of it is needed to use or build wayhint.
- **Decision**: Remove them from the whole history before publishing and list them in
  `.gitignore`; the author keeps them locally. The rules a contributor needs from `AGENTS.md`
  (judging a check by its exit code, adding checks to `./scripts/check`) move into
  `dev-docs/DEVELOPMENT.md`.
- **Alternatives**: publish them (harmless, but noise for a reader); keep a private `main` and
  export a history-less public branch at each release (the local routine stays, but the public
  history is only release cuts and pull requests have to be carried over by hand).
- **Consequences**: Changes to those files are no longer versioned in this repository. Older
  entries here still mention `AGENTS.md` and `STATUS.md` as they were at the time.

## 0046 — Text from other programs and shared sheets is shown and written defensively

- **Date**: 2026-09-25
- **Status**: accepted
- **Context**: A security review before publishing found no way for YAML, `/proc` or Herdr text to
  be executed, but found places where text wayhint does not control -- an app_id, a process name,
  a sheet someone else wrote -- could mislead the user or leave something in their files.
  Sheets are still trusted as the user's own; these are for the day one is shared.
- **Decision**:
  - The detail pane shows what `c` copies whenever it is not exactly the command on the row, with
    control characters written out (`\n`), so a sheet cannot show one command and copy another.
  - The comment at the top of a generated sheet writes control characters out: a bare `\r` in an
    app_id would otherwise end the comment line and become a real key.
  - The `/tmp/wayhint-<uid>` socket directory used without `XDG_RUNTIME_DIR` is refused unless it
    is a real directory, the user's own and mode `0700`.
  - `setup-terminals` quotes the terminal's path in the wrapper and makes it absolute, and stops
    before writing anything when `~/.local/bin` has a character the launchers cannot carry
    unquoted.
  - A write to a symlinked sheet replaces the target and touches the link; the new file is
    `fsync`ed before it replaces the old.
  - Sheets and `config.yaml` over 1 MiB are not read; regexes see at most 4096 characters of each
    app_id, argument or command line.
- **Alternatives**: showing nothing new and documenting `copy` as trusted (a shared sheet is exactly
  where it is not); timing regexes out (Python's `re` has no timeout, and a thread per match is out
  of proportion for text this short).
- **Consequences**: A pattern anchored with `$` stops matching past 4096 characters. A home
  directory with a space in it cannot use `setup-terminals`; the manual steps in
  `docs/TERMINALS.md` still work.

<!--
Entry format (this block is an example, not an entry -- it is kept as a comment so that it cannot
be mistaken for one, and so the first real decision gets number 0001):

## NNNN — Title of the decision

- **Date**: YYYY-MM-DD
- **Status**: accepted | superseded by 000N | rejected
- **Context**: what forced a choice, and what constrained it.
- **Decision**: what was chosen, in one or two sentences.
- **Alternatives**: what else was considered, and why it lost.
- **Consequences**: what this now costs or forecloses.
-->
