"""Phase 7b: the hint-editing CLI, the new IPC commands, and the display order (0014 D7).

Headless: every test works on a tmp config directory, and points ``XDG_RUNTIME_DIR`` at an empty
one so that ``--sheet``-less commands find no daemon instead of talking to the real one.
"""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wayhint import ipc
from wayhint.cli import CommandError, _no_sheet_message, main, neighbour
from wayhint.daemon import Daemon
from wayhint.models import Hint, ProcessInfo, ResolvedContext, SourceLocation
from wayhint.selection import same_group, sort_hints
from wayhint.yaml_store import load_sheet

SHEET = """\
id: demo
title: Demo
hints:
  - id: alpha
    title: Alpha
    category: one
  - id: beta
    title: Beta
    category: two
    favorite: true
  - id: gamma
    title: Gamma
    category: one
  - id: delta
    title: Delta
    favorite: true
"""


def hint(id_: str, category=None, favorite=False) -> Hint:
    return Hint(
        id=id_,
        title=id_.title(),
        location=SourceLocation(Path("x.yaml"), 1),
        category=category,
        favorite=favorite,
    )


class SortOrderTest(unittest.TestCase):
    """DECISIONS 0014 D7: the favorite block ignores category, the rest does not."""

    def test_favorites_keep_yaml_order_across_categories(self) -> None:
        hints = [
            hint("a1", "alpha"),
            hint("b1", "beta", favorite=True),
            hint("n1", None),
            hint("a2", "alpha", favorite=True),
            hint("n2", None, favorite=True),
            hint("b2", "beta"),
        ]
        self.assertEqual(
            [h.id for h in sort_hints(hints)],
            ["b1", "a2", "n2", "a1", "n1", "b2"],
            "favorites in YAML order; non-favorites by first appearance of their category",
        )

    def test_category_rank_ignores_favorites(self) -> None:
        # 'beta' first appears in a favorite, which must not give it a rank in the lower block.
        hints = [hint("f", "beta", favorite=True), hint("x", "alpha"), hint("y", "beta")]
        self.assertEqual([h.id for h in sort_hints(hints)], ["f", "x", "y"])

    def test_same_group(self) -> None:
        self.assertTrue(same_group(hint("a", "one", True), hint("b", "two", True)))
        self.assertTrue(same_group(hint("a", "one"), hint("b", "one")))
        self.assertFalse(same_group(hint("a", "one"), hint("b", "two")))
        self.assertFalse(same_group(hint("a", "one", True), hint("b", "one")))


