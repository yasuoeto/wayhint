# wayhint — Decisions

Lightweight ADRs. Newest last. One entry per decision that took discussion; a decision that was
obvious does not need one.

## 0001 — 実装言語は Python 3 + GTK4 / PyGObject / gtk4-layer-shell / PyWayfire

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: Wayfire 上の layer-shell overlay と Wayfire IPC(PyWayfire)、Herdr CLI 連携、
  YAML の行番号保持が必要。利用者は1人で、素早く育てられることが優先。
- **Decision**: Python 3。GUI は GTK4 + gtk4-layer-shell、compositor 連携は PyWayfire、
  YAML は ruamel.yaml。
- **Alternatives**: Rust/C(GTK/layer-shell binding は充実するが、個人用ツールの改修速度で劣る);
  Web 技術(Wayland layer-shell に乗らない)。
- **Consequences**: PyGObject と gtk4-layer-shell の Python binding が対象マシンに揃っている
  必要がある(§78 の依存確認が Phase 0)。起動は daemon 常駐で吸収する。

## 0002 — 名称は wayhint(設計書の context-hint から変更)

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: 設計書は `context-hint` / `context_hint` / `~/.config/context-hint/` を使うが、
  作業ディレクトリは既に `wayhint` で作られていた。
- **Decision**: リポジトリ・パッケージ・コマンド・設定ディレクトリをすべて `wayhint`
  (daemon は `wayhintd`、socket は `$XDG_RUNTIME_DIR/wayhint.sock`)にする。
- **Alternatives**: 設計書どおり `context-hint` で新ディレクトリを作る。名前の一貫性を取るために
  ディレクトリを増やす価値が無かった。
- **Consequences**: 設計書を参照するときは名称を読み替える。docs/PRODUCT.md 冒頭に読み替え規則
  を明記した。

## 0003 — YAML loader は ruamel.yaml

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: 「Edit hint」で hint の定義行へ editor を jump させるため、parse 結果に行番号が要る。
- **Decision**: ruamel.yaml(round-trip loader)を使い、各 hint の開始行を `SourceLocation`
  に保持する。GUI からの書き戻しは行わない。
- **Alternatives**: PyYAML(行番号を取るには Loader を拡張する必要があり、コメント保持もできない)。
- **Consequences**: 依存が1つ増える。将来 GUI 編集を足すときも構造保持で有利。
- **Amended**: 0014 により「GUI からの書き戻しは行わない」の部分は superseded。ruamel 採用は維持。

## 0004 — hotkey は compositor に委譲し、CLI ↔ daemon は Unix domain socket

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: global hotkey を Wayland client 側で取るのは困難で、compositor が担うのが自然。
  toggle の入口は1つに固定したい。
- **Decision**: compositor の keybinding(当初 Wayfire、0010 以降 labwc も)から `wayhint toggle` を実行。CLI は
  `$XDG_RUNTIME_DIR/wayhint.sock` へ送るだけ。ネットワーク socket は使わない。
- **Alternatives**: D-Bus(依存と定型が増える); daemon 自身で keybinding を取る(Wayland では
  不可・不安定)。
- **Consequences**: compositor ごとに keybinding 設定を書く(README「Compositor setup」)。
  socket path が runtime dir に依存する。

## 0005 — command は表示・copy のみ、実行しない

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: YAML は利用者が editor で頻繁に書き換える data。誤って実行される経路を作りたくない。
- **Decision**: V1 では `command` を実行する UI も API も持たない。`shell=True` / `os.system` を
  コード全体で禁止。実行するのは設定済 editor argv のみ。
- **Alternatives**: `executable: true` flag 付きで実行を許す(将来拡張候補として保留)。
- **Consequences**: 「hint から直接コマンドを走らせる」便利さを V1 で捨てる。security boundary は
  editor argv の1点に絞られる。

## 0006 — YAML schema の細部を Phase 1 で確定

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: 設計書 §21/§43 は項目名までで、型・既定値・エラー条件・一意性の範囲は決めていない。
  validate CLI(PRODUCT 要件 16)を実装するには確定が必要だった。
- **Decision**: `docs/DESIGN.md` Data model のとおり。要点: (a) size は int=px / `Npx` / `N%`
  (0–100)の 3 形のみ。(b) margin は int か 4 辺 mapping。(c) hint id の一意性は **sheet 内**、
  sheet id は全体で一意(editor jump は file+line で行うため hint id の全体一意性は不要)。
  (d) 未知 key は warning ではなく error(typo をすぐ気付かせる)。(e) `editor.command` は
  `{file}` 必須。(f) `version` は任意で 1 固定。(g) YAML の日付スカラーは ISO 文字列に正規化。
