"""``scripts/setup-terminals`` against a throwaway HOME.

The script writes into the user's home, so every path it uses comes from the environment and the
tests point all of it at a temporary directory. What is worth pinning down is the split it makes:
the files wayhint generates are written and kept current, and the launcher configuration the user
maintains is only ever reported.
"""

import importlib.machinery
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/setup-terminals"
# The scripts have no .py suffix, so the loader has to be named rather than inferred.
_LOADER = importlib.machinery.SourceFileLoader("setup_terminals", str(SCRIPT))
_SPEC = importlib.util.spec_from_loader("setup_terminals", _LOADER)
setup_terminals = importlib.util.module_from_spec(_SPEC)
# ``dataclass`` looks the defining module up in sys.modules, so register it before executing.
sys.modules["setup_terminals"] = setup_terminals
_LOADER.exec_module(setup_terminals)

WRAPPER = Path("/home/u/.local/bin/foot-wayhint")
FOOT = next(t for t in setup_terminals.TERMINALS if t.name == "foot")
KITTY = next(t for t in setup_terminals.TERMINALS if t.name == "kitty")
GHOSTTY = next(t for t in setup_terminals.TERMINALS if t.name == "ghostty")

FOOT_DESKTOP = """[Desktop Entry]
Type=Application
Exec=foot
TryExec=foot
Icon=foot
Name=Foot
"""

GHOSTTY_DESKTOP = """[Desktop Entry]
Type=Application
Exec=/usr/bin/ghostty --gtk-single-instance=true
Name=Ghostty

[Desktop Action new-window]
Exec=/usr/bin/ghostty --gtk-single-instance=true
"""

WAYBAR = """{
    // foot is the terminal; this comment must not count as a launch.
    "custom/launcher-foot": {
        "tooltip-format": "foot",
        "on-click": "/usr/bin/foot"
    },
    "custom/launcher-herdr": {
        "on-click": "/usr/bin/foot --app-id=foot-herdr /home/u/.local/bin/herdr"
    }
}
"""

MENU_XML = """<openbox_menu>
  <!-- foot is the native Wayland terminal -->
  <item label="Terminal emulator">
    <action name="Execute" command="foot" />
  </item>
</openbox_menu>
"""


