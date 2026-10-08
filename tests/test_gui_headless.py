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
    end. The first is the pid-suffix convention (README「端末の複数ウィンドウ」): two terminals of
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

    def labels_once_shown(self, session: HeadlessSession, title: str) -> list[str]:
        """The overlay's labels once ``title`` is among them, or as they were after 15 s.

        GTK publishes the tree a moment after the overlay maps (about 0.5 s on GTK 4.24), so a
        read straight after the hotkey can see nothing at all.
        """
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            labels = session.a11y_names("label")
            if title in labels:
                break
            time.sleep(0.2)
        return labels

    def test_the_sheet_follows_the_focus_without_the_overlay_closing(self) -> None:
        root = config_root(self, self.OVERLAY, PROCESS_SHEETS)
        with HeadlessSession(root, keybind=("W-h", "toggle")) as session:
            self.terminal(session, "claude", "claude-code")
            session.press("win", "h")
            self.assertIn(
                "Claude Code", self.labels_once_shown(session, "Claude Code"), session.log_tail()
            )

            self.terminal(session, "vi", "vi")  # the new window takes the focus
            self.assertTrue(session.a11y_nodes(), "the overlay closed when the focus moved")

            session.press("win", "h")
            labels = self.labels_once_shown(session, "Vi")
            self.assertIn("Vi", labels, session.log_tail())
            self.assertNotIn("Claude Code", labels)
            # Replaced, not closed and re-opened: the daemon says which of the two it did.
            self.assertIn("replacing claude-code with vi", session.log_tail(60))


ROWS_SHEET = """\
id: demo
title: Demo
match:
  wayland:
    app_id_regex: ['wayhint-probe']
hints:
  - {id: copy, title: Copy, key: 'Ctrl+C', remark: 'row one'}
  - {id: paste, title: Paste, key: 'Ctrl+V', remark: 'row two'}
  - {id: quit, title: Quit, key: 'Ctrl+Q', remark: 'row three'}
"""
"""Three hints that say which row they are: the detail line under the list shows the remark of
the selected hint, which is how the selection is read back here."""


@needs_key_injection
class EditModeKeyboardTest(unittest.TestCase):
    """Edit mode is usable with the keyboard alone: ``↓`` moves what the next key acts on.

    The single-key operations (``f``, ``J`` / ``K``, ``Enter``, ``d d``) all act on the selected
    row, and the arrow keys are how that row is chosen (DESIGN 編集モード §2). They used to be
    left to GTK's own list navigation, which never answered: the focus the window grabs for the
    list does not stick on a layer surface holding the keyboard, so the selection stayed on the
    first row and **nothing below it could be reached without a mouse** -- on an overlay that
    exists to be driven from a hotkey. Found while scripting the demo (B-7), fixed 2026-09-23.

    Both halves are checked, because either one alone would pass while the feature is broken:
    the overlay says the selection moved, and the file says the key that followed acted on the
    row it moved to.
    """

    OVERLAY = "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}"

    def favourites(self, root: Path) -> list[str]:
        from ruamel.yaml import YAML

        doc = YAML().load(root / "hints" / "en" / "demo.yaml")
        return [hint["id"] for hint in doc["hints"] if hint.get("favorite")]

    def until(self, session: HeadlessSession, what: str, ready) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if ready():
                return
            time.sleep(0.2)
        self.fail(f"{what}\n{session.log_tail()}")

    def selected_row(self, session: HeadlessSession) -> str:
        """Which row the overlay says is selected, by the remark in the detail line."""
        shown = [node.name for node in session.a11y_nodes() if node.showing]
        return next((name.split("\n")[0] for name in shown if name.startswith("row ")), "")

    def test_the_arrow_keys_choose_the_row_a_single_key_acts_on(self) -> None:
        root = config_root(self, self.OVERLAY, {"demo": ROWS_SHEET})
        with HeadlessSession(root, width=WIDTH, height=HEIGHT) as session:
            session.toplevel("wayhint-probe")
            session.wayhint("show")
            self.assertIn("mode=edit", session.wayhint("edit-mode"), session.log_tail())
            self.until(
                session,
                "the first hint was never selected",
                lambda: self.selected_row(session) == "row one",
            )
            # The first key of a session goes nowhere: the virtual keyboard is new and the
            # compositor is still handing the keyboard to the layer surface (measured). Edit
            # mode ignores "x", so this one is free to be the one that is lost.
            session.press("x")
            session.press("Down")
            self.until(
                session,
                "the selection did not move to the second hint",
                lambda: self.selected_row(session) == "row two",
            )

            session.press("f")  # and the key that follows acts on *that* row
            self.until(
                session,
                "nothing was marked as a favourite",
                lambda: bool(self.favourites(root)),
            )
            found = self.favourites(root)
        self.assertEqual(found, ["paste"], "the key acted on the first row, not the chosen one")


