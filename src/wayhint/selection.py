"""Which hints to show, in what order, and search over them. Pure functions, no I/O.

- :func:`visible_hints`: active sheet's hints plus the parent sheet's hints whose tags intersect
  the effective ``parent_tags`` (child ``inherit.parent_tags`` overrides global
  ``nested.parent_tags``). ``favorite`` never affects visibility (PRODUCT requirement 9).
- :func:`sort_hints`: favorites first in YAML order, then the rest by category in order of first
  appearance, then YAML order (requirement 11 as amended by DECISIONS 0014 D7).
- :func:`search_hints`: case-insensitive substring, whitespace-separated tokens ANDed, over
  title/key/command/category/tags/remark (requirement 12).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from wayhint.models import Hint, HintSheet


def effective_parent_tags(
    child: HintSheet | None, global_parent_tags: Sequence[str]
) -> tuple[str, ...]:
    if child is not None and child.parent_tags is not None:
        return tuple(child.parent_tags)
    return tuple(global_parent_tags)


def parent_hints_for(parent: HintSheet | None, parent_tags: Iterable[str]) -> list[Hint]:
    if parent is None:
        return []
    wanted = set(parent_tags)
    if not wanted:
        return []
    return [h for h in parent.hints if wanted.intersection(h.tags)]


def visible_hints(
    active: HintSheet | None,
    parent: HintSheet | None,
    global_parent_tags: Sequence[str],
    includes: Sequence[HintSheet] = (),
) -> list[Hint]:
    """Hints for the overlay before sorting.

    Without a nested context (``parent`` is None) this is simply the active sheet's hints. With
    one, the active (child) sheet's hints come first and the tag-filtered parent hints follow.
    When only the parent is known (foreground process unmatched) all parent hints are shown.

    ``includes`` are the sheets the active one names in ``include`` (or the global default),
    already resolved and in the order they were written. Their hints come last, whole -- no tag
    filter -- and a hint already on the list is not added again: the same sheet can be both the
    nested parent and an include, and two sheets can include the same one (DECISIONS 0026).
    """
    if active is None:
        out = list(parent.hints) if parent is not None else []
    elif parent is None or parent is active:
        out = list(active.hints)
    else:
        tags = effective_parent_tags(active, global_parent_tags)
        out = list(active.hints) + parent_hints_for(parent, tags)
    for sheet in includes:
        out.extend(sheet.hints)
    return _unique(out)


def _unique(hints: Sequence[Hint]) -> list[Hint]:
    """First occurrence wins; a hint is the pair (file it lives in, id) -- 0019."""
    seen: set[tuple[Path, str]] = set()
    out = []
    for hint in hints:
        key = (hint.location.file, hint.id)
        if key in seen:
            continue
        seen.add(key)
        out.append(hint)
    return out


def sheet_for_hint(sheets: Iterable[HintSheet], hint: Hint | None) -> HintSheet | None:
    """The sheet a hint lives in, found by file.

    With ``nested.parent_tags`` the list mixes in hints from the parent sheet, so "the sheet" is
    a property of the selected hint, not of the context.
    """
    if hint is None:
        return None
    return next((s for s in sheets if s.path == hint.location.file), None)


def sort_hints(hints: Sequence[Hint]) -> list[Hint]:
    """Favorites first, in YAML order; then the rest grouped by category (DECISIONS 0014 D7).

    The favorite block ignores ``category`` so that two favorites from different categories can
    be put next to each other by reordering the YAML, which is what ``J`` / ``K`` does.
    """
    category_rank: dict[str | None, int] = {}
    for h in hints:
        if not h.favorite:
            category_rank.setdefault(h.category, len(category_rank))
    indexed = list(enumerate(hints))
    indexed.sort(
        key=lambda ih: (
            not ih[1].favorite,
            0 if ih[1].favorite else category_rank[ih[1].category],
            ih[0],
        )
    )
    return [h for _, h in indexed]


def same_group(a: Hint, b: Hint) -> bool:
    """May ``J`` / ``K`` swap these two? (DECISIONS 0014 D8; the caller checks the sheet.)"""
    if a.favorite != b.favorite:
        return False
    return a.favorite or a.category == b.category


def _haystack(hint: Hint) -> str:
    parts = [hint.title, hint.key, hint.command, hint.category, hint.remark, *hint.tags]
    return "\n".join(p for p in parts if p).casefold()


def search_hints(hints: Sequence[Hint], query: str) -> list[Hint]:
    tokens = [t.casefold() for t in query.split() if t]
    if not tokens:
        return list(hints)
    out = []
    for hint in hints:
        hay = _haystack(hint)
        if all(t in hay for t in tokens):
            out.append(hint)
    return out
