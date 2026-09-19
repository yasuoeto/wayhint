"""JSON Schema for hint sheets, generated from the validation rules in :mod:`wayhint.yaml_store`.

``wayhint schema`` writes this for an editor's yaml-language-server. It is deliberately *weaker*
than the runtime validation: a schema can describe shapes, not relationships. Everything that
needs to look at more than one node -- hint ids unique inside a sheet, sheet ids unique across
files, whether a regex compiles, whether an anchor name and a size make sense together -- stays
in :func:`wayhint.yaml_store.parse_sheet` only. The test that matters is one-directional: what
validation accepts, the schema accepts too.

Pure module: constants in, ``dict`` out. No I/O, no GTK.
"""

from __future__ import annotations

from typing import Any

from wayhint.models import ANCHORS, HINT_KINDS
from wayhint.yaml_store import _HINT_KEYS, _ID_RE, _SHEET_KEYS, SHEET_VERSION

SCHEMA_ID = "https://wayhint.invalid/schema/hint-sheet.json"


def _nullable(*types: str) -> dict[str, Any]:
    return {"type": [*types, "null"]}


def _scalar() -> dict[str, Any]:
    """A text field as validation takes it: ``key: 5`` is kept as ``"5"`` by ``_opt_str``.

    Numbers are in the type list for that reason only. Widening the schema is the one way to
    keep this file's rule -- what validation accepts, the schema accepts -- without making an
    unquoted digit an error in the editor while the daemon loads it happily.
    """
    return _nullable("string", "number")


def _regex_list(title: str) -> dict[str, Any]:
    return {"title": title, "type": ["array", "null"], "items": {"type": "string"}}


def _hint_properties() -> dict[str, Any]:
    props: dict[str, Any] = {
        "id": {"type": "string", "pattern": _ID_RE.pattern},
        "title": {"type": "string", "minLength": 1},
        "kind": {"enum": list(HINT_KINDS)},
        "tags": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}},
        "favorite": {"type": "boolean"},
        # ``learned: 2026-09-18`` parses as a YAML date; both spellings are accepted.
        "learned": {"type": ["string", "number", "null"], "format": "date"},
    }
    for key in ("key", "command", "category", "copy", "remark", "source"):
        props[key] = _scalar()
    missing = set(_HINT_KEYS) - set(props)
    assert not missing, f"hint key(s) missing from the schema: {sorted(missing)}"
    return props


def _match_schema() -> dict[str, Any]:
    desktop = {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {"app_id_regex": _regex_list("app_id patterns")},
    }
    return {
        "type": ["object", "null"],
        "additionalProperties": False,
        "properties": {
            "wayland": desktop,
            "wayfire": desktop,  # pre-0010 spelling, still accepted
            "process": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "properties": {
                    "argv_regex": _regex_list("argv patterns"),
                    "cmdline_regex": _regex_list("cmdline patterns"),
                },
            },
        },
    }


def json_schema() -> dict[str, Any]:
    """The schema document. ``additionalProperties: false`` mirrors "unknown key is an error"."""
    properties: dict[str, Any] = {
        "version": {"const": SHEET_VERSION},
        "id": {"type": "string", "pattern": _ID_RE.pattern},
        "title": {"type": "string", "minLength": 1},
        "priority": {"type": "integer"},
        "match": _match_schema(),
        "display": {
            "type": ["object", "null"],
            "properties": {
                "anchor": {"enum": list(ANCHORS)},
                "width": {"type": ["integer", "string"]},
                "height": {"type": ["integer", "string"]},
                "margin": {"type": ["integer", "object"]},
                "output": _nullable("string"),
            },
        },
        "inherit": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {"parent_tags": {"type": ["array", "null"], "items": {"type": "string"}}},
        },
        "hints": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "title"],
                "properties": _hint_properties(),
            },
        },
    }
    missing = set(_SHEET_KEYS) - set(properties)
    assert not missing, f"sheet key(s) missing from the schema: {sorted(missing)}"
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "wayhint hint sheet",
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "title"],
        "properties": properties,
    }
