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
    """Looks inside a host application (a terminal) for the thing the user is really using.

    Two kinds of provider share this one interface, and the difference is only what they ask:

    * **terminal introspection** -- the terminal does not know what runs in it, so the provider
      finds out for itself (``ProcAdapter`` walks ``/proc``).
    * **nested resolver** -- the host application answers for itself and the provider just asks
      it (``HerdrContextProvider`` runs ``herdr``).

    ``foreground_process`` receives the same ``app_id`` the resolver passed to ``applies_to``.
    A provider that answers for itself ignores it; one that has to find the window's process in
    ``/proc`` reads the pid out of it (DECISIONS 0027).

    The registration order is decided in one place, ``daemon._nested_providers()``.
    """

    def applies_to(self, app_id: str | None) -> bool: ...

    def foreground_process(self, app_id: str | None = None) -> ProcessInfo | None: ...
