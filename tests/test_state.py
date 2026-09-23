"""state.yaml: the rules of DECISIONS 0033 E / F, on the pure functions and on real files."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wayhint import state
from wayhint.state import (
    MAX_FILTERS,
    MAX_QUERY_LEN,
    MAX_STATE_BYTES,
    dump_state,
    load_state,
    parse_state,
    sanitize_query,
    save_state,
    state_path,
)


class ParseStateTest(unittest.TestCase):
    def test_reads_the_filters(self):
        text = 'version: 1\nfilters:\n  claude-code: "pane"\n  herdr: "#session"\n'
        self.assertEqual(parse_state(text), ({"claude-code": "pane", "herdr": "#session"}, []))

    def test_empty_file_is_no_filters_without_a_warning(self):
        self.assertEqual(parse_state(""), ({}, []))

    def test_broken_yaml_is_no_filters_and_one_warning(self):
        filters, warnings = parse_state("foo: [")
        self.assertEqual(filters, {})
        self.assertEqual(len(warnings), 1)

    def test_a_list_at_the_top_is_refused(self):
        filters, warnings = parse_state("- version: 1\n")
        self.assertEqual((filters, len(warnings)), ({}, 1))

    def test_missing_version_is_refused(self):
        filters, warnings = parse_state("filters:\n  a: x\n")
        self.assertEqual((filters, len(warnings)), ({}, 1))

    def test_another_version_is_refused(self):
        for version in ("2", "'1'", "true"):
            with self.subTest(version=version):
                filters, warnings = parse_state(f"version: {version}\nfilters:\n  a: x\n")
                self.assertEqual((filters, len(warnings)), ({}, 1))

    def test_a_value_that_is_not_a_string_drops_only_that_item(self):
        filters, warnings = parse_state("version: 1\nfilters:\n  a: 3\n  b: x\n")
        self.assertEqual(filters, {"b": "x"})
        self.assertEqual(len(warnings), 1)

    def test_a_key_that_is_not_a_sheet_id_drops_only_that_item(self):
        for key in ("'-x'", "'a b'", "'../up'", "12", "'ä'"):
            with self.subTest(key=key):
                filters, warnings = parse_state(f"version: 1\nfilters:\n  {key}: x\n  ok: y\n")
                self.assertEqual(filters, {"ok": "y"})
                self.assertEqual(len(warnings), 1)

    def test_a_value_over_the_limit_is_dropped_not_cut(self):
        long = "あ" * (MAX_QUERY_LEN + 1)
        filters, warnings = parse_state(f"version: 1\nfilters:\n  a: '{long}'\n  b: x\n")
        self.assertEqual(filters, {"b": "x"})
        self.assertEqual(len(warnings), 1)
        self.assertNotIn("あ", warnings[0])  # the filter itself never reaches the log

    def test_a_value_at_the_limit_is_kept(self):
        exact = "a" * MAX_QUERY_LEN
        self.assertEqual(parse_state(f"version: 1\nfilters:\n  a: {exact}\n")[0], {"a": exact})

    def test_items_past_the_limit_are_dropped(self):
        lines = "".join(f"  s{i}: q\n" for i in range(MAX_FILTERS + 1))
        filters, warnings = parse_state(f"version: 1\nfilters:\n{lines}")
        self.assertEqual(len(filters), MAX_FILTERS)
        self.assertNotIn(f"s{MAX_FILTERS}", filters)
        self.assertEqual(len(warnings), 1)

    def test_a_duplicated_sheet_id_keeps_the_last_value(self):
        text = "version: 1\nfilters:\n  a: first\n  a: last\n"
        self.assertEqual(parse_state(text), ({"a": "last"}, []))

    def test_unknown_keys_are_ignored_and_gone_after_a_write(self):
        filters, warnings = parse_state("version: 1\nextra: 5\nfilters:\n  a: x\n")
        self.assertEqual((filters, warnings), ({"a": "x"}, []))
        self.assertNotIn("extra", dump_state(filters))

    def test_control_characters_are_dropped_on_read(self):
        text = 'version: 1\nfilters:\n  a: "pa\\x1bne\\tx"\n'
        self.assertEqual(parse_state(text)[0], {"a": "panex"})

    def test_an_empty_value_is_not_a_filter(self):
        self.assertEqual(parse_state('version: 1\nfilters:\n  a: ""\n')[0], {})


class SanitizeTest(unittest.TestCase):
    def test_removes_cc_and_keeps_everything_else(self):
        self.assertEqual(sanitize_query("ペイン\x00\x07\n#pane ​"), "ペイン#pane ​")


class DumpStateTest(unittest.TestCase):
    def test_round_trip(self):
        filters = {"claude-code": "pane", "herdr": "#session", "vi": "yes", "x": "a: [b"}
        self.assertEqual(parse_state(dump_state(filters)), (filters, []))

    def test_empty_writes_an_empty_mapping(self):
        self.assertEqual(parse_state(dump_state({})), ({}, []))
        self.assertIn("filters: {}", dump_state({}))

    def test_values_are_quoted(self):
        self.assertIn('vi: "yes"', dump_state({"vi": "yes"}))


class FileTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.path = self.dir / "wayhint" / "state.yaml"

    def test_missing_file_is_no_filters_without_a_warning(self):
        self.assertEqual(load_state(self.path), ({}, []))

    def test_a_file_over_the_size_limit_is_not_parsed(self):
        self.path.parent.mkdir()
        self.path.write_text("version: 1\nfilters:\n  a: x\n" + "#" * MAX_STATE_BYTES)
        filters, warnings = load_state(self.path)
        self.assertEqual((filters, len(warnings)), ({}, 1))

    def test_not_utf8_is_no_filters(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"version: 1\nfilters:\n  a: \xff\n")
        filters, warnings = load_state(self.path)
        self.assertEqual((filters, len(warnings)), ({}, 1))

    def test_save_then_load(self):
        save_state(self.path, {"a": "pane"})
        self.assertEqual(load_state(self.path), ({"a": "pane"}, []))

    def test_save_leaves_no_temporary_file(self):
        save_state(self.path, {"a": "pane"})
        save_state(self.path, {"a": "other"})
        self.assertEqual(os.listdir(self.path.parent), ["state.yaml"])

    def test_a_failed_write_keeps_the_old_file_and_no_temporary_file(self):
        save_state(self.path, {"a": "pane"})
        with mock.patch.object(state.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_state(self.path, {"a": "other"})
        self.assertEqual(os.listdir(self.path.parent), ["state.yaml"])
        self.assertEqual(load_state(self.path)[0], {"a": "pane"})

    def test_state_path_follows_xdg_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.dir)}):
            self.assertEqual(state_path(), self.dir / "wayhint" / "state.yaml")
        env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(state_path(), Path.home() / ".local/state/wayhint/state.yaml")


if __name__ == "__main__":
    unittest.main()
