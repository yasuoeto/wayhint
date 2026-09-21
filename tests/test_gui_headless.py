"""The overlay on a real compositor: where it lands, and what it says.

Everything else stops at the widget. ``test_window_render`` checks that ``HintWindow`` asked
``geometry.placement`` and applied the answer to the layer surface, but a layer surface is a
*request*: what the compositor then does with the anchors and the margins is not visible from
inside the process, and neither is whether anything was drawn at all. Those two are what this
covers, and they are the first and the last of the core principles -- the overlay appears where
it is meant to, and it shows the right hints.

Two ways of reading the result, both chosen so they survive a different machine:

* **Where**: the bounding box of what changed between a frame with the overlay and one without.
  Independent of fonts, theme and anything else on screen.
* **What**: the accessible names GTK publishes. The text the user reads, without comparing
  pixels of it.

A committed baseline image would be a third way and is deliberately not used: the capture is
reproducible on one machine (identical bytes across frames, hide/show cycles and fresh sessions)
but fonts and theme make it worthless on the next one. ``headless.difference_box`` is available
for a local one-off comparison when that is what a change needs.

Not run by ``./scripts/check``; see ``tests/headless.py``.
"""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from tests.headless import (
    HeadlessSession,
    difference_box,
    needs_headless,
    needs_key_injection,
)

REPO = Path(__file__).resolve().parent.parent

WIDTH, HEIGHT = 1280, 720
SHEET = """\
id: demo
title: Demo
match:
  wayland:
    app_id_regex: ['wayhint-probe']
hints:
  - {id: copy, title: Copy, key: 'Ctrl+C'}
  - {id: paste, title: Paste, key: 'Ctrl+V'}
  - {id: quit, title: Quit, key: 'Ctrl+Q'}
"""


def scratch(case: unittest.TestCase, prefix: str) -> Path:
    """A directory that goes away with the test, however it ends."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    case.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


def config_root(
    case: unittest.TestCase, overlay: str, sheets: dict[str, str] | None = None
) -> Path:
    """A throwaway config directory with sheets that match the windows a test opens."""
    root = scratch(case, "wayhint-cfg-")
    hints = root / "hints" / "en"
    hints.mkdir(parents=True)
    for name, text in (sheets or {"demo": SHEET}).items():
        (hints / f"{name}.yaml").write_text(text)
    (root / "config.yaml").write_text(
        f"overlay: {overlay}\nappearance: {{language: en}}\ncontext: {{workspace: all}}\n"
    )
    return root


@needs_headless
class PlacementTest(unittest.TestCase):
    """Where the compositor actually put the surface (T3 / T5 of the manual checklist)."""

    def box(self, overlay: str) -> tuple[int, int, int, int]:
        root = config_root(self, overlay)
        work = scratch(self, "wayhint-shot-")
        with HeadlessSession(root, width=WIDTH, height=HEIGHT) as session:
            box = session.overlay_box(work)
            self.assertIsNotNone(box, f"the overlay never appeared\n{session.log_tail()}")
            return box

    def test_top_right_lands_at_the_top_right(self) -> None:
        width, _height, x, y = self.box(
            "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}"
        )
        self.assertEqual(width, 400)
        self.assertEqual(x, WIDTH - 400 - 20)
        self.assertEqual(y, 20)

    def test_bottom_left_lands_at_the_bottom_left(self) -> None:
        """The opposite corner, so a sign error in one margin cannot pass both tests."""
        width, height, x, y = self.box(
            "{anchor: bottom-left, width: 500px, margin: {bottom: 30, left: 10}}"
        )
        self.assertEqual(width, 500)
        self.assertEqual(x, 10)
        self.assertEqual(y + height, HEIGHT - 30)

    def test_a_percentage_width_is_of_the_output(self) -> None:
        """``width: 50%`` means half of *this* output, which only the compositor knows.

        Well above the width the buttons need: the configured width is a minimum, so a small
        percentage would be overruled by the widgets and the test would measure nothing.
        """
        width, _height, _x, _y = self.box(
            "{anchor: top-right, width: 50%, margin: {top: 0, right: 0}}"
        )
        self.assertEqual(width, WIDTH // 2)


@needs_headless
class ContentTest(unittest.TestCase):
    """What the overlay says once it is up, read back through AT-SPI."""

    def test_the_hints_for_the_focused_window_are_the_ones_on_screen(self) -> None:
        root = config_root(self, "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}")
        with HeadlessSession(root, width=WIDTH, height=HEIGHT) as session:
            session.toplevel("wayhint-probe")
            session.wayhint("show")
            labels = session.a11y_names("label")

        self.assertIn("Demo", labels)  # the sheet the app_id chose
        for key, title in (("Ctrl+C", "Copy"), ("Ctrl+V", "Paste"), ("Ctrl+Q", "Quit")):
            self.assertIn(key, labels)
            self.assertIn(title, labels)
        self.assertTrue(
            any("wayhint-probe" in text for text in labels), labels
        )  # the context line names the window the hints are for


@needs_key_injection
class CallerTest(unittest.TestCase):
    """Every caller ends in the same request, so the overlay cannot depend on who asked.

    A key press is the one leg no other test reaches: the compositor's keybind starts the CLI,
    the CLI writes one line to the socket, and from there it is the path
    ``test_daemon_window`` already covers. Driving it with a virtual keyboard (no uinput, no
    privileges) is what makes the hotkey a tested path rather than a checklist item (T1 / T2).
    """

    OVERLAY = "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}"

    def test_the_hotkey_and_the_cli_reach_the_same_overlay(self) -> None:
        root = config_root(self, self.OVERLAY)
        work = scratch(self, "wayhint-shot-")
        with HeadlessSession(
            root, width=WIDTH, height=HEIGHT, keybind=("W-slash", "toggle")
        ) as session:
            session.toplevel("wayhint-probe")

            session.wayhint("hide")
            # One full cycle before the reference frame is taken. The probe window redraws its
            # cursor when the focus moves, and that redraw has to be behind us: otherwise it
            # lands in the difference and the measured box is the union of two things.
            session.press("win", "slash")
            session.press("win", "slash")
            off = session.grab(work / "off.png", settle=1.5)

            session.press("win", "slash")  # the compositor's keybind, not the CLI
            by_key = difference_box(session.grab(work / "by-key.png", settle=1.5), off)
            # Where, not merely "something changed": a key the compositor has no binding for is
            # delivered to the window underneath, and a character echoed by the terminal is a
            # difference too. Only the overlay is 400 wide at the right-hand margin.
            self.assertIsNotNone(by_key, f"the hotkey opened nothing\n{session.log_tail()}")
            width, _height, x, y = by_key
            self.assertEqual((width, x, y), (400, WIDTH - 400 - 20, 20), session.log_tail())
            self.assertIn("Demo", session.a11y_names("label"))

            session.press("win", "slash")  # and it toggles back off
            self.assertIsNone(difference_box(session.grab(work / "off2.png", settle=1.5), off))

            session.wayhint("toggle")
            by_cli = difference_box(session.grab(work / "by-cli.png", settle=1.5), off)

        self.assertEqual(by_key, by_cli)


PROCESS_SHEETS = {
    "claude-code": """\
