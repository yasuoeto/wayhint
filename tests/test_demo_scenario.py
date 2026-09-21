"""The demo's scenario parser and showcase resolver, without a compositor.

These run in ``./scripts/check``: they are pure reading and checking, and they are the only
place the *refusals* are covered. A scenario that is wrong has to be refused before a recording
starts, because by then a compositor is up and the mistake costs a minute instead of a
millisecond. The real ``demo/showcases/`` tree is never renamed or duplicated to test the
naming rules -- every case here builds its own directory in a temporary one.
"""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tools import headless as headless_mod
from tools.demo import __main__ as cli
from tools.demo import names as nm
from tools.demo import scenario as scn
from tools.demo import session as sess
from tools.demo import showcase as shc

BIN = Path(__file__).resolve().parent.parent / "demo" / "bin"
"""The real ``demo/bin``. The wrappers are read and run here for their *refusals* only, which
happen before anything is exec'd -- no terminal and no Herdr is started by this file."""

MINIMAL = """
windows: [{title: main, x: 0, y: 0, width: 100, height: 100}]
steps:
  - id: show
    cli: show
    wait_for: {overlay: visible}
    caption: {ja: "出す"}
    hold: 2
variants:
  short: {target: 2, tolerance: 0.5, steps: [show]}
"""


def scratch(case: unittest.TestCase, prefix: str = "wayhint-demo-test-") -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    case.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


def parse(text: str, demo_bin: Path | None = None) -> scn.Scenario:
    import io

    from ruamel.yaml import YAML

    return scn.parse(YAML(typ="safe").load(io.StringIO(text)), demo_bin)


class ScenarioTest(unittest.TestCase):
    def test_a_minimal_scenario_with_only_japanese_captions_is_accepted(self) -> None:
        """Japanese is written first and English follows in its own task (DECISIONS 0032)."""
        script = parse(MINIMAL)
        self.assertEqual([v.name for v in script.variants], ["short"])
        self.assertEqual(script.variant("short").seconds(30), 2.0)
        self.assertEqual(script.steps["show"].caption, {"ja": "出す"})

    def test_a_caption_without_japanese_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "ja is required"):
            parse(MINIMAL.replace('{ja: "出す"}', '{en: "Show it"}'))

    def test_a_variant_naming_a_step_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "no step 'nope'"):
            parse(MINIMAL.replace("steps: [show]", "steps: [show, nope]"))

    def test_a_step_in_no_variant_is_refused(self) -> None:
        """A step nobody records is either a typo in a variant or dead weight."""
        text = MINIMAL.replace(
            "variants:",
            "  - {id: spare, cli: ping, wait_for: {overlay: hidden}, hold: 1}\nvariants:",
        )
        with self.assertRaisesRegex(scn.ScenarioError, "steps in no variant: spare"):
            parse(text)

    def test_two_actions_in_one_step_are_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "exactly one action"):
            parse(MINIMAL.replace("    cli: show\n", "    cli: show\n    key: super+h\n"))

    def test_a_step_without_wait_for_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "wait_for is required"):
            parse(MINIMAL.replace("    wait_for: {overlay: visible}\n", ""))

    def test_a_negative_hold_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "not negative"):
            parse(MINIMAL.replace("hold: 2", "hold: -1"))

    def test_a_write_outside_the_fixtures_is_refused(self) -> None:
        text = MINIMAL.replace(
            "    cli: show\n", '    write: {file: "../../etc/passwd", text: "x"}\n'
        )
        with self.assertRaisesRegex(scn.ScenarioError, r"without '\.\.'"):
            parse(text)


class NameTest(unittest.TestCase):
    """Step ids, variant names and showcase names become file and directory names."""

    def test_a_variant_name_that_could_climb_out_of_out_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "has to be lower-case"):
            parse(MINIMAL.replace("  short:", "  ../escape:"))

    def test_a_step_id_with_a_slash_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "has to be lower-case"):
            parse(MINIMAL.replace("id: show", "id: a/b").replace("steps: [show]", "steps: [a/b]"))

    def test_a_step_id_in_capitals_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "has to be lower-case"):
            parse(MINIMAL.replace("id: show", "id: Show").replace("steps: [show]", "steps: [Show]"))

    def test_a_showcase_name_that_is_a_path_is_refused(self) -> None:
        with self.assertRaisesRegex(shc.ShowcaseError, "is not a showcase name"):
            shc.load(scratch(self), "../elsewhere")


class NotANumberTest(unittest.TestCase):
    """YAML writes ``.nan`` and ``.inf`` as floats; they would pass every comparison."""

    def test_a_nan_target_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "finite"):
            parse(MINIMAL.replace("target: 2", "target: .nan"))

    def test_an_infinite_tolerance_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "finite"):
            parse(MINIMAL.replace("tolerance: 0.5", "tolerance: .inf"))

    def test_an_infinite_hold_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "finite"):
            parse(MINIMAL.replace("hold: 2", "hold: .inf"))

    def test_a_nan_frame_rate_is_refused(self) -> None:
        """``fps`` divides the frame count; a float there would make every length a float."""
        with self.assertRaisesRegex(scn.ScenarioError, "expected an integer"):
            parse("output: {fps: .nan}\n" + MINIMAL)

    def test_an_infinite_timeout_is_refused(self) -> None:
        text = MINIMAL.replace(
            "wait_for: {overlay: visible}", "wait_for: {overlay: visible, timeout: .inf}"
        )
        with self.assertRaisesRegex(scn.ScenarioError, "finite"):
            parse(text)


