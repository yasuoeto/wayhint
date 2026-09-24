# demo — generate the showcase videos from a scenario

[日本語](README.ja.md)

Recording the screen by hand gives different hint content, timing, and window placement every
time, and fixing a feature means re-recording. Build the video from the scenarios kept here
instead: **on the same machine you get frame-identical output every time.** The design reasons
are in `dev-docs/DECISIONS.md` 0031 (how generation works) and 0032 (showcase and Herdr).

```sh
./scripts/demo                                    # list showcases. Does not record
./scripts/demo --showcase herdr                   # planned length and steps. Does not record
./scripts/demo --showcase herdr --validate        # validate the scenario only. exit 1 if broken
./scripts/demo --showcase herdr --record          # record all variants → out/ja/<variant>/
./scripts/demo --showcase herdr --variant 60s --record
./scripts/demo --showcase herdr --record --out-dir ~/videos/wayhint   # output elsewhere
```

Dependencies (recording only): `ffmpeg` `grim` `imagemagick` `foot` `labwc` `wtype`,
`fonts-noto-cjk` `fonts-noto-mono`, and `herdr` if the showcase uses Herdr. If any are missing,
**it prints the apt package name and stops.** `wtype` is only needed for scenarios that use
`key:` / `type:`. `./scripts/check` does not depend on any of these.

Recording brings up a compositor of its own, headless, and does the recording inside it. Nothing
appears on screen, and it touches neither the session you are using nor `~/.config/wayhint/` nor
`~/.config/herdr/`.

## showcase

One video is one showcase, self-contained under `demo/showcases/<name>/`. **The showcase's true
identity is the directory name**; the files inside it are found by the role at the end of their
name.

```
demo/
  fixtures/                       shared by every showcase (config.yaml, style.css, foot.ini, hints/<lang>/)
  bin/                            stubs and wrappers shared by every showcase
  showcases/
    herdr/
      01_herdr_storyboard.md      storyboard. Written by a person
      02_herdr_scenario.yaml      scenario. Read by the recorder
      out/<lang>/<variant>/       generated output. Not tracked
```

Showcases that exist today:

| showcase | variant | contents |
|---|---|---|
| `herdr` / `terminal` / `gui` | `main` | 3 videos of how wayhint finds it (route): inside Herdr, inside a terminal, in a GUI app |
| `common` | `overview` / `search` / `edit` / `sheets` | common behaviors split into 4 videos by content (DECISIONS 0042) |
| `all` | `60s` / `180s` / `300s` | a through-cut of the 7 scenes above, assembled (DECISIONS 0043). **The captions live in two places** — the original showcase and here — so fix both when you change one |

The filename is `<NN>_<showcase>_<role>.<ext>`. The number is only for a human to order the
steps of the pipeline; the tooling ignores it. The role is `storyboard` (`.md`) and `scenario`
(`.yaml`). If the middle segment doesn't match the directory name, it's a **warning** (recording
still goes through even for a copy where the rename was missed); if there are two files with the
same role, it's an **error** (no way to decide which to use).

To create a new showcase, just add one directory and put a storyboard and a scenario in it.
`fixtures/` and `bin/` are shared, so add only the sheets or stubs you need.

## Storyboard and scenario: which one to edit

| What decides | Source of truth |
|---|---|
| What to convey, which scene, in what order | **`01_*_storyboard.md`** |
| The action executed, `hold`, the actual caption wording, a variant's step composition | **`02_*_scenario.yaml`** |

While tuning, adjust the caption and duration on the scenario side, and **write it back into the
storyboard once it is settled.** When the pitch itself, or the number of scenes, needs to
change, don't rewrite the storyboard on your own — discuss it first.

| What you want to fix | File to touch | How to check |
|---|---|---|
| Caption text, duration | scenario's `caption` / `hold` | `--showcase X --record --only <step>` |
| Adding/reordering scenes | scenario's `steps` / `variants` | `--showcase X` (check length) → `--record` |
| Hint content | `fixtures/hints/<lang>/` | `wayhint validate --config-dir demo/fixtures` |
| What shows in the terminal | stub under `demo/bin/` | `--record --only <that scene>` |
| The pitch itself | storyboard (needs discussion) | — |

