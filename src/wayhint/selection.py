"""Which hints to show, in what order, and search over them. Pure functions, no I/O.

- :func:`visible_hints`: active sheet's hints plus the parent sheet's hints, narrowed by the
  first tag list that was written down: child ``inherit.parent_tags``, then global
  ``nested.parent_tags``, then the parent's own ``nested.export_tags``; none of them written means
  every parent hint (DECISIONS 0034). ``favorite`` never affects visibility (requirement 9).
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
    child: HintSheet | None,
    global_parent_tags: Sequence[str] | None,
    parent: HintSheet | None = None,
) -> tuple[str, ...] | None:
    """The tag filter on the parent's hints, or ``None`` for all of them (DECISIONS 0034).

    One replacement rule, never an intersection: the first of these that was written down wins
    and the ones below it are not looked at -- the child's ``inherit.parent_tags``, the global
    ``nested.parent_tags``, the parent's ``nested.export_tags``. ``[]`` written anywhere is a
    filter that lets nothing through; nothing written anywhere is ``None``.
    """
    if child is not None and child.parent_tags is not None:
        return tuple(child.parent_tags)
    if global_parent_tags is not None:
        return tuple(global_parent_tags)
    if parent is not None and parent.export_tags is not None:
        return tuple(parent.export_tags)
    return None


def parent_hints_for(parent: HintSheet | None, parent_tags: Iterable[str] | None) -> list[Hint]:
    if parent is None:
        return []
    if parent_tags is None:
        return list(parent.hints)
    wanted = set(parent_tags)
    return [h for h in parent.hints if wanted.intersection(h.tags)]


def visible_hints(
    active: HintSheet | None,
    parent: HintSheet | None,
    global_parent_tags: Sequence[str] | None,
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
        tags = effective_parent_tags(active, global_parent_tags, parent)
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
