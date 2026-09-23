"""The manual checklist T41–T44 and T46a (DESIGN 実機チェックリスト, DECISIONS 0033), automated.

Two layers, as everywhere else (DECISIONS 0030). T41, T42 and T44 are about where the filter is
kept, which the daemon decides: they use the window fake of ``test_daemon_edit`` with real files.
T43 and T46a are about what the widgets do with keys and with a reload, so they need a real
``HintWindow`` in this process -- built the way ``test_daemon_window`` builds it, never mapped.

"Restarting the daemon" is two daemons built one after the other on the same state directory;
the process boundary adds nothing the file does not already carry. ``XDG_STATE_HOME`` and
``XDG_CONFIG_HOME`` point into the test's own directory, so the person's
``~/.local/state/wayhint/`` is never read or written, whatever the code under test does.
"""

import logging
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from ruamel.yaml import YAML

from tests.test_daemon_edit import Window, Workspace
from tests.test_desktop_providers import needs_compositor
from wayhint import ipc
from wayhint.daemon import Daemon
from wayhint.i18n import translator
from wayhint.models import ResolvedContext
from wayhint.ui import editmode as em
from wayhint.yaml_store import load_sheet

SHEET_B = (
    "id: b\ntitle: B\nhints:\n"
    "  - {id: split, title: split pane, key: 'C-b %'}\n"
    "  - {id: close, title: close pane, key: 'C-b x'}\n"
    "  - {id: detach, title: detach, key: 'C-b d'}\n"
)


class Resolver:
    def __init__(self, sheet="b"):
        self.sheet = sheet

    def resolve(self, sheets, config):
        return ResolvedContext(active_sheet=self.sheet)


