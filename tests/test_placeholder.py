"""Replace this with real tests.

It is here because `./scripts/check` treats "no test ran at all" as a failure: a repository
whose test command silently passes because it found nothing is worse than one with no tests.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LayoutTest(unittest.TestCase):
    def test_shared_instructions_are_present(self) -> None:
        self.assertTrue((ROOT / "AGENTS.md").is_file())

    def test_check_is_the_validation_entry_point(self) -> None:
        self.assertTrue((ROOT / "scripts" / "check").is_file())
