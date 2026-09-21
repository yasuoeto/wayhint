"""Frames, counted rather than timed.

A screen recorder writes as many frames as the machine managed to produce, so the same
scenario comes out a different length on a different machine, and a slow step turns into a
pause nobody asked for. Here each step is captured as *one* frame, which is then repeated as
many times as the scenario asked for (DECISIONS 0031). The picture is identical across those
frames because nothing on the screen is moving -- the cursors are switched off for exactly
this reason -- so the repeat costs nothing and the length is decided by the file.

The one frame per step is taken only once the screen has stopped changing, which is what makes
two runs on the same machine produce identical bytes.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tools.demo.scenario import Scenario, Step
from tools.demo.session import DemoError
from tools.headless import HeadlessSession

SETTLE = 0.3
STEP = 0.08
STABLE_RUNS = 7
STABLE_TRIES = 220


@dataclass
class Recorder:
    """Writes ``frames/NNNNNN.png`` (hard links) and ``steps/NN-<id>.png`` (one each)."""

    out: Path
    scenario: Scenario
    frames: int = 0

    def __post_init__(self) -> None:
        self.frames_dir = self.out / "frames"
        self.steps_dir = self.out / "steps"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.steps_dir.mkdir(parents=True, exist_ok=True)
        self.shots: list[tuple[Step, Path]] = []

    def record(self, session: HeadlessSession, step: Step, number: int) -> Path:
        """Capture the step and lay down its frames. Returns the still it captured."""
        shot = self.steps_dir / f"{number:02d}-{step.id}.png"
        _stable_grab(session, shot)
        self.shots.append((step, shot))
        for _ in range(step.frames(self.scenario.output.fps)):
            self.frames += 1
            link = self.frames_dir / f"{self.frames:06d}.png"
            os.link(shot, link)
        return shot

    def spans(self) -> list[tuple[Step, int, int]]:
        """Each step with the frame range it occupies, 1-based and inclusive."""
        out, at = [], 0
        for step, _shot in self.shots:
            count = step.frames(self.scenario.output.fps)
            if count:
                out.append((step, at + 1, at + count))
            at += count
        return out


def _stable_grab(session: HeadlessSession, path: Path) -> Path:
    """One frame of a screen that has stopped changing, for good.

    Not "two captures in a row are the same": a *blinking* screen passes that whenever two
    captures fall inside the same half of the blink, and then the recording differs from run to
    run by exactly one caret. The overlay's text cursor blinks -- GTK ignores
    ``gtk-cursor-blink`` in ``settings.ini`` here (GTK 4.22), and it stops on its own about
    eight seconds after the last keystroke -- so the test has to outlast a blink period
    instead. :data:`STABLE_RUNS` identical captures at :data:`STEP` apart is about twice the
    1.2s period, which no blink survives.

    Compared byte for byte rather than with ImageMagick: grim writes the same bytes for the
    same picture, and this runs hundreds of times per recording.
    """
    scratch = path.with_name(path.stem + ".probe.png")
    previous, same = None, 0
    try:
        session.grab(scratch, settle=SETTLE)
        for _ in range(STABLE_TRIES):
            data = scratch.read_bytes()
            same = same + 1 if data == previous else 0
            previous = data
            if same >= STABLE_RUNS:
                path.write_bytes(data)
                return path
            session.grab(scratch, settle=STEP)
    finally:
        scratch.unlink(missing_ok=True)
    raise DemoError(
        f"the screen never stopped changing while capturing {path.name}; "
        "something on it is animating that is not a text cursor"
    )


def contact_sheet(recorder: Recorder, out: Path, font: str, columns: int = 3) -> Path:
    """Every step as one labelled still, in a grid.

    A video cannot be looked at by an agent or a CI job, and a wall of PNGs is no better. This
    is the artefact a reviewer actually opens to see whether the demo still shows what it is
    meant to show.
    """
    argv = ["montage"]
    for number, (step, shot) in enumerate(recorder.shots, start=1):
        argv += ["-label", f"{number:02d} {step.id}", str(shot)]
    argv += [
        "-font",
        font,
        "-pointsize",
        "16",
        "-background",
        "#14141c",
        "-fill",
        "#e8e8f0",
        "-tile",
        f"{columns}x",
        "-geometry",
        "420x236+8+8",
        str(out),
    ]
    subprocess.run(argv, check=True, capture_output=True, timeout=120)
    return out
