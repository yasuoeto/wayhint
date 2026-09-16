"""Provider interfaces. Everything above this layer works with these and with models only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from wayhint.models import OutputInfo, ProcessInfo


class ContextError(RuntimeError):
    """A provider could not answer. Message is safe to show in the overlay."""


@dataclass(frozen=True)
class DesktopSnapshot:
    app_id: str | None
    title: str | None
    view_ref: str | None
    output: OutputInfo | None
    focused_output: OutputInfo | None


class DesktopContextProvider(Protocol):
    def snapshot(self) -> DesktopSnapshot: ...

    def find_output(self, name: str) -> OutputInfo | None: ...

    def focus_view(self, view_ref: str) -> bool: ...


class NestedContextProvider(Protocol):
    """Looks inside a host application (a terminal) for the thing the user is really using."""

    def applies_to(self, app_id: str | None) -> bool: ...

    def foreground_process(self) -> ProcessInfo | None: ...
