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
import subprocess
import tempfile
import unittest
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
        with self.assertRaisesRegex(scn.ScenarioError, "needs -e <program> last"):
            self.spawn("[foot-wayhint]", self.bin())

    def test_an_option_outside_the_allow_list_is_refused(self) -> None:
        """``--override=shell=...`` is how a scenario would put the shell back."""
        for option in ("--override=shell=/bin/sh", "--config=/tmp/foot.ini", "--server", "--hold"):
            with self.subTest(option=option), self.assertRaisesRegex(
                scn.ScenarioError, "is not allowed here"
            ):
                self.spawn(f"[foot-wayhint, {option}, -e, vi]", self.bin())

    def test_an_app_id_outside_the_convention_is_refused(self) -> None:
        with self.assertRaisesRegex(scn.ScenarioError, "is not an app_id"):
            self.spawn("[foot-wayhint, --app-id=evil, -e, vi]", self.bin())

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


class WrapperTest(unittest.TestCase):
    """The terminal wrappers in ``demo/bin``, on the paths that refuse and exec nothing.

    Every case here stops in the wrapper's own argument checking, before ``exec foot``, so no
    terminal and no Herdr is started -- which is what makes these safe in ``./scripts/check``.
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