- **Alternatives**: 未知 key を無視する(将来の拡張に寛容だが typo を隠す); hint id を全体一意
  にする(sheet を跨いで同名 hint が自然に出るので不採用)。
- **Consequences**: schema を広げるときは validation と本 entry の更新が必要。unknown key を
  error にしたため、将来 key を追加すると古い版では読めなくなる(version で区別する)。

## 0007 — matcher の specificity は「一致した pattern 数」、category 順は初出順

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: PRODUCT 要件 7 の「priority → matcher specificity → file order」と要件 11 の
  「category order」は、何を specificity / category order とするか未定義だった。
- **Decision**: specificity = その sheet の match rule のうち実際に一致した regex pattern の数
  (argv_regex は name・argv 各要素・argv[0] の basename に対して、cmdline_regex は cmdline 全文に
  対して評価)。同点は sheet の読み込み順(ファイル名順)。category order は表示対象 hint 列に
  おける category の初出順(設定項目を増やさない)。
- **Alternatives**: pattern 長で比較(regex の長さは特異性を表さない); category の順序を config
  で指定(V1 では設定を増やさない方針)。
- **Consequences**: 特定の sheet を優先させたい場合は `priority` を使う。category の並びを変え
  たい場合は YAML 内の hint の順を変える。

## 0008 — IPC メッセージは 1 接続 1 リクエストの改行終端 JSON

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: DECISIONS 0004 で UDS は決めたが、メッセージ形式(1行テキスト or JSON)は未決だった。
- **Decision**: client は `{"cmd": "<toggle|show|hide|refresh|reload|ping>"}\n` を1つ送って
  書き込み側を閉じ、daemon は `{"ok": true, ...}` か `{"ok": false, "error": "..."}` を1つ返して
  切断する。上限 4096 bytes。未知の `cmd` は error。
- **Alternatives**: 1行テキスト(`toggle\n`)。将来 `show --sheet X` のような引数を足す時に再設計
  になるので JSON にした。長寿命接続 + event push は V1 に不要。
- **Consequences**: CLI 1 回 = 接続 1 回。daemon 側は GLib の IO watch で accept し、非同期に読む。

## 0009 — gtk4-layer-shell は ctypes で GTK より先に読み込む

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: labwc セッションでの smoke test で、`Gtk4LayerShell` typelib を Gtk より先に import
  しても `is_supported()` が False になり "GtkWindow is not a layer surface" 警告が出た。
  gtk4-layer-shell は libwayland-client をフックするため、プロセス内で先に load されている必要が
  あるが、PyGObject の typelib import 順では保証されない。
- **Decision**: `daemon.py` の先頭で `ctypes.CDLL("libgtk4-layer-shell.so.0", RTLD_GLOBAL)` を
  実行してから gi を import する。`LD_PRELOAD` を利用者に要求しない。
- **Alternatives**: `LD_PRELOAD` を wrapper script や systemd unit で設定(利用者側の設定が増え、
  `wayhintd` を直接叩くと再現しない)。
- **Consequences**: ライブラリのファイル名(soname)に依存する。見つからない場合は
  `Daemon.start` が `is_supported()` で検出して終了する。

## 0010 — desktop context は wlr-foreign-toplevel を既定にし、Wayfire IPC は fallback

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: 実機は X11 → Wayland 移行後 labwc をネイティブに起動しており、Wayfire は動いて
  いなかった。labwc には window を問い合わせる IPC が無い。両 compositor で同じコードを動かしたい。
- **Decision**: `context/wayland.py` が `wlr-foreign-toplevel-management-unstable-v1`(pywayland、
  生成コードは `protocols/*.xml` から `scripts/gen-protocol` で `_wlr_foreign_toplevel.py` に vendor)
  で activated toplevel の app_id / title / output を取り、`activate` で focus を返す。
  `context.backend: auto`(既定)は wayland を使い、protocol が無く `WAYFIRE_SOCKET` がある時だけ
  `context/wayfire.py` へ fallback。`ResolvedContext.view_id: int` は backend 不透明な
  `view_ref: str` に変更(wayland: `"<app_id>\t<title>"`、wayfire: view id 文字列)。
  YAML の `match.wayfire` は `match.wayland` に改名し、旧綴りも同義として読む。
