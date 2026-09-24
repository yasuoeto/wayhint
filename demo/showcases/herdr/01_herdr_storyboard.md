# herdr — looking inside Herdr

[日本語](01_herdr_storyboard.ja.md)

- **Subject**: Herdr's window and the command running in its pane
- **Detection path**: the window's app_id is `herdr` → ask Herdr for the focused pane → that
  pane's foreground process

The first of the three ways of finding a sheet. What it can do (the list's shape, not stealing
focus, adding on the fly) is `common`'s job, so this one only follows **which process's hints
are showing**. The closing frame's wording is the same across all three.

---

## 0. Before recording

> Generated with `./scripts/demo --showcase herdr --record`. The session has Herdr
> (`session: {herdr: true}`). The seconds and captions in the table below are kept in sync with
> what is generated (`--validate` checks this).

- Apps shown: Herdr + stubs of Claude Code / Codex, an idle pane, a vi stub, a stub of the
  terminal that ran `wayhint context --shown` (`wayhint-shown`; its output is real)
- §1's setup: the stub `herdr-launch` reads `docs/TERMINALS.md`'s Herdr launch examples on the
  spot and prints them (so the video and the docs never disagree)
- Captions use the words a user would. What is called a unit inside Herdr is called a "tab", as
  a viewer sees it
- Two layers of sheets mix: Herdr's window is `herdr.yaml` (6 entries), the pane's command is
  `claude-code.yaml` (7 entries) / `codex.yaml` (1 entry). Nothing narrows by tag anywhere, so
  all of the parent Herdr's hints mix in (DECISIONS 0034). All three are copies of the real
  machine's `~/.config/wayhint/hints/ja/` (2026-09-24)
- Narrowing in §3 replaces `herdr.yaml` with `narrowed/ja/herdr.yaml` (the copy plus the two
  lines of `nested.export_categories`). Only the working copy is rewritten;
  `demo/fixtures/` does not change
- **Not shown**: real code, conversation content, a username from a home path

## 1. Main cut
<!-- variant: main -->

16:9. 105 seconds total.

### §1 Setup, then picking what is running inside (0:00–0:39)

| sec | screen | caption |
|---|---|---|
| 0–4 | Herdr's window. The pane is idle | Look inside Herdr |
| 4–13 | A wide terminal window with 3 lines of `docs/TERMINALS.md`'s launch examples (kitty / Ghostty / foot, each opened under the name herdr). Closes at 13s | Setup: open Herdr in a terminal named herdr |
| 13–16 | Claude Code starts up in the pane | (no caption) |
| 16–24 | `Super+H`. The header reads `Herdr › Claude Code` | Asks Herdr for the focused tab, then reads its process |
| 24–31 | The list mixes in Herdr's `PgUp/PgDn` and middle-click paste | Shows hints for the whole process chain, Herdr's own included |
| 31–39 | All 6 of Herdr's entries are in, 15 total (the scrollbar shows what does not fit) | Write nothing, and all of Herdr's hints show up too |

### §2 Switching tabs (0:39–1:03)

| sec | screen | caption |
|---|---|---|
| 39–45 | A new tab → Codex. The overlay still reads `Herdr › Claude Code` | The overlay stays on the last tab until pressed again |
| 45–53 | `Super+H` → swaps to `Herdr › Codex` | Switch tabs and press again for that tab's sheet |
| 53–55 | Another new tab. The pane is still idle | (no caption) |
| 55–63 | `Super+H` → Herdr's own sheet (6 entries + wm) | No sheet for the running process? All of Herdr's hints show |

### §3 How to narrow it, and how to check (1:03–1:45)

| sec | screen | caption |
|---|---|---|
| 63–68 | The overlay closes; `nested.export_categories: [scroll, input]` is added to `herdr.yaml`, opened in vi | (no caption) |
| 68–76 | The two lines of `nested:` are visible near the top of vi | To narrow what is shown, write the setting |
| 76–80 | vi's window closes, back to the Claude Code tab | (no caption) |
| 80–88 | `Super+H` → `Herdr › Claude Code` is 12 entries. Herdr's own share is 3: PgUp/PgDn and paste | Herdr's hints are now just scroll and input |
| 88–97 | A terminal window opens with `wayhint context --shown`'s output (`parent herdr: 3/6 shown`, `categories: scroll, input -- nested.export_categories (herdr.yaml)`) | wayhint context --shown shows where it was narrowed |
| 97–105 | The terminal window closes, then `Super+H` closes the overlay | In Herdr, in a terminal or in a GUI app, the hints switch by themselves |

## 2. Notes on caption writing

The rule is `demo/README.md`'s "Writing captions", which is canonical. What this showcase
follows is its rule 8 — the closing frame is the same wording across all three ways of finding a
sheet: "In Herdr, in a terminal or in a GUI app, the hints switch by themselves". When touching
the headline captions of the three lead scenes (rule 7), use the same wording as `common`.

## 3. After recording, check

- [ ] the four states `Herdr › Claude Code` → `Herdr › Codex` → Herdr alone → narrowed
      `Herdr › Claude Code` all appear
- [ ] the narrowed list has neither `Cycle theme` nor either of the two tab entries. `--shown`'s
      output names the same count as the list (3/6)
- [ ] Herdr's own hints are mixed into the list (hints of the same category sit together, so
      the one scroll entry lands right after Claude's scroll)
- [ ] no username, real code, or conversation content is on screen
- [ ] the caption band (the values in `demo/README.md`'s "caption band" table) does not overlap
      the window or the overlay
