"""``wayhintd``: GTK application holding the overlay, the IPC socket and the file monitors.

Everything is event-driven on the GLib main loop: socket accepts via ``GLib.io_add_watch``,
YAML changes via ``Gio.FileMonitor`` with a short debounce. Context is resolved only on
show/refresh (no polling).
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
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
from wayhint.editor import EditorError, edit_target, open_in_editor  # noqa: E402
from wayhint.i18n import translator  # noqa: E402
from wayhint.matcher import argv_basenames  # noqa: E402
from wayhint.models import Hint, HintSheet, ResolvedContext  # noqa: E402
from wayhint.selection import (  # noqa: E402
    effective_parent_tags,
    same_group,
    sort_hints,
    visible_hints,
)
from wayhint.ui import editmode, style  # noqa: E402
from wayhint.ui.editmode import FormDraft, WorkspaceView  # noqa: E402
from wayhint.ui.window import HintWindow  # noqa: E402
from wayhint.yaml_store import (  # noqa: E402
    Issue,
    SheetStore,
    SheetWriteError,
    append_hint,
    build_hint,
    create_sheet,
    delete_hint,
    load_config,
    match_rule_for_context,
    read_document,
    set_favorite,
    slug,
    swap_hints,
    update_hint,
    write_document,
)

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
        # Workspace key -> what is shown there (context, mode and any unsaved draft). An overlay
        # stays open on the workspace it was opened on until it is closed there, so this outlives
        # switching away and back (DECISIONS 0012, extended by 0014 D4).
        self._open: dict[str, WorkspaceView] = {}
        # One slot for the whole daemon: the last deleted hint, for ``u`` (DESIGN 編集モード §6).
        self._undo: tuple[Path, object] | None = None
        self._shown_key: str | None = None  # which workspace's view the window is showing
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
            on_edit=self.edit,
            on_close=self.hide,
            on_action=self.on_edit_action,
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
        return self._open_here(ctx)

    def hide(self) -> dict:
        assert self.window is not None
        self._open.pop(self._workspace_key(), None)
        self._shown_key = None
        self.window.hide_overlay()
        if not self._open:
            self._stop_workspace_watch()
        return {"visible": False}

    def toggle(self) -> dict:
        assert self.window is not None
        self._start_workspace_watch()
        key = self._workspace_key()
        shown = self._open.get(key)
        if shown is not None and shown.mode == "edit":
            # 0014 D4: while editing, the hotkey is hide / show. "What I am looking at" is what
            # is being written, so it must come back unchanged -- even from another window.
            if self.window.is_shown():
                log.info("hotkey during edit: hiding, keeping the draft")
                self._sync_shown()
                self.window.hide_overlay()
                return {"visible": False, "mode": "edit"}
            log.info("hotkey during edit: showing the draft again")
            self._present(key, shown)
            return {"visible": True, "sheet": shown.context.active_sheet, "mode": "edit"}
        ctx = self.resolver.resolve(self.store.sheets, self.config)
        action = toggle_action(
            shown is not None, shown is not None and shown.target_key() == ctx.target_key()
        )
        if action == "hide":
            return self.hide()
        if action == "replace":
            log.info(
                "hotkey from another window: replacing %s with %s",
                shown.context.active_sheet,
                ctx.active_sheet,
            )
        return self._open_here(ctx)

    def _open_here(self, ctx: ResolvedContext) -> dict:
        """Present a context and record it as what is open on the current workspace."""
        key = self._workspace_key()
        view = WorkspaceView(context=ctx)
        self._open[key] = view
        self._present(key, view)
        log.info("overlay open on workspace %s: sheet %s", key or "-", ctx.active_sheet)
        return {"visible": True, "sheet": ctx.active_sheet, "error": ctx.error}

    def _present(self, key: str, view: WorkspaceView) -> None:
        """Put ``view`` on screen with its mode and draft; the window keeps no state of its own."""
        assert self.window is not None
        self._shown_key = key
        self.window.present_context(view.context, self.store.sheets, self.config)
        self.window.show_issues(self.issues)
        self.window.set_mode(view.mode, refocus=False)
        if view.form is not None:
            self.window.open_form(view.form)

    def _sync_view(self, view: WorkspaceView) -> None:
        """Copy the window's live state back into the workspace record before losing the screen."""
        assert self.window is not None
        view.mode = self.window.mode
        view.form = self.window.form_draft()

    def _current_view(self) -> WorkspaceView | None:
        return self._open.get(self._workspace_key())

    def _sync_shown(self) -> None:
        """Save the window's live mode and draft into the view it belongs to."""
        view = self._open.get(self._shown_key) if self._shown_key is not None else None
        if view is not None:
            self._sync_view(view)

    def context_reply(self) -> dict:
        """What the CLI needs to pick a sheet (DECISIONS 0014 D11).

        Deliberately small: no full argv, no cmdline. The reply has to fit in one 4096-byte
        message, and a command line can carry anything.
        """
        ctx = self.resolver.resolve(self.store.sheets, self.config)
        proc = ctx.foreground_process
        return {
            "active_sheet": ctx.active_sheet,
            "parent_context": ctx.parent_context,
            "desktop_app": ctx.desktop_app,
            "process": (
                {"name": proc.name, "argv_basenames": argv_basenames(proc.argv)} if proc else None
            ),
            "error": ctx.error,  # why there is no sheet, when there is none
        }

    def enter_edit_mode(self) -> dict:
        """Show the overlay if needed and switch it to edit mode (DESIGN 編集モード §1).

        Refused when *the sheet being shown* is only there as last-known-good: that document
        cannot be round-tripped, so writing it would throw the broken file away. Another sheet
        being broken does not stop this one from being edited. No grab is taken when refused.
        """
        assert self.window is not None
        view = self._current_view()
        if view is None or not self.window.is_shown():
            self.show()
            view = self._current_view()
        if view is None:
            return {"ok": False, "error": "nothing to edit"}
        stale = self._stale_sheet(view.context.active_sheet)
        if stale is not None:
            tr = translator(self.config.language)
            message = f"{tr('cannot edit while the YAML is broken')}: {stale.name}"
            self.window.show_message(f"⚠ {message}")
            return {"ok": False, "error": message}
        view.mode = "edit"
        self.window.set_mode("edit")
        return {"visible": True, "mode": "edit", "sheet": view.context.active_sheet}

    # --- edit mode actions -----------------------------------------------------------------

    def on_edit_action(self, action: str, payload: dict | None) -> None:
        """Everything the overlay's keys ask for. The window never writes YAML itself."""
        assert self.window is not None
        tr = translator(self.config.language)
        payload = payload or {}
        try:
            self._edit_action(action, payload, tr)
        except (SheetWriteError, OSError) as e:
            log.warning("edit action %s failed: %s", action, e)
            self.window.show_message(f"⚠ {e}")

    def _edit_action(self, action: str, payload: dict, tr) -> None:
        assert self.window is not None
        view = self._current_view()
        if action == "enter-edit":
            self.enter_edit_mode()
            return
        if view is None:
            return
        if action == editmode.EXIT_EDIT:
            view.mode = "normal"
            view.form = None
            self.window.set_mode("normal")
            return
        if action == editmode.ADD:
            self._open_quick_add(view)
            return
        if action == editmode.OPEN_FORM:
            self._open_edit_form(view, payload)
            return
        if action == editmode.FORM_PARENT:
            self.window.toggle_form_parent()
            draft = self.window.form_draft()
            if draft is not None:
                self._refuse_stale_target(view, draft, tr)  # the target changed; re-check it
            return
        if action == editmode.FORM_SAVE:
            self._save_draft(view, payload["draft"], tr)
            return
        if action == editmode.UNDO:
            self._undo_delete(tr)
            return
        if action == editmode.DELETE_COMMIT:
            self._delete(payload, tr)
            return
        if action == editmode.FAVORITE:
            self._toggle_favorite(payload)
            return
        if action in (editmode.MOVE_DOWN, editmode.MOVE_UP):
            self._move(payload, down=action == editmode.MOVE_DOWN, tr=tr)
            return
        log.debug("unhandled edit action: %s", action)

    def _hint_by_id(self, hint_id: str) -> tuple[Hint, HintSheet] | None:
        for sheet in self.store.sheets:
            for hint in sheet.hints:
                if hint.id == hint_id:
                    return hint, sheet
        return None

    def _sheet_by_id(self, sheet_id: str | None) -> HintSheet | None:
        return next((s for s in self.store.sheets if s.id == sheet_id), None)

    def _stale_sheet(self, sheet_id: str | None) -> Path | None:
        """The sheet's path when it is shown as last-known-good, else ``None``."""
        sheet = self._sheet_by_id(sheet_id)
        if sheet is None:
            return None
        return sheet.path if editmode.sheet_is_stale(sheet.path, self.store.errors) else None

    def _refuse_stale_target(self, view: WorkspaceView, draft: FormDraft, tr) -> bool:
        """Put a message in the form when the sheet this save would write is broken (0014 D2)."""
        assert self.window is not None
        if draft.hint_id is not None:
            found = self._hint_by_id(draft.hint_id)
            sheet_id = found[1].id if found else None
        else:
            sheet_id = editmode.target_sheet_id(draft, view.context)
        stale = self._stale_sheet(sheet_id)
        message = f"{tr('cannot edit while the YAML is broken')}: {stale.name}" if stale else None
        self.window.show_form_error(message)
        return stale is not None

    def _open_quick_add(self, view: WorkspaceView) -> None:
        """Quick add works even when the context has no sheet: the sheet is made on save."""
        assert self.window is not None
        warning = None
        sheet = self._sheet_by_id(view.context.active_sheet)
        if sheet is None:
            _match, warning = match_rule_for_context(view.context)
        draft = FormDraft(sheet_id=sheet.id if sheet else None, fields={"kind": "shortcut"})
        draft.warning = warning
        view.form = draft
        self.window.open_form(draft)

    def _open_edit_form(self, view: WorkspaceView, payload: dict) -> None:
        assert self.window is not None
        found = self._hint_by_id(payload.get("hint_id", ""))
        if found is None:
            return
        hint, sheet = found
        draft = editmode.draft_from_hint(hint, sheet.id)
        view.form = draft
        self.window.open_form(draft)

    def _save_draft(self, view: WorkspaceView, draft: FormDraft, tr) -> None:
        assert self.window is not None
        if self._refuse_stale_target(view, draft, tr):
            return
        fields = editmode.draft_fields(draft)
        if draft.hint_id is not None:
            found = self._hint_by_id(draft.hint_id)
            if found is None:
                self.window.show_message(f"⚠ {tr('that sheet is gone')}")
                return
            _hint, sheet = found
            self._write(sheet.path, lambda doc: update_hint(doc, draft.hint_id, fields))
            saved_id = draft.hint_id
        else:
            saved_id = self._append_new(view, draft, fields)
            if saved_id is None:
                return
        view.form = None
        self.window.close_form()
        self.window.show_message(tr("saved {id}").format(id=saved_id))

    def _append_new(self, view: WorkspaceView, draft: FormDraft, fields: dict) -> str | None:
        """Quick add: into the active sheet, the parent sheet, or a sheet made for the context."""
        assert self.window is not None
        sheet_id = view.context.parent_context if draft.to_parent else draft.sheet_id
        sheet = self._sheet_by_id(sheet_id)
        if sheet is not None:
            if draft.to_parent:
                child = self._sheet_by_id(view.context.active_sheet)
                tags = effective_parent_tags(child, self.config.parent_tags)
                if tags:
                    fields["tags"] = list(tags)
            fields["id"] = slug(str(fields["title"]), [h.id for h in sheet.hints])
            fields["learned"] = _dt.date.today().isoformat()
            self._write(sheet.path, lambda doc: append_hint(doc, build_hint(fields)))
            return str(fields["id"])
        fields["id"] = slug(str(fields["title"]))
        fields["learned"] = _dt.date.today().isoformat()
        path, doc = create_sheet(
            view.context,
            build_hint(fields),
            self.config,
            hints_dir=self.root / "hints",
            existing_ids=[s.id for s in self.store.sheets],
        )
        write_document(path, doc)
        log.info("created sheet %s for a context that had none", path)
        return str(fields["id"])

    def _delete(self, payload: dict, tr) -> None:
        assert self.window is not None
        found = self._hint_by_id(payload.get("hint_id", ""))
        if found is None:
            return
        hint, sheet = found
        removed: list[object] = []
        self._write(sheet.path, lambda doc: removed.append(delete_hint(doc, hint.id)))
        if removed:
            self._undo = (sheet.path, removed[0])
        self.window.show_message(tr("deleted {id}").format(id=hint.id))

    def _undo_delete(self, tr) -> None:
        assert self.window is not None
        if self._undo is None:
            self.window.show_message(f"⚠ {tr('nothing to undo')}")
            return
        path, node = self._undo
        if not path.exists():
            self.window.show_message(f"⚠ {tr('that sheet is gone')}")
            return
        self._write(path, lambda doc: append_hint(doc, node))
        self._undo = None
        self.window.show_message(tr("restored {id}").format(id=node.get("id", "?")))

    def _toggle_favorite(self, payload: dict) -> None:
        found = self._hint_by_id(payload.get("hint_id", ""))
        if found is None:
            return
        hint, sheet = found
        self._write(sheet.path, lambda doc: set_favorite(doc, hint.id, not hint.favorite))

    def _move(self, payload: dict, down: bool, tr) -> None:
        """Swap with the hint next to it on screen, inside the same group and sheet (D8)."""
        assert self.window is not None
        found = self._hint_by_id(payload.get("hint_id", ""))
        if found is None:
            return
        hint, sheet = found
        shown = sort_hints(
            visible_hints(
                self._sheet_by_id(self._current_sheet_id()),
                self._sheet_by_id(self._current_parent_id()),
                self.config.parent_tags,
            )
        )
        index = next((i for i, h in enumerate(shown) if h.id == hint.id), None)
        if index is None:
            return
        other_index = index + 1 if down else index - 1
        if not 0 <= other_index < len(shown):
            return
        other = shown[other_index]
        if not same_group(hint, other) or other.location.file != hint.location.file:
            self.window.show_message(f"⚠ {tr('cannot move past another group')}")
            return
        self._write(sheet.path, lambda doc: swap_hints(doc, hint.id, other.id))

    def _current_sheet_id(self) -> str | None:
        view = self._current_view()
        return view.context.active_sheet if view else None

    def _current_parent_id(self) -> str | None:
        view = self._current_view()
        return view.context.parent_context if view else None

    def _write(self, path: Path, mutate) -> None:
        """Read, change, write. Reloading is left to the file monitor (0014 D2)."""
        doc, issues = read_document(path)
        if issues:
            raise SheetWriteError(str(issues[0]))
        mutate(doc)
        write_document(path, doc)

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
            "context": self.context_reply,
            "edit-mode": self.enter_edit_mode,
        }[cmd]()

    def edit(self, sheet: HintSheet | None, hint: Hint | None) -> None:
        assert self.window is not None
        target = edit_target(sheet, hint)
        if target is None:
            self.window.show_message(f"⚠ {translator(self.config.language)('no sheet to edit')}")
            return
        try:
            open_in_editor(self.config.editor, target.file, target.line, target.hint_id)
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

    def _workspace_key(self) -> str:
        """Key for the current workspace, or ``""`` when there is no workspace backend.

        The empty key gives compositors without ``ext-workspace-v1`` a single slot, so the rest of
        the daemon works the same way with and without workspace scoping.

        ``toggle`` arrives over the socket while the workspace change arrives over the Wayland
        connection, so the two race. A round trip settles every pending event first and makes the
        decision the same whichever order they arrive in.
        """
        if self._watcher is None:
            return ""
        self._watcher.roundtrip()
        return self._watcher.active() or ""

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
            self._sync_shown()  # the workspace being left keeps its mode and draft
            self._present(active or "", self._open[active])
        elif self.window.is_shown():
            log.info("workspace %s: hiding the overlay", active)
            self._sync_shown()
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
