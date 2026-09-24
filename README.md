# wayhint

[日本語](README.ja.md)

On Wayland (wlroots-based compositors: labwc, Wayfire, etc.), one hotkey press shows a **cheat
sheet for the app you are currently using** at a fixed spot on the screen (top-right by default).
It looks into commands running inside a terminal or Herdr (vi, Claude Code, Codex, ...) and
switches its contents accordingly. You write the contents yourself in YAML and grow it over time.

- It does not steal keyboard focus while shown. You can keep working in the original app.
- Search, add, edit, favorite, and reorder all happen inside the overlay.
- A `command` written in YAML is only shown and copied, never executed.

If you are developing wayhint, start at [`dev-docs/DEVELOPMENT.md`](dev-docs/DEVELOPMENT.md).

## What you want to do → where to read

| What you want to do | Where to read |
|---|---|
| Install it | [Installation](#installation) |
| Assign a hotkey, start the daemon automatically | [Compositor setup](#compositor-setup) |
| Stop or restart the daemon | [Starting and stopping the daemon](#starting-and-stopping-the-daemon) |
| Show hints for a command inside a terminal (vi, Claude Code, ...) | [Multiple terminal windows](#multiple-terminal-windows), [`docs/TERMINALS.md`](docs/TERMINALS.md) |
| View and copy hints | [Using the overlay](#using-the-overlay) |
| Search for a hint | [Search](#search) |
| Add, fix, or reorder hints inside the overlay | [Edit mode](#edit-mode) |
| Write a sheet in an editor | [Writing hints](#writing-hints), [`docs/SHEET-FORMAT.md`](docs/SHEET-FORMAT.md) |
| Add or fix hints from the command line | [Rewriting hints with the CLI](#rewriting-hints-with-the-cli) |
| Mix in shared hints, build parent/child sheets | [Which sheet gets picked](#which-sheet-gets-picked), [`docs/SHEETS.md`](docs/SHEETS.md) |
| Change position, size, language, editor, or appearance | [Config file](#config-file), [`docs/CONFIG.md`](docs/CONFIG.md) |
| Know what a hotkey does in each state | [`docs/HOTKEYS.md`](docs/HOTKEYS.md) |
| It's not working | [Troubleshooting](#troubleshooting) |
| Update to a new version, uninstall | [Update](#update), [Uninstall](#uninstall) |

## Table of contents

1. [Installation](#installation)
2. [Compositor setup](#compositor-setup)
3. [Config file](#config-file)
4. [Using the overlay](#using-the-overlay)
5. [Writing hints](#writing-hints)
6. [Multiple terminal windows](#multiple-terminal-windows)
7. [CLI](#cli)
8. [Starting and stopping the daemon](#starting-and-stopping-the-daemon)
9. [Update](#update)
10. [Uninstall](#uninstall)
11. [Troubleshooting](#troubleshooting)

## Installation

Dependencies: Python 3.11+, GTK4 + PyGObject, gtk4-layer-shell (with its typelib), a Wayland
compositor that exposes `wlr-foreign-toplevel-management` and `wlr-layer-shell` (labwc, or
Wayfire with the `foreign-toplevel` plugin enabled). Optionally Herdr and gvim. On Debian/sid:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0
```

```sh
git clone <this repo> ~/work/tools/wayhint && cd ~/work/tools/wayhint
./scripts/setup                 # create .venv and install Python dependencies
.venv/bin/pip install -e .      # put wayhint / wayhintd in .venv/bin
```

Put a symlink somewhere on your PATH so you can type `wayhint` from a terminal (the examples in
this README assume `wayhint` is called from PATH). The compositor config uses an absolute path,
so it does not rely on this symlink.

```sh
ln -s ~/work/tools/wayhint/.venv/bin/wayhint ~/work/tools/wayhint/.venv/bin/wayhintd ~/.local/bin/
```

Copy the templates and you can start right away (`style.css` is included too; remove it if you
want to use the app's default colors).

```sh
cp -r examples/. ~/.config/wayhint/
```

## Compositor setup

Start one instance of the daemon (`wayhintd`) per session, and have the compositor's keybinds
call the CLI for hotkeys. The default assignment is these three:

| Key | Command | Meaning |
|---|---|---|
| `Super+h` | `wayhint toggle` | Show / hide hints for the window you are currently looking at |
| `Super+Shift+h` | `wayhint search-mode` | Enter / leave search |
| `Super+Ctrl+h` | `wayhint edit-mode` | Enter / leave edit mode |

### labwc (`~/.config/labwc/rc.xml`)

```xml
<keyboard>
  <keybind key="W-h">
    <action name="Execute" command="/home/USER/work/tools/wayhint/.venv/bin/wayhint toggle"/>
  </keybind>
  <keybind key="W-C-h">
    <action name="Execute" command="/home/USER/work/tools/wayhint/.venv/bin/wayhint edit-mode"/>
  </keybind>
  <keybind key="W-S-h">
    <action name="Execute" command="/home/USER/work/tools/wayhint/.venv/bin/wayhint search-mode"/>
  </keybind>
</keyboard>
```

Add one line to `~/.config/labwc/autostart` for autostart (the file must be executable). Apply
with `labwc --reconfigure`.

```sh
/home/USER/work/tools/wayhint/.venv/bin/wayhintd &
```

If your autostart setup has a mechanism to kill helper processes it started on exit, follow that
convention (e.g. `spawn wayhintd`). No systemd user unit is provided.

### Wayfire (`~/.config/wayfire.ini`)

```ini
[command]
binding_wayhint = <super> KEY_H
command_wayhint = /home/USER/work/tools/wayhint/.venv/bin/wayhint toggle
binding_wayhint_edit = <super> <ctrl> KEY_H
command_wayhint_edit = /home/USER/work/tools/wayhint/.venv/bin/wayhint edit-mode
binding_wayhint_search = <super> <shift> KEY_H
command_wayhint_search = /home/USER/work/tools/wayhint/.venv/bin/wayhint search-mode

[autostart]
wayhint = /home/USER/work/tools/wayhint/.venv/bin/wayhintd
```

Add `foreign-toplevel` to `[core] plugins`. If it is missing but `ipc` and `ipc-rules` are
present, wayhint switches to the Wayfire IPC automatically (you can also pin this with
`context.backend: wayland|wayfire` in `config.yaml`).

### Other compositors

Any compositor that exposes `wlr-foreign-toplevel-management` and `wlr-layer-shell` (e.g. sway)
should work, but only labwc and Wayfire have been verified. Run `wayhint toggle` etc. from a
hotkey, and start `wayhintd` from autostart.

### Checking it works

Running `wayhintd -v` in the foreground in a terminal prints info-level logs (the chosen backend
is on the `desktop backend:` line). Confirm it responds with `wayhint ping` from another
terminal. No environment variables are needed for IME (if it doesn't work, see
[Troubleshooting](#troubleshooting)).

## Config file

Location: `$XDG_CONFIG_HOME/wayhint/` (default `~/.config/wayhint/`). Everything works even if
none of these exist.

| Path | Contents |
|---|---|
| `config.yaml` | Overlay position and size, editor, language, etc. If missing, everything defaults |
| `style.css` | Optional. Overrides the appearance with GTK CSS. The `examples/style.css` template matches labwc's theme (Syscrash) |
| `hints/<language>/*.yaml` | Hint sheets. One file is one sheet ([Writing hints](#writing-hints)) |

- The language of button labels etc. is decided by the machine's locale (`LC_ALL` →
  `LC_MESSAGES` → `LANG`). It can be pinned with `appearance.language: en|ja`. Anything other than
  English or Japanese falls back to English.
- Search filtering is state, not configuration, so the daemon writes it to
  `~/.local/state/wayhint/state.yaml`. It is not meant to be edited by hand, and the daemon
  starts with no filter if it is broken.
- After editing, check it with `wayhint validate` (exits 1 if there is a problem). Once saved,
  the daemon reloads it automatically.

Every `config.yaml` key and its default, and how `style.css` is read, are collected in
[`docs/CONFIG.md`](docs/CONFIG.md).

## Using the overlay

### Showing and hiding it

`Super+h` means "**hints for the window I am currently looking at**". Press it to show them;
press it again while the same hints are shown to hide them. Press it after switching to a
different window and it swaps to that window's hints instead of hiding.

- The contents are decided by **the window at the moment you show it**, and do not follow
  automatically if you switch windows. Press `Super+h` again in the new window (or
  `wayhint refresh` if you only have the mouse).
- Keyboard input does not reach the overlay while it is shown. Hide it with the hotkey or the
  **Close** button. `Esc` only works while searching or in edit mode.
- The overlay only appears **on the workspace where you showed it**. Move to another workspace
  and it hides; come back and it reappears with the same contents. To show it on all workspaces,
  put `context: {workspace: all}` in `config.yaml` (this only works if the compositor exposes
  `ext-workspace-v1`; labwc supports it, Wayfire does not and is always all-workspaces).

What the three hotkeys do in each state, and when things disappear, is diagrammed in
[`docs/HOTKEYS.md`](docs/HOTKEYS.md).

### Reading the list

Each row is one hint: `key` on the left, title and `command` in the middle, `category` on the
right. Selecting a row opens details below it: `remark`, tags, source, the date learned, and the
sheet it belongs to.

The order is: hints with `favorite: true` (marked `★`) first, in the order written in YAML, then
the rest grouped by category. Categories appear in the order they were first seen; within the
same category, hints keep the order they were written in. To change the order, reorder the hints
in the YAML (or use `J` / `K` in edit mode).

Resize by grabbing the grip on the opposite corner from the anchor (bottom-left for the default
top-right anchor). Corners resize width and height together; the left and bottom edges resize
only width or only height. The size you end up with is written back into `config.yaml`'s
`overlay.width` / `height` in px, and used again next time.

### Buttons

| Button | Action |
|---|---|
| Search | Enter search. Press again (Done) or `Esc` to leave. Disabled during edit mode |
| Copy | Copies the selected hint to the clipboard: `copy` if present, else `command`. Disabled for a hint with neither |
| Edit in editor | Opens the selected hint's sheet in the editor and jumps to its line (or the shown sheet if nothing is selected). The overlay stays shown, so the list refreshes on every save. This leaves search or edit mode (to hand the keyboard to the editor). A draft being edited is restored the next time you enter edit mode |
| Edit | Enter edit mode |
| Close | Closes the overlay. Discards any draft being edited |

### Search

Enter with `Super+Shift+h` (or the Search button). Filters to hints that contain **all** the
space-separated words. Case-insensitive; matches against title, `key`, `command`, `category`,
tags, and `remark`.

- Writing `#name` at the start filters by category. `Tab` / `Shift+Tab` cycle through categories
  (`#-` is hints with no category).
- Pressing `↓` in the search box moves to the list (the top row is selected as you type). In the
  list, the following keys work, and are shown at the bottom of the overlay too. Leaving returns
  the keyboard to the original window.

  | Key | Action |
  |---|---|
  | `↑` `↓` | Move the selection. Pressing `↑` at the top of the list returns to the search box |
  | `c` | Copy the selected hint's `copy` (or `command` if absent) and leave search. If neither exists, leave without copying |
  | `Enter` / `Esc` | Leave search without copying (same in the search box) |
  | `Tab` / `Shift+Tab` | Cycle categories (search box) |
- **The filter stays even after you leave.** It is saved per sheet, and comes back if you open
  the same sheet again, even after closing the overlay or restarting the daemon. While filtered,
  a chip appears above the list; clear it with `×`.
- The next time you enter search, the previous filter is in the box, fully selected. Type to
  replace it, or press `End` to append.
- Pressing `Super+Ctrl+h` while searching moves to edit mode, keeping the box's text as the
  filter.

### Edit mode

Enter with `Super+Ctrl+h` (or the Edit button); leave with the same key or `Esc`.

| Key | Action |
|---|---|
| `↑` `↓` | Move the selection |
| `a` | Add a hint (added to the same sheet as the selected hint; shown in the form's heading) |
| `Enter` | Edit the selected hint |
| `d` `d` | Delete the selected hint (first press confirms, second press commits) |
| `u` | Undo the last deletion |
| `f` | Toggle favorite |
| `J` / `K` | Swap with the hint below / above (only within the same group and same file; disabled while filtered) |
| `Esc` | Closes the form if one is open (discarding input); leaves edit mode if none is open |

Inside the form, `Enter` saves, `Esc` discards, `Tab` / `Shift+Tab` move between fields, and
`Ctrl+P` switches the add destination to the parent sheet. **Saving the form ends edit mode**,
returning the keyboard to the original app (so you can enter one hint and get back to work).
Favoriting, reordering, deleting, and undo can all continue while staying in edit mode.

You cannot enter edit mode if the shown sheet's YAML is broken.

## Writing hints

Hints are written in YAML under `~/.config/wayhint/hints/<language>/`. One file is one sheet, and
**the `id` must match the file name (without extension)**. Every field a sheet can have, and the
rules around it, is collected in [`docs/SHEET-FORMAT.md`](docs/SHEET-FORMAT.md).

```yaml
# hints/en/vi.yaml
id: vi
title: vi
match:
  process: {argv_regex: ["^vi$", "^vim$"]}
hints:
  - {id: save, title: Save, key: ":w", category: File}
  - {id: quit, title: Quit without saving, key: ":q!", category: File}
  - id: substitute
    title: Replace across the whole file
    command: ":%s/old/new/g"
    remark: "Drop the g to replace only the first match on each line"
    favorite: true
```

The daemon reloads it automatically on save (you don't need to close the overlay). If the YAML
is broken, the last good version keeps being shown, and `⚠ YAML error file:line: message` appears
at the top of the overlay.

### Hint fields

Only `id` and `title` are required.

| Key | Purpose |
|---|---|
| `id` | A name unique within the sheet. Not shown in the overlay |
| `title` | The description shown in the list |
| `kind` | The kind of hint. `shortcut` (default) is a keystroke, `command` is a command, `tip` has both, `note` is a text-only memo. Only `note` hides `key` and `command` in the list. `kind` itself is not shown in the overlay |
| `key` | The keystroke shown at the left of the list. Long ones wrap (line breaks in the YAML are kept as-is) |
| `command` | The command shown below the title. **Never executed** — only shown and copied |
| `category` | The heading shown at the right of the list. Hints with the same category sit next to each other. If omitted, falls into a pseudo-category (`inbox`; `未定義` in the Japanese UI) |
| `tags` | Used to filter which hints mix in as a parent sheet ([Parent sheet hints](#parent-sheet-hints)). Also searched |
| `favorite` | `true` marks it with `★` and moves it to the front. Does not change how many hints are shown |
| `copy` | Set only when the string to copy differs from what's shown. Defaults to `command`. `key` is never copied |
| `remark` | Extra note shown only when selected |
| `source` | Where it came from (e.g. a URL to official documentation) |
| `learned` | The date learned (ISO date format) |

### Which sheet gets picked

Sheets are chosen by `match`. All of these are Python regular expressions, matched as a
substring.

- `match.wayland.app_id_regex`: matched against the window's app_id
- `match.process.argv_regex` / `cmdline_regex`: matched against the command running inside a
  terminal (the foreground process)

If both a window sheet and a command sheet match, the window sheet becomes the **parent** and the
command sheet the **child**, and the parent's hints are appended after the child's. You don't have
to write a sheet for the terminal itself (in that case only the command sheet is shown). When
multiple sheets match, one is picked by `priority` (higher wins), then by the number of matched
patterns, then by file name. A sheet with no `match` never appears on its own; it can only be
used via `include`.

The command is answered by Herdr itself for Herdr (**the window's app_id must contain `herdr`**),
and by wayhint walking `/proc` for terminals like foot. If a terminal has two or more windows,
you need the launch convention described in
[Multiple terminal windows](#multiple-terminal-windows).

The full set of rules is diagrammed in [`docs/SHEETS.md`](docs/SHEETS.md).

### Parent sheet hints

**If you write nothing, all of the parent's hints are appended to the child's list.** To narrow
this, write `nested.export_tags` (by tag) or `nested.export_categories` (by category) in the
parent sheet. If you write both, any hint matching either is passed through.

```yaml
# hints/en/herdr.yaml — only hints tagged terminal are passed to the child's list
id: herdr
title: Herdr
match: {wayland: {app_id_regex: [herdr]}}
nested: {export_tags: [terminal]}
hints:
  - {id: new-pane, title: New pane, key: Ctrl+Shift+N, tags: [terminal]}
  - {id: theme, title: Switch theme, key: Ctrl+Shift+T}   # not shown in the child's list
```

- To filter by category, write `nested: {export_categories: [basics]}` (no need to mark hints).
- A child sheet can narrow it differently for itself with `inherit.parent_tags` /
  `parent_categories`.
- To keep the parent's hints out entirely, write `nested: {parent_tags: []}` in `config.yaml`.
- `[]` means "show no parent hints" wherever it is written, regardless of the other setting.

### Mixing in other sheets (`include`)

Shared hints, like window-manager operations or IME, can be collected into one sheet and mixed
into others.

```yaml
# hints/en/wm.yaml — has no match, so it never appears on its own. Only used for mixing in
id: wm
title: Window manager
hints:
  - {id: close-window, title: Close window, key: Super+Shift+Q}
```

```yaml
# hints/en/claude-code.yaml (match and hints omitted)
id: claude-code
title: Claude Code
include:
  - wm                                   # wm's hints are appended at the end of this sheet's list
  - {sheet: git, categories: [basics]}    # only the "basics" category from git
```

```yaml
# config.yaml — default that applies to every sheet that has no include of its own
include: [wm]
```

- A sheet's `include:` **replaces** config's default (it is not additive). `include: []` mixes
  in nothing.
- Writing just an id mixes in everything. To mix in only part of it, write it as
  `{sheet, tags, categories}`. If you write both tags and categories, any hint matching either is
  included. `[]` means zero.
- `include` is not followed through the sheet you mixed in (only one level deep).
- Writing an id that doesn't exist still shows the sheet. A warning appears in the overlay's ⚠
  and in `wayhint validate` (exit 0).
- Editing or deleting a mixed-in hint rewrites **that hint's own file** (see `file:` in the
  details pane).

### Hints per language

Sheets live in per-language directories, and **only the directory for the display language** is
read.

```
~/.config/wayhint/hints/
  ja/   claude-code.yaml  herdr.yaml   # only this one is read in a Japanese-language setup
  en/   claude-code.yaml  herdr.yaml
```

- The language is decided the same way as button labels, so hints and UI never end up in
  different languages.
- Search order: `hints/<language>/` → `hints/en/` → `hints/*.yaml`. If you only use one language,
  a flat layout is fine.
- Sheets with the same id can exist per language. Translations are not kept in sync
  automatically.
- Switching is just changing `appearance.language` (no restart needed).

### Editor

`config.yaml`'s `editor.command` is an argv list. Placeholders are `{file}` `{line}`
`{hint_id}`. It does not go through a shell, so quoting and pipes cannot be used.

```yaml
editor:
  command: [code, --goto, "{file}:{line}"]
```

`wayhint schema --write` writes a JSON Schema for hint sheets (default
`~/.config/wayhint/schema.json`); putting the following line at the top of a sheet enables key
completion and validation with yaml-language-server. With `editor.schema_modeline: true`, newly
created sheets and `wayhint format` add this line automatically.

```yaml
# yaml-language-server: $schema=/home/USER/.config/wayhint/schema.json
```

## Multiple terminal windows

If a terminal has two or more windows, wayhint needs to know **which window is in front**.
Neither Wayland nor labwc has a way to answer "which process is drawing this window", so we use
the convention that **the window identifies itself through its app_id**. If the app_id ends in
`.p<pid>`, that number is used as the terminal's PID.

```sh
#!/bin/sh
# ~/.local/bin/foot-wayhint
exec /usr/bin/foot --app-id "foot.p$$" "$@"
```

Create this wrapper and point **every path that launches the terminal** (compositor keybind, bar,
menu, `.desktop` file) at it. wayhint strips the suffix before matching, so a sheet's
`app_id_regex` can stay as `["^foot$"]`.

- Supported: foot / kitty / Ghostty / Alacritty (each with conditions) and Herdr (launch with
  `herdr` included in the window's app_id, e.g. `foot --app-id=foot-herdr`). WezTerm cannot vary
  its app_id per window, so it is not supported.
- Even for windows that don't go through the wrapper, it still resolves if that terminal has only
  one process.

Setup can be done with a script. **It writes nothing unless you pass `--apply`.** It never
rewrites bar or compositor config; it only shows what would change.

```sh
./scripts/setup-terminals           # dry run: shows what it would do
./scripts/setup-terminals --apply   # fixes wrapper / .desktop / launcher config
```

The conditions for each terminal, and how to confirm it's working, are in
[`docs/TERMINALS.md`](docs/TERMINALS.md).

## CLI

`wayhint <command>` just sends one line to the daemon; it has no window of its own.

| Command | Action |
|---|---|
| `toggle` | Show / hide (`Super+h`) |
| `search-mode` | Enter / leave search (`Super+Shift+h`). Refuses while in edit mode |
| `edit-mode` | Enter / leave edit mode (`Super+Ctrl+h`) |
| `show` | Show |
| `hide` | Hide. While searching or editing, same as `toggle`: just hides, keeping the mode and any draft |
| `refresh` | If shown, re-fetch contents for the current window |
| `reload` | Reload `config.yaml` and hints |
| `ping` | Check if the daemon is alive. Returns its pid and sheet count |
| `validate` | Validate the YAML. Works without the daemon running. Exits 1 if there is a problem |
| `context` | Shows which sheet would be picked for the current window. With `--shown`, shows the contents of the overlay currently shown and how mixed-in hints were filtered |
| `inspect SHEET [--parent ID]` | Shows a sheet's includes and, given an assumed parent, how many of how many hints are mixed in. Works without the daemon running |
| `add` / `edit` / `remove` / `favorite` / `move` | Rewrite hints (below) |
| `format [PATH...]` | Reformats sheets into a fixed order and shape |
| `schema [--write PATH]` | Prints the JSON Schema for hint sheets |

`validate` accepts `--config-dir`; every other command accepts `--socket` to change the default
location. Each command's arguments are shown by `wayhint <command> --help`.

### Rewriting hints with the CLI

`add`, `edit`, `remove`, `favorite`, and `move` all **require `--sheet` to specify the id of the
sheet being written to**. They write directly to the sheet's file without going through the
daemon, so they work even if the daemon is stopped. Once saved, the change is reflected in the
overlay right away too.

```
wayhint add TITLE --sheet ID [--kind K] [--key S | --command S] [--category S] [--remark S]
wayhint edit ID --sheet ID [--title S] [--kind K] [--key S | --command S] [--category S] [--remark S]
wayhint remove ID --sheet ID
wayhint favorite ID --sheet ID [--off]
wayhint move ID up|down --sheet ID
wayhint format [--modeline] [PATH...]        # without PATH, all hints/<language>/*.yaml in use
```

Examples:

```sh
wayhint add "Save and quit" --key ":wq" --category File --sheet vi
wayhint add "Open config" --kind command --command "vim ~/.vimrc" --sheet vi
wayhint edit save --key ":w!" --sheet vi       # ID is the hint's id (not shown in the list; check the sheet)
wayhint favorite save --sheet vi
wayhint move save up --sheet vi
wayhint remove save --sheet vi
```

- A sheet's id matches its file name (without extension). When adding to a parent sheet, write
  the parent's id, e.g. `--sheet herdr`.
- The CLI cannot create a new sheet. Write a new sheet in an editor, or create one with `a` in
  edit mode.
- `add`'s `id` is generated automatically from the title (for a title that can't be turned into
  alphanumerics, e.g. one that's only Japanese, it becomes `q-<timestamp>`). The generated id is
  printed as `added <id> to <file>`, so use that for `edit` and the like. `learned` is set to
  today's date.
- Fields that don't fit `--kind` cannot be specified. `shortcut` (default) only takes `--key`,
  `command` only `--command`, `tip` takes both, `note` takes neither.
- `move` only swaps with a neighbor in the same group (favorites together, or the same category).
  It errors if that would cross a group boundary.
- `tags`, `copy`, and `source` cannot be written from the CLI or the edit-mode form. Write them in
  the sheet with an editor.

### Reading `wayhint context`

This is for checking "why did this sheet appear". Only fields with a value are listed as
`key=value`. Running vi in foot gives you this (actually on one line):

```
$ wayhint context
active_sheet=vi desktop_app=foot.p12345 chain=['ProcAdapter'] \
  process={'name': 'vi', 'argv_basenames': ['vi', 'notes.txt']}
```

- `chain` empty: not recognized as a terminal (the command was not looked up).
- `chain` present but no `process`: it was checked but couldn't be determined (e.g. multiple
  windows not following the convention). Better to show nothing than the wrong sheet.
- The `.p12345` in `desktop_app` is only for identifying the window; it is not used for sheet
  matching or display.

Running `wayhint context` inside a terminal makes `wayhint` itself the foreground command. To
check what's inside a terminal, use `wayhint context --shown` (below).

### When a hint that should be mixed in doesn't show up

Hints mixed in from a parent sheet or via `include` can be dropped by a tag or category filter.
Check where it was dropped with these two:

- **While writing a sheet**: `wayhint inspect <sheet id>`. For each `include` entry, it shows the
  filter's contents and "how many of how many are mixed in". Since the parent is determined by
  the window the sheet runs in, pass one explicitly, e.g. `--parent herdr`, to also see the
  parent hints' filter.
- **On the actual screen**: press `Super+h` in the window you want to check to show the overlay,
  then from another terminal run `wayhint context --shown`. For what's currently shown (not
  re-checked), it shows the chosen sheet, its parent, the filters, and where each filter came
  from (which file, which key).

```
$ wayhint inspect claude-code --parent herdr
sheet claude-code (claude-code.yaml)
parent herdr: 4/12 shown
  tags: pane -- nested.export_tags (herdr.yaml)
  categories: not narrowed
include git: 3/9 shown (from claude-code.yaml)
  tags: not narrowed
  categories: basics
```

A count like `0/12` suggests a mistyped tag or category. The count is before deduplication.

## Starting and stopping the daemon

- **Starting**: normally the compositor's autostart launches it at login
  ([Compositor setup](#compositor-setup)). To start it by hand:
  `~/work/tools/wayhint/.venv/bin/wayhintd &`. If it's already running, it prints
  `wayhintd already running` and exits.
- **Stopping**: it stops together with the compositor when you log out. To stop it by hand:
  `kill "$(wayhint ping | sed -n 's/^pid=\([0-9]*\).*/\1/p')"` (the daemon cleans up its socket
  before exiting).
- **If it crashes**: it does not restart itself. Pressing a hotkey shows nothing, and
  `wayhint ping` returns `wayhintd is not running`. Use the one-liner below to restart it.
- **Logs**: run `wayhintd -v` in a terminal in the foreground to watch them.

### Restarting

Changes to hints and `config.yaml` are picked up automatically, so a restart is only needed when
you update wayhint or change `style.css`. Stop and start it again with this one line:

```sh
cd ~/work/tools/wayhint && p=$(.venv/bin/wayhint ping | sed -n 's/^pid=\([0-9]*\).*/\1/p'); \
  [ -n "$p" ] && kill "$p" && while kill -0 "$p" 2>/dev/null; do sleep 0.1; done; \
  nohup .venv/bin/wayhintd -v >>"${XDG_RUNTIME_DIR:-/tmp}/wayhint.log" 2>&1 & disown
```

- The pid comes from `wayhint ping`. Don't use `pkill -f wayhintd`, since **it also matches the
  shell running this very line**.
- If the daemon isn't running, `wayhint: wayhintd is not running …` is printed, but it starts
  anyway.
- It waits for the previous daemon to clean up its socket before starting (without waiting, it
  would exit with `wayhintd already running`).
- Logs are appended to `$XDG_RUNTIME_DIR/wayhint.log` and disappear on logout.

## Update

```sh
cd ~/work/tools/wayhint
git pull
./scripts/setup                 # reinstalls Python dependencies if they changed
.venv/bin/pip install -e .
```

Then [restart](#restarting) the daemon. Your `~/.config/wayhint/` config and sheets are left
untouched. If the config or sheet format changed in the new version, `wayhint validate` will tell
you.

## Uninstall

Undo these in order. wayhint never does any of this automatically.

1. Stop the daemon ([Starting and stopping the daemon](#starting-and-stopping-the-daemon)).
2. Remove the three hotkey lines and the autostart line from the compositor's config (for labwc,
   run `labwc --reconfigure`).
3. Undo the terminal setup (if you used `./scripts/setup-terminals --apply`):
   - Remove the `~/.local/bin/<terminal>-wayhint` wrapper
   - Remove `~/.local/share/applications/<terminal>.desktop` (falls back to the system
     `.desktop`)
   - Restore any rewritten bar or compositor config from the
     `<filename>.wayhint-backup-<timestamp>` in the same directory (or revert the wrapper line to
     the original command)
4. Remove config and state: `~/.config/wayhint/` (this includes your sheets; back them up first
   if you want to keep them) and `~/.local/state/wayhint/`.
5. Remove the `wayhint` and `wayhintd` links in `~/.local/bin/`, and remove the repository
   (`~/work/tools/wayhint/`).

## Troubleshooting

| Symptom | What to check |
|---|---|
| `wayhint: wayhintd is not running` | Start `wayhintd -v` in the foreground and check the logs. The socket is `$XDG_RUNTIME_DIR/wayhint.sock` |
| `⚠ compositor does not provide wlr-foreign-toplevel-management` | Never happens on labwc. On Wayfire, add `foreign-toplevel` to `[core] plugins`, or `ipc` to hand it off to IPC |
| `⚠ Wayfire IPC unavailable` | Only when `context.backend: wayfire` is pinned. Check `echo $WAYFIRE_SOCKET` and `ipc` in `[core] plugins` |
| `this Wayland session has no layer-shell support` | Check whether `gir1.2-gtk4layershell-1.0` is installed. Does not work under X11 / Xwayland |
| Hints are missing / disappeared | Check whether a filter is still active via the chip above the list. Clear it with the chip's `×`. Filters are saved per sheet, so it can look broken when you're really just looking at a different sheet |
| Hints from a parent sheet or `include` aren't mixing in | See [When a hint that should be mixed in doesn't show up](#when-a-hint-that-should-be-mixed-in-doesnt-show-up). Use `wayhint inspect` or `wayhint context --shown` to see which filter dropped it |
| "Edit in editor" doesn't open an editor | Check whether the first command in `config.yaml`'s `editor.command` is on PATH. For an editor that runs inside a terminal (vim, etc.), write it as launching the whole terminal (`[foot, -e, nvim, "+{line}", "{file}"]`). The reason is in `wayhintd -v`'s logs |
| Nothing shows when a hotkey is pressed | Check whether the daemon is running with `wayhint ping`. If it's stopped, [restart it](#restarting) |
| The sheet for a command inside a terminal doesn't show up | Check `chain` and `process` from `wayhint context` (see "Reading" above). If there are multiple windows, check whether they follow the [Multiple terminal windows](#multiple-terminal-windows) convention |
| Only the parent sheet shows up inside Herdr | Match `foreground_processes` from `herdr pane process-info --pane <focused pane id>` against `argv_regex` |
| Hints don't change when switching tabs in Herdr | Check `focused` and `pane_id` from `herdr pane current` |
| Japanese (IME) input doesn't work in the search box or edit form | GTK hasn't picked native Wayland input (text-input-v3). If `gsettings get org.gnome.desktop.interface gtk-im-module` isn't empty, run `gsettings reset org.gnome.desktop.interface gtk-im-module`. Also make sure `GTK_IM_MODULE` is unset. To check, look for `zwp_text_input_v3.enter` and `enable` in the output of `GTK_IM_MODULE= WAYLAND_DEBUG=1 wayhintd` |
| Keyboard input doesn't return to the original app after search | If there are multiple windows with the same app_id and the title also changed, wayhint can't decide where to return focus. Check for `could not return focus` in `wayhintd -v` |
