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
import itertools
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark, MarkedYAMLError, YAMLError
from ruamel.yaml.tokens import CommentToken

from wayhint.config import (
    ConfigError,
    GlobalConfig,
    config_dir,
    parse_display,
    parse_global_config,
)
from wayhint.i18n import resolve_language
from wayhint.matcher import GENERIC_PROCESS_NAMES, argv_basenames, strip_pid_suffix
from wayhint.models import (
    HINT_KINDS,
    Hint,
    HintSheet,
    MatchRule,
    ResolvedContext,
    SourceLocation,
)

SHEET_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHEET_KEYS = {
    "version",
    "id",
    "title",
    "priority",
    "match",
    "include",
    "display",
    "inherit",
    "hints",
}
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
    severity: str = "error"
    """``error`` keeps the sheet out; ``warning`` is reported but the sheet is still used.

    Everything that makes a document unreadable is an error. A warning is for something the
    user should fix that does not stop the rest from working -- an ``include`` naming a sheet
    that is not there (0026).
    """

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else str(self.file)
        prefix = "" if self.severity == "error" else f"{self.severity}: "
        return f"{where}: {prefix}{self.message}"


@dataclass
class LoadResult:
    sheets: list[HintSheet] = field(default_factory=list)
    config: GlobalConfig | None = None
    issues: list[Issue] = field(default_factory=list)
    includes: dict[Path, list[HintSheet]] = field(default_factory=dict)
    """Per sheet (by file), the sheets its ``include`` resolved to, in the order written."""

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    def includes_for(self, sheet: HintSheet) -> list[HintSheet]:
        return self.includes.get(sheet.path, [])


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


DUMP_WIDTH = 4096
"""Wide enough that ruamel never re-wraps a long scalar (the default 80 would, and would leave a
trailing space behind). Long lines in hint sheets are normal: a ``remark`` is a sentence."""


def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    # Without this, ``hints:`` items lose their two-space indent on dump; with it, every sheet in
    # the repository round-trips byte for byte (DECISIONS 0014 D2).
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = DUMP_WIDTH
    return y


