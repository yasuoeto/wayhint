"""Herdr adapter: focused pane → foreground process. The only module that runs ``herdr``.

Herdr 0.8.2 output (recorded in ``docs/PHASE0.md``)::

    herdr pane current
      {"result": {"pane": {"pane_id": "wG:p1", "focused": true, ...}}}
    herdr pane process-info --pane wG:p1
      {"result": {"process_info": {
          "foreground_process_group_id": 123,
          "foreground_processes": [{"pid", "name", "argv", "cmdline", "cwd"}]}}}

``--pane`` is always passed: without it Herdr answers for the *calling* shell's pane, which is
not the focused one when the daemon was started elsewhere. Output is data, never executed.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence

from wayhint.context.process import process_info_from_mapping
from wayhint.models import ProcessInfo

log = logging.getLogger(__name__)

Runner = Callable[[Sequence[str]], str]
"""Run argv, return stdout. Raise OSError / subprocess.SubprocessError on failure."""


def default_runner(argv: Sequence[str]) -> str:
    proc = subprocess.run(  # noqa: S603 - fixed executable, no shell, argv from code only
        list(argv), capture_output=True, text=True, timeout=3, check=True
    )
    return proc.stdout


class HerdrContextProvider:
    def __init__(
        self,
        executable: str = "herdr",
        app_id_pattern: str = r"herdr",
        runner: Runner = default_runner,
    ) -> None:
        self.executable = executable
        self._app_id_re = re.compile(app_id_pattern, re.IGNORECASE)
        self._run = runner

    def applies_to(self, app_id: str | None) -> bool:
        return bool(app_id) and self._app_id_re.search(app_id) is not None

    def _call(self, *args: str) -> Mapping | None:
        argv = [self.executable, *args]
        try:
            out = self._run(argv)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("herdr %s failed: %s", " ".join(args), e.__class__.__name__)
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            log.warning("herdr %s: output is not JSON", " ".join(args))
            return None
        result = data.get("result") if isinstance(data, Mapping) else None
        return result if isinstance(result, Mapping) else None

    def focused_pane_id(self) -> str | None:
        result = self._call("pane", "current")
        pane = result.get("pane") if result else None
        pane_id = pane.get("pane_id") if isinstance(pane, Mapping) else None
        return pane_id if isinstance(pane_id, str) and pane_id else None

    def foreground_process(self) -> ProcessInfo | None:
        pane_id = self.focused_pane_id()
        if pane_id is None:
            return None
        result = self._call("pane", "process-info", "--pane", pane_id)
        info = result.get("process_info") if result else None
        if not isinstance(info, Mapping):
            return None
        procs = info.get("foreground_processes")
        if not isinstance(procs, list) or not procs:
            return None
        candidates = [p for p in procs if isinstance(p, Mapping)]
        leader = info.get("foreground_process_group_id")
        chosen = next((p for p in candidates if p.get("pid") == leader), None)
        if chosen is None:
            chosen = candidates[-1] if candidates else None
        return process_info_from_mapping(chosen) if chosen is not None else None
