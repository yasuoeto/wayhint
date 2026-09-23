"""Phase 7a: writing sheets back. See docs/DESIGN.md "編集モード (Phase 7)" §4 and §13.

Everything here is headless: a tmp directory and an injected clock, no GTK and no compositor.
"""

import datetime as dt
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema
import jsonschema.validators

from wayhint import yaml_store
from wayhint.config import EditorConfig, GlobalConfig
from wayhint.matcher import match_app
from wayhint.models import (
    DisplayConfig,
    HintSheet,
    MatchRule,
    ProcessInfo,
    ResolvedContext,
)
from wayhint.schema import json_schema
from wayhint.yaml_store import (
    CANONICAL_HINT_KEYS,
    GENERIC_PROCESS_WARNING,
    HintNotFoundError,
    SheetWriteError,
    append_hint,
    build_hint,
    create_sheet,
    delete_hint,
    match_rule_for_context,
    normalize_sheet,
    parse_sheet,
    read_document,
    set_favorite,
    set_overlay_size,
    slug,
    swap_hints,
    update_hint,
    write_config,
    write_document,
)

REPO = Path(__file__).resolve().parent.parent
DIRTY = REPO / "tests" / "fixtures" / "dirty"
NOW = dt.datetime(2026, 9, 18, 21, 5, 30)


def sheet_paths() -> list[Path]:
    """Every hint sheet the repository owns, plus the deliberately messy fixture."""
    return sorted(
        [
            *(REPO / "examples" / "hints").rglob("*.yaml"),  # one directory per language
            *(REPO / "tests" / "fixtures" / "good" / "hints").glob("*.yaml"),
            *DIRTY.glob("*.yaml"),
        ]
    )


class TmpSheetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="wayhint-write-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def copy(self, source: Path) -> Path:
        target = self.dir / source.name
        shutil.copy(source, target)
        return target

    def doc(self, path: Path):
        data, issues = read_document(path)
        self.assertEqual(issues, [])
        return data


class GoldenRoundTripTest(TmpSheetTest):
    """load → write_document must not move a single byte in a sheet nobody edited."""

    def test_every_sheet_in_the_repository(self) -> None:
        paths = sheet_paths()
        self.assertGreaterEqual(len(paths), 4, "fixtures went missing")
        for source in paths:
            with self.subTest(sheet=source.name):
                target = self.copy(source)
                write_document(target, self.doc(target))
                self.assertEqual(target.read_bytes(), source.read_bytes())

    @unittest.skipUnless(
        os.environ.get("WAYHINT_GOLDEN_EXTRA_DIR"),
        "WAYHINT_GOLDEN_EXTRA_DIR is not set (the machine's own sheets; never set in CI)",
    )
    def test_extra_directory(self) -> None:
        extra = Path(os.environ["WAYHINT_GOLDEN_EXTRA_DIR"]).expanduser()
        found = sorted(extra.glob("*.yaml"))
        self.assertTrue(found, f"no sheets in {extra}")
        for source in found:
            with self.subTest(sheet=source.name):
                target = self.copy(source)
                write_document(target, self.doc(target))
                self.assertEqual(target.read_bytes(), source.read_bytes())


class WriteDocumentTest(TmpSheetTest):
    def test_keeps_the_mode_of_an_existing_sheet(self) -> None:
        target = self.copy(DIRTY / "messy.yaml")
        os.chmod(target, 0o640)
        write_document(target, self.doc(target))
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_new_sheet_follows_the_umask(self) -> None:
        source = self.copy(DIRTY / "messy.yaml")
        doc = self.doc(source)
        target = self.dir / "new.yaml"
        write_document(target, doc)
        umask = os.umask(0)
        os.umask(umask)
        self.assertEqual(target.stat().st_mode & 0o777, 0o666 & ~umask)

    def test_invalid_document_leaves_the_original_and_no_tmp(self) -> None:
        target = self.copy(DIRTY / "messy.yaml")
        before = target.read_bytes()
        doc = self.doc(target)
        doc["priority"] = "not an integer"
        with self.assertRaises(SheetWriteError) as caught:
            write_document(target, doc)
        self.assertTrue(caught.exception.issues)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["messy.yaml"])

    def test_tmp_is_not_a_sheet_name(self) -> None:
        # hints/ is watched as a directory: a *.yaml tmp would be loaded as a real sheet.
        target = self.copy(DIRTY / "messy.yaml")
        doc = self.doc(target)
        before = target.read_bytes()
        replace = os.replace
        observed = []

        def inspect_then_replace(source, destination):
            temporary = Path(source)
            self.assertTrue(temporary.is_file())
            self.assertNotIn(temporary.suffix, (".yaml", ".yml"))
            self.assertEqual(temporary.parent, target.parent)
            observed.append(temporary)
            return replace(source, destination)

        with mock.patch.object(yaml_store.os, "replace", side_effect=inspect_then_replace):
            write_document(target, doc)
        self.assertTrue(observed, "inspect the temporary before it disappears")
        self.assertEqual(target.read_bytes(), before)

    def test_missing_directory_is_not_created(self) -> None:
        with self.assertRaises(SheetWriteError):
            write_document(self.dir / "nope" / "s.yaml", {"id": "x", "title": "X"})
        self.assertFalse((self.dir / "nope").exists())


