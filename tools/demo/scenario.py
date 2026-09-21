"""The script of a showcase: what happens, in what order, and for how long.

A scenario is data. Nothing in it is ever executed as a command -- the actions it can ask for
are a fixed set, their arguments are checked against an allow-list, and the only substitutions
are ``{demo_bin}`` and ``{lang}`` (DECISIONS 0031, 0032).

One scenario holds every step of a showcase once, and each ``variant`` (60s / 3min / 5min) is a
list of step ids. A variant is a *complete* sequence: running exactly those steps from a clean
session has to work, so nothing is inherited from another variant and there are no hidden setup
steps. Two lengths of the same moment are two steps with two ids.

The length of a recording is decided here, in frames, and not by how fast the machine runs:
``hold`` is seconds in the file, rounded to frames on the way in, and the recorder repeats one
captured frame that many times.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from tools.demo import names

LANGUAGES = ("ja", "en")
DEFAULT_LANGUAGE = "ja"
REQUIRED_LANGUAGE = "ja"
"""Japanese is written first and English follows in its own task (DECISIONS 0032).

``--validate`` therefore only insists on ``ja``; a missing ``en`` is an error at ``--record
--lang en`` and nowhere else, so an unfinished translation cannot quietly ship in a recording.
"""

ACTIONS = ("spawn", "close", "key", "type", "press", "cli", "write", "herdr", "pause")

# What ``press: {button: ...}`` and ``wait_for: {button: ...}`` may name, and the English label
# the widget carries. The label itself is looked up per language through ``wayhint.i18n``, so a
# scenario never spells out "検索" and the en recording presses the same button as the ja one.
BUTTONS = {
    "search": "Search",
    "done": "Done",
    "copy": "Copy",
    "editor": "Edit in editor",
    "edit": "Edit",
    "close": "Close",
}

# Modifiers wtype understands, and the ones a scenario is allowed to name.
MODIFIERS = {"super": "logo", "ctrl": "ctrl", "shift": "shift", "alt": "alt"}
KEY_NAMES = {  # a friendly spelling -> the xkb keysym wtype wants
    "enter": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "space": "space",
    "backspace": "BackSpace",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}
KEYSYM = re.compile(r"^[A-Za-z0-9_]+$")


# ``cli:`` may only ask for a command the daemon already answers. A scenario cannot invent an
# argument, so no string from the file ever reaches a command line.
CLI_COMMANDS = ("toggle", "show", "hide", "refresh", "reload", "ping", "context", "edit-mode")

# --- herdr -------------------------------------------------------------------------------------

# Matched with ``fullmatch``, not ``match``: ``$`` also matches just before a trailing newline,
# so ``re.match`` accepts ``"w1:p1\n"`` -- and everything here comes out of the scenario file,
# where a newline is one keystroke away (DECISIONS 0032's threat model).
PANE_ID = re.compile(r"^w\d+:p\d+$")
TAB_ID = re.compile(r"^w\d+:t\d+$")
WORKSPACE_ID = re.compile(r"^w\d+$")
DIRECTIONS = ("left", "right", "up", "down")

RUNNER_ONLY_HERDR = {("server", "stop")}
"""Herdr commands the recorder uses itself and a scenario may not (``session.py`` teardown)."""


class ScenarioError(Exception):
    """A scenario that cannot be recorded. The message says which step and what is wrong."""


def _herdr_no_args(rest: list[str], where: str, _bin: Path | None) -> None:
    if rest:
        raise ScenarioError(f"{where}: takes no further arguments, got {' '.join(rest)}")


def _herdr_focus_flags(rest: list[str], where: str, _bin: Path | None) -> None:
    """``--focus`` / ``--no-focus`` only. ``--cwd`` / ``--env`` / ``--label`` stay with the
    recorder: they would let a scenario choose a path, an environment or on-screen text."""
    for arg in rest:
        if arg not in ("--focus", "--no-focus"):
            raise ScenarioError(f"{where}: only --focus / --no-focus are allowed, got {arg!r}")


def _herdr_pane_selector(rest: list[str], where: str, _bin: Path | None) -> None:
    if rest == ["--current"]:
        return
    if len(rest) == 2 and rest[0] == "--pane" and PANE_ID.fullmatch(rest[1]):
        return
    raise ScenarioError(f"{where}: expected --current or --pane <wN:pN>, got {' '.join(rest)}")


def _herdr_pane_focus(rest: list[str], where: str, _bin: Path | None) -> None:
    if len(rest) < 2 or rest[0] != "--direction" or rest[1] not in DIRECTIONS:
        raise ScenarioError(f"{where}: expected --direction {'|'.join(DIRECTIONS)} first")
    _herdr_pane_selector(rest[2:], where, None)


def _herdr_pane_split(rest: list[str], where: str, _bin: Path | None) -> None:
    allowed = {"--focus", "--no-focus", "--current"}
    index = 0
    seen_direction = False
    while index < len(rest):
        arg = rest[index]
        if arg == "--direction":
            if index + 1 >= len(rest) or rest[index + 1] not in ("right", "down"):
                raise ScenarioError(f"{where}: --direction takes right or down")
            seen_direction, index = True, index + 2
        elif arg == "--pane":
            if index + 1 >= len(rest) or not PANE_ID.fullmatch(rest[index + 1]):
                raise ScenarioError(f"{where}: --pane takes a pane id like w1:p1")
            index += 2
        elif arg in allowed:
            index += 1
        else:
            raise ScenarioError(f"{where}: {arg!r} is not allowed here")
    if not seen_direction:
        raise ScenarioError(f"{where}: --direction is required")


def _herdr_one(pattern: re.Pattern, kind: str):
    def check(rest: list[str], where: str, _bin: Path | None) -> None:
        if len(rest) != 1 or not pattern.fullmatch(rest[0]):
            raise ScenarioError(f"{where}: expected exactly one {kind} id, got {' '.join(rest)}")

    return check


TERMINALS = {"foot-wayhint": "command", "foot-herdr": "no command"}
"""The wrappers in ``demo/bin`` a ``spawn`` may start, and whether each takes a program.

