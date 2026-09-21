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

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from tools.demo.scenario import Scenario
from tools.demo.scenario import programs as scenario_programs
from tools.headless import HeadlessSession, WindowRule, compositor

"""Placement rules come from the scenario: each ``windows`` entry carries its own ``app_id``
(default ``foot*``, wide enough for every terminal the demo starts) and its title, which is
what tells two terminals apart. A window of its own, like the GUI stub, names its own."""
KEYBINDS = (("W-h", "toggle"), ("W-C-h", "edit-mode"))
"""What the person's own compositor config does (README, compositor の設定)."""

HERDR = "herdr"
"""The name looked up on PATH once, at the start of a recording. After that the resolved path
is used, so nothing later -- including ``demo/bin`` being first on the session PATH -- can put
a different program in its place."""
CONFIG_ENV = "WAYHINT_DEMO_CONFIG"
"""Where the session's copy of the fixtures is, for the one stub that opens a file in it."""
HERDR_BIN_ENV = "WAYHINT_DEMO_HERDR_BIN"
"""How that resolved path reaches ``demo/bin/foot-herdr``, which starts Herdr in a terminal.
The wrapper refuses to run without it rather than falling back to a bare ``herdr``."""
HERDR_STOP_TIMEOUT = 15.0
HERDR_GONE_TIMEOUT = 5.0
DEMO_ROOT = "wayhint-demo"
"""The one directory under /tmp that a recording's throwaway files live in."""
WORK_DIR = "demo"
"""The directory the terminals are started in. Herdr names its workspace after it, and that
name is on screen, so it is a fixed readable word rather than a temporary path."""

PANE_PROGRAM = "idle"
"""What Herdr starts in a pane instead of a shell (``demo/bin/idle``, DECISIONS 0032)."""

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
# Stops the background fetch of agent-detection manifests from herdr.dev: no network, and no
# difference between a run that fetched and one that did not.
manifest_check = false
[ui]
prompt_new_tab_name = false
# Default is "{{hostname}}: {{workspace}}", and the hostname would be in every frame.
window_title = "{{workspace}}"
[terminal]
# Not a shell. A scenario types into the terminal, so a shell in the pane would be a way to
# run anything; this one only ever starts the stubs beside it (DECISIONS 0032).
default_shell = "{pane_program}"
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
    """The throwaway directory a recording runs in -- at a *fixed* path, made fresh.

    Fixed because the overlay shows the path of a sheet it could not read, and the demo records
    that on purpose (the YAML-error scene). A ``mkdtemp`` name would put a different string on
    screen every run and there goes frame-for-frame reproducibility. It carries no uid either:
    the path is *on screen*, and ``/tmp/wayhint-demo-1000-herdr-ja`` reads like an accident to
    whoever watches the video (DECISIONS 0032). Two people recording on one machine at the same
    time is not a case this supports -- the second one is told to look at the first.

    An existing directory is refused rather than emptied: it means either a recording that is
    still running, whose files would be pulled out from under it, or one that died and left
    something worth looking at.
    """
    root = Path(tempfile.gettempdir()) / DEMO_ROOT / f"{showcase}-{language}"
    if root.exists():
        raise DemoError(
            f"{root} is already there. Another recording of {showcase} in {language} may be "
            f"running; if not, remove it and start again (rm -rf {root})"
        )
    try:
        root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.mkdir(mode=0o700)
    except OSError as e:
        raise DemoError(f"cannot make {root}: {e}") from e
    (root / WORK_DIR).mkdir()
    return root


def release(work: Path) -> None:
    """Remove a workspace, and the directory that held it once it is the last one."""
    shutil.rmtree(work, ignore_errors=True)
    with contextlib.suppress(OSError):
        work.parent.rmdir()  # not empty means another language or showcase is still recording


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
        # Resolved here rather than on every call: the session's own PATH starts with
        # demo/bin, and this must not be something that turned up in there. ``None`` when
        # Herdr is not installed -- a scenario that needs it has already been stopped by
        # ``check_requirements``, and one that does not is recorded without it.
        self.herdr_path = shutil.which(HERDR)
        self.session = HeadlessSession(
            config_dir,
            width=scenario.output.width,
            height=scenario.output.height,
            keybinds=KEYBINDS,
            window_rules=[
                WindowRule(w.app_id, w.x, w.y, w.width, w.height, title=w.title)
                for w in scenario.windows
            ],
            # The overlay's own text cursor blinks in the search box and in the form. Anything
            # that animates makes two recordings of the same scenario differ (DECISIONS 0031).
            gtk_settings={"gtk-cursor-blink": "false"},
            # demo/bin first: a command typed into a pane is echoed on screen, so it is typed
            # by name, and the name has to reach the stub rather than the real program. The
            # one program that is *not* found that way is Herdr, whose path was resolved
            # above and is handed to the wrapper instead.
            extra_env=self._env(),
            tag="d",
        )

    def _env(self) -> dict[str, str]:
        env = {
            "PATH": f"{self.demo_bin}:{os.environ.get('PATH', '')}",
            CONFIG_ENV: str(self.config_dir),
        }
        if self.herdr_path is not None:
            env[HERDR_BIN_ENV] = self.herdr_path
        return env

    def __enter__(self) -> DemoSession:
        """Bring the session up, undoing each stage if a later one fails."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.session)
            stack.callback(self.stop_herdr)
            self._write_herdr_config()
            self._check_stubs()
            self._check_output()
            stack.pop_all()
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
        """Nothing outside ``demo/bin`` can be started in this session.

        This is the guard on the rule that matters most here: the demo runs *stubs*, never the
        real coding agents (DECISIONS 0032). A missing PATH entry would silently start the real
        program instead -- it happened once during development -- and the recording would show
        that program's first-run screen. Three routes are checked: what a ``spawn`` starts,
        what ``herdr pane run`` starts, and what Herdr itself puts in a pane.
        """
        path = self.session.env()["PATH"]
        wanted = [(step.id, name) for step in self.scenario.steps.values()
                  for name in scenario_programs(step)]  # fmt: skip
        wanted.append(("herdr's own panes", PANE_PROGRAM))
        for where, name in wanted:
            found = shutil.which(name, path=path)
            if found is None or Path(found).resolve().parent != self.demo_bin:
                raise DemoError(
                    f"{where} would run {found or name!r}, not the stub in {self.demo_bin}; "
                    "the session PATH is wrong"
                )

    # --- herdr ---------------------------------------------------------------------------

    def _write_herdr_config(self) -> None:
        """Herdr reads ``$XDG_CONFIG_HOME/herdr/``, which is inside the session (C-A)."""
        directory = Path(self.session.env()["XDG_CONFIG_HOME"]) / "herdr"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "config.toml").write_text(
            HERDR_CONFIG.format(pane_program=self.demo_bin / PANE_PROGRAM)
        )

    def herdr(self, *args: str, check: bool = True, timeout: float = 20.0) -> str:
        """Run one Herdr command inside the session. The caller has already allow-listed it."""
        if self.herdr_path is None:
            raise DemoError(f"herdr {' '.join(args)}: herdr is not on PATH")
        done = subprocess.run(
            [self.herdr_path, *args],
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