class ConcurrentWriteTest(TmpSheetTest):
    """Two writers on one file: the GUI and the CLI, or two CLI calls (DESIGN §4)."""

    def interleave(self, target: Path, outer: object, inner: object) -> None:
        """Run a whole second write in the middle of the first one's dump."""
        real = yaml_store._yaml

        def hooked() -> object:
            y = real()
            dump = y.dump

            def dump_then_interleave(doc: object, fh: object) -> None:
                dump(doc, fh)
                if doc is outer:  # the nested write must not recurse
                    write_document(target, inner)

            y.dump = dump_then_interleave
            return y

        with mock.patch.object(yaml_store, "_yaml", hooked):
            write_document(target, outer)

    def test_a_writer_mid_flight_does_not_lose_the_write_that_finishes_last(self) -> None:
        target = self.copy(DIRTY / "messy.yaml")
        outer = self.doc(target)
        outer["title"] = "outer"
        inner = self.doc(target)
        inner["title"] = "inner"
        self.interleave(target, outer, inner)
        self.assertEqual(self.doc(target)["title"], "outer")

    def test_neither_writer_leaves_a_temporary_behind(self) -> None:
        target = self.copy(DIRTY / "messy.yaml")
        outer = self.doc(target)
        inner = self.doc(target)
        inner["title"] = "inner"
        self.interleave(target, outer, inner)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["messy.yaml"])


class OverlaySizeTest(TmpSheetTest):
    """The hand-resized overlay writes its size back to config.yaml (DECISIONS 0018)."""

    CONFIG = """# 手書きのコメント
overlay:
  anchor: top-right   # 行末コメント
  width: 420px
  height: 60%
editor:
  command: [gvim, "{file}"]
"""

    def config(self, text: str = CONFIG) -> Path:
        path = self.dir / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_size_is_written_in_px_and_comments_survive(self) -> None:
        path = self.config()
        write_config(path, set_overlay_size(self.doc(path), 500, 640))
        text = path.read_text(encoding="utf-8")
        self.assertIn("width: 500px", text)
        self.assertIn("height: 640px", text)
        self.assertIn("# 手書きのコメント", text)
        self.assertIn("anchor: top-right   # 行末コメント", text)
        self.assertIn('command: [gvim, "{file}"]', text)

    def test_no_config_file_yet(self) -> None:
        path = self.dir / "config.yaml"
        write_config(path, set_overlay_size(None, 500, 640))
        self.assertEqual(
            path.read_text(encoding="utf-8"), "overlay:\n  width: 500px\n  height: 640px\n"
        )

    def test_a_config_that_would_not_load_is_not_written(self) -> None:
        path = self.config("overlay:\n  anchor: nowhere\n")
        with self.assertRaises(SheetWriteError):
            write_config(path, set_overlay_size(self.doc(path), 500, 640))
        self.assertEqual(path.read_text(encoding="utf-8"), "overlay:\n  anchor: nowhere\n")
        self.assertFalse(list(self.dir.glob("*.tmp")))


