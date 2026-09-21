"""Doing what a step says, and knowing when it has happened.

Two rules hold this together. An action is chosen from a fixed set and started with a fixed
argv -- no string out of the scenario is ever evaluated. And every step waits for a *condition*
rather than for a number of seconds: the recording then takes as long as the machine needs, and
the video still comes out the length the scenario asked for, because the frames are counted
separately (``capture``).
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tools.demo.scenario import BUTTONS, Condition, Step
from tools.demo.session import DemoError, DemoSession
from wayhint import ipc
from wayhint.i18n import translator

POLL = 0.15
TYPE_SETTLE = 0.3


@dataclass
class Run:
    """What the steps so far have left running, so later steps and the cleanup can find it."""

    session: DemoSession
    language: str
    demo_bin: Path
    windows: dict[str, subprocess.Popen]

    @property
    def tr(self):
        return translator(self.language)

    def button_label(self, logical: str) -> str:
        """``search`` -> ``Search`` -> ``検索``: the label the widget actually carries."""
        return self.tr(BUTTONS[logical])


def perform(run: Run, step: Step) -> None:
    """Carry out the one action of a step."""
    kind, payload = step.action.kind, step.action.payload
    session = run.session.session
    if kind == "spawn":
        # The scenario names programs; the recorder turns them into paths. Nothing from the
        # file reaches PATH resolution, so a stub cannot be shadowed by a real program of the
        # same name (DECISIONS 0032).
        argv = [
            part if index and part.startswith("-") else str(run.demo_bin / part)
            for index, part in enumerate(payload["argv"])
        ]
        # The title is how the compositor rule finds this window (scenario ``windows``), so it
        # is put in by the recorder rather than written into every argv in the scenario.
        argv.insert(1, f"--title={payload['window']}")
        # Always the same working directory: Herdr names its workspace after it and shows that
        # name in the sidebar, so a temporary path would differ between runs (DECISIONS 0032).
        run.windows[payload["window"]] = session.spawn(argv, cwd=run.session.work_dir)
    elif kind == "close":
        # The counterpart of ``spawn``: with the window gone the compositor gives the focus
        # back to the one underneath, which is how a scene can visit another application and
        # return without a pointer or a window-switcher binding.
        window = run.windows.pop(payload["window"], None)
        if window is None:
            raise DemoError(f"step {step.id!r}: no window called {payload['window']!r} is open")
        session.stop(window)
    elif kind == "key":
        session.press(*payload["keys"])
    elif kind == "type":
        session.type_text(payload["text"][run.language])
        # Typing is delivered synchronously, drawing it is not. The capture waits for a still
        # screen anyway; this only keeps it from deciding the screen is still before the first
        # character has landed on it.
        time.sleep(TYPE_SETTLE)
    elif kind == "press":
        label = run.button_label(payload["button"])
        if not session.a11y_press(label):
            raise DemoError(
                f"step {step.id!r}: no button named {label!r} on the overlay "
                "(is it visible, and in the right mode?)"
            )
    elif kind == "cli":
        session.wayhint(payload["command"])
    elif kind == "herdr":
        run.session.herdr(*payload["argv"])  # already checked against the allow-list
    elif kind == "pause":
        pass  # the step exists for its caption; ``wait_for`` still has to hold
    else:
        _write(run, step)


def _write(run: Run, step: Step) -> None:
    payload = step.action.payload
    target = _inside(run.session.config_dir, _expand(payload["file"], run), step)
    if not target.parent.is_dir():
        raise DemoError(f"step {step.id!r}: no directory for {payload['file']}")
    if "source" in payload:
        source = _inside(run.demo_bin.parent, _expand(payload["source"], run), step)
        if not source.is_file():
            raise DemoError(f"step {step.id!r}: no such file to copy from: {source}")
        target.write_text(source.read_text())
    else:
        target.write_text(payload["text"])


def _inside(root: Path, relative: str, step: Step) -> Path:
    """Resolve a path from the scenario, and refuse anything that leaves ``root``.

    The parser already rejects ``..`` and absolute paths; this checks the result as well,
    because the substitution happens after that and a symlink could point anywhere.
    """
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise DemoError(f"step {step.id!r}: {relative} would write outside {root}")
    return target


def _expand(part: str, run: Run) -> str:
    """The only substitution a scenario gets. Everything else is taken literally."""
    return part.replace("{lang}", run.language)


# --- conditions --------------------------------------------------------------------------------


def satisfied(run: Run, cond: Condition) -> tuple[bool, str]:
    """Whether the condition holds, and what was seen when it did not."""
    session = run.session.session
    seen: list[str] = []
    if cond.toplevel or cond.process_name or cond.active_sheet:
        reply = _context(run)
        app_id = reply.get("desktop_app") or ""
        process = (reply.get("process") or {}).get("name") or ""
        sheet = reply.get("active_sheet") or ""
        seen.append(f"toplevel={app_id!r} process_name={process!r} active_sheet={sheet!r}")
        if cond.toplevel and not re.search(cond.toplevel, app_id):
            return False, seen[-1]
        if cond.process_name and process != cond.process_name:
            return False, seen[-1]
        if cond.active_sheet and sheet != cond.active_sheet:
            return False, seen[-1]
    if (
        cond.overlay is not None
        or cond.label is not None
        or cond.no_label is not None
        or cond.button is not None
        or cond.hints is not None
    ):
        nodes = [node for node in session.a11y_nodes() if node.showing]
        names = [node.name for node in nodes]
        rows = sum(1 for node in nodes if node.role == "list item")
        state = "visible" if nodes else "hidden"
        seen.append(f"overlay={state} hints={rows}")
        if cond.overlay is not None and state != cond.overlay:
            return False, seen[-1]
        if cond.label is not None:
            wanted = run.tr(cond.label)
            if not any(wanted in name for name in names):
                return False, f"{seen[-1]} labels={_sample(names)}"
        if cond.no_label is not None:
            unwanted = run.tr(cond.no_label)
            if any(unwanted in name for name in names):
                return False, f"{seen[-1]} labels={_sample(names)}"
        if cond.button is not None:
            wanted = run.button_label(cond.button)
            buttons = [node.name for node in nodes if node.role == "button"]
            if wanted not in buttons:
                return False, f"{seen[-1]} buttons={buttons}"
        if cond.hints is not None and rows != cond.hints:
            return False, seen[-1]
    return True, "; ".join(seen)


def _sample(names: list[str], limit: int = 8) -> list[str]:
    return [name for name in names if name][:limit]


def _context(run: Run) -> dict:
    reply = ipc.send_command("context", run.session.session.runtime / "wayhint.sock")
    if not reply.get("ok"):
        raise DemoError(f"the daemon could not resolve the context: {reply.get('error')}")
    return reply


def wait_until(run: Run, cond: Condition, what: str) -> str:
    """Poll until the condition holds, or fail saying what was there instead.

    Returns what it saw, so the recording log shows the state each frame was taken in -- which
    is the evidence that the demo went through the real context resolution and not a fixture.
    """
    deadline = time.monotonic() + cond.timeout
    last = ""
    while True:
        ok, last = satisfied(run, cond)
        if ok:
            return last
        if time.monotonic() >= deadline:
            break
        time.sleep(POLL)
    raise DemoError(
        f"{what}: waited {cond.timeout:g}s for {cond.describe()}, saw {last or 'nothing'}\n"
        + run.session.session.log_tail(12)
    )
