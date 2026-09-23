"""The manual checklist T41–T46a (DESIGN 実機チェックリスト, DECISIONS 0033), automated.

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
from wayhint.daemon import Daemon
from wayhint.models import ResolvedContext
from wayhint.ui import editmode as em

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

    def daemon(self, window):
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
        first = self.daemon(first_window)
        first.show()
        self.leave_search_with(first, first_window, "pane")
        del first  # nothing but the file survives

        window = self.fake()
        second = self.daemon(window)
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
            daemon = self.daemon(window)
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
        daemon = self.daemon(window)
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


if __name__ == "__main__":
    unittest.main()
