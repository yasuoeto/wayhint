"""Global configuration (``~/.config/wayhint/config.yaml``).

Only parsing and validation live here; reading files is done by :mod:`wayhint.yaml_store` so
that the same loader (and line numbers) serve both config and hint sheets.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from wayhint.i18n import LANGUAGES
from wayhint.models import ANCHORS, EDITOR_PLACEHOLDERS, DisplayConfig, Margin, Size

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
LOG_LEVELS = ("debug", "info", "warning", "error")
CONTEXT_BACKENDS = ("auto", "wayland", "wayfire")
WORKSPACE_SCOPES = ("current", "all")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "wayhint"


@dataclass(frozen=True)
class EditorConfig:
    command: tuple[str, ...] = ("gvim", "--remote-silent", "+{line}", "{file}")
    schema_modeline: bool = False
    schema_path: Path = field(default_factory=lambda: config_dir() / "schema.json")

    def argv(self, file: Path, line: int, hint_id: str) -> list[str]:
        """Expand placeholders. Pure string substitution; never goes through a shell."""
        values = {"file": str(file), "line": str(line), "hint_id": hint_id}
        return [_PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], part) for part in self.command]


@dataclass(frozen=True)
class GlobalConfig:
    display: DisplayConfig = field(
        default_factory=lambda: DisplayConfig(
            anchor="top-right",
            width=Size(420, "px"),
            height=Size(60, "%"),
            margin=Margin(top=24, right=24),
            output=None,
        )
    )
    style: str = "style.css"
    language: str = "auto"  # auto (locale) | en | ja
    show_category: bool = True
    editor: EditorConfig = field(default_factory=EditorConfig)
    parent_tags: tuple[str, ...] = ()
    live_update: bool = False
    context_backend: str = "auto"  # auto | wayland | wayfire
    workspace_scope: str = "current"  # current = 呼び出した workspace だけ | all
    max_results: int = 50
    log_level: str = "warning"


class ConfigError(ValueError):
    """A validation problem at a known YAML path (``key``), e.g. ``overlay.anchor``."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(f"{key}: {message}")
        self.key = key
        self.message = message


def _mapping(node: object, key: str) -> Mapping:
    if node is None:
        return {}
    if not isinstance(node, Mapping):
        raise ConfigError(key, "must be a mapping")
    return node


def _str_list(node: object, key: str) -> tuple[str, ...]:
    if node is None:
        return ()
    if isinstance(node, str) or not isinstance(node, (list, tuple)):
        raise ConfigError(key, "must be a list of strings")
    out = []
    for i, item in enumerate(node):
        if not isinstance(item, str) or not item:
            raise ConfigError(f"{key}[{i}]", "must be a non-empty string")
        out.append(item)
    return tuple(out)


def _bool(node: object, key: str, default: bool) -> bool:
    if node is None:
        return default
    if not isinstance(node, bool):
        raise ConfigError(key, "must be true or false")
    return node


def _int(node: object, key: str, default: int, minimum: int | None = None) -> int:
    if node is None:
        return default
    if isinstance(node, bool) or not isinstance(node, int):
        raise ConfigError(key, "must be an integer")
    if minimum is not None and node < minimum:
        raise ConfigError(key, f"must be >= {minimum}")
    return node


def parse_anchor(node: object, key: str) -> str | None:
    if node is None:
        return None
    if not isinstance(node, str) or node not in ANCHORS:
        raise ConfigError(key, f"invalid anchor {node!r}; expected one of {', '.join(ANCHORS)}")
    return node


def parse_size(node: object, key: str) -> Size | None:
    if node is None:
        return None
    try:
        return Size.parse(node)
    except ValueError as e:
        raise ConfigError(key, str(e)) from None


def parse_margin(node: object, key: str) -> Margin | None:
    """``margin: 24`` (all sides) or ``margin: {top: 24, right: 8}``."""
    if node is None:
        return None
    if isinstance(node, bool):
        raise ConfigError(key, "must be an integer or a mapping of sides")
    if isinstance(node, int):
        if node < 0:
            raise ConfigError(key, "must be >= 0")
        return Margin(node, node, node, node)
    m = _mapping(node, key)
    sides = {}
    for side in ("top", "right", "bottom", "left"):
        sides[side] = _int(m.get(side), f"{key}.{side}", 0, minimum=0)
    unknown = set(m) - set(sides)
    if unknown:
        raise ConfigError(key, f"unknown side(s): {', '.join(sorted(map(str, unknown)))}")
    return Margin(**sides)


