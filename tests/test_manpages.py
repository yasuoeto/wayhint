"""The man pages name every command and option the parsers accept, in both languages."""

import argparse
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from wayhint.cli import build_parser

MAN = Path(__file__).resolve().parent.parent / "man"
LANGUAGES = ("", ".ja")


def _roff(text: str) -> str:
    """The page's text with roff's escaped hyphens and font changes taken out."""
    for escape in ("\\fI", "\\fB", "\\fR", "\\fP", "\\:"):
        text = text.replace(escape, "")
    return text.replace("\\-", "-")


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {
        s for a in parser._actions for s in a.option_strings if s.startswith("--") and s != "--help"
    }


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


class ManPageTest(unittest.TestCase):
    def page(self, name: str, lang: str) -> str:
        return _roff((MAN / f"{name}{lang}.1").read_text(encoding="utf-8"))

    def test_wayhint_names_every_command_and_option(self) -> None:
        parser = build_parser()
        for lang in LANGUAGES:
            text = self.page("wayhint", lang)
            for name, sub in _subparsers(parser).items():
                with self.subTest(lang=lang or "en", command=name):
                    self.assertRegex(text, rf"(?m)^\.B[IR]? {name}\b")
                    for option in _options(sub):
                        self.assertIn(option, text)
            for option in _options(parser):
                self.assertIn(option, text)

    def test_wayhintd_names_every_option(self) -> None:
        try:
            from wayhint.daemon import build_parser as daemon_parser
        except ImportError as e:  # GTK is not there
            self.skipTest(str(e))
        for lang in LANGUAGES:
            text = self.page("wayhintd", lang)
            for option in _options(daemon_parser()):
                with self.subTest(lang=lang or "en", option=option):
                    self.assertIn(option, text)

    @unittest.skipUnless(shutil.which("man"), "man is not on PATH")
    def test_pages_format_without_warnings(self) -> None:
        env = {**os.environ, "LC_ALL": "C.UTF-8", "MANWIDTH": "80"}
        for page in sorted(MAN.glob("*.1")):
            with self.subTest(page=page.name):
                done = subprocess.run(
                    ["man", "--warnings", "-E", "UTF-8", "-l", str(page)],
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stderr, "")


if __name__ == "__main__":
    unittest.main()
