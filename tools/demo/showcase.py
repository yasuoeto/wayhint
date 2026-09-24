"""One showcase is one video's worth of material, in one directory.

A showcase is what the *viewer* is shown -- Herdr, a terminal, a GUI application -- not an
internal grouping. Its identity is the directory name; the files inside are found by the role
at the end of their name, so the leading number is free to say what order a person works
through them in (DECISIONS 0032)::

    demo/showcases/herdr/
      01_herdr_storyboard.md      what the video argues, and why (a person writes this)
      01_herdr_storyboard.ja.md   the same in Japanese, checked against the Japanese captions
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

from tools.demo import names

ROLES = {"storyboard": (".md",), "scenario": (".yaml", ".yml")}
NAME = re.compile(r"^(?P<number>\d+)_(?P<showcase>.+)_(?P<role>[a-z][a-z-]*)$")
LANGUAGE = re.compile(r"^(?P<stem>.+)\.(?P<language>[a-z]{2})$")
"""A storyboard written in another language than English names it before the suffix:
``01_herdr_storyboard.ja.md``. One without is English, the language of the repository."""
DEFAULT_LANGUAGE = "en"
OUT = "out"


class ShowcaseError(Exception):
    """A showcase that cannot be recorded. The message says which directory and what is wrong."""


@dataclass(frozen=True)
class Showcase:
    name: str
    root: Path
    scenario: Path
    storyboards: dict[str, Path] = field(default_factory=dict)  # language -> storyboard
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def storyboard(self) -> Path | None:
        """The English storyboard, or the only one there is."""
        if DEFAULT_LANGUAGE in self.storyboards:
            return self.storyboards[DEFAULT_LANGUAGE]
        return next(iter(self.storyboards.values()), None)

    def out(self, language: str, variant: str) -> Path:
        return self.root / OUT / language / variant


def discover(root: Path) -> list[Showcase]:
    """Every showcase under ``demo/showcases``, by name. Unreadable ones are left out."""
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not names.is_name(entry.name):
            continue
        try:
            found.append(load(root, entry.name))
        except ShowcaseError:
            continue
    return found


def load(root: Path, name: str) -> Showcase:
    """The showcase called ``name``, with its files resolved by role."""
    try:
        names.validate_name("showcase name", name)
    except names.BadName:
        raise ShowcaseError(
            f"{name!r} is not a showcase name: lower-case letters, digits and hyphens only"
        ) from None
    directory = root / name
    if not directory.is_dir():
        known = ", ".join(p.name for p in sorted(root.iterdir()) if p.is_dir()) or "none"
        raise ShowcaseError(f"no showcase {name!r} in {root} (there is: {known})")
    by_role: dict[str, list[Path]] = {role: [] for role in ROLES}
    storyboards: dict[str, list[Path]] = {}
    warnings: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        stem, language = path.stem, DEFAULT_LANGUAGE
        suffixed = LANGUAGE.match(stem)
        if suffixed is not None:
            stem, language = suffixed.group("stem"), suffixed.group("language")
        match = NAME.match(stem)
        if match is None:
            continue
        role = match.group("role")
        if role not in ROLES or path.suffix not in ROLES[role]:
            continue
        if suffixed is not None and role != "storyboard":
            continue  # one scenario for every language: the captions carry the languages
        if match.group("showcase") != name:
            warnings.append(
                f"{path.name}: the name says {match.group('showcase')!r} but the directory is "
                f"{name!r}; rename it to {match.group('number')}_{name}_{role}{path.suffix}"
            )
        if role == "storyboard":
            storyboards.setdefault(language, []).append(path)
        else:
            by_role[role].append(path)
    claims = {**by_role, **{f"storyboard ({lang})": ps for lang, ps in storyboards.items()}}
    for role, paths in claims.items():
        if len(paths) > 1:
            both = ", ".join(p.name for p in paths)
            raise ShowcaseError(f"{directory}: two files claim the {role} role ({both})")
    if not by_role["scenario"]:
        raise ShowcaseError(
            f"{directory}: no scenario; it needs a file named <NN>_{name}_scenario.yaml"
        )
    return Showcase(
        name=name,
        root=directory,
        scenario=by_role["scenario"][0],
        storyboards={lang: paths[0] for lang, paths in sorted(storyboards.items())},
        warnings=tuple(warnings),
    )
