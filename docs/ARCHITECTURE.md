# ARCHITECTURE — how wayhint is put together

[日本語](ARCHITECTURE.ja.md)

Generated at: 9da2d5e (2026-10-11)

An overview to read before the code: which modules there are, what they depend on, and the path
from a hotkey press to hints on screen. The rules behind the boundaries (which module may call
what, and why) are in [`dev-docs/DESIGN.md`](../dev-docs/DESIGN.md); this page only draws them.

## Module structure

Arrows point from the caller to what it calls or reads. All paths are under `src/wayhint/`
unless they start with `~`. `models.py` (the shared data types) is imported by nearly every
module and is left out of the diagram to keep it readable.

```mermaid
flowchart LR
    subgraph ext[Outside wayhint]
        COMP["Compositor<br/>labwc / Wayfire"]
        TERM["Terminal processes<br/>/proc, herdr CLI"]
        CONF["~/.config/wayhint/<br/>config.yaml, style.css"]
        SHEETS["~/.config/wayhint/hints/LANG/*.yaml"]
    end

    subgraph pkg[src/wayhint]
        CLI[cli.py]
        IPC[ipc.py]
        DAEMON[daemon.py]
        CONFIG[config.py]
        STORE[yaml_store.py]
        RESOLVER[context/resolver.py]
        DESKTOP[Desktop adapters<br/>context/select.py, wayland.py,<br/>wayfire.py, workspace.py]
        NESTED[Nested providers<br/>context/proc.py, herdr.py]
        MATCHER[matcher.py]
        SELECTION[selection.py]
        UI[ui/window.py<br/>editmode.py, geometry.py, style.py]
    end

    COMP -->|"hotkey runs wayhint toggle"| CLI
    CLI --> IPC
    IPC -->|"JSON over a UNIX socket"| DAEMON
    CLI -->|"edit subcommands"| STORE
    DAEMON --> CONFIG
    DAEMON --> STORE
    DAEMON --> RESOLVER
    DAEMON --> UI
    CONFIG -->|reads| CONF
    STORE -->|"reads, writes back"| SHEETS
    RESOLVER --> DESKTOP
    RESOLVER --> NESTED
    RESOLVER --> MATCHER
    DESKTOP <-->|"foreign-toplevel, ext-workspace, Wayfire IPC"| COMP
    NESTED -->|"reads, runs with a fixed argv"| TERM
    UI --> SELECTION
    UI -->|"reads style.css"| CONF
    UI -->|"layer-shell surface"| COMP
```

| Node | Path | Role |
|---|---|---|
| cli.py | `cli.py` | `wayhint` command: sends overlay commands to the daemon, edits sheets from the command line, `check-sheet`, `inspect` |
| ipc.py | `ipc.py` | Socket path, JSON encoding, the client and the request handler shared by both sides |
| daemon.py | `daemon.py` | `wayhintd`: the GTK application; holds the loaded config and sheets, watches files, answers commands |
| config.py | `config.py` | Reads `config.yaml` into `GlobalConfig` |
| yaml_store.py | `yaml_store.py` | Loads and validates sheets (keeping the last good copy), resolves `include`, writes edits back |
| context/resolver.py | `context/resolver.py` | Turns "what is in front" into a `ResolvedContext`: window, terminal process, active sheet, output |
| Desktop adapters | `context/select.py`, `context/wayland.py`, `context/wayfire.py`, `context/workspace.py` | Talk to the compositor: active window and output, focus, the current workspace |
| Nested providers | `context/proc.py`, `context/herdr.py` | Find the foreground process inside a terminal, from `/proc` or by asking Herdr |
| matcher.py | `matcher.py` | Picks the sheet whose `match` fits an app_id or a process |
| selection.py | `selection.py` | Mixes in parent and included hints, sorts, searches |
| ui/window.py | `ui/window.py`, `ui/editmode.py`, `ui/geometry.py`, `ui/style.py` | The overlay: placement, list, search and edit mode |

Not in the diagram: `editor.py` (opens a hint in the editor), `clipboard.py`, `state.py`
(remembered search text), `i18n.py` (UI strings), `schema.py` and `sheet_check.py` (behind
`check-sheet` and the JSON schema). `demo/` and `tools/demo/` are helper tools for recording the
demo videos and are not part of the product.

## From a hotkey press to the overlay

`wayhintd` is started once by the compositor's autostart. At start it reads `config.yaml` and
every sheet, starts watching them, and listens on its socket; nothing is looked up again until a
command arrives. A hotkey press then goes like this (the `toggle` command; `show` and `refresh`
take the same path from the resolve step on).

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Comp as Compositor
    participant CLI as cli.py
    participant D as daemon.py
    participant R as context/resolver.py
    participant DA as Desktop adapter
    participant NP as Nested provider
    participant M as matcher.py
    participant W as ui/window.py

    Note over D: At start: config.py and yaml_store.py load everything,<br/>Gio.FileMonitor watches the files, ipc.py listens
    User->>Comp: press the hotkey
    Comp->>CLI: run wayhint toggle
    CLI->>D: toggle (ipc.py, JSON over the socket)
    D->>D: current workspace key (context/workspace.py)
    alt overlay here is in edit or search mode
        D->>W: hide it, or show it again unchanged
    else
        D->>R: resolve(sheets, config)
        R->>DA: snapshot()
        DA-->>R: app_id, title, output
        R->>M: match_app(app_id)
        opt a nested provider applies to this app_id
            R->>NP: foreground_process(app_id)
            NP-->>R: ProcessInfo
            R->>M: match_process(process)
        end
        R-->>D: ResolvedContext
        D->>D: toggle_action: hide, replace or open
        D->>W: present_context(context, sheets, config, includes)
        W->>W: placement (ui/geometry.py)
        W->>W: visible_hints and sort_hints (selection.py)
        W->>Comp: show the layer-shell surface
    end
    D-->>CLI: reply (visible, sheet, error)
```

| Step | Path | What happens |
|---|---|---|
| Hotkey | compositor config, `cli.py` | The compositor's keybind runs `wayhint toggle`, which only forwards the command |
| Dispatch | `ipc.py`, `daemon.py` | The daemon decodes the request and calls `Daemon.toggle` |
| Workspace | `context/workspace.py` | Decides which workspace the press belongs to; each workspace has its own open overlay |
| Resolve | `context/resolver.py` | Takes one snapshot of the focused window and turns it into a `ResolvedContext` |
| Desktop | `context/select.py`, `context/wayland.py`, `context/wayfire.py` | Reports the focused window's app_id, title and output |
| Nested | `context/proc.py`, `context/herdr.py` | For a terminal, finds the command running in front |
| Match | `matcher.py` | Chooses the window's sheet, then the process's sheet if there is one |
| Draw | `ui/window.py`, `ui/geometry.py`, `selection.py` | Places the surface and lists the hints, parent and included ones mixed in |

How the sheet is chosen and how other sheets' hints mix in is in
[`docs/SHEETS.md`](SHEETS.md); what the hotkey does in each state is in
[`docs/HOTKEYS.md`](HOTKEYS.md).
