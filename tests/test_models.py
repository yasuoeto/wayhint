import unittest
from pathlib import Path

from wayhint.config import ConfigError, EditorConfig, parse_anchor, parse_editor_command
from wayhint.models import DisplayConfig, Margin, Size


class SizeTest(unittest.TestCase):
    def test_parse_variants(self) -> None:
        self.assertEqual(Size.parse(420), Size(420, "px"))
        self.assertEqual(Size.parse("420px"), Size(420, "px"))
        self.assertEqual(Size.parse(" 30% "), Size(30, "%"))
        self.assertEqual(Size.parse("12.5%"), Size(12.5, "%"))

    def test_invalid(self) -> None:
        for raw in ("abc", "-1px", "120%", True, None, "10em", []):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                Size.parse(raw)

    def test_to_px(self) -> None:
        self.assertEqual(Size(30, "%").to_px(1920), 576)
        self.assertEqual(Size(420, "px").to_px(1920), 420)
        self.assertEqual(Size(33.3, "%").to_px(1000), 333)


class AnchorTest(unittest.TestCase):
    def test_all_nine(self) -> None:
        for a in ("top-left", "top", "top-right", "left", "center", "right",
                  "bottom-left", "bottom", "bottom-right"):  # fmt: skip
            self.assertEqual(parse_anchor(a, "k"), a)

    def test_invalid(self) -> None:
        with self.assertRaises(ConfigError):
            parse_anchor("upper-right", "k")


class DisplayMergeTest(unittest.TestCase):
    def test_partial_inherits_from_base(self) -> None:
        base = DisplayConfig("top-right", Size(420, "px"), Size(60, "%"), Margin(24, 24), None)
        part = DisplayConfig(anchor="bottom-left", output="DP-2")
        merged = part.merged_over(base)
        self.assertEqual(merged.anchor, "bottom-left")
        self.assertEqual(merged.width, Size(420, "px"))
        self.assertEqual(merged.margin, Margin(24, 24))
        self.assertEqual(merged.output, "DP-2")


class EditorTest(unittest.TestCase):
    def test_argv_expansion_is_plain_substitution(self) -> None:
        ed = EditorConfig(("gvim", "--remote-silent", "+{line}", "{file}", "--", "{hint_id}"))
        argv = ed.argv(Path("/x/a b.yaml"), 12, "new-pane")
        self.assertEqual(argv, ["gvim", "--remote-silent", "+12", "/x/a b.yaml", "--", "new-pane"])

    def test_unknown_placeholder_rejected(self) -> None:
        with self.assertRaises(ConfigError) as cm:
            parse_editor_command(["ed", "{file}", "{column}"], "editor.command")
        self.assertIn("{column}", str(cm.exception))

    def test_file_placeholder_required(self) -> None:
        with self.assertRaises(ConfigError):
            parse_editor_command(["ed", "+{line}"], "editor.command")
        with self.assertRaises(ConfigError):
            parse_editor_command([], "editor.command")
