"""Normalise a process description (from Herdr, in V1) into :class:`ProcessInfo`."""

from __future__ import annotations

from collections.abc import Mapping

from wayhint.models import ProcessInfo


def process_info_from_mapping(raw: Mapping) -> ProcessInfo | None:
    pid = raw.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    argv_raw = raw.get("argv") or []
    argv = tuple(str(a) for a in argv_raw) if isinstance(argv_raw, (list, tuple)) else ()
    cmdline = raw.get("cmdline")
    if not isinstance(cmdline, str) or not cmdline:
        cmdline = " ".join(argv)
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        name = argv[0].rsplit("/", 1)[-1] if argv else ""
    if not name and not cmdline:
        return None
    cwd = raw.get("cwd")
    return ProcessInfo(
        pid=pid, name=name, argv=argv, cmdline=cmdline, cwd=cwd if isinstance(cwd, str) else None
    )