To build the English version, add `fixtures/hints/en/` and a `caption.en` for each, then
`--lang en`. Don't touch `steps` and `variants`.

## Output

`out/<lang>/<variant>/` receives the following. `<stem>` is
`wayhint-<showcase>-<variant>.<lang>`. With `--out-dir <path>` it is emitted to
`<path>/<lang>/<variant>/` (turning `out/` into a symlink is **not allowed** — recording deletes
`<lang>/<variant>` before it starts, and that would delete whatever the link points to instead).
`--out-dir` only accepts **an empty directory or a directory this tool has written before**; a
directory that has content but is missing the `.wayhint-demo-out` marker is refused rather than
deleted.

| file | contents |
|---|---|
| `<stem>.mp4` | plain, no captions. For adding your own captions |
| `<stem>.sub.mp4` | captions burned in. Ready to post as-is |
| `<stem>.webm` | VP9 of the burned-in version, for pages that can't play H.264 |
| `<stem>.square.mp4` | only for variants with `square: true`. Cropped to 1:1 from the right edge (since the overlay sits top-right) |
| `<stem>.srt` | captions. **Meant to be paired with the plain mp4**, so it's always emitted separately from the burn-in |
| `contact-sheet.png` | representative frames of each step laid out in a grid. **Look at this first** |
| `steps/<NN>-<id>.png` | representative frame per step. Also usable as a still image to paste into a README |
| `frames/` | kept only with `--keep`. Numbered hard links; the actual files are the PNGs in `steps/` |
| `stills/` | `steps/` with the same captions burned in as the video. Same picture as that step's frame in `.sub.mp4` (minus only the degradation from compression) |
| `review/` | only with `--review`. Crops of steps that changed from the adopted take (see "Reviewing a re-take" below) |

## Writing the scenario

```yaml
output: {width: 1280, height: 720, fps: 30}
fonts: {ui: "Noto Sans CJK JP", mono: "Noto Sans Mono"}
windows:
  - {title: Herdr, x: 32, y: 48, width: 620, height: 580}
steps:
  - id: show-hints
    key: super+h
    wait_for: {overlay: visible, label: "Claude Code", hints: 10}
    caption: {ja: "hotkey 一発。いつも右上。"}
    hold: 7.0
variants:
  3min: {target: 160, tolerance: 30, steps: [open-herdr, show-hints, …]}
```

- `output` — the recorded size. The headless default is 1280×720; recording fails immediately
  at a different size.
- `fonts` — checked for existence with `fc-match` at startup, and used for burning in captions
  too.
- `windows` — window placement. `title` is the name referenced by `spawn` / `close`, and it's
  also the window title the compositor's `windowRules` match against. **Reproducibility
  requires a fixed position.**
- `steps` — defines every step once. Defining it here alone does not record it.
- `variants` — what actually gets recorded. Below.

### A variant is a complete sequence

`variants.<name>.steps` lists step ids, and **that sequence must succeed on its own, run in
order, starting from a clean session.** State is not carried over between variants; there is no
hidden setup step and no automatic dependency resolution. Any step that appears in no variant is
an error.

To use the same operation at a different length, **duplicate the step under a different id**
(`show-hints` and `show-hints-60`). There is deliberately no mechanism to override `hold` per
variant — that would make it impossible to tell what gets recorded just by reading the scenario.

| variant key | meaning |
|---|---|
| `target` | seconds derived from the storyboard's time allocation |
| `tolerance` | allowed margin. `--dry-run` exits 1 if outside `target ± tolerance` |
| `square` | if true, also emit `.square.mp4`. Added to things like the 60-second version, meant for social media |
| `steps` | the sequence of step ids |

### Step keys

| key | meaning |
|---|---|
| `id` | the step's name. Used by `--only` / `--from` and in the output filename. Must be unique |
| *action* | **exactly one** of the table below |
| `wait_for` | **required**. Recording happens once this condition is met. Default timeout is 10 seconds |
| `hold` | seconds. Multiplied by `fps` and rounded to a frame count. 0 means it doesn't appear in the video (it still remains in stills) |
| `caption` | `{ja: …}`. `ja` is required, `en` is optional (needed only when recording with `--lang en`). Up to 25 characters per screen |
| `precondition` | optional. A condition that must hold **before** the action. A safety net for `--only` |