- **Alternatives**: `ext-foreign-toplevel-list-v1`(activated 状態と activate 要求が無い);
  永続接続で handle を保持(event loop 統合が増え、compositor 再起動で stale になる。呼び出し毎
  接続の方針 0001 と合わせた); labwc 専用 adapter(問い合わせ手段が無い)。
- **Consequences**: pywayland が必須依存、PyWayfire は任意。pid が取れないので desktop 段の
  match は app_id のみ(従来どおり)。focus 復帰は同 app_id の window が複数で title が変わると
  失敗し得る。focused output は protocol に無く、複数 output で active toplevel が無い時は
  global fallback に落ちる。pywayland の proxy は display 切断前に destroy しないと GC 時に
  segfault するため、`_Session.close()` で明示破棄する。

## 0011 — daemon の起動・停止は compositor の autostart に任せ、service manager に登録しない

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: `wayhintd` をセッションと同時に起動し、compositor 終了時に確実に止めたい。
  systemd の user unit として `graphical-session.target` に紐づける案を検討した。
- **Decision**: compositor の autostart から通常のプロセスとして起動し、停止は compositor 側の
  shutdown 処理に任せる。wayhint は service unit を同梱せず、インストール手順にも含めない。
- **Alternatives**:
  - 永続 user unit + `WantedBy=graphical-session.target`: labwc は `labwc-session.target` を
    同梱せず、target を起動しないセッション構成が普通にあり、その場合 unit は起動しない。
    起動するかどうかが compositor の外の設定に依存するのは、hotkey が無反応になる形で失敗する。
  - transient unit(`systemd-run --user -p Restart=on-failure`): 自動再起動だけが上積みになる。
    overlay が落ちても他の作業は止まらないので、監視の価値がクラッシュの隠蔽と釣り合わない。
    実使用でクラッシュを観測したら再検討する(その時点では autostart 側の数行で済む)。
- **Consequences**: 起動・停止の作法は compositor ごとの autostart 規約に従う。異常終了しても
  自動復帰はせず、次のセッションまで hotkey は無反応になる。socket は SIGTERM で削除し、
  KILL された場合は次回起動時の stale socket 検出で回収する。

## 0012 — overlay の表示状態は workspace ごとに持ち、監視は開いている間だけ接続する

- **Date**: 2026-09-17
- **Status**: accepted
- **Context**: layer surface は output に属し workspace を持たないため、overlay は workspace を
  切り替えても出たままになる。呼び出した workspace でだけ見たい、という要望。最初は「切り替えたら
  隠す」だけを実装したが、実機で試したところ元の workspace に戻っても消えたままで、開き直しが要り
  使いにくかった。表示状態は window ではなく workspace の属性として持つのが正しい。
- **Decision**: daemon が workspace key → `ResolvedContext` の dict を持つ。`show` は現在の
  workspace に entry を足し、`hide` は現在の workspace の entry だけを消す。active workspace が
  変わったら、その workspace に entry があれば同じ context で出し直し、無ければ window を隠す
  (dict は触らない)。`toggle` は window の可視性ではなく「この workspace に entry があるか」で
  判断する。context は開いた時点の snapshot をそのまま出し直す(requirement 6 の凍結と同じ扱い。
  取り直したいときは更新)。監視は entry が 1 つでもある間だけ接続し、全て閉じたら切る。
  既定は `context.workspace: current`、`all` で従来動作。
- **Alternatives**:
  - 切り替えで隠すだけ(最初の実装): 戻っても消えたままで、workspace ごとに開いておけない。
  - 戻ったときに context を取り直す: workspace を往復するたびに Wayland と Herdr へ問い合わせが
    増え、見ていた内容が変わることがある。snapshot を出し直す方が既存方針と揃う。
  - `toggle` を window の可視性で判断: hotkey は socket、workspace 変更は Wayland 接続と経路が
    違い順序が保証されない。event が遅れると「押したのに出ない」になる。
  - 常時接続して監視: 何も開いていない間も接続と event 処理が残る。
  - compositor 側で layer surface を workspace に閉じ込める: labwc に該当設定は無く、protocol 上も
    layer surface は output 単位。
