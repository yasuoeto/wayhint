# TERMINALS — setting up terminals
[日本語](TERMINALS.ja.md)

How wayhint finds the command running inside a terminal window, and how to set up the terminal
and the launcher for that. This page covers only the procedure (for why this approach was chosen,
see the developer-facing `dev-docs/DECISIONS.ja.md` 0027).

## What the problem is

What we want to show hints for is not the terminal itself but the command running inside it
(`vi`, `top`, `claude`). A terminal does not tell the outside world what it is running, so wayhint
walks `/proc` looking for "the process, among that terminal's descendants, that is at the front of
the tty".

The part we don't know where to start walking from is **which terminal process is drawing the
frontmost window**.

- The Wayland protocol does not pass the toplevel's PID to the client
  (neither `zwlr_foreign_toplevel_manager_v1` nor `ext_foreign_toplevel_list_v1` carries a PID)
- labwc has no IPC to ask
- foot has no query interface either

If a terminal has only one window, "that terminal has only one process" settles it. With two or
more it can't be decided. And using a terminal with multiple windows is the normal case.

## The `.p<pid>` convention on app_id

The one piece of information the compositor does hand to the client is the **app_id**, so
**the window side declares its own PID via the app_id**.

If an app_id ends in `.p<number>`, wayhint treats that number as the terminal process's PID and
walks `/proc` from there.

```
app_id = "foot.p12345"  →  base "foot" / walk /proc from PID 12345
app_id = "foot"         →  if there is exactly one foot process use it, otherwise undetermined
```

The PID read this way is checked against `/proc`'s `comm` before use, because once a window is
closed its app_id belongs to nobody and that number gets reused by another process.

wayhint strips the suffix before doing anything else with it, so **whoever configures a sheet does
not need to worry about it**:

- a sheet's `app_id_regex` can stay as `["^foot$"]` (it still matches `foot.p12345`)
- the overlay's context label still shows `foot`
- only `wayhint context`'s `desktop_app` shows `foot.p12345` as-is (since it is the window's
  identifier)

## Start by running the script

Most of the procedure is done by `./scripts/setup-terminals`. **It writes nothing unless you pass
`--apply`** (this holds whether or not you name a terminal). You can pick terminals with
arguments; the default is every installed terminal.

```sh
./scripts/setup-terminals                        # dry run. just shows what it would do
./scripts/setup-terminals kitty ghostty          # dry run. naming specific terminals
./scripts/setup-terminals --apply                # actually writes
./scripts/setup-terminals --apply kitty ghostty  # writes, for specific terminals
```

`--check` is a dry run identical to the default (for when you want to make the intent explicit).
Combining it with `--apply` is an error.

What `--apply` does:

- creates a wrapper at `~/.local/bin/<terminal>-wayhint`
- overwrites `~/.local/share/applications/<terminal>.desktop` (replacing only `Exec` from the
  system `.desktop`; argument placeholders like `%F` are kept)
- **rewrites the matching line in the bar or compositor config**. It replaces only the leading
  word of that line's command, and never reads the whole file back and rewrites it, so comments,
  key order and whitespace are all left untouched

How it treats existing files:

| State | Behaviour |
|---|---|
| Already generated, and up to date | does nothing (`up to date`) |
| Already generated, but stale | overwrites it. A marker comment shows it was made by this script |
| A hand-written file with no marker | **leaves it alone** (`a hand-written file is here, not touching it`) |
| A launcher line that already points at the wrapper | not touched |

Launcher settings are **backed up before being rewritten**. One run makes at most one backup per
file, named `<filename>.wayhint-backup-<timestamp>`, placed in the same directory.

If the path of `~/.local/bin` has a space or a shell character (`"`, `&`, `<`, `$` and so on) in
it, the script stops with exit 2 and writes nothing: the launchers would have to name the wrapper
unquoted.

It exits 1 while work remains, so a dry run doubles as a sanity check. It looks at 8 launcher
files (listed at the end of the run). If you start terminals some other way you'll need to find
that path yourself. Launches embedded in a single shell line (`sh -c '... foot ...'`) are also out
of scope.

The rest of this page explains what the script does, and how to do it by hand.

## Per-terminal support

