# common — what wayhint can do

[日本語](01_common_storyboard.ja.md)

- Format: screen recording + captions only (silent or BGM). No narration
- **One of four videos**. This showcase covers only the product's common features; **how** a
  context is found is each of `herdr` / `terminal` / `gui`'s job, one path apiece
- Has **4 variants**, split by content (DECISIONS 0042). Each stands on its own and starts with
  Herdr and Claude Code starting up. There is no shorter-length variant with the same content
  - `overview` — what the tool is for, always the same place, follows what is running (lead 1)
  - `search` — does not steal focus, search and copy (lead 2)
  - `edit` — write it down right there, breaks and recovers (lead 3)
  - `sheets` — how to write a sheet, what it does not do
- A single video across all of it will be made in `demo/showcases/all/` (not yet started). It
  will combine these 4 common behaviors with scenes from the three detection-path videos, one
  per app kind
- The three lead scenes (shown in this order)
  1. **Follows what is running inside a terminal, switching by itself**
  2. **Does not steal focus, so work continues with it on screen**
  3. **Adds a forgotten command right there, growing the list**
- Notation: hotkeys follow the real machine's bindings — `Super+H` (toggle) /
  `Super+Ctrl+H` (edit mode) / `Super+Shift+H` (search mode)

---

## 0. Before recording

> Not recorded by hand — generated from the neighboring `02_common_scenario.yaml` with
> `./scripts/demo --showcase common --record` (DECISIONS 0032). The hint sheets are
> `demo/fixtures/hints/en/`, the terminal and Herdr setup are `demo/fixtures/` and
> `tools/demo/session.py`, and recording happens inside a headless compositor. **The seconds and
> captions in the table below are kept in sync with what is actually generated** (a person keeps
> them in sync; `demo/README.md`'s "Writing captions" rule 9). Scenes that cannot be shot (a
> browser, zooming, mouse operation, a logo screen) are listed with reasons in `demo/README.md`'s
> "Scenes dropped from the script".

### Environment

- Recording happens inside its own headless compositor. The session currently in use is not
  touched
- Apps shown: Herdr + stubs of Claude Code / Codex, a vi stub
- **Not shown**: real code, conversation content, a username from a home path
- Claude Code / Codex are stopped at their idle screen right after startup (being stubs, no
  conversation happens)

### Why record inside Herdr

This showcase's subject is the **common features**, and Herdr is only the stage. A stage still
has to be picked, and Herdr — where switching a pane alone changes "what is running inside" —
shows this in the fewest steps. How it gets there — asking Herdr, reading `/proc`, choosing by
app_id — is each of `herdr` / `terminal` / `gui`'s job, and is not explained here.

### The hint sheets (`demo/fixtures/hints/en/`)

- `herdr.yaml` / `claude-code.yaml` / `codex.yaml` — copies of the real machine's
  `~/.config/wayhint/hints/ja/` (2026-09-24), translated. The exception is `claude-code.yaml`'s
  English comment on line 1, dropped from the copy because it shows on screen in sheets' vi
  scene. Herdr 6 entries, Claude Code 7, Codex 1. Nothing narrows by tag anywhere, so the
  child's list mixes in all of Herdr's hints (DECISIONS 0034). There is no `favorite`, so no ★
  shows
- `wm.yaml` — no `match`, 2 entries. `config.yaml` has `include: [wm]`
- `vi.yaml` — for the scene in sheets that opens a YAML file. `notes.yaml` / `less.yaml` are
  used by other showcases
- The hint added on the fly during recording is "Toggle permission mode / `Shift+Tab`" (edit).
  It sits next to the selected Claude Code hint, so it goes into Claude Code's sheet

## 1. overview
<!-- variant: overview -->

16:9, real-time pacing. 78 seconds total.

### §1 The problem (0:00–0:18)

| sec | screen | caption |
|---|---|---|
| 0–3 | Herdr's window | Claude Code, running inside Herdr |
| 3–8 | Claude Code starts up | Forget a shortcut, and it's another web search |
| 8–13 | Same screen | And what you looked up is gone again |
| 13–18 | Same screen | What you want: hints for what's running right now |

