# CONFIG — writing config.yaml and style.css

[日本語](CONFIG.ja.md)

wayhint's overall settings go in `config.yaml`, and its look in `style.css`. How to write hints
themselves is covered in the README, "Writing hints".

## Where the files live

Under `$XDG_CONFIG_HOME/wayhint/` (default `~/.config/wayhint/`).

| File | Contents |
|---|---|
| `config.yaml` | The overlay's position and size, language, editor, sheets to mix in, and so on |
| `style.css` | Optional. Overrides the look with GTK CSS |
| `hints/<language>/*.yaml` | Hint sheets (README, "Writing hints") |

Templates live in the repository's `examples/`. `cp -r examples/. ~/.config/wayhint/` copies them
all at once.

## The basics of writing it

- Written in YAML. **Every item can be omitted.** Even with no file at all, it runs with the
  defaults below.
- An unknown section or key is an **error** (so a typo is never silently ignored).
- Check what you wrote with `wayhint validate`. If there is a problem, it prints
  `file:line: message` and exits 1.
- On save, the daemon reloads it automatically. While it is broken, it keeps running with the
  last good config, and the overlay shows the reason at the top with `⚠`.
- Resizing the overlay with the grip makes the daemon write back only `overlay.width` /
  `height`. Other lines and comments are left as they are.

## The defaults, in full

With nothing written, this is what you get. Write only the items you want to change.

```yaml
overlay:
  anchor: top-right
  width: 420px
  height: 60%
  margin: {top: 24, right: 24}
  output: null
appearance:
  style: style.css
  language: auto
  show_category: true
editor:
  command: [gvim, --remote-silent, "+{line}", "{file}"]
  schema_modeline: false
  schema_path: ~/.config/wayhint/schema.json
nested:
  parent_tags: null
  parent_categories: null
include: []
context:
  backend: auto
  workspace: current
  live_update: false
search:
  max_results: 50
logging:
  level: warning
```

## overlay — the overlay's position and size

| key | value | default | meaning |
|---|---|---|---|
| `anchor` | `top-left` `top` `top-right` `left` `center` `right` `bottom-left` `bottom` `bottom-right` | `top-right` | Where on the screen to anchor it |
| `width` / `height` | `420`, `"420px"`, `"30%"` | `420px` / `60%` | Size. `%` is a share (0-100) of the size of the destination screen (output) |
| `margin` | an integer (all sides) or `{top, right, bottom, left}` | `{top: 24, right: 24}` | Distance from the screen edge (px). A side not written is 0 |
| `output` | an output name (e.g. `eDP-1`) | none | The output to use when the destination cannot otherwise be decided |

The destination screen is decided in this order: the sheet's `display.output` → the screen the
window being looked at is on → the screen the compositor says is focused → this `output`.

```yaml
overlay:
  anchor: bottom-right
  width: 30%
  height: 500
  margin: 0          # flush against the corner of the screen
```

### Changing it per sheet

Writing the same keys under a sheet's `display:` overrides them only while that sheet is shown.
A key not written there uses the value from `config.yaml`.

```yaml
# hints/en/inkscape.yaml (match and hints omitted)
id: inkscape
title: Inkscape
display: {anchor: top-left, width: 360px}
```

## appearance — look and language

| key | value | default | meaning |
|---|---|---|---|
| `style` | a filename or path | `style.css` | The CSS to load. A relative path is taken from `~/.config/wayhint/` |
| `language` | `auto` `en` `ja` | `auto` | The text on buttons, and which hint directory is read (`hints/<language>/`). `auto` follows the machine's locale (`LC_ALL` → `LC_MESSAGES` → `LANG`); anything other than Japanese or English falls back to English |
| `show_category` | `true` `false` | `true` | Whether to show the category at the right edge of the list |

Changing `language` switches both the button text and the hints on the spot.

## editor — the editor

| key | value | default | meaning |
|---|---|---|---|
| `command` | a list of strings (argv) | `[gvim, --remote-silent, "+{line}", "{file}"]` | The command launched by "Edit in editor" |
| `schema_modeline` | `true` `false` | `false` | Whether to add a schema line at the top of newly created sheets and of `wayhint format`'s output |
| `schema_path` | a path | `~/.config/wayhint/schema.json` | The path written into the schema line. Also the default output path for `wayhint schema --write` |

`command` supports three placeholders: `{file}` (required), `{line}`, and `{hint_id}`. It launches
without going through a shell, so quoting, pipes, and environment-variable expansion cannot be
written.

