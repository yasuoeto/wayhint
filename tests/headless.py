"""A Wayland session of its own, for tests that need the overlay actually on a screen.

The in-process tests never map a surface, so they cannot see where the compositor put it or what
it drew. This starts a compositor on the wlroots headless backend -- no monitor, no input devices
-- runs ``wayhintd`` inside it and reads the result back with grim.

Nothing touches the session the person running the tests is sitting in. It gets its own runtime
directory, its own ``XDG_CONFIG_HOME`` (so *their* autostart does not launch their panel, their
wallpaper and a second ``wayhintd`` inside the test session), its own D-Bus session bus and its
own socket. All of it is removed again on exit.

Not part of ``./scripts/check``: it needs a compositor binary and the capture tools, and takes
seconds rather than milliseconds. ``./scripts/check-gui`` is the entry point.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPOSITORS = ("labwc", "sway", "cage")
TOOLS = ("grim", "magick")
INJECT = "wtype"
HEADLESS_OUTPUT = "HEADLESS-1"
START_TIMEOUT = 15.0
ENABLE = "WAYHINT_GUI_TESTS"


def _compositor() -> str | None:
    return next((name for name in COMPOSITORS if shutil.which(name)), None)


def requirements() -> str | None:
    """What is missing, or ``None`` when a headless session can be built here."""
    if os.environ.get(ENABLE) != "1":
        return f"{ENABLE} is not set (run ./scripts/check-gui)"
    if _compositor() is None:
        return f"no compositor on PATH ({' / '.join(COMPOSITORS)})"
    for tool in TOOLS:
        if shutil.which(tool) is None:
            return f"{tool} is not on PATH"
    if not os.environ.get("XDG_RUNTIME_DIR"):
        return "no XDG_RUNTIME_DIR"
    if not (REPO / ".venv" / "bin" / "wayhintd").exists():
        return "no .venv/bin/wayhintd (run ./scripts/setup)"
    return None


needs_headless = unittest.skipUnless(requirements() is None, requirements() or "")
needs_key_injection = unittest.skipUnless(
    requirements() is None and shutil.which(INJECT) is not None,
    requirements() or f"{INJECT} is not on PATH",
)


class HeadlessSession:
    """A compositor, a session bus and a ``wayhintd``, all thrown away on exit."""

    def __init__(
        self,
        config_dir: Path,
        *,
        width: int = 1280,
        height: int = 720,
        keybind: tuple[str, str] | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.width, self.height = width, height
        # ``(key, wayhint command)``: what the person's own compositor config does, so the path
        # from a key press to the daemon can be driven end to end.
        self.keybind = keybind
        self.compositor = _compositor()
        self.display = "wayland-0"
        # AF_UNIX paths are capped at about 108 bytes, so this has to be short; a directory under
        # a temporary root is already too long. It sits beside the real runtime dir, not in it.
        self.runtime = Path(os.environ["XDG_RUNTIME_DIR"]) / f"wh-t{os.getpid()}"
        self.home = Path(tempfile.mkdtemp(prefix="wayhint-headless-"))
        self._procs: list[subprocess.Popen] = []
        self._bus: subprocess.Popen | None = None

    # --- environment -----------------------------------------------------------------------

    def env(self, *, inside: bool = True) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        env["XDG_RUNTIME_DIR"] = str(self.runtime)
        env["XDG_CONFIG_HOME"] = str(self.home / "config")
        env["HOME"] = str(self.home)
        if self._bus_address:
            env["DBUS_SESSION_BUS_ADDRESS"] = self._bus_address
        if inside:
            env["WAYLAND_DISPLAY"] = self.display
        return env

    # --- lifecycle -------------------------------------------------------------------------

    def __enter__(self) -> HeadlessSession:
        self._bus_address = ""
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.home / "config" / self.compositor).mkdir(parents=True, exist_ok=True)
        (self.home / "config" / self.compositor / "autostart").write_text("")
        self._write_compositor_config()
        self.log = open(self.home / "session.log", "w+")
        self._start_bus()
        self._spawn(
            [self.compositor],
            {
                **self.env(inside=False),
                "WLR_BACKENDS": "headless",
                "WLR_LIBINPUT_NO_DEVICES": "1",
                "WLR_HEADLESS_OUTPUTS": "1",
                "WLR_RENDERER": "pixman",
            },
        )
        self._wait_for(self.runtime / self.display, "the compositor's socket")
        self._spawn(
            [str(REPO / ".venv" / "bin" / "wayhintd"), "--config-dir", str(self.config_dir), "-v"],
            self.env(),
        )
        self._wait_for(self.runtime / "wayhint.sock", "the daemon's socket")
        # The first map of a GTK surface pulls in the renderer and can take a second. Doing it
        # once here means no measurement has to carry that cost or race it.
        self.wayhint("show")
        self.wayhint("hide")
        return self

    def __exit__(self, *_exc) -> None:
        # By the group, not by the process: a compositor that re-execs or forks leaves a child
        # behind when only its own pid is signalled, and an orphaned compositor holding the
        # runtime directory is exactly the mess these tests must not leave on the machine.
        started = [*self._procs, *filter(None, [self._bus])]
        for proc in reversed(started):
            self._signal_group(proc, signal.SIGTERM)
        for proc in reversed(started):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._signal_group(proc, signal.SIGKILL)
                proc.wait(timeout=5)
        self.log.close()
        shutil.rmtree(self.runtime, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    @staticmethod
    def _signal_group(proc: subprocess.Popen, sig: int) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, sig)  # each was started with start_new_session=True
        except (ProcessLookupError, PermissionError):
            proc.send_signal(sig)

    def _write_compositor_config(self) -> None:
        """Only labwc is configured here; the others are accepted for placement tests only."""
        if self.keybind is None or self.compositor != "labwc":
            return
        key, command = self.keybind
        cli = REPO / ".venv" / "bin" / "wayhint"
        (self.home / "config" / "labwc" / "rc.xml").write_text(
            '<?xml version="1.0"?>\n<labwc_config>\n  <keyboard>\n'
            f'    <keybind key="{key}">\n'
            f'      <action name="Execute" command="{cli} {command}"/>\n'
            "    </keybind>\n  </keyboard>\n</labwc_config>\n"
        )

    def press(self, *keys: str) -> None:
        """Send a key to the compositor, the way the person's keyboard would (手法 d).

        ``wtype`` speaks ``zwp_virtual_keyboard_manager_v1``, which labwc offers. No uinput and
        no elevated privileges: the key goes in at the compositor, not at the kernel.
        """
        argv = ["wtype"]
        for key in keys[:-1]:
            argv += ["-M", key]
        argv += ["-k", keys[-1]]
        for key in reversed(keys[:-1]):
            argv += ["-m", key]
        subprocess.run(argv, env=self.env(), check=True, capture_output=True, timeout=15)

    def _start_bus(self) -> None:
        """A session bus of the test's own, so AT-SPI answers for this session and no other."""
        self._bus = subprocess.Popen(
            ["dbus-daemon", "--session", "--print-address", "--nofork"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        with self._bus.stdout as out:  # the address is the only thing it ever prints
            self._bus_address = (out.readline() or "").strip()
        if not self._bus_address:
            raise RuntimeError("dbus-daemon printed no address")

    def _spawn(self, argv: list[str], env: dict[str, str]) -> None:
        self._procs.append(
            subprocess.Popen(
                argv, env=env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True
            )
        )

    def _wait_for(self, path: Path, what: str) -> None:
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if path.exists():
                return
            for proc in self._procs:
                if proc.poll() is not None:
                    raise RuntimeError(f"{what}: a process exited\n{self.log_tail()}")
            time.sleep(0.05)
        raise RuntimeError(f"{what} never appeared\n{self.log_tail()}")

    def log_tail(self, lines: int = 25) -> str:
        self.log.flush()
        return "\n".join(Path(self.log.name).read_text(errors="replace").splitlines()[-lines:])

    # --- driving it ------------------------------------------------------------------------

    def wayhint(self, *args: str) -> str:
        done = subprocess.run(
            [str(REPO / ".venv" / "bin" / "wayhint"), *args],
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if done.returncode != 0:
            raise RuntimeError(f"wayhint {' '.join(args)}: {done.stderr.strip()}")
        return done.stdout.strip()

    def toplevel(self, app_id: str) -> subprocess.Popen:
        """A window for the overlay to find a sheet for; closed when the session ends.

        Its cursor must not blink. Anything that animates under the overlay shows up in
        :func:`difference_box` as a change that is not the overlay -- a blinking block cursor is
        ten pixels of it, which is enough to make "the overlay is gone" read as "it is still
        there".
        """
        proc = subprocess.Popen(
            [
                "foot",
                f"--app-id={app_id}",
                "--override=cursor.blink=no",
                "sh",
                "-c",
                "sleep 3600",
            ],
            env=self.env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._procs.append(proc)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if app_id in self.wayhint("context"):
                return proc
            time.sleep(0.1)
        raise RuntimeError(f"{app_id} never became the active window\n{self.log_tail()}")

    # --- reading it back -------------------------------------------------------------------

    def grab(self, path: Path, settle: float = 0.3) -> Path:
        """One frame of the headless output. ``settle`` lets the frame after a command land."""
        time.sleep(settle)
        subprocess.run(
            ["grim", "-o", HEADLESS_OUTPUT, str(path)],
            env=self.env(),
            check=True,
            capture_output=True,
            timeout=15,
        )
        return path

    def overlay_box(self, work: Path) -> tuple[int, int, int, int] | None:
        """Where the overlay is, as ``(width, height, x, y)``, or ``None`` when it is not there.

        Measured as the difference between a frame with the overlay and one without, so the
        answer does not depend on fonts, theme or what else is on screen -- only on what the
        overlay covers. That is the property "位置の安定" is about, and it is the one thing the
        in-process tests cannot see, because they never map a surface.
        """
        self.wayhint("hide")
        off = self.grab(work / "off.png")
        self.wayhint("show")
        # Polled, not slept once: a frame the compositor has not composited yet reads back as no
        # difference at all, which looks exactly like an overlay that never appeared.
        deadline = time.monotonic() + START_TIMEOUT
        box = None
        while box is None and time.monotonic() < deadline:
            box = difference_box(self.grab(work / "on.png"), off)
        return box

    def a11y_names(self, role: str) -> list[str]:
        """Every accessible name with ``role`` under the overlay's frame, in tree order.

        GTK exposes the labels and buttons it built, so this reads what the user would read --
        without a pixel comparison, which would break on any font or theme the next machine has.
        """
        done = subprocess.run(
            ["python3", "-c", _A11Y_PROBE, role],
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if done.returncode != 0:
            raise RuntimeError(f"AT-SPI probe failed: {done.stderr.strip()[-800:]}")
        return done.stdout.splitlines()


def difference_box(on: Path, off: Path) -> tuple[int, int, int, int] | None:
    """The bounding box of what changed between two frames, as ``(width, height, x, y)``."""
    done = subprocess.run(
        [
            "magick",
            str(on),
            str(off),
            "-compose",
            "difference",
            "-composite",
            "-colorspace",
            "Gray",
            "-threshold",
            "5%",
            "-format",
            "%@",
            "info:",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    text = done.stdout.strip()
    if not text or text.startswith("0x0"):
        return None
    size, _, offset = text.partition("+")
    width, _, height = size.partition("x")
    x, _, y = offset.partition("+")
    return int(width), int(height), int(x), int(y)


_A11Y_PROBE = """
import sys

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

Atspi.init()
wanted = sys.argv[1]


def walk(node, role, out):
    if node.get_role_name() == role:
        out.append(node)
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        if child is not None:
            walk(child, role, out)
    return out


desktop = Atspi.get_desktop(0)
for i in range(desktop.get_child_count()):
    app = desktop.get_child_at_index(i)
    if app is None:
        continue
    for frame in walk(app, "frame", []):
        if frame.get_name() != "wayhint":
            continue
        for node in walk(frame, wanted, []):
            print(node.get_name())
"""
