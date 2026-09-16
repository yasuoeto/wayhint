# wayhint — Design

設計書 §12–§14, §45, §50–§59 を元に、決まっている範囲だけを書く。未決は「未決」と明記する。

## Overview

常駐 daemon(`wayhintd`)が GTK4 + gtk4-layer-shell の overlay window を1つ保持し、CLI
(`wayhint toggle|show|hide|refresh|validate`)から Unix domain socket 経由で操作される。
compositor の keybinding(labwc rc.xml / wayfire.ini)が `wayhint toggle` を実行する。show 時に context を1回解決し、一致した
sheet(+ 親sheetのtag絞り込み)を描画する。

```text
compositor keybind ─→ wayhint toggle ─(unix socket)─→ wayhintd
                                                        │ show/refresh
                                                        ▼
                                              ContextResolver
                     WaylandContextProvider(foreign-toplevel)→ HerdrContextProvider
                     (fallback: WayfireContextProvider)
                                                        │ ResolvedContext
                                                        ▼
                                                 HintWindow(layer-shell overlay)
```

## Architecture

- **adapter隔離**: pywayland を呼ぶのは `context/wayland.py` と `context/workspace.py` だけ、PyWayfire を呼ぶのは
  `context/wayfire.py` だけ、`herdr` CLI を呼ぶのは `context/herdr.py` だけ。他モジュールからの直接呼び出しは禁止。
