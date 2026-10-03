"""Every document has its Japanese version next to it, with the same headings (DECISIONS 0044)."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{1,6}) ")


def _documents() -> list[Path]:
    """The English documents that have to be translated: README, docs, dev-docs and the demo's."""
    found = [ROOT / "README.md", ROOT / "demo" / "README.md"]
    found += sorted((ROOT / "docs").glob("*.md")) + sorted((ROOT / "dev-docs").glob("*.md"))
    found += sorted((ROOT / "demo" / "showcases").glob("*/01_*_storyboard.md"))
    return [p for p in found if not p.name.endswith(".ja.md")]


def _japanese(english: Path) -> Path:
    return english.with_name(english.name[: -len(".md")] + ".ja.md")


def _heading_levels(path: Path) -> list[int]:
    """The level of each heading in order, skipping `#` lines inside code blocks."""
    levels, in_code = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_code = not in_code
        elif not in_code and (m := HEADING.match(line)):
            levels.append(len(m.group(1)))
    return levels


class DocTranslationTest(unittest.TestCase):
    def test_every_document_has_a_japanese_version(self) -> None:
        """Fails when an English document is added or renamed without its `.ja.md`."""
        for english in _documents():
            with self.subTest(document=str(english.relative_to(ROOT))):
                self.assertTrue(_japanese(english).is_file())

    def test_both_languages_have_the_same_headings(self) -> None:
        """Fails when a section is added, removed or moved in one language only."""
        for english in _documents():
            japanese = _japanese(english)
            if not japanese.is_file():
                continue  # reported by the test above
            with self.subTest(document=str(english.relative_to(ROOT))):
                self.assertEqual(_heading_levels(english), _heading_levels(japanese))


if __name__ == "__main__":
    unittest.main()
