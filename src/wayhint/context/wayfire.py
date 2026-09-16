"""Wayfire IPC adapter (optional backend). The only module allowed to import PyWayfire.

A fresh socket is opened per call: calls happen only on show/refresh (no polling), and a
short-lived connection cannot go stale across compositor restarts.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from wayhint.context.base import ContextError, DesktopSnapshot
from wayhint.models import OutputInfo

log = logging.getLogger(__name__)


def _output_info(raw: object) -> OutputInfo | None:
    if not isinstance(raw, Mapping):
        return None
    name = raw.get("name")
    geo = raw.get("geometry") or {}
    if not isinstance(name, str) or not isinstance(geo, Mapping):
        return None
    try:
        return OutputInfo(name=name, width=int(geo["width"]), height=int(geo["height"]))
    except (KeyError, TypeError, ValueError):
        return None


class WayfireContextProvider:
    def __init__(self, socket_name: str | None = None) -> None:
        self.socket_name = socket_name

    def _connect(self):
        try:
            from wayfire import WayfireSocket
        except ImportError as e:  # pragma: no cover - depends on the environment
            raise ContextError("PyWayfire is not installed") from e
        try:
            return WayfireSocket(self.socket_name)
        except Exception as e:  # PyWayfire raises plain Exception when the socket is missing
            raise ContextError(f"Wayfire IPC unavailable: {e.__class__.__name__}") from e

    def snapshot(self) -> DesktopSnapshot:
        sock = self._connect()
        try:
            view = _safe(sock.get_focused_view)
            focused_output = _output_info(_safe(sock.get_focused_output))
            output = None
            app_id = title = None
            view_ref = None
            if isinstance(view, Mapping):
                app_id = view.get("app-id") or None
                title = view.get("title") or None
                view_ref = str(view["id"]) if isinstance(view.get("id"), int) else None
                out_id = view.get("output-id")
                if isinstance(out_id, int):
                    output = _output_info(_safe(lambda: sock.get_output(out_id)))
            return DesktopSnapshot(
                app_id=app_id,
                title=title,
                view_ref=view_ref,
                output=output or focused_output,
                focused_output=focused_output,
            )
        finally:
            _safe(sock.close)

    def find_output(self, name: str) -> OutputInfo | None:
        sock = self._connect()
        try:
            outputs = _safe(sock.list_outputs) or []
            for raw in outputs:
                info = _output_info(raw)
                if info is not None and info.name == name:
                    return info
            return None
        finally:
            _safe(sock.close)

    def focus_view(self, view_ref: str) -> bool:
        try:
            view_id = int(view_ref)
            sock = self._connect()
        except (ValueError, ContextError):
            return False
        try:
            result = _safe(lambda: sock.set_focus(view_id))
            return isinstance(result, Mapping) and result.get("result") == "ok"
        finally:
            _safe(sock.close)


def _safe(fn):
    try:
        return fn()
    except Exception as e:  # IPC errors are reported, never propagated into the UI
        log.debug("wayfire ipc call failed: %s", e)
        return None
