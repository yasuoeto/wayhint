"""Search mode and the kept filter (DECISIONS 0033), without GTK.

The pure half -- what the filter keeps, what Tab writes, what a key means, what gets copied --
is tested on :mod:`wayhint.ui.editmode`. The daemon half -- the one way out of search, where the
filter goes, when state.yaml is written -- uses the window fake of ``test_daemon_edit`` with the
real store and real files.
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from tests.test_daemon_edit import Window, Workspace
from tests.test_editmode import hint
from wayhint import daemon as daemon_module
from wayhint.daemon import Daemon
from wayhint.models import ResolvedContext
from wayhint.selection import sort_hints
from wayhint.state import load_state
from wayhint.ui import editmode as em
from wayhint.ui.editmode import WorkspaceView


class FilterHintsTest(unittest.TestCase):
    """One list for every mode: the filter narrows the sorted list and keeps its sections."""

    def setUp(self):
        self.hints = sort_hints(
            [
                hint("split", "panes", title="split pane"),
                hint("zoom", "panes", favorite=True, title="zoom pane"),
                hint("detach", "session", title="detach"),
                hint("loose", None, title="loose pane"),
                hint("star", None, favorite=True, title="star"),
            ]
        )

    def ids(self, text, limit=None):
        return [h.id for h in em.filter_hints(self.hints, text, limit)]

    def test_no_filter_is_the_whole_sorted_list(self):
        self.assertEqual(self.ids(""), [h.id for h in self.hints])

    def test_text_keeps_the_favorite_section_first(self):
        self.assertEqual(self.ids("pane"), ["zoom", "split", "loose"])

    def test_category_and_text_together(self):
        self.assertEqual(self.ids("#panes split"), ["split"])
        self.assertEqual(self.ids("#panes"), ["zoom", "split"])

    def test_the_pseudo_category_is_spelled_with_a_dash(self):
        self.assertEqual(self.ids("#-"), ["star", "loose"])
        self.assertEqual(self.ids("#- pane"), ["loose"])

    def test_the_limit_only_cuts_a_filtered_list(self):
        self.assertEqual(len(self.ids("", limit=2)), len(self.hints))
        self.assertEqual(self.ids("pane", limit=2), ["zoom", "split"])

    def test_the_text_is_never_a_pattern(self):
        self.assertEqual(self.ids(".*"), [])
        self.assertEqual(self.ids("[pane"), [])


class FilterTextTest(unittest.TestCase):
    """Tab writes the category into the box, because the box is the filter (0033 C)."""

    order = ["one", None, "two"]

    def test_cycle_writes_each_stop_and_keeps_the_words(self):
        text, seen = "foo", []
        for _ in range(4):
            text = em.cycle_filter_text(text, self.order)
            seen.append(text)
        self.assertEqual(seen, ["#one foo", "#- foo", "#two foo", "foo"])

    def test_cycle_backwards_from_nothing_goes_to_the_last(self):
        self.assertEqual(em.cycle_filter_text("", self.order, forward=False), "#two ")

    def test_parse_reads_the_dash_back(self):
        self.assertEqual(em.parse_search("#- x").category, em.PSEUDO_CATEGORY)
        self.assertEqual(em.parse_search("#-").category, em.PSEUDO_CATEGORY)


class SearchKeysTest(unittest.TestCase):
    def test_c_and_enter_on_the_list_copy_and_leave(self):
        for key in ("c", "Return", "KP_Enter"):
            with self.subTest(key=key):
                self.assertEqual(em.search_action(key), em.COPY_AND_LEAVE)

    def test_nothing_is_taken_from_the_search_box_or_with_a_modifier(self):
        self.assertIsNone(em.search_action("c", editable=True))
        self.assertIsNone(em.search_action("Return", editable=True))  # the IME's first
        self.assertIsNone(em.search_action("c", ctrl=True))
        self.assertIsNone(em.search_action("x"))

    def test_copy_target_is_the_copy_button_rule(self):
        self.assertEqual(em.copy_target(hint("a", copy="c", command="m", key="k")), "c")
        self.assertEqual(em.copy_target(hint("a", command="m", key="k")), "m")
        self.assertEqual(em.copy_target(hint("a", key="k")), "k")
        self.assertIsNone(em.copy_target(hint("a", kind="note")))
        self.assertIsNone(em.copy_target(None))


class Resolver:
    def __init__(self, sheet="b"):
        self.sheet = sheet

    def resolve(self, sheets, config):
        return ResolvedContext(active_sheet=self.sheet)


class DaemonCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "hints").mkdir()
        self.paths = [self.root / "hints" / f"{name}.yaml" for name in ("a", "b")]
        for name, path in zip(("a", "b"), self.paths, strict=True):
            path.write_text(
                f"id: {name}\ntitle: {name}\nhints:\n"
                f"  - {{id: same, title: {name} original, key: k}}\n"
                f"  - {{id: next, title: {name} next}}\n"
            )
        self.state = self.root / "state" / "wayhint" / "state.yaml"
        self.daemon = self.make_daemon()
        self.window = Window()
        self.window.mode = "normal"
        self.daemon.window = self.window
        self.view = WorkspaceView(ResolvedContext(active_sheet="b"))
        self.daemon._open[""] = self.view
        self.daemon._shown_key = ""

    def make_daemon(self):
        daemon = Daemon(self.root, self.root / "unused.sock", self.state)
        daemon.config = replace(daemon.config, workspace_scope="all")
        daemon.store.load_all()
        daemon.resolver = Resolver()
        return daemon

    def search(self, text):
        self.daemon.on_edit_action(em.BEGIN_SEARCH, None)
        self.window.text = text


class DaemonSearchTest(DaemonCase):
    def test_leaving_keeps_the_filter_on_the_view_the_window_and_the_file(self):
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.assertEqual((self.view.mode, self.window.mode), ("normal", "normal"))
        self.assertEqual((self.view.filter_query, self.window.filter), ("pane", "pane"))
        self.assertEqual(load_state(self.state), ({"b": "pane"}, []))

    def test_coming_back_puts_the_kept_filter_in_the_box(self):
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.daemon.on_edit_action(em.BEGIN_SEARCH, None)
        self.assertEqual(self.window.text, "pane")

    def test_an_empty_box_removes_the_sheet_from_the_file(self):
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.search("")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.assertEqual(load_state(self.state), ({}, []))
        self.assertEqual(self.window.filter, "")

    def test_control_characters_never_reach_the_filter(self):
        self.search("pa\x07ne")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.assertEqual(self.view.filter_query, "pane")

    def test_the_same_filter_is_not_written_twice(self):
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        with mock.patch.object(daemon_module, "save_state") as save:
            self.search("pane")
            self.daemon.on_edit_action(em.END_SEARCH, None)
        save.assert_not_called()

    def test_a_context_without_a_sheet_keeps_its_filter_in_memory_only(self):
        self.view.context = ResolvedContext(active_sheet=None, desktop_app="x")
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.assertEqual(self.view.filter_query, "pane")
        self.assertFalse(self.state.exists())

    def test_a_failed_write_keeps_the_filter_and_logs_without_it(self):
        with (
            mock.patch.object(daemon_module, "save_state", side_effect=OSError(28, "No space")),
            self.assertLogs("wayhintd", level="WARNING") as logs,
        ):
            self.search("secret words")
            self.daemon.on_edit_action(em.END_SEARCH, None)
        self.assertEqual(self.daemon.filters, {"b": "secret words"})
        self.assertNotIn("secret", "\n".join(logs.output))
        self.search("secret words")  # nothing new, but the file is still behind: try again
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.assertEqual(load_state(self.state), ({"b": "secret words"}, []))

    def test_a_broken_file_starts_without_filters_and_is_written_over(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("foo: [")
        with self.assertLogs("wayhintd", level="WARNING") as logs:
            daemon = self.make_daemon()
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(daemon.filters, {})
        daemon.window = self.window
        daemon._open[""] = self.view
        daemon._shown_key = ""
        daemon.on_edit_action(em.BEGIN_SEARCH, None)
        self.window.text = "pane"
        daemon.on_edit_action(em.END_SEARCH, None)
        self.assertEqual(load_state(self.state), ({"b": "pane"}, []))

    def test_a_sheet_opened_again_starts_with_its_kept_filter(self):
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.daemon.hide()
        self.daemon.show()
        self.assertEqual(self.daemon._current_view().filter_query, "pane")
        self.assertEqual(self.window.filter, "pane")
        self.daemon = self.make_daemon()  # and after a restart
        self.assertEqual(self.daemon.filters, {"b": "pane"})

    def test_another_workspace_opening_the_same_sheet_gets_the_same_filter(self):
        workspace = Workspace()
        self.daemon._watcher = workspace
        self.daemon._open = {"A": self.view}
        self.daemon._shown_key = "A"
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        workspace.key = "B"
        self.daemon.show()
        self.assertEqual(self.daemon._open["B"].filter_query, "pane")

    def test_hide_is_a_way_out_that_keeps_the_filter(self):
        self.search("pane")
        self.daemon.hide()
        self.assertEqual(load_state(self.state), ({"b": "pane"}, []))

    def test_replacing_the_view_keeps_the_filter_of_the_one_it_replaces(self):
        self.search("pane")
        self.daemon.resolver = Resolver("a")
        self.daemon.toggle()  # another window: replace b with a
        self.assertEqual(self.daemon.filters, {"b": "pane"})
        self.assertEqual(self.daemon._current_view().mode, "normal")

    def test_leaving_the_workspace_ends_the_search_and_keeps_the_filter(self):
        workspace = Workspace()
        self.daemon._watcher = workspace
        self.daemon._open = {"A": self.view}
        self.daemon._shown_key = "A"
        self.search("pane")
        workspace.key = "B"
        workspace.known = lambda: {"A", "B"}
        self.daemon._apply_workspace()
        self.assertEqual(self.view.mode, "normal")
        self.assertEqual(self.daemon.filters, {"b": "pane"})

    def test_the_editor_ends_the_search_and_keeps_the_filter(self):
        self.search("pane")
        sheet = next(s for s in self.daemon.store.sheets if s.path == self.paths[1])
        with mock.patch.object(daemon_module, "open_in_editor"):
            self.daemon.edit(sheet, sheet.hints[0])
        self.assertEqual((self.view.mode, self.view.filter_query), ("normal", "pane"))
        self.assertTrue(self.window.visible)

    def test_the_chip_clears_the_filter_for_the_sheet(self):
        self.search("pane")
        self.daemon.on_edit_action(em.END_SEARCH, None)
        self.daemon.on_edit_action(em.CLEAR_FILTER, None)
        self.assertEqual((self.view.filter_query, self.window.filter), ("", ""))
        self.assertEqual(load_state(self.state), ({}, []))


class SearchModeIpcTest(DaemonCase):
    """``wayhint search-mode`` (0033 A), over the same dispatch the socket uses."""

    def test_enters_search_and_again_leaves_it_with_the_filter(self):
        self.assertEqual(self.daemon.dispatch("search-mode")["mode"], "search")
        self.assertEqual((self.view.mode, self.window.mode), ("search", "search"))
        self.window.text = "pane"
        reply = self.daemon.dispatch("search-mode")
        self.assertEqual(reply["mode"], "normal")
        self.assertEqual((self.view.mode, self.window.mode), ("normal", "normal"))
        self.assertEqual(self.view.filter_query, "pane")

    def test_shows_the_overlay_first_when_it_is_hidden(self):
        self.daemon.hide()
        self.assertEqual(self.daemon.dispatch("search-mode")["mode"], "search")
        self.assertTrue(self.window.visible)
        self.assertEqual(self.daemon._current_view().mode, "search")

    def test_refused_while_editing(self):
        self.view.mode = "edit"
        self.window.mode = "edit"
        reply = self.daemon.dispatch("search-mode")
        self.assertFalse(reply["ok"])
        self.assertEqual((self.view.mode, self.window.mode), ("edit", "edit"))
        self.assertTrue(self.window.messages[-1].startswith("⚠"))


class MoveWhileFilteredTest(DaemonCase):
    """``J`` / ``K`` do nothing while the list is filtered (0033 G)."""

    def move(self, action, hint_id):
        before = self.paths[1].read_bytes()
        self.daemon.on_edit_action(action, {"hint_id": hint_id, "file": str(self.paths[1])})
        return before

    def test_move_down_is_ignored(self):
        self.view.filter_query = "b"
        before = self.move(em.MOVE_DOWN, "same")
        self.assertEqual(self.paths[1].read_bytes(), before)
        self.assertEqual(self.window.messages, [])

    def test_move_up_is_ignored(self):
        self.view.filter_query = "#-"
        before = self.move(em.MOVE_UP, "next")
        self.assertEqual(self.paths[1].read_bytes(), before)

    def test_without_a_filter_it_still_moves(self):
        before = self.move(em.MOVE_DOWN, "same")
        self.assertNotEqual(self.paths[1].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
