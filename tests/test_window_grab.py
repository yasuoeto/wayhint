"""The overlay's keyboard grab, against real GTK and real gtk4-layer-shell.

``keyboard_grab(mode, visible)`` is pure and tested headless; what was never tested is that the
widget side actually applies it. That side is the one with teeth: a grab left behind means the
user cannot type into the application underneath, and the only way to notice has been the manual
checklist (T6, T13, T24). ``AGENTS.md`` says ``_sync_keyboard_mode()`` is the single place allowed
to set ``keyboard_mode``, so this pins the rule to the layer surface itself.

No surface is ever mapped: the window is built but never presented, and ``get_visible`` is
shadowed to stand in for a mapped surface. Nothing appears on screen while the tests run.
"""

import unittest

from tests.test_desktop_providers import needs_compositor
from wayhint.ui.editmode import MODES, keyboard_grab


def noop(*_args, **_kwargs) -> None:
    return None


@needs_compositor
class KeyboardGrabTest(unittest.TestCase):
    """The layer surface's keyboard mode follows ``keyboard_grab`` and nothing else."""

    @classmethod
    def setUpClass(cls) -> None:
        from wayhint import daemon

        daemon._load_gui()  # the preload order DECISIONS 0009 requires
        if not daemon.Gtk.init_check():
            raise unittest.SkipTest("GTK could not open a display")
        cls.daemon = daemon

    def window(self):
        win = self.daemon.HintWindow(None, noop, noop, noop, noop, noop)
        self.addCleanup(win.destroy)
        return win

    def grabbed(self, win) -> bool:
        shell = self.daemon.LayerShell
        mode = shell.get_keyboard_mode(win)
        self.assertIn(mode, (shell.KeyboardMode.NONE, shell.KeyboardMode.EXCLUSIVE))
        return mode == shell.KeyboardMode.EXCLUSIVE

    def test_a_fresh_window_holds_no_keyboard(self) -> None:
        """Built but not shown: the application underneath must keep its input."""
        win = self.window()
        self.assertFalse(win.get_visible())
        self.assertFalse(self.grabbed(win))

    def test_the_surface_agrees_with_the_pure_rule_in_every_state(self) -> None:
        """The widget side and ``keyboard_grab`` cannot drift apart."""
        for visible in (False, True):
            for mode in MODES:
                with self.subTest(mode=mode, visible=visible):
                    win = self.window()
                    win.get_visible = lambda visible=visible: visible
                    win.set_mode(mode, refocus=False)
                    self.assertIs(self.grabbed(win), keyboard_grab(mode, visible))

    def test_hiding_drops_the_grab_and_keeps_the_mode(self) -> None:
        """Leaving the workspace or closing must not leave the keyboard captured (0014 D4)."""
        win = self.window()
        win.get_visible = lambda: True
        win.set_mode("search", refocus=False)
        self.assertTrue(self.grabbed(win))

        del win.get_visible  # hide_overlay calls set_visible(False); the real answer applies again
        win.hide_overlay()
        self.assertFalse(self.grabbed(win))
        self.assertEqual(win.mode, "search")  # the draft and the mode survive the trip

    def test_an_unknown_mode_is_refused_before_anything_is_touched(self) -> None:
        win = self.window()
        with self.assertRaises(ValueError):
            win.set_mode("wayhint-no-such-mode")
        self.assertEqual(win.mode, "normal")
        self.assertFalse(self.grabbed(win))


if __name__ == "__main__":
    unittest.main()