def read_document(path: Path) -> tuple[object, list[Issue]]:
    """Parse one YAML file. Returns ``(data, issues)``; ``data`` is ``None`` on error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, [Issue(path, None, f"cannot read: {e.strerror or e}")]
    except UnicodeDecodeError as e:
        # A file saved in another encoding is a problem to report like any other, not a crash
        # in whatever asked for it: the CLI, the daemon at start, or a reload.
        return None, [Issue(path, None, f"not valid utf-8 at byte {e.start}: {e.reason}")]
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


def _no_unknown(
    ctx: _Ctx, node: Mapping, where: str, allowed: set[str], parent: object, key: object
) -> None:
    """An unknown key is an error at every level, not only the top one (DECISIONS 0002 (d))."""
    unknown = sorted(set(map(str, node)) - allowed)
    if unknown:
        ctx.error(f"{where}: unknown key(s): {', '.join(unknown)}", parent, key)


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
    else:
        _no_unknown(ctx, desktop, f"match.{desktop_key}", {"app_id_regex"}, node, desktop_key)
    if not isinstance(process, Mapping):
        ctx.error("match.process must be a mapping", node, "process")
        process = {}
    else:
        _no_unknown(ctx, process, "match.process", {"argv_regex", "cmdline_regex"}, node, "process")
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


def _sheet_ids(ctx: _Ctx, node: Mapping, key: str, where: str) -> tuple[str, ...] | None:
    """A list of sheet ids, or ``None`` when the key is absent (which means "use the default")."""
    value = node.get(key)
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence):
        ctx.error(f"{where}.{key} must be a list of sheet ids", node, key)
        return None
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not _ID_RE.match(item):
            ctx.error(f"{where}.{key}[{i}] must match {_ID_RE.pattern}", value, i)
            continue
        out.append(item)
    return tuple(out)


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

    include = _sheet_ids(ctx, data, "include", "sheet")
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
            include=include,
            hints=tuple(hints),
        ),
        [],
    )


def load_sheet(path: Path) -> tuple[HintSheet | None, list[Issue]]:
    """Read one file. A sheet whose ``id`` is not the file name is not a sheet (0020).

    Renaming or copying a file is how a second sheet with somebody else's id appears; loading it
    would mean two files answering for one id, and which of them won would depend on the names.
    Tying the id to the file name removes the question: ``claude.yaml`` is sheet ``claude``, and
    ``claude-backup.yaml`` is reported and left out until it is given its own id.
    """
    data, issues = read_document(path)
    if issues:
        return None, issues
    sheet, issues = parse_sheet(data, path)
    if sheet is not None and sheet.id != path.stem:
        message = (
            f"sheet id {sheet.id!r} does not match the file name {path.stem!r}: "
            f"rename the file to {sheet.id}{path.suffix} or change the id to {path.stem!r}"
        )
        return None, [Issue(path, _line_for_key_path(data, "id"), message)]
    return sheet, issues


def hints_dir(root: Path, language: str = "auto", environ: Mapping[str, str] | None = None) -> Path:
    """Where the sheets for ``language`` live, under ``root`` (DECISIONS 0024).

    One language, one directory: ``hints/<lang>/`` when it exists, else ``hints/en/``, else the
    flat ``hints/`` of a single-language setup. The language is the one the interface uses, so
    the hints and the labels around them can never be in different languages, and switching the
    setting switches both. Directories that are not a language code are simply never asked for.
    """
    base = root / "hints"
    for lang in (resolve_language(language, environ), "en"):
        candidate = base / lang
        if candidate.is_dir():
            return candidate
    return base


def sheet_files(hints_dir: Path) -> list[Path]:
    if not hints_dir.is_dir():
        return []
    return sorted(p for p in hints_dir.iterdir() if p.is_file() and p.suffix in (".yaml", ".yml"))


def unique_sheet_ids(sheets: Sequence[HintSheet]) -> tuple[list[HintSheet], list[Issue]]:
    """Split ``sheets`` into the ones that are used and the collisions that are not.

    Two files claiming one id is ambiguous, and ambiguity is never resolved by chance
    (設計書 §59): sheets are read in file-name order, so the first file wins and every later one
    is left out with an issue naming both files. ``sheets`` is expected in that order.
    """
    kept: list[HintSheet] = []
    issues: list[Issue] = []
    first: dict[str, HintSheet] = {}
    for sheet in sheets:
        other = first.get(sheet.id)
        if other is None:
            first[sheet.id] = sheet
            kept.append(sheet)
        else:
            issues.append(
                Issue(
                    sheet.path,
                    1,
                    f"duplicate sheet id {sheet.id!r}: {sheet.path.name} is not used, "
                    f"{other.path.name} was read first",
                )
            )
    return kept, issues


def resolve_includes(
    sheets: Sequence[HintSheet], global_include: Sequence[str] = ()
) -> tuple[dict[Path, list[HintSheet]], list[Issue]]:
    """Turn every sheet's ``include`` into the sheets it names (DECISIONS 0026).

    A sheet without ``include`` uses ``global_include`` from config.yaml; writing ``include`` in
    the sheet replaces that default rather than adding to it, the way ``inherit.parent_tags``
    replaces ``nested.parent_tags``. A name that is not there, and a sheet naming itself, are
    warnings: the sheet is still shown, only that one name is dropped. The second level is not
    followed -- what a sheet includes is what it says, not what its includes say.
    """
    by_id = {sheet.id: sheet for sheet in sheets}
    resolved: dict[Path, list[HintSheet]] = {}
    issues: list[Issue] = []
    for sheet in sheets:
        own = sheet.include is not None
        wanted = sheet.include if own else tuple(global_include)
        found: list[HintSheet] = []
        for name in wanted:
            if name == sheet.id:
                # The global default names every sheet, this one included; only a sheet that
                # writes its own name is saying something wrong.
                if own:
                    issues.append(
                        Issue(sheet.path, 1, f"include: {name!r} is this sheet", "warning")
                    )
                continue
            other = by_id.get(name)
            if other is None:
                issues.append(
                    Issue(sheet.path, 1, f"include: no sheet with id {name!r}", "warning")
                )
                continue
            found.append(other)
        resolved[sheet.path] = found
    return resolved, issues


def load_sheets(hints_dir: Path, global_include: Sequence[str] = ()) -> LoadResult:
    result = LoadResult()
    for path in sheet_files(hints_dir):
        sheet, issues = load_sheet(path)
        result.issues.extend(issues)
        if sheet is not None:
            result.sheets.append(sheet)
    result.sheets, duplicates = unique_sheet_ids(result.sheets)
    result.issues.extend(duplicates)
    result.includes, include_issues = resolve_includes(result.sheets, global_include)
    result.issues.extend(include_issues)
    return result


def load_all(config_root: Path) -> LoadResult:
    """``config.yaml`` + the sheets of the configured language under ``config_root`` (0024)."""
    result = load_config(config_root / "config.yaml")
    language = result.config.language if result.config is not None else "auto"
    include = result.config.include if result.config is not None else ()
    sheets = load_sheets(hints_dir(config_root, language), include)
    result.sheets = sheets.sheets
    result.includes = sheets.includes
    result.issues.extend(sheets.issues)
    return result


# --- last-known-good ---------------------------------------------------------------------------


class SheetStore:
    """Per-file sheets with last-known-good semantics.

    ``reload(path)`` replaces the stored sheet only when the new parse is clean. On failure the
    previous sheet stays and the issues are recorded under ``errors[path]`` until a later reload
    succeeds (or the file is removed).
    """

    def __init__(self, hints_dir: Path, global_include: Sequence[str] = ()) -> None:
        self.hints_dir = hints_dir
        self.global_include = tuple(global_include)
        self._sheets: dict[Path, HintSheet] = {}
        self.errors: dict[Path, list[Issue]] = {}
        self._includes: dict[Path, list[HintSheet]] = {}
        self._include_issues: list[Issue] = []

    def load_all(self) -> None:
        """Re-read the directory, including what is no longer in it.

        An explicit reload is the way out of a missed file event, so it has to end up agreeing
        with the directory: a sheet whose file is gone -- and the issues recorded against it --
        are dropped instead of lingering until the daemon restarts.
        """
        found = set(sheet_files(self.hints_dir))
        for path in [*self._sheets, *self.errors]:
            if path not in found:
                self._sheets.pop(path, None)
                self.errors.pop(path, None)
        for path in found:
            self.reload(path)
        self.resolve()

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
        self.resolve()
        return True

    def resolve(self) -> None:
        """Re-resolve every sheet's ``include``; called after the sheets change (0026)."""
        self._includes, self._include_issues = resolve_includes(self.sheets, self.global_include)

    def includes_for(self, sheet: HintSheet | None) -> list[HintSheet]:
        return self._includes.get(sheet.path, []) if sheet is not None else []

    @property
    def sheets(self) -> list[HintSheet]:
        """The sheets in use: file-name order, and never two files under one id."""
        return unique_sheet_ids([self._sheets[p] for p in sorted(self._sheets)])[0]

    @property
    def issues(self) -> list[Issue]:
        out = [i for issues in self.errors.values() for i in issues]
        out.extend(unique_sheet_ids([self._sheets[p] for p in sorted(self._sheets)])[1])
        out.extend(self._include_issues)
        return out


