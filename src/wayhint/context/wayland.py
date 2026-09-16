"""Generic Wayland adapter via ``wlr-foreign-toplevel-management-unstable-v1``.

Works on any wlroots-based compositor that exposes the protocol (labwc, Wayfire with the
``foreign-toplevel`` plugin, sway, ...). This is the only module allowed to import pywayland.

A fresh connection is opened per call: calls happen only on show/refresh (no polling), and a
short-lived connection cannot go stale across compositor restarts. Toplevel handles therefore do
not survive between calls; ``view_ref`` is ``"<app_id>\\t<title>"`` and is re-resolved on focus.
"""

from __future__ import annotations

import logging
import os
import struct
from dataclasses import dataclass, field

from wayhint.context.base import ContextError, DesktopSnapshot
from wayhint.models import OutputInfo

log = logging.getLogger(__name__)

MANAGER_IFACE = "zwlr_foreign_toplevel_manager_v1"
STATE_ACTIVATED = 2  # zwlr_foreign_toplevel_handle_v1.state
REF_SEP = "\t"


@dataclass
class _Output:
    proxy: object
    name: str | None = None
    width: int = 0
    height: int = 0
    scale: int = 1

    def info(self) -> OutputInfo | None:
        if self.name is None or not self.width or not self.height:
            return None
        s = max(self.scale, 1)
        return OutputInfo(name=self.name, width=self.width // s, height=self.height // s)


@dataclass
class _Toplevel:
    handle: object
    app_id: str | None = None
    title: str | None = None
    states: tuple[int, ...] = ()
    outputs: list[int] = field(default_factory=list)  # ids of _Output entries

    @property
    def activated(self) -> bool:
        return STATE_ACTIVATED in self.states

    @property
    def ref(self) -> str:
        return f"{self.app_id or ''}{REF_SEP}{self.title or ''}"


def decode_states(raw: object) -> tuple[int, ...]:
    """``state`` arrives as a byte array of native uint32 values."""
    if isinstance(raw, (bytes, bytearray, memoryview)):
        data = bytes(raw)
        return tuple(v for (v,) in struct.iter_unpack("=I", data[: len(data) - len(data) % 4]))
    if isinstance(raw, (list, tuple)):
        return tuple(int(v) for v in raw)
    return ()


def pick_active(toplevels: list[_Toplevel]) -> _Toplevel | None:
    return next((t for t in toplevels if t.activated), None)


def find_by_ref(toplevels: list[_Toplevel], ref: str) -> _Toplevel | None:
    """Exact (app_id, title) match first; otherwise the app_id if it identifies one toplevel."""
    exact = [t for t in toplevels if t.ref == ref]
    if len(exact) >= 1:
        return exact[0]
    app_id = ref.split(REF_SEP, 1)[0]
    same_app = [t for t in toplevels if (t.app_id or "") == app_id]
    return same_app[0] if len(same_app) == 1 else None


class _Session:
    """One connection: registry scan, globals bound, toplevel/output state collected."""

    def __init__(self, display_name: str | None) -> None:
        try:
            from pywayland.client import Display
            from pywayland.protocol.wayland import WlOutput, WlSeat

            from wayhint.context._wlr_foreign_toplevel import ZwlrForeignToplevelManagerV1
        except ImportError as e:  # pragma: no cover - depends on the environment
            raise ContextError("pywayland is not installed") from e
        self._WlOutput, self._WlSeat, self._Manager = WlOutput, WlSeat, ZwlrForeignToplevelManagerV1
        self.outputs: dict[int, _Output] = {}
        self.toplevels: list[_Toplevel] = []
        self.seat = None
        self.manager = None
        self.display = Display(display_name)
        try:
            self.display.connect()
        except Exception as e:
            raise ContextError(f"Wayland display unavailable: {e.__class__.__name__}") from e
        try:
            reg = self.display.get_registry()
            reg.dispatcher["global"] = self._on_global
            reg.dispatcher["global_remove"] = _ignore
            for _ in range(3):  # registry → bound globals → toplevel handle events
                self.display.roundtrip()
        except Exception as e:
            self.close()
            raise ContextError(f"Wayland registry scan failed: {e.__class__.__name__}") from e
        if self.manager is None:
            self.close()
            raise ContextError("compositor does not provide wlr-foreign-toplevel-management")

    def close(self) -> None:
        # Destroy every proxy before disconnecting: pywayland proxies that are garbage
        # collected after the display is gone dereference freed memory.
        for t in self.toplevels:
            _quiet(t.handle.destroy)
        if self.manager is not None:
            _quiet(self.manager.stop)
            _quiet(self.manager.destroy)
        for out in self.outputs.values():
            _quiet(out.proxy.release if hasattr(out.proxy, "release") else out.proxy.destroy)
        if self.seat is not None:
            _quiet(self.seat.destroy)
        self.toplevels.clear()
        self.outputs.clear()
        self.manager = self.seat = None
        _quiet(self.display.disconnect)

    # --- registry ---------------------------------------------------------------------------

    def _on_global(self, reg, name: int, iface: str, version: int) -> None:
        if iface == MANAGER_IFACE:
            self.manager = reg.bind(name, self._Manager, min(version, 3))
            self.manager.dispatcher["toplevel"] = self._on_toplevel
            self.manager.dispatcher["finished"] = _ignore
        elif iface == "wl_output":
            proxy = reg.bind(name, self._WlOutput, min(version, 4))
            out = self.outputs[id(proxy)] = _Output(proxy)
            proxy.dispatcher["mode"] = lambda p, flags, w, h, refresh: _set(out, width=w, height=h)
            proxy.dispatcher["scale"] = lambda p, s: _set(out, scale=s)
            proxy.dispatcher["name"] = lambda p, n: _set(out, name=n)
            for ev in ("geometry", "done", "description"):
                proxy.dispatcher[ev] = _ignore
        elif iface == "wl_seat" and self.seat is None:
            self.seat = reg.bind(name, self._WlSeat, 1)
            self.seat.dispatcher["capabilities"] = _ignore
            self.seat.dispatcher["name"] = _ignore

    def _on_toplevel(self, manager, handle) -> None:
        t = _Toplevel(handle)
        self.toplevels.append(t)
        handle.dispatcher["app_id"] = lambda h, s: _set(t, app_id=s or None)
        handle.dispatcher["title"] = lambda h, s: _set(t, title=s or None)
        handle.dispatcher["state"] = lambda h, raw: _set(t, states=decode_states(raw))
        handle.dispatcher["output_enter"] = lambda h, o: t.outputs.append(id(o))
        handle.dispatcher["output_leave"] = lambda h, o: _discard(t.outputs, id(o))
        handle.dispatcher["closed"] = lambda h: _discard(self.toplevels, t)
        for ev in ("done", "parent"):
            handle.dispatcher[ev] = _ignore

    # --- queries ----------------------------------------------------------------------------

    def output_of(self, t: _Toplevel) -> OutputInfo | None:
        for oid in t.outputs:
            out = self.outputs.get(oid)
            if out is not None and out.info() is not None:
                return out.info()
        return None

    def output_infos(self) -> list[OutputInfo]:
        return [o.info() for o in self.outputs.values() if o.info() is not None]

    def activate(self, t: _Toplevel) -> bool:
        if self.seat is None:
            return False
        t.handle.activate(self.seat)
        self.display.roundtrip()
        return True


class WaylandContextProvider:
    def __init__(self, display_name: str | None = None) -> None:
        self.display_name = display_name

    def _session(self) -> _Session:
        if not (self.display_name or os.environ.get("WAYLAND_DISPLAY")):
            raise ContextError("WAYLAND_DISPLAY is not set")
        return _Session(self.display_name)

    def snapshot(self) -> DesktopSnapshot:
        s = self._session()
        try:
            active = pick_active(s.toplevels)
            outputs = s.output_infos()
            focused = outputs[0] if len(outputs) == 1 else None  # protocol has no focused output
            if active is None:
                return DesktopSnapshot(None, None, None, None, focused)
            return DesktopSnapshot(
                app_id=active.app_id,
                title=active.title,
                view_ref=active.ref,
                output=s.output_of(active),
                focused_output=focused,
            )
        finally:
            s.close()

    def find_output(self, name: str) -> OutputInfo | None:
        s = self._session()
        try:
            return next((o for o in s.output_infos() if o.name == name), None)
        finally:
            s.close()

    def focus_view(self, view_ref: str) -> bool:
        try:
            s = self._session()
        except ContextError:
            return False
        try:
            t = find_by_ref(s.toplevels, view_ref)
            if t is None:
                return False
            return s.activate(t)
        except Exception as e:  # protocol errors are reported, never propagated into the UI
            log.debug("activate failed: %s", e)
            return False
        finally:
            s.close()


def _ignore(*_args) -> None:
    return None


def _quiet(fn) -> None:
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - best-effort teardown
        log.debug("teardown call failed: %s", e)


def _set(obj, **kw) -> None:
    for k, v in kw.items():
        setattr(obj, k, v)


def _discard(seq: list, item) -> None:
    if item in seq:
        seq.remove(item)
