"""Pick the sheet that matches the current desktop app or foreground process.

Order among several matching sheets (PRODUCT requirement 7): higher ``priority`` first, then
higher *specificity* (the number of regex patterns in the sheet's rule that matched), then file
order (the order sheets were loaded, i.e. ``hints/`` filename order). DECISIONS 0007.

All regexes come from YAML and are compiled with :func:`re.search`; a pattern that fails to
compile was already rejected by validation, but a defensive ``re.error`` guard keeps a stale
sheet from crashing the overlay.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache

from wayhint.models import HintSheet, ProcessInfo


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern)
    except re.error:
        return None


def _count_matches(patterns: Iterable[str], candidates: Sequence[str]) -> int:
    n = 0
    for pattern in patterns:
        rx = _compile(pattern)
        if rx is not None and any(rx.search(c) for c in candidates):
            n += 1
    return n


def app_specificity(sheet: HintSheet, app_id: str | None) -> int:
    if not app_id:
        return 0
    return _count_matches(sheet.match.app_id_regex, (app_id,))


def process_specificity(sheet: HintSheet, proc: ProcessInfo | None) -> int:
    if proc is None:
        return 0
    # name, every argv element, and each element's basename (``node /path/to/codex`` → codex)
    argv_candidates = [proc.name, *proc.argv, *(a.rsplit("/", 1)[-1] for a in proc.argv)]
    return _count_matches(sheet.match.argv_regex, argv_candidates) + _count_matches(
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