```yaml
editor:
  command: [code, --goto, "{file}:{line}"]
```

```yaml
editor:
  command: [foot, -e, nvim, "+{line}", "{file}"]   # open inside a terminal
```

## nested — hints from the parent sheet

| key | value | default | meaning |
|---|---|---|---|
| `parent_tags` | a list of tags | none | Restricts, by tag, which of the parent's hints are listed in the child sheet's list |
| `parent_categories` | a list of categories | none | The same, restricted by category. If both tags and categories are written, it is OR |

**Normally you don't write this.** With nothing written, all of the parent's hints are listed; to
restrict them, write `nested.export_tags` / `export_categories` on the parent sheet instead. This
key exists for writing `[]` when you want "no parent hints mixed in at all," no matter what is
written on the other side (`[]` always means zero, regardless of what the other key says).

```yaml
nested: {parent_tags: []}   # never mix in any of the parent's hints
```

Writing a restriction here takes priority over every parent sheet's `export_*`, which means you
lose the ability to set a different restriction per parent. The full rules are in
[`SHEETS.md`](SHEETS.md) §3.

## include — sheets mixed into every sheet

| key | value | default | meaning |
|---|---|---|---|
| `include` | a list of sheet ids or `{sheet, tags, categories}` | `[]` | The sheets mixed into every sheet that does not write its own `include:`. Using a map mixes in only part of it |

Writing `include:` on a sheet **replaces** this value for that sheet (it does not add to it).

```yaml
include:
  - wm
  - {sheet: git, categories: [basics]}   # only git's "basics" category
```

The full rules are in [`SHEETS.md`](SHEETS.md) §4.

## context — how the window is examined

| key | value | default | meaning |
|---|---|---|---|
| `backend` | `auto` `wayland` `wayfire` | `auto` | How the focused window is looked up. `auto` uses the standard Wayland protocol, falling back to the Wayfire IPC if it is unavailable |
| `workspace` | `current` `all` | `current` | `current` shows the overlay only on the workspace it was opened on. `all` shows it on every workspace (only takes effect if the compositor exposes `ext-workspace-v1`) |
| `live_update` | `true` `false` | `false` | Can be written, but currently has no effect. Contents are always decided by the window at the moment the overlay was opened |

## search — search

| key | value | default | meaning |
|---|---|---|---|
| `max_results` | an integer, 1 or more | `50` | The maximum number of results shown by search |

## logging — logging

| key | value | default | meaning |
|---|---|---|---|
| `level` | `debug` `info` `warning` `error` | `warning` | How detailed the daemon's log is. Starting `wayhintd -v` prints info-level logs to the foreground |

## style.css — the look

Written in GTK4 CSS. It is layered on top of wayhint's default look, so write only the parts you
want to change. The template `examples/style.css` matches labwc's Syscrash theme's colors; it is
the fastest way to see which class names are available and how to use them.

- **Applying it requires restarting the daemon** (README, "Restarting the daemon"). Unlike
  `config.yaml` and sheets, saving it does not get reloaded automatically.
- With no file, it runs with the default look.
- To use a different name or location, change `appearance.style`.

Available class names:

| Selector | Part |
|---|---|
| `window.wayhint` | The whole overlay (background color, text color, corner radius) |
| `.wayhint-header` | The sheet name at the top |
| `.wayhint-context` | The context below the sheet name (`foot · vi · eDP-1`) |
| `.wayhint-error` | The `⚠` line |
| `.wayhint-row` | One row of the list. A favorite row also gets `.favorite` |
| `.wayhint-key` / `.wayhint-title` / `.wayhint-command` / `.wayhint-category` | The key / title / command / category parts within a row |
| `.wayhint-detail` | The detail that opens when a row is selected |
| `.wayhint-chip` | The chip showing that a filter is active |
| `.wayhint-toolbar` | The button row at the bottom (`.wayhint-toolbar button` for the buttons) |
| `.wayhint-form` / `.wayhint-form-title` / `.wayhint-form-label` / `.wayhint-form-note` | Edit mode's form |
| `.wayhint-help` | The key description shown at the bottom in edit mode |
| `.wayhint-grip-both` / `.wayhint-grip-x` / `.wayhint-grip-y` | The resize grip (corner / horizontal / vertical) |

```css
/* Example: slightly larger text, and yellow keys */
window.wayhint { font-size: 1.1em; }
.wayhint-key { color: #f9e2af; }
```