class BuildHintTest(unittest.TestCase):
    def test_canonical_order_and_null_spelling(self) -> None:
        hint = build_hint({"id": "h", "title": "T", "key": "Ctrl-a", "category": "  "})
        self.assertEqual(list(hint), list(CANONICAL_HINT_KEYS))
        self.assertIsNone(hint["remark"])
        self.assertIsNone(hint["category"], "a blank form field is unset, not an empty string")
        self.assertEqual(hint["kind"], "shortcut")
        self.assertIs(hint["favorite"], False)

    def test_tags_stay_flow_style(self) -> None:
        hint = build_hint({"id": "h", "title": "T", "tags": ["terminal"]})
        self.assertTrue(hint["tags"].fa.flow_style())

    def test_unknown_field_is_a_programming_error(self) -> None:
        with self.assertRaises(ValueError):
            build_hint({"id": "h", "title": "T", "colour": "red"})


class HintOpsTest(TmpSheetTest):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.copy(DIRTY / "messy.yaml")
        self.document = self.doc(self.path)

    def text_after_write(self) -> str:
        write_document(self.path, self.document)
        return self.path.read_text()

    def test_append_and_update_touch_only_their_own_hint(self) -> None:
        append_hint(self.document, build_hint({"id": "fourth", "title": "Fourth"}))
        update_hint(self.document, "second", {"title": "Second renamed"})
        text = self.text_after_write()
        self.assertIn("title: Second renamed", text)
        self.assertIn("command: /second", text, "other fields of that hint survive")
        self.assertIn("key: Ctrl-a   # 行末コメント", text, "other hints are untouched")
        self.assertIn("id: fourth", text)

    def test_update_keeps_canonical_order(self) -> None:
        update_hint(self.document, "second", {"remark": "note"})
        hints = self.document["hints"]
        self.assertEqual(list(hints[1]), list(CANONICAL_HINT_KEYS))

    def test_set_favorite(self) -> None:
        set_favorite(self.document, "first", True)
        self.assertIn("favorite: true", self.text_after_write())

    def test_delete_takes_the_comment_above_and_leaves_the_one_below(self) -> None:
        removed = delete_hint(self.document, "second")
        self.assertEqual(removed["id"], "second")
        text = self.text_after_write()
        self.assertNotIn("# second の直前コメント", text)
        self.assertIn("# ファイル末尾のコメント", text)
        self.assertIn("# first の直前コメント", text)

    def test_swap_moves_the_comment_with_the_hint(self) -> None:
        swap_hints(self.document, "second", "third")
        text = self.text_after_write()
        third = text.index("id: third")
        second = text.index("id: second")
        comment = text.index("# second の直前コメント")
        self.assertLess(third, second, "third moved up")
        self.assertLess(comment, second, "its own comment followed 'second' down")
        self.assertLess(third, comment)

    def test_missing_id(self) -> None:
        for call in (
            lambda: update_hint(self.document, "nope", {"title": "x"}),
            lambda: delete_hint(self.document, "nope"),
            lambda: swap_hints(self.document, "first", "nope"),
            lambda: set_favorite(self.document, "nope", True),
        ):
            with self.assertRaises(HintNotFoundError):
                call()


class NormalizeTest(TmpSheetTest):
    def test_idempotent_and_parse_preserving(self) -> None:
        path = self.copy(DIRTY / "messy.yaml")
        before_sheet, issues = parse_sheet(self.doc(path), path)
        self.assertEqual(issues, [])

        doc = self.doc(path)
        normalize_sheet(doc)
        write_document(path, doc)
        once = path.read_bytes()

        doc = self.doc(path)
        normalize_sheet(doc)
        write_document(path, doc)
        self.assertEqual(path.read_bytes(), once, "format is idempotent")

        after_sheet, issues = parse_sheet(self.doc(path), path)
        self.assertEqual(issues, [])
        self.assertEqual(
            [(h.id, h.title, h.key, h.command, h.tags, h.favorite) for h in before_sheet.hints],
            [(h.id, h.title, h.key, h.command, h.tags, h.favorite) for h in after_sheet.hints],
        )
        self.assertIn("# first の直前コメント", path.read_text(), "comments survive format")

    def test_modeline_is_added_once(self) -> None:
        path = self.copy(REPO / "examples" / "hints" / "en" / "herdr.yaml")
        doc = self.doc(path)
        normalize_sheet(doc, "/home/u/.config/wayhint/schema.json")
        write_document(path, doc)
        text = path.read_text()
        self.assertTrue(
            text.startswith("# yaml-language-server: $schema=/home/u/.config/wayhint/schema.json")
        )

        doc = self.doc(path)
        normalize_sheet(doc, "/home/u/.config/wayhint/schema.json")
        write_document(path, doc)
        self.assertEqual(path.read_text().count("yaml-language-server"), 1)

    def test_unknown_key_is_refused_rather_than_dropped(self) -> None:
        path = self.dir / "odd.yaml"
        path.write_text("id: odd\ntitle: Odd\nhints:\n  - id: a\n    title: A\n    colour: red\n")
        with self.assertRaises(SheetWriteError):
            normalize_sheet(self.doc(path))


