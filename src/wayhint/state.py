"""``state.yaml``: what the daemon remembers between runs -- today, one filter per sheet.

Of the three kinds of file (DECISIONS 0033) this is the one only the daemon writes: content is
``hints/`` and settings are ``config.yaml``, both written by a person. It is still read as if a
person could have touched it, because they can: nothing in here may stop the daemon from starting,
and a filter is only ever handed to the substring search, never to a regex, a path or a shell.

Pure functions (:func:`parse_state`, :func:`dump_state`, :func:`sanitize_query`) are split from the
two that touch the disk, so the rules in 0033 E and F are tested without files.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from ruamel.yaml.nodes import MappingNode, Node
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as Quoted

VERSION = 1
MAX_QUERY_LEN = 200  # the search box's max_length, and the longest value read back
MAX_FILTERS = 256
MAX_STATE_BYTES = 64 * 1024
SHEET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "wayhint" / "state.yaml"


def sanitize_query(text: str) -> str:
    """Drop control characters (Unicode ``Cc``). Everything else is a fine thing to search for."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cc")


def _load(text: str) -> object:
    """Safe-load ``text``, a duplicated key keeping its *last* value (0033 E).

    The safe loader refuses duplicate keys by default, and with ``allow_duplicate_keys`` it keeps
    the first one. A hand-edited file is read the way a person reads it, bottom line winning, so
    the two mappings this file has are built here from the composed nodes.
    """
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = True
    node = yaml.compose(text)
    if node is None:
        return None
    return _construct(yaml, node, depth=0)


def _construct(yaml: YAML, node: Node, depth: int) -> object:
    if isinstance(node, MappingNode) and depth < 2:
        out: dict[object, object] = {}
        for key, value in node.value:
            k = yaml.constructor.construct_object(key, deep=True)
            if not isinstance(k, str | int | float | bool):
                k = object()  # a list or a mapping as a key; kept so it is reported, not hashed
            out[k] = _construct(yaml, value, depth + 1)
        return out
    return yaml.constructor.construct_object(node, deep=True)


def parse_state(text: str) -> tuple[dict[str, str], list[str]]:
    """``(filters, warnings)``. A broken file is no filters, never an exception (0033 E).

    Warnings say what was wrong and where, never what the filter said: a filter is whatever
    the user typed, and the log is not the place for it (0033 F).
    """
    try:
        data = _load(text)
    except YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        return {}, [f"not valid YAML{where}"]
    if data is None:
        return {}, []
    if not isinstance(data, dict):
        return {}, ["top level is not a mapping"]
    version = data.get("version")
    if type(version) is not int or version != VERSION:
        return {}, [f"unsupported version (expected {VERSION})"]
    raw = data.get("filters")
    if raw is None:
        return {}, []
    if not isinstance(raw, dict):
        return {}, ["filters is not a mapping"]
    filters: dict[str, str] = {}
    warnings: list[str] = []
    for n, (key, value) in enumerate(raw.items(), start=1):
        if len(filters) >= MAX_FILTERS:
            warnings.append(f"more than {MAX_FILTERS} filters; the rest were dropped")
            break
        if not isinstance(key, str) or not SHEET_ID.fullmatch(key):
            warnings.append(f"filter {n} dropped: not a sheet id")
            continue
        if not isinstance(value, str):
            warnings.append(f"filter {n} dropped: value is not a string")
            continue
        value = sanitize_query(value)
        if len(value) > MAX_QUERY_LEN:
            warnings.append(f"filter {n} dropped: longer than {MAX_QUERY_LEN} characters")
            continue
        if value:
            filters[key] = value
    return filters, warnings


def load_state(path: Path) -> tuple[dict[str, str], list[str]]:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return {}, []
    except OSError as e:
        return {}, [f"cannot read: {e.strerror or e}"]
    if size > MAX_STATE_BYTES:
        return {}, [f"larger than {MAX_STATE_BYTES} bytes"]
    try:
        text = path.read_bytes()[: MAX_STATE_BYTES + 1].decode("utf-8")
    except OSError as e:
        return {}, [f"cannot read: {e.strerror or e}"]
    except UnicodeDecodeError:
        return {}, ["not UTF-8"]
    if len(text.encode("utf-8")) > MAX_STATE_BYTES:  # grew between stat and read
        return {}, [f"larger than {MAX_STATE_BYTES} bytes"]
    return parse_state(text)


def dump_state(filters: dict[str, str]) -> str:
    """The whole file. Values are always double-quoted, so ``"#pane"`` or ``"yes"`` stay strings."""
    yaml = YAML()
    yaml.default_flow_style = False
    out = io.StringIO()
    doc = {"version": VERSION, "filters": {k: Quoted(v) for k, v in filters.items()}}
    yaml.dump(doc, out)
    return out.getvalue()


def save_state(path: Path, filters: dict[str, str]) -> None:
    """Write through a temporary file in the same directory, then rename over the old one.

    Raises ``OSError``; the daemon logs it and keeps the filters in memory (0033 E).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".yaml", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dump_state(filters))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
