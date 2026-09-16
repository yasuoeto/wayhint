"""Which hints to show, in what order, and search over them. Pure functions, no I/O.

- :func:`visible_hints`: active sheet's hints plus the parent sheet's hints whose tags intersect
  the effective ``parent_tags`` (child ``inherit.parent_tags`` overrides global
  ``nested.parent_tags``). ``favorite`` never affects visibility (PRODUCT requirement 9).
- :func:`sort_hints`: favorite first, then category in order of first appearance, then YAML order
  (requirement 11).
- :func:`search_hints`: case-insensitive substring, whitespace-separated tokens ANDed, over
  title/key/command/category/tags/remark (requirement 12).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

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
) -> list[Hint]:
    """Hints for the overlay before sorting.

    Without a nested context (``parent`` is None) this is simply the active sheet's hints. With
    one, the active (child) sheet's hints come first and the tag-filtered parent hints follow.
    When only the parent is known (foreground process unmatched) all parent hints are shown.
    """
    if active is None:
        return list(parent.hints) if parent is not None else []
    if parent is None or parent is active:
        return list(active.hints)
    tags = effective_parent_tags(active, global_parent_tags)
    return list(active.hints) + parent_hints_for(parent, tags)


def sort_hints(hints: Sequence[Hint]) -> list[Hint]:
    category_rank: dict[str | None, int] = {}
    for h in hints:
        category_rank.setdefault(h.category, len(category_rank))
    indexed = list(enumerate(hints))
    indexed.sort(key=lambda ih: (not ih[1].favorite, category_rank[ih[1].category], ih[0]))
    return [h for _, h in indexed]


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
