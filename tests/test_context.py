import inspect
import json
import logging
import os
import subprocess
import unittest
import unittest.mock
from pathlib import Path

from wayhint.config import GlobalConfig
from wayhint.context import herdr
from wayhint.context.base import ContextError, DesktopSnapshot
from wayhint.context.herdr import HerdrContextProvider, _herdr_env
from wayhint.context.process import process_info_from_mapping
from wayhint.context.resolver import ContextResolver
from wayhint.context.wayfire import WayfireContextProvider
from wayhint.daemon import _nested_providers
from wayhint.models import DisplayConfig, Hint, HintSheet, MatchRule, OutputInfo, SourceLocation
from wayhint.selection import sort_hints, visible_hints

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

    def foreground_process(self, app_id=None):
        if self.raise_:
            raise RuntimeError("boom")
        return self.proc


class FakeProc:
    """Stands in for ProcAdapter: a terminal app_id, and the command running in it."""

    def __init__(self, proc, applies="foot"):
        self.proc, self.applies = proc, applies

    def applies_to(self, app_id):
        return app_id == self.applies

    def foreground_process(self, app_id=None):
        self.seen = app_id  # the resolver hands over what applies_to was asked about
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

    def test_a_terminal_without_a_sheet_still_resolves_its_foreground_process(self) -> None:
        """foot has no sheet of its own; the command running in it is what the user wants (0027).

        The nested provider is asked because the ``app_id`` says a terminal is in front, not
        because somebody wrote hints for that terminal.
        """
        vi = sheet("vi", argv=["^vi$"])
        provider = FakeProc(proc(["vi", "notes.txt"]), applies="foot.p42")
        ctx = ContextResolver(FakeDesktop(snap("foot.p42")), [provider]).resolve(
            [*SHEETS, vi], self.cfg
        )
        self.assertEqual(provider.seen, "foot.p42")  # the app_id carries the window's pid (0027)
        self.assertEqual(ctx.active_sheet, "vi")
        self.assertIsNone(ctx.parent_context)  # no desktop sheet means no parent to filter by
        self.assertEqual(ctx.chain, ("FakeProc",))
        self.assertEqual(ctx.foreground_process.name, "vi")

    def test_a_window_with_a_pid_suffix_matches_the_terminals_own_sheet(self) -> None:
        """``docs/TERMINALS.md`` promises ``app_id_regex: ["^foot$"]`` keeps working (0027).

        The suffix identifies the window, so it stays in ``desktop_app``; it is not part of what
        the sheet is written against, so it must not reach the match.
        """
        foot = sheet("foot", app=["^foot$"])
        vi = sheet("vi", argv=["^vi$"])
        sheets = [*SHEETS, foot, vi]

        ctx = ContextResolver(FakeDesktop(snap("foot.p42"))).resolve(sheets, self.cfg)
        self.assertEqual(ctx.active_sheet, "foot")
        self.assertEqual(ctx.desktop_app, "foot.p42")

        provider = FakeProc(proc(["vi"]), applies="foot.p42")
        nested = ContextResolver(FakeDesktop(snap("foot.p42")), [provider]).resolve(
            sheets, self.cfg
        )
        self.assertEqual((nested.active_sheet, nested.parent_context), ("vi", "foot"))

    def test_the_chain_records_the_provider_that_was_asked(self) -> None:
        """Including one that answered nothing: the chain says where to look, not what was found."""
        providers = [FakeProc(None), FakeHerdr(proc(["claude"]))]
        ctx = ContextResolver(FakeDesktop(snap("foot")), providers).resolve(SHEETS, self.cfg)
        self.assertEqual(ctx.chain, ("FakeProc",))  # the first match decides; Herdr is not asked
        self.assertIsNone(ctx.active_sheet)
        bare = ContextResolver(FakeDesktop(snap("foot"))).resolve(SHEETS, self.cfg)
        self.assertEqual(bare.chain, ())

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


