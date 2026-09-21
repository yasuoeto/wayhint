"""The script of the demo: what happens, in what order, and for how long.

A scenario is data. Nothing in it is ever executed as a command -- the only substitution is
``{demo_bin}``, and the actions it can ask for are a fixed set with fixed argv (DECISIONS 0031).
Reading it does not need a compositor, so ``--validate`` and ``--dry-run`` work anywhere.

The length of the recording is decided here, in frames, and not by how fast the machine runs:
``hold`` is seconds in the file, rounded to frames on the way in, and the recorder repeats one
captured frame that many times.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

LANGUAGES = ("en", "ja")
ACTIONS = ("spawn", "key", "type", "press", "cli", "write")

# What ``press: {button: ...}`` and ``wait_for: {button: ...}`` may name, and the English label
# the widget carries. The label itself is looked up per language through ``wayhint.i18n``, so a
# scenario never spells out "検索" and the ja recording presses the same button as the en one.
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

DEFAULT_TIMEOUT = 10.0
OVERLAY_STATES = ("visible", "hidden")


class ScenarioError(Exception):
    """A scenario that cannot be recorded. The message says which step and what is wrong."""


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
class Scenario:
    output: Output
    fonts: Fonts
    windows: tuple[Window, ...]
    steps: tuple[Step, ...]

    def frames(self) -> int:
        return sum(step.frames(self.output.fps) for step in self.steps)

    def seconds(self) -> float:
        return self.frames() / self.output.fps

    def select(self, only: list[str] | None, start: str | None) -> Scenario:
        """The steps ``--only`` / ``--from`` asked for, in scenario order."""
        ids = [step.id for step in self.steps]
        for wanted in [*(only or []), *([start] if start else [])]:
            if wanted not in ids:
                raise ScenarioError(f"no step {wanted!r}; the scenario has: {', '.join(ids)}")
        steps = self.steps
        if start is not None:
            steps = steps[ids.index(start) :]
        if only:
            steps = tuple(step for step in steps if step.id in only)
        if not steps:
            raise ScenarioError("that selection leaves no steps to record")
        return Scenario(self.output, self.fonts, self.windows, steps)


def load(path: Path) -> Scenario:
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
    return parse(doc)


def parse(doc: dict) -> Scenario:
    _unknown(doc, {"output", "fonts", "windows", "steps"}, "the scenario")
    output = _output(_mapping(doc.get("output"), "output"))
    fonts = _fonts(_mapping(doc.get("fonts"), "fonts"))
    windows = _windows(doc.get("windows"))
    raw = doc.get("steps")
    if not isinstance(raw, list) or not raw:
        raise ScenarioError("steps: expected a non-empty list")
    steps, seen = [], set()
    for index, item in enumerate(raw):
        step = _step(item, index)
        if step.id in seen:
            raise ScenarioError(f"step {step.id!r}: two steps with the same id")
        seen.add(step.id)
        steps.append(step)
    placements = {window.title for window in windows}
    for step in steps:
        if step.action.kind != "spawn":
            continue
        where = step.action.payload["window"]
        if where not in placements:
            raise ScenarioError(
                f"step {step.id!r}: window {where!r} is not in windows "
                f"({', '.join(sorted(placements))})"
            )
    return Scenario(output, fonts, tuple(windows), tuple(steps))


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


def _step(doc: object, index: int) -> Step:
    if not isinstance(doc, dict):
        raise ScenarioError(f"steps[{index}]: expected a mapping")
    known = {"id", "wait_for", "caption", "hold", "precondition", *ACTIONS}
    step_id = _string(doc.get("id"), f"steps[{index}].id")
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
    return Step(
        id=step_id,
        action=_action(present[0], doc[present[0]], where),
        wait_for=_condition(doc["wait_for"], f"{where}.wait_for"),
        hold=float(hold),
        caption=_caption(doc.get("caption"), where),
        precondition=(
            _condition(doc["precondition"], f"{where}.precondition")
            if "precondition" in doc
            else None
        ),
    )


def _action(kind: str, value: object, where: str) -> Action:
    if kind == "spawn":
        doc = _mapping(value, f"{where}.spawn")
        _unknown(doc, {"argv", "window"}, f"{where}.spawn")
        argv = doc.get("argv")
        if not isinstance(argv, list) or not argv:
            raise ScenarioError(f"{where}.spawn.argv: expected a non-empty list")
        return Action(
            "spawn",
            {
                "window": _string(doc.get("window"), f"{where}.spawn.window"),
                "argv": [_string(a, f"{where}.spawn.argv[]") for a in argv],
            },
        )
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


def _relative(value: str, where: str) -> str:
    """A path inside the working copy of the fixtures, and nowhere else.

    ``{lang}`` is substituted when the step runs, so the same scenario writes to
    ``hints/en/`` and ``hints/ja/``; the check below is repeated on the result.
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
        if not KEYSYM.match(original):
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
    for lang in LANGUAGES:
        if lang not in doc:
            raise ScenarioError(f"{where}: {lang} is missing (write every language)")
    return {lang: _string(doc[lang], f"{where}.{lang}") for lang in LANGUAGES}


def _caption(value: object, where: str) -> dict[str, str]:
    if value is None:
        return {}
    doc = _mapping(value, f"{where}.caption")
    _unknown(doc, set(LANGUAGES), f"{where}.caption")
    if not doc:
        return {}
    for lang in LANGUAGES:
        if lang not in doc:
            raise ScenarioError(f"{where}.caption: {lang} is missing (write every language)")
    return {lang: _string(doc[lang], f"{where}.caption.{lang}") for lang in LANGUAGES}


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
    doc["timeout"] = float(timeout)
    for key in ("process_name", "active_sheet", "label", "no_label"):
        if key in doc:
            doc[key] = _string(doc[key], f"{where}.{key}")
    return Condition(**doc)


def _unknown(doc: dict, known: set[str], where: str) -> None:
    extra = sorted(set(doc) - known)
    if extra:
        raise ScenarioError(f"{where}: unknown key(s) {', '.join(extra)}")