``foot-wayhint`` is a bare terminal, so it has to be told what to run: foot with no command
starts the login shell, and this session is built not to have one (DECISIONS 0032).
``foot-herdr`` starts Herdr itself and therefore takes none. Named one by one rather than
matched on a prefix -- a prefix would accept the next wrapper somebody adds, whatever it does.
"""

APP_ID = re.compile(r"^foot(-[a-z0-9]+|\.p\{pid\})?$")
"""What ``--app-id`` may be set to: the naming convention in docs/TERMINALS.md, and nothing
that would make the window look like another application's to the daemon."""


def _bare_program(name: str, where: str, demo_bin: Path | None) -> str:
    """A program named by its file name in ``demo/bin``, and nothing else.

    No path, no ``..``, no absolute name: the demo runs its own stubs, and the guard is that
    the scenario can only ever name one of them (DECISIONS 0032).
    """
    if not name or "/" in name or ".." in name:
        raise ScenarioError(f"{where}: {name!r} has to be a bare program name in demo/bin")
    if demo_bin is not None and not (demo_bin / name).is_file():
        raise ScenarioError(f"{where}: no such program in {demo_bin}: {name}")
    return name


def _spawn_option(part: str, where: str) -> None:
    """The one option a scenario may hand a terminal wrapper.

    An allow list, not "anything that starts with a dash". ``--override=shell=/bin/sh`` puts
    the shell back that DECISIONS 0032 took out, and ``--config``, ``--server`` and ``--term``
    each reach past the fixtures in their own way.
    """
    if not part.startswith("--app-id="):
        raise ScenarioError(
            f"{where}: {part!r} is not allowed here; a spawn may pass --app-id=<id> and nothing "
            "else (the recorder puts in the title, the config and the program)"
        )
    app_id = part[len("--app-id=") :]
    if not APP_ID.fullmatch(app_id):
        raise ScenarioError(
            f"{where}: {app_id!r} is not an app_id this demo uses (foot, or foot-<name>)"
        )