| Terminal | How it joins the convention | Condition |
|---|---|---|
| foot | `--app-id "foot.p$$"` | none (foot has no tabs) |
| kitty | `--class "kitty.p$$"` | don't enable `single_instance` (disabled by default). **only one tab / split per window** |
| Ghostty | `--class="com.mitchellh.ghostty.p$$"` | `gtk-single-instance=false` (enabled by default). **only one tab / split per window** |
| Herdr | include `herdr` in the window's app_id | a window that doesn't include it is not routed through Herdr (below) |
| Alacritty | `--class "alacritty.p$$"` | don't open with `alacritty msg create-window` / `--daemon` (there are no tabs / splits) |
| WezTerm | doesn't join | can't change the app_id per window |

**Only one tab / split per window** comes from a limit of `/proc`. A tab or a split each has its
own pty, and each has its own frontmost process, but `/proc` doesn't say which one is on screen.
As soon as two or more turn up it becomes undetermined (picking one would be picking wrong). For
the same reason, running `tmux` or `ssh -t` inside a single tab also becomes undetermined. Using
tabs / splits needs a terminal-specific adapter (see the "out of scope" list in
`dev-docs/DECISIONS.ja.md` 0027).

A wrapper script is inserted to use `$$`. Because it uses `exec`, `$$` ends up being the
terminal's own PID. The exact way the value is produced doesn't matter — a fixed value works too,
as long as it's unique.

### foot

```sh
#!/bin/sh
# ~/.local/bin/foot-wayhint
exec /usr/bin/foot --app-id "foot.p$$" "$@"
```

### kitty

`--class` (`--app-id` is an alias for it) becomes the Wayland app_id. By default it's one window
per process, so it joins as-is. If `single_instance` is enabled, every window becomes a single
process, and the PID `.p<pid>` points at no longer corresponds to individual windows.

```sh
#!/bin/sh
# ~/.local/bin/kitty-wayhint
exec /usr/bin/kitty --class "kitty.p$$" "$@"
```

### Ghostty

The default `gtk-single-instance=true` makes every window a single process, so we set it to
`false` and pass `--class`. Changing `class` can break launches from the `.desktop` file or D-Bus
activation (see `class` in `man 5 ghostty`).

```sh
#!/bin/sh
# ~/.local/bin/ghostty-wayhint
exec /usr/bin/ghostty --gtk-single-instance=false --class="com.mitchellh.ghostty.p$$" "$@"
```

### Alacritty

`--class` becomes the Wayland app_id. It has neither tabs nor splits, and a normal launch is one
window per process, so it joins as-is, just like foot. A window opened with
`alacritty msg create-window` or `--daemon` lands inside an existing process, so the PID
`.p<pid>` points at no longer corresponds to individual windows (undetermined from the second one
on).

Alacritty's default app_id is `Alacritty` (capitalised), but the wrapper uses **lower-case
`alacritty`**, because PID matching compares the app_id against `comm` (`alacritty`). If a sheet's
`app_id_regex` says `^Alacritty$`, change it to `^alacritty$`.

```sh
#!/bin/sh
# ~/.local/bin/alacritty-wayhint
exec /usr/bin/alacritty --class "alacritty.p$$" "$@"
```

### Herdr

Herdr answers which pane is focused itself, through `herdr pane current` /
`herdr pane process-info`, so it doesn't go through the `/proc` route. But **there is one
precondition**.

> **Herdr's window's app_id must include `herdr`.**

The adapter is chosen by app_id, so a window that doesn't include it is not routed through Herdr.
The precondition matters in two places.

| Where | What | Can it be changed |
|---|---|---|
| Whether Herdr is queried at all | whether the app_id contains `herdr` (substring, case-insensitive) | **no** (there is no `config.yaml` entry for it) |
| Which parent sheet is picked | `herdr.yaml`'s `match.wayland.app_id_regex: ["herdr"]` | yes (in YAML) |

A launch such as `foot --app-id=foot-herdr ... herdr` satisfies this (for Alacritty,
`alacritty --class alacritty-herdr -e herdr`). Starting `herdr` in a plain terminal leaves the
app_id as `foot` or `kitty`, so it does not satisfy this — put `herdr` into the app_id instead.

```sh
kitty  --class kitty-herdr -e herdr
ghostty --gtk-single-instance=false --class=com.mitchellh.ghostty-herdr -e herdr
foot   --app-id foot-herdr herdr
```

For a window that doesn't satisfy the precondition, a terminal whose `/proc` route works (foot /
kitty / Ghostty / Alacritty) can tell that "**a command called `herdr` is running**", but not
which tab inside it is being looked at. When that happens, `wayhintd -v`'s log prints one line:

