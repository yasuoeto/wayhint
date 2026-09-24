"""``wayhint inspect`` and ``wayhint context --shown``: why a mixed-in hint is or is not listed."""

import contextlib
import io
import os
import shutil
import tempfile
import textwrap
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from wayhint import ipc
from wayhint.cli import build_parser, main
from wayhint.daemon import Daemon
from wayhint.models import (
    Hint,
    HintFilter,
    HintSheet,
    IncludeRef,
    ResolvedContext,
    SourceLocation,
)
from wayhint.selection import explain_filters
from wayhint.ui.editmode import WorkspaceView


def hint(id_: str, tags=(), category=None) -> Hint:
    return Hint(
        id=id_,
        title=id_,
        location=SourceLocation(Path("x.yaml"), 1),
        tags=tuple(tags),
        category=category,
    )


HERDR = HintSheet(
    id="herdr",
    title="Herdr",
    path=Path("herdr.yaml"),
    export_tags=("pane",),
    hints=(hint("split", tags=["pane"]), hint("theme", category="ui"), hint("quit")),
)
GIT = HintSheet(
    id="git",
    title="Git",
    path=Path("git.yaml"),
    hints=(hint("commit", category="daily"), hint("bisect", category="rare")),
)
CLAUDE = HintSheet(
    id="claude",
    title="Claude",
    path=Path("claude.yaml"),
    parent_categories=("ui",),
    include=(IncludeRef("git", HintFilter(categories=("daily",))), IncludeRef("gone")),
)


class ExplainFiltersTest(unittest.TestCase):
    def test_parent_filters_say_where_they_came_from(self) -> None:
        parent = explain_filters(CLAUDE, HERDR, [HERDR, GIT, CLAUDE])["parent"]
        self.assertEqual(parent["tags"], ["pane"])
        self.assertEqual(parent["tags_from"], "nested.export_tags (herdr.yaml)")
        self.assertEqual(parent["categories"], ["ui"])
        self.assertEqual(parent["categories_from"], "inherit.parent_categories (claude.yaml)")
        self.assertEqual((parent["shown"], parent["total"]), (2, 3))  # split (tag) or theme (ui)

    def test_the_global_stage_is_config_yaml(self) -> None:
        parent = explain_filters(CLAUDE, HERDR, [], global_parent_tags=[])["parent"]
        self.assertEqual(parent["tags_from"], "nested.parent_tags (config.yaml)")
        self.assertEqual(parent["shown"], 0, "[] lets nothing through whatever categories say")

    def test_include_entries(self) -> None:
        include = explain_filters(CLAUDE, None, [HERDR, GIT, CLAUDE])["include"]
        self.assertEqual(
            [(e["sheet"], e["shown"], e["total"], e["from"]) for e in include],
            [("git", 1, 2, "claude.yaml"), ("gone", None, None, "claude.yaml")],
        )
        self.assertEqual(include[0]["categories"], ["daily"])

    def test_without_its_own_include_the_config_default_is_used(self) -> None:
        sheet = replace(CLAUDE, include=None)
        result = explain_filters(sheet, None, [GIT, sheet], global_include=[IncludeRef("git")])
        entries = [(e["sheet"], e["from"], e["shown"]) for e in result["include"]]
        self.assertEqual(entries, [("git", "config.yaml", 2)])

    def test_no_parent_section_when_the_parent_is_the_active_sheet(self) -> None:
        self.assertIsNone(explain_filters(HERDR, HERDR, [HERDR])["parent"])


class InspectCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="wayhint-inspect-"))
        self.addCleanup(shutil.rmtree, home, True)
        hints = home / "wayhint" / "hints"
        hints.mkdir(parents=True)
        (hints / "herdr.yaml").write_text(
            textwrap.dedent(
                """\
                id: herdr
                title: Herdr
                nested: {export_tags: [pane]}
                hints:
                  - {id: split, title: Split, tags: [pane]}
                  - {id: theme, title: Theme}
                """
            )
        )
        (hints / "git.yaml").write_text(
            "id: git\ntitle: Git\nhints:\n  - {id: commit, title: C, category: daily}\n"
            "  - {id: bisect, title: B, category: rare}\n"
        )
        (hints / "claude.yaml").write_text(
            "id: claude\ntitle: Claude\ninclude:\n  - {sheet: git, categories: [daily]}\n"
        )
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_include_without_a_parent(self) -> None:
        code, out, err = self.run_cli("inspect", "claude")
        self.assertEqual(code, 0, err)
        self.assertIn("parent: decided by the window", out)
        self.assertIn("include git: 1/2 shown (from claude.yaml)", out)
        self.assertIn("  categories: daily", out)

    def test_an_assumed_parent(self) -> None:
        code, out, err = self.run_cli("inspect", "claude", "--parent", "herdr")
        self.assertEqual(code, 0, err)
        self.assertIn("parent herdr: 1/2 shown", out)
        self.assertIn("  tags: pane -- nested.export_tags (herdr.yaml)", out)
        self.assertIn("  categories: not narrowed", out)

    def test_a_sheet_without_include_says_so(self) -> None:
        code, out, err = self.run_cli("inspect", "git")
        self.assertEqual(code, 0, err)
        self.assertIn("include: none", out)

    def test_unknown_sheets(self) -> None:
        self.assertEqual(self.run_cli("inspect", "nope")[0], 1)
        self.assertEqual(self.run_cli("inspect", "claude", "--parent", "nope")[0], 1)


class ShownQueryTest(unittest.TestCase):
    """The daemon answers for the overlay on screen, without resolving the context again."""

    class Window:
        def __init__(self, shown: bool) -> None:
            self.shown = shown

        def is_shown(self) -> bool:
            return self.shown

    def daemon(self, root: Path) -> Daemon:
        hints = root / "hints"
        hints.mkdir()
        (hints / "herdr.yaml").write_text(
            "id: herdr\ntitle: Herdr\nnested: {export_tags: [pane]}\nhints:\n"
            "  - {id: split, title: S, tags: [pane]}\n  - {id: theme, title: T}\n"
        )
        (hints / "claude.yaml").write_text("id: claude\ntitle: Claude\n")
        daemon = Daemon(root, root / "unused.sock")
        daemon.store.load_all()
        daemon.window = self.Window(shown=False)
        return daemon

    def test_it_reports_the_view_and_its_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            daemon = self.daemon(Path(directory))
            ctx = ResolvedContext(active_sheet="claude", parent_context="herdr", desktop_app="foot")
            daemon._open[daemon._workspace_key()] = WorkspaceView(ctx, mode="search")
            with mock.patch.object(daemon.resolver, "resolve") as resolve:
                reply = ipc.handle_request(b'{"cmd":"shown"}\n', daemon.dispatch)
            resolve.assert_not_called()
        self.assertTrue(reply["ok"])
        self.assertEqual(
            (reply["active_sheet"], reply["visible"], reply["mode"]), ("claude", False, "search")
        )
        self.assertEqual(reply["filters"]["parent"]["shown"], 1)

    def test_nothing_shown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            daemon = self.daemon(Path(directory))
            reply = ipc.handle_request(b'{"cmd":"shown"}\n', daemon.dispatch)
        self.assertFalse(reply["ok"])
        self.assertIn("nothing is shown", reply["error"])

    def test_it_is_a_flag_not_a_subcommand(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["shown"])
        self.assertTrue(build_parser().parse_args(["context", "--shown"]).shown)

    def test_the_cli_prints_the_filters(self) -> None:
        reply = {
            "ok": True,
            "active_sheet": "claude",
            "filters": {
                "sheet": "claude",
                "parent": {
                    "sheet": "herdr",
                    "tags": [],
                    "tags_from": "nested.parent_tags (config.yaml)",
                    "categories": None,
                    "categories_from": None,
                    "shown": 0,
                    "total": 2,
                },
                "include": [],
            },
        }
        out = io.StringIO()
        with mock.patch.object(ipc, "send_command", return_value=reply) as send:
            with contextlib.redirect_stdout(out):
                code = main(["context", "--shown"])
        self.assertEqual(code, 0)
        self.assertEqual(send.call_args.args[0], "shown")
        self.assertIn("parent herdr: 0/2 shown", out.getvalue())
        self.assertIn(
            "[] (lets nothing through) -- nested.parent_tags (config.yaml)", out.getvalue()
        )


if __name__ == "__main__":
    unittest.main()