class NestedParentHintsTest(unittest.TestCase):
    """Resolver and selection together: which parent hints a nested context shows (0034).

    No ``nested.parent_tags`` in the config, as a fresh install has it: what the overlay mixes
    in is decided by the parent sheet alone.
    """

    cfg = GlobalConfig()

    @staticmethod
    def make(id_, hints, app=(), argv=(), export=None):
        path = Path(f"{id_}.yaml")
        return HintSheet(
            id=id_,
            title=id_,
            path=path,
            match=MatchRule(app_id_regex=tuple(app), argv_regex=tuple(argv)),
            export_tags=export,
            hints=tuple(
                Hint(id=h, title=h, location=SourceLocation(path, i + 1), tags=tuple(tags))
                for i, (h, tags) in enumerate(hints)
            ),
        )

    def setUp(self) -> None:
        self.herdr = self.make(
            "herdr", [("split", ["pane"]), ("close", [])], app=["^herdr$"], export=("pane",)
        )
        self.foot = self.make("foot", [("scroll", []), ("theme", [])], app=["^foot$"])
        self.vi = self.make("vi", [("quit", [])], argv=["^vi$"])
        self.claude = self.make("claude", [("plan", [])], argv=["claude"])

    def shown(self, sheets, app_id, provider):
        ctx = ContextResolver(FakeDesktop(snap(app_id)), [provider]).resolve(sheets, self.cfg)
        by_id = {s.id: s for s in sheets}
        active = by_id.get(ctx.active_sheet)
        parent = by_id.get(ctx.parent_context) if ctx.parent_context else None
        ids = [h.id for h in sort_hints(visible_hints(active, parent, self.cfg.parent_tags))]
        return ctx, ids

    def test_a_herdr_exports_only_tagged_hints_to_claude(self) -> None:
        sheets = [self.herdr, self.foot, self.vi, self.claude]
        ctx, ids = self.shown(sheets, "herdr", FakeHerdr(proc(["claude"])))
        self.assertEqual((ctx.active_sheet, ctx.parent_context), ("claude", "herdr"))
        self.assertEqual(ids, ["plan", "split"])

    def test_b_foot_without_export_mixes_all_foot_hints(self) -> None:
        sheets = [self.herdr, self.foot, self.vi, self.claude]
        ctx, ids = self.shown(sheets, "foot.p123", FakeProc(proc(["vi"]), applies="foot.p123"))
        self.assertEqual((ctx.active_sheet, ctx.parent_context), ("vi", "foot"))
        self.assertEqual(ids, ["quit", "scroll", "theme"])
        self.assertFalse({"split", "close"} & set(ids))  # nothing of herdr's

    def test_c_foot_without_sheet_shows_only_the_child(self) -> None:
        sheets = [self.herdr, self.vi, self.claude]
        ctx, ids = self.shown(sheets, "foot.p123", FakeProc(proc(["vi"]), applies="foot.p123"))
        self.assertEqual(ctx.active_sheet, "vi")
        self.assertIsNone(ctx.parent_context)
        self.assertEqual(ids, ["quit"])


class HerdrAdapterTest(unittest.TestCase):
    def make(self, responses, clock=None):
        """Returns the provider, the argv of each call, and the timeout each was given."""
        calls: list[list[str]] = []
        timeouts: list[float] = []

        def runner(argv, timeout):
            calls.append(list(argv))
            timeouts.append(timeout)
            key = " ".join(argv[1:3])
            r = responses[key]
            if isinstance(r, Exception):
                raise r
            return r if isinstance(r, str) else json.dumps(r)

        kw = {"clock": clock} if clock is not None else {}
        return HerdrContextProvider(runner=runner, **kw), calls, timeouts

    def test_applies_to(self) -> None:
        p = HerdrContextProvider(runner=lambda a, t: "")
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
        p, calls, _ = self.make({"pane current": PANE, "pane process-info": info(procs, leader=11)})
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
        p, _calls, _ = self.make({"pane current": PANE, "pane process-info": info(procs)})
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
                p, _calls, _ = self.make(responses)
                self.assertIsNone(p.foreground_process())


class WayfireAdapterTest(unittest.TestCase):
    """An IPC failure and "no window is focused" are different answers (DESIGN Failure modes)."""

    OUTPUT = {"name": "DP-1", "geometry": {"width": 2560, "height": 1440}}

    def provider(self, **calls):
        sock = self.Sock(**calls)
        provider = WayfireContextProvider()
        provider._connect = lambda: sock
        return provider

    class Sock:
        def __init__(self, view=None, output=None, per_output=None, fail=()):
            self.view, self.output, self.per_output, self.fail = view, output, per_output, fail

        def _answer(self, name, value):
            if name in self.fail:
                raise RuntimeError(f"{name} failed")
            return value

        def get_focused_view(self):
            return self._answer("get_focused_view", self.view)

        def get_focused_output(self):
            return self._answer("get_focused_output", self.output)

        def get_output(self, _id):
            return self._answer("get_output", self.per_output)

        def close(self):
            return None

    def test_no_focused_window_is_a_snapshot_without_an_app(self) -> None:
        snap = self.provider(view=None, output=self.OUTPUT).snapshot()
        self.assertIsNone(snap.app_id)
        self.assertIsNone(snap.view_ref)
        self.assertEqual(snap.focused_output, DP1)  # enough to place the overlay

    def test_a_failed_call_is_an_error_not_an_empty_desktop(self) -> None:
        for call in ("get_focused_view", "get_focused_output"):
            with self.subTest(call=call):
                provider = self.provider(view={"app-id": "foot"}, output=self.OUTPUT, fail=(call,))
                with self.assertRaises(ContextError) as caught:
                    provider.snapshot()
                self.assertIn(call, str(caught.exception))

    def test_the_view_output_falls_back_to_the_focused_one(self) -> None:
        provider = self.provider(
            view={"app-id": "foot", "title": "t", "id": 7, "output-id": 3},
            output=self.OUTPUT,
            fail=("get_output",),
        )
        snap = provider.snapshot()
        self.assertEqual((snap.app_id, snap.view_ref), ("foot", "7"))
        self.assertEqual(snap.output, DP1)


