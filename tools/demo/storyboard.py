"""Reading the storyboard well enough to check it against the scenario.

The storyboard is a person's document: what the video argues, in what order, and roughly when
(DECISIONS 0032). Nothing here writes it, and the scenario is never generated from it -- the
two are written separately on purpose, because the storyboard is where the *argument* lives and
the scenario is where the *actions* do.

What goes wrong is the seam. Shorten one scene and every second in the storyboard below it is
wrong; reword a caption in the scenario and the storyboard still quotes the old one. That
happened on three changes in a row (B-7, B-8), every time by hand. So this module reads the
parts of the storyboard that are *claims about the scenario* -- the captions, the second ranges
in the tables, the section headings and the stated totals -- and says where the two disagree.

The format it expects is the one the storyboard already uses::

    ## 2. 2〜3 分版(README 埋め込み)
    <!-- variant: 3min -->
    ... 合計 140 秒。

    ### §2 いつも同じ場所(0:18–0:32)

    | 秒 | 画面 | 字幕 |
    |---|---|---|
    | 18–24 | `Super+H`。右上に overlay | hotkey 一発。いつも右上。 |

The ``<!-- variant: ... -->`` marker is the one thing added for this: a heading a person writes
freely cannot be matched to a variant name by guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.demo.scenario import Scenario, Step

HEADING = re.compile(r"^(?P<level>#{2,3})\s+(?P<title>.+?)\s*$")
MARKER = re.compile(r"^<!--\s*variant:\s*(?P<name>[a-z0-9][a-z0-9-]*)\s*-->\s*$")
SPAN = re.compile(r"[(（](?P<from>\d+:\d\d)\s*[-–~〜]\s*(?P<to>\d+:\d\d)")
TOTAL = re.compile(r"合計\s*(?P<seconds>\d+(?:\.\d+)?)\s*秒")
ROW = re.compile(
    r"^\|\s*(?P<start>\d+(?:\.\d+)?)\s*[-–~〜]\s*(?P<end>\d+(?:\.\d+)?)\s*\|"
    r"(?P<screen>[^|]*)\|(?P<caption>[^|]*)\|"
)
NO_CAPTION = "(字幕なし)"
"""What a row with no subtitle says, in the storyboard's own words."""

TOLERANCE = 1.0
"""How far a second in the storyboard may sit from the scenario's own timeline.

The storyboard rounds (``93.5–101`` for a step that ends at 101.1); it is prose about a video,
not a frame count. Anything past a second is drift, not rounding."""


@dataclass(frozen=True)
class Row:
    line: int
    start: float
    end: float
    caption: str  # "" when the row says (字幕なし)


