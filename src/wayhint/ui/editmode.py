"""Edit-mode logic that does not need GTK: the state machine, key routing and the filter.

The GTK side (``ui/window.py``) is a thin shell over this module: it turns a key press into an
action name here, and it asks here whether the layer surface should hold the keyboard. Keeping
that here is what makes the parts that are easy to get wrong -- "is the grab released?", "what
does ``d`` mean right now?" -- testable headless (docs/DESIGN.md 編集モード §1, §2, §9).

Pure module: dataclasses and functions over plain values. No GTK, no compositor, no I/O.
"""

from __future__ import annotations

from collections.abc import Container, Hashable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from wayhint.models import Hint, ResolvedContext

MODES = ("normal", "search", "edit")

PSEUDO_CATEGORY = "\x00inbox"
"""Stands for "no category" inside the filter. Never written to YAML: the label is i18n'd, and
the value the user sees must not end up in a file (0014 D5)."""
FORM_FIELDS = ("title", "kind", "key", "command", "category", "remark")

# Actions the window asks the daemon to perform. Names are the vocabulary of DESIGN §2.
ADD = "add"
OPEN_FORM = "open-form"
DELETE_CONFIRM = "delete-confirm"
DELETE_COMMIT = "delete-commit"
UNDO = "undo"
FAVORITE = "favorite"
MOVE_DOWN = "move-down"
MOVE_UP = "move-up"
EXIT_EDIT = "exit-edit"
BEGIN_SEARCH = "begin-search"
END_SEARCH = "end-search"
FORM_SAVE = "form-save"
FORM_CANCEL = "form-cancel"
FORM_NEXT = "form-next"
FORM_PREVIOUS = "form-previous"
FORM_PARENT = "form-parent"


@dataclass
class FormDraft:
    """An open form, and the draft that survives hide and workspace switching (0014 D4).

    ``hint_id`` is ``None`` for quick add. ``sheet_id`` is ``None`` when the context has no sheet
    yet: the sheet is created on save, and the user is never asked for a file name.
    """

    hint_id: str | None = None
    sheet_id: str | None = None
    file: Path | None = None  # existing hint's owner; IDs are unique only within a sheet
    to_parent: bool = False
    fields: dict[str, str] = field(default_factory=dict)
    warning: str | None = None

    def value(self, name: str) -> str:
        return self.fields.get(name, "")


@dataclass
class WorkspaceView:
    """What one workspace is showing. The daemon keeps one of these per workspace key."""

    context: ResolvedContext
    mode: str = "normal"
    form: FormDraft | None = None
    selected_hint: str | None = None
    delete_pending: str | None = None

    def target_key(self) -> tuple:
        return self.context.target_key()


def keyboard_grab(mode: str, visible: bool) -> bool:
    """Whether the layer surface should take the keyboard (ON_DEMAND) or not (NONE).

    One rule, one place: hiding or leaving the workspace keeps the mode but drops the grab, so a
    failed refocus or a missed event can never leave the keyboard captured (DESIGN §1).
    """
    return visible and mode in ("search", "edit")


def sheet_is_stale(path: Path | None, broken: Container[Path]) -> bool:
    """True when this sheet is on screen only as last-known-good (DESIGN 編集モード §1).

    Writing then would throw away whatever the file now holds, so edit mode is refused for that
    one sheet. A different sheet being broken is none of its business.
    """
    return path is not None and path in broken


def target_sheet_id(draft: FormDraft, context: ResolvedContext) -> str | None:
    """Which sheet a save lands in: the parent when ``Ctrl+P`` is on, else the form's own."""
    return context.parent_context if draft.to_parent else draft.sheet_id


def edit_action(
    key: str, *, ctrl: bool = False, editable: bool = False, pending: bool = False
) -> str | None:
    """Map a key press in edit mode to an action, or ``None`` to let GTK have it.

    ``editable`` is true while a text field has the focus: then only the form keys are taken and
    everything printable goes through, so typing "add" into a title does not delete a hint.
    Any action other than the two delete ones cancels a pending ``d`` (DESIGN §2).

    In the list, a modifier means the key is not ours: ``Ctrl+d`` is the terminal's, and taking
    it as "delete this hint" would act on a keystroke the user aimed somewhere else. Only
    ``Ctrl+P`` in a form has a meaning here, and that one is spelled out below.
    """
    if editable:
        if key == "Return" or key == "KP_Enter":
            return FORM_SAVE
        if key == "Escape":
            return FORM_CANCEL
        if key == "Tab":
            return FORM_NEXT
        if key == "ISO_Left_Tab":
            return FORM_PREVIOUS
        if ctrl and key in ("p", "P"):
            return FORM_PARENT
        return None
    if ctrl:
        return None
    if key == "d":
        return DELETE_COMMIT if pending else DELETE_CONFIRM
    simple = {
        "a": ADD,
        "Return": OPEN_FORM,
        "KP_Enter": OPEN_FORM,
        "u": UNDO,
        "f": FAVORITE,
        "J": MOVE_DOWN,
        "K": MOVE_UP,
        "Escape": EXIT_EDIT,
    }
    return simple.get(key)


def capture_in_editable(action: str | None, *, preedit: bool = False) -> bool:
    """May this action be taken *before* the input method sees the key, in a text field?

    Only the keys the input method never wants. ``Enter`` confirms a conversion and ``Esc``
    cancels one, so those two have to reach the IME first and are handled on the way back up
    (bubble) instead -- otherwise typing Japanese into the form is impossible: the key that
    confirms 「ペイン」 would save the form with the text still unconfirmed.

    ``preedit`` says a conversion is open right now. While it is, even Tab and ``Ctrl+P`` are
    the input method's: they pick and walk candidates. Field movement is worth having, but not
    at the price of making the candidate list unusable, so nothing is taken early until the
    conversion is confirmed or cancelled.
    """
    if preedit:
        return False
    return action in (FORM_NEXT, FORM_PREVIOUS, FORM_PARENT)


