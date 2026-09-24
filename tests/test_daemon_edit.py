"""Controller integration tests with a window boundary fake; no GUI or compositor imports."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from wayhint import daemon as daemon_module
from wayhint.daemon import Daemon
from wayhint.editor import EditorError
from wayhint.models import ResolvedContext
from wayhint.ui import editmode as em
from wayhint.ui.editmode import WorkspaceView
from wayhint.yaml_store import SheetWriteError, load_sheet


class Window:
    """Only the widget boundary is replaced; actions use real store and YAML writes."""

    def __init__(self):
        self.mode = "edit"
        self.form = None
        self.messages = []
        self.context = None
        self.includes = []
        self.visible = True
        self.filter = ""  # what set_filter last handed over
        self.text = ""  # what the search box holds

    def open_form(self, draft):
        self.form = draft

    def close_form(self):
        self.form = None

    def form_draft(self):
        return self.form

    def show_form_error(self, text):
        self.messages.append(text)

    def show_message(self, text):
        self.messages.append(text)

    def is_shown(self):
        return self.visible

    def hide_overlay(self):
        self.visible = False

    def present_context(self, context, sheets, config, includes=()):
        self.context = context
        self.includes = list(includes)
        self.visible = True

    def show_issues(self, issues):
        pass

    def set_mode(self, mode, *, refocus=True):
        if mode == "search" and self.mode != "search":
            self.text = self.filter  # the kept filter comes back in the box (0033 C)
        self.mode = mode
        if mode != "edit":
            self.close_form()

    def set_filter(self, query, *, render=True):
        self.filter = query

    def search_text(self):
        return self.text


class Workspace:
    def __init__(self, alive=True):
        self.key = "A"
        self.alive = alive
        self.stopped = False

    def active(self):
        return self.key

    def roundtrip(self):
        return True

    def known(self):
        return {self.key}

    def dispatch(self):
        return self.alive

    def stop(self):
        self.stopped = True


class DaemonEditTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "hints").mkdir()
        self.paths = [self.root / "hints" / f"{name}.yaml" for name in ("a", "b")]
        for name, path in zip(("a", "b"), self.paths, strict=True):
            path.write_text(
                f"id: {name}\ntitle: {name}\nhints:\n"
                f"  - {{id: same, title: {name} original}}\n"
                f"  - {{id: next, title: {name} next}}\n"
            )
        self.daemon = Daemon(self.root, self.root / "unused.sock")
        self.daemon.config = replace(self.daemon.config, workspace_scope="all")
        self.daemon.store.load_all()
        self.window = Window()
        self.daemon.window = self.window
        self.view = WorkspaceView(ResolvedContext(active_sheet="b"), mode="edit")
        self.daemon._open[""] = self.view
        self.daemon._shown_key = ""

    def action(self, name, hint_id="same", path=None):
        self.daemon.on_edit_action(name, {"hint_id": hint_id, "file": str(path or self.paths[1])})

    def sheet(self, path):
        sheet, issues = load_sheet(path)
        self.assertEqual(issues, [])
        return sheet

    def test_delete_changes_only_the_selected_sheet_with_a_shared_hint_id(self):
        before = self.paths[0].read_bytes()
        self.action(em.DELETE_COMMIT)
        self.assertEqual(self.paths[0].read_bytes(), before)
        self.assertEqual([h.id for h in self.sheet(self.paths[1]).hints], ["next"])

    def test_edit_and_save_keep_the_owner_even_with_another_matching_id(self):
        before = self.paths[0].read_bytes()
        self.action(em.OPEN_FORM)
        self.assertEqual(self.window.form.value("title"), "b original")
        self.window.form.fields["title"] = "edited B"
        self.daemon.on_edit_action(em.FORM_SAVE, {"draft": self.window.form})
        self.assertEqual(self.paths[0].read_bytes(), before)
        self.assertEqual(self.sheet(self.paths[1]).hints[0].title, "edited B")
        self.assertIsNone(self.window.form)

    def test_missing_owner_never_falls_back_to_another_sheet(self):
        self.action(em.OPEN_FORM)
        before = self.paths[0].read_bytes()
        self.paths[1].unlink()
        self.daemon.store.reload(self.paths[1])
        self.daemon.on_edit_action(em.FORM_SAVE, {"draft": self.window.form})
        self.assertEqual(self.paths[0].read_bytes(), before)
        self.assertIsNotNone(self.window.form)
        self.assertTrue(self.window.messages[-1].startswith("⚠"))

    def test_favorite_changes_only_the_selected_sheet(self):
        before = self.paths[0].read_bytes()
        self.action(em.FAVORITE)
        self.assertEqual(self.paths[0].read_bytes(), before)
        self.assertTrue(self.sheet(self.paths[1]).hints[0].favorite)

    def test_move_locates_the_selected_parent_hint_not_the_same_id_in_the_child(self):
        path = self.paths[1]
        path.write_text(path.read_text().replace("title: b ", "tags: [shared], title: b "))
        self.daemon.store.reload(path)
        self.daemon.config = replace(self.daemon.config, parent_tags=("shared",))
        self.view.context = ResolvedContext(active_sheet="a", parent_context="b")
        before = self.paths[0].read_bytes()
        self.action(em.MOVE_DOWN)
        self.assertEqual(self.paths[0].read_bytes(), before)
        self.assertEqual([h.id for h in self.sheet(path).hints], ["next", "same"])

    def test_restore_workspace_without_a_form_does_not_inherit_another_draft(self):
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved A"
        workspace = Workspace()
        self.daemon._watcher = workspace
        self.daemon._open = {
            "A": self.view,
            "B": WorkspaceView(ResolvedContext(active_sheet="a"), mode="edit"),
        }
        self.daemon._shown_key = "A"
        self.daemon.toggle()  # hide A, preserving its live draft
        workspace.key = "B"
        self.daemon.toggle()  # restore B's edit list, which has no form
        self.assertIsNone(self.window.form)
        self.daemon.toggle()
        workspace.key = "A"
        self.daemon.toggle()
        self.assertEqual(self.window.form.value("title"), "unsaved A")

    def test_search_actions_keep_controller_and_window_modes_in_sync(self):
        self.view.mode = "normal"
        self.window.set_mode("normal")
        self.daemon.on_edit_action("begin-search", None)
        self.assertEqual((self.view.mode, self.window.mode), ("search", "search"))
        self.daemon.on_edit_action("end-search", None)
        self.assertEqual((self.view.mode, self.window.mode), ("normal", "normal"))

    def test_cancel_closes_both_the_controller_draft_and_the_visible_form(self):
        self.action(em.OPEN_FORM)
        self.daemon.on_edit_action(em.FORM_CANCEL, None)
        self.assertIsNone(self.view.form)
        self.assertIsNone(self.window.form)
        self.assertEqual((self.view.mode, self.window.mode), ("edit", "edit"))

    def test_search_request_during_edit_preserves_the_live_draft(self):
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        self.daemon.on_edit_action("begin-search", None)
        self.assertEqual((self.view.mode, self.window.mode), ("edit", "edit"))
        self.assertEqual(self.window.form.value("title"), "unsaved")

    def test_edit_mode_restores_a_hidden_draft_without_resolving_another_context(self):
        class OtherContext:
            def resolve(self, sheets, config):
                return ResolvedContext(active_sheet="a")

        self.daemon.resolver = OtherContext()
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        self.daemon.toggle()
        self.daemon.enter_edit_mode()
        self.assertEqual(self.window.context.active_sheet, "b")
        self.assertEqual(self.window.form.value("title"), "unsaved")

    def test_edit_mode_from_another_window_replaces_what_is_shown_then_edits(self):
        class OtherContext:
            def resolve(self, sheets, config):
                return ResolvedContext(active_sheet="a")

        self.view.mode = self.window.mode = "normal"  # shown, not editing yet
        self.daemon.resolver = OtherContext()  # another Herdr tab, say
        reply = self.daemon.enter_edit_mode()
        self.assertEqual((reply["mode"], reply["sheet"]), ("edit", "a"))
        view = self.daemon._current_view()
        self.assertIsNot(view, self.view)
        self.assertEqual((view.mode, self.window.mode), ("edit", "edit"))
        self.assertEqual(self.window.context.active_sheet, "a")

    def test_edit_mode_keeps_a_view_holding_a_draft_from_an_editor_start(self):
        class OtherContext:
            def resolve(self, sheets, config):
                return ResolvedContext(active_sheet="a")

        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        self.daemon._release_for_editor()  # back to normal, the draft kept in the view (0023)
        self.daemon.resolver = OtherContext()
        self.daemon.enter_edit_mode()
        self.assertIs(self.daemon._current_view(), self.view)
        self.assertEqual(self.view.mode, "edit")
        self.assertEqual(self.window.form.value("title"), "unsaved")

    def lose_the_watch(self):
        """The compositor connection dies while the overlay is open on workspace A."""
        watcher = Workspace(alive=False)
        self.daemon._watcher = watcher
        self.daemon._open = {"A": self.view}
        self.daemon._shown_key = "A"
        with self.assertLogs("wayhintd", level="WARNING"):  # and it says so in the log
            self.daemon._on_watch_fd(0, None)
        return watcher

    def test_losing_the_workspace_watch_keeps_the_open_view_and_its_draft(self):
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        watcher = self.lose_the_watch()
        self.assertTrue(watcher.stopped)
        self.assertIsNone(self.daemon._watcher)
        self.assertIs(self.daemon._current_view(), self.view)
        self.assertEqual(self.window.form.value("title"), "unsaved")

    def test_escape_after_losing_the_workspace_watch_leaves_edit_mode(self):
        self.lose_the_watch()
        self.daemon.on_edit_action(em.EXIT_EDIT, None)
        self.assertEqual((self.view.mode, self.window.mode), ("normal", "normal"))

    def test_close_after_losing_the_workspace_watch_closes_the_overlay(self):
        self.lose_the_watch()
        self.daemon.close()
        self.assertFalse(self.window.visible)
        self.assertEqual(self.daemon._open, {})

    def test_hide_during_edit_keeps_the_draft_like_the_toggle_hotkey(self):
        # ``wayhint hide`` is the toggle hotkey's hide, not the Close button (0037).
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        self.assertEqual(self.daemon.dispatch("hide"), {"visible": False, "mode": "edit"})
        self.assertFalse(self.window.visible)
        self.assertIs(self.daemon._current_view(), self.view)
        self.assertEqual(self.view.mode, "edit")
        self.daemon.enter_edit_mode()  # the mode hotkey brings it back as it was
        self.assertTrue(self.window.visible)
        self.assertEqual(self.window.form.value("title"), "unsaved")

    def test_the_close_button_drops_the_draft(self):
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        self.daemon.close()
        self.assertFalse(self.window.visible)
        self.assertEqual(self.daemon._open, {})

    def open_the_editor(self, **patch):
        sheet = next(s for s in self.daemon.store.sheets if s.path == self.paths[1])
        with mock.patch.object(daemon_module, "open_in_editor", **patch) as spawn:
            self.daemon.edit(sheet, sheet.hints[0])
        return spawn

    def test_starting_the_editor_frees_the_keyboard_without_hiding_the_hints(self):
        # Curating in the editor is when the result is worth watching, so the overlay stays;
        # only the grab goes, or the editor would come up with no way to type in it (0023).
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        self.open_the_editor()
        self.assertTrue(self.window.visible)
        self.assertEqual((self.view.mode, self.window.mode), ("normal", "normal"))

    def test_a_draft_that_was_open_comes_back_with_edit_mode(self):
        self.action(em.OPEN_FORM)
        self.window.form.fields["title"] = "unsaved"
        self.open_the_editor()
        self.assertIsNone(self.window.form)
        self.daemon.enter_edit_mode()
        self.assertEqual(self.window.form.value("title"), "unsaved")

    def test_what_the_editor_writes_shows_up_on_the_visible_overlay(self):
        self.view.mode = "normal"
        self.window.set_mode("normal")
        self.paths[1].write_text(
            "id: b\ntitle: b\nhints:\n  - {id: same, title: curated in the editor}\n"
        )
        self.daemon._debounced_reload(self.paths[1])
        self.assertTrue(self.window.visible)
        self.assertEqual(self.sheet(self.paths[1]).hints[0].title, "curated in the editor")
        self.assertEqual([s.id for s in self.daemon.store.sheets], ["a", "b"])

    def test_an_editor_that_cannot_start_leaves_the_overlay_as_it_was(self):
        self.action(em.OPEN_FORM)
        self.open_the_editor(side_effect=EditorError("gvim: not found"))
        self.assertTrue(self.window.visible)
        self.assertTrue(self.window.messages[-1].startswith("⚠"))
        self.assertIsNotNone(self.window.form)

    def test_the_plain_list_is_left_alone_when_the_editor_starts(self):
        self.view.mode = "normal"
        self.window.set_mode("normal")
        self.open_the_editor()
        self.assertTrue(self.window.visible)
        self.assertEqual(self.view.mode, "normal")

    def test_a_hidden_view_is_brought_back_by_the_hotkey_rather_than_closed(self):
        # Hidden but still recorded (the workspace watch was lost): one press shows it again.
        class SameWindow:
            def resolve(self, sheets, config):
                return ResolvedContext(active_sheet="b")

        self.daemon.resolver = SameWindow()
        self.view.mode = "normal"
        self.window.set_mode("normal")
        self.window.hide_overlay()
        self.daemon.toggle()
        self.assertTrue(self.window.visible)
        self.assertEqual(self.window.context.active_sheet, "b")

    def test_a_resize_that_cannot_be_written_is_reported_not_raised(self):
        # The drag ends inside a GTK callback: an OSError from the write would be a traceback
        # in the log and nothing on screen.
        with mock.patch.object(daemon_module, "write_config", side_effect=OSError("read-only")):
            self.daemon.resize(500, 400)
        self.assertTrue(self.window.messages[-1].startswith("⚠"))

    def test_two_favorite_presses_in_a_row_really_toggle_twice(self):
        # The reload is debounced (200 ms), so a second press lands while the store still has
        # the old value. What is written has to come from the file, not from that copy.
        self.action(em.FAVORITE)
        self.assertTrue(self.sheet(self.paths[1]).hints[0].favorite)
        self.action(em.FAVORITE)
        self.assertFalse(self.sheet(self.paths[1]).hints[0].favorite)

    def test_an_edit_action_applies_a_reload_that_is_still_pending(self):
        self.paths[1].write_text(
            "id: b\ntitle: b\nhints:\n  - {id: same, title: changed on disk}\n"
        )
        self.daemon._pending_reload[self.paths[1]] = 1  # the monitor saw it, the timer has not run
        with mock.patch.object(daemon_module, "GLib", mock.Mock(), create=True):
            self.action(em.OPEN_FORM)
        self.assertEqual(self.window.form.value("title"), "changed on disk")
        self.assertEqual(self.daemon._pending_reload, {})

    def save_form(self, **fields):
        self.window.form.fields.update(fields)
        self.daemon.on_edit_action(em.FORM_SAVE, {"draft": self.window.form})

    def quick_add(self, path=None):
        payload = {"file": str(path)} if path is not None else {}
        self.daemon.on_edit_action(em.ADD, payload)

    def test_quick_add_goes_into_the_sheet_of_the_hint_under_the_cursor(self):
        # The list mixes in the parent sheet's hints, so "this sheet" is the selected hint's.
        self.quick_add(self.paths[0])
        self.assertEqual(self.window.form.sheet_id, "a")
        self.save_form(title="from the parent sheet")
        titles = [h.title for h in self.sheet(self.paths[0]).hints]
        self.assertEqual(titles[-1], "from the parent sheet")

    def test_quick_add_without_a_selection_uses_the_active_sheet(self):
        self.quick_add()
        self.assertEqual(self.window.form.sheet_id, "b")

    def test_quick_add_falls_back_when_the_selected_sheet_is_gone(self):
        self.paths[0].unlink()
        self.daemon.store.reload(self.paths[0])
        self.quick_add(self.paths[0])
        self.assertEqual(self.window.form.sheet_id, "b")

    def test_saving_a_quick_add_leaves_edit_mode(self):
        # edit holds the keyboard; once the hint is written the user wants the app back (0021).
        self.daemon.on_edit_action(em.ADD, None)
        self.save_form(title="a new hint")
        self.assertEqual((self.view.mode, self.window.mode), ("normal", "normal"))
        self.assertIsNone(self.view.form)
        self.assertIsNone(self.window.form)

    def test_saving_an_edited_hint_leaves_edit_mode(self):
        self.action(em.OPEN_FORM)
        self.save_form(title="edited")
        self.assertEqual((self.view.mode, self.window.mode), ("normal", "normal"))
        self.assertEqual(self.sheet(self.paths[1]).hints[0].title, "edited")

    def test_single_key_operations_stay_in_edit_mode(self):
        for action in (em.FAVORITE, em.MOVE_DOWN, em.DELETE_CONFIRM, em.DELETE_COMMIT, em.UNDO):
            with self.subTest(action=action):
                self.view.mode = "edit"
                self.window.set_mode("edit")
                self.action(action)
                self.assertEqual((self.view.mode, self.window.mode), ("edit", "edit"))

    def test_a_save_that_cannot_be_written_stays_in_edit_mode(self):
        self.action(em.OPEN_FORM)
        with (
            mock.patch.object(
                daemon_module, "write_document", side_effect=SheetWriteError("would not validate")
            ),
            self.assertLogs("wayhintd", level="WARNING"),
        ):
            self.save_form(title="edited")
        self.assertEqual((self.view.mode, self.window.mode), ("edit", "edit"))
        self.assertIsNotNone(self.window.form)
        self.assertTrue(self.window.messages[-1].startswith("⚠"))


class DaemonHintsDirTest(unittest.TestCase):
    """The daemon reads the language's directory, and follows a change of language (0024)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for lang, title in (("en", "English sheet"), ("ja", "日本語のシート")):
            (self.root / "hints" / lang).mkdir(parents=True)
            (self.root / "hints" / lang / "x.yaml").write_text(
                f"id: x\ntitle: {title}\nhints:\n  - {{id: h, title: {title}}}\n"
            )
        self.daemon = Daemon(self.root, self.root / "unused.sock")

    def titles(self):
        return [s.title for s in self.daemon.store.sheets]

    def set_language(self, language):
        (self.root / "config.yaml").write_text(f"appearance:\n  language: {language}\n")
        self.daemon.reload_all()

    def test_the_language_decides_which_sheets_are_loaded(self):
        self.set_language("ja")
        self.assertEqual(self.titles(), ["日本語のシート"])
        self.set_language("en")
        self.assertEqual(self.titles(), ["English sheet"])

    def test_a_new_sheet_is_created_where_the_others_are_read_from(self):
        self.set_language("ja")
        self.assertEqual(self.daemon.hints_dir, self.root / "hints" / "ja")

    def test_a_flat_layout_still_works(self):
        for lang in ("en", "ja"):
            (self.root / "hints" / lang / "x.yaml").unlink()
            (self.root / "hints" / lang).rmdir()
        (self.root / "hints" / "y.yaml").write_text("id: y\ntitle: Flat\n")
        self.set_language("ja")
        self.assertEqual(self.titles(), ["Flat"])
