"""Phase 7c: the edit-mode logic that can be tested without GTK.

The GTK shell (``ui/window.py``) is not tested here; what is tested is everything it defers to:
the grab rule, what a key means, the category filter, and where the selection lands after a
reload (dev-docs/DESIGN.md 編集モード §1, §2, §5, §8, §9).
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

    def test_the_arrow_keys_move_the_selection(self) -> None:
        """Taken here, not left to GTK: the focus does not stick on the layer surface, so the
        list never answered an arrow key and every single-key operation could only reach the
        first row (found while scripting the demo, fixed 2026-09-23)."""
        self.assertEqual(em.edit_action("Down"), em.SELECT_NEXT)
        self.assertEqual(em.edit_action("Up"), em.SELECT_PREVIOUS)
        self.assertEqual(em.edit_action("KP_Down"), em.SELECT_NEXT)
        self.assertEqual(em.edit_action("KP_Up"), em.SELECT_PREVIOUS)

    def test_the_arrow_keys_are_the_lists_in_a_text_field(self) -> None:
        """In the form they move the caret, and nothing here may take them."""
        for key in ("Down", "Up", "KP_Down", "KP_Up"):
            with self.subTest(key=key):
                self.assertIsNone(em.edit_action(key, editable=True))

    def test_a_modifier_makes_it_another_widgets_key(self) -> None:
        """Ctrl+d is "close the terminal", not "delete this hint" (DESIGN 編集モード §2)."""
        for key in ("a", "d", "u", "f", "J", "K", "Return"):
            with self.subTest(key=key):
                self.assertIsNone(em.edit_action(key, ctrl=True))

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


class ImeTest(unittest.TestCase):
    """A text field must see Enter and Esc before the overlay does, or IME input is impossible."""

    def test_enter_and_escape_are_not_taken_before_the_ime(self) -> None:
        for key in ("Return", "KP_Enter", "Escape"):
            with self.subTest(key=key):
                action = em.edit_action(key, editable=True)
                self.assertIn(action, (em.FORM_SAVE, em.FORM_CANCEL), "still the right meaning")
                self.assertFalse(
                    em.capture_in_editable(action),
                    "but only once the conversion is confirmed or cancelled",
                )

    def test_field_movement_is_taken_early(self) -> None:
        # Tab would otherwise move the focus out of the overlay before anyone sees it.
        for key, ctrl in (("Tab", False), ("ISO_Left_Tab", False), ("p", True)):
            with self.subTest(key=key):
                self.assertTrue(
                    em.capture_in_editable(em.edit_action(key, ctrl=ctrl, editable=True))
                )

    def test_plain_characters_are_never_captured(self) -> None:
        self.assertFalse(em.capture_in_editable(em.edit_action("a", editable=True)))

    def test_nothing_is_taken_early_while_a_conversion_is_open(self) -> None:
        # Tab picks a candidate and Ctrl+P walks the candidate list in the usual Japanese
        # input methods, so during a preedit the field has to see them first.
        for key, ctrl in (("Tab", False), ("ISO_Left_Tab", False), ("p", True)):
            with self.subTest(key=key):
                action = em.edit_action(key, ctrl=ctrl, editable=True)
                self.assertFalse(em.capture_in_editable(action, preedit=True))
                self.assertTrue(em.capture_in_editable(action), "and taken again once it is over")


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

    def test_candidates_with_the_same_prefix_are_all_reachable(self) -> None:
        # `screen` and `session` both start with "s": completing to the first and stopping there
        # would hide the other one (found in T20, 2026-09-18).
        order = ["panes", "screen", "session", None]
        self.assertEqual(em.completions("s", order), ["screen", "session"])
        first = em.next_completion("s", order)
        self.assertEqual(first, "screen")
        self.assertEqual(em.next_completion("s", order, first), "session")
        self.assertEqual(em.next_completion("s", order, "session"), "screen", "wraps around")
        self.assertEqual(em.next_completion("s", order, "screen", forward=False), "session")

    def test_completion_of_an_unknown_prefix(self) -> None:
        self.assertIsNone(em.next_completion("zzz", ["panes", None]))
        self.assertEqual(em.completions("zzz", ["panes", None]), [])


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
    def test_same_id_in_different_files_keeps_the_selected_owner(self) -> None:
        a, b = (Path("a.yaml"), "same"), (Path("b.yaml"), "same")
        self.assertEqual(em.restore_index([a, b], b, 0), 1)

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


class NextSelectionTest(unittest.TestCase):
    """Where ``↑`` / ``↓`` put the selection (DESIGN 編集モード §2)."""

    def test_one_row_at_a_time(self) -> None:
        self.assertEqual(em.next_selection(3, 0, 1), 1)
        self.assertEqual(em.next_selection(3, 2, -1), 1)

    def test_it_stops_at_the_ends_rather_than_wrapping(self) -> None:
        """Wrapping from the last row to the first reads as "it did nothing"."""
        self.assertEqual(em.next_selection(3, 2, 1), 2)
        self.assertEqual(em.next_selection(3, 0, -1), 0)

    def test_nothing_selected_yet(self) -> None:
        self.assertEqual(em.next_selection(3, None, 1), 0)
        self.assertEqual(em.next_selection(3, None, -1), 2)

    def test_an_empty_list(self) -> None:
        self.assertIsNone(em.next_selection(0, None, 1))


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

    def test_sheet_for_hint_finds_the_owner(self) -> None:
        from wayhint.models import HintSheet
        from wayhint.selection import sheet_for_hint

        child = HintSheet(id="child", title="C", path=Path("child.yaml"))
        parent = HintSheet(id="parent", title="P", path=Path("parent.yaml"))
        sheets = [child, parent]
        # "Edit in editor" has to open the sheet of the selected hint, which in a nested view is
        # often the parent, not the active sheet.
        self.assertIs(sheet_for_hint(sheets, hint("a", file="parent.yaml")), parent)
        self.assertIs(sheet_for_hint(sheets, hint("a", file="child.yaml")), child)
        self.assertIsNone(sheet_for_hint(sheets, hint("a", file="gone.yaml")))
        self.assertIsNone(sheet_for_hint(sheets, None))

    def test_neighbours_follow_the_displayed_order(self) -> None:
        hints = [hint("a", "one"), hint("fav", "two", favorite=True), hint("b", "one")]
        self.assertEqual([h.id for h in sort_hints(hints)], ["fav", "a", "b"])


class StaleSheetTest(unittest.TestCase):
    """DESIGN §1 / 0014 D2: only the sheet that is actually broken is off limits."""

    def test_another_broken_sheet_does_not_block_this_one(self) -> None:
        broken = {Path("/c/hints/other.yaml")}
        self.assertFalse(em.sheet_is_stale(Path("/c/hints/active.yaml"), broken))
        self.assertTrue(em.sheet_is_stale(Path("/c/hints/other.yaml"), broken))

    def test_no_sheet_at_all_is_not_stale(self) -> None:
        # A context with no sheet yet: quick add is allowed, the sheet is created on save.
        self.assertFalse(em.sheet_is_stale(None, {Path("/c/hints/other.yaml")}))

    def test_ctrl_p_moves_the_target_to_the_parent_sheet(self) -> None:
        context = ResolvedContext(active_sheet="child", parent_context="parent")
        draft = em.FormDraft(sheet_id="child")
        self.assertEqual(em.target_sheet_id(draft, context), "child")
        draft.to_parent = True
        self.assertEqual(
            em.target_sheet_id(draft, context),
            "parent",
            "so a broken parent has to be re-checked after Ctrl+P",
        )


class FormDraftTest(unittest.TestCase):
    def test_kind_decides_which_fields_are_shown(self) -> None:
        # Changed 2026-09-18: tip and note are notes to self. A tip often says "press this, or
        # run that", so it carries both; a note is prose and carries neither.
        self.assertEqual(em.kind_fields("shortcut"), ("key",))
        self.assertEqual(em.kind_fields("command"), ("command",))
        self.assertEqual(em.kind_fields("tip"), ("key", "command"))
        self.assertEqual(em.kind_fields("note"), ())
        self.assertEqual(em.MEMO_KINDS, ("tip", "note"))

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

    def test_a_note_never_shows_a_key_or_a_command(self) -> None:
        # The YAML may still carry them from before the hint became a note; the row stays prose.
        self.assertEqual(em.display_fields("note"), ())
        for kind in ("shortcut", "command", "tip"):
            with self.subTest(kind=kind):
                self.assertEqual(em.display_fields(kind), ("key", "command"))

    def test_tip_keeps_both(self) -> None:
        draft = em.FormDraft(
            fields={"title": "T", "kind": "tip", "key": "Ctrl-r", "command": "reset"}
        )
        fields = em.draft_fields(draft)
        self.assertEqual(fields["key"], "Ctrl-r")
        self.assertEqual(fields["command"], "reset")

    def test_quick_add_draft_has_no_hint_id(self) -> None:
        self.assertIsNone(em.FormDraft().hint_id)


class CopiedDetailTest(unittest.TestCase):
    """The detail pane says what ``c`` would copy whenever the row does not already say it."""

    def test_nothing_to_copy_shows_nothing(self) -> None:
        self.assertIsNone(em.copied_detail(hint("a")))

    def test_command_alone_is_already_on_the_row(self) -> None:
        self.assertIsNone(em.copied_detail(hint("a", command="git status")))

    def test_copy_that_differs_from_the_command_is_shown(self) -> None:
        shown = em.copied_detail(hint("a", command="git status", copy="curl x | sh"))
        self.assertEqual(shown, "curl x | sh")

    def test_copy_without_a_command_is_shown(self) -> None:
        self.assertEqual(em.copied_detail(hint("a", copy="make test")), "make test")

    def test_control_characters_are_written_out(self) -> None:
        shown = em.copied_detail(hint("a", command="ls", copy="ls\n"))
        self.assertEqual(shown, "ls\\n")
        self.assertEqual(em.copied_detail(hint("a", command="a\tb\x1b")), "a\\tb\\x1b")

    def test_non_ascii_text_is_left_as_it_is(self) -> None:
        self.assertEqual(em.visible("日本語 ⌘"), "日本語 ⌘")
