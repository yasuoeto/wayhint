# DEVELOPMENT — how to develop and how the repository is laid out

[日本語](DEVELOPMENT.ja.md)

Documentation for the people who use wayhint lives in `README.md` and `docs/`. This file holds
only what you need to work on wayhint itself.

## Setup and validation

```sh
./scripts/setup                 # .venv (shares system site-packages) + ruamel.yaml + pywayland + regex (+ PyWayfire) + dev deps
.venv/bin/pip install -e .      # puts wayhint / wayhintd in .venv/bin
./scripts/check                 # lint + unit tests. This is the one entry point for validation
```

Pass/fail is judged by the exit code, not by the last lines printed. Never make output narrowed
with `| tail`, `| grep` or `| head` the condition of `&&` or `if`: a pipeline exits with the status
of its last command, so a failing check reads as a passing one. Run it unnarrowed, or put
`set -o pipefail` before it, or capture the output and print it afterwards. New checks go into
`./scripts/check` rather than into a separate command.

Each document has a Japanese version next to it, `<name>.ja.md` (DECISIONS 0044). Change both in
the same commit: `./scripts/check` fails when one is missing or their headings differ.

## GUI tests

`./scripts/check-gui` starts a compositor on a headless backend and, inside it, actually
displays the overlay to measure its position and contents (DECISIONS 0030). Nothing appears on
screen, and it does not touch the session you are currently using. Run it alongside
`./scripts/check` whenever you change placement, the overlay's contents, or the path from a
command to a window.

```sh
sudo apt install grim imagemagick        # used to measure position
sudo apt install wtype                   # optional: for testing the hotkey path; if missing, only that one test is skipped
./scripts/check-gui
```

The compositor uses whichever of `labwc` / `sway` / `cage` is found on PATH. `at-spi2-core` is
used to read the overlay's contents, but it is normally already present as a GTK dependency. No
extra privileges are needed (`wtype` uses the compositor's virtual-keyboard protocol, so it does
not touch `/dev/uinput`).

## Introductory videos

`./scripts/demo` plays back the script in `demo/showcases/<name>/` inside the same headless
compositor and records it (DECISIONS 0031, 0032). Unless you pass `--record`, it only shows what
it would capture and the running time, without recording.

```sh
sudo apt install ffmpeg grim imagemagick foot wtype fonts-noto-cjk fonts-noto-mono
./scripts/demo                                  # list of showcases
./scripts/demo --showcase herdr                 # planned running time and steps
./scripts/demo --showcase herdr --record        # mp4 / webm / contact sheet under out/ja/<variant>/
```

How to write a script, build a showcase, and add scenes is covered in `demo/README.md`.

## Debian packages

`./scripts/build-deb [unstable|trixie]` builds the `.deb` from `debian/` in a clean container of
each release (both by default), installs it in a second fresh container and runs it once, then
prints lintian's findings. It needs docker and a network and is not part of `./scripts/check`.
What is built is the working tree as git sees it, uncommitted changes included; the packages
land in `build/deb/<dist>/`. The trixie build gets the version `<version>~deb13+1`, which sorts
below the unstable one. The version itself comes from the top entry of `debian/changelog`: add
an entry there when `pyproject.toml`'s version changes, and change the version and date in the
`.TH` line of the pages in `man/`.

The code has to keep working with the oldest library versions the packages depend on, which are
trixie's (pywayland 0.4.18, GTK 4.18, gtk4-layer-shell 1.0.4, Python 3.13). In particular,
regenerate `_wlr_foreign_toplevel.py` only with `scripts/gen-protocol`, which rewrites the
scanner's output to import what 0.4.18 also has.

## After changing Python code

`wayhint reload` only re-reads YAML, so after changing code you need to replace the daemon.
Steps are under "Restarting the daemon" in `README.md`.

## Layout of the repository

| Path | Contents |
|---|---|
| `src/` | Implementation |
| `tests/` | Tests |
| `docs/` | Documentation for users (`CONFIG.md`, `HOTKEYS.md`, `SHEET-FORMAT.md`, `SHEETS.md`, `TERMINALS.md`) |
| `dev-docs/PRODUCT.md` | Requirements |
| `dev-docs/DESIGN.md` | Design |
| `dev-docs/DECISIONS.md` | Record of decisions |
| `dev-docs/PHASE0.md` | Phase 0 dependency check |
| `examples/` | Templates for config.yaml and sheets |
| `skills/` | Skills for coding agents, published with the code (`wayhint-add-sheet`: writing a sheet; DECISIONS 0047) |
| `demo/` | Introductory videos. Scripts and scenarios under `showcases/<name>/`; `fixtures/` and `bin/` are shared (`demo/README.md`) |
| `tools/` | Repository tooling. Headless session (shared between tests and demos) and video generation |
| `scripts/` | `setup`, `check`, `check-gui`, `demo`, `setup-terminals`, `gen-protocol`, `build-deb` |
| `man/` | Man pages `wayhint(1)` and `wayhintd(1)`, English and `.ja` (the tests check that they name every command and option) |
| `debian/` | Debian packaging, built by `scripts/build-deb` for unstable and trixie (DECISIONS 0048) |

The author's coding-agent configuration and working log are kept outside the public repository
(DECISIONS 0045); `.gitignore` lists them so that a clone with its own does not commit them.
