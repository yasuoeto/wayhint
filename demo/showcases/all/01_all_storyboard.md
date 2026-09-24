# all — showing wayhint start to finish

[日本語](01_all_storyboard.ja.md)

- Format: screen recording + captions only (silent or BGM). No narration
- Combines `common`'s 4 videos' common behaviors (overview / search / edit / sheets) with
  scenes from the three detection-path videos (`herdr` / `terminal` / `gui`), one per app kind,
  into a single video (DECISIONS 0043)
- Has **3 variants** of different length (`60s` / `180s` / `300s`). Each is a complete video
  shot from a clean session, not cut from the longer one (DECISIONS 0032). The same action gets
  its own step per length (`m-` in the script is for 180 seconds, `q-` for 60 seconds)
- The scenes and captions are copied from the reviewed originals in the other four videos.
  **When a caption is fixed here, fix it in the original showcase too** (the same scene uses the
  same wording; `demo/README.md`'s "Writing captions" rules 7, 8)
- The three lead scenes (shown in this order): the frontmost process, typing with it on screen,
  writing it down right there

---

## 0. Before recording

> `./scripts/demo --showcase all --record` generates all 3. The seconds and captions in the
> table below are kept in sync with what is generated (`--validate` checks this).

- The session has Herdr. Windows for Herdr, a terminal and a GUI app open and close within the
  one video
- State carries across sections: the hint added in lead 3 makes Claude Code's list 16 entries
  from then on. Detection: `herdr.yaml`, narrowed in the Herdr section, is put back to the
  fixture at the end of that section
- The apps, stubs, and the YAML broken or narrowed are the same as the original showcases
  (`common/broken/`, `herdr/narrowed/`)
- **Not shown**: real code, conversation content, a username from a home path

## 1. 60-second cut (social media, top of the README)
<!-- variant: 60s -->

16:9 and square. Only the three lead scenes. Detection is touched on in the closing frame. 60
seconds total.

### §1 The problem (0:00–0:05)

| sec | screen | caption |
|---|---|---|
| 0–1 | Herdr's window | (no caption) |
| 1–5 | Claude Code starts up | Forget a shortcut, and it's another web search |

### §2 Always the same place (0:05–0:10)

| sec | screen | caption |
|---|---|---|
| 5–10 | `Super+H`. The overlay appears top-right (Herdr › Claude Code) | One hotkey for the focused window's hints |

### §3 Lead 1: the frontmost process (0:10–0:18)

| sec | screen | caption |
|---|---|---|
| 10–11 | A new tab | (no caption) |
| 11–12 | Codex starts up | (no caption) |
| 12–18 | `Super+H` → swaps to `Herdr › Codex` | It follows the frontmost process, not the window |

### §4 Lead 2: typing with it on screen, search and copy (0:18–0:40)

| sec | screen | caption |
|---|---|---|
| 18–19 | Back to the first tab (Claude Code) | (no caption) |
| 19–21 | `Super+H` → `Herdr › Claude Code` | (no caption) |
| 21–26 | With the overlay open, `write tests` is typed into the terminal | Keep typing with the overlay on screen |
| 26–27 | `Ctrl+U` erases the terminal line | (no caption) |
| 27–28 | `Super+Shift+H` → the search box | (no caption) |
| 28–31 | `session` typed → 3 entries | Search is Super+Shift+H |
| 31–32 | `↓` → the top of the list | (no caption) |
| 32–33.5 | `↓` → `/compact` | (no caption) |
| 33.5–36.5 | `c` → copies it and leaves search | c copies it and returns to the window |
| 36.5–39 | `Ctrl+Shift+V` → `/compact` pasted into the terminal | (no caption) |
| 39–40 | Chip's `×` → back to all entries | (no caption) |

### §5 Lead 3: write it down right there (0:40–0:54)

| sec | screen | caption |
|---|---|---|
| 40–44 | `Super+Ctrl+H`. Edit mode's key list shows below | Forgot something? Write it down right there |
| 44–45 | `a` → a form | (no caption) |
| 45–47 | Title "Toggle permission mode" | (no caption) |
| 47–47.6 | Tab | (no caption) |
| 47.6–49.6 | Key `Shift+Tab` | (no caption) |
| 49.6–53.6 | Enter. A new row in the list | Enter saves it, right into the list |

### §6 Close (0:54–1:00)

| sec | screen | caption |
|---|---|---|
| 53.6–59.6 | `Super+H` closes it | In Herdr, in a terminal or in a GUI app, the hints switch by themselves |

## 2. 180-second cut (introduction)
<!-- variant: 180s -->

16:9. The three lead scenes, plus one or two scenes each from the three detection-path videos
and how to write a sheet. 182 seconds total.

### §1 The problem (0:00–0:13)

| sec | screen | caption |
|---|---|---|
| 0–3 | Herdr's window | Claude Code, running inside Herdr |
| 3–8 | Claude Code starts up | Forget a shortcut, and it's another web search |
| 8–13 | Same screen | And what you looked up is gone again |

### §2 Always the same place (0:13–0:23)

| sec | screen | caption |
|---|---|---|
| 13–19 | `Super+H`. The overlay appears top-right (Herdr › Claude Code, 15 entries) | One hotkey for the focused window's hints. Position is configurable |
| 19–23 | The list (key on the left, title and command in the middle, category on the right) | Key on the left, description (or command) in the middle, category on the right |

### §3 Lead 1: the frontmost process (0:23–0:38)

| sec | screen | caption |
|---|---|---|
| 23–28 | Header reads `Herdr › Claude Code` | It follows the frontmost process, not the window |
| 28–29 | A new tab | (no caption) |
| 29–31 | Codex starts up | (no caption) |
| 31–38 | `Super+H` → swaps to `Herdr › Codex` | Press again in another tab and it swaps without closing |

### §4 Lead 2: typing with it on screen, search and copy (0:38–1:20)

| sec | screen | caption |
|---|---|---|
| 38–39 | Back to the first tab (Claude Code) | (no caption) |
| 39–41 | `Super+H` → `Herdr › Claude Code` | (no caption) |
| 41–48 | With the overlay open, `write tests` is typed into the terminal | Keep typing with the overlay on screen |
| 48–49 | `Ctrl+U` erases the terminal line | (no caption) |
| 49–51.5 | `Super+Shift+H` → the search box | Search is Super+Shift+H |
| 51.5–57.5 | `session` typed → 3 entries (`/model` `/compact` `/clear`) | Keyboard input switches over only when search starts |
| 57.5–61.5 | `↓` → the top of the list (`/model`). The key typed so far shows below | ↓ moves into the list. Keys shown below |
| 61.5–65 | `↓` → `/compact`. The detail below changes | In the list, ↑↓ selects a hint |
| 65–69.5 | `c` → copies `/compact` and leaves search. A chip appears | c copies the selected hint's command and returns to the window |
| 69.5–74.5 | `Ctrl+Shift+V` → `/compact` pasted into the terminal | The filter stays, and typing goes back to the window |
| 74.5–80.5 | Chip's `×` → back to all entries | The filter is per sheet. Clear it with × or an empty search box |

### §5 Lead 3: write it down right there (1:20–1:49)

| sec | screen | caption |
|---|---|---|
| 80.5–85.5 | `Super+Ctrl+H`. Edit mode's key list shows below | Forgot something? Write it down right there |
| 85.5–89.5 | `a` → a form, "New hint → Claude Code" | It is added to the same sheet as the selected hint |
| 89.5–93 | Title "Toggle permission mode" | (no caption) |
| 93–93.6 | Tab | (no caption) |
| 93.6–97.1 | Key `Shift+Tab` | (no caption) |
| 97.1–103.1 | Enter. The list is 16 entries | Enter saves it and edit mode ends |
| 103.1–109.1 | `Super+H` closes it | The moment you forget, it is right where you look |

### §6 Detection: inside Herdr (1:49–2:05)

| sec | screen | caption |
|---|---|---|
| 109.1–117.1 | A wide terminal with 3 lines of `docs/TERMINALS.md`'s Herdr launch examples | Setup: open Herdr in a terminal named herdr |
| 117.1–118.1 | The terminal window closes | (no caption) |
| 118.1–124.1 | `Super+H` → `Herdr › Claude Code` (16 entries) | Asks Herdr for the focused tab, then reads its process |
| 124.1–125.1 | `Super+H` closes it | (no caption) |

### §7 Detection: inside a terminal (2:05–2:30)

| sec | screen | caption |
|---|---|---|
| 125.1–130.1 | less is opening `wm.yaml` in a foot window | Even in a terminal with no multiplexer like herdr |
| 130.1–135.1 | A wide terminal with `$ ./scripts/setup-terminals` and the dry run's output (4 terminals) | Using it in a terminal needs one setup step |
| 135.1–141.1 | Same screen. The last line, "add --apply to write" | One command, scripts/setup-terminals. Default just checks |
| 141.1–142.1 | The terminal window closes | (no caption) |
| 142.1–148.1 | `Super+H` → Less (sub-header `foot · less`) | Shows hints for the process running in the terminal |
| 148.1–149.1 | `Super+H` closes it | (no caption) |
| 149.1–150.1 | less' window closes | (no caption) |

### §8 Detection: a GUI app (2:30–2:42)

| sec | screen | caption |
|---|---|---|
| 150.1–154.1 | Notes' window opens | The same for GUI apps |
| 154.1–160.1 | `Super+H` → Notes (sub-header is the app_id) | Each app shows its own hints |
| 160.1–161.1 | `Super+H` closes it | (no caption) |
| 161.1–162.1 | Notes' window closes | (no caption) |

### §9 How to write a sheet (2:42–2:51)

| sec | screen | caption |
|---|---|---|
| 162.1–170.1 | `hints/en/claude-code.yaml` in vi (the `match:` line) | One sheet is one app, one YAML. match decides where it shows |
| 170.1–171.1 | vi closes | (no caption) |

### §10 Close (2:51–3:02)

| sec | screen | caption |
|---|---|---|
| 171.1–177.1 | Herdr's window | In Herdr, in a terminal or in a GUI app, the hints switch by themselves |
| 177.1–182.1 | Same screen | Wayland (labwc) / GTK4 / hints in YAML |

## 3. 300-second cut (start to finish)
<!-- variant: 300s -->

16:9. common's 4 videos and the three detection-path videos, joined almost as they are. 304
seconds total.

### §1 The problem (0:00–0:18)

| sec | screen | caption |
|---|---|---|
| 0–3 | Herdr's window | Claude Code, running inside Herdr |
| 3–8 | Claude Code starts up | Forget a shortcut, and it's another web search |
| 8–13 | Same screen | And what you looked up is gone again |
| 13–18 | Same screen | What you want: hints for what's running right now |

### §2 Always the same place (0:18–0:28)

| sec | screen | caption |
|---|---|---|
| 18–24 | `Super+H`. The overlay appears top-right (Herdr › Claude Code, 15 entries) | One hotkey for the focused window's hints. Position is configurable |
| 24–28 | The list (key on the left, title and command in the middle, category on the right) | Key on the left, description (or command) in the middle, category on the right |

### §3 Lead 1: the frontmost process (0:28–0:53)

| sec | screen | caption |
|---|---|---|
| 28–33 | Header reads `Herdr › Claude Code` | It follows the frontmost process, not the window |
| 33–34 | A new tab | (no caption) |
| 34–39 | Codex starts up. The overlay still reads `Herdr › Claude Code` | The overlay stays on the last tab until pressed again |
| 39–46 | `Super+H` → swaps to `Herdr › Codex` | Press again in another tab and it swaps without closing |
| 46–53 | Herdr's hints (scroll, tab, paste) mix into the list | Shows hints for the whole process chain, Herdr's own included |

### §4 Lead 2: typing with it on screen, search and copy (0:53–1:48)

| sec | screen | caption |
|---|---|---|
| 53–54 | Back to the first tab (Claude Code) | (no caption) |
| 54–56 | `Super+H` → `Herdr › Claude Code` | (no caption) |
| 56–63 | With the overlay open, `write tests` is typed into the terminal | Keep typing with the overlay on screen |
| 63–64 | `Ctrl+U` erases the terminal line | (no caption) |
| 64–66.5 | `Super+Shift+H` → the search box | Search is Super+Shift+H |
| 66.5–72.5 | `session` typed → 3 entries (`/model` `/compact` `/clear`) | Keyboard input switches over only when search starts |
| 72.5–76.5 | `↓` → the top of the list (`/model`). The key typed so far shows below | ↓ moves into the list. Keys shown below |
| 76.5–80 | `↓` → `/compact`. The detail below changes | In the list, ↑↓ selects a hint |
| 80–84.5 | `c` → copies `/compact` and leaves search. A chip appears | c copies the selected hint's command and returns to the window |
| 84.5–89.5 | `Ctrl+Shift+V` → `/compact` pasted into the terminal | The filter stays, and typing goes back to the window |
| 89.5–90.5 | To the Codex tab | (no caption) |
| 90.5–95.5 | `Super+H` → Codex's sheet. No chip | A different sheet is not filtered |
| 95.5–96.5 | Back to the Claude Code tab | (no caption) |
| 96.5–101.5 | `Super+H` → still 3 entries, chip still there | Come back, and the filter is still there |
| 101.5–107.5 | Chip's `×` → back to all entries | The filter is per sheet. Clear it with × or an empty search box |

### §5 Lead 3: write it down right there (1:48–2:29)

| sec | screen | caption |
|---|---|---|
| 107.5–112.5 | `Super+Ctrl+H`. Edit mode's key list shows below | Forgot something? Write it down right there |
| 112.5–116.5 | `a` → a form, "New hint → Claude Code" | It is added to the same sheet as the selected hint |
| 116.5–120 | Title "Toggle permission mode" | (no caption) |
| 120–120.6 | Tab | (no caption) |
| 120.6–124.1 | Key `Shift+Tab` | (no caption) |
| 124.1–130.1 | Enter. The list is 16 entries | Enter saves it and edit mode ends |
| 130.1–136.1 | `herdr.yaml` in vi (line 5 missing its `]`). The overlay reads `⚠ YAML error`, the list stays | Break it by hand, and the last good content stays |
| 136.1–137.1 | vi closes | (no caption) |
| 137.1–143.1 | It is fixed → `⚠` goes away, still 16 entries | Fix it and it recovers right away. No restart needed |
| 143.1–149.1 | `Super+H` closes it | The moment you forget, it is right where you look |

### §6 Detection: inside Herdr (2:29–3:07)

| sec | screen | caption |
|---|---|---|
| 149.1–157.1 | A wide terminal with 3 lines of `docs/TERMINALS.md`'s Herdr launch examples | Setup: open Herdr in a terminal named herdr |
| 157.1–158.1 | The terminal window closes | (no caption) |
| 158.1–164.1 | `Super+H` → `Herdr › Claude Code` (16 entries) | Asks Herdr for the focused tab, then reads its process |
| 164.1–165.1 | `Super+H` closes it | (no caption) |
| 165.1–171.1 | `herdr.yaml` in vi. The two lines of `nested:` near the top | To narrow what is shown, write the setting |
| 171.1–172.1 | vi closes | (no caption) |
| 172.1–178.1 | `Super+H` → 13 entries. Herdr's own share is 3, scroll and input | Herdr's hints are now just scroll and input |
| 178.1–185.1 | A terminal window with `wayhint context --shown`'s output (`parent herdr: 3/6 shown`) | wayhint context --shown shows where it was narrowed |
| 185.1–186.1 | The terminal window closes | (no caption) |
| 186.1–187.1 | `Super+H` closes it | (no caption) |

### §7 Detection: inside a terminal (3:07–3:52)

| sec | screen | caption |
|---|---|---|
| 187.1–192.1 | less is opening `wm.yaml` in a foot window | Even in a terminal with no multiplexer like herdr |
| 192.1–197.1 | Same screen | Supports foot / kitty / Ghostty / Alacritty |
| 197.1–202.1 | A wide terminal with `$ ./scripts/setup-terminals` and the dry run's output (4 terminals) | Using it in a terminal needs one setup step |
| 202.1–208.1 | Same screen. The last line, "add --apply to write" | One command, scripts/setup-terminals. Default just checks |
| 208.1–209.1 | The terminal window closes | (no caption) |
| 209.1–215.1 | `Super+H` → Less (sub-header `foot · less`) | Shows hints for the process running in the terminal |
| 215.1–217.1 | A second foot window opens. vi inside it | (no caption) |
| 217.1–223.1 | Two windows, the overlay still shows Less | Two windows, and it never mixes up their contents |
| 223.1–229.1 | `Super+H` → swaps to Vi | Press again in another window for its frontmost process |
| 229.1–230.1 | `Super+H` closes it | (no caption) |
| 230.1–231.1 | vi's window closes | (no caption) |
| 231.1–232.1 | less' window closes | (no caption) |

### §8 Detection: a GUI app (3:52–4:11)

| sec | screen | caption |
|---|---|---|
| 232.1–236.1 | Notes' window opens | The same for GUI apps |
| 236.1–242.1 | `Super+H` → Notes (sub-header is the app_id) | Each app shows its own hints |
| 242.1–248.1 | `notes.yaml` in vi (`match:` → `wayland:` → `app_id_regex`) | Just put the app's name (app_id) in match |
| 248.1–249.1 | vi closes | (no caption) |
| 249.1–250.1 | `Super+H` closes it | (no caption) |
| 250.1–251.1 | Notes' window closes | (no caption) |

### §9 How to write a sheet (4:11–4:47)

| sec | screen | caption |
|---|---|---|
| 251.1–259.1 | `hints/en/claude-code.yaml` in vi (the `match:` line) | One sheet is one app, one YAML. match decides where it shows |
| 259.1–260.1 | vi closes | (no caption) |
| 260.1–266.1 | `Super+H` → `Herdr › Claude Code` (16 entries) | The sheet matched by match shows its hints |
| 266.1–272.1 | `config.yaml` in vi (`include: [wm]`). The overlay stays open | config.yaml's include mixes common hints into every sheet |
| 272.1–278.1 | Same screen (`language: en`, and the overlay's English UI) | Hints are per language, the same one as the UI |
| 278.1–279.1 | vi closes | (no caption) |
| 279.1–280.1 | A new tab (nothing running) | (no caption) |
| 280.1–286.1 | `Super+H` → Herdr's 8 entries. wm's 2 at the end | Common hints line up at the end of every sheet |
| 286.1–287.1 | `Super+H` closes it | (no caption) |

### §10 Close (4:47–5:04)

| sec | screen | caption |
|---|---|---|
| 287.1–293.1 | Herdr's window | In Herdr, in a terminal or in a GUI app, the hints switch by themselves |
| 293.1–299.1 | Same screen | Not doing: running commands, AI generation, or reading the screen |
| 299.1–304.1 | Same screen | Wayland (labwc) / GTK4 / hints in YAML |

## 4. Notes on caption writing

The rule is `demo/README.md`'s "Writing captions", which is canonical. The captions unique to
the 60-second cut are shortened versions of the original showcases' captions ("One hotkey for
the focused window's hints", "c copies it and returns to the window", "Enter saves it, right
into the list"). The 180-second cut's "One sheet is one app, one YAML. match decides where it
shows" combines sheets' two frames into one.

## 5. After recording, check

- [ ] no username, real code, conversation content, or home path is on screen
- [ ] the caption band (the values in `demo/README.md`'s "caption band" table) does not overlap
      the window or the overlay
- [ ] in the 60-second cut's square crop, the overlay and captions are not cut off
