"""DECISIONS 0039: tags and categories narrow both an include and the nested parent's hints."""

import shutil
import tempfile
import textwrap
import unittest
from dataclasses import replace
from pathlib import Path

from wayhint.config import ConfigError, parse_global_config
from wayhint.models import Hint, HintFilter, HintSheet, IncludeRef, SourceLocation
from wayhint.schema import json_schema
from wayhint.selection import visible_hints
from wayhint.yaml_store import load_sheets


def hint(id_: str, tags=(), category=None) -> Hint:
    return Hint(
        id=id_,
        title=id_,
        location=SourceLocation(Path("x.yaml"), 1),
        tags=tuple(tags),
        category=category,
    )


def ids(hints) -> list[str]:
    return [h.id for h in hints]


class HintFilterTest(unittest.TestCase):
    """What is written is ORed; ``[]`` for either lets nothing through."""

    HINTS = (
        hint("tagged", tags=["daily"]),
        hint("in-cat", category="git"),
        hint("both", tags=["daily"], category="git"),
        hint("neither", tags=["rare"], category="other"),
        hint("bare"),
    )

    def passing(self, **kw) -> list[str]:
        f = HintFilter(**{k: None if v is None else tuple(v) for k, v in kw.items()})
        return ids(h for h in self.HINTS if f.allows(h))

    def test_nothing_written_lets_everything_through(self) -> None:
        self.assertEqual(self.passing(), ids(self.HINTS))

    def test_one_side_written(self) -> None:
        self.assertEqual(self.passing(tags=["daily"]), ["tagged", "both"])
        self.assertEqual(self.passing(categories=["git"]), ["in-cat", "both"])

    def test_both_written_is_or(self) -> None:
        self.assertEqual(
            self.passing(tags=["daily"], categories=["other"]), ["tagged", "both", "neither"]
        )

    def test_a_hint_without_category_matches_no_category(self) -> None:
        self.assertNotIn("bare", self.passing(categories=["git", "other"]))

    def test_empty_list_is_nothing_whatever_the_other_side_says(self) -> None:
        self.assertEqual(self.passing(tags=[]), [])
        self.assertEqual(self.passing(tags=[], categories=["git"]), [])
        self.assertEqual(self.passing(tags=["daily"], categories=[]), [])


class NestedCategoryTest(unittest.TestCase):
    """Categories go through the same first-written-wins rule as tags, on their own (0034)."""

    def setUp(self) -> None:
        self.parent = HintSheet(
            id="herdr",
            title="Herdr",
            path=Path("herdr.yaml"),
            hints=(
                hint("split", tags=["pane"], category="pane"),
                hint("theme", category="ui"),
                hint("quit", category="session"),
            ),
        )
        self.child = HintSheet(id="claude", title="Claude", path=Path("claude.yaml"))

    def shown(self, child=None, parent=None, tags=None, categories=None) -> list[str]:
        child, parent = child or self.child, parent or self.parent
        return ids(visible_hints(child, parent, tags, (), global_parent_categories=categories))

    def test_the_parent_exports_categories(self) -> None:
        parent = replace(self.parent, export_categories=("ui",))
        self.assertEqual(self.shown(parent=parent), ["theme"])

    def test_tags_and_categories_from_different_places_are_ored(self) -> None:
        parent = replace(self.parent, export_tags=("pane",), export_categories=("session",))
        self.assertEqual(self.shown(parent=parent), ["split", "quit"])

    def test_the_child_replaces_the_parent_for_categories_only(self) -> None:
        parent = replace(self.parent, export_tags=("pane",), export_categories=("session",))
        child = replace(self.child, parent_categories=("ui",))
        self.assertEqual(self.shown(child=child, parent=parent), ["split", "theme"])

    def test_the_global_opt_out_is_not_reopened_by_a_category_filter(self) -> None:
        # nested.parent_tags: [] switches parent hints off everywhere (0036).
        parent = replace(self.parent, export_categories=("ui",))
        self.assertEqual(self.shown(parent=parent, tags=[]), [])

    def test_the_global_categories_win_over_the_parent(self) -> None:
        parent = replace(self.parent, export_categories=("ui",))
        self.assertEqual(self.shown(parent=parent, categories=["session"]), ["quit"])


