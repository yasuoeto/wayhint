"""The demo's scenario parser and showcase resolver, without a compositor.

These run in ``./scripts/check``: they are pure reading and checking, and they are the only
place the *refusals* are covered. A scenario that is wrong has to be refused before a recording
starts, because by then a compositor is up and the mistake costs a minute instead of a
millisecond. The real ``demo/showcases/`` tree is never renamed or duplicated to test the
naming rules -- every case here builds its own directory in a temporary one.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools.demo import __main__ as cli
from tools.demo import scenario as scn
from tools.demo import session as sess
from tools.demo import showcase as shc

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


class SpawnTest(unittest.TestCase):
    """A spawn starts a terminal from ``demo/bin``, and nothing else."""

    def bin(self) -> Path:
        demo_bin = scratch(self)
        for name in ("foot-herdr", "foot-wayhint", "vi", "idle"):
            (demo_bin / name).write_text("#!/bin/sh\n")
        return demo_bin

    def spawn(self, argv: str, demo_bin: Path | None = None) -> scn.Scenario:
        text = MINIMAL.replace("    cli: show\n", f"    spawn: {{window: main, argv: {argv}}}\n")
        return parse(text, demo_bin)

    def test_a_wrapper_from_demo_bin_is_accepted(self) -> None:
        script = self.spawn("[foot-herdr]", self.bin())
        self.assertEqual(script.steps["show"].action.payload["argv"], ["foot-herdr"])

    def test_a_wrapper_with_a_stub_after_it_is_accepted(self) -> None:
        self.spawn("[foot-wayhint, vi]", self.bin())

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
            self.spawn("[foot-wayhint, bash]", self.bin())

    def test_options_are_left_alone(self) -> None:
        self.spawn("[foot-wayhint, --hold, vi]", self.bin())

    def test_programs_lists_what_a_step_would_start(self) -> None:
        """What ``session._check_stubs`` walks before a compositor is up."""
        script = self.spawn("[foot-wayhint, --hold, vi]", self.bin())
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


if __name__ == "__main__":
    unittest.main()