def _spawn_argv(argv: list[str], where: str, demo_bin: Path | None) -> list[str]:
    """``[foot-herdr]`` or ``[foot-wayhint, -e, vi]``: one wrapper, options, one stub."""
    head = _bare_program(argv[0], f"{where}[0]", demo_bin)
    if head not in TERMINALS:
        raise ScenarioError(
            f"{where}[0]: {head!r} has to start a terminal ({', '.join(sorted(TERMINALS))})"
        )
    rest = list(argv[1:])
    cut = rest.index("-e") if "-e" in rest else len(rest)
    options, command = rest[:cut], rest[cut + 1 :]
    for index, part in enumerate(options, start=1):
        _spawn_option(part, f"{where}[{index}]")
    if TERMINALS[head] == "no command":
        if cut != len(rest):
            raise ScenarioError(f"{where}: {head!r} starts its own program, so it takes no -e")
        return list(argv)
    if not 1 <= len(command) <= 2:
        raise ScenarioError(
            f"{where}: {head!r} needs -e <program> [<file>] last; a terminal with no command "
            "starts the login shell, and a scenario types into the terminal (DECISIONS 0032)"
        )
    _bare_program(command[0], f"{where}[{len(argv) - len(command)}]", demo_bin)
    if len(command) == 2:
        # The one argument a stub may be given: a file in the session's copy of the fixtures,
        # which is what ``vi`` puts on screen. Same rule as ``write.file``.
        _relative(command[1], f"{where}[{len(argv) - 1}]")
    return list(argv)


def spawn_command(argv: list[str]) -> list[str]:
    """What a ``spawn`` runs inside the terminal: ``[]``, ``[program]`` or ``[program, file]``."""
    rest = list(argv[1:])
    return rest[rest.index("-e") + 1 :] if "-e" in rest else []


def programs(step: Step) -> list[str]:
    """Every program this step would start, by name. Used to check the session's PATH."""
    kind, payload = step.action.kind, step.action.payload
    if kind == "spawn":
        return [payload["argv"][0], *spawn_command(payload["argv"])[:1]]
    if kind == "herdr":
        argv = payload["argv"]
        if argv[:2] == ["pane", "run"] and len(argv) >= 4:
            return [argv[3]]
    return []


def _herdr_pane_run(rest: list[str], where: str, demo_bin: Path | None) -> None:
    """``pane run <pane id> <command>``: the command is a program in ``demo/bin``, by name.

    This is the one Herdr command that starts something, so it is the one that has to be
    pinned. A bare name means the recorder's own ``demo/bin`` (it is first on PATH) and nothing
    else can be reached: no path, no ``..``, and the file has to be there.
    """
    if len(rest) != 2:
        raise ScenarioError(f"{where}: expected <pane id> <command>, got {' '.join(rest)}")
    pane, command = rest
    if not PANE_ID.fullmatch(pane):
        raise ScenarioError(f"{where}: {pane!r} is not a pane id like w1:p1")
    _bare_program(command, where, demo_bin)


def _herdr_status(rest: list[str], where: str, _bin: Path | None) -> None:
    if rest not in ([], ["--json"]):
        raise ScenarioError(f"{where}: only --json is allowed, got {' '.join(rest)}")


HERDR_COMMANDS = {
    ("pane", "list"): _herdr_no_args,
    ("pane", "current"): _herdr_no_args,
    ("pane", "process-info"): _herdr_pane_selector,
    ("pane", "run"): _herdr_pane_run,
    ("pane", "split"): _herdr_pane_split,
    ("pane", "focus"): _herdr_pane_focus,
    ("pane", "close"): _herdr_one(PANE_ID, "pane"),
    ("tab", "create"): _herdr_focus_flags,
    ("tab", "list"): _herdr_no_args,
    ("tab", "focus"): _herdr_one(TAB_ID, "tab"),
    ("workspace", "create"): _herdr_focus_flags,
    ("workspace", "list"): _herdr_no_args,
    ("workspace", "focus"): _herdr_one(WORKSPACE_ID, "workspace"),
    ("status",): _herdr_status,
}
"""Every Herdr command a scenario may run, and what each may be given (DECISIONS 0032)."""