id: claude-code
title: Claude Code
match:
  process:
    argv_regex: ['^claude$']
hints:
  - {id: compact, title: Compact, key: 'Ctrl+C'}
""",
    "vi": """\
id: vi
title: Vi
match:
  process:
    argv_regex: ['^vi$']
hints:
  - {id: quit, title: Quit, key: ':q'}
""",
}


@needs_key_injection
class FocusFollowTest(unittest.TestCase):
    """The sheet follows the focused *window*, and the overlay does not close on the way.

    Two things are pinned here and both are product behaviour that nothing else covers end to
    end. The first is the pid-suffix convention (README「Terminal の複数窓」): two terminals of
    the same program are told apart because each window names the process drawing it in its
    app_id, and ``/proc`` is then read for what runs inside. The second is that pressing the
    hotkey while looking at a different window *replaces* what is on screen rather than
    hiding it and opening it again -- a hidden frame in between is what a user sees as a flash.

    The demo used to show this; it does not any more (DECISIONS 0032), so it lives here. If
    this fails, the regression is in the product, not in the test: do not relax it to suit a
    recording.
    """

    OVERLAY = "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}"
    BIN = REPO / "demo" / "bin"

    def terminal(self, session: HeadlessSession, stub: str, sheet: str) -> None:
        """A foot window named after its own pid, running one of the demo's stubs in it."""
        session.spawn([str(self.BIN / "foot-wayhint"), str(self.BIN / stub)])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if f"active_sheet={sheet}" in session.wayhint("context"):
                return
            time.sleep(0.2)
        self.fail(f"{stub} never became the active context\n{session.wayhint('context')}")

    def test_the_sheet_follows_the_focus_without_the_overlay_closing(self) -> None:
        root = config_root(self, self.OVERLAY, PROCESS_SHEETS)
        with HeadlessSession(root, keybind=("W-h", "toggle")) as session:
            self.terminal(session, "claude", "claude-code")
            session.press("win", "h")
            self.assertIn("Claude Code", session.a11y_names("label"), session.log_tail())

            self.terminal(session, "vi", "vi")  # the new window takes the focus
            self.assertTrue(session.a11y_nodes(), "the overlay closed when the focus moved")

            session.press("win", "h")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                labels = session.a11y_names("label")
                if "Vi" in labels:
                    break
                time.sleep(0.2)
            self.assertIn("Vi", labels, session.log_tail())
            self.assertNotIn("Claude Code", labels)
            # Replaced, not closed and re-opened: the daemon says which of the two it did.
            self.assertIn("replacing claude-code with vi", session.log_tail(60))


if __name__ == "__main__":
    unittest.main()