@needs_key_injection
class SearchModeTest(unittest.TestCase):
    """``wayhint search-mode`` in and out, and the filter that outlives the search (0033).

    The hotkey path to the socket is ``CallerTest``'s; this is what the request does once it is
    there. In: the box takes what is typed. Out, by the same request: the keyboard is let go of
    but the list stays narrowed, a chip says so, and state.yaml has it for the next time. The
    clipboard half (``c`` on the list copies, 0039) is left to the unit tests: reading a Wayland
    selection back needs a client holding keyboard focus, which is the thing this test gives
    away.
    """

    OVERLAY = "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}"

    def showing(self, session: HeadlessSession) -> list[str]:
        return [node.name for node in session.a11y_nodes() if node.showing]

    def until(self, session: HeadlessSession, what: str, ready) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if ready():
                return
            time.sleep(0.2)
        self.fail(f"{what}\n{self.showing(session)}\n{session.log_tail()}")

    def test_search_mode_in_and_out_keeps_the_filter(self) -> None:
        root = config_root(self, self.OVERLAY)
        with HeadlessSession(root, width=WIDTH, height=HEIGHT) as session:
            session.toplevel("wayhint-probe")
            # Open first: entered from a hidden overlay, the second search-mode would close it
            # again (0014 D4 amend) and there would be no chip to read. The point here is the
            # filter outliving the search, so the overlay has to stay.
            session.wayhint("show")
            self.until(session, "the overlay never opened", lambda: "Demo" in self.showing(session))
            self.assertIn("mode=search", session.wayhint("search-mode"), session.log_tail())
            self.until(session, "search did not start", lambda: "Done" in self.showing(session))
            # The first key of a session can be lost while the compositor hands the keyboard
            # over (see EditModeKeyboardTest); whichever way it went, BackSpace leaves it empty.
            session.press("x")
            session.press("BackSpace")
            session.type_text("quit")
            self.until(
                session,
                "typing did not narrow the list",
                lambda: "Quit" in self.showing(session) and "Paste" not in self.showing(session),
            )

            self.assertIn("mode=normal", session.wayhint("search-mode"), session.log_tail())
            self.until(
                session,
                "the filter chip never appeared",
                lambda: "filter: quit" in self.showing(session),
            )
            shown = self.showing(session)
            state = session.home / ".local" / "state" / "wayhint" / "state.yaml"
            written = state.read_text() if state.exists() else ""

            # Back in, the filter is in the box; Enter there leaves with it (0039).
            self.assertIn("mode=search", session.wayhint("search-mode"), session.log_tail())
            self.until(session, "search did not start", lambda: "Done" in self.showing(session))
            session.press("Return")
            self.until(
                session,
                "Enter in the search box did not leave search",
                lambda: "Search" in self.showing(session) and "Done" not in self.showing(session),
            )
            self.assertIn("filter: quit", self.showing(session))
        self.assertNotIn("Paste", shown, "leaving search dropped the filter")
        self.assertIn('demo: "quit"', written)


FIXTURE_BIN = REPO / "tests" / "fixtures" / "bin"

TEXTSINK_SHEET = """\
id: textsink
title: TextSink
match:
  wayland:
    app_id_regex: ['^dev\\.wayhint\\.test\\.TextSink$']
hints:
  - {id: type, title: Type here, key: 'a-z'}
"""


