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
  models.py の ResolvedContext.target_key()  overlay が何を出しているかの比較キー(title は含めない)
  context/herdr.py                herdr CLI 隔離: pane current → process-info --pane
  context/process.py              ProcessInfo 正規化
  ui/geometry.py                  anchor → layer-shell edges + margin、px/% 解決、
                                  resize_delta(掴んだ角の drag → 新サイズ)(純粋、テスト対象)
  i18n.py                         UI 文字列カタログ(en/ja)、locale 検出(純粋、テスト対象)
  ui/window.py, ui/style.py       HintWindow(list/detail/search/toolbar)、CSS
  editor.py                       edit_target(開く file/line の決定、純粋)、placeholder 置換 + Popen(shell=False)
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
editor:     {command: [gvim, --remote-silent, "+{line}", "{file}"], schema_modeline: false,
             schema_path: ~/.config/wayhint/schema.json}
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
- `editor.schema_modeline`: true なら新規 sheet と format が先頭に
  `# yaml-language-server: $schema=` を付ける(DECISIONS 0014 D6)。
- `editor.schema_path`: モードラインの `$schema=` に書く path。`wayhint schema --write` の
  既定出力先。

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

- `id` と `title` 以外は省略可。GUI / CLI / format が書く hint は 12 項目を null 込みで canonical 順
  (`id` `title` `kind` `key` `command` `category` `tags` `favorite` `copy` `remark` `source`
  `learned`)に出力する。読み込む際は key の順序と省略を問わない(DECISIONS 0014 D2)。
- 表示順: favorite 区画(YAML 記述順、category 無視)→ 非 favorite 区画(**非 favorite の hint だけで
  採番した** category 初出順 → YAML 記述順)。category null は 1 グループとして初出順に入り、
  ラベルは擬似 category(DECISIONS 0014 D7)。
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
  その workspace の分だけ出し直す。overlay の「閉じる」と close-request は daemon の `hide` を
  呼び、その workspace の entry を落とす。`HintWindow.hide_overlay` は surface を隠すだけで、
  workspace 切り替えで隠すときに使う。
- **Herdr**: `herdr pane current`, `herdr pane process-info --pane <id>`。出力形式は実機で確認
  し、adapter 内部で吸収する。
- **editor**: `editor.command` argv の `{file}` `{line}` `{hint_id}` を置換して `Popen`。開く場所は
  `edit_target(sheet, hint)`(純粋、テスト対象)が決める。**hint を選んでいるときは hint の
  `location` が sheet より優先する**: nested 表示では親 sheet の hint が一覧に混ざるため、active
  sheet の file を使うと別ファイルの行番号で開いてしまう。hint が無いときだけ sheet の file:1。
- **layer-shell**: layer overlay, exclusive_zone 0。keyboard_mode は状態から導出する。
  normal = none、search / edit = exclusive。設定箇所は `_sync_keyboard_mode()` の 1 つ。
  anchor 名(9種)→ layer-shell anchor + margin へ変換。
- **手動リサイズ**: layer surface に compositor 側の frame / interactive resize は無いので、
  anchor の反対側に grip を `Gtk.Overlay` で重ね、`Gtk.GestureDrag` で掴む。角
  (`.wayhint-grip-both`、16px)が縦横、自由な 2 辺の帯(`.wayhint-grip-x` / `-y`、6px)が
  幅だけ・高さだけ。帯は動かさない側の delta を 0 にして同じ `resize_delta` に渡す。
  重なる部分は後から `add_overlay` した角が勝つ。drag 中は `set_size_request`、drag 終了で
  daemon が `config.yaml` の
  `overlay.width` / `height` を px で書き戻す(DECISIONS 0018)。pointer だけで完結するので
  keyboard_mode は触らない。サイズ計算は `geometry.resize_delta`(純粋)。

## 編集モード（Phase 7）

DECISIONS 0014 の仕様本文。判断の根拠は 0014 を参照。

### 1. 状態と keyboard_mode

| 状態 | keyboard_mode | 入口 | 出口 |
|---|---|---|---|
| `normal` | NONE | show / toggle | hide、workspace 離脱 |
| `search` | EXCLUSIVE | 検索ボタン、既存の begin_search | Esc、hide、workspace 離脱 |
| `edit` | EXCLUSIVE | IPC `edit-mode`（compositor keybinding）、toolbar ボタン | Esc、hide、workspace 離脱 |