```
herdr is running in a window whose app_id is 'kitty'; open it with 'herdr' in the app_id
to get hints for what is inside it (docs/TERMINALS.md)
```

**You can open as many Herdr windows as you like.** A client window is a mirror of the same
session, so opening a second one in another tab makes the first one follow it there. Every window
shows the same pane, so the focused pane Herdr answers with is correct no matter which window you
ask from (verified on real hardware, 2026-09-20). But **every window must include `herdr` in its
app_id** — only a window that doesn't falls back to the `/proc` route above.

The one exception is **running several named sessions at once** (`herdr --session <name>`). Each
session has its own socket, but the adapter always asks the default session. A window belonging to
a non-default session gets no correct answer (`dev-docs/DECISIONS.ja.md` 0028).

### WezTerm

Because it can't change the app_id per window, it doesn't join this convention. It's been
confirmed that a separate route — `wezterm cli list-clients` → `tty_name` → `/proc` — could handle
it, but this is not implemented (`dev-docs/DECISIONS.ja.md` 0027).

## Wiring up the launcher

Making the wrapper alone changes nothing. **Every route that launches the terminal** has to be
pointed at the wrapper.

### 1. List the launch routes

How to wire it up splits into 3 cases depending on how the launcher invokes the terminal. Check
this first.

```sh
grep -rn 'foot' ~/.config/waybar/config.jsonc ~/.config/labwc/menu.xml ~/.config/labwc/rc.xml
grep -n 'Exec' /usr/share/applications/foot.desktop
```

What follows is a worked example (a labwc + waybar + fuzzel setup).

### 2. A launcher that calls it by absolute path

If an absolute path is written directly, as in waybar's `on-click`, there's no way around editing
it there.

```diff
     "custom/launcher-foot": {
         "format": "",
         "tooltip-format": "foot",
-        "on-click": "/usr/bin/foot"
+        "on-click": "/home/USER/.local/bin/foot-wayhint"
     },
```

### 3. A launcher resolved through PATH

As in labwc's root menu (`~/.config/labwc/menu.xml`), where a bare command name is written.
If `~/.local/bin` comes before `/usr/bin` in the PATH the launcher inherits, the name alone would
reach it too, but **writing the launcher config with an absolute path is easier to trace later**.

```diff
   <item label="Terminal emulator">
-    <action name="Execute" command="foot" />
+    <action name="Execute" command="/home/USER/.local/bin/foot-wayhint" />
   </item>
```

The compositor's keybind is the same (`~/.config/labwc/rc.xml`):

```xml
<keybind key="W-Return">
  <action name="Execute" command="/home/USER/.local/bin/foot-wayhint"/>
</keybind>
```

### 4. A launcher that starts from a `.desktop` file

fuzzel and app lists read the system `.desktop` file (`/usr/share/applications/foot.desktop`'s
`Exec=foot`). **Leave the system file untouched**; placing one of the same name under
`~/.local/share/applications/` takes priority over it.

```ini
# ~/.local/share/applications/foot.desktop
[Desktop Entry]
Type=Application
Exec=/home/USER/.local/bin/foot-wayhint
Icon=foot
Terminal=false
Categories=System;TerminalEmulator;
Keywords=shell;prompt;command;commandline;

Name=Foot
GenericName=Terminal
Comment=A wayland native terminal emulator
```

When copying a `.desktop` whose `Exec` has an argument placeholder like `%F`, keep it — the
wrapper's `"$@"` picks it up.

fuzzel also has a `terminal=` setting (the terminal used to open a `.desktop` with
`Terminal=true`). Set that too:

```ini
# ~/.config/fuzzel/fuzzel.ini
terminal=/home/USER/.local/bin/foot-wayhint
```

### 5. Making it take effect

| What was changed | To apply it |
|---|---|
| waybar's config | restart waybar |
| labwc's `menu.xml` / `rc.xml` | `labwc --reconfigure` |
| `~/.local/share/applications/*.desktop` | nothing needed. fuzzel re-reads the XDG directories on every launch |
| the wrapper script itself | nothing needed. takes effect from the next window opened |

**Aliases don't work.** An alias only exists inside an interactive shell, and a launcher runs
without reading shell config.

### Alternative: shadow it on the PATH

Placing a wrapper at `~/.local/bin/foot` — **the same name as the real binary** — lets any route
resolved through PATH join without touching its config. Only the routes that call it by absolute
path (case 2 above) still need editing.