class VariantLengthTest(unittest.TestCase):
    """``target`` and ``tolerance`` come from the storyboard; drifting off them is an error."""

    def test_a_variant_inside_its_tolerance_is_on_target(self) -> None:
        self.assertEqual(parse(MINIMAL).variant("short").off_target(30), 0.0)

    def test_a_variant_outside_its_tolerance_says_how_far(self) -> None:
        script = parse(MINIMAL.replace("hold: 2", "hold: 9"))
        self.assertAlmostEqual(script.variant("short").off_target(30), 6.5)

    def test_frames_not_seconds_decide_the_length(self) -> None:
        """The recorder lays down whole frames, so the length is rounded once, here."""
        script = parse(MINIMAL.replace("hold: 2", "hold: 2.017"))
        self.assertEqual(script.variant("short").frames(30), 61)


class HerdrCommandTest(unittest.TestCase):
    """``herdr:`` runs a real program, so what it may be asked to do is a fixed list."""

    def herdr(self, argv: str, demo_bin: Path | None = None) -> scn.Scenario:
        return parse(MINIMAL.replace("    cli: show\n", f"    herdr: {argv}\n"), demo_bin)

    def test_an_allowed_command_is_accepted(self) -> None:
        script = self.herdr("[tab, focus, 'w1:t2']")
        self.assertEqual(script.steps["show"].action.payload["argv"], ["tab", "focus", "w1:t2"])

    def test_a_command_outside_the_list_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "is not allowed"):
            self.herdr("[agent, prompt, hello]")

    def test_the_recorders_own_teardown_command_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "the recorder's own"):
            self.herdr("[server, stop]")

    def test_an_option_that_could_carry_a_path_is_refused(self) -> None:
        """``--cwd`` / ``--env`` would let a scenario choose a directory or an environment."""
        with self.assertRaisesRegex(scn.ScenarioError, "only --focus / --no-focus"):
            self.herdr("[tab, create, --cwd, /etc]")

    def test_a_pane_id_with_a_trailing_newline_is_refused(self) -> None:
        """The same ``re.match`` hole as the app_id, on the ids that reach Herdr's argv."""
        with self.assertRaisesRegex(scn.ScenarioError, "expected exactly one pane id"):
            self.herdr('[pane, close, "w1:p1\n"]')

    def test_a_bad_pane_id_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "is not a pane id"):
            self.herdr("[pane, run, nonsense, claude]")

    def test_pane_run_only_starts_a_program_from_demo_bin(self) -> None:
        demo_bin = scratch(self)
        (demo_bin / "claude").write_text("#!/bin/sh\n")
        self.herdr("[pane, run, 'w1:p1', claude]", demo_bin)  # the stub is there
        with self.assertRaisesRegex(scn.ScenarioError, "no such program"):
            self.herdr("[pane, run, 'w1:p1', bash]", demo_bin)
        with self.assertRaisesRegex(scn.ScenarioError, "bare program name"):
            self.herdr("[pane, run, 'w1:p1', /bin/bash]", demo_bin)


class FixtureLanguageTest(unittest.TestCase):
    """The sheets are per language, and a recording says so before it starts a compositor."""

    def fixtures(self, *languages: str) -> Path:
        root = scratch(self)
        for language in languages:
            (root / "hints" / language).mkdir(parents=True)
        (root / "config.yaml").write_text("appearance:\n  language: ja\n")
        return root

    def test_the_language_is_set_on_the_copy_not_on_the_fixture(self) -> None:
        fixtures = self.fixtures("ja", "en")
        before = (fixtures / "config.yaml").read_text()
        config = sess.prepare_config(fixtures, "en", scratch(self))
        self.assertIn("language: en", (config / "config.yaml").read_text())
        self.assertEqual((fixtures / "config.yaml").read_text(), before)

    def test_a_language_with_no_sheets_is_refused(self) -> None:
        with self.assertRaisesRegex(sess.DemoError, "no hints for 'en'"):
            sess.prepare_config(self.fixtures("ja"), "en", scratch(self))


class WorkspaceTest(unittest.TestCase):
    """Where a recording's throwaway files go. The path is on screen, so it is part of the film."""

    def setUp(self) -> None:
        root = scratch(self)
        original = tempfile.tempdir
        tempfile.tempdir = str(root)
        self.addCleanup(setattr, tempfile, "tempdir", original)
        self.tmp = root

    def test_it_makes_one_directory_per_showcase_and_language(self) -> None:
        work = sess.workspace("herdr", "ja")
        self.assertEqual(work, self.tmp / sess.DEMO_ROOT / "herdr-ja")
        self.assertTrue((work / sess.WORK_DIR).is_dir())

    def test_the_path_carries_no_uid(self) -> None:
        """It is read off the screen in the YAML-error scene; a uid there reads as an accident."""
        work = sess.workspace("herdr", "ja")
        self.assertNotIn(str(os.getuid()), str(work.relative_to(self.tmp)))

    def test_a_workspace_that_is_already_there_is_refused(self) -> None:
        sess.workspace("herdr", "ja")
        with self.assertRaisesRegex(sess.DemoError, "already there"):
            sess.workspace("herdr", "ja")

    def test_release_takes_the_directory_above_it_too(self) -> None:
        work = sess.workspace("herdr", "ja")
        sess.release(work)
        self.assertFalse(work.exists())
        self.assertFalse(work.parent.exists(), "nothing of the recording is left in /tmp")

    def test_release_keeps_the_directory_above_while_another_recording_is_in_it(self) -> None:
        first = sess.workspace("herdr", "ja")
        second = sess.workspace("herdr", "en")
        sess.release(first)
        self.assertTrue(second.is_dir())
        self.assertTrue(second.parent.is_dir())