class PureTest(unittest.TestCase):
    """The parts that decide what a line means, with no filesystem in sight."""

    def test_the_wrapper_execs_the_real_binary(self) -> None:
        body = setup_terminals.wrapper_body(FOOT, "/usr/bin/foot")
        self.assertIn('exec /usr/bin/foot --app-id "foot.p$$" "$@"', body)
        self.assertIn(setup_terminals.MARKER, body)  # so a rerun knows it may rewrite this file
        # A wrapper that called the bare name would find itself on PATH and recurse.
        self.assertNotIn("exec foot ", body)

    def test_a_terminal_that_shares_its_process_is_told_not_to(self) -> None:
        self.assertIn("single_instance=no", setup_terminals.wrapper_body(KITTY, "/usr/bin/kitty"))
        self.assertIn(
            "--gtk-single-instance=false", setup_terminals.wrapper_body(GHOSTTY, "/usr/bin/ghostty")
        )

    def test_alacritty_gets_a_lower_case_app_id_and_its_desktop_entry_is_rewritten(self) -> None:
        alacritty = next(t for t in setup_terminals.TERMINALS if t.name == "alacritty")
        body = setup_terminals.wrapper_body(alacritty, "/usr/bin/alacritty")
        self.assertIn('exec /usr/bin/alacritty --class "alacritty.p$$" "$@"', body)
        wrapper = Path("/home/u/.local/bin/alacritty-wayhint")
        entry = "[Desktop Entry]\nExec=alacritty\n[Desktop Action New]\nExec=alacritty --class x\n"
        override = setup_terminals.desktop_override(entry, alacritty, wrapper)
        self.assertEqual(override.count(f"Exec={wrapper}\n"), 2)

    def test_exec_keeps_what_the_launcher_needs_and_drops_what_we_set(self) -> None:
        wrapper = Path("/home/u/.local/bin/ghostty-wayhint")
        line = setup_terminals.rewrite_exec(
            "/usr/bin/ghostty --gtk-single-instance=true -e %F", GHOSTTY, wrapper
        )
        self.assertEqual(line, f"{wrapper} -e %F")  # the wrapper passes single-instance itself
        self.assertIsNone(setup_terminals.rewrite_exec("xterm", GHOSTTY, wrapper))

    def test_only_a_command_counts_as_a_launch(self) -> None:
        cases = {
            ('"on-click": "/usr/bin/foot"', "json"): True,
            ('"tooltip-format": "foot",', "json"): False,  # a label, not a command
            ("// foot + herdr, measured 2026-09-16", "json"): False,
            ('<action name="Execute" command="foot" />', "xml"): True,
            ("  <!-- foot is the native terminal -->", "xml"): False,
            ("terminal=foot", "ini"): True,
            ("##   waylandim -> clients (foot, GTK3)", "ini"): False,
            ("command_terminal = foot", "ini"): True,
        }
        for (line, kind), expect in cases.items():
            with self.subTest(line):
                changed = setup_terminals.point_at(line, kind, FOOT, WRAPPER)
                self.assertIs(changed is not None, expect)

    def test_an_edit_touches_the_command_and_nothing_else_on_the_line(self) -> None:
        """No parsing, no reserialising: the rest of the line comes through byte for byte."""
        cases = {
            (
                '        "on-click": "/usr/bin/foot",  // the terminal',
                "json",
            ): f'        "on-click": "{WRAPPER}",  // the terminal',
            (
                '    <action name="Execute" command="foot" />',
                "xml",
            ): f'    <action name="Execute" command="{WRAPPER}" />',
            ("command_terminal = foot", "ini"): f"command_terminal = {WRAPPER}",
            ("terminal=foot -e sh", "ini"): f"terminal={WRAPPER} -e sh",
        }
        for (line, kind), expect in cases.items():
            with self.subTest(line):
                self.assertEqual(setup_terminals.point_at(line, kind, FOOT, WRAPPER), expect)

    def test_a_window_that_already_names_its_app_id_is_left_alone(self) -> None:
        """``foot --app-id=foot-herdr`` is deliberate: that window wants to be the Herdr one."""
        self.assertFalse(
            setup_terminals.launches("/usr/bin/foot --app-id=foot-herdr /bin/herdr", FOOT)
        )
        self.assertTrue(setup_terminals.launches("/usr/bin/foot", FOOT))


class EndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / "usr/bin"
        self.bin.mkdir(parents=True)
        for name in ("foot", "kitty", "ghostty", "alacritty"):
            fake = self.bin / name
            fake.write_text("#!/bin/sh\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        apps = self.root / "usr/share/applications"
        apps.mkdir(parents=True)
        (apps / "foot.desktop").write_text(FOOT_DESKTOP)
        (apps / "com.mitchellh.ghostty.desktop").write_text(GHOSTTY_DESKTOP)
        self.config = self.root / "home/.config"
        (self.config / "waybar").mkdir(parents=True)
        (self.config / "waybar/config.jsonc").write_text(WAYBAR)
        (self.config / "labwc").mkdir(parents=True)
        (self.config / "labwc/menu.xml").write_text(MENU_XML)
        self.env = unittest.mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.root / "home"),
                "XDG_CONFIG_HOME": str(self.config),
                "XDG_DATA_HOME": str(self.root / "home/.local/share"),
                "XDG_DATA_DIRS": str(self.root / "usr/share"),
                "PATH": str(self.bin),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.wrapper = self.root / "home/.local/bin/foot-wayhint"
        self.desktop = self.root / "home/.local/share/applications/foot.desktop"

    def run_script(self, *argv):
        with unittest.mock.patch("sys.stdout"):
            return setup_terminals.main(list(argv))

    def test_nothing_is_written_without_apply(self) -> None:
        """The default is a dry run -- with a terminal named, and without."""
        for argv in (("foot",), ("--check", "foot"), (), ("--check",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_script(*argv), 1)
                self.assertFalse(self.wrapper.exists())
                self.assertFalse(self.desktop.exists())
                self.assertFalse((self.root / "home/.local/bin/kitty-wayhint").exists())

    def test_apply_and_check_together_is_refused(self) -> None:
        with unittest.mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            self.run_script("--apply", "--check")

    def test_apply_writes_the_generated_files(self) -> None:
        self.assertEqual(self.run_script("--apply", "foot"), 0)  # nothing left over
        self.assertTrue(os.access(self.wrapper, os.X_OK))
        self.assertIn('--app-id "foot.p$$"', self.wrapper.read_text())
        self.assertIn(f"Exec={self.wrapper}", self.desktop.read_text())
        self.assertIn("TryExec=foot", self.desktop.read_text())  # the binary still exists

    def test_apply_rewrites_the_launcher_line_and_leaves_the_rest_alone(self) -> None:
        waybar = self.config / "waybar/config.jsonc"
        menu = self.config / "labwc/menu.xml"
        self.run_script("--apply", "foot")

        after = waybar.read_text()
        self.assertIn(f'"on-click": "{self.wrapper}"', after)
        self.assertIn("// foot is the terminal", after)  # the comment survives
        self.assertIn('"tooltip-format": "foot"', after)  # the label is not a command
        self.assertIn("--app-id=foot-herdr", after)  # a deliberate app_id is left alone
        self.assertIn(f'command="{self.wrapper}"', menu.read_text())
        self.assertIn("<!-- foot is the native Wayland terminal -->", menu.read_text())

    def test_apply_copies_each_file_aside_before_touching_it(self) -> None:
        waybar = self.config / "waybar/config.jsonc"
        before = waybar.read_text()
        self.run_script("--apply", "foot")
        backups = list(waybar.parent.glob("config.jsonc.wayhint-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), before)

    def test_a_second_apply_changes_nothing(self) -> None:
        self.run_script("--apply", "foot")
        waybar = self.config / "waybar/config.jsonc"
        after = waybar.read_text()
        wrapper = self.wrapper.read_text()
        self.assertEqual(self.run_script("--apply", "foot"), 0)
        self.assertEqual(waybar.read_text(), after)
        self.assertEqual(self.wrapper.read_text(), wrapper)
        self.assertEqual(len(list(waybar.parent.glob("config.jsonc.wayhint-backup-*"))), 1)

    def test_a_generated_file_that_has_fallen_behind_is_refreshed(self) -> None:
        """An older version of this script wrote a different wrapper; the marker says it is ours."""
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_text(f"#!/bin/sh\n# {setup_terminals.MARKER}\nexec /usr/bin/foot\n")
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text(f"# {setup_terminals.MARKER}\n[Desktop Entry]\nExec=stale\n")
        self.assertEqual(self.run_script("--apply", "foot"), 0)
        self.assertIn('--app-id "foot.p$$"', self.wrapper.read_text())
        self.assertIn(f"Exec={self.wrapper}", self.desktop.read_text())

    def test_a_hand_written_desktop_entry_is_never_overwritten(self) -> None:
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text("[Desktop Entry]\nExec=my own thing\n")
        self.run_script("--apply", "foot")
        self.assertEqual(self.desktop.read_text(), "[Desktop Entry]\nExec=my own thing\n")

    def test_a_launcher_already_pointing_at_the_wrapper_is_left_alone(self) -> None:
        waybar = self.config / "waybar/config.jsonc"
        self.run_script("--apply", "foot")
        after = waybar.read_text()
        self.assertEqual(self.run_script("foot"), 0)  # dry run: nothing outstanding
        self.assertEqual(waybar.read_text(), after)

    def test_one_file_holding_two_terminals_is_copied_aside_once(self) -> None:
        waybar = self.config / "waybar/config.jsonc"
        waybar.write_text(
            WAYBAR.replace(
                '        "on-click": "/usr/bin/foot"\n',
                '        "on-click": "/usr/bin/foot",\n        "on-click-right": "kitty"\n',
            )
        )
        before = waybar.read_text()
        self.run_script("--apply")
        after = waybar.read_text()
        self.assertIn(f'"on-click": "{self.wrapper}"', after)
        self.assertIn(f'"on-click-right": "{self.root}/home/.local/bin/kitty-wayhint"', after)
        backups = list(waybar.parent.glob("config.jsonc.wayhint-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), before)

    def test_a_file_that_does_not_end_in_a_newline_keeps_it_that_way(self) -> None:
        menu = self.config / "labwc/menu.xml"
        menu.write_text(MENU_XML.rstrip("\n"))
        self.run_script("--apply", "foot")
        self.assertFalse(menu.read_text().endswith("\n"))
        self.assertIn(f'command="{self.wrapper}"', menu.read_text())

    def test_a_hand_written_file_is_never_overwritten(self) -> None:
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_text("#!/bin/sh\n# mine\n")
        self.run_script("--apply", "foot")
        self.assertEqual(self.wrapper.read_text(), "#!/bin/sh\n# mine\n")

    def test_only_the_named_terminal_is_touched(self) -> None:
        self.run_script("--apply", "foot")
        self.assertFalse((self.root / "home/.local/bin/kitty-wayhint").exists())
        self.run_script("--apply")  # no terminal named: everything installed
        self.assertTrue((self.root / "home/.local/bin/kitty-wayhint").exists())
        self.assertTrue((self.root / "home/.local/bin/ghostty-wayhint").exists())

    def test_a_terminal_that_cannot_carry_the_convention_is_refused(self) -> None:
        self.assertEqual(self.run_script("wezterm"), 1)
        self.assertEqual(self.run_script("emacs"), 1)

    def test_a_desktop_entry_with_no_system_copy_is_skipped(self) -> None:
        (self.root / "usr/share/applications/foot.desktop").unlink()
        self.run_script("--apply", "foot")
        self.assertTrue(self.wrapper.exists())
        self.assertFalse(self.desktop.exists())


if __name__ == "__main__":
    unittest.main()


class LanguageTest(unittest.TestCase):
    """Messages follow the locale, the way wayhint's interface does; English when unset."""

    def say(self, **env: str) -> str:
        clean = {k: v for k, v in os.environ.items() if k not in ("LC_ALL", "LC_MESSAGES", "LANG")}
        with unittest.mock.patch.dict(os.environ, {**clean, **env}, clear=True):
            return setup_terminals.say("  wrapper   {target}: will create", target="/x")

    def test_english_without_a_locale(self) -> None:
        self.assertEqual(self.say(), "  wrapper   /x: will create")

    def test_japanese_under_a_japanese_locale(self) -> None:
        self.assertEqual(self.say(LANG="ja_JP.UTF-8"), "  wrapper   /x: 作成します")

    def test_lc_all_wins_over_lang(self) -> None:
        self.assertEqual(self.say(LANG="ja_JP.UTF-8", LC_ALL="C"), "  wrapper   /x: will create")

    def test_every_japanese_message_takes_the_same_values(self) -> None:
        """A translation that names a placeholder the English one does not would raise."""
        import string

        for english, japanese in setup_terminals.JA.items():
            names = {f for _, f, _, _ in string.Formatter().parse(english) if f}
            self.assertEqual(names, {f for _, f, _, _ in string.Formatter().parse(japanese) if f})
