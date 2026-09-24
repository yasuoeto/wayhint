# terminal — looking inside a terminal

[日本語](01_terminal_storyboard.ja.md)

- **Subject**: a terminal window with no multiplexer, and the program running inside it
- **Detection path**: the window's app_id is `foot.p<pid>` → that pid's `/proc` → the tty's
  foreground process (`setup-terminals` is what starts the terminal this way; the caption just
  says "setup")

The second of the three ways of finding a sheet. Herdr does not start
(`session: {herdr: false}`) — that is this showcase's argument: the inside of a terminal is
visible even with nobody to ask. The closing frame's wording is the same across all three.

---

## 0. Before recording

> Generated with `./scripts/demo --showcase terminal --record`. The seconds and captions in the
> table below are kept in sync with what is generated (`--validate` checks this).

- Apps shown: two foot windows. Inside them, stubs of `less` and `vi` (both shown opening a
  sheet). Plus two more terminal stubs showing the real output of the commands typed: §2's
  `setup-dry-run` (`./scripts/setup-terminals`'s dry run. Writes nothing. HOME is shown as `~`)
  and §5's `wayhint-shown` (`wayhint context --shown`)
- The terminal sheet added in §4 is `foot/ja/foot.yaml`. It is written only to the session's
  working copy, not to `demo/fixtures/` (so §1–§3's lists do not change)
- The windows are offset so both are visible at once. Two windows with different contents is
  what the picture needs
- Captions use the words a user would. wayhint's internals — `/proc`, the pid, `foot.p<pid>`,
  the contents of `chain` — never appear in a caption (they may appear on screen)
- **Not shown**: real code, a username from a home path
- The sheets shown (`wm.yaml` / `less.yaml` / `foot.yaml`) are read on screen, so no comment
  sits at their top. Their role is noted here:
  - `less.yaml` and `vi.yaml` — the two processes of the path that looks inside a terminal. A
    pair, to show that even with two windows, the sheet is decided by whichever process is in
    front
  - `wm.yaml` — has no `match`, so it is never chosen for a window; it mixes into the end of
    every sheet's list through `config.yaml`'s `include`. Only operations on the window itself
    go in it. How to bring up the overlay (`Super+H`) is not in it (someone who has forgotten
    that cannot open this list, so it would not work as a hint)

## 1. Main cut
<!-- variant: main -->

16:9. 85 seconds total.

### §1 Terminals too (0:00–0:11)

| sec | screen | caption |
|---|---|---|
| 0–5 | One foot window. less is opening a sheet inside it | Even in a terminal with no multiplexer like herdr |
| 5–11 | Same screen | Supports foot / kitty / Ghostty / Alacritty |

### §2 Setup (0:11–0:25)

| sec | screen | caption |
|---|---|---|
| 11–17 | A wide terminal window opens with `$ ./scripts/setup-terminals` and the dry run's output ("Would create" a wrapper and `.desktop` for each of foot / kitty / Ghostty / Alacritty) | Using it in a terminal needs one setup step |
| 17–25 | Same screen. The last line: "add --apply to write". Closes at 25s | One command, scripts/setup-terminals. Default just checks |

### §3 In use (0:25–0:51)

| sec | screen | caption |
|---|---|---|
| 25–33 | `Super+H`. The sub-header reads `foot · less` | Shows hints for the process running in the terminal |
| 33–36 | A second foot window opens. vi inside it | (no caption) |
| 36–43 | Two windows, the overlay still shows less' sheet | Two windows, and it never mixes up their contents |
| 43–51 | `Super+H` → the sheet swaps to `Vi` | Press again in another window for its frontmost process |

### §4 The terminal's own hints (0:51–1:08)

| sec | screen | caption |
|---|---|---|
| 51–52 | vi's window closes (`foot.yaml` has been added to the session's working copy) | (no caption) |
| 52–60 | vi's window opens again, showing `foot.yaml` (3 entries: copy, paste, search) | The terminal's own hints (copy, paste) can be written too |
| 60–68 | `Super+H` → `Foot › Vi`. Foot's 3 entries mix in after vi's, 8 total | Shows together with the frontmost process's hints |

### §5 How to check, and the close (1:08–1:25)

| sec | screen | caption |
|---|---|---|
| 68–77 | A terminal window opens with `wayhint context --shown`'s output (`chain=['ProcAdapter']`, `parent foot: 3/3 shown`) | Nothing showing? Check wayhint context --shown |
| 77–85 | The terminal window closes, then `Super+H` closes the overlay | In Herdr, in a terminal or in a GUI app, the hints switch by themselves |

## 2. Notes on caption writing

The rule is `demo/README.md`'s "Writing captions", which is canonical. What this showcase
follows is its rule 8 — the closing frame is the same wording across all three ways of finding a
sheet: "In Herdr, in a terminal or in a GUI app, the hints switch by themselves". When touching
the headline captions of the three lead scenes (rule 7), use the same wording as `common`.

## 3. After recording, check

- [ ] setup's output paths start with `~/`, and no runtime directory name is shown
- [ ] the sub-header changes from `less` to `vi`
- [ ] once `foot.yaml` is added, the list reads `Foot › Vi` with Foot's 3 entries mixed in
- [ ] `--shown`'s output shows `chain=['ProcAdapter']`, and no home path is shown
- [ ] no herdr / foot-herdr process exists anywhere in the session
- [ ] no username, real code, or home path is on screen
- [ ] the caption band (the values in `demo/README.md`'s "caption band" table) does not overlap
      the window or the overlay
