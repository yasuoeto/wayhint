import contextlib
import io
import shutil
import tempfile
import textwrap
import unittest
from collections.abc import Sequence
from pathlib import Path

from wayhint.cli import main
from wayhint.models import Margin, Size
from wayhint.yaml_store import (
    LoadResult,
    SheetStore,
    hints_dir,
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


class InvalidEncodingTest(unittest.TestCase):
    """A file that is not UTF-8 is a normal problem report, not an exception (DESIGN §11)."""

    BAD = b"id: broken\ntitle: caf\xe9\n"  # latin-1, written by hand or by another tool

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="wayhint-encoding-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.hints = self.dir / "hints"
        self.hints.mkdir()
        self.sheet = self.hints / "s.yaml"
        self.sheet.write_text("id: s\ntitle: S\nhints:\n  - {id: a, title: A}\n")

    def test_read_document_reports_it_instead_of_raising(self) -> None:
        self.sheet.write_bytes(self.BAD)
        data, issues = read_document(self.sheet)
        self.assertIsNone(data)
        self.assertEqual(len(issues), 1)
        self.assertIn("utf-8", str(issues[0]).lower())

    def test_the_store_keeps_the_last_good_sheet(self) -> None:
        store = SheetStore(self.hints)
        store.load_all()
        self.sheet.write_bytes(self.BAD)
        self.assertFalse(store.reload(self.sheet))
        self.assertEqual([s.id for s in store.sheets], ["s"])
        self.assertTrue(store.issues)

    def test_load_config_reports_it(self) -> None:
        config = self.dir / "config.yaml"
        config.write_bytes(self.BAD)
        result = load_config(config)
        self.assertIsNone(result.config)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("utf-8", str(result.issues[0]).lower())


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
        self.assertEqual(set(by_id), {"herdr", "claude", "wm"})
        self.assertEqual(by_id["claude"].include, ("wm",))
        self.assertEqual([s.id for s in result.includes_for(by_id["claude"])], ["wm"])
        self.assertTrue(by_id["wm"].match.is_empty(), "an included-only sheet has no match")
        self.assertIsNone(by_id["herdr"].include, "no include means: use the global default")
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
            "id: x\ntitle: X\nmatch:\n  wayland:\n    app_id_regex: ['(']\n",
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

    def test_unknown_keys_inside_match_and_display(self) -> None:
        # DESIGN §Data model / DECISIONS 0002 (d): an unknown key is an error wherever it sits,
        # so a typo cannot quietly do nothing.
        self.assert_issue(
            "id: x\ntitle: X\nmatch:\n  process:\n    argv_rgex: ['^a$']\n",
            "match.process: unknown key(s): argv_rgex",
        )
        self.assert_issue(
            "id: x\ntitle: X\nmatch:\n  wayland:\n    app_id_rgex: ['^a$']\n",
            "match.wayland: unknown key(s): app_id_rgex",
        )
        self.assert_issue("id: x\ntitle: X\ndisplay:\n  widht: 10\n", "unknown key(s): widht")
        self.assert_issue("id: x\ntitle: X\nversion: 2\n", "version must be 1", line=3)
        self.assert_issue(
            "id: x\ntitle: X\nhints:\n  - {id: a, title: A, colour: red}\n",
            "unknown key(s): colour",
        )

    def test_nested_export_tags(self) -> None:
        """DECISIONS 0034: a parent sheet names what it hands down; unwritten is ``None``."""
        base = "id: x\ntitle: X\n"
        self.assertEqual(_parse(base + "nested: {export_tags: [pane]}\n")[0].export_tags, ("pane",))
        self.assertEqual(_parse(base + "nested: {export_tags: []}\n")[0].export_tags, ())
        self.assertIsNone(_parse(base)[0].export_tags)
        self.assertIsNone(_parse(base + "nested: {}\n")[0].export_tags)
        self.assert_issue(base + "nested: {foo: 1}\n", "nested: unknown key(s): foo")
        self.assert_issue(base + "nested: [pane]\n", "nested must be a mapping")
        self.assert_issue(base + "nested: {export_tags: pane}\n", "must be a list of strings")

    def test_syntax_error_has_line(self) -> None:
        data, issues = read_document_from_text("id: x\ntitle: [unclosed\n", "s.yaml")
        self.assertIsNone(data)
        self.assertEqual(len(issues), 1)
        self.assertIn("YAML syntax error", issues[0].message)
        self.assertIsNotNone(issues[0].line)


class ConfigParentTagsTest(unittest.TestCase):
    """``nested.parent_tags``: unwritten is ``None`` (the parent decides), ``[]`` is empty."""

    def test_unwritten_empty_and_null(self) -> None:
        from wayhint.config import parse_global_config

        self.assertIsNone(parse_global_config({}).parent_tags)
        self.assertIsNone(parse_global_config({"nested": {}}).parent_tags)
        self.assertIsNone(parse_global_config({"nested": {"parent_tags": None}}).parent_tags)
        self.assertEqual(parse_global_config({"nested": {"parent_tags": []}}).parent_tags, ())
        self.assertEqual(
            parse_global_config({"nested": {"parent_tags": ["pane"]}}).parent_tags, ("pane",)
        )


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

    def test_unknown_key_inside_a_section(self) -> None:
        # "未知の section / key は error" (DESIGN §Config): the section is only half of it.
        for text, fragment in (
            ("overlay:\n  widht: 10\n", "overlay: unknown key(s): widht"),
            ("appearance:\n  colour: dark\n", "appearance: unknown key(s): colour"),
            ("editor:\n  commnad: [ed]\n", "editor: unknown key(s): commnad"),
            ("nested:\n  parent_tag: [a]\n", "nested: unknown key(s): parent_tag"),
            ("context:\n  backends: auto\n", "context: unknown key(s): backends"),
            ("search:\n  max_result: 5\n", "search: unknown key(s): max_result"),
            ("logging:\n  levle: info\n", "logging: unknown key(s): levle"),
        ):
            with self.subTest(text=text):
                self.check(text, fragment)

    def test_margin_shorthand(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            p.write_text("overlay:\n  margin: 8\n", encoding="utf-8")
            cfg = load_config(p).config
        self.assertEqual(cfg.display.margin, Margin(8, 8, 8, 8))


class IncludeTest(unittest.TestCase):
    """``include`` names other sheets; unresolved names are a warning, not a rejection (0026)."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="wayhint-include-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name: str, body: str) -> Path:
        path = self.dir / f"{name}.yaml"
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        return path

    def load(self, include: Sequence[str] = ()) -> LoadResult:
        self.write("wm", "id: wm\ntitle: WM\nhints:\n  - {id: close, title: Close}\n")
        return load_sheets(self.dir, global_include=include)

    def test_a_sheet_lists_the_sheets_it_mixes_in(self) -> None:
        self.write("a", "id: a\ntitle: A\ninclude: [wm]\nhints:\n  - {id: x, title: X}\n")
        result = self.load()
        sheet = next(s for s in result.sheets if s.id == "a")
        self.assertEqual(sheet.include, ("wm",))
        self.assertEqual([s.id for s in result.includes_for(sheet)], ["wm"])
        self.assertEqual(result.issues, [])

    def test_the_global_default_applies_to_a_sheet_without_include(self) -> None:
        self.write("a", "id: a\ntitle: A\nhints:\n  - {id: x, title: X}\n")
        result = self.load(include=["wm"])
        sheet = next(s for s in result.sheets if s.id == "a")
        self.assertEqual([s.id for s in result.includes_for(sheet)], ["wm"])

    def test_a_sheet_with_include_replaces_the_global_default(self) -> None:
        self.write("a", "id: a\ntitle: A\ninclude: []\nhints:\n  - {id: x, title: X}\n")
        result = self.load(include=["wm"])
        sheet = next(s for s in result.sheets if s.id == "a")
        self.assertEqual(result.includes_for(sheet), [])

    def test_an_unknown_name_is_a_warning_and_the_sheet_still_loads(self) -> None:
        self.write("a", "id: a\ntitle: A\ninclude: [wm, nope]\nhints:\n  - {id: x, title: X}\n")
        result = self.load()
        sheet = next(s for s in result.sheets if s.id == "a")
        self.assertEqual([s.id for s in result.includes_for(sheet)], ["wm"])
        self.assertEqual([i.severity for i in result.issues], ["warning"])
        self.assertIn("nope", result.issues[0].message)

    def test_the_global_default_does_not_make_a_sheet_include_itself(self) -> None:
        # ``include: [wm]`` in config.yaml names every sheet, wm included; that is not a mistake
        # the user made, so it is dropped quietly.
        result = self.load(include=["wm"])
        wm = next(s for s in result.sheets if s.id == "wm")
        self.assertEqual(result.includes_for(wm), [])
        self.assertEqual(result.issues, [])

    def test_including_itself_is_a_warning_and_is_dropped(self) -> None:
        self.write("a", "id: a\ntitle: A\ninclude: [a]\nhints:\n  - {id: x, title: X}\n")
        result = self.load()
        sheet = next(s for s in result.sheets if s.id == "a")
        self.assertEqual(result.includes_for(sheet), [])
        self.assertEqual([i.severity for i in result.issues], ["warning"])

    def test_a_second_level_of_include_is_not_followed(self) -> None:
        self.write("a", "id: a\ntitle: A\ninclude: [b]\nhints:\n  - {id: x, title: X}\n")
        self.write("b", "id: b\ntitle: B\ninclude: [wm]\nhints:\n  - {id: y, title: Y}\n")
        result = self.load()
        sheet = next(s for s in result.sheets if s.id == "a")
        self.assertEqual([s.id for s in result.includes_for(sheet)], ["b"])

    def test_include_must_be_a_list_of_sheet_ids(self) -> None:
        self.write("a", "id: a\ntitle: A\ninclude: wm\n")
        self.assertTrue(any("include" in i.message for i in load_sheets(self.dir).issues))
        self.write("a", "id: a\ntitle: A\ninclude: ['not an id!']\n")
        self.assertTrue(any("include" in i.message for i in load_sheets(self.dir).issues))


class HintsDirTest(unittest.TestCase):
    """One language, one directory: the sheets follow the language the UI is in (0024)."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="wayhint-hintsdir-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "hints").mkdir()

    def make(self, *names: str) -> None:
        for name in names:
            (self.root / "hints" / name).mkdir()

    def test_the_language_directory_wins(self) -> None:
        self.make("en", "ja")
        self.assertEqual(hints_dir(self.root, "ja"), self.root / "hints" / "ja")
        self.assertEqual(hints_dir(self.root, "en"), self.root / "hints" / "en")

    def test_english_is_the_fallback_for_a_language_without_a_directory(self) -> None:
        self.make("en")
        self.assertEqual(hints_dir(self.root, "ja"), self.root / "hints" / "en")

    def test_without_any_language_directory_the_flat_layout_is_used(self) -> None:
        self.assertEqual(hints_dir(self.root, "ja"), self.root / "hints")

    def test_auto_follows_the_locale_like_the_interface_does(self) -> None:
        self.make("en", "ja")
        self.assertEqual(
            hints_dir(self.root, "auto", environ={"LANG": "ja_JP.UTF-8"}),
            self.root / "hints" / "ja",
        )
        self.assertEqual(
            hints_dir(self.root, "auto", environ={"LANG": "C"}), self.root / "hints" / "en"
        )
        self.assertEqual(hints_dir(self.root, "auto", environ={}), self.root / "hints" / "en")

    def test_a_directory_that_is_not_a_language_is_never_picked(self) -> None:
        self.make("en", "old")
        self.assertEqual(
            hints_dir(self.root, "auto", environ={"LANG": "old_OLD.UTF-8"}),
            self.root / "hints" / "en",
        )

    def test_an_empty_language_directory_is_still_the_one_in_use(self) -> None:
        # Making the directory is the statement "sheets live here"; falling back to another
        # language would quietly mix languages while a translation is being written.
        self.make("en", "ja")
        (self.root / "hints" / "en" / "x.yaml").write_text("id: x\ntitle: X\n")
        self.assertEqual(load_sheets(hints_dir(self.root, "ja")).sheets, [])


class SheetFileNameTest(unittest.TestCase):
    """``id`` has to be the file name (DECISIONS 0020): a copy is not a second sheet."""

    def load(self, d: str, name: str, sheet_id: str):
        root = Path(d)
        (root / name).write_text(f"id: {sheet_id}\ntitle: T\n", encoding="utf-8")
        return load_sheets(root)

    def test_a_sheet_whose_id_is_not_its_file_name_is_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self.load(d, "claude-backup.yaml", "claude")
        self.assertEqual(result.sheets, [])
        self.assertEqual(len(result.issues), 1)
        self.assertIn("claude-backup", result.issues[0].message)
        self.assertIn("claude", result.issues[0].message)

    def test_a_matching_name_loads(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self.load(d, "claude.yaml", "claude")
        self.assertEqual([s.id for s in result.sheets], ["claude"])
        self.assertEqual(result.issues, [])

    def test_the_extension_is_not_part_of_the_name(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self.load(d, "claude.yml", "claude")
        self.assertEqual([s.id for s in result.sheets], ["claude"])

    def test_the_store_keeps_it_out_too(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.yaml").write_text("id: a\ntitle: A\n", encoding="utf-8")
            (root / "a-copy.yaml").write_text("id: a\ntitle: A\n", encoding="utf-8")
            store = SheetStore(root)
            store.load_all()
            self.assertEqual([s.path.name for s in store.sheets], ["a.yaml"])
            self.assertEqual(len(store.issues), 1)


class DuplicateSheetIdTest(unittest.TestCase):
    """``a.yaml`` and ``a.yml`` both pass the file-name rule and still collide."""

    def duplicates(self, d: str) -> Path:
        root = Path(d)
        for name in ("same.yml", "same.yaml"):
            (root / name).write_text("id: same\ntitle: T\n", encoding="utf-8")
        return root

    def test_the_first_file_in_name_order_is_the_one_that_is_used(self) -> None:
        # Never pick at random (設計書 §59): files are read in name order, so the first one wins.
        with tempfile.TemporaryDirectory() as d:
            result = load_sheets(self.duplicates(d))
        self.assertEqual([s.path.name for s in result.sheets], ["same.yaml"])

    def test_the_file_that_is_left_out_says_which_one_won(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = load_sheets(self.duplicates(d))
        self.assertEqual([i.file.name for i in result.issues], ["same.yml"])
        self.assertIn("duplicate sheet id 'same'", result.issues[0].message)
        self.assertIn("same.yaml", result.issues[0].message)  # both names, so the pair is obvious

    def test_the_store_leaves_the_duplicate_out_as_well(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = SheetStore(self.duplicates(d))
            store.load_all()
            self.assertEqual([s.path.name for s in store.sheets], ["same.yaml"])
            self.assertEqual(len(store.issues), 1)


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

    def test_loading_everything_again_forgets_a_file_that_is_gone(self) -> None:
        # An explicit reload is the way out when a delete event was missed, so what the store
        # holds afterwards has to be what the directory holds.
        with tempfile.TemporaryDirectory() as d:
            hints = Path(d)
            for name in ("a", "b"):
                (hints / f"{name}.yaml").write_text(f"id: {name}\ntitle: {name}\n")
            store = SheetStore(hints)
            store.load_all()
            self.assertEqual([s.id for s in store.sheets], ["a", "b"])
            (hints / "b.yaml").unlink()  # removed while the monitor was not looking
            store.load_all()
            self.assertEqual([s.id for s in store.sheets], ["a"])

    def test_loading_everything_again_forgets_the_issues_of_a_file_that_is_gone(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            hints = Path(d)
            bad = hints / "bad.yaml"
            bad.write_text("title: no id\n")
            store = SheetStore(hints)
            store.load_all()
            self.assertTrue(store.issues)
            bad.unlink()
            store.load_all()
            self.assertEqual(store.issues, [])

    def test_cli_exit_code_on_problems(self) -> None:
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()):
            root = Path(d)
            (root / "hints").mkdir()
            (root / "hints" / "bad.yaml").write_text("title: no id\n", encoding="utf-8")
            self.assertEqual(main(["validate", "--config-dir", str(root)]), 1)
            _, issues = load_sheet(root / "hints" / "bad.yaml")
            self.assertTrue(issues)
