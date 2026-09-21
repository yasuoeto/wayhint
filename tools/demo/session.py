"""The session a demo is recorded in: the same headless compositor the GUI tests use.

Nothing here touches the session the person is sitting in (DECISIONS 0030): the compositor gets
its own runtime directory, config home, HOME and session bus, and all of it is removed on the
way out. The fixtures are copied into that throwaway HOME first, because the demo edits them --
the edit-mode scene writes a hint and the YAML-error scene breaks a sheet on purpose, and
``demo/fixtures/`` has to come out of a recording unchanged.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tools.demo.scenario import Scenario
from tools.headless import HeadlessSession, WindowRule, compositor

APP_ID = "foot.p*"
KEYBINDS = (("W-h", "toggle"), ("W-C-h", "edit-mode"))
"""What the person's own compositor config does (README, compositor の設定)."""

FONT_PACKAGES = {
    "Noto Sans CJK JP": "fonts-noto-cjk",
    "Noto Sans Mono": "fonts-noto-mono",
    "Noto Sans": "fonts-noto-core",
}
TOOL_PACKAGES = {
    "ffmpeg": "ffmpeg",
    "grim": "grim",
    "magick": "imagemagick",
    "montage": "imagemagick",
    "wtype": "wtype",
    "foot": "foot",
    "labwc": "labwc",
}


class DemoError(Exception):
    """Something the recording needs is missing or wrong. The message says how to fix it."""


@dataclass(frozen=True)
class Requirements:
    """What a recording needs on top of what the GUI tests need."""

    tools: tuple[str, ...]
    fonts: tuple[str, ...]


def check_requirements(need: Requirements) -> None:
    """Fail before a compositor is started, naming the package to install."""
    missing_tools = [name for name in need.tools if shutil.which(name) is None]
    if missing_tools:
        packages = sorted({TOOL_PACKAGES.get(name, name) for name in missing_tools})
        raise DemoError(
            f"not on PATH: {', '.join(missing_tools)} -- sudo apt install {' '.join(packages)}"
        )
    if compositor() is None:
        raise DemoError("no compositor on PATH -- sudo apt install labwc")
    missing_fonts = [name for name in need.fonts if not _have_font(name)]
    if missing_fonts:
        packages = sorted(
            {FONT_PACKAGES.get(name, "a font providing it") for name in missing_fonts}
        )
        raise DemoError(
            f"font not installed: {', '.join(missing_fonts)} -- "
            f"sudo apt install {' '.join(packages)}"
        )


def _have_font(family: str) -> bool:
    """True when fontconfig answers with the family that was asked for, not a substitute."""
    try:
        done = subprocess.run(
            ["fc-match", "-f", "%{family}", family], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0:
        return False
    return family in [part.strip() for part in done.stdout.split(",")]


def font_file(family: str) -> str:
    """The file fontconfig resolves a family to, for ffmpeg's drawtext."""
    done = subprocess.run(
        ["fc-match", "-f", "%{file}", family], capture_output=True, text=True, timeout=15
    )
    if done.returncode != 0 or not done.stdout.strip():
        raise DemoError(f"no font file for {family!r}")
    return done.stdout.strip()


def workspace(language: str) -> Path:
    """The throwaway directory a recording runs in -- at a *fixed* path, and emptied first.

    Fixed because the overlay shows the path of a sheet it could not read, and the demo records
    that on purpose (the YAML-error scene). A ``mkdtemp`` name would put a different string on
    screen every run and there goes frame-for-frame reproducibility. The uid keeps two people
    on one machine out of each other's way.
    """
    root = Path(tempfile.gettempdir()) / f"wayhint-demo-{os.getuid()}-{language}"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(mode=0o700, parents=True)
    return root


def prepare_config(fixtures: Path, language: str, into: Path) -> Path:
    """A throwaway copy of the fixtures, set to one language.

    The copy is what the daemon reads and what the demo writes to. ``appearance.language`` is
    replaced rather than templated so that ``demo/fixtures/config.yaml`` stays a file a person
    can read and ``wayhint validate`` can check.
    """
    root = into / "config"
    shutil.copytree(fixtures, root)
    config = root / "config.yaml"
    text = config.read_text()
    lines = [
        f"  language: {language}" if line.strip().startswith("language:") else line
        for line in text.splitlines()
    ]
    if not any(line.strip().startswith("language:") for line in lines):
        raise DemoError(f"{fixtures / 'config.yaml'}: no appearance.language to set")
    config.write_text("\n".join(lines) + "\n")
    return root


class DemoSession:
    """A headless session with the demo's keybinds, window placement and fixtures."""

    def __init__(self, scenario: Scenario, config_dir: Path) -> None:
        self.scenario = scenario
        self.config_dir = config_dir
        self.session = HeadlessSession(
            config_dir,
            width=scenario.output.width,
            height=scenario.output.height,
            keybinds=KEYBINDS,
            window_rules=[
                WindowRule(APP_ID, w.x, w.y, w.width, w.height, title=w.title)
                for w in scenario.windows
            ],
            # The overlay's own text cursor blinks in the search box and in the form. Anything
            # that animates makes two recordings of the same scenario differ (DECISIONS 0031).
            gtk_settings={"gtk-cursor-blink": "false"},
            tag="d",
        )
        self._temp: Path | None = None

    def __enter__(self) -> DemoSession:
        self.session.__enter__()
        try:
            self._check_output()
        except Exception:
            self.session.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> None:
        self.session.__exit__(*exc)

    def _check_output(self) -> None:
        """The recording is only reproducible if every frame is the size the scenario says."""
        with tempfile.TemporaryDirectory(prefix="wayhint-demo-") as tmp:
            frame = self.session.grab(Path(tmp) / "size.png", settle=0.2)
            size = subprocess.run(
                ["magick", "identify", "-format", "%wx%h", str(frame)],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout.strip()
        want = f"{self.scenario.output.width}x{self.scenario.output.height}"
        if size != want:
            raise DemoError(
                f"the headless output is {size}, the scenario says {want}; "
                f"run wlr-randr --output HEADLESS-1 --custom-mode {want} inside the session"
            )
