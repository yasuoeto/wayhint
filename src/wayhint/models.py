"""Pure data types shared by every layer. No GTK, Wayland or Herdr imports here."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HINT_KINDS = ("shortcut", "command", "tip", "note")

ANCHORS = (
    "top-left",
    "top",
    "top-right",
    "left",
    "center",
    "right",
    "bottom-left",
    "bottom",
    "bottom-right",
)

EDITOR_PLACEHOLDERS = ("file", "line", "hint_id")

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(px|%)?\s*$")

CONTROL_SHOWN = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def visible(text: str) -> str:
    """``text`` with every character that would not show on screen written out as an escape.

    For text that came from somewhere else -- a sheet, an app_id, a process name -- and is put
    where an invisible character changes what it means: the detail pane, a YAML comment.
    """
    return "".join(c if c.isprintable() else CONTROL_SHOWN.get(c, f"\\x{ord(c):02x}") for c in text)


@dataclass(frozen=True)
class Size:
    """A length in px or as a percentage of the output's logical size."""

    value: float
    unit: str  # "px" | "%"

    @classmethod
    def parse(cls, raw: object) -> Size:
        """Accept ``420``, ``"420px"``, ``"30%"``. Raise ValueError otherwise."""
        if isinstance(raw, bool):
            raise ValueError(f"invalid size: {raw!r}")
        if isinstance(raw, (int, float)):
            if raw < 0:
                raise ValueError(f"invalid size: {raw!r}")
            return cls(float(raw), "px")
        if isinstance(raw, str):
            m = _SIZE_RE.match(raw)
            if m:
                value = float(m.group(1))
                unit = m.group(2) or "px"
                if unit == "%" and value > 100:
                    raise ValueError(f"invalid size: {raw!r} (percentage above 100)")
                return cls(value, unit)
        raise ValueError(f"invalid size: {raw!r}")

    def to_px(self, reference: int) -> int:
        """Resolve against ``reference`` (logical output width or height)."""
        if self.unit == "%":
            return round(reference * self.value / 100)
        return round(self.value)


@dataclass(frozen=True)
class Margin:
    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0


@dataclass(frozen=True)
class SourceLocation:
    file: Path
    line: int  # 1-based


@dataclass(frozen=True)
class Hint:
    id: str
    title: str
    location: SourceLocation
    kind: str = "shortcut"
    key: str | None = None
    command: str | None = None
    category: str | None = None
    tags: tuple[str, ...] = ()
    favorite: bool = False
    copy: str | None = None
    remark: str | None = None
    source: str | None = None
    learned: str | None = None

    def copy_text(self) -> str | None:
        """Text placed on the clipboard: ``copy``, else ``command`` (DECISIONS 0039).

        Not ``key``: a key is pressed, not pasted, so copying it only ever put the wrong thing
        on the clipboard.
        """
        return self.copy or self.command


@dataclass(frozen=True)
class MatchRule:
    app_id_regex: tuple[str, ...] = ()
    argv_regex: tuple[str, ...] = ()
    cmdline_regex: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not (self.app_id_regex or self.argv_regex or self.cmdline_regex)


@dataclass(frozen=True)
class DisplayConfig:
    """Overlay placement. ``None`` means "inherit from the global config"."""

    anchor: str | None = None
    width: Size | None = None
    height: Size | None = None
    margin: Margin | None = None
    output: str | None = None

    def merged_over(self, base: DisplayConfig) -> DisplayConfig:
        return DisplayConfig(
            anchor=self.anchor if self.anchor is not None else base.anchor,
            width=self.width if self.width is not None else base.width,
            height=self.height if self.height is not None else base.height,
            margin=self.margin if self.margin is not None else base.margin,
            output=self.output if self.output is not None else base.output,
        )


@dataclass(frozen=True)
class HintFilter:
    """Which of a mixed-in sheet's hints are let through (DECISIONS 0039).

    ``tags`` and ``categories`` are each ``None`` when not written. What is written is ORed: a
    hint passes when it carries one of the tags *or* its category is one of the categories (a
    hint without a category matches no category). ``[]`` written for either lets nothing through
    whatever the other says -- ``nested.parent_tags: []`` is how parent hints are switched off
    everywhere (0036), and a category filter must not reopen that.
    """

    tags: tuple[str, ...] | None = None
    categories: tuple[str, ...] | None = None

    def is_everything(self) -> bool:
        return self.tags is None and self.categories is None

    def allows(self, hint: Hint) -> bool:
        if self.tags == () or self.categories == ():
            return False
        if self.is_everything():
            return True
        by_tag = self.tags is not None and not set(self.tags).isdisjoint(hint.tags)
        return by_tag or (self.categories is not None and hint.category in self.categories)


@dataclass(frozen=True)
class IncludeRef:
    """One entry of ``include``: a sheet id and what to take from it (0026, 0039)."""

    sheet: str
    filter: HintFilter = field(default_factory=HintFilter)


@dataclass(frozen=True)
class HintSheet:
    id: str
    title: str
    path: Path
    version: int = 1
    priority: int = 0
    match: MatchRule = field(default_factory=MatchRule)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    parent_tags: tuple[str, ...] | None = None  # None → use global nested.parent_tags
    parent_categories: tuple[str, ...] | None = None  # None → global nested.parent_categories
    # What this sheet hands down as a nested parent (nested.export_*); None → everything
    export_tags: tuple[str, ...] | None = None
    export_categories: tuple[str, ...] | None = None
    include: tuple[IncludeRef, ...] | None = None  # sheets mixed in; None → use global include
    hints: tuple[Hint, ...] = ()


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    argv: tuple[str, ...]
    cmdline: str
    cwd: str | None = None


@dataclass(frozen=True)
class OutputInfo:
    name: str
    width: int  # logical size
    height: int


@dataclass(frozen=True)
class ResolvedContext:
    """Snapshot taken on show/refresh. The UI receives this and the sheets, nothing else."""

    desktop_app: str | None = None
    desktop_title: str | None = None
    output: OutputInfo | None = None
    view_ref: str | None = None  # opaque toplevel reference to hand focus back to after search
    parent_context: str | None = None  # parent sheet id when a nested context applies
    foreground_process: ProcessInfo | None = None
    active_sheet: str | None = None
    error: str | None = None  # e.g. desktop context unavailable; shown in the overlay
    chain: tuple[str, ...] = ()  # nested providers consulted, in order; for `wayhint context`

    def target_key(self) -> tuple:
        """What the overlay ends up showing, for deciding whether a new context replaces it.

        Deliberately excludes ``desktop_title`` and ``view_ref``: both carry the window title,
        which many applications rewrite as they work (a terminal follows the running command), so
        comparing them would report a different window every few seconds. The sheet, the parent
        sheet, the application and the foreground process are what the overlay actually shows.
        """
        process = self.foreground_process.name if self.foreground_process else None
        return (self.active_sheet, self.parent_context, self.desktop_app, process)
