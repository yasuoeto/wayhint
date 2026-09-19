"""``wayhint`` command line.

Three kinds of subcommand:

- ``validate`` reads the configuration and says whether it is sound. No daemon.
- ``toggle`` / ``show`` / ``hide`` / ``refresh`` / ``reload`` / ``ping`` / ``context`` /
  ``edit-mode`` are one-line requests to ``wayhintd``.
- ``add`` / ``edit`` / ``remove`` / ``favorite`` / ``move`` / ``format`` / ``schema`` change hint
  sheets. They write the files themselves and never go through the daemon (DECISIONS 0014 D11);
  the daemon notices the change through its file monitor. The only thing they ask the daemon is
  *which sheet*, and only when ``--sheet`` was left out.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from wayhint import __version__, ipc
from wayhint.config import GlobalConfig, config_dir
from wayhint.models import HINT_KINDS, Hint, HintSheet, ProcessInfo, ResolvedContext
from wayhint.schema import json_schema
from wayhint.selection import effective_parent_tags, same_group, sort_hints
from wayhint.ui.editmode import kind_fields
from wayhint.yaml_store import (
    HintNotFoundError,
    LoadResult,
    SheetWriteError,
    append_hint,
    build_hint,
    create_sheet,
    delete_hint,
    hints_dir,
    load_all,
    match_rule_for_context,
    normalize_sheet,
    read_document,
    set_favorite,
    sheet_files,
    slug,
    swap_hints,
    update_hint,
    write_document,
)


class CommandError(RuntimeError):
    """Anything the user should see as ``wayhint: ...`` on stderr."""


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.config_dir) if args.config_dir else config_dir()
    result = load_all(root)
    for issue in result.issues:
        print(str(issue), file=sys.stderr)
    errors = result.errors
    if errors:
        print(f"validate: {len(errors)} problem(s) in {root}", file=sys.stderr)
        return 1
    hints = sum(len(s.hints) for s in result.sheets)
    # Warnings (an ``include`` that names nothing, say) are printed but do not fail the run:
    # everything still loads, and the exit code is what scripts act on (DECISIONS 0026).
    warned = len(result.issues)
    suffix = f", {warned} warning(s)" if warned else ""
    print(f"validate: ok ({len(result.sheets)} sheet(s), {hints} hint(s){suffix}) in {root}")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    try:
        reply = ipc.send_command(args.command, Path(args.socket) if args.socket else None)
    except ipc.DaemonUnavailable as e:
        print(f"wayhint: {e}", file=sys.stderr)
        return 2
    if not reply.get("ok"):
        print(f"wayhint: {reply.get('error', 'unknown error')}", file=sys.stderr)
        return 1
    extras = {k: v for k, v in reply.items() if k != "ok" and v not in (None, [], {})}
    if extras:
        print(" ".join(f"{k}={v}" for k, v in extras.items()))
    return 0


# --- hint editing ------------------------------------------------------------------------------


def _load() -> tuple[Path, LoadResult, GlobalConfig]:
    root = config_dir()
    result = load_all(root)
    if result.issues:
        for issue in result.issues:
            print(str(issue), file=sys.stderr)
        raise CommandError("fix the problems above first; nothing was written")
    return root, result, result.config or GlobalConfig()


def _daemon_context() -> dict:
    """Ask the daemon what is in front of the user. Only used when ``--sheet`` was left out."""
    try:
        reply = ipc.send_command("context")
    except ipc.DaemonUnavailable as e:
        raise CommandError(f"{e}; pass --sheet to say which sheet to change") from e
    if not reply.get("ok"):
        raise CommandError(str(reply.get("error", "unknown error")))
    return reply


def _resolved_context(reply: dict) -> ResolvedContext:
    """Rebuild enough of a :class:`ResolvedContext` for :func:`create_sheet`.

    ``argv_basenames`` stands in for ``argv``: the match rule only ever looks at basenames, so
    the sheet that comes out is the same one the daemon would have written.
    """
    process = reply.get("process") or None
    proc = None
    if process:
        argv = tuple(str(a) for a in process.get("argv_basenames") or ())
        proc = ProcessInfo(pid=0, name=str(process.get("name") or ""), argv=argv, cmdline="")
    return ResolvedContext(
        desktop_app=reply.get("desktop_app"),
        parent_context=reply.get("parent_context"),
        foreground_process=proc,
        active_sheet=reply.get("active_sheet"),
    )


def _sheet_by_id(result: LoadResult, sheet_id: str | None) -> HintSheet | None:
    return next((s for s in result.sheets if s.id == sheet_id), None) if sheet_id else None


def _target_sheet(args: argparse.Namespace, result: LoadResult) -> HintSheet:
    """The sheet a command acts on: ``--sheet`` if given, else the current context's."""
    if getattr(args, "sheet", None):
        sheet = _sheet_by_id(result, args.sheet)
        if sheet is None:
            raise CommandError(f"no sheet with id {args.sheet!r}")
        return sheet
    reply = _daemon_context()
    wanted = (
        reply.get("parent_context") if getattr(args, "parent", False) else reply.get("active_sheet")
    )
    sheet = _sheet_by_id(result, wanted)
    if sheet is None:
        raise CommandError(_no_sheet_message(reply))
    return sheet


