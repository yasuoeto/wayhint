# wayhint — Product

出典: 「Wayfire向けコンテキスト依存ヒントオーバーレイ 設計書」(2026-09-16、以下「設計書」)。
設計書中の名称 `context-hint` / `context_hint` / `~/.config/context-hint/` は、本リポジトリでは
`wayhint` / `wayhint` / `~/.config/wayhint/` に読み替える(DECISIONS 0002)。

## Problem

Wayland環境で操作方法を忘れたとき、Web検索やマニュアル検索を繰り返している。よく使う操作が
一定位置に無いため視線が定まらず、過去に調べた操作・Tips・注意事項が蓄積されない。Herdrのような
入れ子環境では、外側のterminalではなく内側で動いているアプリ(Claude Code, Codex…)のヒントが
必要になる。

## Users and use cases

- 利用者は自分1人。自分専用の **context-aware personal cheatsheet** であり、一般的な
  ショートカット一覧ではない。
- 使い方: 操作を忘れた瞬間にhotkey(既定 `Super+?`)を押す → いつも同じ場所(既定: 画面右上)に、
  現在のcontextに応じた自分用の情報が出る → 見終わったら同じhotkeyで消す。
- 調べた操作はYAMLに追記して育てる。追加・修正・削除はoverlayの編集モードで完結し、sheet全体を
  見直すときはoverlayの「Edit in editor」から外部editor(gvim)で該当ファイル・該当行を直接開ける。

### 最重要原則(設計書 §1.1 / §81)

> 「操作を忘れた瞬間、いつも同じ場所を見れば、そのcontextで必要な自分用情報があること」

位置の安定、正確なcontext判定、情報量の制御、容易な更新、foreground applicationを邪魔しないこと
を、機能追加より優先する。スコープ判断で迷ったらここに戻る。

## Scope

### In scope

- 対応環境(V1正式対象): Linux / Wayland(wlroots 系: labwc, Wayfire)/ Python 3 / GTK4 /
  PyGObject / gtk4-layer-shell / pywayland(wlr-foreign-toplevel)/ YAML。Wayfire IPC(PyWayfire)
  は任意の fallback。
- context判定の階層: compositor の active toplevel → application → (Herdrなら) focused pane →
  foreground process。V1はforeground processまで。
- 入れ子表示: 子sheet(例 Claude Code)のhint + 親sheet(Herdr)のhint。既定は全部。親側
  (`nested.export_tags`)または子側・config(`parent_tags`)で tag を書いたときだけ絞る(DECISIONS 0034)。
- 1 application/context につき1 YAMLファイル(`~/.config/wayhint/hints/*.yaml`)。
- 検索(通常表示ではkeyboardを取らず、Search開始時のみinteractive)。
- 詳細表示(remark / source / learned / tags は詳細のみ。id / kind は表示しない)。clipboard copy。
- 外部editorによる編集(Edit in editor: sheetを開き該当行へjump)、YAML保存時の自動reload、
  invalid YAML時のlast-known-good保持。
- daemon + CLI(`wayhint toggle|show|hide|refresh|validate`)、Unix domain socket IPC、
  hotkeyはcompositor側keybindingに委譲。
- 表示位置(9 anchor)、px/%サイズ、margin、マウスでの手動リサイズ(config.yamlへ px で保存)、
  multi-monitor(active output自動選択 + override)、
  font指定、GTK CSS override。

### Out of scope (V1で実装しないもの — 設計書 §75)

- X11 / GNOME / KDE 対応保証(compositor 依存はadapterに隔離。wlr-foreign-toplevel と layer-shell
  を出す wlroots 系以外への移植は要件外)
- AIによるhint自動生成、Webからのhint自動取得、クラウド同期、hint usage analytics
- **command自動実行**(YAML内の `command` は表示・copyのみ)
- terminal screen scraping による context 推測
- Vim mode / Claude Code内部mode / Codex内部mode / アプリ内部dialog状態の判定
- dynamic plugin system(loader, entry points, marketplace)
- GUI 上での YAML 直接編集(テキストとしての編集)。hint 単位の構造化編集は 0014 で
  スコープ内。sheet メタ・match・並び順の変更は外部 editor のみ
- idle時のlive polling(context取得はtoggle/show/refresh時のみ)

## Requirements

### Functional

設計書の §3–§60 が要件本体。要点:

1. **toggle**: hotkey → context取得 → 表示、表示中に同hotkey → 非表示(§3)。
2. **focus**: 通常表示時 `keyboard_mode = none`。元アプリへの入力を止めない(§3.2)。検索開始時
   のみ interactive(ON_DEMAND、必要ならEXCLUSIVE)、終了時は必ず none に戻し前のviewへfocus
   復帰を試みる(§4, §47, §48)。
3. **layer-shell**: `layer: overlay`, `exclusive_zone: 0`, 既定 anchor top-right。画面領域を
   予約しない(§6)。位置は anchor + margin + size、絶対座標は主方式にしない(§7, §9)。
4. **size**: px と % の混在可。% は対象outputのlogical sizeに対する割合(§8)。
5. **multi-monitor**: 表示先の優先順位 = sheet output override → active viewのoutput →
   compositor の focused output(取れる場合)→ global fallback(§10)。
