"""A Wayland session of its own, for anything that needs the overlay actually on a screen.

The in-process tests never map a surface, so they cannot see where the compositor put it or what
it drew. This starts a compositor on the wlroots headless backend -- no monitor, no input devices
-- runs ``wayhintd`` inside it and reads the result back with grim. It is shared by the GUI tests
(``tests/headless.py`` adds the unittest gating) and by the demo recorder (``scripts/demo``), so a
change here affects both.

Nothing touches the session the person running the tests is sitting in. It gets its own runtime
directory, its own ``XDG_CONFIG_HOME`` (so *their* autostart does not launch their panel, their
wallpaper and a second ``wayhintd`` inside the test session), its own D-Bus session bus and its
own socket. All of it is removed again on exit.

Not part of ``./scripts/check``: it needs a compositor binary and the capture tools, and takes
seconds rather than milliseconds. ``./scripts/check-gui`` is the test entry point.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

REPO = Path(__file__).resolve().parent.parent
COMPOSITORS = ("labwc", "sway", "cage")
TOOLS = ("grim", "magick")
INJECT = "wtype"
HEADLESS_OUTPUT = "HEADLESS-1"
START_TIMEOUT = 15.0


@dataclass(frozen=True)
class WindowRule:
    """Where the compositor puts a window, so two runs record the same picture.

    A client asks for a size and the compositor decides; on the headless backend nothing else
    is on screen, so without a rule the answer is whatever the client happened to ask for. The
    criteria are labwc's (``identifier`` is the app_id, glob, case-insensitive) and the actions
    are ``MoveTo`` / ``ResizeTo``.
    """

    identifier: str
    x: int
    y: int
    width: int
    height: int
    title: str | None = None

    def xml(self) -> list[str]:
        crit = f"identifier={quoteattr(self.identifier)}"
        if self.title is not None:
            crit += f" title={quoteattr(self.title)}"
        return [
            f"    <windowRule {crit}>",
            f'      <action name="MoveTo" x="{self.x}" y="{self.y}"/>',
            f'      <action name="ResizeTo" width="{self.width}" height="{self.height}"/>',
            "    </windowRule>",
        ]


@dataclass(frozen=True)
class A11yNode:
    """One node of the overlay's accessible tree, as the probe below reports it."""

    role: str
    name: str
    showing: bool
    actions: tuple[str, ...] = ()


def compositor() -> str | None:
    """The first compositor on PATH that can run on the headless backend, or ``None``."""
    return next((name for name in COMPOSITORS if shutil.which(name)), None)


def missing() -> str | None:
    """What is missing, or ``None`` when a headless session can be built here."""
    if compositor() is None:
        return f"no compositor on PATH ({' / '.join(COMPOSITORS)})"
    for tool in TOOLS:
        if shutil.which(tool) is None:
            return f"{tool} is not on PATH"
    if not os.environ.get("XDG_RUNTIME_DIR"):
        return "no XDG_RUNTIME_DIR"
    if not (REPO / ".venv" / "bin" / "wayhintd").exists():
        return "no .venv/bin/wayhintd (run ./scripts/setup)"
    return None