def cancels_delete(action: str | None) -> bool:
    """``d`` waits for a second ``d``; anything else -- including no action -- calls it off."""
    return action not in (DELETE_CONFIRM, DELETE_COMMIT)


@dataclass(frozen=True)
class SearchQuery:
    """A parsed search box: an optional category filter plus the remaining free text."""

    category: str | None = None
    text: str = ""
    partial: str | None = None  # "#pan" being typed, for Tab completion

    @property
    def filtering(self) -> bool:
        return self.category is not None


def parse_search(text: str) -> SearchQuery:
    """``"#panes new"`` → category ``panes`` + text ``new``. Only the first token counts.

    A ``#word`` that is still being typed (no space after it) is reported as ``partial`` as well,
    so Tab can complete it (DESIGN §9).
    """
    if not text.startswith("#"):
        return SearchQuery(text=text)
    head, sep, rest = text.partition(" ")
    name = head[1:]
    if not sep:
        return SearchQuery(category=name or None, text="", partial=name)
    return SearchQuery(category=name or None, text=rest.strip())


def category_order(hints: Sequence[Hint]) -> list[str | None]:
    """Categories in order of first appearance, with ``None`` for the uncategorised group."""
    order: list[str | None] = []
    for hint in hints:
        if hint.category not in order:
            order.append(hint.category)
    return order


def cycle_category(
    order: Sequence[str | None], current: str | None, forward: bool = True
) -> str | None:
    """Tab / Shift+Tab: everything → each category in order → everything again (DESIGN §9).

    ``None`` means "no filter". The uncategorised group is part of the cycle like any other; the
    caller knows it as the pseudo category.
    """
    stops: list[str | None] = [None, *[PSEUDO_CATEGORY if c is None else c for c in order]]
    try:
        index = stops.index(current)
    except ValueError:
        index = 0
    return stops[(index + (1 if forward else -1)) % len(stops)]


def matches_category(hint: Hint, category: str | None) -> bool:
    if category is None:
        return True
    if category == PSEUDO_CATEGORY:
        return hint.category is None
    return (hint.category or "").casefold() == category.casefold()


def completions(prefix: str, order: Iterable[str | None]) -> list[str]:
    """Every category that starts with what has been typed, in the order they first appear."""
    needle = prefix.casefold()
    return [c for c in order if c is not None and c.casefold().startswith(needle)]


def complete_category(partial: str, order: Iterable[str | None]) -> str | None:
    """The first category that starts with what has been typed, or ``None``."""
    found = completions(partial, order)
    return found[0] if found else None


def next_completion(
    prefix: str, order: Iterable[str | None], current: str | None = None, forward: bool = True
) -> str | None:
    """The next candidate for ``prefix``, wrapping around.

    With ``screen`` and ``session`` both present, ``#s`` + Tab has to be able to reach either;
    completing to the first match and stopping there hides the other one entirely.
    """
    found = completions(prefix, order)
    if not found:
        return None
    if current is None or current not in found:
        return found[0] if forward else found[-1]
    return found[(found.index(current) + (1 if forward else -1)) % len(found)]


def restore_index(
    hint_ids: Sequence[Hashable], hint_id: Hashable | None, previous: int | None
) -> int | None:
    """Where the selection goes after a reload: same hint if it is still there, else same row.

    The id is the stable handle; the index is the fallback for a hint that was renamed or removed
    (0014 D2). ``None`` when the list is empty.
    """
    if not hint_ids:
        return None
    if hint_id is not None and hint_id in hint_ids:
        return hint_ids.index(hint_id)
    if previous is None:
        return 0
    return max(0, min(previous, len(hint_ids) - 1))


MEMO_KINDS = ("tip", "note")
"""The kinds that are notes to self rather than something to press or run."""


def kind_fields(kind: str) -> tuple[str, ...]:
    """Which of ``key`` / ``command`` this kind may carry (DESIGN §3, amended 2026-09-18).

    ``tip`` is a note that often has both -- "press this, or run that" -- so it gets both fields;
    ``note`` is prose and gets neither.
    """
    if kind == "command":
        return ("command",)
    if kind == "tip":
        return ("key", "command")
    if kind == "note":
        return ()
    return ("key",)


def display_fields(kind: str) -> tuple[str, ...]:
    """Which of ``key`` / ``command`` the list shows for a hint of this kind.

    A ``note`` is prose: even if the YAML still carries a key or a command from before it was
    made a note, the row does not show them. The other kinds show whatever they have.
    """
    return () if kind == "note" else ("key", "command")


def draft_from_hint(hint: Hint, sheet_id: str | None) -> FormDraft:
    """Prefill the form from an existing hint. ``id`` is shown but never edited here."""
    fields = {
        "title": hint.title,
        "kind": hint.kind,
        "key": hint.key or "",
        "command": hint.command or "",
        "category": hint.category or "",
        "remark": hint.remark or "",
    }
    return FormDraft(hint_id=hint.id, sheet_id=sheet_id, file=hint.location.file, fields=fields)


def draft_fields(draft: FormDraft) -> dict[str, object]:
    """The form's values as hint fields: fields the kind does not carry are dropped, blanks null."""
    kind = draft.value("kind") or "shortcut"
    wanted = kind_fields(kind)
    out: dict[str, object] = {"title": draft.value("title").strip(), "kind": kind}
    for name in ("category", "remark"):
        out[name] = draft.value(name).strip() or None
    for name in ("key", "command"):
        out[name] = draft.value(name).strip() or None if name in wanted else None
    return out