- `keyboard_mode` を直接設定する箇所は `_sync_keyboard_mode()` 1 つに集約し、状態変更のたびに呼ぶ。
  hide / workspace 離脱では状態を保ったまま `NONE` に落とし、show / 復帰で状態に応じて張り直す。
- EXCLUSIVE を使う理由: `ON_DEMAND` では compositor が surface への再クリックまで keyboard focus を
  渡さず、検索ボタンを押しただけでは入力が下のアプリへ行ってしまう（labwc 0.20.2 で確認）。
- `edit` への入場条件: active sheet が last-known-good 表示でないこと（`⚠ YAML error` 中は拒否し理由を表示）。
- `edit` 中の hotkey は hide / show（0013 の例外）。`Esc` が唯一の破棄経路。
- 編集状態（モード、開いているフォーム、フォームの入力値、対象 hint id、追加先 sheet）は workspace ごとの context dict と同じ粒度で保持する。メモリのみ。
- 保存後も `edit` に留まる。

### 2. key 割当（edit 中）

| key | 動作 |
|---|---|
| `a` | quick add フォームを開く |
| `Enter` | 選択 hint の編集フォームを開く |
| `d` `d` | 選択 hint を削除（1 回目で確認表示、2 回目で確定。他の key で取り消し） |
| `u` | 直前に削除した 1 件を元の sheet 末尾に戻す（メモリ保持は 1 件、セッション限り） |
| `f` | favorite toggle |
| `J` / `K` | 画面上の下 / 上の hint と swap（§5 の制約） |
| `↑` `↓` | 選択移動（GTK 既定を使う） |
| `Esc` | フォームが開いていればフォームを閉じる（入力破棄）、開いていなければ `edit` を抜ける |

一覧の単打キーと `Tab` / `Shift+Tab` は CAPTURE フェーズの `EventControllerKey` で受ける（ListBox の
行操作や Tab の focus 移動より先に処理するため）。テキスト欄の `Enter` / `Esc` は input method に先に
渡し、bubble フェーズで受ける（変換の確定・取り消しを奪わないため）。

edit 中は overlay 下部にこの割当を 1〜2 行で表示する（i18n en/ja）。

フォーム内: `Enter` で保存、`Esc` で破棄、`Tab` / `Shift+Tab` で欄移動、`Ctrl+P` で追加先を親 sheet に toggle（quick add のみ）。

### 3. フォーム（quick add / 編集は同じフォーム）

| 欄 | 必須 | 備考 |
|---|---|---|
| title | ✓ | |
| kind | ✓ | `shortcut` / `command` / `tip` / `note`。quick add の既定は `shortcut` |
| key / command | – | kind が決める。`shortcut` → `key`、`command` → `command`、`tip` → **両方**、`note` → **どちらも無し**。tip と note は覚え書き |
| category | – | 空なら null（表示上は擬似 category inbox / 未定義） |
| remark | – | |

- 編集フォームは既存値を prefill。`id` は表示のみ。
- 保存時の自動設定（quick add のみ）: `id`（title の slug、衝突 `-2`…、空なら `q-YYYYMMDD-HHMMSS`）、`learned`（当日）、`favorite: false`、他は null。親 sheet 指定時は `effective_parent_tags` を `tags` に付与。
- 保存前に validation。失敗時はフォーム内にエラーを出し書かない。
- 追加先: active sheet。無ければ §7 で新規作成。混入 hint の編集は所属 sheet に書く。

### 4. 書き戻し（yaml_store）

純粋関数として実装し、GTK / pywayland を import しない。

| 関数 | 内容 |
|---|---|
| `write_document(path, doc)` | tmp（`.yaml` / `.yml` 以外の拡張子、同一ディレクトリ）→ validate → `st_mode` コピー → `os.replace` |
| `build_hint(fields) -> CommentedMap` | 12 項目 canonical 順、未設定 null、`tags` は flow style |
| `append_hint(doc, hint)` | `hints` 末尾に追加 |
| `update_hint(doc, id, fields)` | 該当 hint を canonical 順で再構築。見つからなければ `HintNotFoundError` |
| `delete_hint(doc, id) -> removed` | 直前ブロックコメントも削除。除いた node を返す（undo 用） |
| `swap_hints(doc, id_a, id_b)` | 位置 swap。`ca.items` の直前コメントを付け替える |
| `set_favorite(doc, id, value)` | |
| `ensure_modeline(doc, schema_path)` | 先頭にモードライン。既にあれば何もしない |
| `match_rule_for_context(ctx) -> (match, warning)` | §7。警告は呼び出し側（UI / CLI）が表示する |
| `create_sheet(ctx, first_hint, config, hints_dir=None, existing_ids=(), now=None)` | §7。戻り値 `(path, doc)`。`hints_dir` / `now` は注入用で、既定は `config_dir()/hints` と現在時刻 |
| `normalize_sheet(doc, modeline_path=None)` | format: 全 hint を canonical 順・12 項目化。sheet メタは触らない |
| `slug(text, existing=(), now=None)` | id / ファイル名。衝突は `-2`、生成できなければ `q-YYYYMMDD-HHMMSS` |