class OutputDirTest(unittest.TestCase):
    """The one place that deletes a directory checks where it is, whatever it was told."""

    def showcase(self) -> shc.Showcase:
        root = scratch(self)
        (root / "herdr").mkdir()
        scenario = root / "herdr" / "02_herdr_scenario.yaml"
        scenario.write_text(MINIMAL)
        return shc.load(root, "herdr")

    def test_it_prepares_a_directory_under_out(self) -> None:
        show = self.showcase()
        out = cli._output_dir(show, "ja", "short")
        self.assertTrue(out.is_relative_to((show.root / "out").resolve()))
        self.assertFalse(out.exists())  # cleared, not created; the caller makes it

    def test_it_refuses_a_variant_name_that_climbs_out(self) -> None:
        with self.assertRaisesRegex(sess.DemoError, "refusing to write outside"):
            cli._output_dir(self.showcase(), "ja", "../../elsewhere")

    def test_it_refuses_to_delete_the_out_directory_itself(self) -> None:
        with self.assertRaisesRegex(sess.DemoError, "refusing to write outside"):
            cli._output_dir(self.showcase(), ".", ".")

    def test_it_refuses_an_out_that_is_a_symlink(self) -> None:
        """Somebody's ``out/`` may well point at another disk; the delete must not follow it."""
        show = self.showcase()
        elsewhere = scratch(self)
        (elsewhere / "ja" / "short").mkdir(parents=True)
        (show.root / "out").symlink_to(elsewhere)
        with self.assertRaisesRegex(sess.DemoError, "is a symlink to"):
            cli._output_dir(show, "ja", "short")
        self.assertTrue((elsewhere / "ja" / "short").is_dir(), "it deleted through the symlink")

    def test_it_refuses_an_intermediate_directory_that_is_a_symlink(self) -> None:
        show = self.showcase()
        elsewhere = scratch(self)
        (elsewhere / "short").mkdir()
        (show.root / "out").mkdir()
        (show.root / "out" / "ja").symlink_to(elsewhere)
        with self.assertRaisesRegex(sess.DemoError, "is a symlink to"):
            cli._output_dir(show, "ja", "short")
        self.assertTrue((elsewhere / "short").is_dir(), "it deleted through the symlink")

    def test_it_refuses_the_variant_directory_itself_being_a_symlink(self) -> None:
        show = self.showcase()
        elsewhere = scratch(self)
        (elsewhere / "kept").mkdir()
        (show.root / "out" / "ja").mkdir(parents=True)
        (show.root / "out" / "ja" / "short").symlink_to(elsewhere)
        with self.assertRaisesRegex(sess.DemoError, "is a symlink to"):
            cli._output_dir(show, "ja", "short")
        self.assertTrue((elsewhere / "kept").is_dir(), "it deleted through the symlink")


