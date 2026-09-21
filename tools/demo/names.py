"""The one rule for every name that becomes part of a path under ``out/``.

Showcase names, variant names and step ids all end up as directory or file names, and they
arrive from two untrusted places: the scenario file and the command line (DECISIONS 0032's
threat model). One spelling of the rule, in one place, so that a name cannot be accepted by
the parser and refused by the recorder -- or the other way round.
"""

from __future__ import annotations

import re

NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
"""Lower-case letters, digits and hyphens. Matched with ``fullmatch``: a trailing newline is
not a name, and ``re.match`` would have accepted one."""


class BadName(ValueError):
    """A name that is not safe to put in a path. The message says which name and why."""


def is_name(value: object) -> bool:
    return isinstance(value, str) and NAME.fullmatch(value) is not None


def validate_name(kind: str, value: object) -> str:
    """``value`` if it is a name, else :class:`BadName` naming what it was meant to be."""
    if not is_name(value):
        raise BadName(
            f"{value!r} has to be lower-case letters, digits and hyphens "
            f"(it is a {kind} and becomes part of a file name)"
        )
    return str(value)
