import contextlib
import io
import tempfile
import textwrap
import unittest
from pathlib import Path

from wayhint.cli import main

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "skills" / "wayhint-add-sheet" / "assets" / "example-app.yaml"


class CheckSheetTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "config"
        self.hints = self.root / "hints"
        self.hints.mkdir(parents=True)
        self.drafts = Path(tmp.name) / "drafts"
        self.drafts.mkdir()

    def write(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["check-sheet", "--config-dir", str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_template_passes_strict(self) -> None:
        code, out, err = self.run_cli("--strict", str(TEMPLATE))
        self.assertEqual(code, 0, err)
        self.assertIn("check-sheet: ok (3 hint(s))", out)

    def test_loader_error_fails(self) -> None:
        path = self.write(self.drafts, "app.yaml", "id: other\ntitle: App\n")
        code, _out, err = self.run_cli(str(path))
        self.assertEqual(code, 1)
        self.assertIn("does not match the file name", err)

    def test_warnings_pass_unless_strict(self) -> None:
        path = self.write(
            self.drafts,
            "app.yaml",
            """
            id: app
            title: App
            match: {wayland: {app_id_regex: ["foo|"]}}
            hints:
              - {id: a, title: A, command: app --x}
            """,
        )
        code, out, err = self.run_cli(str(path))
        self.assertEqual(code, 0)
        self.assertIn("1 hint(s), 2 warning(s)", out)
        self.assertIn("matches the empty string", err)
        self.assertIn("change kind to 'command'", err)
        self.assertEqual(self.run_cli("--strict", str(path))[0], 1)

    def test_kind_advice(self) -> None:
        path = self.write(
            self.drafts,
            "app.yaml",
            """
            id: app
            title: App
            match: {process: {argv_regex: ["^app$"]}}
            hints:
              - {id: bare, title: Bare}
              - {id: cmd, title: Cmd, kind: command, key: Ctrl+K}
              - {id: tip, title: Tip, kind: tip, key: "!", copy: "! "}
              - {id: note, title: Note, kind: note}
            """,
        )
        _code, _out, err = self.run_cli(str(path))
        self.assertIn("'bare': kind 'shortcut' has neither key nor command", err)
        self.assertIn("'cmd': kind 'command' has a key but no command", err)
        self.assertNotIn("hint 'tip'", err)
        self.assertNotIn("hint 'note'", err)

    def test_unreachable_unless_included(self) -> None:
        path = self.write(self.drafts, "lib.yaml", "id: lib\ntitle: Lib\n")
        _code, _out, err = self.run_cli(str(path))
        self.assertIn("never shown", err)
        self.write(self.hints, "app.yaml", "id: app\ntitle: App\ninclude: [lib]\n")
        code, _out, err = self.run_cli("--strict", str(path))
        self.assertEqual(code, 0, err)

    def test_include_and_id_are_checked_against_installed_sheets(self) -> None:
        self.write(self.hints, "app.yaml", "id: app\ntitle: Installed\n")
        draft = self.write(
            self.drafts,
            "app.yaml",
            "id: app\ntitle: Draft\nmatch: {process: {argv_regex: ['^app$']}}\ninclude: [nope]\n",
        )
        _code, _out, err = self.run_cli(str(draft))
        self.assertIn("already installed", err)
        self.assertIn("no sheet with id 'nope'", err)

    def test_installed_sheet_is_not_its_own_duplicate(self) -> None:
        path = self.write(
            self.hints, "app.yaml", "id: app\ntitle: App\nmatch: {process: {argv_regex: [x]}}\n"
        )
        code, _out, err = self.run_cli("--strict", str(path))
        self.assertEqual(code, 0, err)

    def test_every_path_is_checked(self) -> None:
        bad = self.write(self.drafts, "bad.yaml", "id: bad\n")
        code, out, _err = self.run_cli(str(bad), str(TEMPLATE))
        self.assertEqual(code, 1)
        self.assertIn("ok (3 hint(s))", out)


if __name__ == "__main__":
    unittest.main()