class SpawnTest(unittest.TestCase):
    """A spawn starts a terminal from ``demo/bin``, and nothing else."""

    def bin(self) -> Path:
        demo_bin = scratch(self)
        for name in ("foot-herdr", "foot-wayhint", "vi", "claude", "idle"):
            (demo_bin / name).write_text("#!/bin/sh\n")
        return demo_bin

    def spawn(self, argv: str, demo_bin: Path | None = None) -> scn.Scenario:
        text = MINIMAL.replace("    cli: show\n", f"    spawn: {{window: main, argv: {argv}}}\n")
        return parse(text, demo_bin)

    def test_a_wrapper_from_demo_bin_is_accepted(self) -> None:
        script = self.spawn("[foot-herdr]", self.bin())
        self.assertEqual(script.steps["show"].action.payload["argv"], ["foot-herdr"])

    def test_a_wrapper_with_a_stub_after_it_is_accepted(self) -> None:
        self.spawn("[foot-wayhint, -e, vi]", self.bin())

    def test_a_terminal_with_no_command_is_refused(self) -> None:
        """foot with no command starts the login shell, and that is the hole D1 closed."""
        with self.assertRaisesRegex(scn.ScenarioError, "needs -e <program>"):
            self.spawn("[foot-wayhint]", self.bin())

    def test_an_option_outside_the_allow_list_is_refused(self) -> None:
        """``--override=shell=...`` is how a scenario would put the shell back."""
        for option in ("--override=shell=/bin/sh", "--config=/tmp/foot.ini", "--server", "--hold"):
            with (
                self.subTest(option=option),
                self.assertRaisesRegex(scn.ScenarioError, "is not allowed here"),
            ):
                self.spawn(f"[foot-wayhint, {option}, -e, vi]", self.bin())

    def test_an_app_id_outside_the_convention_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "is not an app_id"):
            self.spawn("[foot-wayhint, --app-id=evil, -e, vi]", self.bin())

    def test_an_app_id_with_a_trailing_newline_is_refused(self) -> None:
        """``$`` matches before a final newline, so this is what ``re.match`` would let past."""
        with self.assertRaisesRegex(scn.ScenarioError, "is not an app_id"):
            self.spawn('[foot-wayhint, "--app-id=foot\n", -e, vi]', self.bin())

    def test_the_one_allowed_option_is_accepted(self) -> None:
        script = self.spawn("[foot-wayhint, --app-id=foot-herdr, -e, claude]", self.bin())
        self.assertEqual(
            script.steps["show"].action.payload["argv"],
            ["foot-wayhint", "--app-id=foot-herdr", "-e", "claude"],
        )

    def test_the_wrapper_that_starts_herdr_takes_no_command(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "takes no -e"):
            self.spawn("[foot-herdr, -e, vi]", self.bin())

    def test_an_absolute_path_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "bare program name"):
            self.spawn("[/usr/bin/foot]", self.bin())

    def test_a_program_that_is_not_a_terminal_is_refused(self) -> None:
        """``sh`` would be a shell in the session, which is the thing there must not be."""
        demo_bin = self.bin()
        (demo_bin / "sh").write_text("#!/bin/sh\n")
        with self.assertRaisesRegex(scn.ScenarioError, "has to start a terminal"):
            self.spawn("[sh]", demo_bin)

    def test_a_stub_may_be_given_one_file_from_the_fixtures(self) -> None:
        script = self.spawn('[foot-wayhint, -e, vi, "hints/{lang}/claude-code.yaml"]', self.bin())
        self.assertEqual(
            script.steps["show"].action.payload["argv"][-1], "hints/{lang}/claude-code.yaml"
        )

    def test_the_file_a_stub_is_given_cannot_leave_the_fixtures(self) -> None:
        for name in ("/etc/passwd", "../../etc/passwd"):
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(scn.ScenarioError, "relative path without"),
            ):
                self.spawn(f'[foot-wayhint, -e, vi, "{name}"]', self.bin())

    def test_a_stub_is_not_given_two_files(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "needs -e <program>"):
            self.spawn('[foot-wayhint, -e, vi, "a.yaml", "b.yaml"]', self.bin())

    def test_a_file_is_not_mistaken_for_a_program(self) -> None:
        """``session._check_stubs`` walks what ``programs`` returns and resolves it on PATH."""
        script = self.spawn('[foot-wayhint, -e, vi, "hints/ja/x.yaml"]', self.bin())
        self.assertEqual(scn.programs(script.steps["show"]), ["foot-wayhint", "vi"])

    def test_a_stub_that_is_not_in_demo_bin_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "no such program"):
            self.spawn("[foot-wayhint, -e, bash]", self.bin())

    def test_programs_lists_what_a_step_would_start(self) -> None:
        """What ``session._check_stubs`` walks before a compositor is up."""
        script = self.spawn("[foot-wayhint, --app-id=foot-x, -e, vi]", self.bin())
        self.assertEqual(scn.programs(script.steps["show"]), ["foot-wayhint", "vi"])
        run = parse(
            MINIMAL.replace("    cli: show\n", "    herdr: [pane, run, 'w1:p1', vi]\n"), self.bin()
        )
        self.assertEqual(scn.programs(run.steps["show"]), ["vi"])


class ShowcaseTest(unittest.TestCase):
    """Files are found by the role at the end of their name; the directory is the identity."""

    def showcases(self, *names: str) -> Path:
        root = scratch(self)
        for name in names:
            (root / name).mkdir()
        return root

    def test_a_scenario_is_found_by_its_role_suffix(self) -> None:
        root = self.showcases("herdr")
        (root / "herdr" / "02_herdr_scenario.yaml").write_text(MINIMAL)
        (root / "herdr" / "01_herdr_storyboard.md").write_text("# story")
        show = shc.load(root, "herdr")
        self.assertEqual(show.scenario.name, "02_herdr_scenario.yaml")
        self.assertEqual(show.storyboard.name, "01_herdr_storyboard.md")
        self.assertEqual(show.warnings, ())

    def test_a_name_that_does_not_match_the_directory_is_a_warning_not_an_error(self) -> None:
        """A half-renamed copy should still record, and should still say something."""
        root = self.showcases("herdr")
        (root / "herdr" / "02_terminal_scenario.yaml").write_text(MINIMAL)
        show = shc.load(root, "herdr")
        self.assertEqual(show.scenario.name, "02_terminal_scenario.yaml")
        self.assertIn("02_herdr_scenario.yaml", show.warnings[0])

    def test_two_files_with_the_same_role_are_an_error(self) -> None:
        root = self.showcases("herdr")
        (root / "herdr" / "02_herdr_scenario.yaml").write_text(MINIMAL)
        (root / "herdr" / "03_herdr_scenario.yaml").write_text(MINIMAL)
        with self.assertRaisesRegex(shc.ShowcaseError, "two files claim the scenario role"):
            shc.load(root, "herdr")

    def test_a_showcase_without_a_scenario_is_an_error(self) -> None:
        root = self.showcases("herdr")
        (root / "herdr" / "01_herdr_storyboard.md").write_text("# story")
        with self.assertRaisesRegex(shc.ShowcaseError, "no scenario"):
            shc.load(root, "herdr")

    def test_discover_skips_what_it_cannot_read(self) -> None:
        root = self.showcases("herdr", "empty")
        (root / "herdr" / "02_herdr_scenario.yaml").write_text(MINIMAL)
        self.assertEqual([s.name for s in shc.discover(root)], ["herdr"])


