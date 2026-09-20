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

Herdr is also asked with ``HERDR_*`` stripped from the environment. ``pane current`` answers for
``HERDR_PANE_ID`` when that is set and only falls back to the focused pane when it is not, so a
daemon started from inside a Herdr pane would otherwise be told about the pane it was launched
from for the rest of the session, whatever tab the user switches to (DECISIONS 0028).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence

from wayhint.context.process import process_info_from_mapping
from wayhint.models import ProcessInfo

log = logging.getLogger(__name__)

Runner = Callable[[Sequence[str], float], str]
"""Run argv with a timeout in seconds, return stdout. Raise OSError / SubprocessError."""


CALL_TIMEOUT = 0.75
LOOKUP_BUDGET = 2 * CALL_TIMEOUT
"""Worst case for one context lookup -- the whole lookup, not one call.

The calls are synchronous and run on the GTK main loop, so a herdr that does not answer holds
up drawing and the socket as well. The budget therefore has to stay under
``ipc.CLIENT_TIMEOUT``: otherwise ``wayhint toggle`` reports a timeout and the overlay opens a
moment later anyway. A lookup is normally two calls and a third when the fallback below is
needed, so the budget is spent against a deadline rather than handed to each call in turn.
Both numbers are worst cases -- a lookup measures a few milliseconds.
"""


def _herdr_env(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` without the variables Herdr exports inside a pane.

    Pure, and tested: forgetting it silently pins the adapter to whichever pane the daemon was
    started from (DECISIONS 0028).
    """
    return {key: value for key, value in environ.items() if not key.startswith("HERDR_")}


def default_runner(argv: Sequence[str], timeout: float = CALL_TIMEOUT) -> str:
    proc = subprocess.run(  # noqa: S603 - fixed executable, no shell, argv from code only
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        env=_herdr_env(os.environ),
    )
    return proc.stdout


class HerdrContextProvider:
    def __init__(
        self,
        executable: str = "herdr",
        app_id_pattern: str = r"herdr",
        runner: Runner = default_runner,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.executable = executable
        self._app_id_re = re.compile(app_id_pattern, re.IGNORECASE)
        self._run = runner
        self._clock = clock

    def applies_to(self, app_id: str | None) -> bool:
        return bool(app_id) and self._app_id_re.search(app_id) is not None

    def _call(self, deadline: float, *args: str) -> Mapping | None:
        """One herdr call, given whatever is left of the lookup's budget."""
        timeout = min(CALL_TIMEOUT, deadline - self._clock())
        if timeout <= 0:
            log.warning("herdr %s skipped: the lookup is out of time", " ".join(args))
            return None
        argv = [self.executable, *args]
        try:
            out = self._run(argv, timeout)
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

    def focused_pane_id(self, deadline: float | None = None) -> str | None:
        """The pane the user is looking at.

        ``pane current`` is the answer once ``HERDR_*`` is out of the environment. The
        ``focused: false`` branch is belt and braces: if some other route to the calling pane
        turns up, wayhint asks which pane is focused rather than quietly describing another one.
        """
        deadline = self._clock() + LOOKUP_BUDGET if deadline is None else deadline
        result = self._call(deadline, "pane", "current")
        pane = result.get("pane") if result else None
        if not isinstance(pane, Mapping):
            return None
        if pane.get("focused") is False:
            log.warning("herdr pane current answered an unfocused pane; asking pane list")
            return self._focused_from_list(deadline)
        pane_id = pane.get("pane_id")
        return pane_id if isinstance(pane_id, str) and pane_id else None

    def _focused_from_list(self, deadline: float) -> str | None:
        """Fallback: the one pane in ``pane list`` that says it is focused, or no answer.

        Which Herdr *window* that pane belongs to is not checked; with two Herdr windows open the
        focused pane may not be in the one the compositor has focused (DECISIONS 0028).
        """
        result = self._call(deadline, "pane", "list")
        panes = result.get("panes") if result else None
        if not isinstance(panes, list):
            return None
        focused = [p for p in panes if isinstance(p, Mapping) and p.get("focused") is True]
        if len(focused) != 1:
            log.warning("herdr pane list reported %d focused panes; no answer", len(focused))
            return None
        pane_id = focused[0].get("pane_id")
        return pane_id if isinstance(pane_id, str) and pane_id else None

    def foreground_process(self, app_id: str | None = None) -> ProcessInfo | None:
        # ``app_id`` only picks the provider; Herdr answers for its own focused pane.
        deadline = self._clock() + LOOKUP_BUDGET
        pane_id = self.focused_pane_id(deadline)
        if pane_id is None:
            return None
        result = self._call(deadline, "pane", "process-info", "--pane", pane_id)
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
