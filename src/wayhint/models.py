"""Pure data types shared by every layer. No GTK, Wayfire or Herdr imports here."""

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
        """Text placed on the clipboard: ``copy`` → ``command`` → ``key``."""
        return self.copy or self.command or self.key


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
class HintSheet:
    id: str
    title: str
    path: Path
    version: int = 1
    priority: int = 0
    match: MatchRule = field(default_factory=MatchRule)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    parent_tags: tuple[str, ...] | None = None  # None → use global nested.parent_tags
    hints: tuple[Hint, ...] = ()


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    argv: tuple[str, ...]
    cmdline: str
    cwd: str | None = None


@dataclass(frozen=True)
class ResolvedContext:
    desktop_app: str | None = None
    desktop_title: str | None = None
    output: str | None = None
    parent_context: str | None = None
    foreground_process: ProcessInfo | None = None
    active_sheet: str | None = None