def parse_display(node: object, key: str) -> DisplayConfig:
    m = _mapping(node, key)
    output = m.get("output")
    if output is not None and (not isinstance(output, str) or not output):
        raise ConfigError(f"{key}.output", "must be a non-empty string")
    return DisplayConfig(
        anchor=parse_anchor(m.get("anchor"), f"{key}.anchor"),
        width=parse_size(m.get("width"), f"{key}.width"),
        height=parse_size(m.get("height"), f"{key}.height"),
        margin=parse_margin(m.get("margin"), f"{key}.margin"),
        output=output,
    )


def parse_editor_command(node: object, key: str) -> tuple[str, ...]:
    argv = _str_list(node, key)
    if not argv:
        raise ConfigError(key, "must be a non-empty argv list")
    for i, part in enumerate(argv):
        for name in _PLACEHOLDER_RE.findall(part):
            if name not in EDITOR_PLACEHOLDERS:
                allowed = ", ".join(f"{{{p}}}" for p in EDITOR_PLACEHOLDERS)
                raise ConfigError(
                    f"{key}[{i}]", f"unknown placeholder {{{name}}}; allowed: {allowed}"
                )
    if not any("{file}" in part for part in argv):
        raise ConfigError(key, "must contain the {file} placeholder")
    return argv


def parse_global_config(data: object) -> GlobalConfig:
    """Build a :class:`GlobalConfig` from a parsed YAML document. Raise :class:`ConfigError`."""
    root = _mapping(data, "config")
    defaults = GlobalConfig()
    known = {"overlay", "appearance", "editor", "nested", "context", "search", "logging"}
    unknown = set(map(str, root)) - known
    if unknown:
        raise ConfigError("config", f"unknown section(s): {', '.join(sorted(unknown))}")

    display = parse_display(root.get("overlay"), "overlay").merged_over(defaults.display)

    appearance = _mapping(root.get("appearance"), "appearance")
    style = appearance.get("style", defaults.style)
    if not isinstance(style, str) or not style:
        raise ConfigError("appearance.style", "must be a non-empty string")
    language = appearance.get("language", defaults.language)
    if not isinstance(language, str) or language not in LANGUAGES:
        raise ConfigError("appearance.language", f"must be one of {', '.join(LANGUAGES)}")

    editor_node = _mapping(root.get("editor"), "editor")
    if "command" in editor_node:
        editor = EditorConfig(parse_editor_command(editor_node["command"], "editor.command"))
    else:
        editor = defaults.editor

    nested = _mapping(root.get("nested"), "nested")
    context = _mapping(root.get("context"), "context")
    search = _mapping(root.get("search"), "search")
    backend = context.get("backend", defaults.context_backend)
    if not isinstance(backend, str) or backend not in CONTEXT_BACKENDS:
        raise ConfigError("context.backend", f"must be one of {', '.join(CONTEXT_BACKENDS)}")
    scope = context.get("workspace", defaults.workspace_scope)
    if not isinstance(scope, str) or scope not in WORKSPACE_SCOPES:
        raise ConfigError("context.workspace", f"must be one of {', '.join(WORKSPACE_SCOPES)}")
    logging_node = _mapping(root.get("logging"), "logging")
    level = logging_node.get("level", defaults.log_level)
    if not isinstance(level, str) or level.lower() not in LOG_LEVELS:
        raise ConfigError("logging.level", f"must be one of {', '.join(LOG_LEVELS)}")

    return GlobalConfig(
        display=display,
        style=style,
        language=language,
        show_category=_bool(appearance.get("show_category"), "appearance.show_category", True),
        editor=editor,
        parent_tags=_str_list(nested.get("parent_tags"), "nested.parent_tags"),
        live_update=_bool(context.get("live_update"), "context.live_update", False),
        context_backend=backend,
        workspace_scope=scope,
        max_results=_int(search.get("max_results"), "search.max_results", 50, minimum=1),
        log_level=level.lower(),
    )