DEFAULT_TIMEOUT = 10.0
OVERLAY_STATES = ("visible", "hidden")


@dataclass(frozen=True)
class Output:
    width: int = 1280
    height: int = 720
    fps: int = 30


@dataclass(frozen=True)
class Fonts:
    ui: str = "Noto Sans CJK JP"
    mono: str = "Noto Sans Mono"


@dataclass(frozen=True)
class Window:
    """Where a spawned window goes. Fixed, so the picture is the same on the next run.

    ``title`` is both the name a ``spawn`` step refers to and the window title the compositor
    matches its rule on, which is how two terminals end up in two different places.
    """

    title: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Condition:
    """What has to be true before a step is recorded (or before it may start).

    Every field is optional and all of them are ANDed. They are read back through the paths the
    product already has -- ``wayhint context`` and the overlay's accessible tree -- so a
    condition never depends on pixels, fonts or theme.
    """

    toplevel: str | None = None  # regex, matched against the active window's app_id
    process_name: str | None = None  # the foreground process wayhint resolved
    active_sheet: str | None = None  # the sheet id it chose for that context
    overlay: str | None = None  # "visible" | "hidden"
    label: str | None = None  # a label on the overlay containing this text
    no_label: str | None = None  # ... and one that must not be there
    button: str | None = None  # a button by logical name (BUTTONS)
    hints: int | None = None  # how many hint rows are listed
    timeout: float = DEFAULT_TIMEOUT

    def describe(self) -> str:
        parts = [
            f"{name}={value!r}"
            for name, value in (
                ("toplevel", self.toplevel),
                ("process_name", self.process_name),
                ("active_sheet", self.active_sheet),
                ("overlay", self.overlay),
                ("label", self.label),
                ("no_label", self.no_label),
                ("button", self.button),
                ("hints", self.hints),
            )
            if value is not None
        ]
        return ", ".join(parts) or "nothing"


@dataclass(frozen=True)
class Action:
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Step:
    id: str
    action: Action
    wait_for: Condition
    hold: float
    caption: dict[str, str] = field(default_factory=dict)
    precondition: Condition | None = None

    def frames(self, fps: int) -> int:
        """How many frames this step contributes. Rounded once, here, and never re-derived."""
        return max(0, round(self.hold * fps))


@dataclass(frozen=True)
class Variant:
    """One cut of the showcase: a length, and the steps that make it up."""

    name: str
    target: float
    tolerance: float
    square: bool
    steps: tuple[Step, ...]

    def frames(self, fps: int) -> int:
        return sum(step.frames(fps) for step in self.steps)

    def seconds(self, fps: int) -> float:
        return self.frames(fps) / fps

    def off_target(self, fps: int) -> float:
        """How far outside ``target ± tolerance`` this is, in seconds. 0 when it fits."""
        return max(0.0, abs(self.seconds(fps) - self.target) - self.tolerance)

    def select(self, only: list[str] | None, start: str | None) -> Variant:
        """The steps ``--only`` / ``--from`` asked for, in scenario order."""
        ids = [step.id for step in self.steps]
        for wanted in [*(only or []), *([start] if start else [])]:
            if wanted not in ids:
                raise ScenarioError(
                    f"variant {self.name!r} has no step {wanted!r}; it has: {', '.join(ids)}"
                )
        steps = self.steps
        if start is not None:
            steps = steps[ids.index(start) :]
        if only:
            steps = tuple(step for step in steps if step.id in only)
        if not steps:
            raise ScenarioError(f"that selection leaves no steps in variant {self.name!r}")
        return Variant(self.name, self.target, self.tolerance, self.square, steps)


