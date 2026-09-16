"""Load hint sheets and the global config from YAML, keeping source line numbers.

ruamel.yaml's round-trip loader is the only YAML entry point in the project. It is a *safe*
loader: no arbitrary object construction. Nothing read here is ever executed.

Two levels of API:

- :func:`load_config` / :func:`load_sheet` / :func:`load_sheets`: one-shot parse + validate,
  returning a :class:`LoadResult` whose ``issues`` list is empty on success.
- :class:`SheetStore`: keeps the last-known-good sheet per file so a broken edit does not take
  hints away from the overlay (Failure modes, ``docs/DESIGN.md``).
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError

from wayhint.config import ConfigError, GlobalConfig, parse_display, parse_global_config
from wayhint.models import HINT_KINDS, Hint, HintSheet, MatchRule, SourceLocation

SHEET_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHEET_KEYS = {"version", "id", "title", "priority", "match", "display", "inherit", "hints"}
_HINT_KEYS = {
    "id",
    "title",
    "kind",
    "key",
    "command",
    "category",
    "tags",
    "favorite",
    "copy",
    "remark",
    "source",
    "learned",
}


@dataclass(frozen=True)
class Issue:
    file: Path
    line: int | None
    message: str

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else str(self.file)
        return f"{where}: {self.message}"


@dataclass
class LoadResult:
    sheets: list[HintSheet] = field(default_factory=list)
    config: GlobalConfig | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


class _Ctx:
    """Collects issues for one file and knows how to find line numbers in ruamel nodes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.issues: list[Issue] = []

    def line_of(self, node: object, key: object | None = None) -> int | None:
        lc = getattr(node, "lc", None)
        if lc is None:
            return None
        try:
            if key is not None:
                if isinstance(node, Mapping):
                    return lc.key(key)[0] + 1
                return lc.item(key)[0] + 1
            return lc.line + 1
        except (KeyError, IndexError, AttributeError, TypeError):
            return None

    def error(self, message: str, node: object = None, key: object | None = None) -> None:
        self.issues.append(Issue(self.path, self.line_of(node, key), message))


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    return y


