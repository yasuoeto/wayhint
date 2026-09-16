"""Active-workspace watcher via ``ext-workspace-v1``.

A layer surface belongs to an output, not to a workspace, so the overlay stays visible when the
compositor switches workspaces. To scope it to the workspace it was opened on, the daemon watches
the active workspace and hides the overlay when it changes.

The connection is open only while the overlay is visible: nothing runs, and nothing is connected,
when it is hidden. Events drive every update, so there is no polling. The daemon owns the main
loop; this module only exposes a file descriptor and a dispatch call, and imports no GLib.

Compositors without the protocol are handled by :meth:`WorkspaceWatcher.start` returning False;
the caller then keeps the previous behaviour of showing the overlay on every workspace.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Container, Mapping

log = logging.getLogger(__name__)

MANAGER_IFACE = "ext_workspace_manager_v1"
STATE_ACTIVE = 1  # ext_workspace_handle_v1.state.active


def workspace_key(ws_id: str | None, name: str | None, handle_id: int) -> str:
    """Stable identity for one workspace within a single connection.

    ``id`` is optional in the protocol and labwc 0.20.2 does not send it, so ``name`` is the usual
    key. The handle's object id is the last resort: it is stable for as long as the connection
    lives, which is exactly as long as a watcher is running.
    """
    return ws_id or name or f"handle:{handle_id}"


def active_key(workspaces: Mapping[str, int]) -> str | None:
    """Key of the active workspace, or None when the compositor reports none.

    ``workspaces`` maps key to the state bitfield. More than one active workspace is possible with
    several workspace groups (one per output); the overlay lives on one output, so the first is
    taken and the rest ignored.
    """
    for key, state in workspaces.items():
        if state & STATE_ACTIVE:
            return key
    return None


def toggle_action(open_here: bool, shows_the_same: bool) -> str:
    """``"show"``, ``"replace"`` or ``"hide"`` for a ``toggle`` request.

    The hotkey means "hints for what I am looking at now". Pressing it while the hints for another
    window are up should swap them, not put them away: closing is only what the user wants when
    the hints already on screen are the ones the key would bring up.

    ``open_here`` is a property of the workspace, not of the window, and is what settles the race
    between the hotkey on the socket and the workspace change on the Wayland connection. Asking
    "is it open on this workspace" gives the same answer whichever arrives first, where asking
    "is the window visible" does not.
    """
    if not open_here:
        return "show"
    return "hide" if shows_the_same else "replace"


def workspace_action(current: str | None, open_on: Container[str]) -> str:
    """``"restore"`` or ``"hide"`` after the active workspace changed.

    Each workspace keeps whatever the user opened there until they close it, so arriving at a
    workspace with an overlay puts it back rather than making the user press the hotkey again.
    """
    if current is not None and current in open_on:
        return "restore"
    return "hide"


class WorkspaceWatcher:
    """One Wayland connection bound to ``ext_workspace_manager_v1``.

    ``start`` connects and reads the initial state, ``dispatch`` must be called when ``fileno``
    becomes readable, and ``stop`` tears the connection down. ``on_change`` fires once per
    protocol ``done`` event in which the active workspace changed.
    """

    def __init__(
        self, on_change: Callable[[str | None], None], display_name: str | None = None
    ) -> None:
        self._on_change = on_change
        self._display_name = display_name
        self._display = None
        self._manager = None
        self._groups: list = []
        self._handles: dict[int, object] = {}
        self._state: dict[str, int] = {}
        self._keys: dict[int, str] = {}
        self._active: str | None = None
        self._ready = False  # suppress the notification for the initial state

    # --- lifecycle -------------------------------------------------------------------------

    def start(self) -> bool:
        """Connect and bind. False when unavailable; the caller then does without."""
        if not (self._display_name or os.environ.get("WAYLAND_DISPLAY")):
            return False
        try:
            from pywayland.client import Display
            from pywayland.protocol.ext_workspace_v1 import ExtWorkspaceManagerV1
        except ImportError:  # pragma: no cover - depends on the environment
            log.info("pywayland missing; workspace scoping disabled")
            return False
        self._manager_class = ExtWorkspaceManagerV1
        try:
            self._display = Display(self._display_name)
            self._display.connect()
            registry = self._display.get_registry()
            registry.dispatcher["global"] = self._on_global
            registry.dispatcher["global_remove"] = _ignore
            for _ in range(3):  # registry -> manager -> workspace handles and their state
                self._display.roundtrip()
        except Exception as e:  # noqa: BLE001 - any failure means "no workspace scoping"
            log.info("workspace watcher unavailable: %s", e.__class__.__name__)
            self.stop()
            return False
        if self._manager is None:
            log.info("compositor does not provide %s; workspace scoping disabled", MANAGER_IFACE)
            self.stop()
            return False
        self._active = active_key(self._state)
        self._ready = True
        return True

    def stop(self) -> None:
        # Destroy proxies before disconnecting: pywayland proxies collected after the display is
        # gone dereference freed memory (DECISIONS 0010).
        for handle in self._handles.values():
            _quiet(handle.destroy)
        for group in self._groups:
            _quiet(group.destroy)
        if self._manager is not None:
            _quiet(self._manager.stop)
        self._handles.clear()
        self._groups.clear()
        self._state.clear()
        self._keys.clear()
        self._manager = None
        self._active = None
        self._ready = False
        if self._display is not None:
            _quiet(self._display.disconnect)
            self._display = None

    # --- main-loop interface ---------------------------------------------------------------

    def fileno(self) -> int:
        assert self._display is not None
        return self._display.get_fd()

    def dispatch(self) -> bool:
        """Drain the socket and run the handlers. False when the connection is gone.

        Call this when the descriptor is readable. ``read`` is what actually empties the socket:
        ``dispatch(block=False)`` only runs events that are already queued, so calling it alone
        leaves the descriptor readable forever and the caller's watch spins at full CPU.
        """
        if self._display is None:
            return False
        try:
            self._display.flush()
            self._display.read()
            self._display.dispatch(block=False)
            self._display.flush()
        except Exception as e:  # noqa: BLE001 - a dead connection must not take the daemon down
            log.info("workspace watcher connection lost: %s", e.__class__.__name__)
            return False
        return True

    def roundtrip(self) -> bool:
        """Settle every event the compositor has already sent. False when the connection died."""
        if self._display is None:
            return False
        try:
            self._display.roundtrip()
        except Exception as e:  # noqa: BLE001 - a dead connection must not take the daemon down
            log.info("workspace watcher round trip failed: %s", e.__class__.__name__)
            return False
        return True

    def active(self) -> str | None:
        return self._active

    def known(self) -> set[str]:
        """Every workspace the compositor currently reports."""
        return set(self._state)

    # --- protocol --------------------------------------------------------------------------

    def _on_global(self, registry, name: int, iface: str, version: int) -> None:
        if iface != MANAGER_IFACE:
            return
        self._manager = registry.bind(name, self._manager_class, min(version, 1))
        self._manager.dispatcher["workspace_group"] = self._on_group
        self._manager.dispatcher["workspace"] = self._on_workspace
        self._manager.dispatcher["done"] = self._on_done
        self._manager.dispatcher["finished"] = _ignore

    def _on_group(self, manager, group) -> None:
        self._groups.append(group)
        for event in ("capabilities", "output_enter", "output_leave", "removed"):
            group.dispatcher[event] = _ignore
        for event in ("workspace_enter", "workspace_leave"):
            group.dispatcher[event] = _ignore

    def _on_workspace(self, manager, handle) -> None:
        oid = id(handle)
        self._handles[oid] = handle
        self._keys[oid] = workspace_key(None, None, oid)
        handle.dispatcher["id"] = lambda h, value: self._rekey(oid, ws_id=value)
        handle.dispatcher["name"] = lambda h, value: self._rekey(oid, name=value)
        handle.dispatcher["state"] = lambda h, value: self._set_state(oid, int(value))
        for event in ("coordinates", "capabilities"):
            handle.dispatcher[event] = _ignore
        handle.dispatcher["removed"] = lambda h: self._remove(oid)

    def _rekey(self, oid: int, ws_id: str | None = None, name: str | None = None) -> None:
        old = self._keys.get(oid)
        new = workspace_key(ws_id, name, oid)
        self._keys[oid] = new
        if old is not None and old in self._state:
            self._state[new] = self._state.pop(old)

    def _set_state(self, oid: int, state: int) -> None:
        self._state[self._keys[oid]] = state

    def _remove(self, oid: int) -> None:
        key = self._keys.pop(oid, None)
        if key is not None:
            self._state.pop(key, None)
        self._handles.pop(oid, None)

    def _on_done(self, manager) -> None:
        current = active_key(self._state)
        if current == self._active:
            return
        self._active = current
        if self._ready:  # the state read during start() is not a change
            self._on_change(current)


def _ignore(*_args) -> None:
    return None


def _quiet(fn) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - best-effort teardown
        log.debug("workspace teardown call failed: %s", e)
