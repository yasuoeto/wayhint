import json
import logging
import subprocess
import unittest
from pathlib import Path

from wayhint.config import GlobalConfig
from wayhint.context.base import ContextError, DesktopSnapshot
from wayhint.context.herdr import HerdrContextProvider
from wayhint.context.process import process_info_from_mapping
from wayhint.context.resolver import ContextResolver
from wayhint.models import DisplayConfig, Hint, HintSheet, MatchRule, OutputInfo, SourceLocation

LOC = SourceLocation(Path("x.yaml"), 1)


def setUpModule() -> None:
    logging.disable(logging.CRITICAL)  # adapters log expected failures; keep test output clean


def tearDownModule() -> None:
    logging.disable(logging.NOTSET)


DP1 = OutputInfo("DP-1", 2560, 1440)
DP2 = OutputInfo("DP-2", 1920, 1080)


def sheet(id_, app=(), argv=(), output=None, priority=0) -> HintSheet:
    return HintSheet(
        id=id_,
        title=id_,
        path=Path(f"{id_}.yaml"),
        priority=priority,
        match=MatchRule(app_id_regex=tuple(app), argv_regex=tuple(argv)),
        display=DisplayConfig(output=output),
        hints=(Hint(id=f"{id_}-h", title="H", location=LOC),),
    )


HERDR = sheet("herdr", app=["^herdr$"])
CLAUDE = sheet("claude", argv=["^claude$"])
CODEX = sheet("codex", argv=["^codex$"])
INKSCAPE = sheet("inkscape", app=["inkscape"], output="DP-2")
SHEETS = [HERDR, CLAUDE, CODEX, INKSCAPE]


class FakeDesktop:
    def __init__(self, snap=None, error=None, outputs=(DP1, DP2)):
        self.snap, self.error, self.outputs = snap, error, outputs

    def snapshot(self):
        if self.error:
            raise ContextError(self.error)
        return self.snap

    def find_output(self, name):
        return next((o for o in self.outputs if o.name == name), None)

    def focus_view(self, view_id):
        return True


class FakeHerdr:
    def __init__(self, proc, applies="herdr", raise_=False):
        self.proc, self.applies, self.raise_ = proc, applies, raise_

    def applies_to(self, app_id):
        return app_id == self.applies

    def foreground_process(self):
        if self.raise_:
            raise RuntimeError("boom")
        return self.proc


def snap(app_id, view_ref="7", output=DP1, focused=DP1, title="T"):
    return DesktopSnapshot(
        app_id=app_id, title=title, view_ref=view_ref, output=output, focused_output=focused
    )


def proc(argv, name=None):
    return process_info_from_mapping(
        {"pid": 5, "name": name or argv[0], "argv": argv, "cmdline": " ".join(argv), "cwd": "/"}
    )


class ResolverTest(unittest.TestCase):
    cfg = GlobalConfig()

    def test_desktop_unavailable_yields_error(self) -> None:
        ctx = ContextResolver(FakeDesktop(error="desktop context unavailable")).resolve(
            SHEETS, self.cfg
        )
        self.assertEqual(ctx.error, "desktop context unavailable")
        self.assertIsNone(ctx.active_sheet)

    def test_desktop_app(self) -> None:
        ctx = ContextResolver(FakeDesktop(snap("org.inkscape.Inkscape"))).resolve(SHEETS, self.cfg)
        self.assertEqual(ctx.active_sheet, "inkscape")
        self.assertIsNone(ctx.parent_context)
        self.assertEqual(ctx.output, DP2)  # sheet output override wins
        self.assertEqual(ctx.view_ref, "7")

    def test_unknown_app(self) -> None:
        ctx = ContextResolver(FakeDesktop(snap("foot"))).resolve(SHEETS, self.cfg)
        self.assertIsNone(ctx.active_sheet)
        self.assertEqual(ctx.desktop_app, "foot")
        self.assertEqual(ctx.output, DP1)

    def test_nested_claude_and_codex(self) -> None:
        for argv, expect in ((["claude"], "claude"), (["node", "/x/codex"], "codex")):
            with self.subTest(argv=argv):
                r = ContextResolver(
                    FakeDesktop(snap("herdr")), [FakeHerdr(proc(argv, name="node"))]
                )
                ctx = r.resolve(SHEETS, self.cfg)
                self.assertEqual(ctx.active_sheet, expect)
                self.assertEqual(ctx.parent_context, "herdr")
                self.assertEqual(ctx.foreground_process.argv, tuple(argv))

    def test_nested_unknown_process_falls_back_to_parent(self) -> None:
        r = ContextResolver(FakeDesktop(snap("herdr")), [FakeHerdr(proc(["bash"]))])
        ctx = r.resolve(SHEETS, self.cfg)
        self.assertEqual(ctx.active_sheet, "herdr")
        self.assertEqual(ctx.parent_context, "herdr")

    def test_nested_provider_failure_is_contained(self) -> None:
        for prov in (FakeHerdr(None), FakeHerdr(None, raise_=True)):
            ctx = ContextResolver(FakeDesktop(snap("herdr")), [prov]).resolve(SHEETS, self.cfg)
            self.assertEqual(ctx.active_sheet, "herdr")
            self.assertIsNone(ctx.foreground_process)

    def test_provider_not_consulted_for_other_apps(self) -> None:
        r = ContextResolver(
            FakeDesktop(snap("org.inkscape.Inkscape")), [FakeHerdr(proc(["claude"]))]
        )
        self.assertEqual(r.resolve(SHEETS, self.cfg).active_sheet, "inkscape")

    def test_output_fallback_chain(self) -> None:
        r = ContextResolver(FakeDesktop(snap("foot", output=None, focused=DP2)))
        self.assertEqual(r.resolve(SHEETS, self.cfg).output, DP2)
        r = ContextResolver(FakeDesktop(snap("foot", output=None, focused=None)))
        self.assertIsNone(r.resolve(SHEETS, self.cfg).output)
        cfg = GlobalConfig(display=DisplayConfig(output="DP-2"))
        self.assertEqual(r.resolve(SHEETS, cfg).output, DP2)
        # override naming a missing output falls through to the view's output
        r = ContextResolver(FakeDesktop(snap("org.inkscape.Inkscape"), outputs=(DP1,)))
        self.assertEqual(r.resolve(SHEETS, self.cfg).output, DP1)