@dataclass(frozen=True)
class Section:
    line: int
    title: str
    variant: str | None
    span: tuple[float, float] | None
    rows: tuple[Row, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Storyboard:
    path: Path
    sections: tuple[Section, ...]
    totals: dict[str, float]

    def captions(self) -> set[str]:
        return {row.caption for s in self.sections for row in s.rows if row.caption}


def _seconds(clock: str) -> float:
    minutes, _, rest = clock.partition(":")
    return int(minutes) * 60 + int(rest)


def read(path: Path) -> Storyboard:
    """Parse the storyboard. Anything it does not recognise is left alone."""
    sections: list[Section] = []
    totals: dict[str, float] = {}
    variant: str | None = None
    line_no, title, span = 0, "", None
    rows: list[Row] = []

    def close() -> None:
        if title:
            sections.append(Section(line_no, title, variant, span, tuple(rows)))

    for number, line in enumerate(path.read_text().splitlines(), start=1):
        marker = MARKER.match(line)
        if marker is not None:
            variant = marker.group("name")
            continue
        heading = HEADING.match(line)
        if heading is not None:
            close()
            line_no, title, rows = number, heading.group("title"), []
            if heading.group("level") == "##":
                variant = None  # a new part of the document; its marker comes next
            found = SPAN.search(title)
            span = (
                (_seconds(found.group("from")), _seconds(found.group("to")))
                if found is not None
                else None
            )
            continue
        total = TOTAL.search(line)
        if total is not None and variant is not None:
            totals[variant] = float(total.group("seconds"))
        row = ROW.match(line)
        if row is not None:
            caption = row.group("caption").strip()
            rows.append(
                Row(
                    line=number,
                    start=float(row.group("start")),
                    end=float(row.group("end")),
                    caption="" if caption == NO_CAPTION else caption,
                )
            )
    close()
    return Storyboard(path, tuple(sections), totals)


def _timeline(script: Scenario, variant: str) -> dict[str, tuple[Step, float, float]]:
    """``caption -> (step, start, end)`` for one variant. Captions have to be unique in it."""
    fps = script.output.fps
    at, out = 0.0, {}
    for step in script.variant(variant).steps:
        end = at + step.frames(fps) / fps
        caption = step.caption.get("ja", "")
        if caption:
            out[caption] = (step, at, end)
        at = end
    return out


def check(story: Storyboard, script: Scenario) -> tuple[list[str], list[str]]:
    """``(problems, warnings)``. Problems mean the two documents disagree about the video."""
    problems: list[str] = []
    timelines = {name: _timeline(script, name) for name in (v.name for v in script.variants)}
    where = f"{story.path.name}"

    for variant, seconds in story.totals.items():
        if variant not in timelines:
            problems.append(f"{where}: 合計 for a variant the scenario does not have: {variant}")
            continue
        actual = script.variant(variant).seconds(script.output.fps)
        if abs(actual - seconds) > TOLERANCE:
            problems.append(
                f"{where}: {variant} says 合計 {seconds:g} 秒, the scenario is {actual:.1f}"
            )

    for section in story.sections:
        if section.variant is None or not section.rows:
            continue
        if section.variant not in timelines:
            problems.append(
                f"{where}:{section.line}: variant {section.variant!r} is not in the scenario"
            )
            continue
        timeline = timelines[section.variant]
        covered: list[tuple[float, float]] = []
        for row in section.rows:
            if not row.caption:
                continue
            found = timeline.get(row.caption)
            if found is None:
                problems.append(
                    f"{where}:{row.line}: no step in {section.variant} has this caption: "
                    f"{row.caption!r}"
                )
                continue
            step, start, end = found
            covered.append((start, end))
            # Inside the row, not equal to it: one row often covers several steps and carries
            # the caption of one of them ("`a` → タイトル → Tab → キー" is four).
            if start < row.start - TOLERANCE or end > row.end + TOLERANCE:
                problems.append(
                    f"{where}:{row.line}: step {step.id!r} runs {start:.1f}–{end:.1f}, "
                    f"outside the row's {row.start:g}–{row.end:g}"
                )
        if section.span is not None:
            # The heading against the section's own table -- the rows are already tied to the
            # scenario above, so this catches a heading left behind when the rows were fixed.
            first = min(row.start for row in section.rows)
            last = max(row.end for row in section.rows)
            low, high = section.span
            if abs(first - low) > TOLERANCE or abs(last - high) > TOLERANCE:
                problems.append(
                    f"{where}:{section.line}: the table under {section.title!r} runs "
                    f"{first:g}–{last:g}s, the heading says {low:.0f}–{high:.0f}s"
                )

    told = story.captions()
    for variant, timeline in timelines.items():
        for caption, (step, _, _) in timeline.items():
            if caption not in told:
                problems.append(
                    f"{where}: step {step.id!r} ({variant}) has a caption the storyboard does "
                    f"not mention: {caption!r}"
                )

    return problems, _warnings(script)


def _warnings(script: Scenario) -> list[str]:
    """Steps whose ``wait_for`` cannot tell a step that worked from one that did nothing.

    A judgement call, never a failure: a caption-only step is *meant* to leave the screen alone
    (`pause:`). But the hole this catches is real -- in B-7 three steps pressed keys that never
    reached the overlay, and ``wait_for: {overlay: visible}`` waved all three through.
    """
    out: list[str] = []
    for variant in script.variants:
        previous = None
        for step in variant.steps:
            if step.action.kind == "pause":
                previous = _asserts(step)
                continue  # a pause is *meant* to leave the screen alone
            shape = _asserts(step)
            if not shape:
                out.append(
                    f"step {step.id!r} ({variant.name}): wait_for only says the overlay is up, "
                    "which it already was; it cannot catch this step doing nothing"
                )
            elif shape == previous:
                out.append(
                    f"step {step.id!r} ({variant.name}): wait_for is the same as the step before "
                    "it, so it holds whether or not this step did anything"
                )
            previous = shape
    return out


def _asserts(step: Step) -> tuple:
    """What a step's ``wait_for`` actually pins down, beyond the overlay being up."""
    cond = step.wait_for
    return tuple(
        (name, value)
        for name, value in (
            ("toplevel", cond.toplevel),
            ("process_name", cond.process_name),
            ("active_sheet", cond.active_sheet),
            ("label", cond.label),
            ("no_label", cond.no_label),
            ("button", cond.button),
            ("hints", cond.hints),
            ("overlay", cond.overlay if cond.overlay == "hidden" else None),
        )
        if value is not None
    )
