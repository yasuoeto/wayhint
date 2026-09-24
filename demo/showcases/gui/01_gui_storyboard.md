# gui — looking at a GUI app's window

[日本語](01_gui_storyboard.ja.md)

- **Subject**: a GTK app's window, not a terminal
- **Detection path**: just matching the window's app_id against `match.wayland`. No process
  inside is looked for

The third of the three ways of finding a sheet, and the shortest. Shows the side that has no
foreground process to look into (DECISIONS 0024). Herdr does not start. The closing frame's
wording is the same across all three.

---

## 0. Before recording

> Generated with `./scripts/demo --showcase gui --record`. The seconds and captions in the
> table below are kept in sync with what is generated (`--validate` checks this).

- App shown: the demo's own GTK4 stub `notes` (`dev.wayhint.demo.Notes`). **No real app is
  used** — its output would change every time, and its logo and wording are not ours to borrow
- A stub of the terminal that last ran `wayhint context --shown` opens (`wayhint-shown`; its
  output is real)
- The Notes window is placed to fill most of the screen (the terminal is only the last frame).
  The subject of this scene is the window itself
- **Not shown**: a real app, real data
- `notes.yaml` is demo-only (not a copy of a real machine's). It is read on screen, so no
  comment sits at its top. A GUI app has no foreground process the way a terminal's does, and is
  chosen by the window's app_id alone (DECISIONS 0024)

## 1. Main cut
<!-- variant: main -->

16:9. 47 seconds total.

### §1 Decided by the window alone (0:00–0:47)

| sec | screen | caption |
|---|---|---|
| 0–5 | Notes' window opens | The same for GUI apps |
| 5–13 | `Super+H` → `Notes`'s sheet | Each app shows its own hints |
| 13–21 | The sub-header shows only the app_id | The top line names the app |
| 21–30 | vi's window opens, showing `notes.yaml`'s `match:` → `wayland:` → `app_id_regex`. Closes at 30s | Just put the app's name (app_id) in match |
| 30–39 | A terminal window opens with `wayhint context --shown`'s output (`desktop_app=dev.wayhint.demo.Notes`, no `process` or `chain`) | Nothing showing? Check wayhint context --shown |
| 39–47 | The terminal window closes, then `Super+H` closes the overlay | In Herdr, in a terminal or in a GUI app, the hints switch by themselves |

## 2. Notes on caption writing

The rule is `demo/README.md`'s "Writing captions", which is canonical. What this showcase
follows is its rule 8 — the closing frame is the same wording across all three ways of finding a
sheet: "In Herdr, in a terminal or in a GUI app, the hints switch by themselves". When touching
the headline captions of the three lead scenes (rule 7), use the same wording as `common`.

## 3. After recording, check

- [ ] the sub-header shows no process name (app_id only)
- [ ] `--shown`'s `desktop_app` output matches the sub-header's app_id, and no `chain` is shown
- [ ] the wm hint is appended at the end of the list
- [ ] no herdr / foot-herdr process exists anywhere in the session
- [ ] the caption band (the values in `demo/README.md`'s "caption band" table) does not overlap
      the window or the overlay
