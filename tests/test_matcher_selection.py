import unittest
from dataclasses import replace
from pathlib import Path

from wayhint.matcher import MAX_CANDIDATE, match_app, match_process
from wayhint.models import Hint, HintSheet, MatchRule, ProcessInfo, SourceLocation
from wayhint.selection import search_hints, sort_hints, visible_hints

LOC = SourceLocation(Path("x.yaml"), 1)


def hint(id_, **kw) -> Hint:
    return Hint(id=id_, title=kw.pop("title", id_.title()), location=LOC, **kw)


def sheet(
    id_, priority=0, app=(), argv=(), cmdline=(), hints=(), parent_tags=None, include=()
) -> HintSheet:
    path = Path(f"{id_}.yaml")
    return HintSheet(
        id=id_,
        title=id_,
        path=path,
        priority=priority,
        match=MatchRule(
            app_id_regex=tuple(app), argv_regex=tuple(argv), cmdline_regex=tuple(cmdline)
        ),
        parent_tags=parent_tags,
        include=tuple(include),
        # A hint knows the file it lives in; that is what tells two sheets' hints apart.
        hints=tuple(replace(h, location=SourceLocation(path, i + 1)) for i, h in enumerate(hints)),
    )


def proc(argv, name=None, cmdline=None) -> ProcessInfo:
    return ProcessInfo(
        pid=1,
        name=name or argv[0].rsplit("/", 1)[-1],
        argv=tuple(argv),
        cmdline=cmdline or " ".join(argv),
    )


class MatchAppTest(unittest.TestCase):
    def test_basic_and_no_match(self) -> None:
        sheets = [sheet("inkscape", app=["^org\\.inkscape"]), sheet("chromium", app=["chrom"])]
        self.assertIs(match_app(sheets, "org.inkscape.Inkscape"), sheets[0])
        self.assertIs(match_app(sheets, "chromium-browser"), sheets[1])
        self.assertIsNone(match_app(sheets, "foot"))
        self.assertIsNone(match_app(sheets, None))

    def test_priority_then_specificity_then_file_order(self) -> None:
        generic = sheet("generic", app=["."])
        two_patterns = sheet("two", app=["herdr", "^herdr$"])
        first = sheet("first", app=["herdr"])
        high = sheet("high", priority=5, app=["herdr"])
        self.assertIs(match_app([generic, two_patterns, first], "herdr"), two_patterns)
        self.assertIs(match_app([generic, first], "herdr"), generic)  # equal → file order
        self.assertIs(match_app([generic, two_patterns, high], "herdr"), high)

    def test_broken_regex_is_ignored(self) -> None:
        self.assertIsNone(match_app([sheet("bad", app=["("])], "anything"))

    def test_only_the_start_of_a_very_long_candidate_is_matched(self) -> None:
        """A program can make its app_id or command line as long as it likes; a pattern that
        backtracks badly must not get all of it (the overlay waits for the match)."""
        long_id = "a" * MAX_CANDIDATE + "tail"
        self.assertIsNone(match_app([sheet("tail", app=["tail$"])], long_id))
        self.assertIsNotNone(match_app([sheet("head", app=["^a"])], long_id))
        long_cmd = proc(["node", "x" * (MAX_CANDIDATE * 2)])
        self.assertIsNone(match_process([sheet("end", cmdline=["x{8000}"])], long_cmd))


class MatchProcessTest(unittest.TestCase):
    def test_argv_basename_and_cmdline(self) -> None:
        claude = sheet("claude", argv=["^claude$"])
        codex = sheet("codex", argv=["^codex$"], cmdline=["node .*/codex"])
        sheets = [claude, codex]
        self.assertIs(match_process(sheets, proc(["claude"])), claude)
        self.assertIs(match_process(sheets, proc(["/usr/bin/claude"])), claude)
        # ``node /path/to/codex``: name is node, argv[1] basename is codex → argv match
        self.assertIs(
            match_process(sheets, proc(["node", "/opt/codex/bin/codex"], name="node")), codex
        )
        self.assertIsNone(match_process(sheets, proc(["bash"])))
        self.assertIsNone(match_process(sheets, None))

    def test_argv_regex_does_not_see_full_cmdline(self) -> None:
        s = sheet("s", argv=["^node /opt"])
        self.assertIsNone(match_process([s], proc(["node", "/opt/x"], name="node")))
        s2 = sheet("s2", cmdline=["^node /opt"])
        self.assertIs(match_process([s2], proc(["node", "/opt/x"], name="node")), s2)


class VisibleHintsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.herdr = sheet(
            "herdr",
            hints=[
                hint("split", tags=["terminal"], favorite=True),
                hint("theme", tags=["ui"]),
                hint("scroll", tags=["terminal", "ai"]),
            ],
        )
        self.claude = sheet("claude", hints=[hint("compact")], parent_tags=None)

    def test_desktop_only(self) -> None:
        self.assertEqual(
            [h.id for h in visible_hints(self.herdr, None, ["terminal"])],
            ["split", "theme", "scroll"],
        )
        self.assertEqual(
            [h.id for h in visible_hints(self.herdr, self.herdr, ["x"])],
            ["split", "theme", "scroll"],
        )

    def test_nested_uses_global_tags(self) -> None:
        ids = [h.id for h in visible_hints(self.claude, self.herdr, ["terminal"])]
        self.assertEqual(ids, ["compact", "split", "scroll"])

    def test_child_overrides_global_tags_and_favorite_is_irrelevant(self) -> None:
        child = sheet("codex", hints=[hint("c")], parent_tags=["ui"])
        ids = [h.id for h in visible_hints(child, self.herdr, ["terminal"])]
        self.assertEqual(ids, ["c", "theme"])  # favorite 'split' is not pulled in
        empty = sheet("empty", hints=[hint("e")], parent_tags=[])
        self.assertEqual([h.id for h in visible_hints(empty, self.herdr, ["terminal"])], ["e"])

    def test_parent_only_when_process_unknown(self) -> None:
        self.assertEqual(len(visible_hints(None, self.herdr, ["terminal"])), 3)
        self.assertEqual(visible_hints(None, None, ["terminal"]), [])


class ParentFilterOrderTest(unittest.TestCase):
    """DECISIONS 0034 D1: the first tag list written down decides, and nothing written is all.

    Columns: the child's ``inherit.parent_tags``, the global ``nested.parent_tags``, the
    parent's ``nested.export_tags``. ``None`` is "not written", ``[]`` is "written, empty".
    """

    TABLE = (
        (None, None, None, ["c", "split", "close", "theme"]),
        (None, None, ["pane"], ["c", "split", "close"]),
        (None, None, [], ["c"]),
        (None, ["pane"], ["other"], ["c", "split", "close"]),  # the parent's list is not read
        (None, [], ["pane"], ["c"]),
        (["pane"], [], [], ["c", "split", "close"]),
        ([], None, None, ["c"]),
    )

    def test_the_table(self) -> None:
        parent_hints = [
            hint("split", tags=["pane"]),
            hint("close", tags=["pane", "other"]),
            hint("theme", tags=["ui"]),
        ]
        for row, (child_tags, global_tags, export, expected) in enumerate(self.TABLE, start=1):
            with self.subTest(row=row, child=child_tags, glob=global_tags, export=export):
                parent = replace(
                    sheet("herdr", hints=parent_hints),
                    export_tags=None if export is None else tuple(export),
                )
                child = sheet("claude", hints=[hint("c")], parent_tags=child_tags)
                ids = [h.id for h in visible_hints(child, parent, global_tags)]
                self.assertEqual(ids, expected)

    def test_export_tags_are_not_read_for_an_include(self) -> None:
        """``export_tags`` is the nested path only; an include still brings the whole sheet."""
        herdr = replace(
            sheet("herdr", hints=[hint("split", tags=["pane"]), hint("theme")]),
            export_tags=("pane",),
        )
        child = sheet("claude", hints=[hint("c")])
        self.assertEqual(
            [h.id for h in visible_hints(child, None, None, [herdr])], ["c", "split", "theme"]
        )


