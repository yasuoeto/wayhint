"""``./scripts/demo`` -- read a scenario, and (with ``--record``) record it.

Recording starts a compositor, so it is opt-in the way ``./scripts/setup-terminals --apply``
is: with no arguments this only reads the scenario and prints what it would do.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from tools.demo import actions, capture, encode
from tools.demo import scenario as scn
from tools.demo import session as sess
from tools.demo.scenario import Scenario, ScenarioError, Step

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "demo"
LANGUAGES = ("en", "ja")
RECORD_TOOLS = ("grim", "magick", "montage", "foot", "ffmpeg")
INJECT_ACTIONS = ("key", "type")
"""Actions that go in through the virtual keyboard, and so need ``wtype``."""


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        script = scn.load(args.scenario)
        only = _steps_named(args.only)
        selected = script.select(only, getattr(args, "from"))
        if not args.record:
            _print_plan(args.scenario, selected, _languages(args.lang), validate=args.validate)
            return 0
        for language in _languages(args.lang):
            _record(args, selected, language)
        return 0
    except (ScenarioError, sess.DemoError) as e:
        print(f"demo: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("demo: interrupted", file=sys.stderr)
        return 130


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="./scripts/demo",
        description="Record the wayhint demo from demo/scenario.yaml. "
        "With no arguments it only reads the scenario and prints the plan.",
    )
    p.add_argument("--record", action="store_true", help="actually record (starts a compositor)")
    p.add_argument(
        "--validate", action="store_true", help="check the scenario and say nothing else"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="the default: print the plan, record nothing"
    )
    p.add_argument("--lang", default="all", choices=("en", "ja", "all"), help="default: all")
    p.add_argument("--only", help="record these steps only, comma separated")
    p.add_argument("--from", help="start at this step")
    p.add_argument("--keep", action="store_true", help="keep the captured frames")
    p.add_argument("--no-burn", action="store_true", help="do not burn the captions into the video")
    p.add_argument("--scenario", type=Path, default=DEMO / "scenario.yaml")
    p.add_argument("--out", type=Path, default=DEMO / "out", help="default: demo/out")
    p.add_argument("--fixtures", type=Path, default=DEMO / "fixtures")
    p.add_argument("--bin", type=Path, default=DEMO / "bin", dest="bin_dir")
    return p


def _steps_named(value: str | None) -> list[str] | None:
    """``--only a,b`` -> the ids, or ``None`` when every step is wanted."""
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _languages(choice: str) -> tuple[str, ...]:
    return LANGUAGES if choice == "all" else (choice,)


def _print_plan(
    path: Path, script: Scenario, languages: tuple[str, ...], *, validate: bool
) -> None:
    if validate:
        print(f"demo: {path} is a valid scenario ({len(script.steps)} steps)")
        return
    fps = script.output.fps
    print(f"scenario: {path}")
    print(f"output:   {script.output.width}x{script.output.height} at {fps} fps")
    print(f"steps:    {len(script.steps)}")
    for number, step in enumerate(script.steps, start=1):
        frames = step.frames(fps)
        print(
            f"  {number:02d} {step.id:<18} {step.action.kind:<6} "
            f"{step.hold:>5.1f}s {frames:>5}f  wait: {step.wait_for.describe()}"
        )
    print(f"total:    {script.seconds():.1f}s ({script.frames()} frames) per language")
    where = ", ".join(f"demo/out/{lang}" for lang in languages)
    print(f"languages: {', '.join(languages)}  ->  {where}")
    print("nothing was recorded; add --record")


def _record(args: argparse.Namespace, script: Scenario, language: str) -> None:
    tools = RECORD_TOOLS
    typed = next((s.id for s in script.steps if s.action.kind in INJECT_ACTIONS), None)
    if typed is not None:
        # Only when the scenario actually presses keys. The point of those steps is the path
        # from a key to the daemon, so they are never quietly replaced by the CLI: without
        # wtype the recording stops here and says so (DECISIONS 0031).
        tools = (*tools, "wtype")
    try:
        sess.check_requirements(
            sess.Requirements(tools=tools, fonts=(script.fonts.ui, script.fonts.mono))
        )
    except sess.DemoError as e:
        if typed is not None and "wtype" in str(e):
            raise sess.DemoError(f"{e}\n  step {typed!r} sends a key, which needs wtype") from e
        raise
    out = args.out / language
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    print(f"demo: recording {language} -> {out}")
    work = sess.workspace(language)
    try:
        config = sess.prepare_config(args.fixtures, language, work)
        with sess.DemoSession(script, config) as demo:
            run = actions.Run(
                session=demo, language=language, demo_bin=args.bin_dir.resolve(), windows={}
            )
            recorder = capture.Recorder(out, script)
            for number, step in enumerate(script.steps, start=1):
                _run_step(run, recorder, step, number)
        _finish(args, script, recorder, out, language)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        # A run that failed before it captured anything leaves a directory where a recording
        # should be; that reads as "it recorded nothing", which is worse than saying nothing.
        if out.is_dir() and not any(path.is_file() for path in out.rglob("*")):
            shutil.rmtree(out)


def _run_step(run: actions.Run, recorder: capture.Recorder, step: Step, number: int) -> None:
    if step.precondition is not None:
        ok, seen = actions.satisfied(run, step.precondition)
        if not ok:
            raise sess.DemoError(
                f"step {step.id!r} needs {step.precondition.describe()} before it runs, "
                f"but saw {seen or 'nothing'}; it cannot be recorded on its own "
                "(use --from to include what sets it up)"
            )
    actions.perform(run, step)
    seen = actions.wait_until(run, step.wait_for, f"step {step.id!r}")
    recorder.record(run.session.session, step, number)
    frames = step.frames(recorder.scenario.output.fps)
    print(f"  {number:02d} {step.id:<18} {frames:>5}f  {seen}")


def _finish(
    args: argparse.Namespace,
    script: Scenario,
    recorder: capture.Recorder,
    out: Path,
    language: str,
) -> None:
    font = sess.font_file(script.fonts.ui)
    captions = encode.captions_for(recorder.spans(), language)
    videos = encode.encode(
        recorder.frames_dir,
        out,
        script,
        captions,
        font_file=font,
        burn=not args.no_burn,
    )
    encode.write_srt(out / "captions.srt", captions, script.output.fps)
    sheet = capture.contact_sheet(recorder, out / "contact-sheet.png", font)
    if not args.keep:
        shutil.rmtree(recorder.frames_dir)
        # The per-caption text files are ffmpeg's input, not a result; captions.srt is the
        # copy worth keeping.
        shutil.rmtree(out / "captions", ignore_errors=True)
    names = ", ".join(path.name for path in [*videos, sheet])
    print(f"demo: {recorder.frames} frames ({recorder.frames / script.output.fps:.1f}s) -> {names}")


if __name__ == "__main__":
    sys.exit(main())
