"""Which hints to show, in what order, and search over them. Pure functions, no I/O.

- :func:`visible_hints`: active sheet's hints plus the parent sheet's hints, narrowed by the
  first tag list that was written down: child ``inherit.parent_tags``, then global
  ``nested.parent_tags``, then the parent's own ``nested.export_tags``; none of them written means
  every parent hint (DECISIONS 0034). Categories are settled the same way on their own, and a
  hint passes when either matches (0039). ``favorite`` never affects visibility (requirement 9).
- :func:`sort_hints`: favorites first in YAML order, then the rest by category in order of first
  appearance, then YAML order (requirement 11 as amended by DECISIONS 0014 D7).
- :func:`search_hints`: case-insensitive substring, whitespace-separated tokens ANDed, over
  title/key/command/category/tags/remark (requirement 12).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from wayhint.models import Hint, HintFilter, HintSheet, IncludeRef


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


def effective_parent_categories(
    child: HintSheet | None,
    global_parent_categories: Sequence[str] | None,
    parent: HintSheet | None = None,
) -> tuple[str, ...] | None:
    """The category filter on the parent's hints: the same rule as :func:`effective_parent_tags`,
    settled on its own -- ``inherit.parent_categories``, ``nested.parent_categories``,
    ``export_categories``."""
    if child is not None and child.parent_categories is not None:
        return tuple(child.parent_categories)
    if global_parent_categories is not None:
        return tuple(global_parent_categories)
    if parent is not None and parent.export_categories is not None:
        return tuple(parent.export_categories)
    return None


def parent_hints_for(
    parent: HintSheet | None,
    parent_tags: Iterable[str] | None,
    parent_categories: Iterable[str] | None = None,
) -> list[Hint]:
    if parent is None:
        return []
    wanted = HintFilter(
        tags=None if parent_tags is None else tuple(parent_tags),
        categories=None if parent_categories is None else tuple(parent_categories),
    )
    return [h for h in parent.hints if wanted.allows(h)]


def visible_hints(
    active: HintSheet | None,
    parent: HintSheet | None,
    global_parent_tags: Sequence[str] | None,
    includes: Sequence[HintSheet] = (),
    global_parent_categories: Sequence[str] | None = None,
) -> list[Hint]:
    """Hints for the overlay before sorting.

    Without a nested context (``parent`` is None) this is simply the active sheet's hints. With
    one, the active (child) sheet's hints come first and the tag-filtered parent hints follow.
    When only the parent is known (foreground process unmatched) all parent hints are shown.

    ``includes`` are the sheets the active one names in ``include`` (or the global default),
    already resolved, narrowed by their own ``tags`` / ``categories`` (0039) and in the order they
    were written. Their hints come last, and a hint already on the list is not added again: the
    same sheet can be both the nested parent and an include, and two sheets can include the same
    one (DECISIONS 0026).
    """
    if active is None:
        out = list(parent.hints) if parent is not None else []
    elif parent is None or parent is active:
        out = list(active.hints)
    else:
        tags = effective_parent_tags(active, global_parent_tags, parent)
        categories = effective_parent_categories(active, global_parent_categories, parent)
        out = list(active.hints) + parent_hints_for(parent, tags, categories)
    for sheet in includes:
        out.extend(sheet.hints)
    return _unique(out)


def _stage(child, global_value, parent, child_key, global_key, parent_key):
    """``(value, where it came from)`` for one of the parent filters, first written wins (0034)."""
    if child is not None and getattr(child, child_key) is not None:
        return tuple(getattr(child, child_key)), f"inherit.{child_key}", child.path.name
    if global_value is not None:
        return tuple(global_value), f"nested.{global_key}", "config.yaml"
    if parent is not None and getattr(parent, parent_key) is not None:
        return tuple(getattr(parent, parent_key)), f"nested.{parent_key}", parent.path.name
    return None, None, None


def explain_filters(
    active: HintSheet | None,
    parent: HintSheet | None,
    sheets: Sequence[HintSheet],
    global_parent_tags: Sequence[str] | None = None,
    global_parent_categories: Sequence[str] | None = None,
    global_include: Sequence[IncludeRef] = (),
) -> dict:
    """What narrowed the mixed-in hints, for ``wayhint inspect`` and ``context --shown``.

    Plain data (JSON-able): the parent's tag and category filters with the key and file each came
    from, and every ``include`` entry with its filter. Counts are before de-duplication, so a hint
    that is both a parent hint and an include is counted in both.
    """
    out: dict = {"sheet": active.id if active is not None else None, "parent": None, "include": []}
    if active is None:
        return out
    if parent is not None and parent is not active:
        tags, tags_key, tags_file = _stage(
            active, global_parent_tags, parent, "parent_tags", "parent_tags", "export_tags"
        )
        cats, cats_key, cats_file = _stage(
            active,
            global_parent_categories,
            parent,
            "parent_categories",
            "parent_categories",
            "export_categories",
        )
        out["parent"] = {
            "sheet": parent.id,
            "tags": list(tags) if tags is not None else None,
            "tags_from": f"{tags_key} ({tags_file})" if tags_key else None,
            "categories": list(cats) if cats is not None else None,
            "categories_from": f"{cats_key} ({cats_file})" if cats_key else None,
            "shown": len(parent_hints_for(parent, tags, cats)),
            "total": len(parent.hints),
        }
    own = active.include is not None
    refs = active.include if own else tuple(global_include)
    by_id = {sheet.id: sheet for sheet in sheets}
    for ref in refs:
        if ref.sheet == active.id:
            continue  # a sheet never includes itself (0026)
        other = by_id.get(ref.sheet)
        entry = {
            "sheet": ref.sheet,
            "from": active.path.name if own else "config.yaml",
            "tags": list(ref.filter.tags) if ref.filter.tags is not None else None,
            "categories": list(ref.filter.categories)
            if ref.filter.categories is not None
            else None,
            "shown": None,
            "total": None,
        }
        if other is not None:
            entry["shown"] = sum(1 for h in other.hints if ref.filter.allows(h))
            entry["total"] = len(other.hints)
        out["include"].append(entry)
    return out


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
