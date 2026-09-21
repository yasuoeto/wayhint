"""Frames in, the videos out -- and the captions, both burnt in and beside them.

ffmpeg only ever joins what ``capture`` produced: the frame rate it is given matches the one
the frames were counted at, so the length of the result is the number of files on disk divided
by the fps, and nothing here can change it.

Four files come out of one recording, because they are wanted for different things
(DECISIONS 0032): the plain video for anyone who wants to add their own subtitles, the burnt-in
one for posting as it is, a WebM of the same for a page that cannot play H.264, and -- for a
variant marked ``square`` -- a square crop for feeds that show one. The ``.srt`` is written
whatever happens, so the plain video is usable without re-encoding anything.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from tools.demo.scenario import Scenario, Step

CRF_H264 = "20"
CRF_VP9 = "32"
SQUARE_CROP = "crop=ih:ih:iw-ih:0"
"""A square taken from the right-hand edge: the overlay lives there, and it has to be whole."""


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
    stem: str,
    square: bool = False,
) -> list[Path]:
    """Write the plain, subtitled, WebM and (optionally) square videos. Returns their paths."""
    if not any(frames_dir.iterdir()):
        raise ValueError("no frames to encode")
    fps = str(scenario.output.fps)
    burn = _drawtext(captions, out_dir, font_file, scenario.output.height)
    square_burn = _drawtext(
        captions, out_dir, font_file, scenario.output.height, prefix=f"{SQUARE_CROP},"
    )
    jobs = [
        (f"{stem}.mp4", "libx264", "", _H264),
        (f"{stem}.sub.mp4", "libx264", burn, _H264),
        (f"{stem}.webm", "libvpx-vp9", burn, _VP9),
        *([(f"{stem}.square.mp4", "libx264", square_burn or SQUARE_CROP, _H264)] if square else []),
    ]
    written = []
    for name, codec, filters, extra in jobs:
        target = out_dir / name
        argv = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", fps, "-i",
                str(frames_dir / "%06d.png")]  # fmt: skip
        if filters:
            argv += ["-vf", filters]
        argv += ["-c:v", codec, *extra, "-pix_fmt", "yuv420p", "-r", fps, str(target)]
        subprocess.run(argv, check=True, capture_output=True, timeout=3600)
        written.append(target)
    return written


_H264 = ["-crf", CRF_H264, "-preset", "medium"]
_VP9 = ["-crf", CRF_VP9, "-b:v", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "2"]


BOX_BORDER = 14
"""``boxborderw``: how far the band reaches past the text on every side."""
BOX_GAP = 12
"""How far the band's *text* stays clear of the bottom edge, at two lines of it."""


def caption_size(height: int) -> int:
    """The font size the band is drawn at, from the frame height."""
    return max(18, round(height / 26))


def caption_band_top(height: int) -> int:
    """The first row the band may cover. Nothing the compositor draws may reach it.

    The band is the one thing burnt into the picture afterwards, so its rows are reserved:
    windows are placed to end above this (the scenario's ``windows``) and the overlay's height
    is set so its bottom edge does too (``demo/fixtures/config.yaml``). At 720p that is
    ``720 - (28 * 2 + 12) - 14 = 638``; see demo/README「字幕帯」.
    """
    return caption_text_top(height) - BOX_BORDER


def caption_text_top(height: int) -> int:
    """Where the first line of the caption starts -- ``drawtext``'s ``y``."""
    return height - (caption_size(height) * 2 + BOX_GAP)


def _drawtext(
    captions: list[Caption], out_dir: Path, font_file: str, height: int, prefix: str = ""
) -> str:
    """One ``drawtext`` per caption, each switched on for the frames of its step.

    The text goes in a file rather than in the filter string: a caption is prose, with colons
    and commas in it, and ffmpeg's filter syntax would need it escaped twice. ``expansion=none``
    then stops ffmpeg reading ``%`` or ``{}`` in the prose as something to substitute.
    """
    if not captions:
        return ""
    folder = out_dir / "captions"
    folder.mkdir(parents=True, exist_ok=True)
    size = caption_size(height)
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
                    # A fixed band at the bottom, whose rows the windows and the overlay are
                    # kept out of (:func:`caption_band_top`). Room for two lines, so a caption
                    # that wraps does not push the band over anything.
                    f"y={caption_text_top(height)}",
                    "box=1",
                    "boxcolor=black@0.62",
                    f"boxborderw={BOX_BORDER}",
                    f"enable='between(n\\,{caption.first - 1}\\,{caption.last - 1})'",
                ]
            )
        )
    return prefix + ",".join(parts)


def _escape(value: str) -> str:
    """A path inside an ffmpeg filter argument."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def write_srt(path: Path, captions: list[Caption], fps: int) -> Path:
    """The same captions as a sidecar, so the plain video can be used as it is."""
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