# --- writing -----------------------------------------------------------------------------------
#
# Everything below writes YAML back. Pure functions over a ruamel document plus one atomic file
# write; no GTK, no compositor, no subprocess (DECISIONS 0014 D2).

CANONICAL_HINT_KEYS = (
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
)
"""The order a hint is written in. Reading does not care about order or about missing keys."""

MODELINE_PREFIX = "# yaml-language-server: $schema="
GENERIC_PROCESS_WARNING = "generic process name: check the match rule"


class SheetWriteError(RuntimeError):
    """A sheet could not be written. Safe to display in the overlay."""

    def __init__(self, message: str, issues: Sequence[Issue] = ()) -> None:
        super().__init__(message)
        self.issues = list(issues)


class HintNotFoundError(SheetWriteError):
    """The hint id is not in the document.

    It happens when the sheet was edited elsewhere while a form was open (DECISIONS 0014 D2).
    """


def write_document(path: Path, doc: object) -> None:
    """Write a sheet over ``path``, atomically, and only if the result still validates."""

    def check(data: object) -> list[Issue]:
        return parse_sheet(data, path)[1]

    _write_checked(path, doc, check)


def write_config(path: Path, doc: object) -> None:
    """Write ``config.yaml`` the same way, validated as the global config (DECISIONS 0018)."""

    def check(data: object) -> list[Issue]:
        try:
            parse_global_config(data)
        except ConfigError as e:
            return [Issue(path, _line_for_key_path(data, e.key), str(e))]
        return []

    _write_checked(path, doc, check)