class IncludeFilterTest(unittest.TestCase):
    """An include entry can be ``{sheet, tags, categories}``; plain ids still mean everything."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="wayhint-filter-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.write(
            "git",
            """\
            id: git
            title: Git
            hints:
              - {id: commit, title: Commit, category: daily}
              - {id: bisect, title: Bisect, category: rare}
              - {id: push, title: Push, tags: [remote]}
            """,
        )

    def write(self, name: str, body: str) -> None:
        (self.dir / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")

    def included(self, include: str, global_include=()) -> list[str]:
        self.write("a", f"id: a\ntitle: A\n{include}hints: []\n")
        result = load_sheets(self.dir, global_include=global_include)
        self.assertEqual([i for i in result.issues if i.severity == "error"], [])
        sheet = next(s for s in result.sheets if s.id == "a")
        return [h.id for s in result.includes_for(sheet) for h in s.hints]

    def test_a_plain_id_still_brings_the_whole_sheet(self) -> None:
        self.assertEqual(self.included("include: [git]\n"), ["commit", "bisect", "push"])

    def test_a_mapping_narrows_by_category_or_tag(self) -> None:
        self.assertEqual(
            self.included("include:\n  - {sheet: git, categories: [daily]}\n"), ["commit"]
        )
        self.assertEqual(
            self.included("include:\n  - {sheet: git, categories: [daily], tags: [remote]}\n"),
            ["commit", "push"],
        )

    def test_the_global_include_takes_the_same_shape(self) -> None:
        narrowed = IncludeRef("git", HintFilter(tags=("remote",)))
        self.assertEqual(self.included("", global_include=[narrowed]), ["push"])

    def test_the_included_hints_are_the_originals(self) -> None:
        # Editing a mixed-in hint writes to the file it lives in, so it must keep its location.
        self.write("a", "id: a\ntitle: A\ninclude:\n  - {sheet: git, tags: [remote]}\n")
        result = load_sheets(self.dir)
        a = next(s for s in result.sheets if s.id == "a")
        git = next(s for s in result.sheets if s.id == "git")
        self.assertIs(result.includes_for(a)[0].hints[0], git.hints[2])

    def test_mistakes_are_reported(self) -> None:
        for body in (
            "include:\n  - {tags: [x]}\n",  # no sheet
            "include:\n  - {sheet: git, kinds: [tip]}\n",  # unknown key
            "include:\n  - {sheet: git, categories: daily}\n",  # not a list
        ):
            with self.subTest(body=body):
                self.write("a", f"id: a\ntitle: A\n{body}")
                self.assertTrue(any("include" in i.message for i in load_sheets(self.dir).issues))

    def test_nested_keys_are_read(self) -> None:
        self.write(
            "p",
            "id: p\ntitle: P\nnested: {export_categories: [ui]}\n"
            "inherit: {parent_categories: [x]}\n",
        )
        sheet = next(s for s in load_sheets(self.dir).sheets if s.id == "p")
        self.assertEqual((sheet.export_categories, sheet.parent_categories), (("ui",), ("x",)))


class ConfigTest(unittest.TestCase):
    def test_include_and_parent_categories(self) -> None:
        config = parse_global_config(
            {
                "include": ["wm", {"sheet": "git", "categories": ["daily"]}],
                "nested": {"parent_categories": []},
            }
        )
        self.assertEqual(
            config.include,
            (IncludeRef("wm"), IncludeRef("git", HintFilter(categories=("daily",)))),
        )
        self.assertEqual(config.parent_categories, ())

    def test_mistakes_are_errors(self) -> None:
        for data in (
            {"include": [{"categories": ["x"]}]},
            {"include": [{"sheet": "git", "kinds": ["tip"]}]},
            {"nested": {"parent_categories": "x"}},
        ):
            with self.subTest(data=data), self.assertRaises(ConfigError):
                parse_global_config(data)


class SchemaTest(unittest.TestCase):
    def test_the_schema_knows_the_new_keys(self) -> None:
        props = json_schema()["properties"]
        entry = props["include"]["items"]["oneOf"][1]["properties"]
        self.assertEqual(set(entry), {"sheet", "tags", "categories"})
        self.assertIn("parent_categories", props["inherit"]["properties"])
        self.assertIn("export_categories", props["nested"]["properties"])


if __name__ == "__main__":
    unittest.main()
