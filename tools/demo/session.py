"""The session a demo is recorded in: the same headless compositor the GUI tests use.

Nothing here touches the session the person is sitting in (DECISIONS 0030): the compositor gets
its own runtime directory, config home, HOME and session bus, and all of it is removed on the
way out. The fixtures are copied into that throwaway HOME first, because the demo edits them --
the edit-mode scene writes a hint and the YAML-error scene breaks a sheet on purpose, and
``demo/fixtures/`` has to come out of a recording unchanged.

Herdr is the one real program a recording runs (DECISIONS 0032), and it gets the same treatment:
its config, socket, logs and state all live under the session's ``XDG_CONFIG_HOME``, it is
started with ``HERDR_*`` stripped from the environment so a client in here cannot reach the
person's own server, and it is stopped before the session is torn down.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from tools.demo.scenario import Scenario
from tools.headless import HeadlessSession, WindowRule, compositor

APP_ID = "foot*"
"""Every terminal the demo starts, whatever suffix it carries.

The placement rules tell the windows apart by *title*, which the recorder sets from the
scenario, so the app_id only has to be wide enough to catch them all: ``foot.p<pid>`` from the
pid-suffix convention and ``foot-herdr`` from the one Herdr runs in (docs/TERMINALS.md)."""
KEYBINDS = (("W-h", "toggle"), ("W-C-h", "edit-mode"))
"""What the person's own compositor config does (README, compositor の設定)."""

HERDR = "herdr"
HERDR_STOP_TIMEOUT = 15.0
HERDR_GONE_TIMEOUT = 5.0
WORK_DIR = "demo"
"""The directory the terminals are started in. Herdr names its workspace after it, and that
name is on screen, so it is a fixed readable word rather than a temporary path."""

