"""One showcase is one video's worth of material, in one directory.

A showcase is what the *viewer* is shown -- Herdr, a terminal, a GUI application -- not an
internal grouping. Its identity is the directory name; the files inside are found by the role
at the end of their name, so the leading number is free to say what order a person works
through them in (DECISIONS 0032)::

    demo/showcases/herdr/
      01_herdr_storyboard.md      what the video argues, and why (a person writes this)
      02_herdr_scenario.yaml      what the recorder executes
      out/<lang>/<variant>/       results, never committed

The middle part of the file name should be the directory name. When it is not, that is a
warning rather than an error: it is a copied file someone has not finished renaming, and
refusing to record would help nobody. Two files claiming the same role *is* an error, because
there is no way to tell which one was meant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROLES = {"storyboard": (".md",), "scenario": (".yaml", ".yml")}
NAME = re.compile(r"^(?P<number>\d+)_(?P<showcase>.+)_(?P<role>[a-z][a-z-]*)$")
SHOWCASE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
"""A showcase name is a directory name and part of every output file's name."""
OUT = "out"


class ShowcaseError(Exception):
    """A showcase that cannot be recorded. The message says which directory and what is wrong."""


@dataclass(frozen=True)
class Showcase:
    name: str
    root: Path
    scenario: Path
    storyboard: Path | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def out(self, language: str, variant: str) -> Path:
        return self.root / OUT / language / variant


def discover(root: Path) -> list[Showcase]:
    """Every showcase under ``demo/showcases``, by name. Unreadable ones are left out."""
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not SHOWCASE.match(entry.name):
            continue
        try:
            found.append(load(root, entry.name))
        except ShowcaseError:
            continue
    return found


def load(root: Path, name: str) -> Showcase:
    """The showcase called ``name``, with its files resolved by role."""
    if not SHOWCASE.match(name):
        raise ShowcaseError(
            f"{name!r} is not a showcase name: lower-case letters, digits and hyphens only"
        )
    directory = root / name
    if not directory.is_dir():
        known = ", ".join(p.name for p in sorted(root.iterdir()) if p.is_dir()) or "none"
        raise ShowcaseError(f"no showcase {name!r} in {root} (there is: {known})")
    by_role: dict[str, list[Path]] = {role: [] for role in ROLES}
    warnings: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        match = NAME.match(path.stem)
        if match is None:
            continue
        role = match.group("role")
        if role not in ROLES or path.suffix not in ROLES[role]:
            continue
        if match.group("showcase") != name:
            warnings.append(
                f"{path.name}: the name says {match.group('showcase')!r} but the directory is "
                f"{name!r}; rename it to {match.group('number')}_{name}_{role}{path.suffix}"
            )
        by_role[role].append(path)
    for role, paths in by_role.items():
        if len(paths) > 1:
            names = ", ".join(p.name for p in paths)
            raise ShowcaseError(f"{directory}: two files claim the {role} role ({names})")
    if not by_role["scenario"]:
        raise ShowcaseError(
            f"{directory}: no scenario; it needs a file named <NN>_{name}_scenario.yaml"
        )
    return Showcase(
        name=name,
        root=directory,
        scenario=by_role["scenario"][0],
        storyboard=by_role["storyboard"][0] if by_role["storyboard"] else None,
        warnings=tuple(warnings),
    )
