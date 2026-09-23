"""CLI ↔ daemon protocol over ``$XDG_RUNTIME_DIR/wayhint.sock`` (DECISIONS 0004, 0008).

One request per connection: the client sends a single JSON object terminated by ``\\n``, the
daemon answers with one JSON object and closes. Requests: ``{"cmd": "toggle"|"show"|"hide"|
"refresh"|"reload"|"ping"|"context"|"edit-mode"|"search-mode"}``. Replies: ``{"ok": true, ...}`` or
``{"ok": false, "error": "..."}``. ``context`` answers with the part of the resolved context the
CLI needs to pick a sheet; it stays small on purpose (the reply limit is 4096 bytes).

This module holds the path, the encoding and the blocking client. The server side lives in the
daemon because it needs the GLib main loop.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

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
MAX_MESSAGE = 4096


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        runtime = f"/tmp/wayhint-{os.getuid()}"  # noqa: S108 - fallback only, dir is created 0700
        os.makedirs(runtime, mode=0o700, exist_ok=True)
    return Path(runtime) / "wayhint.sock"


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
    if cmd not in COMMANDS:
        return {"ok": False, "error": f"unknown command: {cmd!r}"}
    try:
        result = dispatch(cmd) or {}
    except Exception as e:  # never let a handler kill the daemon's socket loop
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
    if cmd not in COMMANDS:
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
