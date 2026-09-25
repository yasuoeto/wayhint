# SHEET-FORMAT — writing hint sheets

[日本語](SHEET-FORMAT.ja.md)

A hint sheet (sheet, below) is a YAML file that collects the hints for one app or command. One
file is one sheet. How to write your first sheet is covered in the README, "Writing hints"; how
sheets are chosen and mixed is covered in [`SHEETS.md`](SHEETS.md). This document collects every
item a sheet can have, and the rules for each.

## Where files live, and their names

- Location: `~/.config/wayhint/hints/<language>/` (`hints/ja/` for Japanese). The search order is
  `hints/<language>/` → `hints/en/` → directly under `hints/`; only the first directory found is
  read.
- Extension is `.yaml` or `.yml`. Files are read in filename order.
- **The filename (minus the extension) must match the sheet's `id`.** A mismatched file is not
  loaded, and the reason shows up both in the overlay's `⚠` and in `wayhint validate`
  (`claude-backup.yaml` claiming `id: claude` does not take effect twice).
- On save, the daemon reloads it automatically.

## Overall shape

```yaml
version: 1                      # Optional. Write 1 if you write it at all
id: claude-code                 # Required. Same as the filename
title: Claude Code              # Required
priority: 0                     # Optional. When several sheets match, the higher one is chosen
match:                          # Optional. A sheet without this never appears on its own
  wayland:
    app_id_regex: ["^foot$"]
  process:
    argv_regex: ["^claude$"]
    cmdline_regex: ["claude .*--resume"]
include:                        # Optional. Sheets mixed into this list
  - wm                          #   an id alone mixes in all of it
  - {sheet: git, categories: [basics]}   # {sheet, tags, categories} mixes in only part
display: {anchor: top-left}     # Optional. Overrides the overlay's position/size only while this sheet is shown
inherit: {parent_tags: [pane]}  # Optional. When shown as a child, restricts the parent's hints (parent_categories also works)
nested: {export_tags: [pane]}   # Optional. When shown as a parent, restricts the hints handed to the child (export_categories also works)
hints:                          # List of hints
  - id: resume
    title: Resume a previous conversation
    command: claude --resume
    category: Starting up
```

An unknown key is an error (so a typo is never silently ignored).

## Sheet-level items

| key | required | value | meaning |
|---|---|---|---|
| `version` | | `1` | The format version. Defaults to 1 |
| `id` | ✓ | starts with an alphanumeric, then alphanumerics and `.` `_` `-` | The sheet's name. Make it match the filename. Unique across all sheets |
| `title` | ✓ | string | The sheet's heading |
| `priority` | | integer (default 0) | When several sheets match, the higher one is chosen |
| `match` | | see "match" below | Which windows or commands it is shown for |
| `include` | | a list of sheet ids or `{sheet, tags, categories}` | Sheets mixed in at the end of this list. Using a map mixes in only hints with that tag or category. If omitted, falls back to `config.yaml`'s `include`. `[]` mixes in nothing |
| `display` | | `anchor` `width` `height` `margin` `output` | Overrides the overlay's position/size only while this sheet is shown. Written the same way as `overlay` in [`CONFIG.md`](CONFIG.md) |
| `inherit.parent_tags` / `inherit.parent_categories` | | a list of tags / categories | When this sheet is chosen as a child, restricts the parent's hints by this |
| `nested.export_tags` / `nested.export_categories` | | a list of tags / categories | When this sheet becomes a parent, restricts which hints are handed to the child's list. If omitted, all are handed over |
| `hints` | | a list of hints | See "Hint-level items" below |

If both tags and categories are written, a hint matching either one counts (OR). `[]` means zero,
regardless of the other side. How `include`, `inherit`, and `nested` relate is diagrammed in
[`SHEETS.md`](SHEETS.md).

## match

| key | what it matches against |
|---|---|
| `wayland.app_id_regex` | The focused window's app_id (writing `wayfire.app_id_regex` has the same effect) |
| `process.argv_regex` | The name of the command running inside a terminal or Herdr, each of its arguments, and the filename part of a path argument |
| `process.cmdline_regex` | That command's whole line |

- All of these are lists of Python regular expressions, matched as a **substring**. Wrap with
  `^...$` to match the whole thing.
- `argv_regex` matches arguments as well as the name, so a command run through another program,
  like `node /path/to/codex`, is still matched by `^codex$`.
- One pattern counts as 1 regardless of how many times it matched. A sheet with more matched
  patterns is preferred (before that comes `priority`, and finally filename order).
- A window whose app_id has a `.p<number>` suffix (README, "Multiple windows of a terminal") is
  also matched by the name with the suffix stripped. Writing `^foot$` also matches `foot.p12345`.
- Only the first 4096 characters of an app_id, an argument or a command line are matched: the
  program sets them, and a slow pattern must not hold up the overlay. Past that, `$` no longer
  matches.