### action

| action | how to write it | what it does |
|---|---|---|
| `spawn` | `{window: <name>, argv: [foot-herdr]}` / `{…, argv: [foot-wayhint, -e, vi]}` | launches a window. `argv[0]` is a terminal wrapper in `demo/bin` (`foot-wayhint` or `foot-herdr`). `foot-wayhint` **requires `-e <stub>`** — foot with no command opens a login shell, which is refused. `foot-herdr` launches Herdr itself, so it takes no command. The only option is `--app-id=foot-<name>`. **Names only** (no absolute paths) |
| `close` | `{window: <name>}` | closes that window. Focus returns to the window below, so you can show a different app and come back |
| `key` | `super+ctrl+h` | sends one keystroke via wtype. Modifiers: `super` `ctrl` `shift` `alt`. **Used for modified key operations (`super+h` etc.) and single special keys (`enter` `tab` `esc` `down`)**. `wtype -k` doesn't apply the shift level, so uppercase letters or symbols that need shift can't be sent this way (`key: J` and `key: shift+j` both arrive at the window as `j`; measured with labwc 0.20.2 / wtype 0.4) |
| `type` | `"a string"` or `{ja: …, en: …}` | types characters via wtype's text mode. **Use this for uppercase letters and symbols** — `type: "J"` arrives as `J`. Edit mode's `J` / `K` are also sent this way |
| `press` | `{button: search}` | presses an overlay button via AT-SPI. `search` `done` `copy` `editor` `edit` `close` `clear-filter` (the `×` on the filter chip) |
| `cli` | `refresh` | calls `wayhint <cmd>` directly (for ones with no hotkey) |
| `herdr` | `[tab, focus, "w1:t2"]` | Herdr's CLI. Limited to the allow list below |
| `write` | `{file: "hints/{lang}/herdr.yaml", text: …}` or `{…, source: "fixtures/…"}` | rewrites the fixtures working copy (to show auto-reload) |
| `pause` | `true` | does nothing. Used for **a step that only shows a caption** |

The only substitution is `{lang}`. Programs are written **by name**, and the recorder resolves
them to a path, so a string in the scenario never touches PATH resolution and is never executed
as a command (the set of actions is fixed, argv is validated, and `shell=True` is never used).

### `herdr:` allow list

Since Herdr is a real, running program, the subcommands and arguments it can be called with are
fixed. Anything outside the list makes `--validate` exit 1.

| subcommand | allowed arguments |
|---|---|
| `pane list` / `pane current` / `tab list` / `workspace list` | none |
| `pane process-info` | `--current` or `--pane <wN:pN>` |
| `pane run` | `<wN:pN> <program>`. `program` must be **the name of an executable that lives in `demo/bin`** (no `/`, no `..`, existence checked) |
| `pane split` | `--direction right\|down` (required), `--pane <wN:pN>` / `--current`, `--focus` / `--no-focus` |
| `pane focus` | `--direction left\|right\|up\|down` (required), `--pane <wN:pN>` / `--current` |
| `pane close` | `<wN:pN>` |
| `tab create` / `workspace create` | `--focus` / `--no-focus` only |
| `tab focus` | `<wN:tN>` |
| `workspace focus` | `<wN>` |
| `status` | `--json` |

`--cwd` `--env` `--label` cannot be passed from a scenario (strings that show on screen, and
where things run, are decided by the recorder). `server stop` is reserved for the recorder's own
cleanup; writing it in a scenario makes it exit 1.

### Conditions available to `wait_for` / `precondition` (all ANDed)

| condition | what it checks |
|---|---|
| `toplevel: <regex>` | the app_id of the frontmost window |
| `context: {process_name: …, active_sheet: …}` | the foreground process and sheet that `wayhint context` reports |
| `overlay: visible \| hidden` | whether the overlay is exposed to AT-SPI |
| `label: <text>` / `no_label: <text>` | text visible in the overlay. **Write UI text in the original English** (the key in `src/wayhint/i18n.py`; for `ja` the translation is matched automatically) |
| `first_hint: <text>` | whether that text is in **the first row of the list**. It's the only way to observe `J` / `K` reordering (the set of rows doesn't change) |
| `text: <text>` | **text currently in an input field**. Checks whether typing into a form or search reached the overlay. Labels don't count |
| `button: <name>` | whether that button is present (same names as `press`) |
| `hints: <n>` | number of rows visible in the list. **The way to confirm a save or a filter took effect** |
| `unchecked: "<reason>"` | declares, **in writing**, that a step can't be judged by any of the above. Clears the warning below. Fewer than 10 characters exits 1 |
| `timeout: <seconds>` | default 10 |