@dataclass(frozen=True)
class Scenario:
    output: Output
    fonts: Fonts
    windows: tuple[Window, ...]
    steps: dict[str, Step]
    variants: tuple[Variant, ...]

    def variant(self, name: str) -> Variant:
        for item in self.variants:
            if item.name == name:
                return item
        names = ", ".join(v.name for v in self.variants)
        raise ScenarioError(f"no variant {name!r}; the scenario has: {names}")

    def languages(self) -> list[str]:
        """Every language the captions are written in, most complete first."""
        return [
            lang
            for lang in LANGUAGES
            if all(not step.caption or lang in step.caption for step in self.steps.values())
        ]


def load(path: Path, demo_bin: Path | None = None) -> Scenario:
    """Read and check a scenario file. Raises :class:`ScenarioError` with the reason."""
    try:
        text = path.read_text()
    except OSError as e:
        raise ScenarioError(f"{path}: {e.strerror or e}") from e
    try:
        doc = YAML(typ="safe").load(text)
    except YAMLError as e:
        raise ScenarioError(f"{path}: {e}") from e
    if not isinstance(doc, dict):
        raise ScenarioError(f"{path}: the top level has to be a mapping")
    return parse(doc, demo_bin)


def parse(doc: dict, demo_bin: Path | None = None) -> Scenario:
    _unknown(doc, {"output", "fonts", "windows", "steps", "variants"}, "the scenario")
    output = _output(_mapping(doc.get("output"), "output"))
    fonts = _fonts(_mapping(doc.get("fonts"), "fonts"))
    windows = _windows(doc.get("windows"))
    raw = doc.get("steps")
    if not isinstance(raw, list) or not raw:
        raise ScenarioError("steps: expected a non-empty list")
    steps: dict[str, Step] = {}
    for index, item in enumerate(raw):
        step = _step(item, index, demo_bin)
        if step.id in steps:
            raise ScenarioError(f"step {step.id!r}: two steps with the same id")
        steps[step.id] = step
    placements = {window.title for window in windows}
    for step in steps.values():
        if step.action.kind not in ("spawn", "close"):
            continue
        where = step.action.payload["window"]
        if where not in placements:
            raise ScenarioError(
                f"step {step.id!r}: window {where!r} is not in windows "
                f"({', '.join(sorted(placements))})"
            )
    variants = _variants(doc.get("variants"), steps)
    unused = sorted(set(steps) - {s.id for v in variants for s in v.steps})
    if unused:
        raise ScenarioError(
            f"steps in no variant: {', '.join(unused)} (a step nobody records is dead weight)"
        )
    return Scenario(output, fonts, tuple(windows), steps, variants)


# --- pieces ------------------------------------------------------------------------------------


