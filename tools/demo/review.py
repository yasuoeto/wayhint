"""What changed between two takes, cut down to the part a reviewer has to look at.

The stills a reviewer opens cost the same whether anything on them changed or not, and a
re-recording usually changes a few steps out of dozens. So this compares a new take's
``steps/`` with the adopted one's, by step id rather than by number (a step inserted near the
top renumbers everything below it), and for each step that differs writes a crop of the
region that changed, at full resolution. A still that is shrunk to fit a tall grid is where a
cut-off line stops being visible; a crop of the changed rows keeps every pixel of it.

A step with no counterpart in the adopted take is written whole: there is nothing to compare
it to, so all of it is new.

The captions are not in the stills (``encode`` burns them in afterwards), so a caption that
changed shows up here only if the picture under it changed too.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PAD = 32
"""How far a crop reaches past the changed pixels, so the line around a change is readable."""

REVIEW_DIR = "review"

_STEP = re.compile(r"^(\d+)-(.+)\.png$")
_BOX = re.compile(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$")


@dataclass(frozen=True)
class Box:
    width: int
    height: int
    x: int
    y: int

    def padded(self, pad: int, width: int, height: int) -> Box:
        left, top = max(0, self.x - pad), max(0, self.y - pad)
        right = min(width, self.x + self.width + pad)
        bottom = min(height, self.y + self.height + pad)
        return Box(right - left, bottom - top, left, top)

    def geometry(self) -> str:
        return f"{self.width}x{self.height}+{self.x}+{self.y}"


@dataclass(frozen=True)
class Change:
    kind: str  # "changed", "new", "removed" or "same"
    step: str  # the step id
    new: Path | None
    base: Path | None
    box: Box | None = None  # changed only: the pixels that differ


def steps_by_id(folder: Path) -> dict[str, Path]:
    """``NN-<id>.png`` -> ``{id: path}``, in recording order."""
    found = []
    for path in folder.glob("*.png"):
        match = _STEP.match(path.name)
        if match:
            found.append((int(match.group(1)), match.group(2), path))
    return {step: path for _, step, path in sorted(found)}


def compare(
    base: dict[str, Path], new: dict[str, Path], differ: Callable[[Path, Path], Box | None]
) -> list[Change]:
    """Every step of the new take against the adopted one, then what the new take dropped."""
    out = []
    for step, path in new.items():
        old = base.get(step)
        if old is None:
            out.append(Change("new", step, path, None))
            continue
        box = None if path.read_bytes() == old.read_bytes() else differ(old, path)
        out.append(Change("changed" if box else "same", step, path, old, box))
    out += [Change("removed", step, None, path) for step, path in base.items() if step not in new]
    return out


def parse_box(text: str) -> Box | None:
    """ImageMagick's ``%@`` (the trim box). ``0x0+W+H`` is how it says there is nothing."""
    match = _BOX.match(text.strip())
    if not match:
        raise ValueError(f"unexpected bounding box from magick: {text.strip()!r}")
    box = Box(*(int(group) for group in match.groups()))
    return box if box.width and box.height else None


def magick_diff(base: Path, new: Path) -> Box | None:
    """Where the two stills differ, or ``None`` when every pixel is the same."""
    argv = ["magick", str(base), str(new), "-alpha", "off", "-compose", "difference",
            "-composite", "-colorspace", "gray", "-threshold", "0",
            "-format", "%@", "info:"]  # fmt: skip
    result = subprocess.run(argv, check=True, capture_output=True, text=True, timeout=60)
    return parse_box(result.stdout)


def image_size(path: Path) -> tuple[int, int]:
    """A PNG's width and height, from its IHDR."""
    header = path.read_bytes()[16:24]
    return int.from_bytes(header[:4], "big"), int.from_bytes(header[4:], "big")


def write(changes: list[Change], folder: Path) -> list[Path]:
    """The crops of what changed and the whole of what is new. Returns them in order."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    written = []
    for change in changes:
        if change.new is None or change.kind == "same":
            continue
        target = folder / change.new.name
        if change.box is None:
            shutil.copyfile(change.new, target)
        else:
            width, height = image_size(change.new)
            crop = change.box.padded(PAD, width, height).geometry()
            argv = ["magick", str(change.new), "-crop", crop, "+repage", str(target)]
            subprocess.run(argv, check=True, capture_output=True, timeout=60)
        written.append(target)
    return written


def report(changes: list[Change]) -> list[str]:
    """One line per step that needs looking at, and a count of the ones that do not."""
    lines = []
    for change in changes:
        if change.kind == "changed" and change.box is not None:
            lines.append(f"  changed  {change.step:<20} {change.box.geometry()}")
        elif change.kind == "new":
            lines.append(f"  new      {change.step:<20} whole frame")
        elif change.kind == "removed":
            lines.append(f"  removed  {change.step}")
    same = sum(1 for change in changes if change.kind == "same")
    lines.append(f"  same     {same} step(s), nothing to look at")
    return lines