PANE = {"id": "cli", "result": {"pane": {"pane_id": "wG:p1", "focused": True}}}


def info(procs, leader=None):
    return {
        "result": {
            "process_info": {
                "pane_id": "wG:p1",
                "shell_pid": 1,
                "foreground_process_group_id": leader,
                "foreground_processes": procs,
            }
        }
    }


class HerdrAdapterTest(unittest.TestCase):
    def make(self, responses):
        calls = []

        def runner(argv):
            calls.append(list(argv))
            key = " ".join(argv[1:3])
            r = responses[key]
            if isinstance(r, Exception):
                raise r
            return r if isinstance(r, str) else json.dumps(r)

        return HerdrContextProvider(runner=runner), calls

    def test_applies_to(self) -> None:
        p = HerdrContextProvider(runner=lambda a: "")
        self.assertTrue(p.applies_to("herdr"))
        self.assertTrue(p.applies_to("com.example.Herdr"))
        self.assertFalse(p.applies_to("foot"))
        self.assertFalse(p.applies_to(None))

    def test_passes_pane_id_and_picks_group_leader(self) -> None:
        procs = [
            {"pid": 10, "name": "bash", "argv": ["bash"], "cmdline": "bash"},
            {
                "pid": 11,
                "name": "node",
                "argv": ["node", "/opt/codex"],
                "cmdline": "node /opt/codex",
                "cwd": "/w",
            },
        ]
        p, calls = self.make({"pane current": PANE, "pane process-info": info(procs, leader=11)})
        pi = p.foreground_process()
        self.assertEqual(calls[1][:5], ["herdr", "pane", "process-info", "--pane", "wG:p1"])
        self.assertEqual(
            (pi.pid, pi.name, pi.argv, pi.cwd), (11, "node", ("node", "/opt/codex"), "/w")
        )

    def test_without_leader_takes_last(self) -> None:
        procs = [
            {"pid": 1, "name": "bash", "argv": ["bash"]},
            {"pid": 2, "name": "claude", "argv": ["claude"]},
        ]
        p, _ = self.make({"pane current": PANE, "pane process-info": info(procs)})
        self.assertEqual(p.foreground_process().name, "claude")

    def test_failures_return_none(self) -> None:
        cases = {
            "missing binary": {"pane current": FileNotFoundError("herdr")},
            "timeout": {"pane current": subprocess.TimeoutExpired("herdr", 3)},
            "nonzero": {"pane current": subprocess.CalledProcessError(1, "herdr")},
            "garbage": {"pane current": "not json"},
            "no procs": {"pane current": PANE, "pane process-info": info([])},
            "no pane": {"pane current": {"result": {"pane": {}}}},
        }
        for name, responses in cases.items():
            with self.subTest(name):
                p, _ = self.make(responses)
                self.assertIsNone(p.foreground_process())


class ProcessInfoTest(unittest.TestCase):
    def test_normalisation(self) -> None:
        pi = process_info_from_mapping({"pid": 3, "argv": ["/usr/bin/claude", "--x"]})
        self.assertEqual((pi.name, pi.cmdline), ("claude", "/usr/bin/claude --x"))
        self.assertIsNone(process_info_from_mapping({"name": "x"}))
        self.assertIsNone(process_info_from_mapping({"pid": True}))
        self.assertIsNone(process_info_from_mapping({"pid": 1}))
