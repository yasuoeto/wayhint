"""``wayhint check-sheet``: one sheet, checked as it would load and against the sheets around it.

``validate`` answers "does everything load"; this answers "is this one new sheet ready", for a
sheet written by hand or by a coding agent (DECISIONS 0047). The errors are exactly the loader's
(:func:`load_sheet`), so a sheet that passes here loads in ``wayhintd``. On top of them come
warnings for things that load but are probably not what was meant: a pattern that matches
every window, a sheet nothing will ever show, a hint whose ``kind`` and fields disagree, an id
another sheet already has. Each message says what to change, since the reader may be a program
fixing the file in a loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import regex

from wayhint.matcher import MATCH_TIMEOUT
from wayhint.models import HintSheet, IncludeRef
from wayhint.yaml_store import Issue, resolve_includes


def _matches_everything(pattern: str) -> bool:
    """A pattern that matches the empty string matches, as a substring, every piece of text."""
    try:
        return regex.search(pattern, "", timeout=MATCH_TIMEOUT) is not None
    except (regex.error, TimeoutError):
        return False


def _match_warnings(sheet: HintSheet) -> list[Issue]:
    issues = []
    rule = sheet.match
    for key, patterns in (
        ("match.wayland.app_id_regex", rule.app_id_regex),
        ("match.process.argv_regex", rule.argv_regex),
        ("match.process.cmdline_regex", rule.cmdline_regex),
    ):
        for pattern in patterns:
            if _matches_everything(pattern):
                issues.append(
                    Issue(
                        sheet.path,
                        None,
                        f"{key}: {pattern!r} matches the empty string, so it matches every "
                        "window; anchor it, e.g. '^name$'",
                        "warning",
                    )
                )
    return issues


def _kind_advice(kind: str, key: str | None, command: str | None) -> str | None:
    """What to change when ``kind`` and the fields written disagree, or ``None``.

    Only the plain mismatches: edit mode's form keeps the fields of the kind (SHEET-FORMAT,
    "kind"), so a ``shortcut`` holding only a command loses it the first time it is edited.
    """
    if kind == "note":
        return None
    if not key and not command:
        return "has neither key nor command; write one, or change kind to 'note'"
    if kind == "shortcut" and not key:
        return "has a command but no key; change kind to 'command'"
    if kind == "command" and not command:
        return "has a key but no command; change kind to 'shortcut'"
    return None


def _hint_warnings(sheet: HintSheet) -> list[Issue]:
    issues = []
    for hint in sheet.hints:
        advice = _kind_advice(hint.kind, hint.key, hint.command)
        if advice:
            issues.append(
                Issue(
                    hint.location.file,
                    hint.location.line,
                    f"hint {hint.id!r}: kind {hint.kind!r} {advice}",
                    "warning",
                )
            )
    return issues


def _reachable(sheet: HintSheet, others: Sequence[HintSheet], global_include: Sequence) -> bool:
    """Whether anything can put ``sheet`` on screen: its own match, or another sheet's include."""
    if not sheet.match.is_empty():
        return True
    for other in others:
        wanted = other.include if other.include is not None else tuple(global_include)
        for ref in wanted:
            name = ref.sheet if isinstance(ref, IncludeRef) else ref
            if name == sheet.id:
                return True
    return False


def check_sheet(
    path: Path,
    sheet: HintSheet,
    others: Sequence[HintSheet],
    global_include: Sequence[IncludeRef | str] = (),
) -> list[Issue]:
    """Warnings for ``sheet`` (already loaded without errors) among the installed ``others``.

    ``others`` are the sheets of the configured hints directory, without ``sheet`` itself (a
    sheet already installed is found there by its path and left out by the caller).
    """
    issues: list[Issue] = []
    same_id = next((o for o in others if o.id == sheet.id), None)
    if same_id is not None:
        issues.append(
            Issue(
                path,
                None,
                f"a sheet with id {sheet.id!r} is already installed at {same_id.path}; "
                "installing this one replaces it -- choose another id (and file name) "
                "or edit that file instead",
                "warning",
            )
        )
    peers = [o for o in others if o.id != sheet.id]
    _, include_issues = resolve_includes([sheet, *peers], global_include)
    issues.extend(i for i in include_issues if i.file == sheet.path)
    issues.extend(_match_warnings(sheet))
    if not _reachable(sheet, peers, global_include):
        issues.append(
            Issue(
                path,
                None,
                "no match and no sheet includes it, so it is never shown; add match "
                "(wayland.app_id_regex for a window, process.argv_regex for a command in a "
                "terminal)",
                "warning",
            )
        )
    issues.extend(_hint_warnings(sheet))
    return issues