```sh
#!/bin/sh
exec /usr/bin/foot --app-id "foot.p$$" "$@"   # /usr/bin/ is required; plain "foot" would call itself, infinite recursion
```

Less work, but from then on every launch of that terminal by name silently gets `--app-id`
attached, which is harder to trace later, so being explicit per route is recommended instead.

## Checking that it's working

**Don't run `wayhint context` inside the terminal.** You want to know the frontmost process, but
the moment you run it, that `wayhint` itself becomes that terminal's frontmost process. For the
same reason, putting something in the background like `vi memo &` doesn't give an answer either
(a background process isn't among the frontmost processes). **Observe in a way that doesn't
change what you're observing.**

### 1. Look at the overlay (the easiest way)

Run something like `vi` **in the foreground** in a terminal opened through the wrapper, focus it,
and press the hotkey. The context shows below the overlay's heading.

```
foot  ·  vi  ·  eDP-1
```

If `foot` (with the suffix stripped) and the name of the command running in that terminal show up
together, it's working.

### 2. When you need the full text of `wayhint context`

Run it from a compositor keybind and dump it to a file. A process started from a keybind has no
controlling terminal, so the terminal's frontmost process doesn't change.

```sh
cat > ~/.local/bin/wayhint-ctx <<'EOF'
#!/bin/sh
exec wayhint context > /tmp/wayhint-context.txt 2>&1
EOF
chmod +x ~/.local/bin/wayhint-ctx
```

```xml
<!-- ~/.config/labwc/rc.xml -->
<keybind key="W-S-c">
  <action name="Execute" command="/home/USER/.local/bin/wayhint-ctx"/>
</keybind>
```

Run `vi` in a terminal in the foreground, focus that window, press `W-S-c`, then read it from
another window.

```
$ cat /tmp/wayhint-context.txt
active_sheet=vi desktop_app=foot.p12345 chain=['ProcAdapter'] process={'name': 'vi', ...}
```

### How to read it when nothing shows up

| Symptom | Cause |
|---|---|
| `desktop_app` has no `.p<pid>` | that window didn't go through the wrapper. Check whether it was opened by some other route (back to "List the launch routes") |
| No `chain` | that app_id is out of scope. What's left after stripping `.p<pid>` must **exactly match** one of `foot` `footclient` `kitty` `com.mitchellh.ghostty` `alacritty` (a Herdr window takes a different route, so it shows `chain=['HerdrContextProvider']`) |
| `chain` shows up but no `process` | the terminal process, or the pty inside it, couldn't be pinpointed. (a) kitty's `single_instance` or Ghostty's `gtk-single-instance` is enabled, or Alacritty was opened with `msg create-window` / `--daemon`, so all windows are one process (b) there are multiple windows without the wrapper (c) **that window has more than one tab / split, or the pty count has grown through tmux or `ssh -t`** (see "Not supported" below) |
| `process` shows `wayhint` | you ran `wayhint context` inside the terminal. Use method 1 or 2 above instead |
| `process` shows up but no `active_sheet` | the convention is working. You just haven't written a sheet for that command yet (see "Writing a hint" in `README.md`) |

## Not supported

- **A window that doesn't go through the wrapper** — if that terminal has exactly one process,
  this resolves as before. As soon as there are two or more it becomes undetermined (showing
  nothing beats showing the wrong sheet). **If Herdr is running in that terminal, it will never be
  "just one"**: running Herdr with `foot --app-id=foot-herdr` means there are always two or more
  foot processes, so a foot window that doesn't go through the wrapper is always undetermined.
- **A single window with more than one pty** — tabs, splits, `tmux`, `ssh -t`. There's a frontmost
  process per pty, and `/proc` doesn't say which pty is on screen. Rather than guess from depth or
  PID order, this is left undetermined. Supporting it needs an adapter that asks the terminal
  itself which one is focused (`kitten @ ls` for kitty, `wezterm cli list-clients` for WezTerm).
- **foot's server mode** (`foot --server` + `footclient`) — the PID of the client that opened the
  window and the PID of the server that is the shell's parent are different, so this doesn't join
  the convention.
- **Telling by the terminal's title** — `vim` / `neovim` set a title but `top` / `htop` / `less` /
  `more` don't. Even if the shell sets one, a TUI that sets a title overwrites it right after
  starting.
- **Making `TERMINAL_APP_IDS` configurable** — which terminals are in scope is decided by the
  program property "a terminal that runs commands as descendants", not by preference.