class Isolated(unittest.TestCase):
    """A config directory and a state directory of the test's own, and the XDG variables on them."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "config" / "wayhint"
        (self.root / "hints").mkdir(parents=True)
        (self.root / "hints" / "b.yaml").write_text(SHEET_B)
        self.state = Path(temp.name) / "state" / "wayhint" / "state.yaml"
        env = mock.patch.dict(
            os.environ,
            {"XDG_STATE_HOME": str(self.state.parent.parent), "XDG_CONFIG_HOME": temp.name},
        )
        env.start()
        self.addCleanup(env.stop)

    def make_daemon(self, window):
        daemon = Daemon(self.root, self.root / "unused.sock", self.state)
        daemon.config = replace(daemon.config, workspace_scope="all")
        daemon.store.load_all()
        daemon.resolver = Resolver()
        daemon.window = window
        return daemon


class FakeWindowCase(Isolated):
    def fake(self):
        window = Window()
        window.mode = "normal"
        window.visible = False
        return window

    def leave_search_with(self, daemon, window, text):
        daemon.on_edit_action(em.BEGIN_SEARCH, None)
        window.text = text
        daemon.on_edit_action(em.END_SEARCH, None)


class T41RestartTest(FakeWindowCase):
    """T41: after a restart, the same sheet opens with the same filter."""

    def test_a_second_daemon_on_the_same_state_restores_the_filter(self):
        first_window = self.fake()
        first = self.make_daemon(first_window)
        first.show()
        self.leave_search_with(first, first_window, "pane")
        del first  # nothing but the file survives

        window = self.fake()
        second = self.make_daemon(window)
        second.show()
        self.assertEqual(second._current_view().filter_query, "pane")
        self.assertEqual(window.filter, "pane")
        second.on_edit_action(em.BEGIN_SEARCH, None)
        self.assertEqual(window.text, "pane")  # and it is what the box starts with


class T42BrokenStateTest(FakeWindowCase):
    """T42: a broken state.yaml starts, warns once, filters nothing, and is written over."""

    def test_starts_with_one_warning_and_the_next_search_writes_it_over(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("foo: [")
        window = self.fake()
        with self.assertLogs(level=logging.WARNING) as logs:
            daemon = self.make_daemon(window)
            daemon.show()
        about_state = [r for r in logs.records if "state.yaml" in r.getMessage()]
        self.assertEqual(len(about_state), 1, logs.output)  # not once per read, not per show
        self.assertEqual(len(logs.records), 1, logs.output)
        self.assertEqual(daemon.filters, {})
        self.assertEqual((daemon._current_view().filter_query, window.filter), ("", ""))

        self.leave_search_with(daemon, window, "pane")
        written = YAML(typ="safe").load(self.state.read_text())
        self.assertEqual(written, {"version": 1, "filters": {"b": "pane"}})


class T44WorkspaceTest(FakeWindowCase):
    """T44: another workspace opening the same sheet gets the same filter."""

    def test_two_workspaces_share_the_filter_of_one_sheet(self):
        window = self.fake()
        daemon = self.make_daemon(window)
        workspace = Workspace()
        daemon._watcher = workspace
        daemon.show()  # on workspace A
        self.leave_search_with(daemon, window, "#- pane")

        workspace.key = "B"
        workspace.known = lambda: {"A", "B"}
        daemon.show()
        self.assertEqual(daemon._open["B"].filter_query, "#- pane")
        self.assertEqual(window.filter, "#- pane")
        self.assertEqual(daemon._open["A"].filter_query, "#- pane")


def noop(*_args, **_kwargs):
    return None


@needs_compositor
class RealWindowCase(Isolated):
    """A real ``HintWindow`` wired to the daemon the way ``Daemon.start`` wires it.

    Never mapped: ``present`` and ``set_visible`` are shadowed as in ``test_daemon_window``, so
    nothing appears on the screen of whoever runs the tests. Keys go through the window's own
    key handler -- the one its capture-phase controller calls -- rather than a compositor.
    """

    @classmethod
    def setUpClass(cls):
        from wayhint import daemon

        daemon._load_gui()  # the preload order DECISIONS 0009 requires
        if not daemon.Gtk.init_check():
            raise unittest.SkipTest("GTK could not open a display")
        cls.gui = daemon

    def setUp(self):
        super().setUp()
        (self.root / "config.yaml").write_text(
            "appearance: {language: en}\ncontext: {workspace: all}\n"
        )
        self.visible = False
        self.daemon = self.make_daemon(None)
        self.daemon.reload_all()
        d = self.daemon
        self.window = self.gui.HintWindow(
            None, d.edit, d.hide, d.on_edit_action, noop, noop, tr=translator("en")
        )
        self.addCleanup(self.window.destroy)
        self.window.present = noop
        self.window.set_visible = self._set_visible
        self.window.get_visible = lambda: self.visible
        d.window = self.window
        d._start_workspace_watch = noop
        d._stop_workspace_watch = noop

    def _set_visible(self, value):
        self.visible = bool(value)

    def send(self, cmd):
        return ipc.handle_request(f'{{"cmd":"{cmd}"}}\n'.encode(), self.daemon.dispatch)

    def key(self, name):
        from gi.repository import Gdk

        return self.window._on_key(None, Gdk.keyval_from_name(name), 0, Gdk.ModifierType(0))

    def rows(self):
        out, index = [], 0
        while (row := self.window._list.get_row_at_index(index)) is not None:
            out.append(row.hint.id)
            index += 1
        return out

    def selected(self):
        row = self.window._list.get_selected_row()
        return row.hint.id if row is not None else None

    def sheet_ids(self):
        sheet, issues = load_sheet(self.root / "hints" / "b.yaml")
        self.assertEqual(issues, [])
        return [h.id for h in sheet.hints], [h.id for h in sheet.hints if h.favorite]

    def filter_by(self, text):
        """Narrow the list the way a person does: search-mode, type, search-mode again."""
        self.assertEqual(self.send("search-mode")["mode"], "search")
        self.window._search.set_text(text)
        self.assertEqual(self.send("search-mode")["mode"], "normal")
        self.assertEqual(self.window._query, text)


class T43EditWhileFilteredTest(RealWindowCase):
    """T43: in edit mode on a filtered list, J / K do nothing and a / Enter / d d / f still work."""

    def setUp(self):
        super().setUp()
        self.send("show")
        self.filter_by("pane")
        self.assertEqual(self.rows(), ["split", "close"])
        # On a mapped window GTK takes the focus off the search box when the box is hidden
        # (checked on the headless compositor: ``f`` then marks a hint). This window is never
        # mapped, so GTK leaves the focus on the hidden box; clear it the way a mapped one does.
        if not self.window._search.get_visible():
            self.window.set_focus(None)
        self.assertEqual(self.send("edit-mode")["mode"], "edit")
        # A key reaching a text field is not an edit-mode key at all, which would make "J does
        # nothing" pass for the wrong reason: the search box must not be holding the focus.
        self.assertFalse(self.window._editable_focused())

    def test_j_changes_neither_the_order_nor_the_selection(self):
        before = self.sheet_ids()
        self.assertTrue(self.key("J"))  # taken, like every edit-mode key ...
        self.assertEqual((self.rows(), self.selected()), (["split", "close"], "split"))
        self.assertEqual(self.sheet_ids(), before)  # ... and nothing is written
        self.assertFalse(self.window._error.get_visible())  # not even a message

    def test_k_changes_neither_the_order_nor_the_selection(self):
        # Checked on its own: after a J that did swap, a K on the same pair would swap it back
        # and the file would read as untouched.
        self.key("Down")
        before = self.sheet_ids()
        self.assertTrue(self.key("K"))
        self.assertEqual((self.rows(), self.selected()), (["split", "close"], "close"))
        self.assertEqual(self.sheet_ids(), before)
        self.assertFalse(self.window._error.get_visible())

    def test_f_marks_the_selected_hint(self):
        self.key("Down")
        self.assertTrue(self.key("f"))
        self.assertEqual(self.sheet_ids()[1], ["close"])

    def test_a_opens_quick_add(self):
        self.assertTrue(self.key("a"))
        self.assertIsNotNone(self.window._form)
        self.assertIsNone(self.window._form.hint_id)
        self.assertIsNotNone(self.daemon._current_view().form)

    def test_enter_opens_the_selected_hint(self):
        self.key("Down")
        self.assertTrue(self.key("Return"))
        self.assertEqual(self.window._form.hint_id, "close")

    def test_d_d_deletes_the_selected_hint(self):
        self.key("Down")
        self.key("d")
        self.assertEqual(self.sheet_ids()[0], ["split", "close", "detach"])  # one d asks
        self.key("d")
        self.assertEqual(self.sheet_ids()[0], ["split", "detach"])


class RefusalMessageTest(RealWindowCase):
    """A refusal answers one press: it goes when its mode ends, a YAML error stays."""

    def setUp(self):
        super().setUp()
        self.send("show")
        self.assertEqual(self.send("edit-mode")["mode"], "edit")

    def test_leaving_edit_clears_the_refusal_to_search(self):
        self.assertFalse(self.send("search-mode")["ok"])
        self.assertTrue(self.window._error.get_visible())
        self.assertIn("finish editing", self.window._error.get_label())
        self.assertEqual(self.send("edit-mode")["mode"], "normal")
        self.assertFalse(self.window._error.get_visible())

    def test_leaving_edit_puts_a_yaml_error_back(self):
        (self.root / "hints" / "broken.yaml").write_text("id: [\n")
        self.daemon.reload_all()
        self.window.show_issues(self.daemon.issues)
        self.assertFalse(self.send("search-mode")["ok"])
        self.assertEqual(self.send("edit-mode")["mode"], "normal")
        self.assertTrue(self.window._error.get_visible())
        self.assertIn("YAML error", self.window._error.get_label())


class T46aReloadWhileSearchingTest(RealWindowCase):
    """T46a: a sheet rewritten from outside during a search leaves the search box alone.

    The file is changed and then handed to the entry the file monitor calls after its debounce
    (``_debounced_reload``), so no main loop has to be run and waited on.
    """

    NEW_SHEET = (
        "id: b\ntitle: B\nhints:\n"
        "  - {id: split, title: split pane, key: 'C-b %'}\n"
        "  - {id: detach, title: detach, key: 'C-b d'}\n"
        "  - {id: zoom, title: zoom pane, key: 'C-b z'}\n"
    )

    def focus_in_box(self):
        focus = self.window.get_focus()
        box = self.window._search
        return focus is not None and (focus is box or focus.is_ancestor(box))

    def test_the_box_keeps_text_caret_and_focus_and_the_filter_applies_to_the_new_file(self):
        self.send("show")
        self.assertEqual(self.send("search-mode")["mode"], "search")
        box = self.window._search
        box.set_text("pane")
        box.set_position(2)
        self.assertTrue(self.focus_in_box())
        self.window._render_from_top()  # what the box's delayed search-changed does
        self.assertEqual(self.rows(), ["split", "close"])

        path = self.root / "hints" / "b.yaml"
        path.write_text(self.NEW_SHEET)  # close is gone, zoom is new
        self.daemon._debounced_reload(path)

        self.assertEqual(self.window.mode, "search")
        self.assertEqual(box.get_text(), "pane")
        self.assertEqual(box.get_position(), 2)
        self.assertTrue(self.focus_in_box())
        self.assertEqual(self.rows(), ["split", "zoom"])  # the box's filter, on the new file
        self.assertEqual(self.selected(), "split")


class ModeHotkeyTwiceTest(RealWindowCase):
    """Entered from a hidden overlay, the second press hides and lets go of the keyboard.

    0014 D4 amend (2026-09-23). The daemon tests pin the states; this one reads the grab the
    real layer surface was left with, which is what decides whether the application gets its
    keys back.
    """

    def test_edit_and_search_from_hidden_end_with_no_grab(self):
        none = self.gui.LayerShell.KeyboardMode.NONE
        for cmd in ("edit-mode", "search-mode"):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.visible)
                self.send(cmd)
                self.assertNotEqual(self.gui.LayerShell.get_keyboard_mode(self.window), none)
                reply = self.send(cmd)
                self.assertEqual((reply["visible"], reply["mode"]), (False, "normal"))
                self.assertFalse(self.visible)
                self.assertEqual(self.gui.LayerShell.get_keyboard_mode(self.window), none)


if __name__ == "__main__":
    unittest.main()
