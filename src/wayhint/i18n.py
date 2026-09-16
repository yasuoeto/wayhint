"""UI strings. Pure module: no GTK.

Language comes from the machine's locale (``LC_ALL`` → ``LC_MESSAGES`` → ``LANG``, the POSIX
precedence) unless ``appearance.language`` in config.yaml names one. Unknown languages fall back
to English; a missing key in a catalog falls back to the English text.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

Translator = Callable[[str], str]

EN: dict[str, str] = {
    "Search": "Search",
    "Done": "Done",
    "Refresh": "Refresh",
    "Copy": "Copy",
    "Edit hint": "Edit hint",
    "Edit sheet": "Edit sheet",
    "Close": "Close",
    "search hints…": "search hints…",
    "no matching sheet": "no matching sheet",
    "no sheet to edit": "no sheet to edit",
    "YAML error": "YAML error",
    "… and {n} more": "… and {n} more",
    "tags": "tags",
    "source": "source",
    "learned": "learned",
}

JA: dict[str, str] = {
    "Search": "検索",
    "Done": "完了",
    "Refresh": "更新",
    "Copy": "コピー",
    "Edit hint": "ヒントを編集",
    "Edit sheet": "シートを編集",
    "Close": "閉じる",
    "search hints…": "ヒントを検索…",
    "no matching sheet": "該当するシートなし",
    "no sheet to edit": "編集するシートがありません",
    "YAML error": "YAML エラー",
    "… and {n} more": "… 他 {n} 件",
    "tags": "タグ",
    "source": "出典",
    "learned": "習得日",
}

CATALOGS: dict[str, Mapping[str, str]] = {"en": EN, "ja": JA}
LANGUAGES = ("auto", *CATALOGS)


def detect_language(environ: Mapping[str, str] | None = None) -> str:
    """Two-letter language code from the locale environment; ``en`` when unset or ``C``."""
    env = os.environ if environ is None else environ
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(var)
        if value:
            code = value.split(".", 1)[0].split("@", 1)[0].split("_", 1)[0].lower()
            return "en" if code in ("c", "posix", "") else code
    return "en"


def translator(language: str = "auto", environ: Mapping[str, str] | None = None) -> Translator:
    lang = detect_language(environ) if language == "auto" else language
    catalog = CATALOGS.get(lang, EN)

    def tr(key: str) -> str:
        return catalog.get(key) or EN.get(key, key)

    return tr
