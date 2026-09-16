"""ContextResolver: desktop snapshot → sheet match → optional nested provider → ResolvedContext.

Flow (DESIGN §56):

1. Desktop provider gives app_id / title / toplevel ref / output.
   Failure → ``ResolvedContext.error``.
2. ``match_app`` picks the desktop sheet.
3. If a nested provider applies to that app_id, ask it for the foreground process and
   ``match_process`` for a child sheet. Any failure falls back to the desktop sheet alone.
4. Output priority: sheet ``display.output`` override → active view's output → focused output →
   global ``overlay.output`` fallback → None (UI uses the default monitor).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from wayhint.config import GlobalConfig
from wayhint.context.base import ContextError, DesktopContextProvider, NestedContextProvider
from wayhint.matcher import match_app, match_process
from wayhint.models import HintSheet, OutputInfo, ResolvedContext

log = logging.getLogger(__name__)


class ContextResolver:
    def __init__(
        self,
        desktop: DesktopContextProvider,
        nested: Sequence[NestedContextProvider] = (),
        find_output: Callable[[str], OutputInfo | None] | None = None,
    ) -> None:
        self.desktop = desktop
        self.nested = list(nested)
        self._find_output = find_output or desktop.find_output

    def resolve(self, sheets: Sequence[HintSheet], config: GlobalConfig) -> ResolvedContext:
        try:
            snap = self.desktop.snapshot()
        except ContextError as e:
            return ResolvedContext(error=str(e))

        desktop_sheet = match_app(sheets, snap.app_id)
        active = desktop_sheet
        parent_id = None
        proc = None
        if desktop_sheet is not None:
            for provider in self.nested:
                if not provider.applies_to(snap.app_id):
                    continue
                try:
                    proc = provider.foreground_process()
                except Exception:  # adapter bug must not take the overlay down
                    log.exception("nested provider failed")
                    proc = None
                parent_id = desktop_sheet.id
                child = match_process(sheets, proc)
                if child is not None and child is not desktop_sheet:
                    active = child
                break

        output = self._pick_output(active, snap.output, snap.focused_output, config)
        return ResolvedContext(
            desktop_app=snap.app_id,
            desktop_title=snap.title,
            output=output,
            view_ref=snap.view_ref,
            parent_context=parent_id,
            foreground_process=proc,
            active_sheet=active.id if active is not None else None,
        )

    def _pick_output(
        self,
        sheet: HintSheet | None,
        view_output: OutputInfo | None,
        focused_output: OutputInfo | None,
        config: GlobalConfig,
    ) -> OutputInfo | None:
        override = sheet.display.output if sheet is not None else None
        if override:
            found = self._lookup(override)
            if found is not None:
                return found
        if view_output is not None:
            return view_output
        if focused_output is not None:
            return focused_output
        if config.display.output:
            return self._lookup(config.display.output)
        return None

    def _lookup(self, name: str) -> OutputInfo | None:
        try:
            return self._find_output(name)
        except Exception:
            log.debug("output lookup failed for %r", name)
            return None