**Always wait on a condition right after a `press`.** An AT-SPI click is a request, not a
completion; typing right after without waiting means the characters land on the window below
instead of the overlay.

## Adding a new scene

1. Read the storyboard and check that the scene you want to add fits its pitch. If it doesn't,
   discuss the storyboard first.
2. Add a step to the scenario and put it in the `variants` sequence. If a condition is based on
   UI text, write it in the original English.
3. Check the length with `./scripts/demo --showcase X`. If it falls outside
   `target ± tolerance`, adjust `hold`.
4. Record just the one scene with
   `--record --variant <v> --only <new id> --keep` and look at the PNG in `out/.../steps/`. For a
   scene that needs prior state, list the steps it needs in `--only`.
5. Record the whole thing (`--record`). Check `contact-sheet.png` for lines that got cut off.
6. Confirm it reproduces. Record twice and compare every frame:

   ```sh
   ./scripts/demo --showcase X --variant 60s --record --keep --out-dir /tmp/take-a
   ./scripts/demo --showcase X --variant 60s --record --keep --out-dir /tmp/take-b
   seq -f '%06g' 1 <frame count> | xargs -P 8 -I{} compare -metric AE \
     /tmp/take-a/ja/60s/frames/{}.png /tmp/take-b/ja/60s/frames/{}.png null:
   ```

   `--out-dir` is used here so that **a verification recording doesn't delete the adopted `out/`**
   (recording deletes the destination before it starts).

   A difference usually means **something on screen is moving**. Already stopped: foot's cursor
   (`fixtures/foot.ini`), the overlay's caret (it waits about 8 seconds after the last keystroke
   for it to stop naturally on its own), and Herdr's workspace name and window title (below). If
   you add something new that moves, find a way to stop it.

   Two things aren't stopped. **Herdr's status glyph next to the tab** (`·` and `○`) changes
   with the time elapsed since the last output, so if the moment of recording shifts by even a
   second — say, because you added a `wait_for` — that scene alone can differ by about 15px
   (measured 2026-09-23, the 5-minute version's `wrong-hints`). It doesn't show up when both
   recordings are made under the same conditions. **The pid embedded in the terminal's app_id**
   (`demo/bin/foot-wayhint`'s `foot.p$$`) changes on every recording, producing about a 50x10px
   difference in the terminal's `context-cli` (measured 2026-09-24). This isn't stopped since
   it's the very mechanism by which wayhint finds the process inside a terminal. It's at most 7
   digits, so line wrapping doesn't change.

## Reviewing a re-take

A re-take usually changes only a handful of the several dozen steps. Instead of re-checking every
still image or contact sheet, look at **only the steps that changed from the adopted take
(`out/`)**:

```sh
./scripts/demo --showcase X --variant main --record --out-dir /tmp/take --review
```

`--review` matches the new take in `--out-dir` against the adopted take's `stills/` (with
captions) in `out/`, **by step id** (not by number, since adding a step shifts the numbers). A
caption-only change also shows up as `changed`. If the adopted take was recorded before
`stills/` existed, it isn't there, so it compares against `steps/` (no captions) instead and
prints a warning. Once the adopted take is re-recorded, it will include captions from then on.
Results go to `<out-dir>/<lang>/<variant>/review/`:

| kind | what's produced |
|---|---|
| `changed` | a PNG cropped around the changed pixels, expanded by 32px, **without shrinking** |
| `new` | a step absent from the adopted take. There's nothing to compare against, so the whole frame |
| `removed` | a step gone from the new take. Just listed |
| `same` | pixels identical. Only a count is printed, nothing written |

Once a take is done, drop `--record` and keep only `--review`. `--out-dir` is required (so the
adopted take isn't overwritten). If you decide to adopt it after looking, re-record into `out/`.

**When having an agent look, hand it only the PNGs in `review/`.** Image tokens scale with area,
and an image that stays in the conversation gets re-read on every following response. The crops
are smaller than the full frame and aren't shrunk, so a cut-off line is still readable. Tell it
what to look for (cut-off lines, captions overflowing, anything that shouldn't be on screen), let
it read the images in a separate context, and take back only the written result. `stills/` is the
same picture as each step in the video, so there's no need to watch the video itself. Frames
aren't pulled from the video for comparison, because H.264 degradation differs on every take and
would make every step look changed.

## Scenes dropped from the storyboard

Things that are in the storyboard but can't be recorded by generation. Either said instead in a
caption, or simply not shown.

| Storyboard passage | Why it was dropped |
|---|---|
| The opening browser search, footage of a hand | An external app and real-world footage. Said instead in a caption |
| Zooming on the header or the list | Generation is one still frame at a time. There's no zoom effect |
| Clicking a row → the detail pane | A mouse operation. The detail is already shown for the selected row, so it's explained in a caption |
| Resizing with the grip | A mouse operation |
| "Edit in editor" → gvim | The real gvim isn't shown. check-gui's T46b (`tests/fixtures/bin/fake-editor`) verifies everything from launch through the reload on each save. The YAML content itself is shown with the vi stub |
| labwc workspace switching | Workspace operations under headless are unverified |
| The logo/URL still screen | No way to composite it. Substituted with a `pause` caption |
| Key display (showmethekey) | Keys pressed are included in the caption instead |
| IME conversion in progress | wtype sends already-committed strings, so conversion in progress never appears |
| Moving the selected row in the list | Possible with `↑` `↓` in edit mode (since 2026-09-23), but not included in the video. Single-key operations (`f` `J` `K`) are shown only for **the first row** |

## Fixtures and stubs

`fixtures/` is copied wholesale into `/tmp/wayhint-demo/<showcase>-<lang>/config` on every
recording, and that copy is what the daemon reads. **The edit-mode scenes and the YAML-error
scene rewrite that copy**, so `fixtures/` itself never changes across recordings. The path is
fixed because the YAML-error scene shows that path in the overlay (`mkdtemp` would put a
different string in the frame every time).

Only `appearance.language` is rewritten per language. Everything else is used exactly as written,
so keep it in a state where `wayhint validate --config-dir demo/fixtures` passes. The font is
pinned on the fixtures side (`style.css` and `foot.ini` name Noto explicitly; this machine's
default sans-serif is VL Gothic).

A sheet used only partway through one showcase is not placed in `fixtures/`, but under that
showcase, and brought into the working copy with `write`'s `source` (putting it in `fixtures/`
would change even the row count in other showcases' lists). Right now there are two:
`showcases/herdr/narrowed/ja/herdr.yaml` (the fixture's `herdr.yaml` plus two lines of
`nested.export_categories`; `tests/test_demo_scenario.py` checks it hasn't drifted) and
`showcases/terminal/foot/ja/foot.yaml` (a terminal sheet for `^foot$`).

`bin/notes` is a **GUI app stub** (GTK4). It's there to show the side where the sheet is decided
by the window's `app_id` (`dev.wayhint.demo.Notes`) rather than a process inside a terminal, so
in `spawn`'s allow list it's in its own bucket, `GUI_STUBS`, separate from the terminal wrappers
(it takes no arguments). It contains only a label — no entry, no scrolled window, no animation.
Recorded twice three seconds apart and confirmed AE=0.

`vi`, `less`, `claude`, and `codex` under `bin/` are **not the real thing**. They're python
scripts that just wait on stdin; `claude` and `codex` show the screen they display right after
launch. `vi` and `less` **actually open the sheet given as an argument** and display its first 14
lines at a fixed width (`common` points at `match` / `include` and `hints/ja/` on screen, and
needs to). Back when they showed a fixed excerpt, the caption talked about lines that weren't on
screen. What they open is limited to the session's fixtures copy, whose location is passed via
`WAYHINT_DEMO_CONFIG`. `less` prints something like `<filename> (END)` on the last line and quits
on `q` — it's the second process needed to **run a different process in the same terminal**,
without which `terminal` showcase's "two windows, different processes inside" couldn't be built.
Two things matter here:

* **The filename.** wayhint finds a terminal's foreground process from `/proc` and uses the
  basename of `argv[0]` (or of `argv[1]` for an interpreter) as the name, so the script `claude`
  with `#!/usr/bin/env python3` is matched as `claude`.
* **`prctl(PR_SET_NAME)`.** The `name` Herdr reports is the kernel's `comm`, so without calling
  this, the overlay's context line would show `python3`.

**Never launch another process from inside a stub** — spawning a child like `sleep` would let
that child answer as the foreground process instead.

Only `bin/wayhint-shown` launches one child: it calls the repository's
`.venv/bin/wayhint context --shown` with a fixed argv and no shell, and prints **its real output**
below the `$ wayhint context --shown` line (so the scene where the caption talks about
`wayhint context` shows that actual output). Only after the child exits and the output is fully
written does it change `comm` to `wayhint-shown`, so the scenario can wait with
`wait_for: {context: {process_name: wayhint-shown}}` for "the output is on screen." `--shown`
doesn't re-check, so it keeps answering with the contents from when the overlay was opened even
after focus moves to the terminal window. Lines wrap on whitespace to fit the 620px window. If
`Super+H` is pressed while this window still has focus, the list gets swapped for a different
window's hotkey, so return to the original window with `close: {window: shown}` before closing.

`bin/setup-dry-run` is built the same way: it runs `./scripts/setup-terminals` with **no
arguments** (a dry run that writes nothing) against the session's disposable `$HOME`, and prints
the real output. On screen, `$HOME` is shown as `~` (the session's home is a runtime directory
whose name changes on every recording, and it's not a form a person would read as their own
path). A dry run exits 1 if anything remains to be done, so up to 1 is treated as success; 2 or
higher stops without renaming.

`bin/herdr-launch` doesn't run a command. At launch, it reads the `sh` block under
`### Herdr` in `docs/TERMINALS.md` (the launch examples for kitty / Ghostty / foot) and prints
it, so the video and the documentation never disagree. If the block can't be found, it stops
without renaming.

`bin/foot-wayhint` is the wrapper for README's "Terminal, multiple windows" (puts its own pid in
the app_id), and `bin/foot-herdr` is for Herdr (includes `herdr` in the app_id, as
`docs/TERMINALS.md` assumes). Both read `fixtures/foot.ini`.

**Neither wrapper passes its arguments through.** They only accept `--app-id=` and `--title=`,
and `foot-wayhint` additionally requires `-e <stub>` (the stub must be one of the ones next to
it: `claude` `codex` `vi` `less` `wayhint-shown` `setup-dry-run` `herdr-launch`; a symlink is
refused). The only argument a stub can be given is **one file, from within
`WAYHINT_DEMO_CONFIG`**. Passing `"$@"` straight through to foot would let the scenario side put a
shell into a pane with `--override=shell=…` — a scenario is data, not code (the threat model in
DECISIONS 0032). The absolute path of the Herdr binary that `foot-herdr` launches is passed via
the environment variable `WAYHINT_DEMO_HERDR_BIN`. If it's unset, the wrapper doesn't launch and
exits 1 (falling back to a bare `herdr` would resolve into `demo/bin`, which is first on PATH).

## Checking storyboard and scenario for drift

The storyboard (`01_*_storyboard.md`) and the scenario (`02_*_scenario.yaml`) are **written
separately, by a person.** The scenario is not generated from the storyboard — the storyboard is
where the pitch is decided, and turning it into a generated artifact would just make it another
YAML dialect. Instead, `--validate` cross-checks only **the parts of the storyboard that are
claims about the scenario** (`tools/demo/storyboard.py`).

| What it checks | Failure condition |
|---|---|
| A table's caption | the scenario has no step with that caption / the scenario's caption is nowhere in the storyboard |
| A table's seconds | the interval of the step holding that caption falls outside that row's seconds |
| A section heading's `(m:ss–m:ss)` | doesn't match the first and last seconds of that section's table |
| `Total N seconds` | drifted by 1 second or more from the variant's actual length |

Which variant a section refers to is marked by `<!-- variant: 60s -->` right after the `##`
heading (it can't be guessed from a freely-written heading). Sections without a table, and
explanatory sections like `### Environment`, are ignored.

**Warnings** are also produced (non-fatal): a step whose `wait_for` only checks that "the overlay
is showing," or one with the same condition as the previous step. The 3 steps in B-7 where `f` /
`J` / `K` leaked to the terminal instead of reaching the overlay slipped past exactly this and
got recorded as all 3, intact. `pause:` is exempt, since its job is to not change the screen; for
a step with the same issue, write `unchecked: "<reason>"` in its `wait_for` (giving a reason is
the requirement — some steps, like one where characters merely appear in a terminal, leave
nothing the daemon can be asked about).

`./scripts/check`'s test runs the same check against the real showcases, so committing with
drift still in place makes it fail.

## Writing captions

All 4 showcases follow the same convention. The wording itself is defined by the scenario's
`caption`; the storyboard's table is a copy of it (see rule 9).

1. About 20 characters per screen, up to 2 lines. Shown right **before** the action happens, kept
   up throughout the action
2. No closing punctuation mark at the end. Either `。` or `、` may be used as an in-sentence break
3. Product terms are written in Japanese: `hint` → 「ヒント」, `sheet` → 「シート」,
   `pane` → 「ペイン」, `focus` → 「フォーカス」, `editor` → 「エディタ」, `overlay` → 「ヒント画面」,
   窓 (window) → 「ウィンドウ」 (changed from the Latin spelling on 2026-09-24; everything from
   「ヒント画面」 on was added to match the README). `hotkey` and `context` stay in Latin script.
   Command names, arguments, and YAML keys are never changed
4. Keys, commands, filenames, and YAML keys get a half-width space on either side (e.g. 「Enter
   で保存」 — "save with Enter", 「match に名前を書く」 — "write a name under `match`").
   **Never put a backtick inside a caption** — the burn-in uses one typeface, so the character
   would show up literally on screen. Monospace is reserved for the storyboard's own prose and
   for this README
5. 「窓」 (a more colloquial word for "window") is never used in captions. A focused toplevel is
   called 「ウィンドウ」; when contrasting the container against what's inside it, it's still
   「ウィンドウ」 versus 「一番前のプロセス」 ("the frontmost process"). 「窓」 may only be used in
   the storyboard's `画面` (screen) column, which is internal notes
6. Parent/child are written as **a relationship between processes (context)**. 「親シート」
   ("parent sheet"), 「子シート」 ("child sheet"), 「親子シート」 ("parent-child sheet") are not
   used — those are implementation terms (they survive in `dev-docs/DESIGN.md` as shorthand for
   the sheet of a `parent_context`). Example: 「親子関係にあるプロセスのヒントを同時に表示する」
   ("show hints for processes in a parent-child relationship at the same time")
7. The three headline scenes have these three fixed captions. When another showcase touches the
   same scene, it uses the same wording. The English version is translated from these three
   plus the closing statement of principle:
   - 「見ているのはウィンドウではなく、一番前のプロセス」 ("What it looks at isn't the window,
     but the frontmost process")
   - 「ヒント画面を出したまま、そのまま入力できる」 ("You can keep typing with the overlay still
     showing")
   - 「忘れていた操作を見つけたら、その場で書く」 ("Found an operation you'd forgotten? Write it
     down right there")
8. The three "how wayhint finds it" videos (`herdr` / `terminal` / `gui`) share one closing
   caption: 「Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる」 ("Inside
   Herdr, inside a terminal, or in a GUI — wherever it's running, the hints switch
   automatically")
9. A table's seconds in the storyboard and the caption stay in sync with the scenario. **Keeping
   them in sync is a person's job** — when a caption changes, fix it in the storyboard and in
   `02_*_scenario.yaml`'s `caption` in the same commit. Committing with drift still in place
   makes `--validate` and `./scripts/check` fail (see "Checking storyboard and scenario for
   drift"), but fixing what fails is still up to the person

Changing even one caption means that showcase needs a **re-take** (burning in happens after
recording, but the `.sub.mp4` and the frames all have to be remade too).

### English captions

The rules above are for the Japanese captions. The English ones (`caption.en`, recorded with
`--lang en`) follow these:

1. Short and plain, one line where possible (about 45 characters), never more than two. No
   trailing period, no backticks. Commands, keys, file names and YAML keys as they are.
2. Product terms: hint, sheet, the overlay, tab (Herdr's tab), window, terminal.
3. The same Japanese caption has the same English caption everywhere, including in `all`.
4. The three lead captions and the closing line of the three finding videos are fixed:
   "It follows the frontmost process, not the window", "Keep typing with the overlay on
   screen", "Forgot something? Write it down right there", and "In Herdr, in a terminal or in
   a GUI app, the hints switch by themselves".
5. An English storyboard writes "(no caption)" where the Japanese one writes 「(字幕なし)」.

## Caption band

Captions are burned in by ffmpeg after recording (`tools/demo/encode.py`). **The band's row is
reserved by the layout** — at 720p:

| | y |
|---|---|
| Top of the band (`caption_band_top`) | **638** |
| Top of the text (`caption_text_top`) | 652 |
| Bottom of the band (measured for 1 line) | 692 |
| Lowest edge windows/the overlay may use | **634** (3px above the band) |

Windows are kept above the band via the scenario's `windows` `height`, and the overlay via
`overlay.height` in `fixtures/config.yaml`. Measured, a window's bottom edge sits at 624 and the
overlay's at 628 — both leave more than 10px of clearance. **Rather than making the band opaque
to hide overlap, it's placed so nothing overlaps** — a translucent band with an app's edge
showing through underneath would look the same as a caption cutting into a window.

Captions must be **one line**. `drawtext` doesn't wrap, so it stays on one line unless a newline
is written into it (a one-line band is 55px). Two lines would push the box about 6px past the
bottom edge; if that's ever needed, `caption_text_top` has to move up, and the overlay's height
has to come down to match.

## Isolating Herdr

The `herdr` showcase **runs the real Herdr** (DECISIONS 0032). The binary used is resolved from
PATH exactly once, at the start of recording (on this machine, `~/.local/bin/herdr`, 0.8.2), and
called by that absolute path from then on — since `demo/bin` sits first in the session's PATH,
calling it by name the whole time could get it swapped for whatever's placed there.

A minimal `config.toml` is written to a session-specific `XDG_CONFIG_HOME` on every recording
(`HERDR_CONFIG` in `tools/demo/session.py`). Settings in effect, and why:

| setting | reason |
|---|---|
| `onboarding = false` | don't show the first-run onboarding screen |
| `[theme] name = "catppuccin"` | without this it asks for a theme choice on first run, and that would show up in the recording |
| `[update] version_check = false` | stops the version check against herdr.dev (network reachability) |
| `[update] manifest_check = false` | stops fetching the agent-detection manifest from herdr.dev. **Prevents network reachability, and at the same time** prevents the non-determinism where the agent detection result depends on whether the fetch happened. The session's state is empty, so the bundled version is used |
| `[ui] prompt_new_tab_name = false` | lets `tab create` skip asking for a name (generated names `1` `2` are used instead) |
| `[ui] window_title = "{workspace}"` | the default is `"{hostname}: {workspace}"`, and **the hostname would show up as the window title in every frame** |
| `[terminal] default_shell = <demo_bin>/idle` | no shell sits in a pane (below) |

**There is no shell in the session.** `default_shell` is `demo/bin/idle`, which prints one line,
reads stdin, and just `exec`s into whatever it read if the line is `claude`, `codex`, or `vi`
(a static list inside `idle`). `herdr pane run <pane> claude` is exactly that one line. Since the
scenario types characters into the terminal (the "doesn't take over the keyboard" scene), a real
shell there would let anything be run from it. During recording, `comm` values inside the session
are counted to confirm not one of them is `sh` / `bash` / `dash`.

Every `HERDR_*` variable is stripped from the session's environment. Without that, running
`./scripts/demo` from a Herdr pane would inherit `HERDR_SOCKET_PATH`, and the Herdr client inside
the session would connect to **that person's own Herdr server.**

Herdr's server daemonizes and leaves the session's process group, so `herdr server stop` is
called **before** the session is torn down. If it doesn't stop, any herdr whose `/proc/*/environ`
`HOME` matches the session's is sent SIGTERM instead (`pkill -f herdr` isn't used, since it would
catch the real user's own Herdr too).
