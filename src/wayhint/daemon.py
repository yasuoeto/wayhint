"""``wayhintd``: GTK application holding the overlay, the IPC socket and the file monitors.

Everything is event-driven on the GLib main loop: socket accepts via ``GLib.io_add_watch``,
YAML changes via ``Gio.FileMonitor`` with a short debounce. Context is resolved only on
show/refresh (no polling).
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import signal
import socket
import sys
from collections.abc import Sequence
from pathlib import Path

import gi

# gtk4-layer-shell hooks libwayland-client and therefore has to be in the process *before* GTK
# (or any typelib) loads it. Importing the typelib first is not enough under PyGObject, so the
# shared library is loaded explicitly with RTLD_GLOBAL (DECISIONS 0009). Failure is tolerated
# here; ``Daemon.start`` reports the missing support via ``is_supported``.
for _name in ("libgtk4-layer-shell.so.0", "libgtk4-layer-shell.so"):
    try:
        ctypes.CDLL(_name, mode=ctypes.RTLD_GLOBAL)
        break
    except OSError:
        continue

gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
gi.require_version("GLibUnix", "2.0")
from gi.repository import Gio, GLib, GLibUnix, Gtk  # noqa: E402

from wayhint import ipc  # noqa: E402
from wayhint.config import GlobalConfig, config_dir  # noqa: E402
from wayhint.context.herdr import HerdrContextProvider  # noqa: E402
from wayhint.context.resolver import ContextResolver  # noqa: E402
from wayhint.context.select import select_desktop_provider  # noqa: E402
from wayhint.context.workspace import (  # noqa: E402
    WorkspaceWatcher,
    toggle_action,
    workspace_action,
)
from wayhint.editor import EditorError, open_in_editor  # noqa: E402
from wayhint.i18n import translator  # noqa: E402
from wayhint.models import Hint, HintSheet, ResolvedContext  # noqa: E402
from wayhint.ui import style  # noqa: E402
from wayhint.ui.window import HintWindow  # noqa: E402
from wayhint.yaml_store import Issue, SheetStore, load_config  # noqa: E402

log = logging.getLogger("wayhintd")
DEBOUNCE_MS = 200


class Daemon:
    def __init__(self, root: Path, socket_file: Path) -> None:
        self.root = root
        self.socket_file = socket_file
        self.config = GlobalConfig()
        self.config_issues: list[Issue] = []
        self.store = SheetStore(root / "hints")
        self.desktop = select_desktop_provider(self.config.context_backend)
        self.resolver = ContextResolver(self.desktop, [HerdrContextProvider()])
        self._backend = self.config.context_backend
        self.window: HintWindow | None = None
        self._watcher: WorkspaceWatcher | None = None
        self._watch_source: int | None = None
        # Workspace key -> the context shown there. An overlay stays open on the workspace it was
        # opened on until it is closed there, so this outlives switching away and back.
        self._open: dict[str, ResolvedContext] = {}
        self._pending_reload: dict[Path, int] = {}
        self._monitors: list[Gio.FileMonitor] = []
        self._server: socket.socket | None = None

    # --- lifecycle -------------------------------------------------------------------------

    def start(self, app: Gtk.Application) -> None:
        if not LayerShell.is_supported():  # needs the GDK display, so checked after Gtk init
            raise SystemExit("wayhintd: this Wayland session has no layer-shell support")
        self.reload_all()
        style.install(self.root / self.config.style)
        self.window = HintWindow(
            app,
            on_refresh=self.refresh,
            on_edit=self.edit,
            refocus=self._refocus,
            tr=translator(self.config.language),
        )
        self._watch_files()
        self._listen()
        log.info("wayhintd ready: config=%s socket=%s", self.root, self.socket_file)

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        try:
            self.socket_file.unlink()
        except OSError:
            pass

    # --- config / sheets -------------------------------------------------------------------

    def reload_all(self) -> None:
        self._reload_config()
        self.store.load_all()
        self._after_reload()

    def _reload_config(self) -> None:
        result = load_config(self.root / "config.yaml")
        self.config_issues = result.issues
        if result.config is not None:
            self.config = result.config  # else keep last-known-good config
        logging.getLogger("wayhint").setLevel(self.config.log_level.upper())
        if self.config.context_backend != self._backend:
            self._backend = self.config.context_backend
            self.desktop = select_desktop_provider(self._backend)
            self.resolver = ContextResolver(self.desktop, [HerdrContextProvider()])

    def _after_reload(self) -> None:
        if self.window is not None and self.window.is_shown() and self.window.context is not None:
            self.window.present_context(self.window.context, self.store.sheets, self.config)
        if self.window is not None:
            self.window.show_issues(self.issues)

    @property
    def issues(self) -> list[Issue]:
        return [*self.config_issues, *self.store.issues]

    def _watch_files(self) -> None:
        hints_dir = self.root / "hints"
        hints_dir.mkdir(parents=True, exist_ok=True)
        for target, flag in (
            (hints_dir, Gio.FileMonitorFlags.WATCH_MOVES),
            (self.root / "config.yaml", Gio.FileMonitorFlags.NONE),
        ):
            gfile = Gio.File.new_for_path(str(target))
            try:
                mon = gfile.monitor(flag, None)
            except GLib.Error as e:
                log.warning("cannot watch %s: %s", target, e)
                continue
            mon.connect("changed", self._on_file_changed)
            self._monitors.append(mon)

    def _on_file_changed(self, _mon, gfile, other, event) -> None:
        for f in (gfile, other):
            if f is None:
                continue
            path = Path(f.get_path())
            if path.suffix not in (".yaml", ".yml"):
                continue
            if (tid := self._pending_reload.pop(path, None)) is not None:
                GLib.source_remove(tid)
            self._pending_reload[path] = GLib.timeout_add(DEBOUNCE_MS, self._debounced_reload, path)

    def _debounced_reload(self, path: Path) -> bool:
        self._pending_reload.pop(path, None)
        if path == self.root / "config.yaml":
            self._reload_config()
        elif path.parent == self.root / "hints":
            ok = self.store.reload(path)
            log.info("reloaded %s: %s", path.name, "ok" if ok else "kept last-known-good")
        self._after_reload()
        return False

    # --- commands --------------------------------------------------------------------------

    def show(self) -> dict:
        assert self.window is not None
        self._start_workspace_watch()
        ctx = self.resolver.resolve(self.store.sheets, self.config)
        self._present(ctx)
        workspace = self._current_workspace()
        if workspace is not None:
            self._open[workspace] = ctx
            log.info("overlay open on workspace %s", workspace)
        return {"visible": True, "sheet": ctx.active_sheet, "error": ctx.error}

    def hide(self) -> dict:
        assert self.window is not None
        workspace = self._current_workspace()
        if workspace is not None:
            self._open.pop(workspace, None)
        else:
            self._open.clear()
        self.window.hide_overlay()
        if not self._open:
            self._stop_workspace_watch()
        return {"visible": False}

    def toggle(self) -> dict:
        assert self.window is not None
        self._start_workspace_watch()
        action = toggle_action(self.window.is_shown(), self._current_workspace(), self._open)
        return self.show() if action == "show" else self.hide()

    def _present(self, ctx: ResolvedContext) -> None:
        assert self.window is not None
        self.window.present_context(ctx, self.store.sheets, self.config)
        self.window.show_issues(self.issues)

    def refresh(self) -> dict:
        assert self.window is not None
        if self.window.is_shown():
            return self.show()
        return {"visible": False}

    def dispatch(self, cmd: str) -> dict:
        if cmd == "ping":
            return {
                "pid": os.getpid(),
                "sheets": len(self.store.sheets),
                "issues": len(self.issues),
            }
        if cmd == "reload":
            self.reload_all()
            return {"sheets": len(self.store.sheets), "issues": [str(i) for i in self.issues]}
        return {
            "toggle": self.toggle,
            "show": self.show,
            "hide": self.hide,
            "refresh": self.refresh,
        }[cmd]()

    def edit(self, sheet: HintSheet | None, hint: Hint | None) -> None:
        assert self.window is not None
        if sheet is None:
            self.window.show_message(f"⚠ {translator(self.config.language)('no sheet to edit')}")
            return
        line = hint.location.line if hint is not None else 1
        try:
            open_in_editor(self.config.editor, sheet.path, line, hint.id if hint else sheet.id)
        except EditorError as e:
            self.window.show_message(f"⚠ {e}")

    # --- workspace scoping -----------------------------------------------------------------

    def _start_workspace_watch(self) -> None:
        """Watch the active workspace while any workspace has the overlay open.

        A layer surface has no workspace of its own, so the overlay has to put itself away when
        the compositor leaves the workspace it was opened on, and bring itself back on return.
        Compositors without ``ext-workspace-v1`` keep the old behaviour of showing it everywhere.
        """
        if self.config.workspace_scope != "current":
            return
        if self._watcher is None:
            watcher = WorkspaceWatcher(self._on_workspace_changed)
            if not watcher.start():
                return
            self._watcher = watcher
            self._watch_source = GLibUnix.fd_add_full(
                GLib.PRIORITY_DEFAULT, watcher.fileno(), GLib.IOCondition.IN, self._on_watch_fd
            )

    def _stop_workspace_watch(self) -> None:
        if self._watch_source is not None:
            GLib.source_remove(self._watch_source)
            self._watch_source = None
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        self._open.clear()

    def _current_workspace(self) -> str | None:
        """The active workspace now, not as of the last event we happened to process.

        ``toggle`` arrives over the socket while the workspace change arrives over the Wayland
        connection, so the two race. A round trip settles every pending event first and makes the
        decision the same whichever order they arrive in.
        """
        if self._watcher is None:
            return None
        self._watcher.roundtrip()
        return self._watcher.active()

    def _on_watch_fd(self, _fd, _condition) -> bool:
        if self._watcher is None or not self._watcher.dispatch():
            self._watch_source = None
            self._stop_workspace_watch()
            return False
        return True

    def _on_workspace_changed(self, active: str | None) -> None:
        # Called from inside the watcher's own event dispatch; touching the connection here would
        # act on it while it is still being read. Decide on the next main-loop turn instead.
        GLib.idle_add(self._apply_workspace)

    def _apply_workspace(self) -> bool:
        if self.window is None or self._watcher is None:
            return False
        known = self._watcher.known()
        for gone in set(self._open) - known:  # a workspace the compositor dropped
            del self._open[gone]
        active = self._watcher.active()
        if workspace_action(active, self._open) == "restore":
            log.info("workspace %s: restoring the overlay", active)
            self._present(self._open[active])
        elif self.window.is_shown():
            log.info("workspace %s: hiding the overlay", active)
            self.window.hide_overlay()
        return False

    def _refocus(self, view_ref: str | None) -> None:
        if view_ref is not None and not self.desktop.focus_view(view_ref):
            log.info("could not return focus to toplevel %s", view_ref)

    # --- socket server ---------------------------------------------------------------------

    def _listen(self) -> None:
        if self.socket_file.exists():
            try:
                ipc.send_command("ping", self.socket_file, timeout=0.5)
            except ipc.DaemonUnavailable:
                self.socket_file.unlink()  # stale socket from a dead daemon
            else:
                raise SystemExit(f"wayhintd already running on {self.socket_file}")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.setblocking(False)
        srv.bind(str(self.socket_file))
        os.chmod(self.socket_file, 0o600)
        srv.listen(8)
        self._server = srv
        GLib.io_add_watch(srv.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._on_accept)

    def _on_accept(self, _fd, _cond) -> bool:
        assert self._server is not None
        try:
            conn, _ = self._server.accept()
        except OSError:
            return True
        conn.setblocking(False)
        buf = bytearray()
        GLib.io_add_watch(
            conn.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._on_data, conn, buf
        )
        return True

    def _on_data(self, _fd, cond, conn: socket.socket, buf: bytearray) -> bool:
        try:
            chunk = conn.recv(4096)
        except BlockingIOError:
            return True
        except OSError:
            conn.close()
            return False
        if chunk:
            buf.extend(chunk)
        done = (not chunk) or buf.endswith(b"\n") or len(buf) > ipc.MAX_MESSAGE
        if not done:
            return True
        reply = ipc.handle_request(bytes(buf), self.dispatch)
        try:
            conn.sendall(ipc.encode(reply))
        except OSError:
            pass
        conn.close()
        return False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wayhintd", description="wayhint overlay daemon")
    p.add_argument("--config-dir", help="directory with config.yaml and hints/ (default: XDG)")
    p.add_argument("--socket", help="override the Unix socket path")
    p.add_argument("-v", "--verbose", action="store_true", help="log at info level")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    root = Path(args.config_dir) if args.config_dir else config_dir()
    sock = Path(args.socket) if args.socket else ipc.socket_path()
    daemon = Daemon(root, sock)
    app = Gtk.Application(
        application_id="dev.wayhint.daemon", flags=Gio.ApplicationFlags.NON_UNIQUE
    )
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda *_: (app.quit(), False)[1])

    def on_activate(a: Gtk.Application) -> None:
        try:
            daemon.start(a)
        except SystemExit as e:
            print(e, file=sys.stderr)
            a.quit()
            raise
        a.hold()  # stay alive with the window hidden

    app.connect("activate", on_activate)
    app.connect("shutdown", lambda *_: daemon.stop())
    try:
        return app.run(None)
    except SystemExit as e:
        return 1 if e.code else 0


if __name__ == "__main__":
    sys.exit(main())