class HeadlessSession:
    """A compositor, a session bus and a ``wayhintd``, all thrown away on exit."""

    def __init__(
        self,
        config_dir: Path,
        *,
        width: int = 1280,
        height: int = 720,
        keybind: tuple[str, str] | None = None,
        keybinds: Sequence[tuple[str, str]] = (),
        window_rules: Sequence[WindowRule] = (),
        gtk_settings: dict[str, str] | None = None,
        extra_env: dict[str, str] | None = None,
        tag: str | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.width, self.height = width, height
        # ``(key, wayhint command)``: what the person's own compositor config does, so the path
        # from a key press to the daemon can be driven end to end.
        self.keybind = keybind
        # More of the same, for a session that needs several (``W-h`` and ``W-C-h``).
        self.keybinds = tuple(keybinds)
        # Where the compositor puts the windows that are spawned in here, so a recording of
        # them is the same on the next run (:class:`WindowRule`).
        self.window_rules = tuple(window_rules)
        # ``gtk-4.0/settings.ini`` for the clients inside, e.g. ``gtk-cursor-blink=false``.
        self.gtk_settings = dict(gtk_settings or {})
        # Environment for everything started in here, applied before the session's own
        # variables so that those cannot be overridden by accident. A PATH belongs here.
        self.extra_env = dict(extra_env or {})
        self.compositor = compositor()
        self.display = "wayland-0"
        # AF_UNIX paths are capped at about 108 bytes, so this has to be short; a directory under
        # a temporary root is already too long. It sits beside the real runtime dir, not in it.
        self.runtime = Path(os.environ["XDG_RUNTIME_DIR"]) / f"wh-{tag or 't'}{os.getpid()}"
        self.home = Path(tempfile.mkdtemp(prefix="wayhint-headless-"))
        self._procs: list[subprocess.Popen] = []
        self._bus: subprocess.Popen | None = None
        self._bus_address = ""
        self.log: object | None = None

    # --- environment -----------------------------------------------------------------------

    def env(self, *, inside: bool = True) -> dict[str, str]:
        # ``HERDR_*`` goes too. A session started from inside a Herdr pane inherits
        # ``HERDR_SOCKET_PATH``, and a herdr client started in here would then talk to the
        # *person's own* server instead of the one in this session -- measured, not feared.
        # The adapter strips these as well (DECISIONS 0028), but that only covers the daemon's
        # own calls, not a terminal the session starts.
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("DISPLAY", "WAYLAND_DISPLAY") and not k.startswith("HERDR_")
        }
        env.update(self.extra_env)
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
        """Start the session, and take down whatever started if any of it fails.

        Every step after the first can fail -- a compositor that exits, a socket that never
        appears -- and until this returns there is no ``with`` block to run ``__exit__``. The
        stack undoes what has been done so far and is dismissed only on the way out.
        """
        with contextlib.ExitStack() as stack:
            stack.callback(self._tear_down)
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
                [
                    str(REPO / ".venv" / "bin" / "wayhintd"),
                    "--config-dir",
                    str(self.config_dir),
                    "-v",
                ],
                self.env(),
            )
            self._wait_for(self.runtime / "wayhint.sock", "the daemon's socket")
            # The first map of a GTK surface pulls in the renderer and can take a second. Doing
            # it once here means no measurement has to carry that cost or race it.
            self.wayhint("show")
            self.wayhint("hide")
            stack.pop_all()
        return self

    def __exit__(self, *_exc) -> None:
        self._tear_down()

    def _tear_down(self) -> None:
        # By the group, not by the process: a compositor that re-execs or forks leaves a child
        # behind when only its own pid is signalled, and an orphaned compositor holding the
        # runtime directory is exactly the mess these tests must not leave on the machine.
        #
        # In the order they were started -- bus, compositor, daemon -- and stopped in the
        # reverse of it below. The bus went up first because the two after it are given its
        # address, so it is the last thing that may go down: taking it out from under a live
        # compositor is what makes AT-SPI clients hang on the way out.
        started = [*filter(None, [self._bus]), *self._procs]
        for proc in reversed(started):
            self._signal_group(proc, signal.SIGTERM)
        for proc in reversed(started):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._signal_group(proc, signal.SIGKILL)
                proc.wait(timeout=5)
        if self.log is not None:
            self.log.close()
            self.log = None
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

    def _write_gtk_settings(self) -> None:
        if not self.gtk_settings:
            return
        gtk = self.home / "config" / "gtk-4.0"
        gtk.mkdir(parents=True, exist_ok=True)
        rows = "".join(f"{k}={v}\n" for k, v in self.gtk_settings.items())
        (gtk / "settings.ini").write_text(f"[Settings]\n{rows}")

    def _write_compositor_config(self) -> None:
        """Only labwc is configured here; the others are accepted for placement tests only."""
        self._write_gtk_settings()
        binds = ([self.keybind] if self.keybind is not None else []) + list(self.keybinds)
        if self.compositor != "labwc" or not (binds or self.window_rules):
            return
        cli = REPO / ".venv" / "bin" / "wayhint"
        lines = ['<?xml version="1.0"?>', "<labwc_config>"]
        if binds:
            lines.append("  <keyboard>")
            for key, command in binds:
                lines.append(f'    <keybind key="{key}">')
                lines.append(f'      <action name="Execute" command="{cli} {command}"/>')
                lines.append("    </keybind>")
            lines.append("  </keyboard>")
        if self.window_rules:
            lines.append("  <windowRules>")
            for rule in self.window_rules:
                lines.extend(rule.xml())
            lines.append("  </windowRules>")
        lines.append("</labwc_config>")
        (self.home / "config" / "labwc" / "rc.xml").write_text("\n".join(lines) + "\n")

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

    def type_text(self, text: str) -> None:
        """Type a string into whatever has the keyboard, the way the person would.

        The text is an argument, never a command line: ``wtype`` is started directly, with no
        shell, so a scenario cannot smuggle anything through it.
        """
        subprocess.run(
            ["wtype", "--", text], env=self.env(), check=True, capture_output=True, timeout=30
        )

    def _start_bus(self) -> None:
        """A session bus of the test's own, so AT-SPI answers for this session and no other.

        Started with the session's environment, not the one this process happens to have:
        whatever the bus activates later -- the AT-SPI launcher above all -- inherits it, and
        would otherwise put its socket in the *real* ``XDG_RUNTIME_DIR``.
        """
        self._bus = subprocess.Popen(
            ["dbus-daemon", "--session", "--print-address", "--nofork"],
            env=self.env(inside=False),
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

    def spawn(self, argv: Sequence[str], *, cwd: Path | None = None) -> subprocess.Popen:
        """Start a client inside the session and take responsibility for killing it.

        Its output goes nowhere: a program drawing a terminal writes escape sequences, and the
        session log is read as text. Whatever this returns can be passed to :meth:`stop`; what
        is not stopped is killed with everything else on the way out. ``cwd`` matters more than
        it looks: a terminal multiplexer names things after it and puts that name on screen.
        """
        proc = subprocess.Popen(
            list(argv),
            env=self.env(),
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._procs.append(proc)
        return proc

    def stop(self, proc: subprocess.Popen) -> None:
        """Kill one client early, by its group, the way :meth:`__exit__` kills the rest."""
        self._signal_group(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._signal_group(proc, signal.SIGKILL)
            proc.wait(timeout=5)
        if proc in self._procs:
            self._procs.remove(proc)

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

    def _a11y(self, *argv: str) -> list[str]:
        done = subprocess.run(
            ["python3", "-c", _A11Y_PROBE, *argv],
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if done.returncode != 0:
            raise RuntimeError(f"AT-SPI probe failed: {done.stderr.strip()[-800:]}")
        return done.stdout.splitlines()

    def a11y_nodes(self) -> list[A11yNode]:
        """The overlay's accessible tree, in the order a reader would go through it.

        GTK exposes the labels and buttons it built, so this reads what the user would read --
        without a pixel comparison, which would break on any font or theme the next machine has.
        An empty list means the overlay is not on the bus at all, which is how "it is gone"
        reads here.
        """
        return [A11yNode(**json.loads(line)) for line in self._a11y("dump") if line]

    def a11y_names(self, role: str) -> list[str]:
        """Every accessible name with ``role`` under the overlay's frame, in tree order."""
        return [node.name for node in self.a11y_nodes() if node.role == role]

    def a11y_press(self, name: str, role: str = "button") -> bool:
        """Press a widget by the name it publishes. ``False`` when there is no such widget.

        The click is queued, not done: GTK answers the action and runs it on its own loop, so
        the caller has to wait for the *effect* before doing anything that depends on it.
        """
        return self._a11y("press", role, name) == ["ok"]


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
import json
import sys

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi

Atspi.init()
mode = sys.argv[1]


def walk(node, out):
    # Every call can fail: the tree is the live widget tree, and a redraw between two of these
    # calls takes the node away. A dump of what is still there is the right answer -- the
    # caller is polling, and will ask again.
    out.append(node)
    try:
        count = node.get_child_count()
    except Exception:
        return out
    for i in range(count):
        try:
            child = node.get_child_at_index(i)
        except Exception:
            continue
        if child is not None:
            walk(child, out)
    return out


def named(node):
    try:
        return node.get_role_name(), node.get_name()
    except Exception:
        return "", ""


def frames():
    desktop = Atspi.get_desktop(0)
    found = []
    for i in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(i)
        except Exception:
            continue
        if app is None:
            continue
        found += [n for n in walk(app, []) if named(n) == ("frame", "wayhint")]
    return found


def actions(node):
    # Reported for diagnosis only, and defensively: some widgets answer get_n_actions() with
    # a count they then refuse to name, and a dump must not die on one of those.
    iface = node.get_action_iface()
    if iface is None:
        return []
    out = []
    for i in range(iface.get_n_actions()):
        try:
            out.append(iface.get_action_name(i))
        except Exception:
            pass
    return out


def describe(node):
    try:
        return {
            "role": node.get_role_name(),
            "name": node.get_name() or "",
            "showing": node.get_state_set().contains(Atspi.StateType.SHOWING),
            "actions": actions(node),
        }
    except Exception:
        return None


nodes = [n for frame in frames() for n in walk(frame, [])]
if mode == "dump":
    for node in nodes:
        described = describe(node)
        if described is not None:
            print(json.dumps(described))
elif mode == "press":
    role, name = sys.argv[2], sys.argv[3]
    for node in nodes:
        described = describe(node)
        if described is None or described["role"] != role or described["name"] != name:
            continue
        iface = node.get_action_iface()
        try:
            if iface is not None and iface.get_n_actions() and iface.do_action(0):
                print("ok")
        except Exception as e:
            print(f"action failed: {e}", file=sys.stderr)
        break
"""
