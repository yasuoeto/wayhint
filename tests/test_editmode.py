"""Phase 7c: the edit-mode logic that can be tested without GTK.

The GTK shell (``ui/window.py``) is not tested here; what is tested is everything it defers to:
the grab rule, what a key means, the category filter, and where the selection lands after a
reload (docs/DESIGN.md 編集モード §1, §2, §5, §8, §9).
"""

import unittest
from pathlib import Path

from wayhint.models import Hint, ResolvedContext, SourceLocation
from wayhint.selection import same_group, sort_hints
from wayhint.ui import editmode as em


def hint(id_, category=None, favorite=False, kind="shortcut", file="a.yaml", **kw) -> Hint:
    return Hint(
        id=id_,
        title=kw.pop("title", id_.title()),
        location=SourceLocation(Path(file), 1),
        category=category,
        favorite=favorite,
        kind=kind,
        **kw,
    )


class KeyboardGrabTest(unittest.TestCase):
    """DESIGN §1: one rule, derived from mode and visibility."""

    def test_the_whole_table(self) -> None:
        for mode, visible, expected in (
            ("normal", True, False),
            ("normal", False, False),
            ("search", True, True),
            ("search", False, False),  # hidden: the mode stays, the grab does not
            ("edit", True, True),
            ("edit", False, False),  # left the workspace while editing
        ):
            with self.subTest(mode=mode, visible=visible):
                self.assertEqual(em.keyboard_grab(mode, visible), expected)

    def test_coming_back_to_a_workspace_takes_the_grab_again(self) -> None:
        view = em.WorkspaceView(context=ResolvedContext(active_sheet="s"), mode="edit")
        self.assertFalse(em.keyboard_grab(view.mode, False), "hidden while away")
        self.assertTrue(em.keyboard_grab(view.mode, True), "and grabbed again on return")

    def test_every_mode_is_covered(self) -> None:
        for mode in em.MODES:
            em.keyboard_grab(mode, True)  # would raise KeyError if a mode were unhandled


class EditActionTest(unittest.TestCase):
    def test_list_keys(self) -> None:
        self.assertEqual(em.edit_action("a"), em.ADD)
        self.assertEqual(em.edit_action("Return"), em.OPEN_FORM)
        self.assertEqual(em.edit_action("u"), em.UNDO)
        self.assertEqual(em.edit_action("f"), em.FAVORITE)
        self.assertEqual(em.edit_action("J"), em.MOVE_DOWN)
        self.assertEqual(em.edit_action("K"), em.MOVE_UP)
        self.assertEqual(em.edit_action("Escape"), em.EXIT_EDIT)
        self.assertIsNone(em.edit_action("x"))

    def test_double_d(self) -> None:
        self.assertEqual(em.edit_action("d"), em.DELETE_CONFIRM)
        self.assertEqual(em.edit_action("d", pending=True), em.DELETE_COMMIT)

    def test_pending_delete_is_cancelled_by_anything_else(self) -> None:
        self.assertFalse(em.cancels_delete(em.edit_action("d")))
        self.assertFalse(em.cancels_delete(em.edit_action("d", pending=True)))
        for key in ("a", "f", "Escape", "x", "Return"):
            with self.subTest(key=key):
                self.assertTrue(em.cancels_delete(em.edit_action(key, pending=True)))

    def test_a_text_field_keeps_its_keys(self) -> None:
        """Typing "add" into a title must not add and delete hints."""
        for key in ("a", "d", "f", "J", "u", "x"):
            with self.subTest(key=key):
                self.assertIsNone(em.edit_action(key, editable=True))

    def test_form_keys(self) -> None:
        self.assertEqual(em.edit_action("Return", editable=True), em.FORM_SAVE)
        self.assertEqual(em.edit_action("Escape", editable=True), em.FORM_CANCEL)
        self.assertEqual(em.edit_action("Tab", editable=True), em.FORM_NEXT)
        self.assertEqual(em.edit_action("ISO_Left_Tab", editable=True), em.FORM_PREVIOUS)
        self.assertEqual(em.edit_action("p", ctrl=True, editable=True), em.FORM_PARENT)
        self.assertIsNone(em.edit_action("p", editable=True), "plain p is a character")


class SearchQueryTest(unittest.TestCase):
    def test_plain_text(self) -> None:
        query = em.parse_search("new pane")
        self.assertIsNone(query.category)
        self.assertEqual(query.text, "new pane")
        self.assertFalse(query.filtering)

    def test_category_and_text(self) -> None:
        query = em.parse_search("#panes new")
        self.assertEqual((query.category, query.text, query.partial), ("panes", "new", None))
        self.assertTrue(query.filtering)

    def test_partial_category_is_reported_for_completion(self) -> None:
        query = em.parse_search("#pan")
        self.assertEqual((query.category, query.partial, query.text), ("pan", "pan", ""))

    def test_only_the_first_token_counts(self) -> None:
        query = em.parse_search("panes #new")
        self.assertIsNone(query.category)
        self.assertEqual(query.text, "panes #new")

    def test_bare_hash(self) -> None:
        self.assertIsNone(em.parse_search("#").category)

    def test_completion(self) -> None:
        order = ["panes", "session", None]
        self.assertEqual(em.complete_category("pan", order), "panes")
        self.assertEqual(em.complete_category("SES", order), "session")
        self.assertIsNone(em.complete_category("zzz", order))


class CategoryCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hints = [hint("a", "one"), hint("b", None), hint("c", "two"), hint("d", "one")]

    def test_order_is_first_appearance_including_the_uncategorised_group(self) -> None:
        self.assertEqual(em.category_order(self.hints), ["one", None, "two"])

    def test_tab_cycles_all_then_each_category_then_all(self) -> None:
        order = em.category_order(self.hints)
        stops = []
        current = None
        for _ in range(5):
            current = em.cycle_category(order, current)
            stops.append(current)
        self.assertEqual(stops, ["one", em.PSEUDO_CATEGORY, "two", None, "one"])

    def test_shift_tab_goes_the_other_way(self) -> None:
        order = em.category_order(self.hints)
        self.assertEqual(em.cycle_category(order, None, forward=False), "two")
        self.assertEqual(em.cycle_category(order, "one", forward=False), None)

    def test_matching(self) -> None:
        self.assertTrue(em.matches_category(hint("x", "one"), None))
        self.assertTrue(em.matches_category(hint("x", "one"), "ONE"))
        self.assertFalse(em.matches_category(hint("x", "one"), "two"))
        self.assertTrue(em.matches_category(hint("x", None), em.PSEUDO_CATEGORY))
        self.assertFalse(em.matches_category(hint("x", "one"), em.PSEUDO_CATEGORY))

    def test_the_pseudo_category_never_looks_like_a_yaml_value(self) -> None:
        # The label is i18n; the value must never reach a file.
        self.assertNotIn(em.PSEUDO_CATEGORY, ("inbox", "未定義"))
        self.assertTrue(em.PSEUDO_CATEGORY.startswith("\x00"))


class RestoreSelectionTest(unittest.TestCase):
    def test_same_hint_wins(self) -> None:
        self.assertEqual(em.restore_index(["a", "b", "c"], "c", 0), 2)

    def test_falls_back_to_the_index(self) -> None:
        self.assertEqual(em.restore_index(["a", "b", "c"], "gone", 1), 1)

    def test_index_is_clamped(self) -> None:
        self.assertEqual(em.restore_index(["a"], "gone", 7), 0)

    def test_empty_list(self) -> None:
        self.assertIsNone(em.restore_index([], "a", 0))

    def test_no_previous_selection(self) -> None:
        self.assertEqual(em.restore_index(["a", "b"], None, None), 0)


class SwapRuleTest(unittest.TestCase):
    """DESIGN §5: only inside the same group and the same sheet."""

    def test_group_rule(self) -> None:
        self.assertTrue(same_group(hint("a", "one", True), hint("b", "two", True)))
        self.assertFalse(same_group(hint("a", "one", True), hint("b", "one")))
        self.assertFalse(same_group(hint("a", "one"), hint("b", "two")))

    def test_a_hint_from_the_parent_sheet_is_a_different_file(self) -> None:
        mine = hint("a", "one", file="child.yaml")
        theirs = hint("b", "one", file="parent.yaml")
        self.assertTrue(same_group(mine, theirs), "same group…")
        self.assertNotEqual(mine.location.file, theirs.location.file, "…but not the same sheet")

    def test_neighbours_follow_the_displayed_order(self) -> None:
        hints = [hint("a", "one"), hint("fav", "two", favorite=True), hint("b", "one")]
        self.assertEqual([h.id for h in sort_hints(hints)], ["fav", "a", "b"])


class FormDraftTest(unittest.TestCase):
    def test_kind_decides_which_field_is_shown(self) -> None:
        self.assertEqual(em.kind_field("shortcut"), "key")
        self.assertEqual(em.kind_field("tip"), "key")
        self.assertEqual(em.kind_field("command"), "command")
        self.assertIsNone(em.kind_field("note"))

    def test_prefill_from_a_hint(self) -> None:
        draft = em.draft_from_hint(hint("h", "one", kind="command", command="/x"), "sheet")
        self.assertEqual(draft.hint_id, "h")
        self.assertEqual(draft.sheet_id, "sheet")
        self.assertEqual(draft.value("command"), "/x")
        self.assertEqual(draft.value("category"), "one")
        self.assertEqual(draft.value("remark"), "")

    def test_fields_drop_the_unused_one_and_blank_out_to_null(self) -> None:
        draft = em.FormDraft(
            fields={"title": " New pane ", "kind": "shortcut", "key": "Ctrl-n", "command": "/old"}
        )
        fields = em.draft_fields(draft)
        self.assertEqual(fields["title"], "New pane")
        self.assertEqual(fields["key"], "Ctrl-n")
        self.assertIsNone(fields["command"], "kind shortcut has no command")
        self.assertIsNone(fields["category"])

    def test_note_has_neither(self) -> None:
        draft = em.FormDraft(fields={"title": "T", "kind": "note", "key": "x", "command": "y"})
        fields = em.draft_fields(draft)
        self.assertIsNone(fields["key"])
        self.assertIsNone(fields["command"])

    def test_quick_add_draft_has_no_hint_id(self) -> None:
        self.assertIsNone(em.FormDraft().hint_id)