UNFOCUSED = {"result": {"pane": {"pane_id": "wH:p1", "focused": False}}}


def pane_list(*panes):
    return {"result": {"panes": list(panes)}}


class HerdrEnvironmentTest(unittest.TestCase):
    """``pane current`` answers for ``HERDR_PANE_ID`` when it is set (DECISIONS 0028)."""

    def test_only_herdr_variables_are_dropped(self) -> None:
        env = _herdr_env(
            {
                "HERDR_PANE_ID": "wH:p1",
                "HERDR_SOCKET_PATH": "/x/herdr.sock",
                "PATH": "/usr/bin",
                "HOME": "/home/u",
                "HERDRISH": "kept: the prefix is HERDR_, not HERDR",
            }
        )
        self.assertEqual(
            env,
            {
                "PATH": "/usr/bin",
                "HOME": "/home/u",
                "HERDRISH": "kept: the prefix is HERDR_, not HERDR",
            },
        )

    def test_every_call_is_spawned_without_them(self) -> None:
        """Checked at the ``subprocess`` boundary so that no call path can be forgotten."""
        procs = [{"pid": 7, "name": "vi", "argv": ["vi"], "cmdline": "vi"}]
        answers = {
            "pane current": UNFOCUSED,  # forces the pane list call as well
            "pane list": pane_list({"pane_id": "wH:p3", "focused": True}),
            "pane process-info": info(procs, leader=7),
        }
        spawned = []

        class Completed:
            def __init__(self, stdout):
                self.stdout = stdout

        def fake_run(argv, **kwargs):
            spawned.append((list(argv), kwargs))
            return Completed(json.dumps(answers[" ".join(argv[1:3])]))

        with unittest.mock.patch.object(herdr, "subprocess") as sub:
            sub.run = fake_run
            sub.SubprocessError = subprocess.SubprocessError
            with unittest.mock.patch.dict(
                os.environ, {"HERDR_PANE_ID": "wH:p1", "WAYLAND_DISPLAY": "wayland-0"}
            ):
                proc = HerdrContextProvider().foreground_process("herdr")

        self.assertEqual(proc.name, "vi")
        self.assertEqual(
            [c[0][1:3] for c in spawned],
            [["pane", "current"], ["pane", "list"], ["pane", "process-info"]],
        )
        for argv, kwargs in spawned:
            with self.subTest(argv=argv):
                self.assertNotIn("HERDR_PANE_ID", kwargs["env"], "HERDR_* reached the child")
                self.assertEqual(kwargs["env"].get("WAYLAND_DISPLAY"), "wayland-0")


class HerdrFocusedPaneTest(unittest.TestCase):
    """Which pane the adapter describes when ``pane current`` is not the focused one."""

    make = HerdrAdapterTest.make

    def test_a_focused_answer_is_taken_as_is(self) -> None:
        procs = [{"pid": 3, "name": "bash", "argv": ["bash"]}]
        p, calls, _ = self.make({"pane current": PANE, "pane process-info": info(procs, leader=3)})
        self.assertEqual(p.foreground_process().name, "bash")
        self.assertEqual([c[1:3] for c in calls], [["pane", "current"], ["pane", "process-info"]])

    def test_an_unfocused_answer_falls_back_to_the_focused_pane(self) -> None:
        procs = [{"pid": 9, "name": "top", "argv": ["top"]}]
        p, calls, _ = self.make(
            {
                "pane current": UNFOCUSED,
                "pane list": pane_list(
                    {"pane_id": "wH:p1", "focused": False},
                    {"pane_id": "wH:p4", "focused": True},
                ),
                "pane process-info": info(procs, leader=9),
            }
        )
        self.assertEqual(p.foreground_process().name, "top")
        self.assertEqual(calls[1][1:3], ["pane", "list"])
        self.assertEqual(calls[2][:5], ["herdr", "pane", "process-info", "--pane", "wH:p4"])

    def test_no_single_focused_pane_is_no_answer(self) -> None:
        cases = {
            "none focused": pane_list({"pane_id": "wH:p1", "focused": False}),
            "two focused": pane_list(
                {"pane_id": "wH:p1", "focused": True}, {"pane_id": "w9:p1", "focused": True}
            ),
            "empty": pane_list(),
        }
        for name, listing in cases.items():
            with self.subTest(name):
                p, calls, _ = self.make({"pane current": UNFOCUSED, "pane list": listing})
                self.assertIsNone(p.foreground_process())
                self.assertEqual(len(calls), 2)  # never reaches process-info