_write_serial = itertools.count()


def _write_checked(path: Path, doc: object, check: Callable[[object], list[Issue]]) -> None:
    """Dump, re-read, validate, then replace. Nothing is written when the result would not load.

    The temporary file sits next to the target (``os.replace`` cannot cross filesystems) and must
    not end in ``.yaml`` / ``.yml``: ``hints/`` is watched as a directory, so a temporary sheet
    would be picked up as a real one for as long as it exists.

    The name also has to be this writer's own. The overlay and the CLI write the same sheets, and
    a shared ``<name>.tmp`` lets one writer read, replace or delete the other's file mid-flight,
    which fails in ways that are not "the last writer wins". Process id plus a counter is unique
    while both are running, which is exactly as long as it matters; a name left behind by a
    crashed writer is simply overwritten. Ordering between writers is still last-write-wins --
    no mtime comparison is added here.
    """
    if not path.parent.is_dir():
        raise SheetWriteError(f"no such directory: {path.parent}")
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{next(_write_serial)}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            _yaml().dump(doc, fh)
        data, issues = read_document(tmp)
        if not issues:
            # Validate what will actually land, but report it against the real name.
            issues = check(data)
        if issues:
            raise SheetWriteError(f"{path.name} would not validate; nothing was written", issues)
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o7777)  # keep the mode the user gave the file
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def set_overlay_size(doc: object, width: int, height: int) -> CommentedMap:
    """``overlay.width`` / ``overlay.height`` set to ``<n>px``, keeping everything else.

    Takes the document ``read_document`` returned (``None`` when there is no config.yaml yet) and
    returns the document to write. Percentages given by hand become pixels the moment the overlay
    is resized by hand -- that is the point of the resize (DECISIONS 0018).
    """
    root = doc if isinstance(doc, CommentedMap) else CommentedMap()
    overlay = root.get("overlay")
    if not isinstance(overlay, CommentedMap):
        overlay = CommentedMap()
        root["overlay"] = overlay
    overlay["width"] = f"{max(1, int(width))}px"
    overlay["height"] = f"{max(1, int(height))}px"
    return root


def _flow_tags(values: object) -> CommentedSeq:
    seq = CommentedSeq(str(v) for v in values)  # type: ignore[union-attr]
    seq.fa.set_flow_style()  # ``tags: [a, b]``, the spelling the hand-written sheets use
    return seq


def build_hint(fields: Mapping[str, object]) -> CommentedMap:
    """One hint as it is written: all 12 keys, canonical order, unset ones ``null``.

    ``kind`` and ``favorite`` never become ``null`` -- validation rejects both.
    """
    unknown = set(map(str, fields)) - set(CANONICAL_HINT_KEYS)
    if unknown:
        raise ValueError(f"unknown hint field(s): {', '.join(sorted(unknown))}")
    out = CommentedMap()
    for key in CANONICAL_HINT_KEYS:
        value = fields.get(key)
        if key == "kind":
            value = value or "shortcut"
        elif key == "favorite":
            value = bool(value)
        elif key == "tags":
            value = _flow_tags(value) if value else None
        elif isinstance(value, str) and not value.strip():
            value = None  # an empty form field is "unset", not ""
        out[key] = value
    return out


def _carry_comments(old: Mapping, new: CommentedMap) -> CommentedMap:
    """Move a rebuilt hint's comments across.

    A trailing comment after the last hint, and an end-of-line comment on a key, both live inside
    the hint's own ``ca``. Rebuilding the mapping would drop them, and D2 says only the *order* of
    the target hint may change.
    """
    ca = getattr(old, "ca", None)
    if ca is None:
        return new
    if ca.comment is not None:
        new.ca.comment = ca.comment
    for key, comment in getattr(ca, "items", {}).items():
        if key in new:
            new.ca.items[key] = comment
    return new


def _hints_of(doc: object) -> CommentedSeq:
    if not isinstance(doc, Mapping):
        raise SheetWriteError("sheet must be a mapping at top level")
    hints = doc.get("hints")
    if hints is None:
        hints = CommentedSeq()
        doc["hints"] = hints  # type: ignore[index]
    if isinstance(hints, str) or not isinstance(hints, Sequence):
        raise SheetWriteError("hints must be a list")
    return hints