- **Consequences**: pywayland を import する module が 2 つになる(`wayland.py` と `workspace.py`)。
  `ext-workspace-v1` を出さない compositor では設定に関わらず従来動作。Wayfire は未確認のため
  未対応扱い。workspace の識別子は protocol の `id`、無ければ `name` で、labwc 0.20.2 は `name`
  のみ送る。compositor が workspace を消したら、その entry も落とす。overlay の開閉は watcher の
  event dispatch 中に呼ばれるため GLib の idle に逃がす。fd からは `read` で socket を空にする必要が
  あり、`dispatch` だけでは fd が readable のままになり watch が CPU を回し続ける。
- **Amended**: 0014 で amend(編集モード中の挙動)。

## 0013 — hotkey は別 window から押されたら閉じずに差し替える

- **Date**: 2026-09-17
- **Status**: accepted
- **Context**: window1 の hint を出したまま window2 に focus を移して hotkey を押すと、hint が
  閉じるだけで、window2 の hint を見るにはもう一度押す必要があった。hotkey の意味は「いま見て
  いるものの hint」であり、閉じたいのは既に同じものが出ているときだけ。
- **Decision**: `toggle` は押された時点の context を解決し、いま出ているものと比べる。同じなら
  閉じ、違えば差し替える。何も出ていなければ出す。比較は `ResolvedContext.target_key()` =
  (active_sheet, parent_context, desktop_app, foreground process 名)。
- **Alternatives**:
  - window を識別子で覚える: 使えるのは `view_ref` だが、中身は app_id と title で、terminal は
    実行中のコマンドで title を書き換える。数秒ごとに「別 window」と誤判定する。
  - `ext-foreign-toplevel-list-v1` の安定 identifier を使う: labwc は出すが、この protocol には
    focus 状態が無い。focus は `wlr-foreign-toplevel` 側にあり、両者を突き合わせる手段が
    app_id と title しかないため同じ問題に戻る。
  - 常に差し替える(閉じない): hotkey で閉じられなくなる。
- **Consequences**: `toggle` は閉じる場合も context を 1 回解決する(Wayland 往復と、Herdr 使用時は
  `herdr` 1 回)。同じ sheet に解決される 2 つの window の間では差し替えではなく通常の閉じるに
  なる。出る内容は同じなので見た目の破綻は無いが、window 単位の挙動ではない。
- **Amended**: 0014 で amend(編集モード中の挙動)。

## 0014 — hint 単位の構造化編集を GUI（編集モード）と CLI から行う

- **Date**: 2026-09-18
- **Status**: accepted
- **Supersedes**: 0003 のうち「GUI からの書き戻しは行わない」の部分、および PRODUCT.md Out of scope の「GUI 上での YAML 直接編集」
- **Amends**: 0012（workspace ごとの表示状態）、0013（hotkey は差し替え）
- **Alternatives**:
  - append-only の quick add のみ(編集・削除は editor): 誤入力の修正と不要 hint の削除で editor を
    開く負荷が残る。
  - 詳細 pane のインライン編集: 420px 幅で 12 項目のフォームは収まらず、既存 hint の編集は頻度が
    低い。
  - layer-shell ではない通常 window での編集: 「いつも同じ場所」の原則から外れ、editor との差が
    無くなる。
  - 作らず gvim 側を強化(snippet / template): capture の切り替えコストと match 規則の推測は
    editor では解けない。ただし CLI ルートはこの思想を引き継いで採用した。

### Context

0003 で ruamel.yaml を採用した時点では、書き戻しの動機が「既存 hint の修正」しかなく、それは外部 editor の方が優れていた。
そのため「GUI からの書き戻しは行わない」とし、PRODUCT.md でも GUI 編集を V1 の Out of scope に置いた。

その後 context 判定が compositor → application → Herdr pane → foreground process と階層化した結果、
hint を追加するコストの重心が「YAML を打つこと」から次の 2 つに移った。

1. **捕まえる瞬間の切り替えコスト。** 操作を調べた直後に hint を残したいのに、editor を開き、
   `hints:` の末尾を探し、YAML の構造を思い出して書く、という作業が「脳のコンテキストスイッチ」として重い。
   editor の snippet / template で削れるのは「型を思い出す」部分だけで、切り替え自体は editor である限り残る。
2. **sheet が無い context に最初の hint を書くコスト。** 重いのは YAML の形ではなく `match` 規則で、
   「この context は app_id で判定されたのか、Herdr 内の process で判定されたのか、regex は何を書けば当たるのか」を
   人間が他の sheet を見て推測している。この答えは daemon が `ResolvedContext` として既に持っており、
   editor 側の template では原理的に埋められない。

