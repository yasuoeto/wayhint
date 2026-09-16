import unittest
from pathlib import Path

from wayhint.matcher import match_app, match_process
from wayhint.models import Hint, HintSheet, MatchRule, ProcessInfo, SourceLocation
from wayhint.selection import search_hints, sort_hints, visible_hints

LOC = SourceLocation(Path("x.yaml"), 1)


def hint(id_, **kw) -> Hint:
    return Hint(id=id_, title=kw.pop("title", id_.title()), location=LOC, **kw)


def sheet(id_, priority=0, app=(), argv=(), cmdline=(), hints=(), parent_tags=None) -> HintSheet:
    return HintSheet(
        id=id_,
        title=id_,
        path=Path(f"{id_}.yaml"),
        priority=priority,
        match=MatchRule(
            app_id_regex=tuple(app), argv_regex=tuple(argv), cmdline_regex=tuple(cmdline)
        ),
        parent_tags=parent_tags,
        hints=tuple(hints),
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