例外は `SheetWriteError`（書き込み不能・validation 失敗。`.issues` を持つ）と、その subclass の
`HintNotFoundError`。定数は `CANONICAL_HINT_KEYS` / `DUMP_WIDTH` / `MODELINE_PREFIX`。

読み書きは既存の `read_document` を使い、`_yaml()` に `indent(mapping=2, sequence=4, offset=2)` と
折り返しの起きない `width` を追加する。load / dump で同じ設定を共有する。
canonical 順の 12 項目は Data model「hints/*.yaml」を参照。
`json_schema() -> dict`(validation の定義から生成)は新設 module `schema.py` に置く。

### 5. 表示順と並び替え

表示順は Data model「hints/*.yaml」を参照。ラベルは擬似 category。

`J` / `K` の制約:
- 隣が同グループ（favorite 区画内、または非 favorite 区画で同 category）かつ同 sheet のときだけ swap。
  所属 sheet の同一性は `hint.location.file` で判定する。
- それ以外は何もしない（音や表示は出さない）。
- フィルタ中も可。
- CLI の `move` はグループ跨ぎ・sheet 跨ぎをエラー終了、GUI は無反応（メッセージのみ）。

### 6. 削除と undo

- `d` `d` で確定。確定前に他の key を押したら取り消し。
- 削除した node を 1 件だけメモリに保持。`u` で元の sheet の末尾に append。sheet が消えていればエラー表示。

### 7. sheet の新規作成

- path: `~/.config/wayhint/hints/<slug>.yaml`。slug は app 名 / process 名から。sheet id 衝突時 `-2`。
- 内容: 先頭コメント（生成日時、`desktop_app`、`parent_context`、`foreground_process.name`、採用した regex）、`editor.schema_modeline` が true なら、先頭に `# yaml-language-server: $schema=<editor.schema_path を展開した絶対 path>` を付ける、`id` `title` `priority`（既定）`match` `hints: [first_hint]`。
- `match` の生成:
  - `parent_context is None` → app_id 一致
  - `parent_context` あり、`active_sheet` が親と異なる状況で process により子を作る → `process.argv_regex: ["^<name>$"]`
  - `name` が汎用名（定数 `GENERIC_PROCESS_NAMES`。`matcher.py` に置く）→ `argv[1:]` の basename を候補にする（候補生成は matcher の `process_candidates` / `argv_basenames` と同じ規則）。`-` で始まる引数（オプション）は候補から除く。非汎用の候補が無ければフォームに警告
  - app_id 一致の regex は `re.escape` した完全一致（例 `^org\.inkscape\.Inkscape$`）
  - 警告は `match_rule_for_context` の戻り値で返し、UI / CLI がそれを表示する
- 生成直後の FileMonitor reload で新 sheet が有効になる。

### 8. 同時編集と reload

- 後勝ち。mtime 比較なし。
- 保存時に対象 id が無ければエラー表示、reload に任せる。
- 自己書き込みの reload は抑止しない。`_after_reload` で選択・スクロールを hint id で復元、無ければ index。
- gvim の古い buffer は editor 側（W11）に任せる。

### 9. category フィルタ（search 状態）

- 検索文字列の先頭トークンが `#` 始まりなら category フィルタ。残りはテキスト検索。両者は AND。
- `Tab` / `Shift+Tab` で巡回: 全表示 → category 初出順（擬似 category を含む）→ 全表示。`#` 入力途中なら補完。
- フィルタ状態は入力欄横に chip 表示。表示セッション限り。
- 実装: window の CAPTURE フェーズ controller で search 中の `Tab` / `Shift+Tab` を処理する（key 経路を 1 箇所に集約するため）。

### 10. IPC / CLI

追加コマンド（`ipc.COMMANDS` に追加）:

| cmd | 応答 |
|---|---|
| `context` | `{active_sheet, parent_context, desktop_app, process: {name, argv_basenames}, error}`。argv 全体は載せない。`error` は context 取得が失敗した理由（CLI が「sheet が無い」の理由に添える） |
| `edit-mode` | 編集モードに入る（表示中でなければ show してから）。`{visible, sheet, error}` |

CLI（daemon を経由せず自分でファイルに書く。`--sheet ID` 省略時は `context` で決める）の
引数一覧は README「CLI」を参照。`wayhint schema` は PATH 省略時は `editor.schema_path`、
`--write` 無しは標準出力。`wayhint format --modeline` の path は `editor.schema_path`。

### 11. config 追加

`editor.schema_modeline` を追加する。既定値と意味は Data model「config.yaml」を参照。

### 12. i18n

新規ラベルは EN（キー兼値）と JA の両方に追加。対象: フォームの欄名と kind の表示、key 割当ヘルプ、擬似 category（`inbox` / `未定義`）、エラー（validation 失敗、id 不在、YAML error 中は編集不可、sheet 不在）、削除確認、汎用 process 名の警告。

### 13. テスト

純粋関数（`./scripts/check`）:
- golden: リポジトリ内の sheet 全部（`examples/hints/*.yaml`、`tests/fixtures/good/*.yaml`）+ 汚い fixture（key 順バラバラ、hint 直前 / 直後コメント、行末コメント、hint 間空行、quote 混在、flow style の tags と match、値なし `remark:`）で load → dump byte 一致。加えて、環境変数 `WAYHINT_GOLDEN_EXTRA_DIR` が指すディレクトリの `*.yaml` も対象にする任意テスト（未設定なら skip、CI では未設定）
- `swap_hints`: コメント付き hint の移動でコメントが追随する
- `delete_hint`: 直前コメントが消え、直後コメントが残る
- `build_hint` / `update_hint`: canonical 順、null 表記、flow style tags
- `create_sheet`: app_id 解決 / process 解決 / 汎用名の 3 ケース
- slug 生成: 衝突、日本語 fallback、regex 適合
- `normalize_sheet`: format 済み sheet は再 format で byte 一致、format 前後で parse 結果が等しい
- sort: favorite 区画が category を無視すること、null category の位置
- `json_schema`: validation で通る sheet が schema でも通る

実機チェックリストは下の「実機チェックリスト」に T13–T24 として記載。

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
- T7 エディタで編集: 選択中の hint の sheet が開き該当行に jump、無選択では表示中の sheet の先頭
- T8 Herdr で bash → Herdr hints、`claude` → Claude sheet + tag 付き Herdr hints
- T9 Herdr で unknown process → Herdr hints のみ
- T10 表示中に YAML を編集 → 閉じずに更新
- T11 YAML を壊す → crash せず last-known-good + `⚠ YAML error`、直すと復帰
- T12 「閉じる」で閉じたあと workspace を往復しても再表示されない
- T13 `wayhint edit-mode` で EXCLUSIVE、Esc で NONE に戻り前の view に focus が返る
- T14 edit 中に workspace を離れる → NONE、戻ると grab が張り直され入力が残っている
- T15 edit 中の hotkey → hide / show、入力が残る
- T16 sheet が無い context で quick add → 新規 sheet が生成され、次の hotkey でその sheet が表示される
- T17 保存 → reload で overlay が閉じず、選択位置が保たれる
- T18 gvim で開いたまま GUI 保存 → gvim に W11
- T19 search で Tab / Shift+Tab → category 巡回、focus が overlay 外へ抜けない
- T20 `#` 途中入力 + Tab → 補完
- T21 `⚠ YAML error` 中に `wayhint edit-mode` → 拒否メッセージ、grab しない
- T22 `d` `d` → 削除、`u` → 復帰
- T23 混入 hint（親 sheet）を編集 → 親 sheet ファイルが更新される
- T24 各操作後、元アプリへ入力できる（grab 残留なし、既存項目の共通確認）
- T25 角 / 辺の grip を drag → 追従して伸縮、離すと config.yaml が px で書き換わる。閉じて開き
  直しても、daemon を再起動しても同じサイズ **(2026-09-18 確認済)**

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