### §2 Always the same place (0:18–0:32)

All three screens are the same (the overlay stays open). Kept short enough to read.

| sec | screen | caption |
|---|---|---|
| 18–24 | `Super+H`. The overlay appears top-right | One hotkey for the focused window's hints. Position is configurable |
| 24–28 | The list (key on the left, title and command in the middle, category on the right) | Key on the left, description (or command) in the middle, category on the right |
| 28–32 | The selected row's detail shows below | Extra detail shows below |

### §3 Lead 1: follows what is running (0:32–0:58)

| sec | screen | caption |
|---|---|---|
| 32–37 | Header reads `Herdr › Claude Code` | It follows the frontmost process, not the window |
| 37–42 | A new tab → Codex | (no caption) |
| 42–50 | `Super+H` → swaps to `Herdr › Codex` | Press again in another tab and it swaps without closing |
| 50–58 | Herdr's hints (scroll, tab, paste) mix into the list | Shows hints for the whole process chain, Herdr's own included |

### §4 Close (0:58–1:18)

| sec | screen | caption |
|---|---|---|
| 58–64 | `Super+H` closes it | The moment you forget, it is right where you look |
| 64–72 | Same screen | Not doing: running commands, AI generation, or reading the screen |
| 72–78 | Same screen | Wayland (labwc) / GTK4 / hints in YAML |

## 2. search
<!-- variant: search -->

16:9. 68 seconds total. The copy scene is shot in Claude Code's pane. What gets copied is
`copy`, or `command` alone when there is none (DECISIONS 0039), and the Codex and Herdr sheets
have only keys.

### §1 Does not steal focus (0:00–0:16)

| sec | screen | caption |
|---|---|---|
| 0–3 | Claude Code starts up inside Herdr | (no caption) |
| 3–7 | `Super+H` → `Herdr › Claude Code` | Find a hint and use it right there |
| 7–15 | With the overlay open, `write tests` is typed into the terminal (ASCII: full-width would make `Ctrl+U` erase the prompt too) | Keep typing with the overlay on screen |
| 15–16 | `Ctrl+U` erases the terminal line | (no caption) |

### §2 Search and copy (0:16–0:43.5)

| sec | screen | caption |
|---|---|---|
| 16–18.5 | `Super+Shift+H` → the search box opens, the key typed so far shows below | Search is Super+Shift+H |
| 18.5–25.5 | `session` (a category) typed in the search box → the list narrows to 3 (`/model` `/compact` `/clear`) | Keyboard input switches over only when search starts |
| 25.5–30 | `↓` → moves into the list, `/model` selected first. Below: `c copy and leave · Enter/Esc leave …` | ↓ moves into the list. Keys shown below |
| 30–33.5 | `↓` → moves to `/compact`. The detail below changes to compact's description | In the list, ↑↓ selects a hint |
| 33.5–38 | `c` → copies `/compact` and leaves search. The list is still 3, a chip appears | c copies the selected hint's command and returns to the window |
| 38–43.5 | `Ctrl+Shift+V` → `/compact` is pasted into the terminal. The list stays narrowed | The filter stays, and typing goes back to the window |

### §3 The filter is per sheet (0:43.5–1:07.5)

| sec | screen | caption |
|---|---|---|
| 43.5–49.5 | A new tab → `Super+H` shows Herdr's sheet. All 8 entries, no chip | A different sheet is not filtered |
| 49.5–55.5 | Back to the first tab, `Super+H` → Claude Code is still 3 entries, chip still there | Come back, and the filter is still there |
| 55.5–61.5 | Chip's `×` → the list returns to all entries | The filter is per sheet. Clear it with × or an empty search box |
| 61.5–67.5 | `Super+H` closes it | The moment you forget, it is right where you look |

## 3. edit
<!-- variant: edit -->

