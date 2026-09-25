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
    "Copy": "Copy",
    "Edit in editor": "Edit in editor",
    "Close": "Close",
    "search hints…": "search hints…",
    "no matching sheet": "no matching sheet",
    "no sheet to edit": "no sheet to edit",
    "YAML error": "YAML error",
    "… and {n} more": "… and {n} more",
    "copies": "copies",
    "tags": "tags",
    "source": "source",
    "learned": "learned",
    "file": "file",
    # --- edit mode (Phase 7c) ---
    "Edit": "Edit",
    "Save": "Save",
    "Cancel": "Cancel",
    "Title": "Title",
    "Kind": "Kind",
    "Key": "Key",
    "Command": "Command",
    "Category": "Category",
    "Remark": "Remark",
    "New hint": "New hint",
    "inbox": "inbox",
    "a new sheet": "a new sheet",
    "a add · Enter edit · dd delete · u undo · f favorite · J/K move · Esc leave": (
        "a add · Enter edit · dd delete · u undo · f favorite · J/K move · Esc leave"
    ),
    "c copy and leave · Enter/Esc leave · ↓ list · Tab category": (
        "c copy and leave · Enter/Esc leave · ↓ list · Tab category"
    ),
    "Enter save and leave · Esc discard · Tab next field · Ctrl+P parent sheet": (
        "Enter save and leave · Esc discard · Tab next field · Ctrl+P parent sheet"
    ),
    "press d again to delete {title}": "press d again to delete {title}",
    "deleted {id}": "deleted {id}",
    "nothing to undo": "nothing to undo",
    "restored {id}": "restored {id}",
    "saved {id}": "saved {id}",
    "title is required": "title is required",
    "cannot edit while the YAML is broken": "cannot edit while the YAML is broken",
    "no hint selected": "no hint selected",
    "that sheet is gone": "that sheet is gone",
    "cannot move past another group": "cannot move past another group",
    "generic process name: check the match rule": ("generic process name: check the match rule"),
    "filter: {query}": "filter: {query}",
    "finish editing before searching": "finish editing before searching",
}

JA: dict[str, str] = {
    "Search": "検索",
    "Done": "完了",
    "Copy": "コピー",
    "Edit in editor": "エディタで編集",
    "Close": "閉じる",
    "search hints…": "ヒントを検索…",
    "no matching sheet": "該当するシートなし",
    "no sheet to edit": "編集するシートがありません",
    "YAML error": "YAML エラー",
    "… and {n} more": "… 他 {n} 件",
    "copies": "コピー内容",
    "tags": "タグ",
    "source": "出典",
    "learned": "習得日",
    "file": "ファイル",
    # --- 編集モード (Phase 7c) ---
    "Edit": "編集",
    "Save": "保存",
    "Cancel": "取消",
    "Title": "タイトル",
    "Kind": "種別",
    "Key": "キー",
    "Command": "コマンド",
    "Category": "カテゴリ",
    "Remark": "補足",
    "New hint": "新しいヒント",
    "inbox": "未定義",
    "a new sheet": "新しいシート",
    "a add · Enter edit · dd delete · u undo · f favorite · J/K move · Esc leave": (
        "a 追加 · Enter 編集 · dd 削除 · u 取消 · f お気に入り · J/K 並び替え · Esc 終了"
    ),
    "c copy and leave · Enter/Esc leave · ↓ list · Tab category": (
        "c コピーして戻る · Enter/Esc 戻る · ↓ 一覧へ · Tab 分類"
    ),
    "Enter save and leave · Esc discard · Tab next field · Ctrl+P parent sheet": (
        "Enter 保存して終了 · Esc 破棄 · Tab 次の欄 · Ctrl+P 親シート"
    ),
    "press d again to delete {title}": "もう一度 d で「{title}」を削除",
    "deleted {id}": "{id} を削除しました",
    "nothing to undo": "取り消せる削除がありません",
    "restored {id}": "{id} を戻しました",
    "saved {id}": "{id} を保存しました",
    "title is required": "タイトルは必須です",
    "cannot edit while the YAML is broken": "YAML が壊れている間は編集できません",
    "no hint selected": "ヒントが選択されていません",
    "that sheet is gone": "対象のシートがありません",
    "cannot move past another group": "別のグループを越える移動はできません",
    "generic process name: check the match rule": (
        "汎用的なプロセス名です。match 規則を確認してください"
    ),
    "filter: {query}": "絞り込み: {query}",
    "finish editing before searching": "編集を終えてから検索してください",
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


def resolve_language(language: str = "auto", environ: Mapping[str, str] | None = None) -> str:
    """The language actually used: the setting, or the locale, falling back to ``en``.

    A locale the application has no catalog for is English as far as the interface goes, so it
    has to be English for everything else that follows the language too (hint sheets, 0024).
    """
    lang = detect_language(environ) if language == "auto" else language
    return lang if lang in CATALOGS else "en"


def translator(language: str = "auto", environ: Mapping[str, str] | None = None) -> Translator:
    lang = resolve_language(language, environ)
    catalog = CATALOGS[lang]

    def tr(key: str) -> str:
        return catalog.get(key) or EN.get(key, key)

    return tr
