import contextlib
import io
import tempfile
import textwrap
import unittest
from pathlib import Path

from wayhint.cli import main
from wayhint.models import Margin, Size
from wayhint.yaml_store import (
    SheetStore,
    load_all,
    load_config,
    load_sheet,
    load_sheets,
    parse_sheet,
    read_document,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOOD = FIXTURES / "good"


def _sheet_text(body: str) -> str:
    return textwrap.dedent(body).lstrip()


def _parse(body: str, name: str = "s.yaml"):
    data, issues = read_document_from_text(_sheet_text(body), name)
    assert not issues, issues
    return parse_sheet(data, Path(name))


def read_document_from_text(text: str, name: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(text, encoding="utf-8")
        return read_document(p)


class GoodFixtureTest(unittest.TestCase):
    def test_config(self) -> None:
        result = load_config(GOOD / "config.yaml")
        self.assertEqual(result.issues, [])
        cfg = result.config
        self.assertEqual(cfg.display.anchor, "top-right")
        self.assertEqual(cfg.display.width, Size(420, "px"))
        self.assertEqual(cfg.display.height, Size(60, "%"))
        self.assertEqual(cfg.display.margin, Margin(top=24, right=24))
        self.assertEqual(cfg.parent_tags, ("terminal",))
        self.assertEqual(cfg.max_results, 30)
        self.assertEqual(cfg.log_level, "info")
        self.assertEqual(cfg.editor.command, ("gvim", "--remote-silent", "+{line}", "{file}"))

    def test_missing_config_gives_defaults(self) -> None:
        result = load_config(GOOD / "nope.yaml")
        self.assertTrue(result.ok)
        self.assertEqual(result.config.display.anchor, "top-right")

    def test_sheets_and_line_numbers(self) -> None:
        result = load_sheets(GOOD / "hints")
        self.assertEqual(result.issues, [])
        by_id = {s.id: s for s in result.sheets}
        self.assertEqual(set(by_id), {"herdr", "claude"})
        herdr = by_id["herdr"]
        self.assertEqual([h.id for h in herdr.hints], ["new-pane", "kill-pane"])
        self.assertEqual(herdr.hints[0].location.line, 8)
        self.assertEqual(herdr.hints[1].location.line, 14)
        self.assertTrue(herdr.hints[0].favorite)
        self.assertEqual(herdr.match.app_id_regex, ("^herdr$",))
        self.assertIsNone(herdr.parent_tags)
        claude = by_id["claude"]
        self.assertEqual(claude.priority, 10)
        self.assertEqual(claude.display.anchor, "bottom-right")
        self.assertEqual(claude.display.width, Size(50, "%"))
        self.assertIsNone(claude.display.height)
        self.assertEqual(claude.parent_tags, ("terminal", "ai"))
        self.assertEqual(claude.hints[0].kind, "command")
        self.assertEqual(claude.hints[1].copy_text(), "/model opus")
        self.assertEqual(claude.hints[0].copy_text(), "/compact")
        self.assertEqual(claude.hints[1].learned, "2026-09-16")

    def test_load_all_and_cli(self) -> None:
        self.assertTrue(load_all(GOOD).ok)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["validate", "--config-dir", str(GOOD)]), 0)


