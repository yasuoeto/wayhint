"""Frames in, one video out -- and the captions, both burnt in and beside it.

ffmpeg only ever joins what ``capture`` produced: the frame rate it is given matches the one
the frames were counted at, so the length of the result is the number of files on disk divided
by the fps, and nothing here can change it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from tools.demo.scenario import Scenario, Step

CRF_H264 = "20"
CRF_VP9 = "32"


@dataclass(frozen=True)
class Caption:
    text: str
    first: int  # 1-based frame numbers, inclusive, as ``Recorder.spans`` reports them
    last: int


def captions_for(spans: list[tuple[Step, int, int]], language: str) -> list[Caption]:
    return [
        Caption(step.caption[language], first, last)
        for step, first, last in spans
        if step.caption.get(language)
    ]


def encode(
    frames_dir: Path,
    out_dir: Path,
    scenario: Scenario,
    captions: list[Caption],
    *,
    font_file: str,
    burn: bool = True,
    stem: str = "wayhint-demo",
) -> list[Path]:
    """Write ``<stem>.mp4`` and ``<stem>.webm`` from the frames, captions burnt in or not."""
    if not any(frames_dir.iterdir()):
        raise ValueError("no frames to encode")
    fps = str(scenario.output.fps)
    filters = _drawtext(captions, out_dir, font_file, scenario) if burn else ""
    common = ["-framerate", fps, "-i", str(frames_dir / "%06d.png")]
    if filters:
        common += ["-vf", filters]
    written = []
    for name, codec, extra in (
        ("mp4", "libx264", ["-crf", CRF_H264, "-preset", "medium"]),
        ("webm", "libvpx-vp9", ["-crf", CRF_VP9, "-b:v", "0", "-row-mt", "1"]),
    ):
        target = out_dir / f"{stem}.{name}"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                *common,
                "-c:v",
                codec,
                *extra,
                "-pix_fmt",
                "yuv420p",
                "-r",
                fps,
                str(target),
            ],
            check=True,
            capture_output=True,
            timeout=900,
        )
        written.append(target)
    return written


def _drawtext(captions: list[Caption], out_dir: Path, font_file: str, scenario: Scenario) -> str:
    """One ``drawtext`` per caption, each switched on for the frames of its step.

    The text goes in a file rather than in the filter string: a caption is prose, with colons
    and commas in it, and ffmpeg's filter syntax would need it escaped twice. ``expansion=none``
    then stops ffmpeg reading ``%`` or ``{}`` in the prose as something to substitute.
    """
    if not captions:
        return ""
    folder = out_dir / "captions"
    folder.mkdir(parents=True, exist_ok=True)
    size = max(18, round(scenario.output.height / 26))
    parts = []
    for number, caption in enumerate(captions, start=1):
        path = folder / f"{number:02d}.txt"
        path.write_text(caption.text + "\n")
        parts.append(
            "drawtext="
            + ":".join(
                [
                    f"fontfile={_escape(font_file)}",
                    f"textfile={_escape(str(path))}",
                    "expansion=none",
                    "fontcolor=white",
                    f"fontsize={size}",
                    "x=(w-text_w)/2",
                    f"y=h-{size * 3}",
                    "box=1",
                    "boxcolor=black@0.62",
                    "boxborderw=14",
                    f"enable='between(n\\,{caption.first - 1}\\,{caption.last - 1})'",
                ]
            )
        )
    return ",".join(parts)


def _escape(value: str) -> str:
    """A path inside an ffmpeg filter argument."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def write_srt(path: Path, captions: list[Caption], fps: int) -> Path:
    """The same captions as a sidecar, for a recording made with ``--no-burn``."""
    blocks = []
    for number, caption in enumerate(captions, start=1):
        start = _timestamp((caption.first - 1) / fps)
        end = _timestamp(caption.last / fps)
        blocks.append(f"{number}\n{start} --> {end}\n{caption.text}\n")
    path.write_text("\n".join(blocks))
    return path


def _timestamp(seconds: float) -> str:
    whole = int(seconds)
    millis = round((seconds - whole) * 1000)
    if millis == 1000:  # a float that lands just under the next second
        whole, millis = whole + 1, 0
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d},{millis:03d}"