したがって書き戻しを「daemon が持っている情報で埋められる、hint 単位の操作」に限定して daemon 側に置く。
これは「GUI で YAML を直接編集する」ことではなく、YAML を意識させない構造化編集である。

原則との照合: 容易な更新（capture の数秒化、sheet 新規作成の自動化）と位置の安定（overlay の中で完結）を満たす。
foreground application を邪魔しないことに対しては、keyboard を握る範囲を編集モード中に限定し、
編集する瞬間は元アプリを触っていない瞬間である、という整理で許容する。

### Decision

#### D1. 操作の範囲

GUI（編集モード）と CLI の両方から、hint 単位の次の操作を行う。両者は同じ純粋関数を使う。

| 操作 | GUI | CLI |
|---|---|---|
| 追加（quick add） | `a` | `wayhint add` |
| 編集（5 項目） | `Enter` | `wayhint edit ID ...` |
| 削除 | `d` `d` | `wayhint remove ID` |
| favorite toggle | `f` | `wayhint favorite ID [--off]` |
| 並び替え（隣と swap） | `J` `K` | `wayhint move ID up\|down` |

GUI / CLI で扱う項目は **title / kind / key または command / category / remark** の 5 つと favorite。
それ以外（`id` `tags` `copy` `source` `learned`、sheet メタ、`match`、category の並び順）は外部 editor でのみ変更する。

補助コマンドとして `wayhint format`（正規化）と `wayhint schema`（JSON Schema 出力）を追加する。

#### D2. 書き戻し規則

- ruamel.yaml round-trip。`typ="rt"`、`preserve_quotes=True`、`indent(mapping=2, sequence=4, offset=2)`、`width` は折り返しが起きない大きさ。
- **書き込む際は 12 項目すべてを canonical 順（`id` `title` `kind` `key` `command` `category` `tags` `favorite` `copy` `remark` `source` `learned`）で出力し、未設定は null（`key:` のみ）とする。** 読み込む際は key の順序と省略を問わない。
- 正規化するのは操作対象の hint のみ。他の hint、sheet メタ、コメント、空行、quote style、flow style は触らない。
- 新規 hint の `tags` は flow style（`tags: [a]`）で出力する。
- 書き込みは同一ディレクトリの tmp ファイル（拡張子は `.yaml` / `.yml` 以外、例 `<name>.yaml.tmp`）に出力し、
  **既存の validation（未知 key / 重複 id / 不正 regex 等）を通した上で** `os.replace` する。validation 失敗時は書かずにエラーを表示する。
- 既存 sheet は元ファイルの `st_mode` をコピーする。新規 sheet は umask に任せる。
- 同時編集は後勝ち。mtime 比較は行わない。保存時に対象 hint の `id` が見つからなければ「外部で変更された」としてエラー表示し、reload に任せる。
- 自分の書き込みによる FileMonitor の再 parse は抑止しない。reload 後、選択位置とスクロール位置は hint `id` で復元する。`id` が消えていれば index で fallback する。
- コメントの扱い: hint の移動では、その hint の直前ブロックコメント（`ca.items`）を移動先へ付け替える。削除では直前ブロックコメントも一緒に消す（「hint の直前コメントはその hint の説明」という慣習に従う）。行末コメントは hint に属し追随する。
- 壊れた YAML を last-known-good で表示している間（`⚠ YAML error` 状態）は、round-trip できないため編集モードへの入場を拒み、理由を表示する。

#### D3. keyboard grab と状態遷移

- overlay の状態を `normal` / `search` / `edit` の 3 つとし、`keyboard_mode` は **状態から導出する 1 つの関数**（`_sync_keyboard_mode()` 相当）でのみ設定する。`normal` = NONE、`search` / `edit` = EXCLUSIVE（`ON_DEMAND` では compositor が focus を渡すのにsurface への再クリックが要り、検索ボタンを押しても入力が下のアプリに行く。labwc 0.20.2 で確認）。
  hide、workspace 離脱、Esc、hotkey の全経路がこの関数を通る。「grab の残留禁止」の不変条件はここで守る。