def _index_of(hints: Sequence, hint_id: str) -> int:
    for i, item in enumerate(hints):
        if isinstance(item, Mapping) and item.get("id") == hint_id:
            return i
    raise HintNotFoundError(f"hint {hint_id!r} is not in this sheet")


def append_hint(doc: object, hint: Mapping[str, object]) -> None:
    _hints_of(doc).append(hint)


def update_hint(doc: object, hint_id: str, fields: Mapping[str, object]) -> CommentedMap:
    """Rebuild one hint from its current values plus ``fields``. Other hints are not touched."""
    hints = _hints_of(doc)
    index = _index_of(hints, hint_id)
    current = hints[index]
    base: dict[str, object] = {k: current.get(k) for k in CANONICAL_HINT_KEYS}
    base.update(fields)
    hints[index] = _carry_comments(current, build_hint(base))
    return hints[index]


def set_favorite(doc: object, hint_id: str, value: bool) -> CommentedMap:
    return update_hint(doc, hint_id, {"favorite": bool(value)})


def toggle_favorite(doc: object, hint_id: str) -> CommentedMap:
    """Flip what the file says, not what the caller last saw.

    Reloads are debounced, so two presses in a row would otherwise both be computed from the
    same in-memory copy and write the same value twice.
    """
    hints = _hints_of(doc)
    node = hints[_index_of(hints, hint_id)]
    current = node.get("favorite") if isinstance(node, Mapping) else False
    return set_favorite(doc, hint_id, not bool(current))


def delete_hint(doc: object, hint_id: str) -> CommentedMap:
    """Remove a hint and return the node, so ``u`` can put it back.

    ruamel drops the block comment stored at that index with it, which is what we want: the
    comment above a hint describes that hint.
    """
    hints = _hints_of(doc)
    index = _index_of(hints, hint_id)
    node = hints[index]
    del hints[index]
    return node


def swap_hints(doc: object, id_a: str, id_b: str) -> None:
    """Swap two hints' positions, block comments included."""
    hints = _hints_of(doc)
    i, j = _index_of(hints, id_a), _index_of(hints, id_b)
    if i == j:
        return
    hints[i], hints[j] = hints[j], hints[i]
    items = getattr(getattr(hints, "ca", None), "items", None)
    if items is None:
        return
    comment_i, comment_j = items.pop(i, None), items.pop(j, None)
    if comment_j is not None:
        items[i] = comment_j
    if comment_i is not None:
        items[j] = comment_i


def _start_comment_tokens(doc: object) -> list:
    comment = getattr(getattr(doc, "ca", None), "comment", None)
    return list(comment[1]) if comment and comment[1] else []


def ensure_modeline(doc: object, schema_path: Path | str) -> None:
    """Put ``# yaml-language-server: $schema=...`` first, unless the file already has one."""
    if any(MODELINE_PREFIX in getattr(t, "value", "") for t in _start_comment_tokens(doc)):
        return
    token = CommentToken(f"{MODELINE_PREFIX}{schema_path}\n", CommentMark(0))
    comment = getattr(doc, "ca", None)
    if comment is None:
        raise SheetWriteError("cannot add a modeline to this document")
    if comment.comment is None:
        comment.comment = [None, [token]]
    else:
        comment.comment[1] = [token, *(comment.comment[1] or [])]


def normalize_sheet(doc: object, modeline_path: Path | str | None = None) -> None:
    """``wayhint format``: every hint canonical, 12 keys. Sheet metadata and comments stay."""
    hints = _hints_of(doc)
    for index, item in enumerate(hints):
        if not isinstance(item, Mapping):
            raise SheetWriteError(f"hints[{index}] must be a mapping")
        unknown = set(map(str, item)) - set(CANONICAL_HINT_KEYS)
        if unknown:
            raise SheetWriteError(f"hints[{index}]: unknown key(s): {', '.join(sorted(unknown))}")
        hints[index] = _carry_comments(
            item, build_hint({k: item.get(k) for k in CANONICAL_HINT_KEYS})
        )
    if modeline_path is not None:
        ensure_modeline(doc, modeline_path)