6. **context snapshot**: 開いた瞬間のcontextを表示中固定(`context.live_update: false`)。
   再判定は閉じて開く / hotkeyの押し直し / `wayhint refresh` / 明示reload(§11)。
7. **matcher**: `match.wayland.app_id_regex`(旧 `match.wayfire`) / `match.process.{argv_regex,cmdline_regex}`。
   複数一致は priority → matcher specificity → file order(§16, §59)。
8. **Herdr adapter**: `herdr pane current` / `herdr pane process-info --pane <id>` から
   foreground process (name/argv/cmdline/pid/cwd) を取得。name だけに依存せず argv basename
   も照合(`node /path/to/codex`)。取得失敗時はHerdr hintsのみ(§14, §15)。
9. **parent tag filtering**: 表示対象は tag の交差のみで決め、favorite で決めない。
   子sheet `inherit.parent_tags` が global `nested.parent_tags` を上書き(§17–§19, §29)。
10. **hint schema**: 必須 `id`,`title`。任意 `kind(shortcut|command|tip|note)`, `key`,
    `command`, `category`, `tags`, `favorite`, `copy`, `remark`, `source`, `learned`(§21–§26)。
    `id` と `title` 以外は省略可。GUI / CLI / format が書く hint は 12 項目を null 込みで出力する。
11. **sort**: favorite 区画は YAML 記述順、非 favorite 区画は category 初出順 → YAML 記述順(§29)。
12. **search**: 対象 title/key/command/category/tags/remark、case-insensitive substring +
    token AND(§31)。入力(検索モード、keyboard を奪う間)と絞り込み(一覧の状態)を分け、
    絞り込みは検索を抜けても残し、sheet ごとに `state.yaml` へ保存する。入口は検索ボタンと
    `wayhint search-mode`(DECISIONS 0033)。
13. **copy**: 優先 `copy` → `command` → `key`。GTK/GDK clipboard(§32)。検索欄の `Enter`、
    一覧の `c` / `Enter` でもコピーし、検索を抜ける(0033)。
14. **editor**: 設定済argvの placeholder `{file}` `{line}` `{hint_id}` を置換し
    `subprocess.Popen(argv, shell=False)`(§34–§38)。
15. **reload**: Gio.FileMonitor 等の event-driven 監視 → debounce → parse → validation → UI
    更新。parse失敗時はlast-known-goodを保持し `⚠ YAML error` を表示、修正で自動復帰(§39, §40)。
16. **validate CLI**: YAML syntax / duplicate sheet id / duplicate hint id / invalid regex /
    invalid size / invalid anchor / invalid editor placeholder / unknown required field。
    エラー時 exit code ≠ 0(§60)。
17. **failure policy**: desktop context 不可 → error表示・crashしない。Herdr不可 → desktop context
    へfallback。editor不在 → GUIでerror(§63)。

### Non-functional

- **セキュリティ**(§33, §62): `os.system` / `shell=True` 禁止。YAML・`/proc`・Herdr由来の
  文字列は data であり command として実行しない。editor は設定済argvのみ実行。
- **性能**(§64, §65): idle polling なし。context取得は表示時のみ。file監視は event-driven。
- **ログ**(§61): 標準 logging、既定 warning。個人情報・terminal buffer を記録しない。
- **構造**(§77): compositor 依存は `context/wayland`(+ fallback `context/wayfire`)、Herdr依存は
  `context/herdr` に隔離。UIは `ResolvedContext` のみを受け取り、compositor/Herdr CLI を直接呼ばない。YAML schema を
  理由なく変更しない。外部APIが想定と異なる場合はadapter内部を変え、上位仕様は変えない。

## Success criteria

- 設計書 §74 Acceptance Criteria 全項目。
- 実機テスト §69 (Test 1–11、labwc と Wayfire の双方。手順は `docs/DESIGN.md` の実機
  チェックリスト): 右上表示、元アプリへの入力継続、toggle、別outputからの起動、
  output override、px/%サイズ、Search時のみ入力可、Search後にgrabが残らない、
  gvim Edit in editor(sheetが開き該当行へjump)。
- Herdr実機テスト §70: bash → Herdr hints、Claude Code / Codex → 各hints + Herdr指定tag、
  unknown foreground → Herdr hints。
- §71 editor行jump、§72 閉じずにreload、§73 broken YAMLで crashせず last-known-good 維持
  → 修正で復帰。

## Open questions

- 依存確認(§78)は 2026-09-16 実施、結果は `docs/PHASE0.md`。未導入: gtk4-layer-shell(apt)、
  PyWayfire(PyPI 名 `wayfire`)、ruamel.yaml(PyPI)。2026-09-16 に pywayland を追加し labwc で
  foreign-toplevel 経由の取得と activate を確認。Wayfire は未起動で IPC socket は未確認。
- labwc / Wayfire 上で layer-shell `ON_DEMAND` が期待どおりfocusを得るか(§47)。実機確認まで未決。
- foreign-toplevel `activate` / Wayfire IPC でのfocus復帰(§48)が UI 経由でも安全に働くか。
