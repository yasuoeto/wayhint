"""CLI ↔ daemon protocol over ``$XDG_RUNTIME_DIR/wayhint.sock`` (DECISIONS 0004, 0008).

One request per connection: the client sends a single JSON object terminated by ``\\n``, the
daemon answers with one JSON object and closes. Requests: ``{"cmd": "toggle"|"show"|"hide"|
"refresh"|"reload"|"ping"|"context"|"edit-mode"|"search-mode"}``. Replies: ``{"ok": true, ...}`` or
``{"ok": false, "error": "..."}``. ``context`` answers with the part of the resolved context the
CLI needs to pick a sheet; it stays small on purpose (the reply limit is 4096 bytes). ``shown`` is
a query with no subcommand of its own (``wayhint context --shown``): the context of the overlay on
screen, not resolved again, and what narrowed its mixed-in hints.

This module holds the path, the encoding and the blocking client. The server side lives in the
daemon because it needs the GLib main loop.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import stat
from pathlib import Path
from typing import Any

log = logging.getLogger("wayhint.ipc")

COMMANDS = (
    "toggle",
    "show",
    "hide",
    "refresh",
    "reload",
    "ping",
    "context",
    "edit-mode",
    "search-mode",
)
QUERIES = ("shown",)
"""Requests that only a flag of another subcommand sends, so they are not subcommands."""
MAX_MESSAGE = 4096


FALLBACK_ROOT = "/tmp"  # noqa: S108 - only without XDG_RUNTIME_DIR, and checked below
"""Where the socket's directory goes when there is no ``$XDG_RUNTIME_DIR``."""


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        runtime = _private_dir(Path(FALLBACK_ROOT) / f"wayhint-{os.getuid()}")
    return Path(runtime) / "wayhint.sock"


def _private_dir(path: Path) -> Path:
    """``path`` as a directory only this user can use, created 0700 if it is not there.

    ``/tmp`` is shared: another user can make the directory first, and whoever owns it can
    replace the socket inside with their own. A directory that is not a plain one, is not ours,
    or lets anyone else in is refused rather than used.
    """
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as e:
        raise DaemonUnavailable(f"cannot create {path}: {e.strerror or e}") from e
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise DaemonUnavailable(
            f"{path} is not a private directory of this user; set XDG_RUNTIME_DIR or remove it"
        )
    return path


def encode(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def decode(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_MESSAGE:
        raise ValueError("message too large")
    obj = json.loads(data.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("message must be a JSON object")
    return obj


def handle_request(raw: bytes, dispatch) -> dict[str, Any]:
    """Server helper: parse ``raw``, validate ``cmd``, call ``dispatch(cmd) -> dict``."""
    try:
        req = decode(raw)
    except (ValueError, UnicodeDecodeError) as e:
        return {"ok": False, "error": f"bad request: {e}"}
    cmd = req.get("cmd")
    if cmd not in COMMANDS and cmd not in QUERIES:
        return {"ok": False, "error": f"unknown command: {cmd!r}"}
    try:
        result = dispatch(cmd) or {}
    except Exception as e:  # never let a handler kill the daemon's socket loop
        # The caller is often a hotkey whose stderr goes nowhere; the daemon log is all there is.
        log.exception("%s failed", cmd)
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return {"ok": True, **result}


class DaemonUnavailable(RuntimeError):
    pass


CLIENT_TIMEOUT = 2.0
"""How long the CLI waits for a reply. Work the daemon does for one command has to fit in it,
or the caller reports a failure for something that then happens anyway."""


def send_command(
    cmd: str, path: Path | None = None, timeout: float = CLIENT_TIMEOUT
) -> dict[str, Any]:
    if cmd not in COMMANDS and cmd not in QUERIES:
        raise ValueError(f"unknown command: {cmd!r}")
    path = path or socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(str(path))
        except OSError as e:
            raise DaemonUnavailable(f"wayhintd is not running ({path}): {e.strerror or e}") from e
        s.sendall(encode({"cmd": cmd}))
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > MAX_MESSAGE:
                raise DaemonUnavailable("reply too large")
    try:
        return decode(b"".join(chunks))
    except ValueError as e:
        raise DaemonUnavailable(f"bad reply from daemon: {e}") from e
