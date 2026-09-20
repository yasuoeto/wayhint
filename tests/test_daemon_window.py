"""The daemon's receiving boundary joined to a real ``HintWindow``.

``test_daemon_edit`` drives the daemon with a fake window, and ``test_window_render`` drives a
real window with a hand-built context. Between them sits the join nobody tested: a command
arriving on the socket, going through ``dispatch``, and landing in the widgets. That is the path
every caller takes -- the compositor's keybind, the CLI and any future one all become the same
``{"cmd": ...}`` line before the daemon sees them, so this is where "the overlay showed the right
thing" is decided.

The request is fed through :func:`wayhint.ipc.handle_request`, the same function the socket loop
calls, so the parsing and the reply shape are part of what is checked.

Nothing is presented: ``present`` and ``set_visible`` are shadowed, with ``get_visible`` reading
back what ``set_visible`` was given so the keyboard rule still sees visibility move. No surface
is ever mapped, so nothing appears on the screen of whoever runs the tests.
"""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_desktop_providers import needs_compositor
from wayhint import ipc
from wayhint.daemon import Daemon
from wayhint.models import OutputInfo, ResolvedContext

OUT = OutputInfo("eDP-1", 2560, 1600)
SHEET = (
    "id: a\ntitle: A\nmatch: {wayland: {app_id_regex: [inkscape]}}\n"
    "hints:\n  - {id: one, title: One}\n  - {id: two, title: Two}\n"
)


def noop(*_args, **_kwargs) -> None:
    return None


@needs_compositor
class DaemonToWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from wayhint import daemon

        daemon._load_gui()  # the preload order DECISIONS 0009 requires
        if not daemon.Gtk.init_check():
            raise unittest.SkipTest("GTK could not open a display")
        cls.gui = daemon

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "hints").mkdir()
        (self.root / "hints" / "a.yaml").write_text(SHEET)

        self.daemon = Daemon(self.root, self.root / "unused.sock")
        self.daemon.config = replace(self.daemon.config, workspace_scope="all")
        self.daemon.store.load_all()
        self.assertEqual([s.id for s in self.daemon.store.sheets], ["a"], self.daemon.store.issues)

        self.window = self.gui.HintWindow(None, noop, noop, noop, noop, noop)
        self.addCleanup(self.window.destroy)
        self.visible = False
        self.window.present = noop
        self.window.set_visible = self._set_visible
        self.window.get_visible = lambda: self.visible
        self.daemon.window = self.window

        # The desktop is whatever the person happens to be running, so the context is fixed here;
        # what the adapters answer is the subject of ``test_desktop_providers``.
        self.daemon.resolver.resolve = lambda _sheets, _config: ResolvedContext(
            active_sheet="a", desktop_app="inkscape", output=OUT
        )
        self.daemon._start_workspace_watch = noop
        self.daemon._stop_workspace_watch = noop

    def _set_visible(self, value: bool) -> None:
        self.visible = bool(value)

    def send(self, cmd: str) -> dict:
        return ipc.handle_request(f'{{"cmd":"{cmd}"}}\n'.encode(), self.daemon.dispatch)

    def rows(self) -> list[str]:
        out, index = [], 0
        while (row := self.window._list.get_row_at_index(index)) is not None:
            out.append(row.hint.id)
            index += 1
        return out

    def keyboard(self):
        return self.gui.LayerShell.get_keyboard_mode(self.window)

    def test_show_over_the_socket_fills_the_real_widgets(self) -> None:
        self.assertEqual(
            self.send("show"), {"ok": True, "visible": True, "sheet": "a", "error": None}
        )
        self.assertEqual(self.rows(), ["one", "two"])
        self.assertEqual(self.window._header.get_label(), "A")
        self.assertIn("inkscape", self.window._context_label.get_label())
        self.assertTrue(self.visible)

    def test_toggle_shows_then_hides_the_same_window(self) -> None:
        self.send("toggle")
        self.assertEqual(self.rows(), ["one", "two"])
        self.assertEqual(self.send("toggle"), {"ok": True, "visible": False})
        self.assertFalse(self.visible)

    def test_edit_mode_takes_the_keyboard_and_hide_gives_it_back(self) -> None:
        """The grab the user can be locked out by, driven the way the hotkey drives it."""
        shell = self.gui.LayerShell
        self.send("show")
        self.assertEqual(self.keyboard(), shell.KeyboardMode.NONE)  # normal never grabs

        self.assertEqual(self.send("edit-mode")["mode"], "edit")
        self.assertEqual(self.window.mode, "edit")
        self.assertEqual(self.keyboard(), shell.KeyboardMode.EXCLUSIVE)

        self.send("hide")
        self.assertEqual(self.keyboard(), shell.KeyboardMode.NONE)  # 0014 D4: hiding drops it

    def test_a_request_the_daemon_cannot_serve_is_a_reply_not_a_crash(self) -> None:
        self.assertFalse(self.send("wayhint-no-such-command")["ok"])
        self.assertFalse(ipc.handle_request(b"not json\n", self.daemon.dispatch)["ok"])
        self.send("show")  # the window is still usable afterwards
        self.assertEqual(self.rows(), ["one", "two"])


if __name__ == "__main__":
    unittest.main()