class SheetWithoutMatchTest(unittest.TestCase):
    """A sheet with no ``match`` exists to be included, never to be picked (0026)."""

    def test_it_is_never_the_active_sheet(self) -> None:
        common = sheet("wm", hints=[hint("close")])
        sheets = [common, sheet("foot", app=["^foot$"])]
        self.assertEqual(match_app(sheets, "foot").id, "foot")
        self.assertIsNone(match_app([common], "foot"))
        self.assertIsNone(match_app([common], "wm"))  # not even by its own name
        self.assertIsNone(match_process([common], proc(["wm"])))

    def test_it_can_still_be_mixed_in(self) -> None:
        common = sheet("wm", hints=[hint("close")])
        active = sheet("foot", app=["^foot$"], hints=[hint("split")], include=["wm"])
        ids = [h.id for h in visible_hints(active, None, [], [common])]
        self.assertEqual(ids, ["split", "close"])


class IncludeTest(unittest.TestCase):
    """Sheets named by ``include`` are mixed in after the parent (DECISIONS 0026)."""

    def setUp(self) -> None:
        self.git = sheet("git", hints=[hint("commit"), hint("push")])
        self.wm = sheet("wm", hints=[hint("close")])
        self.claude = sheet("claude", hints=[hint("compact")], include=["git", "wm"])
        self.herdr = sheet("herdr", hints=[hint("split", tags=["terminal"]), hint("theme")])

    def ids(self, *args, **kw):
        return [h.id for h in visible_hints(*args, **kw)]

    def test_included_hints_follow_the_active_sheet_in_the_listed_order(self) -> None:
        self.assertEqual(
            self.ids(self.claude, None, [], [self.git, self.wm]),
            ["compact", "commit", "push", "close"],
        )

    def test_the_parent_comes_before_anything_included(self) -> None:
        self.assertEqual(
            self.ids(self.claude, self.herdr, ["terminal"], [self.git]),
            ["compact", "split", "commit", "push"],
        )

    def test_a_sheet_that_is_both_parent_and_included_is_listed_once(self) -> None:
        self.assertEqual(
            self.ids(self.claude, self.herdr, ["terminal"], [self.herdr]),
            ["compact", "split", "theme"],
        )

    def test_the_same_sheet_included_twice_is_listed_once(self) -> None:
        self.assertEqual(
            self.ids(self.claude, None, [], [self.git, self.git]),
            ["compact", "commit", "push"],
        )

    def test_including_the_active_sheet_changes_nothing(self) -> None:
        self.assertEqual(self.ids(self.claude, None, [], [self.claude]), ["compact"])

    def test_nothing_included_is_the_old_behaviour(self) -> None:
        self.assertEqual(self.ids(self.claude, None, [], []), ["compact"])


class SortSearchTest(unittest.TestCase):
    def test_sort(self) -> None:
        hints = [
            hint("a", category="edit"),
            hint("b", category="nav"),
            hint("c", category="edit", favorite=True),
            hint("d", category="nav"),
            hint("e"),
            hint("f", category="nav", favorite=True),
        ]
        self.assertEqual([h.id for h in sort_hints(hints)], ["c", "f", "a", "b", "d", "e"])

    def test_search(self) -> None:
        hints = [
            hint("a", title="Split pane", key="Ctrl+Shift+D", category="Panes"),
            hint("b", title="Compact", command="/compact", remark="Summarise context", tags=["ai"]),
            hint("c", title="Kill", key="ctrl+shift+w"),
        ]
        ids = lambda q: [h.id for h in search_hints(hints, q)]  # noqa: E731
        self.assertEqual(ids(""), ["a", "b", "c"])
        self.assertEqual(ids("CTRL shift"), ["a", "c"])
        self.assertEqual(ids("ctrl pane"), ["a"])
        self.assertEqual(ids("summarise"), ["b"])
        self.assertEqual(ids("AI"), ["b"])
        self.assertEqual(ids("nothing here"), [])