def ctx(**kw) -> ResolvedContext:
    return ResolvedContext(**kw)


def proc(name: str, argv: tuple[str, ...]) -> ProcessInfo:
    return ProcessInfo(pid=1, name=name, argv=argv, cmdline=" ".join(argv))


class CreateSheetTest(TmpSheetTest):
    def config(self, **kw) -> GlobalConfig:
        return GlobalConfig(editor=EditorConfig(**kw))

    def test_app_id_context(self) -> None:
        path, doc = create_sheet(
            ctx(desktop_app="org.inkscape.Inkscape"),
            build_hint({"id": "h", "title": "T"}),
            self.config(),
            hints_dir=self.dir,
            now=NOW,
        )
        self.assertEqual(path, self.dir / "org.inkscape.inkscape.yaml")
        self.assertEqual(doc["match"]["wayland"]["app_id_regex"], ["^org\\.inkscape\\.Inkscape$"])
        write_document(path, doc)
        self.assertIn("generated by wayhint 2026-09-18 21:05", path.read_text())

    def test_process_context(self) -> None:
        path, doc = create_sheet(
            ctx(desktop_app="foot", parent_context="herdr", foreground_process=proc("claude", ())),
            build_hint({"id": "h", "title": "T"}),
            self.config(),
            hints_dir=self.dir,
            now=NOW,
        )
        self.assertEqual(path.name, "claude.yaml")
        self.assertEqual(doc["match"]["process"]["argv_regex"], ["^claude$"])

    def test_process_context_without_a_parent_sheet(self) -> None:
        """A terminal with no sheet of its own still generates a sheet for what runs in it.

        ``ProcAdapter`` reaches this: ``foot`` rarely has hints, so there is no parent, and a
        rule built from its ``app_id`` would match every command ever run in it (0027).
        """
        path, doc = create_sheet(
            ctx(desktop_app="foot", foreground_process=proc("vi", ("vi", "notes.txt"))),
            build_hint({"id": "h", "title": "T"}),
            self.config(),
            hints_dir=self.dir,
            now=NOW,
        )
        self.assertEqual(path.name, "vi.yaml")
        self.assertEqual(doc["match"]["process"]["argv_regex"], ["^vi$"])
        self.assertNotIn("wayland", doc["match"])

    def test_the_window_pid_suffix_is_not_part_of_the_generated_rule(self) -> None:
        """A rule from ``foot.p12345`` would match that window and nothing ever again (0027)."""
        path, doc = create_sheet(
            ctx(desktop_app="foot.p12345"),
            build_hint({"id": "h", "title": "T"}),
            self.config(),
            hints_dir=self.dir,
            now=NOW,
        )
        self.assertEqual(path.name, "foot.yaml")
        self.assertEqual(doc["match"]["wayland"]["app_id_regex"], ["^foot$"])

        # Round trip: the sheet this produced has to match the next window of that terminal, which
        # carries a different pid in its app_id.
        generated = HintSheet(
            id="foot",
            title="foot",
            path=path,
            priority=0,
            match=MatchRule(app_id_regex=tuple(doc["match"]["wayland"]["app_id_regex"])),
            display=DisplayConfig(),
            hints=(),
        )
        self.assertIs(match_app([generated], "foot.p999"), generated)
        self.assertIs(match_app([generated], "foot"), generated)

    def test_generic_process_name_uses_the_arguments(self) -> None:
        context = ctx(
            desktop_app="foot",
            parent_context="herdr",
            foreground_process=proc("node", ("node", "/path/to/codex", "--flag")),
        )
        match, warning = match_rule_for_context(context)
        self.assertEqual(match["process"]["argv_regex"], ["^codex$"])
        self.assertIsNone(warning)

    def test_generic_process_name_without_a_candidate_warns(self) -> None:
        context = ctx(
            desktop_app="foot",
            parent_context="herdr",
            foreground_process=proc("bash", ("bash", "-l")),
        )
        match, warning = match_rule_for_context(context)
        self.assertEqual(match["process"]["argv_regex"], ["^bash$"])
        self.assertEqual(warning, GENERIC_PROCESS_WARNING)

    def test_modeline_when_configured(self) -> None:
        path, doc = create_sheet(
            ctx(desktop_app="foot"),
            build_hint({"id": "h", "title": "T"}),
            self.config(schema_modeline=True, schema_path=Path("/tmp/wayhint-schema.json")),
            hints_dir=self.dir,
            now=NOW,
        )
        write_document(path, doc)
        self.assertTrue(
            path.read_text().startswith(
                "# yaml-language-server: $schema=/tmp/wayhint-schema.json\n"
            )
        )

    def test_id_collision(self) -> None:
        path, _doc = create_sheet(
            ctx(desktop_app="foot"),
            build_hint({"id": "h", "title": "T"}),
            self.config(),
            hints_dir=self.dir,
            existing_ids=("foot", "foot-2"),
            now=NOW,
        )
        self.assertEqual(path.name, "foot-3.yaml")