- **一方向依存**: `ui/` は `ResolvedContext` と sheet データのみを受け取る。UI から
  compositor/Herdr へ問い合わせない。
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
  cli.py                          `wayhint validate|toggle|show|hide|refresh|reload|ping`
  daemon.py                       `wayhintd`: Gtk.Application、UDS server、Gio.FileMonitor(debounce)
  config.py                       global config(overlay/appearance/editor/nested/context/search/logging)
  models.py                       Hint, HintSheet, MatchRule, DisplayConfig, Size, Margin,
                                  ResolvedContext, ProcessInfo, OutputInfo, SourceLocation
  yaml_store.py                   ruamel.yaml load、行番号、validation(Issue)、SheetStore(last-known-good)
  matcher.py                      app_id / argv / cmdline regex matching、priority → specificity → file order
  selection.py                    parent tag filter、favorite/category sort、search
  context/base.py                 DesktopContextProvider / NestedContextProvider(Protocol)
  context/resolver.py             ContextResolver(§56 の流れ、output 優先順位)
  context/wayland.py              pywayland 隔離: wlr-foreign-toplevel で active toplevel/output、activate
  context/_wlr_foreign_toplevel.py  生成物(protocols/*.xml → scripts/gen-protocol)
  context/wayfire.py              PyWayfire 隔離(optional backend): focused view/output、set_focus
  context/select.py               `context.backend` auto|wayland|wayfire の選択と auto fallback
  context/workspace.py            pywayland 隔離: ext-workspace-v1 で active workspace 監視、toggle/切替の判定
  context/herdr.py                herdr CLI 隔離: pane current → process-info --pane
  context/process.py              ProcessInfo 正規化
  ui/geometry.py                  anchor → layer-shell edges + margin、px/% 解決(純粋、テスト対象)
  i18n.py                         UI 文字列カタログ(en/ja)、locale 検出(純粋、テスト対象)
  ui/window.py, ui/style.py       HintWindow(list/detail/search/toolbar)、CSS
  editor.py                       placeholder 置換 + Popen(shell=False)
  clipboard.py                    GDK clipboard
  ipc.py                          socket path、JSON encode/decode、client、handle_request
```

設計書 §53 の `matcher/` `ui/hint_list.py` 等は実装量が少ないため上記に統合した。

## Data model

- `Hint`: `id`, `title`(必須); `kind`, `key`, `command`, `category`, `tags`, `favorite`,
  `copy`, `remark`, `source`, `learned`; `location: SourceLocation(file, line)`。
- `HintSheet`: `version`, `id`, `title`, `priority`, `match: MatchRule`, `display: DisplayConfig`
  (部分指定、global から継承), `inherit.parent_tags`, `hints: list[Hint]`, `path`。
- `MatchRule`: `wayland.app_id_regex[]`(旧綴り `wayfire` も読む), `process.argv_regex[]`, `process.cmdline_regex[]`。
- `ResolvedContext`: `desktop_app`, `desktop_title`, `output: OutputInfo(name, width, height)`,
  `view_ref`(検索後の focus 復帰先。backend 固有の不透明文字列), `parent_context`(親sheet id),
  `foreground_process: ProcessInfo | None`, `active_sheet`, `error`(desktop context 取得不可時の表示文)。
- `ProcessInfo`: `pid`, `name`, `argv`, `cmdline`, `cwd`。
- 設定ファイル: `$XDG_CONFIG_HOME/wayhint/config.yaml`, `style.css`, `hints/*.yaml`(`.yml` も可、
  ファイル名順に読む)。schema は設計書 §21, §43 を元に Phase 1 で確定(DECISIONS 0006)。

### config.yaml(実装: `config.py`)

```yaml
overlay:    {anchor: top-right, width: 420px, height: 60%, margin: {top: 24, right: 24}, output: null}
appearance: {style: style.css, show_category: true, language: auto}   # language: auto(locale) | en | ja
editor:     {command: [gvim, --remote-silent, "+{line}", "{file}"]}
nested:     {parent_tags: []}
context:    {live_update: false, backend: auto, workspace: current}  # backend: auto|wayland|wayfire
                                                                     # workspace: current|all
search:     {max_results: 50}
logging:    {level: warning}
```

- 全項目任意、ファイル自体も無くてよい(上記が既定値)。未知の section / key は error。
- size: 整数(px)、`"420px"`、`"30%"`(0–100)。margin: 整数(全辺)か `{top,right,bottom,left}`。
- `editor.command` は argv list。placeholder は `{file}` `{line}` `{hint_id}` のみ、`{file}` 必須。
  未知の `{...}` は error。展開は文字列置換のみで shell を通らない。

### hints/*.yaml(実装: `yaml_store.py`)

```yaml
version: 1              # 任意、1 のみ
id: claude              # 必須 ^[A-Za-z0-9][A-Za-z0-9._-]*$、全 sheet で一意
title: Claude Code      # 必須
priority: 10            # 任意 int、既定 0
match:
  wayland: {app_id_regex: [...]}                       # 旧綴り wayfire: も同義
  process: {argv_regex: [...], cmdline_regex: [...]}   # Python re でコンパイルできること
display: {anchor, width, height, margin, output}       # 部分指定、global overlay から継承
inherit: {parent_tags: [terminal, ai]}                 # 省略時は global nested.parent_tags
hints:
  - {id, title,            # 必須。id は sheet 内で一意
     kind: shortcut|command|tip|note, key, command, category, tags: [], favorite: false,
     copy, remark, source, learned}
```

- 各 hint の `location` は list 要素の開始行(1-based)。`learned` の日付は ISO 文字列に正規化。
- validation は 1 ファイル内の問題を全部集めて `Issue(file, line, message)` で返す。1 つでも
  あれば sheet は採用しない。`SheetStore` は採用済みの sheet を保持し(last-known-good)、次に
  clean に parse できた時だけ置き換える。

## Interfaces

- **CLI ↔ daemon**: Unix domain socket `$XDG_RUNTIME_DIR/wayhint.sock`。ネットワーク socket は
  使わない。メッセージ形式は未決(1行テキスト or JSON、実装時に決めて DECISIONS へ)。
- **Wayland (既定)**: `wlr-foreign-toplevel-management-unstable-v1`(pywayland、呼び出し毎に接続)。
  取得: activated な toplevel の app_id / title / output(wl_output v4 の name、mode ÷ scale)。
  focus 復帰は `activate(seat)`。handle は接続をまたげないので `view_ref = "<app_id>\t<title>"` を
  再解決する(完全一致 → app_id 単一一致 → 諦める)。focused output は protocol に無く、
  output が 1 枚のときだけ埋める。
- **Wayfire (fallback / 明示)**: PyWayfire(IPC plugin 必須)。取得: active view, その output,
  app-id, title。focus 復帰は `set_focus`。`context.backend: auto` では foreign-toplevel が無く
  `WAYFIRE_SOCKET` がある場合だけ使う。
- **workspace**: `ext-workspace-v1`(pywayland)。どこかの workspace で overlay が開いている間だけ
  接続し、manager の `done` ごとに active workspace を再計算する。接続の fd は daemon が GLib main
  loop に載せ、読めるようになったら `flush → read → dispatch` で socket を空にする
  (`dispatch` だけでは socket を読まず fd が readable のままになり、watch が回り続ける)。
  polling は無い。daemon は workspace key → `ResolvedContext` の dict を持ち、切り替え時に
  その workspace の分だけ出し直す。
- **Herdr**: `herdr pane current`, `herdr pane process-info --pane <id>`。出力形式は実機で確認
  し、adapter 内部で吸収する。
- **editor**: `editor.command` argv の `{file}` `{line}` `{hint_id}` を置換して `Popen`。
- **layer-shell**: layer overlay, exclusive_zone 0, keyboard_mode none(検索中のみ
  on_demand/exclusive)。anchor 名(9種)→ layer-shell anchor + margin へ変換。

## Failure modes

| 状況 | 振る舞い |
|---|---|
| desktop context 不可(protocol 無し・IPC 不可) | overlay に error 表示。crash しない |
| Herdr 不可 / pane 取得失敗 | desktop context(Herdr sheet)まで fallback |
| foreground process 不明 | Herdr hints のみ。screen scraping で推測しない |
| sheet YAML が invalid | last-known-good を表示し続け `⚠ YAML error`(file/line/error)を表示。修正で自動復帰 |
| editor 不在 / 起動失敗 | GUI で error 表示 |
| 検索終了時 focus 復帰失敗 | それでも keyboard_mode は必ず none に戻す(grab 残留禁止) |

## Testing strategy

- **unit**(§66): YAML parse、schema validation、size parse、% 変換、anchor 変換、app/process
  matcher、match priority、parent tag filter、favorite sort、search、editor argv 展開、
  source line mapping。
- **context tests**(§67, §68): mock desktop provider(Inkscape/Chromium/Herdr)、mock Herdr process-info
  (bash/claude/codex/`node /path/to/codex`)。nested: Herdr+Claude → Claude sheet + tag 交差の
  Herdr hints。favorite は影響しない。
- **実機**(§69–§73): 自動化しない。下の手動チェックリストで確認する。
- `./scripts/check` が unit/context tests を実行する唯一の入口。GTK/pywayland/PyWayfire 依存の import は
  テストから分離し、ヘッドレスでも通るようにする。

### 実機チェックリスト(§69–§73、手動)

`./scripts/check` の対象外。GTK と compositor が要るため自動化しない。labwc と Wayfire の
それぞれのセッションで実施し、**結果は `STATUS.md` に日付付きで記録する**。この一覧は項目の
定義だけを持ち、合否は持たない。同じ項目でも compositor ごとに結果が変わるため、記録先を
1 か所に寄せる。

- T1 hotkey で右上に表示、元アプリへの入力が続く(keyboard grab なし)
- T2 同じ hotkey で非表示(toggle)
- T3 別 output 上のアプリから起動 → そのアプリの output に出る
- T4 sheet の `display.output` override が効く
- T5 `width: 30%` / `height: 60%` が対象 output の logical size 基準
- T6 検索中だけ入力を受け、完了 / Esc 後に grab が残らず前の view に focus が戻る
- T7 シートを編集で editor が sheet を開く、ヒントを編集で該当行に jump
- T8 Herdr で bash → Herdr hints、`claude` → Claude sheet + tag 付き Herdr hints
- T9 Herdr で unknown process → Herdr hints のみ
- T10 表示中に YAML を編集 → 閉じずに更新
- T11 YAML を壊す → crash せず last-known-good + `⚠ YAML error`、直すと復帰

## Known limits and future work

- V1 の限界は PRODUCT.md「Out of scope」のとおり。
- **workspace をまたいだ表示**: layer surface は output に属し workspace を持たないため、overlay は
  何もしなければ workspace 切り替えをまたいで表示され続ける。`context.workspace: current`(既定)は
  `ext_workspace_manager_v1` で active workspace を監視し、overlay を workspace 単位で開閉する
  (DECISIONS 0012)。
  **Wayfire は未対応**。protocol を出すかどうかは実機が無く未確認で、確認できないものを対応とは
  書かない。protocol が無い compositor では監視せず、従来どおり全 workspace に表示する。
- 拡張余地(§76、V1 には含めない): アプリ内部 mode(Vim/shell)、SSH remote、tmux pane、
  terminal title detector、AI agent lifecycle state、context 別 styling、usage frequency、
  recently learned、explicit executable flag 付き command 実行。
- 実装順序は設計書 §79 の Phase 1–9。Phase 1(config loader / YAML model / validation)から
  始め、Phase 0 として §78 の依存確認を行う。