- 一覧の単打キーと `Tab` / `Shift+Tab` は CAPTURE フェーズの `EventControllerKey` で受け、GTK 組み込み（ListBox の行操作、Tab の focus 移動）より先に処理する。テキスト欄の `Enter` / `Esc` は input method に先に渡し、bubble フェーズで受ける（変換の確定・取り消しを奪わないため）。
- 編集モードへの入口は **compositor keybinding → `wayhint edit-mode`（IPC コマンド新設）を主、toolbar ボタンを併設**。
  通常表示は NONE のため overlay 上の key では入れない。
- 編集モード中は下部に key 割当の一覧を表示する。
- 保存後も編集モードに留まる。`Esc` で抜ける。

#### D4. 0012 / 0013 との関係（amend）

- **workspace 切り替え（0012 の延長）**: 編集状態と未保存の下書きは workspace ごとに保持する。離れると overlay は隠れ `NONE` に戻り、戻ると grab を張り直して編集中の内容のまま復帰する。
  下書きはメモリのみで、ファイルには持たない。
- **hotkey（0013 の例外）**: 編集モード中の hotkey は「差し替え」ではなく overlay の **hide / show** とする。
  hotkey の意味は「いま見ているものの hint」だが、書き込み中は「いま書いているもの」に置き換わっていると解釈する。
  入力を破棄する経路は `Esc` のみ。

#### D5. quick add

- 入力項目: title（必須）/ kind（選択、既定 `shortcut`）/ key と command（kind が決める: `shortcut` → `key`、`command` → `command`、`tip` → 両方、`note` → どちらも無し。tip と note は覚え書きで、tip は「これを押す、または これを実行する」を 1 つの hint に書ける。2026-09-18 に amend）/ category（任意）/ remark（任意）。
- 自動設定: `id` は title から slug 生成（`^[A-Za-z0-9][A-Za-z0-9._-]*$` に合わせ、衝突時 `-2` `-3`、slug が空なら `q-YYYYMMDD-HHMMSS`）。以後 GUI では変更しない。`learned` は当日、以後 GUI では変更しない。`favorite: false`、他は null。
- category 未入力（null）は「未 curate」の印として扱い、表示側で i18n ラベル（en `inbox` / ja `未定義`）の擬似 category として末尾にまとめる。**YAML に書く値は locale に依存させない。**
- 追加先は現在 context の active sheet。`Ctrl+P` toggle で親 sheet に切り替え、その場合 `effective_parent_tags` の tag を `tags` に付与する。
- active sheet が無い context では sheet を新規作成する（D6）。

#### D6. sheet の自動生成

- ファイルは `~/.config/wayhint/hints/<slug>.yaml`。`id` / `title` は context の app 名または process 名から生成し、sheet id 衝突時は `-2`。`priority` は既定値、`version` は省略。
- `match` は `ResolvedContext` から生成する。`parent_context` が None なら app_id 一致、`parent_context` があり process で解決していれば `process.argv_regex: ["^<name>$"]`。
- process 名が汎用名（`python3` `python` `node` `sh` `bash` 等。一覧は 1 箇所の定数で持つ）の場合は matcher と同じ規則で `argv[1:]` の basename を候補とする。非汎用の候補が 1 つも無いときだけ警告を出す。
- app_id から作る regex は `re.escape` した完全一致とする（`.` を含む app_id で必要）。
- 汎用名の候補生成では `-` で始まる引数（オプション）を候補から除く（`bash -l` から `^-l$` を作らない）。
- 生成ファイルの先頭に、生成日時・判定に使った context 情報・採用した regex をコメントで残す。
- config `editor.schema_modeline: bool`（既定 false）が true なら、先頭に `# yaml-language-server: $schema=...` を付ける。`$schema=` に書く path は config `editor.schema_path`（既定 `~/.config/wayhint/schema.json`）。`wayhint format` も同じ設定を見る。

#### D7. 表示順の変更

従来: favorite → category 初出順 → YAML 記述順。
変更後: **favorite 区画は category を無視して YAML 記述順**、非 favorite 区画は、非 favorite の hint だけで採番した category 初出順 → YAML 記述順。
これにより favorite 同士を category を跨いで並び替えられる。並び替えは YAML 上の位置 swap で実装し、swap は他 hint の相対順を変えない。
副作用として、ある category の最初の hint を favorite にすると、非 favorite 区画でその category の位置が動き得る（favorite 化は意図的な操作なので許容する）。

#### D8. 並び替えの制約