class NeighbourTest(unittest.TestCase):
    def hints(self) -> list[Hint]:
        return [
            hint("fav1", "one", favorite=True),
            hint("fav2", "two", favorite=True),
            hint("a", "one"),
            hint("b", "one"),
            hint("c", "two"),
        ]

    def test_inside_a_group(self) -> None:
        self.assertEqual(neighbour(self.hints(), "a", "down").id, "b")
        self.assertEqual(neighbour(self.hints(), "b", "up").id, "a")
        self.assertEqual(neighbour(self.hints(), "fav1", "down").id, "fav2")

    def test_refuses_to_cross_a_group(self) -> None:
        for hint_id, direction in (("b", "down"), ("fav2", "down"), ("a", "up")):
            with self.subTest(hint=hint_id, direction=direction):
                with self.assertRaises(CommandError):
                    neighbour(self.hints(), hint_id, direction)


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        # config_dir() is <XDG_CONFIG_HOME>/wayhint, so the config lives one level down.
        home = Path(tempfile.mkdtemp(prefix="wayhint-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        self.sheet = home / "wayhint" / "hints" / "demo.yaml"
        self.sheet.parent.mkdir(parents=True)
        self.sheet.write_text(SHEET)
        self.config_home = home
        self.runtime = Path(tempfile.mkdtemp(prefix="wayhint-run-"))
        self.addCleanup(shutil.rmtree, self.runtime, True)
        self.env("XDG_CONFIG_HOME", str(home))
        self.env("XDG_RUNTIME_DIR", str(self.runtime))  # no socket: the daemon is "not running"

    def env(self, name: str, value: str) -> None:
        import os

        old = os.environ.get(name)
        os.environ[name] = value
        self.addCleanup(lambda: os.environ.__setitem__(name, old) if old else os.environ.pop(name))

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def hints(self) -> list[Hint]:
        sheet, issues = load_sheet(self.sheet)
        self.assertEqual(issues, [])
        return list(sheet.hints)

    def ids(self) -> list[str]:
        return [h.id for h in self.hints()]

    def test_add(self) -> None:
        code, out, err = self.run_cli(
            "add", "New pane", "--key", "Ctrl+Shift+N", "--category", "panes", "--sheet", "demo"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("added new-pane", out)
        added = self.hints()[-1]
        self.assertEqual(
            (added.id, added.title, added.key), ("new-pane", "New pane", "Ctrl+Shift+N")
        )
        self.assertEqual(added.category, "panes")
        self.assertFalse(added.favorite)
        self.assertTrue(added.learned, "learned is stamped with the day it was captured")

    def test_add_gives_a_colliding_slug_a_number(self) -> None:
        self.run_cli("add", "Alpha", "--sheet", "demo")
        self.assertIn("alpha-2", self.ids())

    def test_tip_takes_both_key_and_command(self) -> None:
        code, _out, err = self.run_cli(
            "add",
            "Reset the terminal",
            "--kind",
            "tip",
            "--key",
            "Ctrl-l",
            "--command",
            "reset",
            "--sheet",
            "demo",
        )
        self.assertEqual(code, 0, err)
        added = self.hints()[-1]
        self.assertEqual((added.kind, added.key, added.command), ("tip", "Ctrl-l", "reset"))

    def test_note_takes_neither(self) -> None:
        code, _out, err = self.run_cli(
            "add", "Remember this", "--kind", "note", "--key", "Ctrl-l", "--sheet", "demo"
        )
        self.assertEqual(code, 1)
        self.assertIn("--kind note", err)

    def test_edit(self) -> None:
        code, _out, err = self.run_cli("edit", "alpha", "--title", "Renamed", "--sheet", "demo")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.hints()[0].title, "Renamed")
        self.assertEqual(self.hints()[0].category, "one", "untouched fields survive")

    def test_edit_unknown_hint(self) -> None:
        code, _out, err = self.run_cli("edit", "nope", "--title", "x", "--sheet", "demo")
        self.assertEqual(code, 1)
        self.assertIn("nope", err)

    def test_edit_without_fields(self) -> None:
        code, _out, err = self.run_cli("edit", "alpha", "--sheet", "demo")
        self.assertEqual(code, 1)
        self.assertIn("nothing to change", err)

    def test_remove(self) -> None:
        code, _out, err = self.run_cli("remove", "beta", "--sheet", "demo")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.ids(), ["alpha", "gamma", "delta"])

    def test_favorite_on_and_off(self) -> None:
        self.run_cli("favorite", "alpha", "--sheet", "demo")
        self.assertTrue(self.hints()[0].favorite)
        self.run_cli("favorite", "alpha", "--off", "--sheet", "demo")
        self.assertFalse(self.hints()[0].favorite)

    def test_move_inside_a_group(self) -> None:
        code, _out, err = self.run_cli("move", "alpha", "down", "--sheet", "demo")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.ids(), ["gamma", "beta", "alpha", "delta"], "YAML positions swapped")

    def test_move_refuses_to_cross_a_group(self) -> None:
        code, _out, err = self.run_cli("move", "delta", "down", "--sheet", "demo")
        self.assertEqual(code, 1)
        self.assertIn("group", err)
        self.assertEqual(self.ids(), ["alpha", "beta", "gamma", "delta"], "nothing was written")

    def test_format_is_idempotent_and_reports(self) -> None:
        code, out, err = self.run_cli("format")
        self.assertEqual(code, 0, err)
        self.assertIn("formatted", out)
        code, out, _err = self.run_cli("format")
        self.assertIn("unchanged", out)
        self.assertEqual(self.ids(), ["alpha", "beta", "gamma", "delta"])

    def test_format_adds_the_modeline_when_asked(self) -> None:
        code, _out, err = self.run_cli("format", "--modeline")
        self.assertEqual(code, 0, err)
        self.assertTrue(self.sheet.read_text().startswith("# yaml-language-server: $schema="))

    def test_schema_to_stdout_and_to_a_file(self) -> None:
        code, out, err = self.run_cli("schema")
        self.assertEqual(code, 0, err)
        self.assertIn('"$schema"', out)
        target = self.config_home / "wayhint" / "schema.json"
        code, out, err = self.run_cli("schema", "--write", str(target))
        self.assertEqual(code, 0, err)
        self.assertTrue(target.exists())

    def test_without_sheet_and_without_daemon(self) -> None:
        code, _out, err = self.run_cli("edit", "alpha", "--title", "x")
        self.assertEqual(code, 1)
        self.assertIn("--sheet", err)

    def test_unknown_sheet(self) -> None:
        code, _out, err = self.run_cli("remove", "alpha", "--sheet", "nope")
        self.assertEqual(code, 1)
        self.assertIn("nope", err)


class IpcCommandTest(unittest.TestCase):
    def context_reply(self, context: ResolvedContext) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            daemon = Daemon(root, root / "unused.sock")
            # Replace context acquisition, not the daemon's response construction or dispatch.
            with mock.patch.object(daemon.resolver, "resolve", return_value=context):
                return ipc.handle_request(b'{"cmd":"context"}\n', daemon.dispatch)

    def test_new_commands_exist(self) -> None:
        self.assertIn("context", ipc.COMMANDS)
        self.assertIn("edit-mode", ipc.COMMANDS)

    def test_context_reply_shape(self) -> None:
        reply = self.context_reply(
            ResolvedContext(
                active_sheet="claude-code",
                parent_context="herdr",
                desktop_app="foot",
                foreground_process=ProcessInfo(
                    pid=123,
                    name="node",
                    argv=("/usr/bin/node", "/example/bin/codex"),
                    cmdline="synthetic private command line",
                    cwd="/example/private",
                ),
            )
        )
        self.assertEqual(
            reply,
            {
                "ok": True,
                "active_sheet": "claude-code",
                "parent_context": "herdr",
                "desktop_app": "foot",
                "process": {"name": "node", "argv_basenames": ["node", "codex"]},
                "include": [],
                "error": None,
            },
        )

    def test_context_says_why_there_is_no_sheet(self) -> None:
        reply = self.context_reply(ResolvedContext(error="desktop context unavailable"))
        self.assertEqual(
            reply,
            {
                "ok": True,
                "active_sheet": None,
                "parent_context": None,
                "desktop_app": None,
                "process": None,
                "include": [],
                "error": "desktop context unavailable",
            },
        )

    def test_no_sheet_message_carries_the_reason(self) -> None:
        message = _no_sheet_message({"error": "desktop context unavailable"})
        self.assertIn("desktop context unavailable", message)
        self.assertIn("--sheet", message)
        self.assertNotIn("(", _no_sheet_message({}), "no reason, no parenthesis")