HERDR_CONFIG = """\
# Written by tools/demo/session.py for one recording. Everything that would reach the network,
# ask a question, or put a machine-specific string on screen is turned off (DECISIONS 0032).
onboarding = false
[theme]
# Pinned, or Herdr asks the user to choose one on first run and that question is what the
# recording would show instead of the terminal.
name = "catppuccin"
[update]
version_check = false
manifest_check = false
[ui]
prompt_new_tab_name = false
window_title = "{workspace}"
[terminal]
default_shell = "/bin/sh"
"""

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
TOOL_NOTES = {"herdr": "herdr is not an apt package; see https://herdr.dev"}


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
        notes = [TOOL_NOTES[name] for name in missing_tools if name in TOOL_NOTES]
        packages = sorted({TOOL_PACKAGES[name] for name in missing_tools if name in TOOL_PACKAGES})
        hint = f" -- sudo apt install {' '.join(packages)}" if packages else ""
        raise DemoError(
            f"not on PATH: {', '.join(missing_tools)}{hint}"
            + ("".join(f"\n  {note}" for note in notes))
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


def workspace(showcase: str, language: str) -> Path:
    """The throwaway directory a recording runs in -- at a *fixed* path, and emptied first.

    Fixed because the overlay shows the path of a sheet it could not read, and the demo records
    that on purpose (the YAML-error scene). A ``mkdtemp`` name would put a different string on
    screen every run and there goes frame-for-frame reproducibility. The uid keeps two people
    on one machine out of each other's way.
    """
    root = Path(tempfile.gettempdir()) / f"wayhint-demo-{os.getuid()}-{showcase}-{language}"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(mode=0o700, parents=True)
    (root / WORK_DIR).mkdir()
    return root


def prepare_config(fixtures: Path, language: str, into: Path) -> Path:
    """A throwaway copy of the fixtures, set to one language.

    The copy is what the daemon reads and what the demo writes to. ``appearance.language`` is
    replaced rather than templated so that ``demo/fixtures/config.yaml`` stays a file a person
    can read and ``wayhint validate`` can check.
    """
    root = into / "config"
    shutil.copytree(fixtures, root)
    hints = root / "hints" / language
    if not hints.is_dir():
        raise DemoError(
            f"no hints for {language!r}: {fixtures / 'hints' / language} does not exist "
            f"(the sheets are written per language; see demo/README.md)"
        )
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


def session_herdr_pids(home: Path) -> list[int]:
    """Herdr processes belonging to *this* session, found by their HOME.

    The server daemonises out of the session's process group, so it survives the kill that
    takes the compositor down, and it cannot be found by name either -- the person's own Herdr
    is running too and must not be touched. The environment is the one thing that separates
    them.
    """
    want = f"HOME={home}".encode()
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_bytes().strip() != HERDR.encode():
                continue
            if want in (entry / "environ").read_bytes().split(b"\0"):
                pids.append(int(entry.name))
        except OSError:
            continue  # it exited while we looked at it
    return pids


class DemoSession:
    """A headless session with the demo's keybinds, window placement and fixtures."""

    def __init__(
        self, scenario: Scenario, config_dir: Path, work_dir: Path, demo_bin: Path
    ) -> None:
        self.scenario = scenario
        self.config_dir = config_dir
        self.work_dir = work_dir
        self.demo_bin = demo_bin.resolve()
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
            # demo/bin first: a command typed into a pane is echoed on screen, so it is typed
            # by name, and the name has to reach the stub rather than the real program.
            extra_env={"PATH": f"{self.demo_bin}:{os.environ.get('PATH', '')}"},
            tag="d",
        )

    def __enter__(self) -> DemoSession:
        self.session.__enter__()
        try:
            self._write_herdr_config()
            self._check_stubs()
            self._check_output()
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> None:
        home = self.session.home
        try:
            self.stop_herdr()
        finally:
            self.session.__exit__(*exc)
            # A Herdr that had to be killed writes its session file on the way out, which
            # re-creates the directory the line above just removed (measured in C-A).
            if home.exists():
                shutil.rmtree(home, ignore_errors=True)

    def _check_stubs(self) -> None:
        """Every program the scenario runs in a pane has to resolve to ``demo/bin``.

        This is the guard on the one rule that matters most here: the demo runs *stubs*, never
        the real coding agents (DECISIONS 0032). A missing PATH entry would silently start the
        real program instead -- it happened once during development -- and the recording would
        show that program's first-run screen.
        """
        path = self.session.env()["PATH"]
        for step in self.scenario.steps.values():
            if step.action.kind != "herdr":
                continue
            argv = step.action.payload["argv"]
            if argv[:2] != ["pane", "run"] or len(argv) < 4:
                continue
            command = argv[3]
            found = shutil.which(command, path=path)
            if found is None or Path(found).parent != self.demo_bin:
                raise DemoError(
                    f"step {step.id!r} would run {found or command!r}, not the stub in "
                    f"{self.demo_bin}; the session PATH is wrong"
                )

    # --- herdr ---------------------------------------------------------------------------

    def _write_herdr_config(self) -> None:
        """Herdr reads ``$XDG_CONFIG_HOME/herdr/``, which is inside the session (C-A)."""
        directory = Path(self.session.env()["XDG_CONFIG_HOME"]) / "herdr"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "config.toml").write_text(HERDR_CONFIG)

    def herdr(self, *args: str, check: bool = True, timeout: float = 20.0) -> str:
        """Run one Herdr command inside the session. The caller has already allow-listed it."""
        done = subprocess.run(
            [HERDR, *args],
            env=self.session.env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and done.returncode != 0:
            raise DemoError(f"herdr {' '.join(args)}: {done.stderr.strip()[-400:]}")
        return done.stdout.strip()

    def stop_herdr(self) -> None:
        """Ask Herdr to stop, then make sure it did -- without touching anyone else's."""
        home = self.session.home
        if not session_herdr_pids(home):
            return
        try:
            self.herdr("server", "stop", check=False, timeout=HERDR_STOP_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            pass
        if self._wait_gone(home):
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in session_herdr_pids(home):
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            if self._wait_gone(home):
                return

    @staticmethod
    def _wait_gone(home: Path) -> bool:
        deadline = time.monotonic() + HERDR_GONE_TIMEOUT
        while time.monotonic() < deadline:
            if not session_herdr_pids(home):
                return True
            time.sleep(0.2)
        return not session_herdr_pids(home)

    # --- the output ----------------------------------------------------------------------

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
