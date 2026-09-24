"""The desktop adapters against the interface the resolver uses, and against a real compositor.

The nested providers got a contract test after one of them drifted out of step with the
resolver's call and nothing failed (``RealProviderContractTest`` in ``test_context.py``). The
desktop side had the same hole and is harder to reach, because pywayland wants a compositor and
GTK wants a display. It splits into three:

* **Signatures** need neither, so every adapter is checked on every run.
* **Failure** needs neither either: pointing pywayland at a display that is not there is exactly
  the path a session without a compositor takes, and it has to arrive as ``ContextError`` rather
  than as whatever the library raised (``dev-docs/DESIGN.md`` Failure modes).
* **Success** needs a compositor, so it is skipped when there is none. Where one is running it
  connects for real -- which is the only way to notice that a protocol binding was regenerated
  wrong, or that the GTK and layer-shell typelibs stopped loading in the order DECISIONS 0009
  requires.
"""

import inspect
import os
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

from wayhint.config import GlobalConfig
from wayhint.context.base import ContextError, DesktopContextProvider
from wayhint.context.resolver import ContextResolver
from wayhint.context.wayfire import WayfireContextProvider
from wayhint.context.wayland import WaylandContextProvider
from wayhint.models import OutputInfo

ROOT = Path(__file__).resolve().parent.parent
NO_SUCH_DISPLAY = "wayhint-no-such-display"


def compositor_available() -> bool:
    """Is there a compositor this session can actually take a snapshot from?"""
    if not os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        WaylandContextProvider().snapshot()
    except ContextError:
        return False
    return True


needs_compositor = unittest.skipUnless(
    compositor_available(), "no Wayland compositor for this session"
)


class DesktopContractTest(unittest.TestCase):
    """Every adapter answers the calls ``ContextResolver`` makes, by signature alone."""

    def test_the_adapters_match_the_protocol_the_resolver_uses(self) -> None:
        declared = {name for name in vars(DesktopContextProvider) if not name.startswith("_")}
        self.assertEqual(declared, {"snapshot", "find_output", "focus_view"})
        for adapter in (WaylandContextProvider, WayfireContextProvider):
            with self.subTest(adapter=adapter.__name__):
                inspect.signature(adapter.snapshot).bind(adapter)
                inspect.signature(adapter.find_output).bind(adapter, "eDP-1")
                inspect.signature(adapter.focus_view).bind(adapter, "7")


class WithoutACompositorTest(unittest.TestCase):
    """A session with no compositor is an error the overlay can show, not a crash."""

    def snapshot_of_nothing(self):
        with unittest.mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": NO_SUCH_DISPLAY}):
            return WaylandContextProvider().snapshot()

    def test_an_unreachable_display_is_a_context_error(self) -> None:
        with self.assertRaises(ContextError) as caught:
            self.snapshot_of_nothing()
        self.assertIn("Wayland", str(caught.exception))

    def test_the_resolver_turns_it_into_a_context_the_overlay_can_render(self) -> None:
        """The real adapter, through the real resolver: an error context, not an exception."""
        with unittest.mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": NO_SUCH_DISPLAY}):
            ctx = ContextResolver(WaylandContextProvider()).resolve([], GlobalConfig())
        self.assertTrue(ctx.error)
        self.assertIsNone(ctx.active_sheet)
        self.assertIsNone(ctx.foreground_process)


@needs_compositor
class LiveCompositorTest(unittest.TestCase):
    """Against the compositor this session is running on. Read-only: nothing is focused or moved."""

    def test_a_snapshot_has_the_shape_the_resolver_expects(self) -> None:
        snap = WaylandContextProvider().snapshot()
        for field in (snap.app_id, snap.title, snap.view_ref):
            self.assertIsInstance(field, (str, type(None)))
        for output in (snap.output, snap.focused_output):
            if output is not None:
                self.assertIsInstance(output, OutputInfo)
                self.assertGreater(output.width, 0)
                self.assertGreater(output.height, 0)

    def test_find_output_answers_for_a_name_the_snapshot_gave(self) -> None:
        provider = WaylandContextProvider()
        snap = provider.snapshot()
        known = snap.output or snap.focused_output
        if known is None:
            self.skipTest("the compositor named no output")
        self.assertEqual(provider.find_output(known.name), known)
        self.assertIsNone(provider.find_output("wayhint-no-such-output"))

    def test_the_resolver_produces_a_context_from_the_real_desktop(self) -> None:
        ctx = ContextResolver(WaylandContextProvider()).resolve([], GlobalConfig())
        self.assertIsNone(ctx.error)
        self.assertEqual(ctx.chain, ())  # no sheets, so no nested provider was registered
        self.assertIsNone(ctx.active_sheet)


@needs_compositor
class GuiLoadsTest(unittest.TestCase):
    """GTK and gtk4-layer-shell load, in the order DECISIONS 0009 requires.

    Run in a child process: importing the typelibs is global and irreversible, and a mistake in
    the preload aborts the interpreter rather than raising. The daemon does nothing but load them
    here -- no window is created, so nothing appears on screen.
    """

    def test_load_gui_succeeds(self) -> None:
        probe = (
            "from wayhint.daemon import _load_gui\n"
            "_load_gui()\n"
            "from wayhint import daemon\n"
            "assert daemon.Gtk is not None and daemon.LayerShell is not None\n"
            "print('ok')\n"
        )
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        done = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60, env=env
        )
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