class PaneProgramTest(unittest.TestCase):
    """``demo/bin/idle`` is what a pane runs instead of a shell, so what it may exec is fixed."""

    def idle(self):
        loader = importlib.machinery.SourceFileLoader("demo_idle", str(BIN / "idle"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_the_startable_names_are_written_out_not_listed(self) -> None:
        """A listing would grow the answer every time somebody adds a file to demo/bin."""
        self.assertEqual(self.idle().STARTABLE, ("claude", "codex", "vi"))

    def test_a_name_outside_the_list_starts_nothing(self) -> None:
        idle = self.idle()
        for name in ("foot-wayhint", "idle", "sh", "", "../vi"):
            with self.subTest(name=name):
                self.assertIsNone(idle.target(name))

    def test_the_demos_own_stubs_are_startable(self) -> None:
        idle = self.idle()
        for name in idle.STARTABLE:
            with self.subTest(name=name):
                self.assertEqual(idle.target(name), BIN / name)

    def test_a_stub_that_is_a_symlink_starts_nothing(self) -> None:
        """The name is checked, and then the file: a symlink runs something else under it."""
        here = scratch(self)
        (here / "claude").symlink_to("/bin/echo")
        self.assertIsNone(self.idle().target("claude", here))


class SheetViewerTest(unittest.TestCase):
    """``demo/bin/vi`` shows a real sheet, because the 5-minute cut reads it out loud."""

    def viewer(self):
        loader = importlib.machinery.SourceFileLoader("demo_vi", str(BIN / "vi"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def root(self, **files: str) -> Path:
        root = scratch(self)
        for name, text in files.items():
            (root / name).write_text(text)
        os.environ[self.viewer().ROOT_ENV] = str(root)
        self.addCleanup(os.environ.pop, self.viewer().ROOT_ENV, None)
        return root

    def test_the_status_line_is_named_relative_to_the_session_and_fits(self) -> None:
        """A wrapped status line scrolls the first line of the file off the top."""
        vi = self.viewer()
        root = self.root()
        (root / "hints").mkdir()
        (root / "hints" / "ja").mkdir()
        (root / "hints" / "ja" / "claude-code.yaml").write_text("id: x\n")
        screen = vi.screen(*vi.opened([str(root / "hints" / "ja" / "claude-code.yaml")]))
        self.assertIn('"hints/ja/claude-code.yaml" 1L, 6B', screen[-1])
        self.assertLessEqual(len(screen[-1].replace(vi.STATUS, "").replace(vi.OFF, "")), vi.COLUMNS)

    def test_it_shows_the_top_of_the_file_and_the_real_line_count(self) -> None:
        vi = self.viewer()
        body = "".join(f"line{n}: value\n" for n in range(1, 31))
        self.root(**{"sheet.yaml": body})
        screen = vi.screen(*vi.opened(["sheet.yaml"]))
        self.assertEqual(len(screen), vi.ROWS + 1)
        self.assertIn("line1", screen[0])
        self.assertIn(f"line{vi.ROWS}", screen[vi.ROWS - 1])
        self.assertIn(f'"sheet.yaml" 30L, {len(body)}B', screen[-1])

    def test_a_short_file_is_padded_the_way_vi_pads_it(self) -> None:
        vi = self.viewer()
        self.root(**{"sheet.yaml": "id: x\n"})
        screen = vi.screen(*vi.opened(["sheet.yaml"]))
        self.assertEqual(len(screen), vi.ROWS + 1)
        self.assertIn("~", screen[1])

    def test_a_long_line_is_cut_to_a_fixed_width(self) -> None:
        """One long line must not reflow the window; two recordings have to match."""
        vi = self.viewer()
        self.root(**{"sheet.yaml": "title: " + "あ" * 80 + "\n"})
        screen = vi.screen(*vi.opened(["sheet.yaml"]))
        self.assertLessEqual(screen[0].count("あ"), vi.COLUMNS // 2)

    def test_a_file_outside_the_session_is_refused(self) -> None:
        vi = self.viewer()
        self.root(**{"sheet.yaml": "id: x\n"})
        for name in ("../escape.yaml", "/etc/passwd"):
            with (
                self.subTest(name=name),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                vi.opened([name])

    def test_a_symlink_is_refused(self) -> None:
        vi = self.viewer()
        root = self.root()
        (root / "sheet.yaml").symlink_to("/etc/passwd")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            vi.opened(["sheet.yaml"])

    def test_no_argument_means_an_empty_buffer(self) -> None:
        vi = self.viewer()
        screen = vi.screen(*vi.opened([]))
        self.assertIn('"" 0L, 0B', screen[-1])


class WrapperTest(unittest.TestCase):
    """The terminal wrappers in ``demo/bin``, on the paths that refuse and exec nothing.

    These do run the wrapper as a real subprocess -- there is no other way to check a shell
    script's own argument handling. What they do not start is **foot and Herdr**: every case
    here stops in the wrapper's argument checking, several lines before ``exec /usr/bin/foot``,
    so nothing is drawn, no compositor is needed and no server is contacted. That is what makes
    them safe to run in ``./scripts/check`` next to the pure parsing tests.
    """

    def run_wrapper(self, wrapper: Path, *args: str, herdr: str | None = None):
        env = {k: v for k, v in os.environ.items() if k != sess.HERDR_BIN_ENV}
        if herdr is not None:
            env[sess.HERDR_BIN_ENV] = herdr
        return subprocess.run(
            [str(wrapper), *args], capture_output=True, text=True, timeout=30, env=env
        )

    def test_the_herdr_wrapper_refuses_to_run_without_the_resolved_path(self) -> None:
        done = self.run_wrapper(BIN / "foot-herdr")
        self.assertEqual(done.returncode, 1)
        self.assertIn(sess.HERDR_BIN_ENV, done.stderr)

    def test_the_herdr_wrapper_refuses_a_relative_herdr(self) -> None:
        done = self.run_wrapper(BIN / "foot-herdr", herdr="herdr")
        self.assertEqual(done.returncode, 1)
        self.assertIn("absolute path", done.stderr)

    def test_the_herdr_wrapper_refuses_an_option_outside_its_list(self) -> None:
        done = self.run_wrapper(BIN / "foot-herdr", "--override=shell=/bin/sh", herdr="/bin/true")
        self.assertEqual(done.returncode, 1)
        self.assertIn("option not allowed", done.stderr)

    def test_the_herdr_wrapper_takes_no_command(self) -> None:
        done = self.run_wrapper(BIN / "foot-herdr", "vi", herdr="/bin/true")
        self.assertEqual(done.returncode, 1)
        self.assertIn("takes no command", done.stderr)

    def test_the_terminal_wrapper_refuses_to_start_without_a_program(self) -> None:
        done = self.run_wrapper(BIN / "foot-wayhint")
        self.assertEqual(done.returncode, 1)
        self.assertIn("login shell", done.stderr)

    def test_the_terminal_wrapper_refuses_an_option_outside_its_list(self) -> None:
        for option in ("--override=shell=/bin/sh", "--config=/tmp/foot.ini", "--server"):
            with self.subTest(option=option):
                done = self.run_wrapper(BIN / "foot-wayhint", option, "-e", "vi")
                self.assertEqual(done.returncode, 1)
                self.assertIn("option not allowed", done.stderr)

    def test_the_terminal_wrapper_refuses_a_program_that_is_not_a_stub(self) -> None:
        done = self.run_wrapper(BIN / "foot-wayhint", "-e", "/bin/sh")
        self.assertEqual(done.returncode, 1)
        self.assertIn("not one of the demo's stubs", done.stderr)

    def test_the_terminal_wrapper_refuses_a_stub_from_another_directory(self) -> None:
        done = self.run_wrapper(BIN / "foot-wayhint", "-e", "/tmp/vi")
        self.assertEqual(done.returncode, 1)
        self.assertIn("started from", done.stderr)

    def test_the_terminal_wrapper_refuses_a_file_outside_the_session(self) -> None:
        here = scratch(self)
        (here / "config").mkdir()
        env = {**os.environ, "WAYHINT_DEMO_CONFIG": str(here / "config")}
        done = subprocess.run(
            [str(BIN / "foot-wayhint"), "-e", "vi", "/etc/passwd"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("has to be inside", done.stderr)

    def test_the_terminal_wrapper_needs_the_session_config_for_a_file(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "WAYHINT_DEMO_CONFIG"}
        done = subprocess.run(
            [str(BIN / "foot-wayhint"), "-e", "vi", "sheet.yaml"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("WAYHINT_DEMO_CONFIG", done.stderr)

    def test_the_terminal_wrapper_refuses_a_stub_that_is_a_symlink(self) -> None:
        """Run from a copy of the directory: the real ``demo/bin`` is left as it is."""
        here = scratch(self)
        shutil.copy(BIN / "foot-wayhint", here / "foot-wayhint")
        (here / "vi").symlink_to("/bin/echo")
        done = self.run_wrapper(here / "foot-wayhint", "-e", "vi")
        self.assertEqual(done.returncode, 1)
        self.assertIn("is a symlink", done.stderr)


class CommandLineNameTest(unittest.TestCase):
    """``--showcase`` and friends become paths too, so they follow the scenario's own rule."""

    def run_cli(self, *argv: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main([*argv, "--showcases", str(scratch(self))])
        return code, err.getvalue()

    def test_a_name_that_is_not_one_is_refused(self) -> None:
        for flag, value in (
            ("--showcase", "show\n"),
            ("--showcase", "Show"),
            ("--showcase", "sh ow"),
            ("--variant", "../escape"),
            ("--only", "a,Show"),
            ("--from", "sh ow"),
        ):
            with self.subTest(flag=flag, value=value):
                code, err = self.run_cli(flag, value)
                self.assertEqual(code, 1)
                self.assertIn("has to be lower-case", err)

    def test_every_name_on_the_command_line_goes_through_the_one_check(self) -> None:
        seen: list[tuple[str, str]] = []
        original = nm.validate_name
        self.addCleanup(setattr, nm, "validate_name", original)
        nm.validate_name = lambda kind, value: (seen.append((kind, value)), value)[1]
        self.run_cli("--showcase", "herdr", "--variant", "60s", "--only", "a,b", "--from", "a")
        self.assertEqual(
            seen[:5],
            [
                ("--showcase value", "herdr"),
                ("--variant value", "60s"),
                ("--from value", "a"),
                ("--only value", "a"),
                ("--only value", "b"),
            ],
        )
        # ... and the showcase resolver reaches the same function, rather than its own regex.
        self.assertIn(("showcase name", "herdr"), seen)


class WaitGroupGoneTest(unittest.TestCase):
    """The tear-down waits for the whole process group, and never signals its own.

    ``os.killpg`` is a mock in every case here: a real one on the wrong group takes the test
    runner with it, which is exactly the accident the guard exists for.
    """

    class Proc:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return 0  # already exited, so `_signal_group` has nothing to send

        def wait(self, timeout=None):
            return 0

    def session(self) -> headless_mod.HeadlessSession:
        session = headless_mod.HeadlessSession(scratch(self))
        self.addCleanup(shutil.rmtree, session.home, ignore_errors=True)
        return session

    def killpg(self, *side_effect):
        patch = unittest.mock.patch.object(headless_mod.os, "killpg")
        mock = patch.start()
        self.addCleanup(patch.stop)
        if side_effect:
            mock.side_effect = side_effect
        return mock

    def test_it_refuses_pid_zero(self) -> None:
        """``killpg(0, ...)`` is 'my own group', and it would kill whatever is running this."""
        killpg = self.killpg()
        with self.assertRaisesRegex(ValueError, "own"):
            self.session()._wait_group_gone(self.Proc(0))
        killpg.assert_not_called()

    def test_it_refuses_its_own_process_group(self) -> None:
        killpg = self.killpg()
        with self.assertRaisesRegex(ValueError, "own"):
            self.session()._wait_group_gone(self.Proc(os.getpgrp()))
        killpg.assert_not_called()

    def test_it_returns_as_soon_as_the_group_is_empty(self) -> None:
        killpg = self.killpg(ProcessLookupError())
        self.session()._wait_group_gone(self.Proc(os.getpgrp() + 1))
        self.assertEqual(killpg.call_count, 1)  # one probe, and nothing to kill
        self.assertEqual(killpg.call_args.args[1], 0)

    def test_signal_group_refuses_pid_zero(self) -> None:
        """Every signal in the file goes through the same guard, not only the wait."""
        killpg = self.killpg()
        with self.assertRaisesRegex(ValueError, "own"):
            self.session()._signal_group(self.Proc(0), signal.SIGTERM)
        killpg.assert_not_called()

    def test_signal_group_refuses_its_own_process_group(self) -> None:
        killpg = self.killpg()
        with self.assertRaisesRegex(ValueError, "own"):
            self.session()._signal_group(self.Proc(os.getpgrp()), signal.SIGKILL)
        killpg.assert_not_called()

    def test_it_escalates_to_sigkill_when_the_group_stays(self) -> None:
        """A group that outlives the timeout is killed, and then waited for again."""
        patch = unittest.mock.patch.object(headless_mod, "GROUP_GONE_TIMEOUT", 0.1)
        patch.start()
        self.addCleanup(patch.stop)
        killpg = self.killpg()
        killpg.side_effect = [*[None] * 40, None, ProcessLookupError()]
        self.session()._wait_group_gone(self.Proc(os.getpgrp() + 1))
        signals = [call.args[1] for call in killpg.call_args_list]
        self.assertIn(signal.SIGKILL, signals)
        self.assertEqual(signals[-1], 0, "it waits again after the kill")


class KeepDirectoriesTest(unittest.TestCase):
    """The session's directories go only when the process group is *seen* to be empty.

    Something still running can still write into them, and a directory left in /tmp is a
    smaller problem than deleting files a live process is holding.
    """

    def session(self) -> headless_mod.HeadlessSession:
        session = headless_mod.HeadlessSession(scratch(self))
        self.addCleanup(shutil.rmtree, session.home, ignore_errors=True)
        session._procs = [WaitGroupGoneTest.Proc(os.getpgrp() + 1)]
        return session

    def patch(self, name: str, target, **kw):
        patch = unittest.mock.patch.object(target, name, **kw)
        mock = patch.start()
        self.addCleanup(patch.stop)
        return mock

    def tear_down(self, *killpg_effect):
        self.patch("GROUP_GONE_TIMEOUT", headless_mod, new=0.1)
        killpg = self.patch("killpg", headless_mod.os)
        if killpg_effect:
            killpg.side_effect = killpg_effect[0]
        rmtree = self.patch("rmtree", headless_mod.shutil)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.session()._tear_down()
        return rmtree, err.getvalue()

    def test_a_group_that_never_empties_keeps_the_directories(self) -> None:
        rmtree, err = self.tear_down()  # killpg always answers "still there"
        rmtree.assert_not_called()
        self.assertIn("leaving", err)
        self.assertIn("timed out", err)

    def test_a_permission_error_keeps_the_directories(self) -> None:
        rmtree, err = self.tear_down(PermissionError(1, "not yours"))
        rmtree.assert_not_called()
        self.assertIn("leaving", err)

    def test_a_group_seen_to_go_lets_the_directories_be_removed(self) -> None:
        rmtree, err = self.tear_down(ProcessLookupError())
        self.assertEqual(rmtree.call_count, 2)  # the runtime directory and the home
        self.assertEqual(err, "")


class StartupUnwindTest(unittest.TestCase):
    """A failure before ``with`` begins has to take down whatever already started.

    Until ``__enter__`` returns there is no ``with`` block, so nothing would call ``__exit__``
    -- and a compositor started two lines earlier would be left running with its socket in a
    directory nobody removes. Both sessions build themselves on an ``ExitStack`` for this.
    """

    def headless(self) -> headless_mod.HeadlessSession:
        session = headless_mod.HeadlessSession(scratch(self))
        session.compositor = "labwc"  # nothing is actually started; the spawn is stubbed
        self.addCleanup(shutil.rmtree, session.home, ignore_errors=True)
        self.addCleanup(shutil.rmtree, session.runtime, ignore_errors=True)
        # These cases stub out the tear-down, which is what would close the log.
        self.addCleanup(lambda: session.log.close() if session.log is not None else None)
        return session

    def test_a_socket_that_never_appears_tears_the_session_down(self) -> None:
        session = self.headless()
        started: list[str] = []
        torn: list[bool] = []

        def never(path, what):
            raise RuntimeError(what)

        session._start_bus = lambda: started.append("bus")
        session._spawn = lambda argv, env: started.append(argv[0])
        session._wait_for = never
        session._tear_down = lambda: torn.append(True)
        with self.assertRaises(RuntimeError):
            session.__enter__()
        self.assertEqual(started, ["bus", "labwc"])
        self.assertTrue(torn, "the compositor was left running")

    def test_a_session_that_starts_is_not_torn_down(self) -> None:
        session = self.headless()
        torn: list[bool] = []
        session._start_bus = lambda: None
        session._spawn = lambda argv, env: None
        session._wait_for = lambda path, what: None
        session.wayhint = lambda *args: ""
        session._tear_down = lambda: torn.append(True)
        self.assertIs(session.__enter__(), session)
        self.assertEqual(torn, [])

    def test_the_session_is_stopped_in_the_reverse_of_the_order_it_started(self) -> None:
        """The bus is given to the two after it, so it has to be the last one left running."""

        class Proc:
            def __init__(self, name: str) -> None:
                self.name, self.pid = name, 0

            def poll(self):
                return None

            def wait(self, timeout=None):
                return 0

        session = self.headless()
        started: list[str] = []
        stopped: list[str] = []

        def start_bus() -> None:
            started.append("bus")
            session._bus = Proc("bus")

        def spawn(argv, _env) -> None:
            started.append(Path(argv[0]).name)
            session._procs.append(Proc(Path(argv[0]).name))

        session._start_bus = start_bus
        session._spawn = spawn
        session._wait_for = lambda path, what: None
        session.wayhint = lambda *args: ""
        session._signal_group = lambda proc, sig: (
            stopped.append(proc.name) if sig == signal.SIGTERM else None
        )
        session._wait_group_gone = lambda proc: True  # the fakes have no process group
        session.__enter__()
        self.assertEqual(started, ["bus", "labwc", "wayhintd"])
        session.__exit__()
        self.assertEqual(stopped, list(reversed(started)))

    def test_the_session_log_is_closed_after_the_tear_down(self) -> None:
        """The tear-down writes into the log when it has something to report, so it goes first."""
        session = self.headless()
        seen: list[tuple[str, bool]] = []
        session._start_bus = lambda: None
        session._spawn = lambda argv, env: None
        session._wait_for = lambda path, what: (_ for _ in ()).throw(RuntimeError(what))
        session._tear_down = lambda: seen.append(("tear-down", session.log.closed))
        with self.assertRaises(RuntimeError):
            session.__enter__()
        self.assertEqual(seen, [("tear-down", False)], "the log was closed too early")
        self.assertTrue(session.log.closed, "the log was left open")

    def test_a_demo_session_closes_the_headless_one_when_a_check_fails(self) -> None:
        class Fake:
            def __init__(self, home: Path) -> None:
                self.home, self.entered, self.exited = home, False, False

            def __enter__(self):
                self.entered = True
                return self

            def __exit__(self, *_exc):
                self.exited = True

            def env(self, **_kw):
                return {"XDG_CONFIG_HOME": str(self.home), "PATH": ""}

        work = scratch(self)
        demo = sess.DemoSession(parse(MINIMAL), work, work, work)
        # Building one makes a real HeadlessSession, and that makes its HOME in /tmp. The fake
        # below takes its place, so nothing else will ever remove it.
        self.addCleanup(shutil.rmtree, demo.session.home, ignore_errors=True)
        fake = Fake(work)
        demo.session = fake
        demo._check_stubs = lambda: (_ for _ in ()).throw(sess.DemoError("no stub"))
        demo.stop_herdr = lambda: None
        with self.assertRaisesRegex(sess.DemoError, "no stub"):
            demo.__enter__()
        self.assertTrue(fake.entered)
        self.assertTrue(fake.exited, "the headless session was left running")


if __name__ == "__main__":
    unittest.main()