- `J` `K` は画面上の隣と swap する。隣が別グループ（favorite / 非 favorite、または非 favorite 区画で別 category）なら動かさない。category を変えたい場合は編集で category を書き換える。
- 隣が別 sheet（親 sheet から混入した hint）なら動かさない。ファイルを跨ぐ移動はしない。
- 検索・category フィルタ中も `J` `K` は可。swap 意味論のため、フィルタで隠れている hint を飛び越える形になるが他の順序は保たれる。

#### D9. 親 sheet から混入した hint

編集・削除・favorite は所属 sheet のファイルに書く。所属 sheet の同一性は `hint.location.file` で判定する。並び替えは D8 のとおり sheet を跨がない。

#### D10. category フィルタ

検索モード内で `#category` 構文（先頭トークンのみ）と `Tab` / `Shift+Tab` 巡回の両方を提供する。
両者は同じ 1 つのフィルタ状態を書く。`#` 入力途中の `Tab` は補完。巡回順は全表示 → category 初出順（擬似 category を含む）→ 全表示。
フィルタ状態は表示セッション限りで揮発する。

#### D11. IPC / CLI

- IPC に `context`（`ResolvedContext` の必要フィールドのみを返す）と `edit-mode`（編集モードに入る）を追加する。
- CLI は `context` の結果で sheet を決め、**daemon を経由せず自分でファイルに書く**。adapter は daemon 側に留まり、書き込み関数は GUI と共有する。FileMonitor が変更を拾い overlay が更新される。

### Consequences

- docs の更新: PRODUCT.md Out of scope、DESIGN.md（schema 表・表示順・実機チェックリスト・編集モード仕様）、README のフィールド表と compositor 設定例、AGENTS.md §4 の「ui/ は ResolvedContext だけを受け取る」を実態に合わせる、STATUS.md。
- 「あとは書きたいものだけ書く」は「省略可。GUI / CLI / format が書く hint は 12 項目を null 込みで出力する」に改める。既存の手書き sheet は `wayhint format` で手動一括正規化する。
- yaml_store.py に dump 経路と hint 操作の純粋関数を追加し、golden test（round-trip byte 一致、コメント付き hint の移動・削除、null 表記、flow style 保持）を追加する。GUI 部分は実機チェックリストへ。
- 0003 の「GUI からの書き戻しは行わない」は superseded。ruamel 採用の判断自体は維持。
- Wayfire は未確認のまま keyboard grab を握る面積が増える。実機チェック項目で確認する。
- 後日の改修候補: 親 sheet 混入 hint の並び替え、Tab の focus 移動との競合、filter の永続化。

## 0015 — labwc に合わせた配色は既定 CSS ではなく `examples/style.css` で配る

- **Date**: 2026-09-18
- **Status**: accepted
- **Context**: 既定 CSS(`ui/style.py` の `DEFAULT_CSS`)は Catppuccin Mocha 風(紫寄りの `#1e1e2e`、
  角丸 10px)で、実機の labwc(テーマ `Syscrash`、`cornerRadius` 0、OSD を waybar と同じ黒基調に
  する `themerc-override`)から浮いていた。overlay は compositor の OSD と同じ役どころなので
  そこに合わせたい。一方で既定 CSS を書き換えると、アプリの「設定なしの見た目」が 1 台の
  テーマに固定される。CSS の層は 2 つあり、`style.css` は `PRIORITY_USER` で既定に勝つ。
- **Decision**: 既定 CSS は中立のまま変えない。labwc 用の配色は `examples/style.css` として
  リポジトリに置き、実配置は `~/.config/wayhint/style.css` へコピーして使う。色の出典は
  Syscrash の themerc と labwc の OSD 色で、CSS 内のコメントに対応を残す
  (panel = `osd.bg.color`、header = `window.active.label.bg` の縦 gradient、選択行 =
  `menu.items.active`、button = `window.active.button.*`、accent = `#9fbfc1`)。テーマに対応色が
  無い warning / critical だけ desktop 側で使っている `#ffcc00` / `#f53c3c` を使う。
- **Alternatives**:
  - 既定 CSS を書き換える(最初に実装した案): 設定ファイル無しで labwc に馴染むが、リポジトリの
    既定が 1 台のテーマに寄る。ユーザーの判断で不採用。
  - GTK テーマの色を使う(`@theme_bg_color` 等): 実機の GTK テーマは light Adwaita で、
    layer-shell の overlay としては明るすぎ、labwc の OSD とも揃わない。
  - themerc を実行時に読んで色を生成する: Openbox の gradient と GTK CSS が一対一でなく、
    テーマが無い環境の fallback も要る。得られるのは追随性だけで V1 の価値に見合わない。