16:9. 52 seconds total. The hint added on the fly during recording is "Toggle permission mode /
`Shift+Tab`" (a Claude Code operation). What gets broken is the `]` on line 5 of `herdr.yaml`
(`broken/en/herdr.yaml` is the fixture with just that one change). Breaking the Claude Code
sheet would also drop the hint just added when it is fixed, so the Herdr sheet mixed into the
same list is broken instead.

### §1 Write it down right there (0:00–0:31)

| sec | screen | caption |
|---|---|---|
| 0–3 | Claude Code starts up inside Herdr | (no caption) |
| 3–7 | `Super+H` → `Herdr › Claude Code` | Missing a hint? Add it yourself |
| 7–12 | `Super+Ctrl+H`. Edit mode's key list shows below | Forgot something? Write it down right there |
| 12–16 | `a` → a form. Heading reads "New hint → Claude Code" | It is added to the same sheet as the selected hint |
| 16–23.6 | Title "Toggle permission mode" → Tab → key `Shift+Tab` | (no caption) |
| 23.6–30.6 | Enter. A new row appears in the list | Enter saves it and edit mode ends |

### §2 Breaks and recovers (0:31–0:52)

| sec | screen | caption |
|---|---|---|
| 30.6–37.6 | Opening `herdr.yaml` in vi shows line 5 missing its `]`. The overlay reads `⚠ YAML error`, the list stays | Break it by hand, and the last good content stays |
| 37.6–45.6 | vi closes, it is fixed → `⚠` goes away | Fix it and it recovers right away. No restart needed |
| 45.6–51.6 | `Super+H` closes it | The moment you forget, it is right where you look |

## 4. sheets
<!-- variant: sheets -->

16:9. 58 seconds total. The vi stub really opens the sheet given as its argument. The `match`
the caption points to sits on that line on screen; `include` and the language sit in
`config.yaml`'s `include: [wm]` and `appearance.language: en`. Neither file has a comment at its
top, so both fit within their first 14 lines. Narrowing by process chain (`nested`) is the
`herdr` showcase's job.

### §1 How to write a sheet (0:00–0:26)

| sec | screen | caption |
|---|---|---|
| 0–3 | Claude Code starts up inside Herdr | (no caption) |
| 3–10 | Opens `hints/en/claude-code.yaml` in vi | One sheet is one app, one YAML |
| 10–18 | Same screen (the `match:` line) | match decides which window or process it shows for |
| 18–26 | vi closes, `Super+H` → `Herdr › Claude Code`'s list | The sheet matched by match shows its hints |

### §2 Common hints and language (0:26–0:51)

| sec | screen | caption |
|---|---|---|
| 26–34 | Opens `config.yaml` in vi. `include: [wm]` is visible. The overlay stays open | config.yaml's include mixes common hints into every sheet |
| 34–42 | Same screen (`language: en`, and the overlay's English UI) | Hints are per language, the same one as the UI |
| 42–51 | vi closes, a new tab, `Super+H` → Herdr's 8 entries. wm's `Alt+Tab` and `Super+Ctrl+H` at the end | Common hints line up at the end of every sheet |

### §3 Close (0:51–0:58)

| sec | screen | caption |
|---|---|---|
| 51–58 | `Super+H` closes it | Wayland (labwc) / GTK4 / hints in YAML |

## 2. Notes on caption writing

The rule is `demo/README.md`'s "Writing captions", which is canonical. What this one follows is
its rule 7 — the headline captions of the three lead scenes; other showcases touching the same
scene use the same wording.

- It follows the frontmost process, not the window
- Keep typing with the overlay on screen
- Forgot something? Write it down right there

## 3. After recording, check

- [ ] no username, real code, or conversation content is on screen
- [ ] no row is cut off in `contact-sheet.png`
- [ ] the hint added on the fly during recording is not left in the fixtures (writing to the
      session's copy should leave none)
- [ ] the caption band (the values in `demo/README.md`'s "caption band" table) does not overlap
      the window or the overlay
