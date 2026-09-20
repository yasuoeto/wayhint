"""What the overlay would put on screen, against real GTK and real gtk4-layer-shell.

``selection`` and ``geometry`` are pure and tested headless; what was untested is that the widget
side asks them and applies the answer. The list the user reads, the breadcrumb above it and where
the surface sits all come from that join.

Nothing is presented. :meth:`HintWindow.lay_out` fills the widgets and stops, which is exactly the
part worth checking -- ``present_context`` only adds ``set_visible`` and ``present``, and calling
those in a test would put a window on the screen of whoever runs it.
"""

import unittest
from pathlib import Path

from tests.test_desktop_providers import needs_compositor
from wayhint.config import GlobalConfig
from wayhint.models import (
    DisplayConfig,
    Hint,
    HintSheet,
    Margin,
    MatchRule,
    OutputInfo,
    ProcessInfo,
    ResolvedContext,
    Size,
    SourceLocation,
)
from wayhint.selection import sort_hints, visible_hints
from wayhint.ui.geometry import placement

OUT = OutputInfo("eDP-1", 2560, 1600)


def hint(hint_id: str, path: str, *, tags=(), favorite=False, category=None) -> Hint:
    return Hint(
        id=hint_id,
        title=hint_id.upper(),
        location=SourceLocation(Path(path), 1),
        tags=tuple(tags),
        favorite=favorite,
        category=category,
    )


def sheet(sheet_id: str, hints, *, display=None, parent_tags=None) -> HintSheet:
    return HintSheet(
        id=sheet_id,
        title=sheet_id.title(),
        path=Path(f"{sheet_id}.yaml"),
        priority=0,
        match=MatchRule(),
        display=display or DisplayConfig(),
        parent_tags=parent_tags,
        hints=tuple(hints),
    )


def noop(*_args, **_kwargs) -> None:
    return None


@needs_compositor
class RenderTest(unittest.TestCase):
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

    def rows(self, win) -> list[str]:
        """The hint ids the list is showing, in the order it shows them."""
        out, index = [], 0
        while (row := win._list.get_row_at_index(index)) is not None:
            out.append(row.hint.id)
            index += 1
        return out

    def test_the_list_is_what_selection_says_it_should_be(self) -> None:
        """Favourites first, then by category -- decided by ``sort_hints``, not by the widget.

        The child names no ``parent_tags`` of its own, so the tag filter has to come from the
        global config. A widget that stopped passing it would quietly drop the parent hints.
        """
        config = GlobalConfig(parent_tags=("terminal",))
        child = sheet(
            "claude", [hint("one", "claude.yaml"), hint("two", "claude.yaml", favorite=True)]
        )
        parent = sheet(
            "herdr",
            [hint("pane", "herdr.yaml", tags=["terminal"]), hint("theme", "herdr.yaml")],
        )
        ctx = ResolvedContext(active_sheet="claude", parent_context="herdr", output=OUT)
        win = self.window()
        win.lay_out(ctx, [child, parent], config)

        expected = sort_hints(visible_hints(child, parent, config.parent_tags, []))
        self.assertEqual(self.rows(win), [h.id for h in expected])
        self.assertIn("two", self.rows(win))  # the favourite is there
        self.assertIn("pane", self.rows(win))  # the tagged parent hint is mixed in
        self.assertNotIn("theme", self.rows(win))  # the untagged one is not

    def test_the_breadcrumb_and_the_context_line_say_where_the_hints_came_from(self) -> None:
        child = sheet("claude", [hint("one", "claude.yaml")])
        parent = sheet("herdr", [hint("pane", "herdr.yaml")])
        ctx = ResolvedContext(
            active_sheet="claude",
            parent_context="herdr",
            desktop_app="foot.p12345",
            foreground_process=ProcessInfo(
                pid=1, name="claude", argv=("claude",), cmdline="claude"
            ),
            output=OUT,
        )
        win = self.window()
        win.lay_out(ctx, [child, parent], GlobalConfig())

        self.assertEqual(win._header.get_label(), "Herdr › Claude")
        label = win._context_label.get_label()
        self.assertIn("foot", label)
        self.assertNotIn("p12345", label)  # the window's pid is not news to the user (0027)
        self.assertIn("claude", label)
        self.assertIn("eDP-1", label)

    def test_a_context_with_no_sheet_says_so_and_shows_nothing(self) -> None:
        ctx = ResolvedContext(desktop_app="inkscape", output=OUT)
        win = self.window()
        win.lay_out(ctx, [], GlobalConfig())
        self.assertEqual(self.rows(win), [])
        self.assertIn("inkscape", win._context_label.get_label())
        self.assertEqual(win._header.get_label(), "wayhint")

    def test_the_surface_is_placed_where_geometry_says(self) -> None:
        """The pure placement and the layer surface cannot drift apart.

        Both ways of asking for it: the global ``display`` block, and a sheet overriding it. The
        sheet's block is merged over the global one, so the expectation has to be built the same
        way -- a sheet that names only an anchor still inherits the global size.
        """
        display = DisplayConfig(anchor="bottom-left", width=Size(600, "px"), margin=Margin(7, 9))
        cases = {
            "global": (GlobalConfig(display=display), sheet("s", [hint("h", "s.yaml")])),
            "sheet override": (
                GlobalConfig(),
                sheet("s", [hint("h", "s.yaml")], display=display),
            ),
        }
        shell = self.daemon.LayerShell
        edges = {
            "top": shell.Edge.TOP,
            "bottom": shell.Edge.BOTTOM,
            "left": shell.Edge.LEFT,
            "right": shell.Edge.RIGHT,
        }
        for name, (config, active) in cases.items():
            with self.subTest(name):
                win = self.window()
                win.lay_out(ResolvedContext(active_sheet="s", output=OUT), [active], config)
                place = placement(active.display.merged_over(config.display), OUT)
                self.assertEqual(place.edges, {"bottom", "left"})  # the anchor was honoured
                for edge_name, edge in edges.items():
                    on = edge_name in place.edges
                    self.assertIs(shell.get_anchor(win, edge), on, edge_name)
                    self.assertEqual(
                        shell.get_margin(win, edge),
                        getattr(place.margins, edge_name) if on else 0,
                        edge_name,
                    )
                self.assertEqual(tuple(win.get_size_request()), (place.width, place.height or -1))

    def test_search_narrows_the_list_without_touching_the_sheet(self) -> None:
        active = sheet(
            "s", [hint("copy", "s.yaml"), hint("paste", "s.yaml"), hint("quit", "s.yaml")]
        )
        win = self.window()
        win.lay_out(ResolvedContext(active_sheet="s", output=OUT), [active], GlobalConfig())
        self.assertEqual(sorted(self.rows(win)), ["copy", "paste", "quit"])

        win.set_mode("search", refocus=False)
        win._search.set_text("PAST")  # the search is case-insensitive
        win._render_list()
        self.assertEqual(self.rows(win), ["paste"])

        win.set_mode("normal", refocus=False)
        self.assertEqual(sorted(self.rows(win)), ["copy", "paste", "quit"])


if __name__ == "__main__":
    unittest.main()
