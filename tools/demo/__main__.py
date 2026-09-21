"""``./scripts/demo`` -- read a showcase's scenario, and (with ``--record``) record it.

Recording starts a compositor, so it is opt-in the way ``./scripts/setup-terminals --apply``
is: with no arguments this only reads what is there and prints it.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from tools.demo import actions, capture, encode, names
from tools.demo import scenario as scn
from tools.demo import session as sess
from tools.demo import showcase as shc
from tools.demo.scenario import Scenario, ScenarioError, Step, Variant

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "demo"
SHOWCASES = DEMO / "showcases"
RECORD_TOOLS = ("grim", "magick", "montage", "foot", "ffmpeg")
INJECT_ACTIONS = ("key", "type")
"""Actions that go in through the virtual keyboard, and so need ``wtype``."""


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _check_names(args)
        if not args.showcase:
            return _list_showcases(args)
        show = shc.load(args.showcases, args.showcase)
        for warning in show.warnings:
            print(f"demo: warning: {warning}", file=sys.stderr)
        script = scn.load(show.scenario, demo_bin=args.bin_dir)
        variants = _variants(script, args.variant)
        only = _steps_named(args.only)
        chosen = [v.select(only, getattr(args, "from")) for v in variants]
        whole = not only and not getattr(args, "from")
        if not args.record:
            return _print_plan(show, script, chosen, args, whole=whole)
        _check_lengths(script, chosen, whole=whole)
        for language in _languages(args.lang):
            for variant in chosen:
                _record(args, show, script, variant, language)
        return 0
    except (ScenarioError, shc.ShowcaseError, sess.DemoError, names.BadName) as e:
        print(f"demo: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("demo: interrupted", file=sys.stderr)
        return 130


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="./scripts/demo",
        description="Record a demo video from demo/showcases/<name>/. With no arguments it "
        "lists the showcases and records nothing.",
    )
    p.add_argument("--showcase", help="which showcase to read; required by --record")
    p.add_argument("--variant", default="all", help="a variant name, or all (the default)")
    p.add_argument("--record", action="store_true", help="actually record (starts a compositor)")
    p.add_argument(
        "--validate", action="store_true", help="check the scenario and say nothing else"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="the default: print the plan, record nothing"
    )
    p.add_argument("--lang", default=scn.DEFAULT_LANGUAGE, choices=scn.LANGUAGES)
    p.add_argument("--only", help="record these steps only, comma separated")
    p.add_argument("--from", help="start at this step")
    p.add_argument("--keep", action="store_true", help="keep the captured frames")
    p.add_argument("--showcases", type=Path, default=SHOWCASES)
    p.add_argument("--fixtures", type=Path, default=DEMO / "fixtures")
    p.add_argument("--bin", type=Path, default=DEMO / "bin", dest="bin_dir")
    return p


def _check_names(args: argparse.Namespace) -> None:
    """Every name off the command line, by the rule the scenario's own names follow.

    They end up in the same two places -- a directory under ``out/`` and a lookup in the
    scenario -- and the command line is as untrusted as the file (DECISIONS 0032).
    """
    for flag, value in (
        ("--showcase", args.showcase),
        ("--variant", args.variant),
        ("--from", getattr(args, "from")),
    ):
        if value is not None:
            names.validate_name(f"{flag} value", value)
    for value in _steps_named(args.only) or []:
        names.validate_name("--only value", value)


def _steps_named(value: str | None) -> list[str] | None:
    """``--only a,b`` -> the ids, or ``None`` when every step is wanted."""
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _languages(choice: str) -> tuple[str, ...]:
    return (choice,)


def _variants(script: Scenario, choice: str) -> list[Variant]:
    return list(script.variants) if choice == "all" else [script.variant(choice)]


def _list_showcases(args: argparse.Namespace) -> int:
    if args.record:
        names = ", ".join(s.name for s in shc.discover(args.showcases)) or "none yet"
        print(
            f"demo: --record needs --showcase <name> (there is: {names})",
            file=sys.stderr,
        )
        return 1
    found = shc.discover(args.showcases)
    if not found:
        print(f"demo: no showcases in {args.showcases}")
        return 0
    print(f"showcases in {args.showcases}:")
    for show in found:
        try:
            script = scn.load(show.scenario, demo_bin=args.bin_dir)
            fps = script.output.fps
            variants = ", ".join(f"{v.name} {v.seconds(fps):.0f}s" for v in script.variants)
            story = "storyboard" if show.storyboard else "no storyboard"
            print(f"  {show.name:<12} {variants}   ({story}, {show.scenario.name})")
        except ScenarioError as e:
            print(f"  {show.name:<12} unreadable: {e}")
    print("nothing was recorded; add --showcase <name> --record")
    return 0


def _print_plan(
    show: shc.Showcase,
    script: Scenario,
    variants: list[Variant],
    args: argparse.Namespace,
    *,
    whole: bool,
) -> int:
    fps = script.output.fps
    if args.validate:
        _check_lengths(script, variants, whole=whole)
        steps = len(script.steps)
        print(f"demo: {show.scenario} is valid ({steps} steps, {len(script.variants)} variants)")
        return 0
    print(f"showcase: {show.name} ({show.root})")
    print(f"scenario: {show.scenario.name}")
    print(f"output:   {script.output.width}x{script.output.height} at {fps} fps")
    print(f"language: {args.lang}")
    for variant in variants:
        off = variant.off_target(fps)
        verdict = "ok" if not off else f"OFF TARGET by {off:.1f}s"
        square = ", square" if variant.square else ""
        print(
            f"\n  {variant.name}: {len(variant.steps)} steps, {variant.seconds(fps):.1f}s "
            f"(target {variant.target:g} ±{variant.tolerance:g}{square}) [{verdict}]"
        )
        for number, step in enumerate(variant.steps, start=1):
            caption = step.caption.get(args.lang, "")
            print(
                f"    {number:02d} {step.id:<16} {step.action.kind:<6} "
                f"{step.hold:>5.1f}s {step.frames(fps):>5}f  {caption[:44]}"
            )
    where = show.root / shc.OUT / args.lang
    print(f"\nnothing was recorded; add --record  ->  {where}/<variant>/")
    return 1 if any(v.off_target(fps) for v in variants) and whole else 0


def _check_lengths(script: Scenario, variants: list[Variant], *, whole: bool) -> None:
    if not whole:
        return  # --only / --from record a part on purpose; the target is about the whole
    fps = script.output.fps
    bad = [v for v in variants if v.off_target(fps)]
    if bad:
        lines = "\n".join(
            f"  {v.name}: {v.seconds(fps):.1f}s, wanted {v.target:g} ±{v.tolerance:g}" for v in bad
        )
        raise ScenarioError("a variant is not the length the storyboard asked for:\n" + lines)


def _output_dir(show: shc.Showcase, language: str, variant: str) -> Path:
    """Where this recording goes, emptied first -- after checking that it is where it claims.

    Everything that makes up the path is already restricted to ``[a-z0-9-]`` by the parsers,
    but this is the one place that *deletes a directory*, so it verifies the result rather
    than trusting the checks upstream.

    The directories are looked at *before* they are resolved. ``out/`` is a plausible thing
    for somebody to point at another disk with a symlink, and following it would move the
    delete to wherever it lands -- so a symlink anywhere on the way down is refused instead
    (DECISIONS 0032's threat model: ``out/`` is state this has to survive, not trust).
    """
    root = show.root / shc.OUT
    out = show.out(language, variant)
    for path in (root, root / language, out):
        if path.is_symlink():
            raise sess.DemoError(
                f"{path} is a symlink to {path.readlink()}; refusing to empty it.\n"
                "  A recording deletes its output directory first, so every step of "
                f"{shc.OUT}/<language>/<variant> has to be a real directory in the showcase.\n"
                "  (Putting the results elsewhere would need an --out-dir option; there is "
                "none yet -- see STATUS.md, Remaining work.)"
            )
    root, out = root.resolve(), out.resolve()
    if not out.is_relative_to(root) or out == root:
        raise sess.DemoError(f"refusing to write outside {root}: {out}")
    if out.exists():
        shutil.rmtree(out)
    return out


def _record(
    args: argparse.Namespace,
    show: shc.Showcase,
    script: Scenario,
    variant: Variant,
    language: str,
) -> None:
    missing = [s.id for s in variant.steps if s.caption and language not in s.caption]
    if missing:
        raise sess.DemoError(
            f"no {language} caption for: {', '.join(missing)} "
            f"(write caption.{language}, or record --lang {scn.DEFAULT_LANGUAGE})"
        )
    tools = RECORD_TOOLS
    typed = next((s.id for s in variant.steps if s.action.kind in INJECT_ACTIONS), None)
    if typed is not None:
        # Only when the scenario actually presses keys. The point of those steps is the path
        # from a key to the daemon, so they are never quietly replaced by the CLI: without
        # wtype the recording stops here and says so (DECISIONS 0031).
        tools = (*tools, "wtype")
    if any(s.action.kind == "herdr" for s in variant.steps):
        tools = (*tools, sess.HERDR)
    try:
        sess.check_requirements(
            sess.Requirements(tools=tools, fonts=(script.fonts.ui, script.fonts.mono))
        )
    except sess.DemoError as e:
        if typed is not None and "wtype" in str(e):
            raise sess.DemoError(f"{e}\n  step {typed!r} sends a key, which needs wtype") from e
        raise
    out = _output_dir(show, language, variant.name)
    out.mkdir(parents=True)
    print(f"demo: recording {show.name} {variant.name} in {language} -> {out}")
    work = sess.workspace(show.name, language)
    try:
        config = sess.prepare_config(args.fixtures, language, work)
        with sess.DemoSession(script, config, work / sess.WORK_DIR, args.bin_dir) as demo:
            run = actions.Run(
                session=demo, language=language, demo_bin=args.bin_dir.resolve(), windows={}
            )
            recorder = capture.Recorder(out, script)
            for number, step in enumerate(variant.steps, start=1):
                _run_step(run, recorder, step, number, script.output.fps)
        _finish(args, script, recorder, out, language, show, variant)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        # A run that failed before it captured anything leaves a directory where a recording
        # should be; that reads as "it recorded nothing", which is worse than saying nothing.
        if out.is_dir() and not any(path.is_file() for path in out.rglob("*")):
            shutil.rmtree(out)


def _run_step(run: actions.Run, recorder: capture.Recorder, step: Step, number: int, fps: int):
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
    print(f"  {number:02d} {step.id:<16} {step.frames(fps):>5}f  {seen}")


def _finish(
    args: argparse.Namespace,
    script: Scenario,
    recorder: capture.Recorder,
    out: Path,
    language: str,
    show: shc.Showcase,
    variant: Variant,
) -> None:
    font = sess.font_file(script.fonts.ui)
    captions = encode.captions_for(recorder.spans(), language)
    stem = f"wayhint-{show.name}-{variant.name}.{language}"
    videos = encode.encode(
        recorder.frames_dir,
        out,
        script,
        captions,
        font_file=font,
        stem=stem,
        square=variant.square,
    )
    encode.write_srt(out / f"{stem}.srt", captions, script.output.fps)
    sheet = capture.contact_sheet(recorder, out / "contact-sheet.png", font)
    if not args.keep:
        shutil.rmtree(recorder.frames_dir)
        # The per-caption text files are ffmpeg's input, not a result; the .srt is the copy
        # worth keeping.
        shutil.rmtree(out / "captions", ignore_errors=True)
    names = ", ".join(path.name for path in [*videos, sheet])
    print(f"demo: {recorder.frames} frames ({recorder.frames / script.output.fps:.1f}s) -> {names}")


if __name__ == "__main__":
    sys.exit(main())