@needs_key_injection
class SearchChecklistTest(unittest.TestCase):
    """T45 and T46b of the manual checklist: what only a real keyboard and editor can show.

    T45 is the keyboard coming back: a second ``Super+Shift+H`` must leave search *and* let the
    application underneath have the keys again, which only the compositor can say. T46b is the
    editor path: after "Edit in editor" the overlay is back in normal, and every save the editor
    makes -- in place, then by rename -- re-renders the list still narrowed by the filter.
    What stays manual is the person's own ``rc.xml`` binding and a real gvim.
    """

    OVERLAY = "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}"

    def showing(self, session: HeadlessSession) -> list[str]:
        return [node.name for node in session.a11y_nodes() if node.showing]

    def until(self, session: HeadlessSession, what: str, ready, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ready():
                return
            time.sleep(0.2)
        self.fail(f"{what}\n{self.showing(session)}\n{session.log_tail()}")

    def searching(self, session: HeadlessSession) -> bool:
        shown = self.showing(session)
        return "Done" in shown and "Search" not in shown

    def normal(self, session: HeadlessSession) -> bool:
        shown = self.showing(session)
        return "Search" in shown and "Done" not in shown

    def test_t45_the_hotkey_again_leaves_search_and_gives_the_keys_back(self) -> None:
        root = config_root(self, self.OVERLAY, {"demo": SHEET, "textsink": TEXTSINK_SHEET})
        typed = scratch(self, "wayhint-sink-") / "typed.txt"
        with HeadlessSession(
            root, width=WIDTH, height=HEIGHT, keybind=("W-S-h", "search-mode")
        ) as session:
            # The overlay is already up for another window, the way it is left open while working:
            # the hotkey has to search the hints of the window it was pressed in, not these, and
            # leaving has to hand the keys to that window (found on the real desktop, 2026-09-23).
            session.toplevel("wayhint-probe")
            session.wayhint("show")
            self.until(session, "the overlay never opened", lambda: "Demo" in self.showing(session))
            session.spawn([str(FIXTURE_BIN / "textsink"), str(typed)])
            self.until(
                session,
                "textsink never became the active window",
                lambda: "dev.wayhint.test.TextSink" in session.wayhint("context"),
                timeout=30,
            )
            session.press("win", "shift", "h")
            self.until(
                session, "the hotkey did not start a search", lambda: self.searching(session)
            )
            self.until(
                session,
                "the search was not for the window the hotkey was pressed in",
                lambda: "TextSink" in self.showing(session) and "Demo" not in self.showing(session),
            )
            session.type_text("box")  # into the overlay, not the application
            session.press("win", "shift", "h")
            self.until(
                session, "the hotkey again did not leave search", lambda: self.normal(session)
            )
            session.type_text("hello")
            self.until(
                session,
                "the keys did not come back to the application",
                lambda: typed.exists() and "hello" in typed.read_text(),
            )
            got = typed.read_text()
        self.assertNotIn("box", got, "what was typed into the search box reached the application")

    def test_t46b_every_save_from_the_editor_re_renders_the_filtered_list(self) -> None:
        root = config_root(self, self.OVERLAY)
        (root / "config.yaml").write_text(
            f"overlay: {self.OVERLAY}\nappearance: {{language: en}}\n"
            "context: {workspace: all}\n"
            f"editor: {{command: ['{FIXTURE_BIN / 'fake-editor'}', '{{file}}']}}\n"
        )
        sheet = root / "hints" / "en" / "demo.yaml"
        with HeadlessSession(root, width=WIDTH, height=HEIGHT) as session:
            session.toplevel("wayhint-probe")
            self.assertIn("mode=search", session.wayhint("search-mode"), session.log_tail())
            # Keys typed before the first frame are dropped (all of them on GTK 4.24 with a
            # GPU renderer), so wait for the list before typing.
            self.until(session, "the list never showed", lambda: "Quit" in self.showing(session))
            session.press("x")  # the first key of a session can be lost; BackSpace evens it out
            session.press("BackSpace")
            session.type_text("quit")
            self.until(
                session,
                "typing did not narrow the list",
                lambda: "Quit" in self.showing(session) and "Paste" not in self.showing(session),
            )

            self.assertTrue(session.a11y_press("Edit in editor"), session.log_tail())
            self.until(session, "the editor did not end the search", lambda: self.normal(session))
            self.assertIn("filter: quit", self.showing(session))

            # First save, in place: the new hint matches and shows, the rest stay filtered out.
            self.until(
                session,
                "the in-place save never reached the list",
                lambda: "Quit again" in self.showing(session),
            )
            self.assertNotIn("Paste", self.showing(session))

            # Second save, by rename: one new hint matches, the other does not.
            (sheet.parent / (sheet.name + ".next")).touch()
            self.until(
                session,
                "the save by rename never reached the list",
                lambda: "Quit three" in self.showing(session),
            )
            shown = self.showing(session)
        self.assertNotIn("Zoom in", shown, "a hint the filter does not match was shown")
        self.assertNotIn("Paste", shown)
        self.assertIn("filter: quit", shown)


@needs_key_injection
class KeysReturnToTheAppTest(unittest.TestCase):
    """Six items of the manual checklist (T6, T13, T15, T16, T21, T28): whatever the mode does,
    the compositor must not be left holding the keyboard for the overlay once the item's action
    is done. Every test proves it the way ``SearchChecklistTest`` does for T45: type into
    ``textsink`` afterwards and read back what actually arrived, because "no grab left behind" is
    a fact about the compositor, not about the process running the overlay (only
    ``_sync_keyboard_mode`` may touch ``keyboard_mode``, DESIGN 編集モード §1).
    """

    OVERLAY = "{anchor: top-right, width: 400px, margin: {top: 20, right: 20}}"

    def showing(self, session: HeadlessSession) -> list[str]:
        return [node.name for node in session.a11y_nodes() if node.showing]

    def until(self, session: HeadlessSession, what: str, ready, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ready():
                return
            time.sleep(0.2)
        self.fail(f"{what}\n{self.showing(session)}\n{session.log_tail()}")

    def searching(self, session: HeadlessSession) -> bool:
        shown = self.showing(session)
        return "Done" in shown and "Search" not in shown

    def normal(self, session: HeadlessSession) -> bool:
        shown = self.showing(session)
        return "Search" in shown and "Done" not in shown and not self.editing(session)

    def editing(self, session: HeadlessSession) -> bool:
        return any(s.startswith("a add") for s in self.showing(session))

    def form_open(self, session: HeadlessSession) -> bool:
        return "Title" in self.showing(session)

    def spawn_textsink(self, session: HeadlessSession, typed: Path) -> None:
        session.spawn([str(FIXTURE_BIN / "textsink"), str(typed)])
        self.until(
            session,
            "textsink never became the active window",
            lambda: "dev.wayhint.test.TextSink" in session.wayhint("context"),
            timeout=30,
        )

    def assert_keys_reach_the_app(self, session: HeadlessSession, typed: Path, word: str) -> None:
        # The first key after the keyboard comes back can be lost, as at the start of a
        # session; a space ahead of the word takes that loss, and ``in`` ignores it.
        session.type_text(" " + word)
        self.until(
            session,
            "the keys did not come back to the application",
            lambda: typed.exists() and word in typed.read_text(),
        )

    def test_t6_leaving_search_keeps_the_filter_and_returns_the_keys(self) -> None:
        root = config_root(self, self.OVERLAY, {"demo": SHEET, "textsink": TEXTSINK_SHEET})
        typed = scratch(self, "wayhint-sink-") / "typed.txt"
        with HeadlessSession(
            root, width=WIDTH, height=HEIGHT, keybind=("W-S-h", "search-mode")
        ) as session:
            self.spawn_textsink(session, typed)
            session.wayhint("show")
            self.until(
                session, "the overlay never opened", lambda: "Type here" in self.showing(session)
            )

            # First round: Esc.
            session.press("win", "shift", "h")
            self.until(
                session, "the hotkey did not start a search", lambda: self.searching(session)
            )
            session.type_text("type")
            self.until(
                session,
                "typing did not narrow the list",
                lambda: "Type here" in self.showing(session),
            )
            session.press("Escape")
            self.until(session, "Esc did not leave search", lambda: self.normal(session))
            self.assertIn("filter: type", self.showing(session), "Esc dropped the filter")
            self.assert_keys_reach_the_app(session, typed, "after-esc")

            # Second round: Enter, from the same window.
            session.press("win", "shift", "h")
            self.until(
                session, "the hotkey did not start a search", lambda: self.searching(session)
            )
            session.press("Return")
            self.until(session, "Enter did not leave search", lambda: self.normal(session))
            self.assertIn("filter: type", self.showing(session), "Enter dropped the filter")
            self.assert_keys_reach_the_app(session, typed, "after-enter")

    def test_t13_leaving_edit_returns_the_keys(self) -> None:
        root = config_root(self, self.OVERLAY, {"textsink": TEXTSINK_SHEET})
        typed = scratch(self, "wayhint-sink-") / "typed.txt"
        with HeadlessSession(
            root, width=WIDTH, height=HEIGHT, keybind=("W-C-h", "edit-mode")
        ) as session:
            self.spawn_textsink(session, typed)

            # Esc with no form open exits edit mode outright.
            session.press("win", "ctrl", "h")
            self.until(session, "the hotkey did not enter edit mode", lambda: self.editing(session))
            session.press("Escape")
            self.until(session, "Esc did not leave edit mode", lambda: not self.editing(session))
            self.assert_keys_reach_the_app(session, typed, "after-esc")

            # The hotkey a second time also exits.
            session.press("win", "ctrl", "h")
            self.until(session, "the hotkey did not enter edit mode", lambda: self.editing(session))
            session.press("win", "ctrl", "h")
            self.until(
                session,
                "the hotkey again did not leave edit mode",
                lambda: not self.editing(session),
            )
            self.assert_keys_reach_the_app(session, typed, "after-hotkey-again")

            # With a form open, the first call only closes the form; the second leaves edit mode.
            session.press("win", "ctrl", "h")
            self.until(session, "the hotkey did not enter edit mode", lambda: self.editing(session))
            session.press("a")
            self.until(
                session, "'a' did not open the quick-add form", lambda: self.form_open(session)
            )
            session.press("win", "ctrl", "h")
            self.until(
                session,
                "the first call did not close the form",
                lambda: not self.form_open(session),
            )
            self.assertTrue(
                self.editing(session), "the first call left edit mode instead of the form"
            )
            session.press("win", "ctrl", "h")
            self.until(
                session,
                "the second call did not leave edit mode",
                lambda: not self.editing(session),
            )
            self.assert_keys_reach_the_app(session, typed, "after-form-then-exit")

    def test_t15_the_toggle_hotkey_hides_and_shows_edit_with_state_intact(self) -> None:
        root = config_root(self, self.OVERLAY, {"textsink": TEXTSINK_SHEET})
        typed = scratch(self, "wayhint-sink-") / "typed.txt"
        with HeadlessSession(
            root,
            width=WIDTH,
            height=HEIGHT,
            keybinds=[("W-h", "toggle"), ("W-C-h", "edit-mode")],
        ) as session:
            self.spawn_textsink(session, typed)
            session.press("win", "ctrl", "h")
            self.until(session, "the hotkey did not enter edit mode", lambda: self.editing(session))

            session.press("win", "h")  # hide: mode and draft are kept, the keyboard is released
            self.until(session, "the overlay did not hide", lambda: not session.a11y_nodes())
            self.assert_keys_reach_the_app(session, typed, "while-hidden")

            session.press("win", "h")  # show again, without swapping context or dropping edit
            self.until(session, "the overlay did not come back", lambda: bool(session.a11y_nodes()))
            self.until(session, "it did not come back in edit mode", lambda: self.editing(session))
            # Shown again in edit, the keyboard is retaken: what is typed now must not reach the
            # application underneath.
            session.type_text("must-not-arrive")
            time.sleep(1.0)
            self.assertNotIn(
                "must-not-arrive",
                typed.read_text() if typed.exists() else "",
                "the keyboard was not retaken when the overlay came back",
            )

    def test_t16_quick_add_with_no_sheet_creates_one_and_shows_the_hint(self) -> None:
        root = config_root(self, self.OVERLAY, {"demo": SHEET})  # nothing matches textsink
        typed = scratch(self, "wayhint-sink-") / "typed.txt"
        hints_dir = root / "hints" / "en"
        with HeadlessSession(
            root, width=WIDTH, height=HEIGHT, keybind=("W-C-h", "edit-mode")
        ) as session:
            self.spawn_textsink(session, typed)
            before = set(hints_dir.glob("*.yaml"))

            session.press("win", "ctrl", "h")
            self.until(session, "the hotkey did not enter edit mode", lambda: self.editing(session))
            session.press("a")
            self.until(
                session, "'a' did not open the quick-add form", lambda: self.form_open(session)
            )
            session.type_text("Brand new hint")
            session.press("Return")  # the title field's own activate saves the form

            self.until(
                session,
                "a sheet was never created for the context",
                lambda: set(hints_dir.glob("*.yaml")) != before,
            )
            self.until(
                session,
                "the new hint never appeared in the list",
                lambda: "Brand new hint" in self.showing(session),
            )
            self.assertTrue(self.normal(session), "saving did not return to normal mode")
            self.assert_keys_reach_the_app(session, typed, "after-quick-add")

    def test_t21_edit_mode_is_refused_while_the_yaml_is_broken(self) -> None:
        root = config_root(self, self.OVERLAY, {"textsink": TEXTSINK_SHEET})
        typed = scratch(self, "wayhint-sink-") / "typed.txt"
        sheet = root / "hints" / "en" / "textsink.yaml"
        with HeadlessSession(root, width=WIDTH, height=HEIGHT) as session:
            self.spawn_textsink(session, typed)
            session.wayhint("show")
            self.until(
                session, "the overlay never opened", lambda: "Type here" in self.showing(session)
            )

            sheet.write_text("hints: [this is not valid: yaml: at all\n")
            self.until(
                session,
                "the YAML error was never shown",
                lambda: any("YAML error" in s for s in self.showing(session)),
            )

            with self.assertRaises(RuntimeError) as caught:
                session.wayhint("edit-mode")
            self.assertIn("cannot edit while the YAML is broken", str(caught.exception))
            self.assertFalse(self.editing(session), "edit mode was entered despite the refusal")
            self.assert_keys_reach_the_app(session, typed, "after-refusal")

    def test_t28_edit_in_editor_stays_shown_and_hands_back_the_keys(self) -> None:
        root = config_root(self, self.OVERLAY, {"textsink": TEXTSINK_SHEET})
        (root / "config.yaml").write_text(
            f"overlay: {self.OVERLAY}\nappearance: {{language: en}}\n"
            "context: {workspace: all}\n"
            f"editor: {{command: ['{FIXTURE_BIN / 'fake-editor'}', '{{file}}']}}\n"
        )
        typed = scratch(self, "wayhint-sink-") / "typed.txt"
        with HeadlessSession(
            root, width=WIDTH, height=HEIGHT, keybind=("W-C-h", "edit-mode")
        ) as session:
            self.spawn_textsink(session, typed)
            session.press("win", "ctrl", "h")
            self.until(session, "the hotkey did not enter edit mode", lambda: self.editing(session))

            self.assertTrue(session.a11y_press("Edit in editor"), session.log_tail())
            self.until(session, "the editor did not end edit mode", lambda: self.normal(session))
            self.until(
                session,
                "the overlay closed instead of staying shown",
                lambda: "Type here" in self.showing(session),
            )
            # The stub editor was launched with the sheet's own path: its first save appends a
            # fixed hint there, which only shows up if that is the file it was given.
            self.until(
                session,
                "the editor's save never reached the overlay's list",
                lambda: "Quit again" in self.showing(session),
            )
            self.assert_keys_reach_the_app(session, typed, "after-edit-in-editor")


if __name__ == "__main__":
    unittest.main()