class SlugTest(unittest.TestCase):
    ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

    def test_from_a_title(self) -> None:
        self.assertEqual(slug("Compact the conversation"), "compact-the-conversation")
        self.assertEqual(slug("  /model switch!  "), "model-switch")

    def test_collisions(self) -> None:
        self.assertEqual(slug("New pane", ("new-pane",)), "new-pane-2")
        self.assertEqual(slug("New pane", ("new-pane", "new-pane-2")), "new-pane-3")

    def test_japanese_falls_back_to_a_timestamp(self) -> None:
        self.assertEqual(slug("新しいペイン", (), NOW), "q-20260918-210530")

    def test_always_matches_the_id_pattern(self) -> None:
        for title in ("Ctrl+Shift+N", "★ favourite", "---", "日本語", "9 lives", ".hidden"):
            with self.subTest(title=title):
                self.assertRegex(slug(title, (), NOW), self.ID_RE)


class SchemaTest(unittest.TestCase):
    """One direction only: what validation accepts, the schema accepts (docs/DESIGN.md §13)."""

    def plain(self, value):
        if isinstance(value, dict):
            return {str(k): self.plain(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.plain(v) for v in value]
        if isinstance(value, (dt.date, dt.datetime)):
            return value.isoformat()
        return value

    def validator(self):
        schema = json_schema()
        cls = jsonschema.validators.validator_for(schema)
        cls.check_schema(schema)  # the schema itself must be a valid draft 2020-12 document
        return cls(schema, format_checker=cls.FORMAT_CHECKER)

    def test_valid_sheets_pass_the_schema(self) -> None:
        validator = self.validator()
        for path in sheet_paths():
            with self.subTest(sheet=path.name):
                data, issues = read_document(path)
                self.assertEqual(issues, [])
                _sheet, issues = parse_sheet(data, path)
                self.assertEqual(issues, [], "fixture must be valid for this test to mean anything")
                validator.validate(self.plain(data))

    def test_nested_export_tags_in_the_schema(self) -> None:
        validator = self.validator()
        doc = {"id": "s", "title": "S", "nested": {"export_tags": ["pane"]}}
        self.assertEqual(parse_sheet(doc, Path("s.yaml"))[1], [])
        validator.validate(doc)
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate({"id": "s", "title": "S", "nested": {"foo": 1}})

    def test_numbers_that_validation_accepts_pass_the_schema(self) -> None:
        # ``key: 5`` is a hint for the digit 5, not a typo: yaml_store._opt_str keeps it as
        # "5", so the schema has to accept it as well, or an editor flags a valid sheet.
        doc = {
            "id": "s",
            "title": "S",
            "hints": [{"id": "h", "title": "T", "key": 5, "command": 3, "category": 2026}],
        }
        _sheet, issues = parse_sheet(doc, Path("s.yaml"))
        self.assertEqual(issues, [])
        self.validator().validate(self.plain(doc))

    def test_generated_sheet_passes_the_schema(self) -> None:
        _path, doc = create_sheet(
            ctx(desktop_app="foot", parent_context="herdr", foreground_process=proc("claude", ())),
            build_hint({"id": "h", "title": "T", "tags": ["terminal"], "learned": "2026-09-18"}),
            GlobalConfig(),
            hints_dir=Path("/tmp"),
            now=NOW,
        )
        self.validator().validate(self.plain(doc))