def _mapping(value: object, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ScenarioError(f"{where}: expected a mapping")
    return value


def _int(value: object, where: str, *, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ScenarioError(f"{where}: expected an integer of at least {minimum}")
    return value


def _number(value: object, where: str, *, minimum: float = 0.0) -> float:
    """A real number. ``nan`` and ``inf`` are refused: YAML writes them as ``.nan`` / ``.inf``,
    they pass every comparison quietly, and the first place they would surface is a frame
    count."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ScenarioError(f"{where}: expected a number of at least {minimum:g}")
    if not math.isfinite(value) or value < minimum:
        raise ScenarioError(f"{where}: expected a finite number of at least {minimum:g}")
    return float(value)


def _name(value: object, kind: str, where: str) -> str:
    """A step id or a variant name: safe to use as a file name (``names.validate_name``)."""
    try:
        return names.validate_name(kind, _string(value, where))
    except names.BadName as e:
        raise ScenarioError(f"{where}: {e}") from e


def _string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScenarioError(f"{where}: expected a non-empty string")
    return value


def _output(doc: dict) -> Output:
    _unknown(doc, {"width", "height", "fps"}, "output")
    base = Output()
    return Output(
        width=_int(doc.get("width", base.width), "output.width", minimum=16),
        height=_int(doc.get("height", base.height), "output.height", minimum=16),
        fps=_int(doc.get("fps", base.fps), "output.fps"),
    )


def _fonts(doc: dict) -> Fonts:
    _unknown(doc, {"ui", "mono"}, "fonts")
    base = Fonts()
    return Fonts(
        ui=_string(doc.get("ui", base.ui), "fonts.ui"),
        mono=_string(doc.get("mono", base.mono), "fonts.mono"),
    )


def _windows(value: object) -> list[Window]:
    if not isinstance(value, list) or not value:
        raise ScenarioError("windows: expected a non-empty list of placements")
    out, seen = [], set()
    for index, item in enumerate(value):
        doc = _mapping(item, f"windows[{index}]")
        where = f"windows[{index}]"
        _unknown(doc, {"title", "x", "y", "width", "height"}, where)
        title = _string(doc.get("title"), f"{where}.title")
        if title in seen:
            raise ScenarioError(f"windows: two placements called {title!r}")
        seen.add(title)
        out.append(
            Window(
                title=title,
                x=_int(doc.get("x", 40), f"{where}.x", minimum=0),
                y=_int(doc.get("y", 60), f"{where}.y", minimum=0),
                width=_int(doc.get("width", 760), f"{where}.width", minimum=16),
                height=_int(doc.get("height", 460), f"{where}.height", minimum=16),
            )
        )
    return out


def _variants(value: object, steps: dict[str, Step]) -> tuple[Variant, ...]:
    doc = _mapping(value, "variants")
    if not doc:
        raise ScenarioError("variants: expected at least one variant")
    out = []
    for name, raw in doc.items():
        where = f"variants.{name}"
        _name(name, "variant name", where)
        item = _mapping(raw, where)
        _unknown(item, {"target", "tolerance", "square", "steps"}, where)
        ids = item.get("steps")
        if not isinstance(ids, list) or not ids:
            raise ScenarioError(f"{where}.steps: expected a non-empty list of step ids")
        chosen = []
        for step_id in ids:
            if not isinstance(step_id, str) or step_id not in steps:
                raise ScenarioError(
                    f"{where}.steps: no step {step_id!r} is defined (defined: {', '.join(steps)})"
                )
            chosen.append(steps[step_id])
        if len({s.id for s in chosen}) != len(chosen):
            raise ScenarioError(f"{where}.steps: the same step id appears twice")
        out.append(
            Variant(
                name=str(name),
                target=_number(item.get("target"), f"{where}.target", minimum=1),
                tolerance=_number(item.get("tolerance", 0), f"{where}.tolerance"),
                square=bool(item.get("square", False)),
                steps=tuple(chosen),
            )
        )
    return tuple(out)


def _step(doc: object, index: int, demo_bin: Path | None) -> Step:
    if not isinstance(doc, dict):
        raise ScenarioError(f"steps[{index}]: expected a mapping")
    known = {"id", "wait_for", "caption", "hold", "precondition", *ACTIONS}
    step_id = _name(doc.get("id"), "step id", f"steps[{index}].id")
    where = f"step {step_id!r}"
    _unknown(doc, known, where)
    present = [name for name in ACTIONS if name in doc]
    if len(present) != 1:
        raise ScenarioError(
            f"{where}: expected exactly one action out of {', '.join(ACTIONS)}, got "
            + (", ".join(present) or "none")
        )
    if "wait_for" not in doc:
        raise ScenarioError(f"{where}: wait_for is required (what says the step has happened?)")
    hold = doc.get("hold", 0)
    if not isinstance(hold, int | float) or isinstance(hold, bool) or hold < 0:
        raise ScenarioError(f"{where}: hold has to be a number of seconds, and not negative")
    if not math.isfinite(hold):
        raise ScenarioError(f"{where}: hold has to be a finite number of seconds")
    return Step(
        id=step_id,
        action=_action(present[0], doc[present[0]], where, demo_bin),
        wait_for=_condition(doc["wait_for"], f"{where}.wait_for"),
        hold=float(hold),
        caption=_caption(doc.get("caption"), where),
        precondition=(
            _condition(doc["precondition"], f"{where}.precondition")
            if "precondition" in doc
            else None
        ),
    )


def _action(kind: str, value: object, where: str, demo_bin: Path | None) -> Action:
    if kind == "spawn":
        doc = _mapping(value, f"{where}.spawn")
        _unknown(doc, {"argv", "window"}, f"{where}.spawn")
        argv = doc.get("argv")
        if not isinstance(argv, list) or not argv:
            raise ScenarioError(f"{where}.spawn.argv: expected a non-empty list")
        parts = [_string(a, f"{where}.spawn.argv[]") for a in argv]
        return Action(
            "spawn",
            {
                "window": _string(doc.get("window"), f"{where}.spawn.window"),
                "argv": _spawn_argv(parts, f"{where}.spawn.argv", demo_bin),
            },
        )
    if kind == "close":
        doc = _mapping(value, f"{where}.close")
        _unknown(doc, {"window"}, f"{where}.close")
        return Action("close", {"window": _string(doc.get("window"), f"{where}.close.window")})
    if kind == "key":
        return Action("key", {"keys": _keys(_string(value, f"{where}.key"), where)})
    if kind == "type":
        return Action("type", {"text": _per_language(value, f"{where}.type")})
    if kind == "press":
        doc = _mapping(value, f"{where}.press")
        _unknown(doc, {"button"}, f"{where}.press")
        return Action("press", {"button": _button(doc.get("button"), f"{where}.press.button")})
    if kind == "cli":
        command = _string(value, f"{where}.cli")
        if command not in CLI_COMMANDS:
            raise ScenarioError(f"{where}.cli: {command!r} is not one of {', '.join(CLI_COMMANDS)}")
        return Action("cli", {"command": command})
    if kind == "herdr":
        return Action("herdr", {"argv": _herdr(value, f"{where}.herdr", demo_bin)})
    if kind == "pause":
        if value is not True:
            raise ScenarioError(f"{where}.pause: write `pause: true` (it does nothing on purpose)")
        return Action("pause", {})
    doc = _mapping(value, f"{where}.write")
    _unknown(doc, {"file", "text", "source"}, f"{where}.write")
    target = _relative(_string(doc.get("file"), f"{where}.write.file"), f"{where}.write.file")
    if ("text" in doc) == ("source" in doc):
        raise ScenarioError(f"{where}.write: give either text or source, not both")
    if "source" in doc:
        source = _relative(_string(doc["source"], f"{where}.write.source"), f"{where}.write.source")
        return Action("write", {"file": target, "source": source})
    if not isinstance(doc["text"], str):
        raise ScenarioError(f"{where}.write.text: expected a string")
    return Action("write", {"file": target, "text": doc["text"]})


def _herdr(value: object, where: str, demo_bin: Path | None) -> list[str]:
    """One Herdr command, as argv, checked against the allow-list (DECISIONS 0032)."""
    if not isinstance(value, list) or not value:
        raise ScenarioError(f"{where}: expected a non-empty argv list, e.g. [tab, focus, w1:t1]")
    argv = [_string(part, f"{where}[]") for part in value]
    head2, head1 = tuple(argv[:2]), tuple(argv[:1])
    if head2 in RUNNER_ONLY_HERDR:
        raise ScenarioError(
            f"{where}: {' '.join(head2)} is the recorder's own (it tears the session down)"
        )
    for head in (head2, head1):
        check = HERDR_COMMANDS.get(head)
        if check is not None:
            check(argv[len(head) :], f"{where} ({' '.join(head)})", demo_bin)
            return argv
    allowed = ", ".join(sorted(" ".join(k) for k in HERDR_COMMANDS))
    raise ScenarioError(f"{where}: {' '.join(argv[:2])!r} is not allowed. Allowed: {allowed}")


def _relative(value: str, where: str) -> str:
    """A path inside the working copy of the fixtures, and nowhere else.

    ``{lang}`` is substituted when the step runs, so the same scenario writes to ``hints/ja/``
    and ``hints/en/``; the check below is repeated on the result.
    """
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ScenarioError(f"{where}: has to be a relative path without '..'")
    return value


def _button(value: object, where: str) -> str:
    name = _string(value, where)
    if name not in BUTTONS:
        raise ScenarioError(f"{where}: {name!r} is not one of {', '.join(sorted(BUTTONS))}")
    return name


def _keys(value: str, where: str) -> list[str]:
    """``super+ctrl+h`` -> the modifier names and keysym wtype takes, checked here."""
    parts = [part.strip().lower() for part in value.split("+") if part.strip()]
    if not parts:
        raise ScenarioError(f"{where}.key: expected something like 'super+h'")
    *mods, key = parts
    for mod in mods:
        if mod not in MODIFIERS:
            raise ScenarioError(
                f"{where}.key: {mod!r} is not a modifier ({', '.join(sorted(MODIFIERS))})"
            )
    if key in KEY_NAMES:
        keysym = KEY_NAMES[key]
    else:
        original = value.split("+")[-1].strip()
        if not KEYSYM.fullmatch(original):
            raise ScenarioError(f"{where}.key: {original!r} is not a key name")
        keysym = original
    return [*(MODIFIERS[mod] for mod in mods), keysym]


def _per_language(value: object, where: str) -> dict[str, str]:
    """A string, or one per language. Typed text is content: the ja demo types Japanese."""
    if isinstance(value, str):
        if not value:
            raise ScenarioError(f"{where}: expected a non-empty string")
        return dict.fromkeys(LANGUAGES, value)
    doc = _mapping(value, where)
    _unknown(doc, set(LANGUAGES), where)
    if REQUIRED_LANGUAGE not in doc:
        raise ScenarioError(f"{where}: {REQUIRED_LANGUAGE} is required")
    return {lang: _string(doc[lang], f"{where}.{lang}") for lang in LANGUAGES if lang in doc}


def _caption(value: object, where: str) -> dict[str, str]:
    if value is None:
        return {}
    return _per_language(value, f"{where}.caption")


def _condition(value: object, where: str) -> Condition:
    doc = _mapping(value, where)
    known = {
        "toplevel",
        "process_name",
        "active_sheet",
        "overlay",
        "label",
        "no_label",
        "button",
        "hints",
        "timeout",
        "context",
    }
    _unknown(doc, known, where)
    doc = dict(doc)
    for key, sub in _mapping(doc.pop("context", None), f"{where}.context").items():
        if key not in ("process_name", "active_sheet"):
            raise ScenarioError(f"{where}.context.{key}: expected process_name or active_sheet")
        doc[key] = sub
    if not doc:
        raise ScenarioError(f"{where}: expected at least one condition")
    overlay = doc.get("overlay")
    if overlay is not None and overlay not in OVERLAY_STATES:
        raise ScenarioError(f"{where}.overlay: expected {' or '.join(OVERLAY_STATES)}")
    if "toplevel" in doc:
        pattern = _string(doc["toplevel"], f"{where}.toplevel")
        try:
            re.compile(pattern)
        except re.error as e:
            raise ScenarioError(f"{where}.toplevel: {e}") from e
    if "button" in doc:
        doc["button"] = _button(doc["button"], f"{where}.button")
    if "hints" in doc:
        doc["hints"] = _int(doc["hints"], f"{where}.hints", minimum=0)
    timeout = doc.get("timeout", DEFAULT_TIMEOUT)
    if not isinstance(timeout, int | float) or isinstance(timeout, bool) or timeout <= 0:
        raise ScenarioError(f"{where}.timeout: expected a positive number of seconds")
    if not math.isfinite(timeout):
        raise ScenarioError(f"{where}.timeout: expected a finite number of seconds")
    doc["timeout"] = float(timeout)
    for key in ("process_name", "active_sheet", "label", "no_label"):
        if key in doc:
            doc[key] = _string(doc[key], f"{where}.{key}")
    return Condition(**doc)


def _unknown(doc: dict, known: set[str], where: str) -> None:
    extra = sorted(set(doc) - known)
    if extra:
        raise ScenarioError(f"{where}: unknown key(s) {', '.join(extra)}")