_SLUG_INVALID = re.compile(r"[^a-z0-9._-]+")
_SLUG_DASHES = re.compile(r"-{2,}")


def slug(text: str, existing: Sequence[str] = (), now: _dt.datetime | None = None) -> str:
    """An id derived from a title: lower case, ``[A-Za-z0-9][A-Za-z0-9._-]*``, never a duplicate.

    A title with nothing usable in it (Japanese, emoji) falls back to a timestamp, so a hint
    captured in a hurry still gets a stable id.
    """
    base = _SLUG_DASHES.sub("-", _SLUG_INVALID.sub("-", (text or "").casefold())).strip("-._")
    while base and not base[0].isascii() or base and not base[0].isalnum():
        base = base[1:]
    if not base:
        stamp = (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
        base = f"q-{stamp}"
    taken = set(existing)
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def match_rule_for_context(ctx: ResolvedContext) -> tuple[CommentedMap, str | None]:
    """The ``match:`` block for a sheet generated from ``ctx``, plus a warning to show, or ``None``.

    Which key the context was decided by is recoverable from the context itself: with a
    foreground process the sheet was chosen by that process, without one by ``app_id``
    (DECISIONS 0014 D6). Interpreter names say nothing about what is running, so for those the
    regex is taken from the arguments instead, using the same basename rule as the matcher.

    The test is the foreground process and not ``parent_context``: a terminal usually has no
    sheet of its own, so there is no parent, and a rule built from the terminal's ``app_id``
    would match every command ever run in it (DECISIONS 0027).
    """
    proc = ctx.foreground_process
    if proc is None:
        # The pid suffix names one window, not the program: a rule built from it would match
        # that window and nothing ever again (0027).
        base, _pid = strip_pid_suffix(ctx.desktop_app)
        return _match_map("wayland", "app_id_regex", base or ""), None
    if proc.name not in GENERIC_PROCESS_NAMES:
        return _match_map("process", "argv_regex", proc.name), None
    for candidate in argv_basenames(proc.argv[1:]):
        # ``-l`` is an option, not a program: a rule built from it would match anything.
        if candidate and not candidate.startswith("-") and candidate not in GENERIC_PROCESS_NAMES:
            return _match_map("process", "argv_regex", candidate), None
    return _match_map("process", "argv_regex", proc.name), GENERIC_PROCESS_WARNING


def _match_map(section: str, key: str, value: str) -> CommentedMap:
    patterns = _flow_tags([f"^{re.escape(value)}$"])
    inner = CommentedMap([(key, patterns)])
    return CommentedMap([(section, inner)])


def create_sheet(
    ctx: ResolvedContext,
    first_hint: Mapping[str, object],
    config: GlobalConfig,
    hints_dir: Path | None = None,
    existing_ids: Sequence[str] = (),
    now: _dt.datetime | None = None,
) -> tuple[Path, CommentedMap]:
    """A new sheet for a context that has none, holding ``first_hint`` (DECISIONS 0014 D6).

    The point is that nobody is asked for a file name or a regex: the daemon already knows how
    the context was decided, and that is exactly what the sheet has to say.
    """
    now = now or _dt.datetime.now()
    hints_dir = hints_dir if hints_dir is not None else config_dir() / "hints"
    proc = ctx.foreground_process
    source = proc.name if proc is not None else strip_pid_suffix(ctx.desktop_app)[0]
    sheet_id = slug(source or "", existing_ids, now)
    match, _warning = match_rule_for_context(ctx)

    doc = CommentedMap()
    doc["id"] = sheet_id
    doc["title"] = (source or sheet_id).strip()
    doc["priority"] = 0
    doc["match"] = match
    doc["hints"] = CommentedSeq([first_hint])
    regex = next(iter(next(iter(match.values())).values()))
    doc.yaml_set_start_comment(
        "\n".join(
            [
                f"generated by wayhint {now.strftime('%Y-%m-%d %H:%M')}",
                f"desktop_app: {ctx.desktop_app or '-'}",
                f"parent_context: {ctx.parent_context or '-'}",
                f"foreground_process: {proc.name if proc else '-'}",
                f"match: {list(regex)}",
            ]
        )
    )
    if config.editor.schema_modeline:
        ensure_modeline(doc, Path(config.editor.schema_path).expanduser().resolve())
    return hints_dir / f"{sheet_id}.yaml", doc
