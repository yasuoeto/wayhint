"""Pick the sheet that matches the current desktop app or foreground process.

Order among several matching sheets (PRODUCT requirement 7): higher ``priority`` first, then
higher *specificity* (the number of regex patterns in the sheet's rule that matched), then file
order (the order sheets were loaded, i.e. ``hints/`` filename order). DECISIONS 0007.

All regexes come from YAML and are searched with the ``regex`` module, not ``re``: its syntax is
``re``'s, but a search can be given a time limit (DECISIONS 0046). The text searched comes from
whatever program is running, so a pattern that backtracks badly -- ``^(a|aa)+$`` -- would
otherwise hold up the overlay for as long as the program likes. A pattern that fails to compile
was already rejected by validation, but a defensive ``regex.error`` guard keeps a stale sheet
from crashing the overlay.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from functools import lru_cache

import regex

from wayhint.models import HintSheet, ProcessInfo

log = logging.getLogger("wayhint.matcher")


@lru_cache(maxsize=512)
def _compile(pattern: str) -> regex.Pattern[str] | None:
    try:
        return regex.compile(pattern)
    except regex.error:
        return None


MATCH_TIMEOUT = 0.05
"""Seconds one pattern may spend on one piece of text. A sane pattern on text this short takes
microseconds; one that needs this long is backtracking without end, and gets no longer."""

_reported: set[str] = set()


MAX_CANDIDATE = 4096
"""How much of an app_id, argv element or command line a pattern is matched against.

The text comes from whatever program is running, which can make it as long as it likes, and a
pattern that backtracks badly takes time that grows with the text -- all of it spent inside the
overlay before it can show. Real app_ids and argv are far shorter; past this, a pattern anchored
with ``$`` stops matching."""


def _count_matches(patterns: Iterable[str], candidates: Sequence[str]) -> int:
    candidates = [c[:MAX_CANDIDATE] for c in candidates]
    n = 0
    for pattern in patterns:
        rx = _compile(pattern)
        if rx is not None and _matches(pattern, rx, candidates):
            n += 1
    return n


def _matches(pattern: str, rx: regex.Pattern[str], candidates: Sequence[str]) -> bool:
    """Whether ``rx`` finds any of ``candidates``. Running out of time counts as not matching.

    A pattern that times out once is not tried on the rest of the candidates: a command with a
    thousand arguments would otherwise cost a thousand timeouts. It is reported once per
    pattern, so the log says which rule to fix.
    """
    for text in candidates:
        try:
            if rx.search(text, timeout=MATCH_TIMEOUT) is not None:
                return True
        except TimeoutError:
            if pattern not in _reported:
                _reported.add(pattern)
                log.warning(
                    "regex %r took longer than %.0f ms and was treated as not matching; "
                    "rewrite it so that it does not backtrack",
                    pattern,
                    MATCH_TIMEOUT * 1000,
                )
            return False
    return False


def app_specificity(sheet: HintSheet, app_id: str | None) -> int:
    """Matched against the app_id *and*, for a window naming its pid, the terminal behind it.

    ``foot.p12345`` has to match the sheet somebody wrote for ``foot`` -- the suffix identifies
    the window, not the program (DECISIONS 0027). Both forms are offered rather than the base
    alone, so a rule written against a literal app_id that happens to end in ``.p<digits>`` keeps
    matching; a pattern counts once however many of them it matches.
    """
    if not app_id:
        return 0
    base, _pid = strip_pid_suffix(app_id)
    candidates = (app_id, base) if base and base != app_id else (app_id,)
    return _count_matches(sheet.match.app_id_regex, candidates)


GENERIC_PROCESS_NAMES = frozenset({"python", "python3", "node", "sh", "bash", "zsh"})
"""Interpreter and shell names that say nothing about what is running (DECISIONS 0014 D6)."""


APP_ID_PID_RE = re.compile(r"\.p(\d+)$")
"""``<app-id>.p<pid>``: a terminal window saying which process draws it (DECISIONS 0027).

No Wayland protocol tells a client the pid behind a toplevel, and a terminal with several windows
is otherwise indistinguishable in ``/proc``. The window therefore says so itself, through the one
field the compositor does hand out: a launcher starts each window with this suffix on its app_id.
"""


def strip_pid_suffix(app_id: str | None) -> tuple[str | None, int | None]:
    """``"foot.p12345"`` → ``("foot", 12345)``; anything else comes back unchanged with ``None``.

    Kept here rather than in the ``/proc`` adapter because the pure side needs it too: a sheet
    generated for such a window has to match the *terminal*, not the one window it was made in.
    """
    if not app_id:
        return app_id, None
    found = APP_ID_PID_RE.search(app_id)
    if found is None:
        return app_id, None
    return app_id[: found.start()], int(found.group(1))


def argv_basenames(argv: Sequence[str]) -> list[str]:
    """``/path/to/codex`` → ``codex``. The rule sheet generation must agree with."""
    return [a.rsplit("/", 1)[-1] for a in argv]


def process_candidates(proc: ProcessInfo) -> list[str]:
    """What ``argv_regex`` is matched against: the name, every argv element, and each basename.

    ``node /path/to/codex`` therefore matches ``^codex$``. Sheet generation reuses this so the
    regex it writes is matched the same way it was chosen.
    """
    return [proc.name, *proc.argv, *argv_basenames(proc.argv)]


def process_specificity(sheet: HintSheet, proc: ProcessInfo | None) -> int:
    if proc is None:
        return 0
    return _count_matches(sheet.match.argv_regex, process_candidates(proc)) + _count_matches(
        sheet.match.cmdline_regex, (proc.cmdline,)
    )


def _best(sheets: Sequence[HintSheet], score: Sequence[int]) -> HintSheet | None:
    best: HintSheet | None = None
    best_key: tuple[int, int, int] | None = None
    for index, (sheet, spec) in enumerate(zip(sheets, score, strict=True)):
        if spec <= 0:
            continue
        key = (sheet.priority, spec, -index)
        if best_key is None or key > best_key:
            best, best_key = sheet, key
    return best


def match_app(sheets: Sequence[HintSheet], app_id: str | None) -> HintSheet | None:
    """Sheet for the active toplevel's ``app_id`` (desktop context)."""
    return _best(sheets, [app_specificity(s, app_id) for s in sheets])


def match_process(sheets: Sequence[HintSheet], proc: ProcessInfo | None) -> HintSheet | None:
    """Sheet for a terminal's foreground process (nested context)."""
    return _best(sheets, [process_specificity(s, proc) for s in sheets])
