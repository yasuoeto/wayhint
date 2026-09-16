# wayhint — Design

設計書 §12–§14, §45, §50–§59 を元に、決まっている範囲だけを書く。未決は「未決」と明記する。

## Overview

常駐 daemon(`wayhintd`)が GTK4 + gtk4-layer-shell の overlay window を1つ保持し、CLI
(`wayhint toggle|show|hide|refresh|validate`)から Unix domain socket 経由で操作される。
Wayfire の keybinding が `wayhint toggle` を実行する。show 時に context を1回解決し、一致した
sheet(+ 親sheetのtag絞り込み)を描画する。

```text
Wayfire keybinding ─→ wayhint toggle ─(unix socket)─→ wayhintd
                                                        │ show/refresh
                                                        ▼
                                              ContextResolver
                                    WayfireContextProvider → HerdrContextProvider
                                                        │ ResolvedContext
                                                        ▼
                                                 HintWindow(layer-shell overlay)
```

## Architecture

- **adapter隔離**: PyWayfire を呼ぶのは `context/wayfire.py` だけ、`herdr` CLI を呼ぶのは
  `context/herdr.py` だけ。他モジュールからの直接呼び出しは禁止。
- **一方向依存**: `ui/` は `ResolvedContext` と sheet データのみを受け取る。UI から
  Wayfire/Herdr へ問い合わせない。
- **snapshot**: context は show/refresh 時に解決して固定。live update は設定項目だけ用意し
  V1では常に false。
- **event-driven**: idle polling なし。file 監視は Gio.FileMonitor。
- **plugin system は作らない**: `NestedContextProvider` interface だけ用意し、V1 実装は
  `HerdrContextProvider` のみ。将来 Tmux/SSH/EditorMode を同 interface で追加できる。

## Modules

設計書 §53 の layout を `wayhint` に読み替えたもの。責務境界の目安であり、実装量が少なければ統合
してよい(過剰分割禁止)。

```text
src/wayhint/
  app.py / daemon.py / cli.py     GTK app 起動、socket server、CLI entry
  config.py                       global config(overlay/appearance/editor/nested/context/search/logging)
  models.py                       Hint, HintSheet, MatchRule, DisplayConfig, EditorConfig,
                                  ResolvedContext, ProcessInfo, SourceLocation
  yaml_store.py                   ruamel.yaml による load、行番号保持、validation、last-known-good
  context/base.py                 NestedContextProvider interface
  context/resolver.py             ContextResolver(§56 の流れ)
  context/wayfire.py              PyWayfire 隔離: active view/output, app-id, title, output名
  context/herdr.py                herdr CLI 隔離: focused pane → process-info → ProcessInfo
  context/process.py              ProcessInfo 正規化(name/argv/cmdline/basename)
  matcher/app.py, matcher/process.py   app_id / argv / cmdline regex matching と優先順位
  ui/window.py, hint_list.py, hint_row.py, detail.py, search.py, style.py
  editor.py                       placeholder 置換 + Popen(shell=False)
  clipboard.py                    GDK clipboard
  ipc.py                          $XDG_RUNTIME_DIR/wayhint.sock
```

## Data model

- `Hint`: `id`, `title`(必須); `kind`, `key`, `command`, `category`, `tags`, `favorite`,
  `copy`, `remark`, `source`, `learned`; `location: SourceLocation(file, line)`。
- `HintSheet`: `version`, `id`, `title`, `priority`, `match: MatchRule`, `display: DisplayConfig`
  (部分指定、global から継承), `inherit.parent_tags`, `hints: list[Hint]`, `path`。
- `MatchRule`: `wayfire.app_id_regex[]`, `process.argv_regex[]`, `process.cmdline_regex[]`。
- `ResolvedContext`: `desktop_app`, `desktop_title`, `output`, `parent_context`(親sheet id),
  `foreground_process: ProcessInfo | None`, `active_sheet`。
- `ProcessInfo`: `pid`, `name`, `argv`, `cmdline`, `cwd`。
- 設定ファイル: `~/.config/wayhint/config.yaml`, `style.css`, `hints/*.yaml`。schema は設計書
  §21, §43 のとおり(変更は DECISIONS に記録)。

## Interfaces

- **CLI ↔ daemon**: Unix domain socket `$XDG_RUNTIME_DIR/wayhint.sock`。ネットワーク socket は
  使わない。メッセージ形式は未決(1行テキスト or JSON、実装時に決めて DECISIONS へ)。
- **Wayfire**: PyWayfire(IPC plugin 必須)。取得: active view, その output, app-id, title。
  focus 復帰にも使う(安全に可能な場合のみ)。
- **Herdr**: `herdr pane current`, `herdr pane process-info --pane <id>`。出力形式は実機で確認
  し、adapter 内部で吸収する。
- **editor**: `editor.command` argv の `{file}` `{line}` `{hint_id}` を置換して `Popen`。
- **layer-shell**: layer overlay, exclusive_zone 0, keyboard_mode none(検索中のみ
  on_demand/exclusive)。anchor 名(9種)→ layer-shell anchor + margin へ変換。

## Failure modes

| 状況 | 振る舞い |
|---|---|
| Wayfire IPC 不可 | overlay に error 表示。crash しない |
| Herdr 不可 / pane 取得失敗 | desktop context(Herdr sheet)まで fallback |
| foreground process 不明 | Herdr hints のみ。screen scraping で推測しない |
| sheet YAML が invalid | last-known-good を表示し続け `⚠ YAML error`(file/line/error)を表示。修正で自動復帰 |
| editor 不在 / 起動失敗 | GUI で error 表示 |
| 検索終了時 focus 復帰失敗 | それでも keyboard_mode は必ず none に戻す(grab 残留禁止) |

## Testing strategy

- **unit**(§66): YAML parse、schema validation、size parse、% 変換、anchor 変換、app/process
  matcher、match priority、parent tag filter、favorite sort、search、editor argv 展開、
  source line mapping。
- **context tests**(§67, §68): mock Wayfire(Inkscape/Chromium/Herdr)、mock Herdr process-info
  (bash/claude/codex/`node /path/to/codex`)。nested: Herdr+Claude → Claude sheet + tag 交差の
  Herdr hints。favorite は影響しない。
- **実機**(§69–§73): 自動化しない。README のチェックリストとして残し、Phase 9 で手動確認。
- `./scripts/check` が unit/context tests を実行する唯一の入口。GTK/Wayfire 依存の import は
  テストから分離し、ヘッドレスでも通るようにする。

## Known limits and future work

- V1 の限界は PRODUCT.md「Out of scope」のとおり。
- 拡張余地(§76、V1 には含めない): アプリ内部 mode(Vim/shell)、SSH remote、tmux pane、
  terminal title detector、AI agent lifecycle state、context 別 styling、usage frequency、
  recently learned、explicit executable flag 付き command 実行。
- 実装順序は設計書 §79 の Phase 1–9。Phase 1(config loader / YAML model / validation)から
  始め、Phase 0 として §78 の依存確認を行う。
