import unittest

from wayhint.config import ConfigError, parse_global_config
from wayhint.context.workspace import (
    STATE_ACTIVE,
    WorkspaceWatcher,
    active_key,
    should_show_on_toggle,
    workspace_key,
)


class FakeHandle:
    """Stands in for a pywayland proxy: only a dispatcher table and destroy() are used."""

    def __init__(self) -> None:
        self.dispatcher: dict = {}
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True

    def emit(self, event, *args) -> None:
        self.dispatcher[event](self, *args)


class KeyTest(unittest.TestCase):
    def test_workspace_key_prefers_id_then_name(self) -> None:
        self.assertEqual(workspace_key("ws-1", "one", 7), "ws-1")
        self.assertEqual(workspace_key(None, "one", 7), "one")
        self.assertEqual(workspace_key(None, None, 7), "handle:7")

    def test_active_key(self) -> None:
        self.assertEqual(active_key({"a": 0, "b": STATE_ACTIVE}), "b")
        self.assertIsNone(active_key({"a": 0}))
        self.assertIsNone(active_key({}))
        self.assertEqual(active_key({"a": STATE_ACTIVE | 4}), "a")


class ToggleRuleTest(unittest.TestCase):
    def test_hidden_always_shows(self) -> None:
        self.assertTrue(should_show_on_toggle(False, None, "one"))
        self.assertTrue(should_show_on_toggle(False, "one", "one"))

    def test_visible_on_the_same_workspace_hides(self) -> None:
        self.assertFalse(should_show_on_toggle(True, "one", "one"))

    def test_visible_on_another_workspace_shows_here(self) -> None:
        # The hotkey can beat the workspace-change event; comparing workspaces settles it.
        self.assertTrue(should_show_on_toggle(True, "one", "two"))

    def test_unknown_workspace_keeps_plain_toggle(self) -> None:
        self.assertFalse(should_show_on_toggle(True, None, "one"))
        self.assertFalse(should_show_on_toggle(True, "one", None))


class WatcherBookkeepingTest(unittest.TestCase):
    """Drives the protocol callbacks directly; no compositor and no connection involved."""

    def setUp(self) -> None:
        self.changes: list[str | None] = []
        self.watcher = WorkspaceWatcher(self.changes.append)

    def add(self, name, state):
        handle = FakeHandle()
        self.watcher._on_workspace(None, handle)
        handle.emit("name", name)
        handle.emit("state", state)
        return handle

    def test_active_follows_state_events(self) -> None:
        self.add("one", STATE_ACTIVE)
        self.add("two", 0)
        self.watcher._on_done(None)
        self.assertEqual(self.watcher.active(), "one")
        self.assertEqual(self.changes, ["one"])

    def test_change_reported_once_per_done(self) -> None:
        one = self.add("one", STATE_ACTIVE)
        two = self.add("two", 0)
        self.watcher._on_done(None)
        one.emit("state", 0)
        two.emit("state", STATE_ACTIVE)
        self.watcher._on_done(None)
        self.watcher._on_done(None)  # nothing changed in this batch
        self.assertEqual(self.watcher.active(), "two")
        self.assertEqual(self.changes, ["one", "two"])

    def test_name_after_state_keeps_the_state(self) -> None:
        handle = FakeHandle()
        self.watcher._on_workspace(None, handle)
        handle.emit("state", STATE_ACTIVE)
        handle.emit("name", "late")
        self.watcher._on_done(None)
        self.assertEqual(self.watcher.active(), "late")

    def test_removed_workspace_drops_out(self) -> None:
        handle = self.add("one", STATE_ACTIVE)
        self.watcher._on_done(None)
        handle.emit("removed")
        self.watcher._on_done(None)
        self.assertIsNone(self.watcher.active())
        self.assertEqual(self.changes, ["one", None])

    def test_stop_destroys_handles_without_a_display(self) -> None:
        handle = self.add("one", STATE_ACTIVE)
        self.watcher.stop()
        self.assertTrue(handle.destroyed)
        self.assertIsNone(self.watcher.active())

    def test_dispatch_and_roundtrip_without_a_connection(self) -> None:
        self.assertFalse(self.watcher.dispatch())
        self.assertFalse(self.watcher.roundtrip())

    def test_dispatch_reads_the_socket_before_dispatching(self) -> None:
        # dispatch(block=False) alone never empties the socket, so the descriptor stays readable
        # and the caller's watch spins. read() is what drains it.
        calls = []

        class FakeDisplay:
            def flush(self):
                calls.append("flush")

            def read(self):
                calls.append("read")

            def dispatch(self, block=False):
                calls.append(f"dispatch(block={block})")

        self.watcher._display = FakeDisplay()
        self.assertTrue(self.watcher.dispatch())
        self.assertEqual(calls.index("read"), 1)
        self.assertLess(calls.index("read"), calls.index("dispatch(block=False)"))

    def test_dispatch_reports_a_broken_connection(self) -> None:
        class Dead:
            def flush(self):
                raise RuntimeError("connection closed")

        self.watcher._display = Dead()
        self.assertFalse(self.watcher.dispatch())


class ConfigScopeTest(unittest.TestCase):
    def test_default_and_values(self) -> None:
        self.assertEqual(parse_global_config({}).workspace_scope, "current")
        cfg = parse_global_config({"context": {"workspace": "all"}})
        self.assertEqual(cfg.workspace_scope, "all")
        with self.assertRaises(ConfigError):
            parse_global_config({"context": {"workspace": "every"}})


if __name__ == "__main__":
    unittest.main()
