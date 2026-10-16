"""Pick the desktop context backend (config ``context.backend``).

``wayland`` is the generic wlr-foreign-toplevel adapter and works on labwc and Wayfire alike.
``wayfire`` is the compositor-specific IPC adapter. ``auto`` uses ``wayland`` and falls back to
``wayfire`` only when the compositor lacks the foreign-toplevel protocol and ``WAYFIRE_SOCKET``
is set. The choice is made on the first successful call and then kept. A failure that is not
"this cannot work here" (``ProviderUnavailable``) -- a round trip that broke, a display not up
yet at autostart -- is that one call's failure, and does not move the choice.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from wayhint.context.base import (
    ContextError,
    DesktopContextProvider,
    DesktopSnapshot,
    ProviderUnavailable,
)
from wayhint.models import OutputInfo

log = logging.getLogger(__name__)

Factory = Callable[[], DesktopContextProvider]


def _wayland() -> DesktopContextProvider:
    from wayhint.context.wayland import WaylandContextProvider

    return WaylandContextProvider()


def _wayfire() -> DesktopContextProvider:
    from wayhint.context.wayfire import WayfireContextProvider

    return WayfireContextProvider()


class AutoDesktopProvider:
    def __init__(
        self,
        primary: Factory = _wayland,
        fallback: Factory = _wayfire,
        fallback_available: Callable[[], bool] = lambda: bool(os.environ.get("WAYFIRE_SOCKET")),
    ) -> None:
        self._primary = primary()
        self._fallback_factory = fallback
        self._fallback_available = fallback_available
        self._chosen: DesktopContextProvider | None = None

    def _candidates(self) -> list[DesktopContextProvider]:
        if self._chosen is not None:
            return [self._chosen]
        out: list[DesktopContextProvider] = [self._primary]
        if self._fallback_available():
            out.append(self._fallback_factory())
        return out

    def snapshot(self) -> DesktopSnapshot:
        last: ContextError | None = None
        for p in self._candidates():
            try:
                snap = p.snapshot()
            except ProviderUnavailable as e:
                last = e
                continue
            if self._chosen is None:
                self._chosen = p
                log.info("desktop backend: %s", p.__class__.__name__)
            return snap
        raise last or ContextError("no desktop context backend available")

    def find_output(self, name: str) -> OutputInfo | None:
        for p in self._candidates():
            try:
                return p.find_output(name)
            except ProviderUnavailable:
                continue
            except ContextError:
                return None
        return None

    def focus_view(self, view_ref: str) -> bool:
        # A view ref names a window in the backend that reported it: the chosen one.
        return (self._chosen or self._primary).focus_view(view_ref)


def select_desktop_provider(backend: str) -> DesktopContextProvider:
    if backend == "wayland":
        return _wayland()
    if backend == "wayfire":
        return _wayfire()
    return AutoDesktopProvider()