class HerdrBudgetTest(unittest.TestCase):
    """The whole lookup stays inside ``LOOKUP_BUDGET``, however many calls it takes."""

    make = HerdrAdapterTest.make

    def test_a_later_call_only_gets_what_is_left(self) -> None:
        ticks = iter([0.0, 0.0, 1.4, 1.45])  # deadline, then the clock before each call
        p, calls, timeouts = self.make(
            {
                "pane current": UNFOCUSED,
                "pane list": pane_list({"pane_id": "wH:p9", "focused": True}),
                "pane process-info": info([{"pid": 1, "name": "vi", "argv": ["vi"]}], leader=1),
            },
            clock=lambda: next(ticks),
        )
        p.foreground_process()
        self.assertEqual(timeouts[0], herdr.CALL_TIMEOUT)  # a fresh lookup gets a full call
        self.assertAlmostEqual(timeouts[1], 0.1)  # 1.5 - 1.4 left, not another 0.75
        self.assertAlmostEqual(timeouts[2], 0.05)
        self.assertEqual(len(calls), 3)

    def test_an_exhausted_budget_stops_the_lookup(self) -> None:
        ticks = iter([0.0, 0.0, 2.0])
        p, calls, _ = self.make(
            {"pane current": UNFOCUSED, "pane list": pane_list()},
            clock=lambda: next(ticks),
        )
        self.assertIsNone(p.foreground_process())
        self.assertEqual(len(calls), 1)  # pane list was never spawned


class RealProviderContractTest(unittest.TestCase):
    """The resolver against the providers the daemon registers, not stand-ins.

    Everything else in this file uses fakes, and that is what let a provider drift out of step
    with the call the resolver makes. ``foreground_process`` grew an ``app_id`` argument for
    ``ProcAdapter``; had ``HerdrContextProvider`` kept the old signature, the resolver's call
    would raise ``TypeError``, be caught as "adapter bug must not take the overlay down", and
    Herdr would silently stop answering -- with every test still green.
    """

    def test_every_registered_provider_takes_the_call_the_resolver_makes(self) -> None:
        """Signatures only: binding the arguments proves the shape without running anything."""
        providers = _nested_providers()
        self.assertTrue(providers)
        for provider in providers:
            with self.subTest(provider=type(provider).__name__):
                inspect.signature(provider.applies_to).bind("foot")
                inspect.signature(provider.foreground_process).bind("foot")

    def test_the_resolver_drives_the_real_herdr_adapter(self) -> None:
        """End to end through the real adapter, with only the subprocess faked."""
        procs = [{"pid": 5, "name": "claude", "argv": ["claude"], "cmdline": "claude"}]
        answers = {"pane current": PANE, "pane process-info": info(procs, leader=5)}

        def runner(argv, timeout):
            return json.dumps(answers[" ".join(argv[1:3])])

        resolver = ContextResolver(
            FakeDesktop(snap("herdr")), [HerdrContextProvider(runner=runner)]
        )
        ctx = resolver.resolve(SHEETS, GlobalConfig())
        self.assertEqual(ctx.active_sheet, "claude")
        self.assertEqual(ctx.parent_context, "herdr")
        self.assertEqual(ctx.foreground_process.name, "claude")
        self.assertEqual(ctx.chain, ("HerdrContextProvider",))


class ProcessInfoTest(unittest.TestCase):
    def test_normalisation(self) -> None:
        pi = process_info_from_mapping({"pid": 3, "argv": ["/usr/bin/claude", "--x"]})
        self.assertEqual((pi.name, pi.cmdline), ("claude", "/usr/bin/claude --x"))
        self.assertIsNone(process_info_from_mapping({"name": "x"}))
        self.assertIsNone(process_info_from_mapping({"pid": True}))
        self.assertIsNone(process_info_from_mapping({"pid": 1}))
