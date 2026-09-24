# wayhint — Phase 0: dependency check (design document §78)

[日本語](PHASE0.ja.md)

Done on: 2026-09-16, host mifuyu (Debian, Linux 7.1.12).

| Item | Result | Notes |
|---|---|---|
| Wayfire | **0.10.0 (wlroots 0.19.3) installed, not running** | The current session is labwc. `~/.config/wayfire.ini`'s `[core] plugins` includes `ipc`, `ipc-rules`. Whether the IPC socket actually exists needs to be checked while Wayfire is running |
| Python | 3.14.7 (`/usr/bin/python3`) | venv is also 3.14.7 |
| GTK4 | 4.22.4 (`gir1.2-gtk-4.0`, `libgtk-4-1`) | `gi.require_version("Gtk","4.0")` OK |
| PyGObject | 3.57.1 (`python3-gi`) | System site-packages. From a venv, needs `--system-site-packages` or the `PyGObject` wheel |
| gtk4-layer-shell | 1.3.0 (installed 2026-09-16) | apt: `libgtk4-layer-shell0` + `gir1.2-gtk4layershell-1.0`. `gi.require_version("Gtk4LayerShell","1.0")` OK |
| pywayland | 0.4.19 (added to `.venv` on 2026-09-16) | Default backend. Generated code for `wlr-foreign-toplevel-management` is vendored in the repo (`protocols/`, `scripts/gen-protocol`) |
| PyWayfire | 4.0 (added to `.venv` on 2026-09-16) | PyPI name is `wayfire`; the name `pywayfire` is not it. For the fallback backend, optional |
| labwc | Running (native, from tty1) | Advertises `zwlr_foreign_toplevel_manager_v1` v3 and `wl_output` v4. Confirmed toplevels and activated state for foot / chromium / firefox, and confirmed `activate` |
| ruamel.yaml | 0.19.1 (added to `.venv` on 2026-09-16) | Not in apt (`python3-ruyaml` is a different fork) |
| Herdr | 0.8.2 (`~/.local/bin/herdr`) | See below |
| gvim | Vim 9.2 (`/usr/bin/gvim` → alternatives) | OK |

## The actual shape of the Herdr CLI

- `herdr pane current` → JSON
  `{"result":{"pane":{pane_id, focused, workspace_id, agent, agent_status, terminal_title, terminal_title_stripped, cwd, foreground_cwd, ...}}}`.
  Returns the focused pane.
- `herdr pane process-info --current` / `--pane <ID>` →
  `{"result":{"process_info":{pane_id, shell_pid, foreground_process_group_id, foreground_processes:[{pid,name,argv,cmdline,cwd}]}}}`.
- **Caution**: omitting `--pane`/`--current` returns the pane of the calling shell (not
  necessarily the focused one). The adapter must always pass either `--current` or the `pane_id`
  from `pane current`.
- The `agent` / `terminal_title` fields are also returned, but as design document §15 specifies,
  V1 decides context using `foreground_processes` alone (title is close to screen scraping).

## Needed before implementation (requires sudo / network)

```sh
sudo apt install libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0
```

On the venv side (to be automated by updating `scripts/setup`):

```sh
python3 -m venv --system-site-packages .venv   # shares PyGObject/GTK
.venv/bin/pip install pywayland ruamel.yaml wayfire
```

## Not yet confirmed (can only be confirmed in a Wayfire session)

- Whether the same protocol appears when the `foreign-toplevel` plugin is enabled (if so, the
  wayland backend can be used as is).
- Whether `WAYFIRE_SOCKET` actually exists, and getting the active view / output via PyWayfire.
- The behavior of layer-shell `ON_DEMAND` keyboard mode (§47).
- Real-hardware tests §69–§73 in general.