def read_document(path: Path) -> tuple[object, list[Issue]]:
    """Parse one YAML file. Returns ``(data, issues)``; ``data`` is ``None`` on error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, [Issue(path, None, f"cannot read: {e.strerror or e}")]
    try:
        return _yaml().load(text), []
    except MarkedYAMLError as e:
        mark = e.problem_mark
        line = mark.line + 1 if mark is not None else None
        problem = (e.problem or e.context or "YAML error").strip()
        return None, [Issue(path, line, f"YAML syntax error: {problem}")]
    except YAMLError as e:
        return None, [Issue(path, None, f"YAML error: {e}")]


# --- global config -----------------------------------------------------------------------------


def load_config(path: Path) -> LoadResult:
    """Missing file → defaults; present file → parsed and validated."""
    result = LoadResult()
    if not path.exists():
        result.config = GlobalConfig()
        return result
    data, issues = read_document(path)
    if issues:
        result.issues = issues
        return result
    try:
        result.config = parse_global_config(data)
    except ConfigError as e:
        result.issues.append(Issue(path, _line_for_key_path(data, e.key), str(e)))
    return result


def _line_for_key_path(data: object, key_path: str) -> int | None:
    """Best-effort: walk ``a.b[2].c`` through ruamel nodes to find a line number."""
    node = data
    line = None
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", key_path):
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(node, Sequence) or isinstance(node, str) or idx >= len(node):
                break
            line = _Ctx(Path()).line_of(node, idx) or line
            node = node[idx]
        else:
            if not isinstance(node, Mapping) or part not in node:
                break
            line = _Ctx(Path()).line_of(node, part) or line
            node = node[part]
    return line


# --- hint sheets -------------------------------------------------------------------------------


def _regex_list(ctx: _Ctx, parent: Mapping, key: str, path: str) -> tuple[str, ...]:
    node = parent.get(key)
    if node is None:
        return ()
    if isinstance(node, str) or not isinstance(node, Sequence):
        ctx.error(f"{path} must be a list of regex strings", parent, key)
        return ()
    out = []
    for i, item in enumerate(node):
        if not isinstance(item, str):
            ctx.error(f"{path}[{i}] must be a string", node, i)
            continue
        try:
            re.compile(item)
        except re.error as e:
            ctx.error(f"{path}[{i}] invalid regex {item!r}: {e}", node, i)
            continue
        out.append(item)
    return tuple(out)


def _match_rule(ctx: _Ctx, root: Mapping) -> MatchRule:
    node = root.get("match")
    if node is None:
        return MatchRule()
    if not isinstance(node, Mapping):
        ctx.error("match must be a mapping", root, "match")
        return MatchRule()
    unknown = set(map(str, node)) - {"wayland", "wayfire", "process"}
    if unknown:
        ctx.error(f"match: unknown key(s): {', '.join(sorted(unknown))}", root, "match")
    desktop_key = "wayland" if "wayland" in node else "wayfire"  # wayfire: pre-0010 spelling
    desktop = node.get(desktop_key) or {}
    process = node.get("process") or {}
    if not isinstance(desktop, Mapping):
        ctx.error(f"match.{desktop_key} must be a mapping", node, desktop_key)
        desktop = {}
    if not isinstance(process, Mapping):
        ctx.error("match.process must be a mapping", node, "process")
        process = {}
    return MatchRule(
        app_id_regex=_regex_list(ctx, desktop, "app_id_regex", f"match.{desktop_key}.app_id_regex"),
        argv_regex=_regex_list(ctx, process, "argv_regex", "match.process.argv_regex"),
        cmdline_regex=_regex_list(ctx, process, "cmdline_regex", "match.process.cmdline_regex"),
    )


def _opt_str(ctx: _Ctx, node: Mapping, key: str, where: str) -> str | None:
    value = node.get(key)
    if value is None:
        return None
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()  # ``learned: 2026-09-16`` is a YAML timestamp scalar
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)  # e.g. ``key: 5``
    if not isinstance(value, str):
        ctx.error(f"{where}.{key} must be a string", node, key)
        return None
    return value


def _req_id(ctx: _Ctx, node: Mapping, where: str) -> str | None:
    if "id" not in node:
        ctx.error(f"{where}: required field 'id' is missing", node)
        return None
    value = node["id"]
    if not isinstance(value, str) or not _ID_RE.match(value):
        ctx.error(f"{where}.id must match {_ID_RE.pattern}", node, "id")
        return None
    return value


def _req_title(ctx: _Ctx, node: Mapping, where: str) -> str | None:
    if "title" not in node:
        ctx.error(f"{where}: required field 'title' is missing", node)
        return None
    value = node["title"]
    if not isinstance(value, str) or not value.strip():
        ctx.error(f"{where}.title must be a non-empty string", node, "title")
        return None
    return value


def _tags(ctx: _Ctx, node: Mapping, key: str, where: str) -> tuple[str, ...] | None:
    value = node.get(key)
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence):
        ctx.error(f"{where}.{key} must be a list of strings", node, key)
        return None
    out = []
    for i, tag in enumerate(value):
        if not isinstance(tag, str) or not tag:
            ctx.error(f"{where}.{key}[{i}] must be a non-empty string", value, i)
            continue
        out.append(tag)
    return tuple(out)


def _hint(ctx: _Ctx, node: object, index: int, hints_node: object) -> Hint | None:
    where = f"hints[{index}]"
    line = ctx.line_of(hints_node, index) or ctx.line_of(node) or 1
    if not isinstance(node, Mapping):
        ctx.error(f"{where} must be a mapping", hints_node, index)
        return None
    unknown = set(map(str, node)) - _HINT_KEYS
    if unknown:
        ctx.error(f"{where}: unknown key(s): {', '.join(sorted(unknown))}", node)
    hint_id = _req_id(ctx, node, where)
    title = _req_title(ctx, node, where)
    kind = node.get("kind", "shortcut")
    if kind not in HINT_KINDS:
        ctx.error(f"{where}.kind must be one of {', '.join(HINT_KINDS)}", node, "kind")
        kind = "shortcut"
    favorite = node.get("favorite", False)
    if not isinstance(favorite, bool):
        ctx.error(f"{where}.favorite must be true or false", node, "favorite")
        favorite = False
    tags = _tags(ctx, node, "tags", where) or ()
    fields = {k: _opt_str(ctx, node, k, where) for k in ("key", "command", "category", "copy")}
    fields.update({k: _opt_str(ctx, node, k, where) for k in ("remark", "source", "learned")})
    if hint_id is None or title is None:
        return None
    return Hint(
        id=hint_id,
        title=title,
        location=SourceLocation(ctx.path, line),
        kind=kind,
        tags=tags,
        favorite=favorite,
        **fields,
    )


def parse_sheet(data: object, path: Path) -> tuple[HintSheet | None, list[Issue]]:
    """Validate a parsed sheet document. Returns the sheet only when there are no issues."""
    ctx = _Ctx(path)
    if not isinstance(data, Mapping):
        ctx.error("sheet must be a mapping at top level")
        return None, ctx.issues
    unknown = set(map(str, data)) - _SHEET_KEYS
    if unknown:
        ctx.error(f"unknown top-level key(s): {', '.join(sorted(unknown))}", data)

    version = data.get("version", SHEET_VERSION)
    if version != SHEET_VERSION:
        ctx.error(f"version must be {SHEET_VERSION}", data, "version")
    sheet_id = _req_id(ctx, data, "sheet")
    title = _req_title(ctx, data, "sheet")
    priority = data.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int):
        ctx.error("priority must be an integer", data, "priority")
        priority = 0
    match = _match_rule(ctx, data)
    try:
        display = parse_display(data.get("display"), "display")
    except ConfigError as e:
        ctx.error(str(e), data, "display")
        display = parse_display(None, "display")

    parent_tags = None
    inherit = data.get("inherit")
    if inherit is not None:
        if not isinstance(inherit, Mapping):
            ctx.error("inherit must be a mapping", data, "inherit")
        else:
            unknown = set(map(str, inherit)) - {"parent_tags"}
            if unknown:
                ctx.error(f"inherit: unknown key(s): {', '.join(sorted(unknown))}", data, "inherit")
            parent_tags = _tags(ctx, inherit, "parent_tags", "inherit")

    hints: list[Hint] = []
    hints_node = data.get("hints", [])
    if hints_node is None:
        hints_node = []
    if isinstance(hints_node, str) or not isinstance(hints_node, Sequence):
        ctx.error("hints must be a list", data, "hints")
        hints_node = []
    seen: dict[str, int] = {}
    for i, item in enumerate(hints_node):
        hint = _hint(ctx, item, i, hints_node)
        if hint is None:
            continue
        if hint.id in seen:
            first_line = seen[hint.id]
            ctx.error(
                f"hints[{i}]: duplicate hint id {hint.id!r} (first defined at line {first_line})",
                hints_node,
                i,
            )
            continue
        seen[hint.id] = hint.location.line
        hints.append(hint)

    if ctx.issues or sheet_id is None or title is None:
        return None, ctx.issues
    return (
        HintSheet(
            id=sheet_id,
            title=title,
            path=path,
            version=version,
            priority=priority,
            match=match,
            display=display,
            parent_tags=parent_tags,
            hints=tuple(hints),
        ),
        [],
    )


def load_sheet(path: Path) -> tuple[HintSheet | None, list[Issue]]:
    data, issues = read_document(path)
    if issues:
        return None, issues
    return parse_sheet(data, path)


def sheet_files(hints_dir: Path) -> list[Path]:
    if not hints_dir.is_dir():
        return []
    return sorted(p for p in hints_dir.iterdir() if p.is_file() and p.suffix in (".yaml", ".yml"))


def check_duplicate_sheet_ids(sheets: Sequence[HintSheet]) -> list[Issue]:
    issues = []
    first: dict[str, HintSheet] = {}
    for sheet in sheets:
        other = first.get(sheet.id)
        if other is None:
            first[sheet.id] = sheet
        else:
            issues.append(
                Issue(sheet.path, 1, f"duplicate sheet id {sheet.id!r} (also in {other.path})")
            )
    return issues


def load_sheets(hints_dir: Path) -> LoadResult:
    result = LoadResult()
    for path in sheet_files(hints_dir):
        sheet, issues = load_sheet(path)
        result.issues.extend(issues)
        if sheet is not None:
            result.sheets.append(sheet)
    result.issues.extend(check_duplicate_sheet_ids(result.sheets))
    return result


def load_all(config_root: Path) -> LoadResult:
    """``config.yaml`` + ``hints/*.yaml`` under ``config_root``."""
    result = load_config(config_root / "config.yaml")
    sheets = load_sheets(config_root / "hints")
    result.sheets = sheets.sheets
    result.issues.extend(sheets.issues)
    return result


# --- last-known-good ---------------------------------------------------------------------------


class SheetStore:
    """Per-file sheets with last-known-good semantics.

    ``reload(path)`` replaces the stored sheet only when the new parse is clean. On failure the
    previous sheet stays and the issues are recorded under ``errors[path]`` until a later reload
    succeeds (or the file is removed).
    """

    def __init__(self, hints_dir: Path) -> None:
        self.hints_dir = hints_dir
        self._sheets: dict[Path, HintSheet] = {}
        self.errors: dict[Path, list[Issue]] = {}

    def load_all(self) -> None:
        for path in sheet_files(self.hints_dir):
            self.reload(path)

    def reload(self, path: Path) -> bool:
        if not path.exists():
            self._sheets.pop(path, None)
            self.errors.pop(path, None)
            return True
        sheet, issues = load_sheet(path)
        if sheet is None:
            self.errors[path] = issues
            return False
        self._sheets[path] = sheet
        self.errors.pop(path, None)
        return True

    @property
    def sheets(self) -> list[HintSheet]:
        return [self._sheets[p] for p in sorted(self._sheets)]

    @property
    def issues(self) -> list[Issue]:
        out = [i for issues in self.errors.values() for i in issues]
        out.extend(check_duplicate_sheet_ids(self.sheets))
        return out
