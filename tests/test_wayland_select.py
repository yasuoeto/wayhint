import struct
import unittest

from wayhint.config import ConfigError, parse_global_config
from wayhint.context.base import ContextError, DesktopSnapshot
from wayhint.context.select import AutoDesktopProvider, select_desktop_provider
from wayhint.context.wayland import _Toplevel, decode_states, find_by_ref, pick_active
from wayhint.models import OutputInfo

OUT = OutputInfo("eDP-1", 2560, 1600)


def tl(app_id, title, *states):
    return _Toplevel(handle=None, app_id=app_id, title=title, states=tuple(states))


class WaylandHelpersTest(unittest.TestCase):
    def test_decode_states_from_uint32_array(self) -> None:
        self.assertEqual(decode_states(struct.pack("=II", 2, 1)), (2, 1))
        self.assertEqual(decode_states(b""), ())
        self.assertEqual(decode_states([2]), (2,))
        self.assertEqual(decode_states(None), ())

    def test_pick_active(self) -> None:
        a, b = tl("foot", "x"), tl("firefox", "y", 2)
        self.assertIs(pick_active([a, b]), b)
        self.assertIsNone(pick_active([a]))

    def test_find_by_ref_exact_then_unique_app(self) -> None:
        a, b, c = tl("foot", "one"), tl("foot", "two"), tl("firefox", "f")
        tls = [a, b, c]
        self.assertIs(find_by_ref(tls, a.ref), a)
        self.assertIs(find_by_ref(tls, "foot\tgone"), None)  # two foot windows: ambiguous
        self.assertIs(find_by_ref(tls, "firefox\tgone"), c)  # title changed, app unique
        self.assertIsNone(find_by_ref(tls, "chromium\t"))


class Fake:
    def __init__(self, error=None):
        self.error, self.focused = error, []

    def snapshot(self):
        if self.error:
            raise ContextError(self.error)
        return DesktopSnapshot("foot", "t", "foot\tt", OUT, OUT)

    def find_output(self, name):
        if self.error:
            raise ContextError(self.error)
        return OUT if name == OUT.name else None

    def focus_view(self, ref):
        self.focused.append(ref)
        return not self.error


class AutoProviderTest(unittest.TestCase):
    def test_primary_wins_and_sticks(self) -> None:
        primary, fallback = Fake(), Fake()
        auto = AutoDesktopProvider(lambda: primary, lambda: fallback, lambda: True)
        self.assertEqual(auto.snapshot().app_id, "foot")
        self.assertTrue(auto.focus_view("foot\tt"))
        self.assertEqual(fallback.focused, [])

    def test_falls_back_when_primary_fails_and_fallback_available(self) -> None:
        primary, fallback = Fake(error="no protocol"), Fake()
        auto = AutoDesktopProvider(lambda: primary, lambda: fallback, lambda: True)
        self.assertEqual(auto.snapshot().app_id, "foot")
        self.assertEqual(auto.find_output("eDP-1"), OUT)

    def test_error_surfaces_when_no_fallback(self) -> None:
        auto = AutoDesktopProvider(lambda: Fake(error="no protocol"), Fake, lambda: False)
        with self.assertRaises(ContextError) as cm:
            auto.snapshot()
        self.assertEqual(str(cm.exception), "no protocol")
        self.assertIsNone(auto.find_output("eDP-1"))

    def test_select_by_name(self) -> None:
        self.assertEqual(
            select_desktop_provider("wayland").__class__.__name__, "WaylandContextProvider"
        )
        self.assertEqual(
            select_desktop_provider("wayfire").__class__.__name__, "WayfireContextProvider"
        )
        self.assertIsInstance(select_desktop_provider("auto"), AutoDesktopProvider)


class ConfigBackendTest(unittest.TestCase):
    def test_backend_default_and_values(self) -> None:
        self.assertEqual(parse_global_config({}).context_backend, "auto")
        self.assertEqual(
            parse_global_config({"context": {"backend": "wayland"}}).context_backend, "wayland"
        )
        with self.assertRaises(ConfigError):
            parse_global_config({"context": {"backend": "x11"}})


if __name__ == "__main__":
    unittest.main()
