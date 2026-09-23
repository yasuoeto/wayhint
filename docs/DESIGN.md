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
                     WaylandContextProvider(foreign-toplevel)→ ProcAdapter / HerdrContextProvider
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
  `ProcAdapter` と `HerdrContextProvider` の 2 つ。判定材料で 2 群に分かれる —
  **terminal introspection**(app_id を見て自分で foreground process を探す: `ProcAdapter`)と
  **nested resolver**(host application に聞く: `HerdrContextProvider`)— が interface は共通で、
  ContextResolver は登録順に `applies_to` を問い、最初に当たった 1 つに `foreground_process(app_id)`
  を聞く。登録順を決める場所は `daemon._nested_providers()` の 1 か所。多段解決
  (terminal → multiplexer → command)は DECISIONS 0027 で見送った。将来 Tmux/SSH/EditorMode を
  同 interface で追加できる。
- **窓 → プロセスは app_id の接尾辞で解く**: Wayland の protocol も labwc も toplevel の pid を
  client に渡さないので、同じ端末の窓が 2 枚あると `/proc` だけでは区別できない。窓の側が
  `--app-id foot.p<pid>` と名乗る規約にして、compositor が返す app_id から pid を読み戻す
  (`matcher.strip_pid_suffix`、DECISIONS 0027)。接尾辞が無い app_id では、その端末の
  プロセスが 1 つのときだけ答える。sheet の照合・生成と overlay の表示は接尾辞を外した base を
  使い、`ResolvedContext.desktop_app` には接尾辞付きのまま入れる(窓が違えば context も違う)。
  sheet の照合は `app_specificity` が app_id と base の**両方**を候補にする(接尾辞付きの窓が
  `^foot$` の sheet に当たる。base だけにしないのは、たまたま `.p<数字>` で終わる app_id 向けの
  rule を壊さないため)。前面プロセスは **pty ごとに 1 つ**存在するので、端末の子孫に複数の tty が
  見つかったら(tab / split / tmux)深さや PID で推測せず**無判定**にする。
  端末と launcher の設定手順は `docs/TERMINALS.md`。

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
  context/proc.py                 /proc 隔離: terminal の子孫から foreground process(pgrp == tpgid)
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
- 設定ファイル: `$XDG_CONFIG_HOME/wayhint/config.yaml`, `style.css`, `hints/<lang>/*.yaml`(`.yml` も可、
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
include:    []          # 既定で全 sheet に混ぜる sheet id(DECISIONS 0026)。sheet 側 include が勝つ
```

- 全項目任意、ファイル自体も無くてよい(上記が既定値)。未知の section / key は error。
- size: 整数(px)、`"420px"`、`"30%"`(0–100)。margin: 整数(全辺)か `{top,right,bottom,left}`。
- `editor.command` は argv list。placeholder は `{file}` `{line}` `{hint_id}` のみ、`{file}` 必須。
  未知の `{...}` は error。展開は文字列置換のみで shell を通らない。
- `editor.schema_modeline`: true なら新規 sheet と format が先頭に
  `# yaml-language-server: $schema=` を付ける(DECISIONS 0014 D6)。
- `editor.schema_path`: モードラインの `$schema=` に書く path。`wayhint schema --write` の
  既定出力先。

### hints/<lang>/*.yaml(実装: `yaml_store.py`)

置き場所は言語ごとに 1 ディレクトリ(DECISIONS 0024)。`hints/<lang>/` → `hints/en/` →
`hints/*.yaml`(フラット、単一言語や移行前の配置)の順に**最初に見つかった 1 つだけ**を読む。
`<lang>` は UI と同じ `resolve_language()`(設定 `appearance.language` → locale → 未知なら `en`)。
読み書き・新規作成・監視はすべてそのディレクトリに対して行い、言語設定を変えると読み直す。


```yaml
version: 1              # 任意、1 のみ
id: claude              # 必須 ^[A-Za-z0-9][A-Za-z0-9._-]*$、ファイル名(stem)と同じ、全 sheet で一意
title: Claude Code      # 必須
priority: 10            # 任意 int、既定 0
match:                                                 # 省略可。無い sheet は active にならない
  wayland: {app_id_regex: [...]}                       # 旧綴り wayfire: も同義
  process: {argv_regex: [...], cmdline_regex: [...]}   # Python re でコンパイルできること
include: [wm, ime]                                     # 混ぜる sheet id。省略時は global include
display: {anchor, width, height, margin, output}       # 部分指定、global overlay から継承
inherit: {parent_tags: [terminal, ai]}                 # 省略時は global nested.parent_tags
hints:
  - {id, title,            # 必須。id は sheet 内で一意
     kind: shortcut|command|tip|note, key, command, category, tags: [], favorite: false,
     copy, remark, source, learned}
```

- **`include`**(DECISIONS 0026): ここに並べた sheet の hint を、この sheet の一覧に混ぜる。tag では
  絞らず全部入る。書かなければ config の `include` が既定として使われ、書けば**置き換える**
  (`inherit.parent_tags` と `nested.parent_tags` の関係と同じ)。include 先の include は辿らない。
  解決できない id と自分自身の id は warning で、その id だけ無視する(sheet は表示される。
  ただし config 既定由来の自己参照は黙って外す)。
- **`match` は省略可**。`match` の無い sheet はどの context でも active にならず、`include` からだけ
  一覧に出る(共通 hint 用)。`match` があっても include 対象にはできる。
- 一覧の連結順は active → 親 sheet(tag 一致分) → include(記述順)で、その後 D7 のソートを掛ける。
  同じ hint が 2 経路から来たときは `(ファイル, id)` で 1 件に落とす(0019)。
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
  使わない。メッセージは 1 接続 1 リクエストの改行終端 JSON(DECISIONS 0008): client が
  `{"cmd": "<name>"}\n` を 1 つ送って書き込み側を閉じ、daemon が `{"ok": true, ...}` か
  `{"ok": false, "error": "..."}` を 1 つ返して切断する。上限 4096 bytes、未知の `cmd` は error。
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
  し、adapter 内部で吸収する。**前提**: adapter が選ばれるのは app_id が `app_id_pattern`
  (既定 `herdr`、部分一致)に当たる窓だけで、これは config ではなく `HerdrContextProvider` の
  既定値。`herdr.yaml` の `app_id_regex` と対になっており、どちらも満たさない窓
  (素の kitty で `herdr` を起動した、など)は `/proc` 経路に落ちて「`herdr` というプロセスが
  動いている」までしか分からない。その状態は `proc.SELF_REPORTING` の判定で INFO ログに出す。
  **呼び出し規約**(DECISIONS 0028): 環境から `HERDR_` で始まる変数を
  除いて呼ぶ——`pane current` は `HERDR_PANE_ID` があればその pane を返すので、Herdr の pane 内から
  起動した daemon はその pane に固定されてしまう。`pane current` が `focused: false` を返したとき
  だけ保険として `pane list` を呼び、`focused: true` の pane が 1 つのときだけ採る。時間予算は
  lookup 開始時の deadline に対して使い、各 call には `min(CALL_TIMEOUT, 残り時間)` を渡す
  (最大 3 call でも合計は `LOOKUP_BUDGET` 以内)。
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
| `edit` | EXCLUSIVE | IPC `edit-mode`（compositor keybinding）、toolbar ボタン | Esc、もう一度 `edit-mode`、hide、workspace 離脱 |

- `keyboard_mode` を直接設定する箇所は `_sync_keyboard_mode()` 1 つに集約し、状態変更のたびに呼ぶ。
  hide / workspace 離脱では状態を保ったまま `NONE` に落とし、show / 復帰で状態に応じて張り直す。
- EXCLUSIVE を使う理由: `ON_DEMAND` では compositor が surface への再クリックまで keyboard focus を
  渡さず、検索ボタンを押しただけでは入力が下のアプリへ行ってしまう（labwc 0.20.2 で確認）。
- `edit` への入場条件: active sheet が last-known-good 表示でないこと（`⚠ YAML error` 中は拒否し理由を表示）。
- `edit` 中の hotkey は hide / show（0013 の例外）。
- エディタ起動（「エディタで編集」）では overlay を隠さない（DECISIONS 0023）。editor でキュレーション
  した結果を、保存のたびに reload で見たいため。`edit` / `search` のときは Escape と同じ経路で `normal`
  に戻し（keyboard_mode NONE、前の view へ focus 復帰）、editor が入力を受けられるようにする。`normal`
  のときは何もしない。開いていた下書きは view に残し、次の `edit-mode` で開き直す。起動に失敗したときは
  モードも変えずエラーを表示する。
- 編集状態（モード、開いているフォーム、フォームの入力値、対象 hint id、追加先 sheet）は workspace ごとの context dict と同じ粒度で保持する。メモリのみ。
- モード変更とフォームのキャンセルは daemon を経由し、UI はその状態を描画する。復帰先にフォームが
  無い場合も明示的に閉じ、他 workspace のフォームを残さない。編集中は検索ボタンを無効にし、
  編集を終了してから検索する。非表示の編集画面への `edit-mode` は保持した下書きを再表示する。
- **保存後の状態は操作で分ける**(DECISIONS 0021)。

  | 操作 | 完了後 |
  |---|---|
  | quick add フォーム（`a` → Enter） | `normal`（keyboard_mode NONE、前の view へ focus 復帰） |
  | 編集フォーム（Enter → Enter） | `normal`（同上） |
  | `f` / `J` `K` / `d` `d` / `u` | `edit` に留まる |
  | フォームの `Esc`（入力破棄） | `edit` に留まる |
  | validation 失敗 | フォームを開いたまま `edit` に留まる |

  フォーム保存の処理順は、ファイル書き込み成功 → mode を `normal` に変更 → `_sync_keyboard_mode()`
  → focus 復帰（search 終了と同じ経路）。書き込みに失敗したら mode は変えない。§7 の sheet 新規作成を
  伴う quick add も同じく `normal` に戻る。「保存して留まる」別キーや config 項目は作らない。

### 2. key 割当（edit 中）

| key | 動作 |
|---|---|
| `a` | quick add フォームを開く（追加先は選択中の hint の sheet、§3） |
| `Enter` | 選択 hint の編集フォームを開く |
| `d` `d` | 選択 hint を削除（1 回目で確認表示、2 回目で確定。他の key で取り消し） |
| `u` | 直前に削除した 1 件を元の sheet 末尾に戻す（メモリ保持は 1 件、セッション限り） |
| `f` | favorite toggle |
| `J` / `K` | 画面上の下 / 上の hint と swap（§5 の制約） |
| `↑` `↓` | 選択移動（`KP_Up` / `KP_Down` も同じ。単打キーと同様 CAPTURE で受ける） |
| `Esc` | フォームが開いていればフォームを閉じる（入力破棄）、開いていなければ `edit` を抜ける |

一覧の単打キーと `Tab` / `Shift+Tab` は CAPTURE フェーズの `EventControllerKey` で受ける（ListBox の
行操作や Tab の focus 移動より先に処理するため）。テキスト欄の `Enter` / `Esc` は input method に先に
渡し、bubble フェーズで受ける（変換の確定・取り消しを奪わないため）。

`↑` `↓` も同じ経路で受ける（2026-09-23 変更。当初は「GTK 既定を使う」だった）。keyboard を
EXCLUSIVE で掴んだ layer surface では、window が一覧に与えた focus が定着しない——`grab_focus()`
は true を返すのに AT-SPI はどの行も focused と報告せず、最初の矢印キーは「一覧に入る」だけで
消える（labwc 0.20.2 で実測）。結果として**マウス無しでは 2 行目以降に `f` / `J` / `K` / `Enter` /
`d` `d` が当たらない**状態になっていた。選択移動は `editmode.next_selection()` の純粋関数で決め、
端では折り返さない。テキスト欄では矢印はカーソル移動なので、`editable` のときは受けない。

一覧のキーは修飾なしのときだけ受ける。`Ctrl+d` 等は別のアプリ・ウィジェットのキーであり、
これを削除確認に使うと狙っていない操作が走る。テキスト欄で先に受ける `Tab` / `Shift+Tab` /
`Ctrl+P` も、**変換中（preedit あり）は input method に渡す**（候補選択・候補移動に使われるため）。
preedit の有無は `GtkText::preedit-changed` で追う。

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
- 保存前に validation。失敗時はフォーム内にエラーを出し書かない（`edit` のまま、フォームも開いたまま）。
- 保存に成功したらフォームを閉じ、`edit` を抜けて `normal` に戻る（§1 の表）。続けて追加するときは
  もう一度 `wayhint edit-mode` → `a`。
- 追加先: **選択中の hint の所属 sheet**（DECISIONS 0025）。一覧には親 sheet の hint が混ざるため、
  見ているものと同じ sheet に入れる。未選択、または所属ファイルが消えていれば active sheet、
  それも無ければ §7 で新規作成。`Ctrl+P` は追加先を親 sheet に切り替える。フォームの見出しに
  追加先の sheet 名を出す。混入 hint の編集は所属 sheet に書く（0014 D9）。

### 4. 書き戻し（yaml_store）

純粋関数として実装し、GTK / pywayland を import しない。

| 関数 | 内容 |
|---|---|
| `write_document(path, doc)` | tmp（`.yaml` / `.yml` 以外の拡張子、同一ディレクトリ、**writer ごとに別名**）→ validate → `st_mode` コピー → `os.replace` |
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

- path: `~/.config/wayhint/hints/<lang>/<slug>.yaml`(表示中の言語のディレクトリ、0024)。slug は app 名 / process 名から。sheet id 衝突時 `-2`。
- 内容: 先頭コメント（生成日時、`desktop_app`、`parent_context`、`foreground_process.name`、採用した regex）、`editor.schema_modeline` が true なら、先頭に `# yaml-language-server: $schema=<editor.schema_path を展開した絶対 path>` を付ける、`id` `title` `priority`（既定）`match` `hints: [first_hint]`。
- `match` の生成:
  - `foreground_process is None` → app_id 一致
  - `foreground_process` あり → `process.argv_regex: ["^<name>$"]`。判定材料は `parent_context` ではなく foreground process:
    terminal は自分用の sheet を持たないのが普通で（`parent_context` が `null`）、その app_id から作った rule はその terminal で動かす全コマンドに当たってしまう（0027）
  - `name` が汎用名（定数 `GENERIC_PROCESS_NAMES`。`matcher.py` に置く）→ `argv[1:]` の basename を候補にする（候補生成は matcher の `process_candidates` / `argv_basenames` と同じ規則）。`-` で始まる引数（オプション）は候補から除く。非汎用の候補が無ければフォームに警告
  - app_id 一致の regex は `re.escape` した完全一致（例 `^org\.inkscape\.Inkscape$`）
  - 警告は `match_rule_for_context` の戻り値で返し、UI / CLI がそれを表示する
- 生成直後の FileMonitor reload で新 sheet が有効になる。

### 8. 同時編集と reload

- 後勝ち。mtime 比較なし。
- tmp 名は writer ごとに分ける（`<name>.<pid>-<連番>.tmp`）。GUI と CLI、CLI 同士が同じ sheet を
  書くため、共有すると片方の tmp を他方が read / replace / unlink して「後勝ち」ではない失敗になる。
- 保存時に対象 id が無ければエラー表示、reload に任せる。
- 自己書き込みの reload は抑止しない。`_after_reload` で選択を hint id で復元し、無ければ index。
  スクロールは pixel 位置を保存せず、復元した選択 hint が見える位置まで動かすだけ(復元できなければ先頭)。スクロールバーは常時表示(overlay scrollbar は使わない)。
- hint id は sheet 内だけで一意。GUI の編集・削除・favorite・移動・選択復元には
  `(所属ファイル, hint id)` を使う。編集フォームも所属ファイルを保持し、対象消失時は他 sheet へ代替しない。
- 編集操作の前に debounce 待ちの reload を先に適用する(`_flush_pending_reloads`)。自分の書き込みの
  reload は 200ms 後なので、連打すると古い store を見て決めてしまうため。favorite の toggle は
  さらに file の値を反転する(`toggle_favorite`)。
- sheet の `id` はファイル名の stem と一致必須。違うファイルは hint として読み込まず Issue にする
  (rename / backup コピーで他人の id を名乗るファイルが増えるため。DECISIONS 0020)。
- それでも `x.yaml` と `x.yml` は衝突しうるので、重複時はファイル名順で先に読んだ 1 枚だけを使い、
  後続は store に入れず Issue にする(両方のファイル名を含める)。曖昧なときに選び方を運任せにしない
  (設計書 §59)。
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
| `context` | `{active_sheet, parent_context, desktop_app, process: {name, argv_basenames}, include, chain, error}`。argv 全体は載せない。`include` は解決できた混入元 sheet id の list（0026）。`chain` は **問い合わせた nested provider のクラス名**の list（順番どおり、現状は 0 か 1 要素。答えが `null` だった provider も載る＝どこを見ればよいかを示す）。`error` は context 取得が失敗した理由（CLI が「sheet が無い」の理由に添える） |
| `edit-mode` | 編集モードに入る（表示中でなければ show してから）。編集モード中に再度呼ぶと抜ける（フォームが開いていれば先にフォームを閉じる）。`{visible, mode, sheet, error}` |

CLI（daemon を経由せず自分でファイルに書く。`--sheet ID` 省略時は `context` で決める）の
引数一覧は README「CLI」を参照。`wayhint schema` は PATH 省略時は `editor.schema_path`、
`--write` 無しは標準出力。`wayhint format --modeline` の path は `editor.schema_path`。

### 11. config 追加

`editor.schema_modeline` を追加する。既定値と意味は Data model「config.yaml」を参照。

### 12. i18n

新規ラベルは EN（キー兼値）と JA の両方に追加。対象: フォームの欄名と kind の表示、key 割当ヘルプ、擬似 category（`inbox` / `未定義`）、エラー（validation 失敗、id 不在、YAML error 中は編集不可、sheet 不在）、削除確認、汎用 process 名の警告。

`appearance.language` の変更は **daemon を再起動せずに反映する**（0024 の「1 言語 = 1 ディレクトリ」は
sheet だけでなく UI の文言にも掛かる）。context ごとに描き直す文字列は毎回 `self._tr` を引くので
自動的に追従するが、**widget を組み立てたときに一度だけ書き込んだ文字列**（ツールバーの 5 ボタン、
検索欄の placeholder、フォームの欄名と `Kind`）は追従しない。この分だけを
`HintWindow._fixed()` が `(setter, key)` として控え、`set_language()` が引き直す。
daemon 側は `_reload_config` で `appearance.language` の変化を見て呼ぶ
（`hints_dir` の変化では判定できない——`ja` と `auto` が同じ `hints/en/` に落ちることがある）。

### 13. テスト

純粋関数（`./scripts/check`）:
- golden: リポジトリ内の sheet 全部（`examples/hints/<lang>/*.yaml`、`tests/fixtures/good/*.yaml`）+ 汚い fixture（key 順バラバラ、hint 直前 / 直後コメント、行末コメント、hint 間空行、quote 混在、flow style の tags と match、値なし `remark:`）で load → dump byte 一致。加えて、環境変数 `WAYHINT_GOLDEN_EXTRA_DIR` が指すディレクトリの `*.yaml` も対象にする任意テスト（未設定なら skip、CI では未設定）
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
| `include` が解決できない id / 自己参照 | その id だけ無視して sheet は表示する。`Issue(severity="warning")` として overlay と `wayhint validate` に出すが、validate の exit code は 0 のまま |
| editor 不在 / 起動失敗 | GUI で error 表示 |
| 検索終了時 focus 復帰失敗 | それでも keyboard_mode は必ず none に戻す(grab 残留禁止) |
| 復帰先の window が一意に決まらない(app_id と title が同じ window が複数) | focus 復帰を諦めて log に残す。別 window を掴まない |
| workspace 監視の接続が切れた | 監視だけを止め、表示中の view(モード・下書き)は単一 slot に引き継ぐ。Esc / hide で必ず抜けられる |
| YAML が UTF-8 でない | 他の読み取り失敗と同じ Issue。last-known-good を保つ |

## Testing strategy

- **unit**(§66): YAML parse、schema validation、size parse、% 変換、anchor 変換、app/process
  matcher、match priority、parent tag filter、favorite sort、search、editor argv 展開、
  source line mapping。
- **context tests**(§67, §68): mock desktop provider(Inkscape/Chromium/Herdr)、mock Herdr process-info
  (bash/claude/codex/`node /path/to/codex`)。nested: Herdr+Claude → Claude sheet + tag 交差の
  Herdr hints。favorite は影響しない。
- **実機**(§69–§73): 自動化しない。下の手動チェックリストで確認する。
- **contract tests**: resolver と**実物の** provider を繋ぐ。fake だけで固めていると、provider の
  signature が resolver の呼び出しと食い違っても全部通ってしまう(resolver の `except Exception` が
  `TypeError` を飲むため、実機では黙って答えなくなるだけになる)。nested 側は
  `tests/test_context.py` の `RealProviderContractTest`、desktop 側は
  `tests/test_desktop_providers.py`。
- **adapter tests**(`tests/test_desktop_providers.py`): signature と「compositor が無いときに
  `ContextError` になること」はヘッドレスで常に走る。compositor があるセッションでは、実際に
  接続して snapshot / `find_output` の形と、GTK + gtk4-layer-shell の typelib が DECISIONS 0009 の
  順で読めること(子プロセスで `_load_gui()`)まで確認する。無ければ skip する。
- **keyboard grab**(`tests/test_window_grab.py`): `keyboard_grab` は純粋で headless に検証済みだが、
  **widget 側がそれを適用しているか**は手動チェックリスト(T6 / T13 / T24)しか見ていなかった。
  compositor があるときだけ、実物の `HintWindow` を建てて layer surface の `keyboard_mode` が
  `keyboard_grab` と全状態で一致すること、hide で grab が落ちて mode は残ることを確認する。
  **surface は map しない**(`present()` を呼ばず `get_visible` を差し替える)ので画面には何も出ない。
- **描画**(`tests/test_window_render.py`): `HintWindow.lay_out()`(= `present_context` から
  `set_visible` / `present` を除いた部分)を呼び、一覧が `sort_hints(visible_hints(...))` と
  一致すること、見出しの `親 › 子` と context ラベル(app_id は接尾辞を外す)、sheet が無いときの
  表示、layer surface の anchor / margin / size が `geometry.placement` と一致すること
  (global 指定と sheet override の両方)、search で絞られて抜けると戻ることを確認する。
  ここも surface は map しない。
- **daemon → window**(`tests/test_daemon_window.py`): socket に届いた 1 行を
  `ipc.handle_request` → `dispatch` → **実物の `HintWindow`** まで通す。`test_daemon_edit` は
  window を fake にし、`test_window_render` は context を手で組むので、その間の継ぎ目だけが
  誰にも見られていなかった。呼び出し元(compositor の keybind / CLI / 将来の経路)は CLI より手前で
  同じ `{"cmd": ...}` に正規化されるので、ここが「正しいものが出たか」の決まる場所になる。
  ここも surface は map しない(`present` / `set_visible` を差し替え、`get_visible` は
  `set_visible` に渡った値を返すので keyboard の規則は可視性の変化を見られる)。
- **headless GUI**(`tests/test_gui_headless.py`、入口は `./scripts/check-gui`): compositor を
  `WLR_BACKENDS=headless` で立て、その中で `wayhintd` を動かし、実際に map された surface を
  測る(DECISIONS 0030)。session の起動・後片付け・grim / AT-SPI / wtype の呼び出しは
  `tools/headless.py` にあり、`tests/headless.py` は unittest 向けの opt-in と skip だけを足す薄い層
  (デモ生成 `scripts/demo` と共有するため)。layer surface は compositor への
  *要求*なので、anchor と margin がどう解釈されたかはプロセス内からは見えない。
  **位置**は overlay を出した frame と出していない frame の差分の bounding box(font 非依存)、
  **中身**は AT-SPI の accessible name で読む。ベースライン画像の全面比較は採らない(0030)。
  入力注入(compositor の keybind → CLI → IPC)は `wtype` がある環境でだけ走る。
  ユーザーが座っているセッションには触らない——専用の `XDG_RUNTIME_DIR` /
  `XDG_CONFIG_HOME` / `HOME` / session bus を与える。
- `./scripts/check` が unit/context tests を実行する唯一の入口。GTK/pywayland/PyWayfire 依存の import は
  テストから分離し、ヘッドレスでも通るようにする(実機が要るものは skip。上の adapter tests)。
  headless compositor を要するものは `./scripts/check-gui` に分け、`WAYHINT_GUI_TESTS=1` が
  無ければ skip する(既定の `check` は数百 ms・依存無しのまま)。
- daemon の GUI import は起動時まで遅延する。`tests/test_daemon_edit.py` は window と workspace の
  境界を fake にし、実際の daemon / SheetStore / YAML 保存を通して対象ファイルと編集状態を検証する。

## Demo generation

紹介動画は `./scripts/demo --showcase <name> --record` が
`demo/showcases/<name>/02_<name>_scenario.yaml` から生成する(DECISIONS 0031、0032)。
テストと同じ基盤の上に乗っている:

```
tools/headless.py ──┬── tests/headless.py ── tests/test_gui_headless.py   (./scripts/check-gui)
 (compositor /      │
  daemon / grim /   └── tools/demo/session.py ── tools/demo/__main__.py    (./scripts/demo)
  AT-SPI / wtype)
```

`tools/headless.py` は headless session そのもの(専用の `XDG_RUNTIME_DIR` / `XDG_CONFIG_HOME` /
`HOME` / session bus、compositor と `wayhintd` の起動と後片付け、grim・AT-SPI・wtype)。
`tests/headless.py` は unittest の opt-in と skip だけを足す薄い層で、`tools/demo/` は同じ
session に keybind 2 つ・`windowRules`・fixtures の作業コピーを足して使う。**ここを変えると
`./scripts/check-gui` とデモの両方が動く。**

`tools/demo/` の分担は showcase(ディレクトリと役割ファイルの解決)、scenario(読み込みと検証、
尺の計算)、session(必要なものの確認、fixtures の配置、Herdr の隔離起動と停止)、actions(action の
実行と `wait_for` の判定)、capture(frame-stepping と contact sheet)、encode(ffmpeg と SRT)。
尺は scenario の `hold` を frame 数に丸めたもので決まり、1 step につき 1 frame だけ撮って複製する。
scenario の書き方は `demo/README.md`。

### showcase と variant(DECISIONS 0032)

動画 1 本分を **showcase** とし、`demo/showcases/<name>/` に閉じる。中のファイルは名前の末尾の
役割で探す(`<NN>_<showcase>_<role>.<ext>`。`storyboard` が台本、`scenario` が実行用)。中央部分が
ディレクトリ名と違えば警告、同じ役割が 2 つあれば error。生成物は `out/<lang>/<variant>/` で、
追跡しない。

1 つの scenario は step を 1 回ずつ定義し、**variant**(`60s` / `3min` / `5min`)がその id を並べる。
variant は *clean session からその列だけを実行して成立する完全な列*で、variant 間で状態を引き継が
ない。`--dry-run` は各 variant の予定尺を `target ± tolerance` と突き合わせ、外れれば止まる。

### Herdr の隔離(DECISIONS 0032)

showcase `herdr` は**実物の Herdr** を動かす。`tools/demo/session.py` が session の
`XDG_CONFIG_HOME` に最小の `config.toml`(オンボーディングとテーマ選択、版チェック、tab 名の入力を
止め、shell と window title を固定)を書き、`HeadlessSession.env()` が **`HERDR_*` を落とす**
——落とさないと session 内の herdr client が実ユーザーの server に繋がる。Herdr の server は
daemon 化して session のプロセスグループを抜けるので、session を畳む**前**に `herdr server stop`
を呼び、残ったら `/proc/*/environ` の `HOME` が session のものである herdr だけを kill する。

### 言語

`hints/<lang>/` と `caption.<lang>` だけが言語ごとで、`config.yaml` は 1 つ。recorder は session 用の
コピーに `appearance.language` を書き、repository の fixture は変えない。日本語が先で、`--validate`
は ja の字幕だけを要求する。

### 実機チェックリスト(§69–§73、手動)

`./scripts/check` の対象外。labwc と Wayfire の
それぞれのセッションで実施し、**結果は `STATUS.md` に日付付きで記録する**。この一覧は項目の
定義だけを持ち、合否は持たない。同じ項目でも compositor ごとに結果が変わるため、記録先を
1 か所に寄せる。

- T1 hotkey で右上に表示、元アプリへの入力が続く(keyboard grab なし)
  （位置と hotkey 経路は `./scripts/check-gui` が headless でも見る。実機で見るのは
  「元アプリへの入力が続く」の方）
- T2 同じ hotkey で非表示(toggle)（同上）
- T3 別 output 上のアプリから起動 → そのアプリの output に出る（複数 output は headless では
  作っていないので実機のまま）
- T4 sheet の `display.output` override が効く
- T5 `width: 30%` / `height: 60%` が対象 output の logical size 基準
  （`./scripts/check-gui` が単一 output で見る。実機では回転・スケールのある output で確認する）
- T6 検索中だけ入力を受け、完了 / Esc 後に grab が残らず前の view に focus が戻る
- T7 エディタで編集: 選択中の hint の sheet が開き該当行に jump、無選択では表示中の sheet の先頭
- T8 Herdr で bash → Herdr hints、`claude` → Claude sheet + tag 付き Herdr hints
- T9 Herdr で unknown process → Herdr hints のみ
- T10 表示中に YAML を編集 → 閉じずに更新
- T11 YAML を壊す → crash せず last-known-good + `⚠ YAML error`、直すと復帰
- T12 「閉じる」で閉じたあと workspace を往復しても再表示されない
- T13 `wayhint edit-mode` で EXCLUSIVE、Esc で NONE に戻り前の view に focus が返る。
  もう一度 `wayhint edit-mode` を呼んでも同じく抜ける（フォームが開いていれば 1 回目はフォームを閉じるだけ）
- T14 edit 中に workspace を離れる → NONE、戻ると grab が張り直され入力が残っている
- T15 edit 中の hotkey → hide / show、入力が残る
- T16 sheet が無い context で quick add → 新規 sheet が生成され、保存直後にその hint が
  一覧へ出る(次の hotkey を待たない)。保存すると overlay は表示されたまま `normal` に戻り、
  元アプリへ入力できる。続けて追加するときは再度 `wayhint edit-mode` → `a`（同じ sheet に追記される）
  **(2026-09-19 確認済)**
- T17 `f` / `J` `K` など `edit` に留まる操作 → reload で overlay が閉じず、選択位置が保たれる。
  選択中の hint が画面外に出ていたら見える位置までスクロールする。一覧が画面に収まらないとき
  スクロールバーが出ている。フォーム保存の場合は `normal` に戻った一覧で同じことを確認する
  **(2026-09-19 確認済)**
- T17b `↑` `↓` で選択が 1 行ずつ動き、端で止まる。動かした行に `f` が効く（マウスを使わない）
  **(2026-09-23 確認済)**
- T18 gvim で開いたまま GUI 保存 → gvim に W11
- T19 search で Tab / Shift+Tab → category 巡回、focus が overlay 外へ抜けない
- T20 `#` 途中入力 + Tab → 補完
- T21 `⚠ YAML error` 中に `wayhint edit-mode` → 拒否メッセージ、grab しない
- T22 `d` `d` → 削除、`u` → 復帰
- T22b `f` を続けて 2 回 → favorite が付いて外れる。`J` を続けて 2 回 → 2 つ下まで動く
  **(2026-09-19 確認済)**
- T23 混入 hint（親 sheet）を編集 → 親 sheet ファイルが更新される
- T23c 混入 hint（親 sheet）を選んで `a` → フォームの見出しが親 sheet になり、保存すると
  親 sheet ファイルに追記される。未選択で `a` を押すと active sheet が追加先になる
- T23b sheet を別名でコピー（`claude.yaml` → `claude-backup.yaml`）→ 一覧は増えず、⚠ にファイル名と
  id の不一致が出る **(2026-09-19 確認済)**
- T30 `appearance.language` を `ja` / `en` で切り替える（または `LANG` を変えて daemon を起動）
  → UI の文言と一緒に `hints/ja/` と `hints/en/` が切り替わる。片方しか無い言語では `en` に
  落ち、どちらも無ければ `hints/*.yaml` が読まれる。**overlay を出したまま config.yaml を
  書き換えても、再起動せずにボタンと欄名まで切り替わる**（自動テストは
  `tests/test_daemon_window.py`。実機で見るのは overlay を開いたままの書き換え）
- T31 sheet の `include` で他 sheet の hint が一覧の末尾に出る。それを編集すると所属ファイルが
  更新される（詳細欄の `ファイル:` が書き換え先）
- T32 config の `include` が `include` を書いていない sheet 全部に効き、`include:` を書いた sheet では
  置き換わる（`include: []` なら何も混ざらない）
- T33 `match` の無い sheet は単独では表示されず、`include` 経由でだけ出る
- T34 解決できない id を `include` に書いても sheet は表示され、overlay の ⚠ と
  `wayhint validate` に warning が出る（validate の終了コードは 0）
- T35 `wayhint context` の応答に `include` が含まれる
- T24 各操作後、元アプリへ入力できる（grab 残留なし、既存項目の共通確認）
- T25 角 / 辺の grip を drag → 追従して伸縮、離すと config.yaml が px で書き換わる。閉じて開き
  直しても、daemon を再起動しても同じサイズ **(2026-09-18 確認済)**
- T26 key と title が 1 行ずつのとき文字のベースラインが揃う。どちらかが折り返したら、
  1 行のほうが行の高さの中央に来る(overlay の幅を grip で変えて title を折り返させる)
  **(2026-09-18 確認済)**
- T27 IME で変換中に `Tab` / `Ctrl+P` → 候補操作が効き、欄移動や親 sheet toggle に取られない。
  確定後は従来どおり欄移動になる **(2026-09-19 確認済)**
- T28 「エディタで編集」→ overlay は出たまま、エディタに入力できる（`edit` / `search` から押した
  ときは `normal` に戻る）。エディタで保存すると overlay の一覧がその場で更新される。開いていた
  下書きは次の `wayhint edit-mode` で戻る。エディタが起動できないときはモードも変わらずエラーが出る
  **(2026-09-19 確認済)**
- T29 出力を 90 度回転させた状態で `width: 50%` → 回転後の論理サイズ基準で配置される
  (回転できるモニタが要るため未実施)
- T36 `foot.p$$` で起動した foot 上で `vi` 実行中に hotkey → vi 用 sheet が選ばれ、
  `wayhint context` の `chain` に `ProcAdapter`、process name に `vi` が出る。foot 窓を 2 枚開いても
  フォーカス中の窓の process が取れる。`desktop_app` は `foot.p<pid>`、overlay の context ラベルは
  接尾辞の無い `foot`。foot 用 sheet は書かなくてよい(`parent_context` は `null`)
- T37 wrapper を通さず起動した端末の窓が 2 枚以上あるとき → `chain` に `ProcAdapter` は入るが
  process は `null`（無判定）。1 枚だけのときは解決する。
  **foot では確認できない**: Herdr の窓を `foot --app-id=foot-herdr` で動かしている限り foot の
  プロセスは常に 2 つ以上あり、「1 枚だけ」の状態を作れない。別の端末（ghostty 等）で確認する

## Known limits and future work

- V1 の限界は PRODUCT.md「Out of scope」のとおり。
- **workspace をまたいだ表示**: layer surface は output に属し workspace を持たないため、overlay は
  何もしなければ workspace 切り替えをまたいで表示され続ける。`context.workspace: current`(既定)は
  `ext_workspace_manager_v1` で active workspace を監視し、overlay を workspace 単位で開閉する
  (DECISIONS 0012)。
  **Wayfire は未対応**。protocol を出すかどうかは実機が無く未確認で、確認できないものを対応とは
  書かない。protocol が無い compositor では監視せず、従来どおり全 workspace に表示する。
- **fractional scaling の論理サイズ**: `wl_output.scale` は整数しか持たないため、1.5 倍等の環境では
  論理サイズが概算になる(`mode / ceil(scale)`)。正確に取るには `xdg_output` の `logical_size` を
  bind する必要があるが、主環境(labwc)で fractional scaling を使っていないため入れない
  (DECISIONS 0020)。使う予定が出たら `xdg_output_manager` 利用・無ければ現行計算へ fallback、
  として別件で起こす。回転(`wl_output.geometry.transform`)と `mode` の CURRENT flag は対応済み。
- **context 取得の同期呼び出し**: Herdr(subprocess)と Wayland(roundtrip)は GTK の main loop 上で
  同期に走る。実測は herdr 2 往復で 2-3ms、Wayland snapshot で 0-18ms だが、応答しない相手が
  いると描画と IPC が止まる。Herdr 側は 1 回の context 取得の上限を `ipc.CLIENT_TIMEOUT` より
  短くしてあり(`herdr.LOOKUP_BUDGET`)、CLI が諦めたあとに遅れて処理が通ることは無い。Wayland 側の
  roundtrip には時間制限が無い。非同期化は adapter の契約を変えるため別途判断する。
- 拡張余地(§76、V1 には含めない): アプリ内部 mode(Vim/shell)、SSH remote、tmux pane、
  terminal title detector、AI agent lifecycle state、context 別 styling、usage frequency、
  recently learned、explicit executable flag 付き command 実行。
- 実装順序は設計書 §79 の Phase 1–9。Phase 1(config loader / YAML model / validation)から
  始め、Phase 0 として §78 の依存確認を行う。