- **Consequences**: 実配置はリポジトリ外なので、`examples/style.css` を直しても
  `~/.config/wayhint/style.css` は自動では変わらない(コピーし直す)。`style.css` を読むのは
  daemon 起動時の一度だけなので、変更には再起動が要る。既定 CSS が下に残るため、上書き側は
  `opacity` のように「既定で付いている」property を明示的に戻す必要がある(実例:
  `.wayhint-context` の `opacity: 1`)。`cp -r examples/. ~/.config/wayhint/` は style.css も
  入れるので、既定の配色で使いたい場合は消す必要がある。色の検証は自動化できず、
  `./scripts/check` が見るのは既定 CSS が parse できることまで。

## 0016 — toolbar の「更新」ボタンを外す(IPC / CLI の `refresh` は残す)

- **Date**: 2026-09-18
- **Status**: accepted
- **Amends**: 0012（「取り直したいときは更新」の記述）、0013（hotkey は差し替え）
- **Context**: `refresh` は「表示中なら `show()` をやり直す」= context の再判定で、YAML の
  読み直しではない(そちらは file monitor の自動 reload)。効くのは「overlay を開いたまま別の
  window に移った」場面だけで、同じことは 0013 で hotkey の押し直しでもできるようになっていた。
  7 個並んだ toolbar の中で、押す理由が説明しにくいボタンになっていた。
- **Decision**: toolbar から「更新」を外す。`HintWindow` の `on_refresh` も消す。IPC の
  `refresh` と CLI の `wayhint refresh` は残す(マウスしか使えない場面と script 用)。
- **Alternatives**:
  - 残して tooltip で説明する: 押す理由が hotkey と重なる事実は変わらない。
  - `refresh` 自体を消す: CLI から context を取り直す手段が無くなる。overlay を閉じずに
    確認したい場面(実機テスト含む)で使う。
- **Consequences**: マウスだけで context を取り直す手段が overlay 上から無くなる
  (端末から `wayhint refresh`、または hotkey)。README の toolbar 表と PRODUCT.md §11 の
  「再判定」の記述を hotkey / CLI に書き換えた。i18n の `Refresh` は両カタログから削除。


## 0017 — 外部 editor は sheet 全体のキュレーション用の 1 ボタンにまとめる

- **Date**: 2026-09-18
- **Status**: accepted
- **Amends**: 0014（編集モードと外部 editor の役割分担）
- **Context**: 0014 で hint 単位の追加・修正・削除・並べ替えが overlay の中でできるようになり、
  外部 editor を開く動機は「1 件を直す」から「sheet 全体を見直す」に移った。それでも toolbar には
  「ヒントを編集」と「シートを編集」が並んでいた。両者は開くファイルが同じ（0014 以降、
  「シートを編集」も選択中 hint の sheet を開く）で、違いは該当行へ jump するかどうかだけ。
- **Decision**: 2 つを **「エディタで編集」** 1 つに統合する。選択中の hint があればその hint の
  file を該当行で開き、無選択なら表示中の sheet を先頭から開く。`editor.edit_target` が
  「hint の location が sheet に勝つ」を既に実装しているので、両方を渡すだけで足りる。
- **Alternatives**:
  - 「シートを編集」だけ残す: 行 jump は sheet が長いほど効く。捨てる理由が無い。
  - 「ヒントを編集」だけ残す: 無選択のとき押せないボタンになる（実際、選択に応じて sensitive を
    切り替えていた）。
- **Consequences**: toolbar は 検索 / コピー / エディタで編集 / 編集 / 閉じる の 5 個になった。
  「選択中の hint だけを開く」「sheet を必ず先頭から開く」を選び分ける手段は無くなった。
  i18n の `Edit hint` / `Edit sheet` は `Edit in editor` に置き換え、選択有無で editor ボタンの
  sensitive を切り替える処理も消した。


<!--
Entry format (this block is an example, not an entry -- it is kept as a comment so that it cannot
be mistaken for one, and so the first real decision gets number 0001):

## NNNN — Title of the decision

- **Date**: YYYY-MM-DD
- **Status**: accepted | superseded by 000N | rejected
- **Context**: what forced a choice, and what constrained it.
- **Decision**: what was chosen, in one or two sentences.
- **Alternatives**: what else was considered, and why it lost.
- **Consequences**: what this now costs or forecloses.
-->