def _no_sheet_message(reply: dict) -> str:
    """Say *why* there is no sheet when the daemon told us (context resolution can fail)."""
    reason = reply.get("error")
    return (
        "no sheet for the current context" + (f" ({reason})" if reason else "") + "; pass --sheet"
    )


def _edited_fields(args: argparse.Namespace) -> dict[str, object]:
    fields: dict[str, object] = {}
    for name in ("title", "kind", "key", "command", "category", "remark"):
        value = getattr(args, name, None)
        if value is not None:
            fields[name] = value
    return fields


def _check_kind(fields: Mapping[str, object], kind: str) -> None:
    """A hint only carries what its kind allows: ``tip`` both, ``note`` neither (DESIGN §3)."""
    allowed = kind_fields(kind)
    for name in ("key", "command"):
        if name in fields and name not in allowed:
            wanted = " or ".join(f"--{a}" for a in allowed) or "neither"
            raise CommandError(f"--{name} does not go with --kind {kind}; use {wanted}")


def _write(path: Path, mutate) -> None:
    doc, issues = read_document(path)
    if issues:
        raise CommandError(str(issues[0]))
    mutate(doc)
    write_document(path, doc)


def cmd_add(args: argparse.Namespace) -> int:
    _root, result, config = _load()
    fields = _edited_fields(args)
    fields["title"] = args.title
    fields.setdefault("kind", "shortcut")
    _check_kind(fields, str(fields["kind"]))
    fields["favorite"] = False
    fields["learned"] = dt.date.today().isoformat()

    sheet: HintSheet | None = None
    context: ResolvedContext | None = None
    if args.sheet:
        sheet = _target_sheet(args, result)
    else:
        context = _resolved_context(_daemon_context())
        wanted = context.parent_context if args.parent else context.active_sheet
        sheet = _sheet_by_id(result, wanted)
    if sheet is not None and args.parent:
        child = _sheet_by_id(result, (context.active_sheet if context else None))
        tags = effective_parent_tags(child, config.parent_tags)
        if tags:
            fields["tags"] = list(tags)

    if sheet is not None:
        fields["id"] = slug(args.title, [h.id for h in sheet.hints])
        _write(sheet.path, lambda doc: append_hint(doc, build_hint(fields)))
        print(f"added {fields['id']} to {sheet.path}")
        return 0

    if context is None:
        raise CommandError("no sheet for the current context; pass --sheet")
    fields["id"] = slug(args.title)
    path, doc = create_sheet(
        context,
        build_hint(fields),
        config,
        hints_dir=hints_dir(config_dir(), config.language),
        existing_ids=[s.id for s in result.sheets],
    )
    _match, warning = match_rule_for_context(context)
    write_document(path, doc)
    if warning:
        print(f"wayhint: {warning} ({path})", file=sys.stderr)
    print(f"created {path} with {fields['id']}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    _root, result, _config = _load()
    sheet = _target_sheet(args, result)
    fields = _edited_fields(args)
    if not fields:
        raise CommandError("nothing to change; pass at least one of --title/--kind/--key/…")
    current = next((h for h in sheet.hints if h.id == args.id), None)
    _check_kind(fields, str(fields.get("kind") or (current.kind if current else "shortcut")))
    _write(sheet.path, lambda doc: update_hint(doc, args.id, fields))
    print(f"updated {args.id} in {sheet.path}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    _root, result, _config = _load()
    sheet = _target_sheet(args, result)
    _write(sheet.path, lambda doc: delete_hint(doc, args.id))
    print(f"removed {args.id} from {sheet.path}")
    return 0


def cmd_favorite(args: argparse.Namespace) -> int:
    _root, result, _config = _load()
    sheet = _target_sheet(args, result)
    value = not args.off
    _write(sheet.path, lambda doc: set_favorite(doc, args.id, value))
    print(f"{'set' if value else 'cleared'} favorite on {args.id} in {sheet.path}")
    return 0


def neighbour(hints: Sequence[Hint], hint_id: str, direction: str) -> Hint:
    """The hint ``J`` / ``K`` would swap with, or a refusal (DECISIONS 0014 D8).

    The order is the one the overlay shows, so ``up`` means "one row up on screen", not "one
    entry earlier in the file".
    """
    ordered = sort_hints(hints)
    index = next((i for i, h in enumerate(ordered) if h.id == hint_id), None)
    if index is None:
        raise HintNotFoundError(f"hint {hint_id!r} is not in this sheet")
    other = index - 1 if direction == "up" else index + 1
    if not 0 <= other < len(ordered):
        edge = "top" if direction == "up" else "bottom"
        raise CommandError(f"{hint_id} is already at the {edge}")
    if not same_group(ordered[index], ordered[other]):
        raise CommandError(
            f"{hint_id} would cross into another group; change its category or favorite instead"
        )
    return ordered[other]


def cmd_move(args: argparse.Namespace) -> int:
    _root, result, _config = _load()
    sheet = _target_sheet(args, result)
    other = neighbour(sheet.hints, args.id, args.direction)
    _write(sheet.path, lambda doc: swap_hints(doc, args.id, other.id))
    print(f"moved {args.id} {args.direction} past {other.id} in {sheet.path}")
    return 0


def cmd_format(args: argparse.Namespace) -> int:
    root, _result, config = _load()
    directory = hints_dir(root, config.language)
    paths = [Path(p) for p in args.paths] if args.paths else sheet_files(directory)
    if not paths:
        raise CommandError(f"no sheets in {directory}")
    modeline = str(Path(config.editor.schema_path).expanduser()) if args.modeline else None
    for path in paths:
        before = path.read_bytes()
        _write(path, lambda doc: normalize_sheet(doc, modeline))
        print(f"{'formatted' if path.read_bytes() != before else 'unchanged'} {path}")
    return 0


def cmd_schema(args: argparse.Namespace) -> int:
    text = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    if not args.write:
        sys.stdout.write(text)
        return 0
    _root, _result, config = _load()
    target = Path(args.write if args.write is not True else config.editor.schema_path)
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def _hint_fields(parser: argparse.ArgumentParser, *, title_option: bool) -> None:
    if title_option:
        parser.add_argument("--title")
    parser.add_argument("--kind", choices=list(HINT_KINDS))
    # Not mutually exclusive: a ``tip`` carries both. The kind decides, in :func:`_check_kind`.
    parser.add_argument("--key", help="key combination, e.g. 'Ctrl-o'")
    parser.add_argument("--command", help="command string; wayhint never runs it")
    parser.add_argument("--category")
    parser.add_argument("--remark")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wayhint")
    parser.add_argument("--version", action="version", version=f"wayhint {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="check config.yaml and hints/*.yaml; exit 1 on problems")
    v.add_argument("--config-dir", help="directory holding config.yaml and hints/ (default: XDG)")
    v.set_defaults(func=cmd_validate)
    help_ = {
        "toggle": "show the overlay, or hide it if it is visible",
        "show": "resolve the context and show the overlay",
        "hide": "hide the overlay",
        "refresh": "re-resolve the context if the overlay is visible",
        "reload": "re-read config.yaml and hints/*.yaml",
        "ping": "check that wayhintd is running",
        "context": "print the context the daemon resolves right now",
        "edit-mode": "enter edit mode in the overlay",
    }
    for name in ipc.COMMANDS:
        c = sub.add_parser(name, help=help_[name])
        c.add_argument("--socket", help="override the Unix socket path")
        c.set_defaults(func=cmd_send)

    add = sub.add_parser("add", help="add a hint to a sheet")
    add.add_argument("title")
    _hint_fields(add, title_option=False)
    add.add_argument("--parent", action="store_true", help="write to the parent sheet instead")
    add.add_argument("--sheet", help="sheet id (default: the current context's sheet)")
    add.set_defaults(func=cmd_add)

    edit = sub.add_parser("edit", help="change fields of one hint")
    edit.add_argument("id")
    _hint_fields(edit, title_option=True)
    edit.add_argument("--sheet", help="sheet id (default: the current context's sheet)")
    edit.set_defaults(func=cmd_edit)

    remove = sub.add_parser("remove", help="delete one hint")
    remove.add_argument("id")
    remove.add_argument("--sheet")
    remove.set_defaults(func=cmd_remove)

    favorite = sub.add_parser("favorite", help="mark a hint as favorite")
    favorite.add_argument("id")
    favorite.add_argument("--off", action="store_true", help="clear it instead")
    favorite.add_argument("--sheet")
    favorite.set_defaults(func=cmd_favorite)

    move = sub.add_parser("move", help="swap a hint with the one above or below it")
    move.add_argument("id")
    move.add_argument("direction", choices=("up", "down"))
    move.add_argument("--sheet")
    move.set_defaults(func=cmd_move)

    fmt = sub.add_parser("format", help="rewrite sheets in canonical form")
    fmt.add_argument("paths", nargs="*", metavar="PATH", help="default: every sheet in hints/")
    fmt.add_argument(
        "--modeline", action="store_true", help="also add the yaml-language-server modeline"
    )
    fmt.set_defaults(func=cmd_format)

    schema = sub.add_parser("schema", help="print the JSON Schema for hint sheets")
    schema.add_argument(
        "--write",
        nargs="?",
        const=True,
        metavar="PATH",
        help="write to PATH instead of stdout (default: editor.schema_path)",
    )
    schema.set_defaults(func=cmd_schema)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CommandError, SheetWriteError) as e:
        print(f"wayhint: {e}", file=sys.stderr)
        for issue in getattr(e, "issues", []):
            print(f"  {issue}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"wayhint: {e.strerror or e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