```yaml
match:
  wayland: {app_id_regex: ["^org\\.inkscape\\.Inkscape$"]}    # a GUI app
```

```yaml
match:
  process: {argv_regex: ["^vi$", "^vim$", "^nvim$"]}           # a command inside a terminal
```

## Hint-level items

| key | required | value | meaning |
|---|---|---|---|
| `id` | ✓ | same shape as a sheet's `id` | A name unique within the sheet. Not shown in the overlay |
| `title` | ✓ | string | The description shown in the list |
| `kind` | | `shortcut` (default) `command` `tip` `note` | The kind. See "kind" below |
| `key` | | string | The key operation shown at the left edge of the list (e.g. `Ctrl-o`). Long ones wrap; a line break written in the YAML is kept as-is |
| `command` | | string | The command shown below the title. **Never executed.** Display and copy only |
| `category` | | string | The heading shown at the right edge of the list. Hints with the same category sit next to each other. If omitted, falls into a pseudo-category (`inbox`; `未定義` in the Japanese UI) |
| `tags` | | a list of strings | Used to restrict what mixes in from a parent sheet or `include`. Also searchable |
| `favorite` | | `true` / `false` (default) | `true` marks it with `★` and moves it to the front of the list |
| `copy` | | string | Write only when the copied text should differ from what is shown. When it does, the detail pane shows it, with control characters such as a newline written out (`\n`) |
| `remark` | | string | Extra text shown only when the row is selected |
| `source` | | string | Where it came from (e.g. a URL to official documentation) |
| `learned` | | a date | The date it was learned. Written like `2026-09-24` |

- Writing only digits in `key` or `command` (e.g. `key: 5`) still treats it as a string.
- What gets copied is `copy`, or `command` if there is no `copy`. A hint that has only `key` is not
  copied (a key is pressed, not pasted).
- Two hints with the same `id` inside the same sheet is an error. The same `id` can be reused
  across different sheets.

### kind

| kind | use it for | how it shows up in the list |
|---|---|---|
| `shortcut` | A key operation. Normally you write `key` | Shows the `key` and `command` you wrote |
| `command` | A command. Normally you write `command` | Same as above |
| `tip` | A note that has both a key operation and a command | Same as above |
| `note` | A note that is text only | `key` and `command` are not shown even if written |

`kind` itself never appears in the overlay and is never used for filtering. When hand-writing
YAML, you can write `key` and `command` regardless of `kind`, but edit mode's form and the CLI
only accept the fields that match `kind` (`shortcut` → key, `command` → command, `tip` → both,
`note` → neither).

## Ordering

The list's order is decided in this order:

1. Hints with `favorite: true`, in the order written in the sheet (category is ignored).
2. Everything else, grouped by category, categories in the order they first appear, and within
   the same category, in the order written.

To change the order, rearrange the hints in the YAML. Edit mode's `J` / `K` do the same thing. For
where hints mixed in from a parent sheet or `include` land, see [`SHEETS.md`](SHEETS.md) §2.

## When there is a mistake

- If a sheet has even one mistake, that sheet is not loaded. If it loaded correctly before, its
  **previous content keeps showing**, and the overlay shows `⚠ YAML error file:line: message` at
  the top.
- `wayhint validate` checks every sheet and `config.yaml`. If there is a mistake, it exits 1.
- Writing a sheet id in `include` that cannot be resolved is only a warning; the sheet is still
  shown (and `validate` also exits 0).
- While the sheet being shown is broken, you cannot enter edit mode (so the broken file is not
  overwritten).
- A sheet or `config.yaml` larger than 1 MiB is not read; it is reported as a mistake.

## When the overlay or the CLI writes it

When edit mode or `wayhint add` and the like write a hint, they line it up in this shape. When you
write it yourself, you don't have to follow this; the order and omission of keys is up to you.

- The hint's 12 items, in the order `id` `title` `kind` `key` `command` `category` `tags`
  `favorite` `copy` `remark` `source` `learned`, with items not written left empty (as in
  `key:` with no value).
- `wayhint format [PATH...]` reshapes a hand-written sheet into the same form.
- Pressing `a` in edit mode, when no sheet yet matches, creates a new sheet. Its filename is the
  app or command's name, and its `match` is filled in automatically to match the current window
  (or, inside a terminal, the command running in it).
- A sheet that is a symlink (into a dotfiles repository, say) stays one: the file it points to is
  rewritten.

## Editor completion

Running `wayhint schema --write` writes out the sheet's JSON Schema; placing this one line at the
top of a sheet enables key completion and validation in an editor that supports
yaml-language-server (configured under `editor` in [`CONFIG.md`](CONFIG.md)).

```yaml
# yaml-language-server: $schema=/home/USER/.config/wayhint/schema.json
```