class SheetValidationTest(unittest.TestCase):
    def assert_issue(self, body: str, fragment: str, line: int | None = None) -> None:
        sheet, issues = _parse(body)
        self.assertIsNone(sheet)
        msgs = [str(i) for i in issues]
        hits = [i for i in issues if fragment in i.message]
        self.assertTrue(hits, f"{fragment!r} not in {msgs}")
        if line is not None:
            self.assertEqual(hits[0].line, line, msgs)

    def test_missing_required(self) -> None:
        self.assert_issue("title: X\nhints: []\n", "required field 'id'")
        self.assert_issue("id: x\nhints: []\n", "required field 'title'")
        self.assert_issue(
            """
            id: x
            title: X
            hints:
              - title: no id
            """,
            "hints[0]: required field 'id'",
            line=4,
        )

    def test_duplicate_hint_id(self) -> None:
        self.assert_issue(
            """
            id: x
            title: X
            hints:
              - {id: a, title: A}
              - {id: a, title: B}
            """,
            "duplicate hint id 'a'",
            line=5,
        )

    def test_invalid_regex_anchor_size_kind(self) -> None:
        self.assert_issue(
            "id: x\ntitle: X\nmatch:\n  wayfire:\n    app_id_regex: ['(']\n",
            "invalid regex",
            line=5,
        )
        self.assert_issue("id: x\ntitle: X\ndisplay:\n  anchor: middle\n", "invalid anchor", line=3)
        self.assert_issue("id: x\ntitle: X\ndisplay:\n  width: 3em\n", "invalid size")
        self.assert_issue(
            "id: x\ntitle: X\nhints:\n  - {id: a, title: A, kind: macro}\n", "kind must be one of"
        )

    def test_unknown_keys_and_version(self) -> None:
        self.assert_issue("id: x\ntitle: X\nfoo: 1\n", "unknown top-level key(s): foo")
        self.assert_issue("id: x\ntitle: X\nversion: 2\n", "version must be 1", line=3)
        self.assert_issue(
            "id: x\ntitle: X\nhints:\n  - {id: a, title: A, colour: red}\n",
            "unknown key(s): colour",
        )

    def test_syntax_error_has_line(self) -> None:
        data, issues = read_document_from_text("id: x\ntitle: [unclosed\n", "s.yaml")
        self.assertIsNone(data)
        self.assertEqual(len(issues), 1)
        self.assertIn("YAML syntax error", issues[0].message)
        self.assertIsNotNone(issues[0].line)


class ConfigValidationTest(unittest.TestCase):
    def check(self, text: str, fragment: str) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text(textwrap.dedent(text), encoding="utf-8")
            result = load_config(p)
        self.assertIsNone(result.config)
        self.assertTrue(any(fragment in i.message for i in result.issues), result.issues)

    def test_errors(self) -> None:
        self.check("overlay:\n  anchor: nowhere\n", "invalid anchor")
        self.check("overlay:\n  width: -5\n", "invalid size")
        self.check("overlay:\n  margin: {top: 1, inside: 2}\n", "unknown side")
        self.check("editor:\n  command: [ed, '{file}', '{col}']\n", "unknown placeholder")
        self.check("editor:\n  command: 'gvim {file}'\n", "list of strings")
        self.check("search:\n  max_results: 0\n", ">= 1")
        self.check("logging:\n  level: loud\n", "must be one of")
        self.check("bogus: {}\n", "unknown section")

    def test_margin_shorthand(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("overlay:\n  margin: 8\n", encoding="utf-8")
            cfg = load_config(p).config
        self.assertEqual(cfg.display.margin, Margin(8, 8, 8, 8))


class DuplicateSheetIdTest(unittest.TestCase):
    def test_reported_once_per_extra_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("a.yaml", "b.yaml"):
                (root / name).write_text("id: same\ntitle: T\n", encoding="utf-8")
            result = load_sheets(root)
        self.assertEqual(len(result.sheets), 2)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("duplicate sheet id 'same'", result.issues[0].message)
        self.assertEqual(result.issues[0].file.name, "b.yaml")


class SheetStoreTest(unittest.TestCase):
    def test_last_known_good(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            hints = Path(d)
            p = hints / "x.yaml"
            p.write_text("id: x\ntitle: X\nhints:\n  - {id: a, title: A}\n", encoding="utf-8")
            store = SheetStore(hints)
            store.load_all()
            self.assertEqual([s.id for s in store.sheets], ["x"])
            self.assertEqual(store.issues, [])

            p.write_text("id: x\ntitle: [broken\n", encoding="utf-8")
            self.assertFalse(store.reload(p))
            self.assertEqual([h.id for h in store.sheets[0].hints], ["a"])  # still the old one
            self.assertEqual(len(store.issues), 1)
            self.assertIn("YAML syntax error", store.issues[0].message)

            p.write_text("id: x\ntitle: X\nhints:\n  - {id: b, title: B}\n", encoding="utf-8")
            self.assertTrue(store.reload(p))
            self.assertEqual([h.id for h in store.sheets[0].hints], ["b"])
            self.assertEqual(store.issues, [])

            p.unlink()
            self.assertTrue(store.reload(p))
            self.assertEqual(store.sheets, [])

    def test_cli_exit_code_on_problems(self) -> None:
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()):
            root = Path(d)
            (root / "hints").mkdir()
            (root / "hints" / "bad.yaml").write_text("title: no id\n", encoding="utf-8")
            self.assertEqual(main(["validate", "--config-dir", str(root)]), 1)
            _, issues = load_sheet(root / "hints" / "bad.yaml")
            self.assertTrue(issues)
