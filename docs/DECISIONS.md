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
- 生成した sheet は、その場で表示中の view の `active_sheet` になる。`active_sheet` は context を 解決した時点（show）でしか決まらないため、これをしないと file monitor の reload が来ても 一覧に出ず、次の quick add が二つ目の sheet を作ってしまう。
- config `editor.schema_modeline: bool`（既定 false）が true なら、先頭に `# yaml-language-server: $schema=...` を付ける。`$schema=` に書く path は config `editor.schema_path`（既定 `~/.config/wayhint/schema.json`）。`wayhint format` も同じ設定を見る。

#### D7. 表示順の変更

従来: favorite → category 初出順 → YAML 記述順。
変更後: **favorite 区画は category を無視して YAML 記述順**、非 favorite 区画は、非 favorite の hint だけで採番した category 初出順 → YAML 記述順。
これにより favorite 同士を category を跨いで並び替えられる。並び替えは YAML 上の位置 swap で実装し、swap は他 hint の相対順を変えない。
副作用として、ある category の最初の hint を favorite にすると、非 favorite 区画でその category の位置が動き得る（favorite 化は意図的な操作なので許容する）。

#### D8. 並び替えの制約

- `J` `K` は画面上の隣と swap する。隣が別グループ（favorite / 非 favorite、または非 favorite 区画で別 category）なら動かさない。category を変えたい場合は編集で category を書き換える。
- 隣が別 sheet（親 sheet から混入した hint）なら動かさない。ファイルを跨ぐ移動はしない。
- ~~検索・category フィルタ中も `J` `K` は可。~~ **撤回（0020）**。検索中は入力欄に focus があり、フィルタを確定したあとも語を足したり消したりして絞り込みを変える使い方をするため、`J` `K` を一覧に渡すには入力欄から focus を奪うことになる。並び替えは検索を終えてから行う。

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
- **改修(2026-09-23): `↑` `↓` の選択移動は GTK 既定ではなく自前で受ける。** 当初の仕様は
  「GTK 既定を使う」だったが、keyboard を EXCLUSIVE で掴んだ layer surface では window が
  一覧に与えた focus が定着しない——`grab_focus()` は true を返すのに AT-SPI はどの行も
  focused と報告せず、最初の矢印キーは「一覧に入る」だけで消える(labwc 0.20.2 実測)。
  そのため**マウス無しでは 2 行目以降に `f` / `J` / `K` / `Enter` / `d` `d` が当たらない**
  ——hotkey で開く overlay としては成立しない状態だった。他の単打キーと同じ CAPTURE の
  経路に乗せ、移動先は `editmode.next_selection()` で決める(端で折り返さない。短い一覧で
  先頭へ戻るのは「効かなかった」と区別がつかない)。テキスト欄ではカーソル移動なので受けない。
  紹介動画の脚本を書いているときに見つかった(B-7)。検証は `tests/test_gui_headless.py` の
  `EditModeKeyboardTest`——実 compositor で `↓` を送り、選択が動いたことと、次の `f` が
  **その行**に効いたことの両方を見る。

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


## 0018 — overlay は角の grip で手動リサイズし、サイズは config.yaml に書き戻す

- **Date**: 2026-09-18
- **Status**: accepted
- **Context**: 幅・高さは `config.yaml` の `overlay.width` / `height` でしか変えられず、
  ちょうどいい大きさを探すのに「編集 → 保存 → 開き直す」を繰り返す必要があった。layer surface
  には compositor 側の frame も interactive resize も無いので、掴む場所はアプリが自分で出すしか
  ない。サイズは「いつも同じ大きさで出る」(最重要原則の位置の安定)ために永続化が要る。
- **Decision**: anchor の反対側に grip を `Gtk.Overlay` で重ね、`Gtk.GestureDrag` で掴んで
  伸縮させる。角(16px)は縦横同時、自由な 2 辺に置いた 6px の帯は幅だけ・高さだけを変える。drag 終了時に daemon が `config.yaml` の `overlay.width` / `height` を
  **px** で書き戻す。書き込みは sheet と同じ atomic write + 事前 validation
  (`write_config`)で、ruamel の round-trip なので手書きのコメントは残る。file monitor が
  reload するので、次の表示・再起動後も同じ大きさになる。適用は global(sheet ごとではない)。
- **Alternatives**:
  - サイズを別の state ファイル(`~/.local/state/wayhint/`)に持つ: 設定と実行時状態は分かれるが、
    config.yaml を手で直しても state が勝つため、どちらが効いているのか分からなくなる。
  - メモリだけで保持: daemon 再起動で戻る。「いつも同じ大きさ」を満たさない。
  - sheet ごとに保存: sheet を切り替えるたびに大きさが変わり、位置の安定に反する。
  - compositor 側のリサイズに任せる: layer surface には無い。通常 window にすると
    「いつも同じ場所」が崩れる(0011 以前からの前提)。
- **Consequences**: 手で `60%` と書いていても、一度掴んで離せば px になる(% に戻すには手で直す)。
  GUI 操作が `config.yaml` を書き換えるようになった。壊れた config.yaml のときは書かずに
  `⚠` を出す。grip は overlay child なので当たり判定を奪う: 角 16px と、自由な 2 辺の 6px 幅の帯。
  toolbar の下 padding を 6px → 12px に広げ、帯が button に掛からないようにしてある。
  sheet ごとの `display` 上書きがある場合、書き戻すのは global 側なので、sheet 側の指定が
  勝ったままになる(その sheet では手動リサイズが効いていないように見える)。


## 0019 — hint の所属と workspace の編集状態を失わずに操作する

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014 D2 / D3 / D4 / D9
- **Context**: 実装監査 F1/F2 で、全 sheet から hint id だけで対象を選ぶ誤更新と、workspace 復帰時の
  フォーム混入、検索ボタンによる下書き破棄が判明した。
- **Decision**: hint の操作・フォーム・選択復元では所属ファイルと id の組を保持する。
  モード変更とキャンセルは daemon を経由し、復元時にはフォームの有無も適用する。
  編集中の検索ボタンは無効とし、検索するには先に編集を終了する。非表示の編集画面への
  `edit-mode` は context を再取得せず下書きを再表示する。
- **Consequences**: YAML schema は変更しない。検索と編集の同時使用は追加せず、D8 の
  「フィルタ中の J/K」の未実装は別件として残す。daemon の GUI import を起動時へ遅延し、
  window を fake にした headless の保存・状態遷移テストを追加する。


## 0020 — 監査の残件に対する方針（D8 撤回、重複 sheet id、scroll、adapter の失敗区別ほか）

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014 D8（撤回）、0008 / 0012 の記述整合
- **Context**: 実装監査 F3–F11 とその周辺で、仕様と実装が食い違う点、仕様自体が未決の点が残った。
  実装で決められるもの（不具合）と、使い方の判断が要るものを分けてユーザーに諮った結果をここにまとめる。
  前提として、このプロジェクトは Wayland 専用で主環境は **labwc**。Wayfire 固有の記述は adapter の
  一実装として扱い、実機確認と F7 / F10 の判断は labwc を正とする。
- **Decision**:
  1. **検索・フィルタ中の `J` `K`（0014 D8）は実装しない**。D8 のその一文は撤回する。フィルタ確定後も
     フィルタ内容を変える使い方をするので、入力欄から focus を奪う仕様は採らない。
  2. **reload 後の scroll は pixel 位置を復元しない**。復元した選択 hint が見える位置まで動かすだけとし、
     選択が復元できなければ先頭を見せる。スクロールバーは常時表示（overlay scrollbar を使わない）。
  3. **sheet の `id` はファイル名の stem と一致必須**とし、一致しないファイルは hint として読み込まない
     （Issue にして一覧には出さない）。rename やバックアップコピーで他人の id を名乗るファイルが増えても、
     どちらが効くかがファイル名次第という状況を作らないため。調査時点で生成物・fixture・examples・実配置の
     全 sheet が既に一致していた（`create_sheet` は `<slug>.yaml` を作るので生成側は常に一致する）。
     それでも `x.yaml` と `x.yml` のように stem が同じ組は残るので、**重複したときはファイル名昇順で先に
     読んだ 1 枚だけを使い**、後続は store に入れず Issue にして GUI に出す（メッセージに両方のファイル名。
     曖昧さを運任せにしない、設計書 §59）。
  4. **編集操作の前に debounce 待ちの reload を適用する**。favorite の toggle は file の値を反転する。
     200ms 以内の連打で「2 回目が効かない / 並び替えが戻る」ことを headless テストで再現してから直した。
  5. **fractional scaling のために `xdg_output` を bind しない**。`wl_output.scale` は整数のため論理サイズは
     概算のままとし、既知の制限として DESIGN に記録する。実機で fractional scaling を使う予定が出たら
     `xdg_output_manager` 利用（無ければ現行計算へ fallback）を別件として起こす。transform による
     縦横入れ替えと `mode` の CURRENT flag は実装する。
  6. **editor の起動後の異常終了は監視しない**。起動の失敗は従来どおり GUI に出す。
  7. **Wayfire adapter は IPC 失敗と window 不在を区別する**。snapshot に不可欠な呼び出しの失敗は
     `ContextError`（overlay は落とさず error 表示）、`None` は「focus されている window が無い」として
     desktop context に fallback する（設計書 §63）。
  8. **文書の矛盾は文書側で直す**。DESIGN の「IPC メッセージ形式は未決」は 0008 の内容に置き換える。
     AGENTS の「subprocess は editor だけ」に Herdr adapter を例外として明記する（固定 argv、
     `shell=False`、timeout 付き、YAML 由来の文字列を引数にしない）。
  9. **STATUS** は実機確認・常駐状態を推測で書き換えない。
- **Alternatives**: D8 を実装する（フィルタ確定で一覧へ focus を移す案。絞り込みの変更が主な使い方
  なので却下）; 重複 sheet を両方読む（どちらが効いたのか分からない）; scroll 位置を pixel で保存する
  （reload 後は行の並びが変わり得るので意味が薄い）; `xdg_output` を今 bind する（実機で必要になって
  いない）; Wayfire の失敗を従来どおり無視する（context が空なのか壊れたのか区別できない）。
- **Consequences**: YAML schema は変わらない。id がファイル名と違う sheet と、重複 id の 2 枚目以降は
  「読まれない」ので、そうした構成では表示が変わる（Issue で理由とリネーム先が出る）。手でファイル名を
  変えるときは `id` も一緒に変える必要がある。Wayfire の IPC 失敗は今後 error として見えるようになる
  （従来は無言で空の context）。

## 0021 — フォームの保存で編集モードを終える（単打キー操作は留まる）

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014（DESIGN「編集モード」§1 の「保存後も `edit` に留まる」を上書きする。0014 自体は
  そのまま残し、ここを参照する）
- **Context**: `edit` は EXCLUSIVE grab なので、留まっている時間はそのまま元アプリを邪魔する時間に
  なる（設計書 §81）。典型的な流れは「操作を忘れた → 調べた → 1 件書く → 作業に戻る」で、保存した
  瞬間に用は済んでいる。一方、favorite / 並べ替え / 削除 / undo は「何件かまとめて整える」操作で、
  `u` は `edit` 中でなければ押せない。
- **Decision**: フォーム（quick add と編集）の保存に成功したら `normal` に戻し、keyboard_mode を
  NONE にして前の view へ focus を返す。処理順は「書き込み成功 → mode 変更 → `_sync_keyboard_mode()`
  → focus 復帰」で、search 終了と同じ経路を使う。書き込みに失敗したとき、validation に失敗したとき、
  `Esc` で破棄したときは mode を変えない。単打キー操作（`f` / `J` `K` / `d` `d` / `u`）は従来どおり
  `edit` に留まる。§7 の sheet 新規作成を伴う quick add も `normal` に戻る。
- **Alternatives**: 全操作で留まる（現状。1 件書くだけでも Esc を押す必要があり、忘れると grab が
  残ったままになる）; 全操作で抜ける（`u` が押せなくなり、まとめて整える操作が成立しない）;
  「保存して留まる」を別キー（`Ctrl+Enter`）や config で選べるようにする（まず単純な形で使い、
  必要が出てから判断する）。
- **Consequences**: 続けて追加するときは `wayhint edit-mode` → `a` をもう一度押す。200ms 後の
  自己書き込み reload は `normal` の一覧に対して走るが、`_after_reload` の選択復元はそのままでよい。
  フォーム下部のヘルプを「Enter 保存して終了」に変える（en/ja）。

## 0022 — 「エディタで編集」はどのモードでも overlay を隠す

- **Date**: 2026-09-19
- **Status**: superseded by 0023
- **Context**: F9 の修正で `edit` / `search` のときだけ overlay を隠すようにしたが（EXCLUSIVE grab の
  ままではエディタに入力できないため）、`normal` では出したままだった。実機で使うと、同じボタンが
  押したときのモード次第で違う動きをするのが分かりにくい。エディタを開くのは「このファイルを見に行く」
  という操作で、overlay がエディタの上に残る必然性もない。
- **Decision**: 起動に成功したら、どのモードでも overlay を hide する。モードと下書きは保持し、次の
  hotkey で戻す。戻すときは同じ context なら開いていたものをそのまま再表示し、別 window から押された
  ときは 0013 のとおり差し替える（hide 中に hotkey が来たら閉じるのではなく開く、を全モードに広げた）。
  起動に失敗したときは隠さずエラーを表示する。
- **Alternatives**: `normal` だけ出したままにする（現状。ボタンの意味がモードで変わる）; hide せず
  grab だけ外す（`edit` / `search` でエディタに入力はできるが、overlay がエディタに被さったままになる）。
- **Consequences**: エディタを閉じたあと hint を見るには hotkey を 1 回押す。**エディタの終了を検知して
  自動で戻すことは、今の editor 設定（`gvim --remote-silent`）では実装できない**: すでに gvim が動いて
  いれば起動したプロセスは即終了し、動いていなければそのプロセスが gvim 本体になるため、子プロセスの
  終了は「エディタを閉じた」を意味しない。自動復帰が要るなら別の合図（保存による file monitor の
  イベントなど）を選ぶ必要があり、未決のまま残す。

## 0023 — 「エディタで編集」でも overlay は消さない（grab だけ外す）

- **Date**: 2026-09-19
- **Status**: accepted
- **Supersedes**: 0022（および F9 で入れた「`edit` / `search` のときだけ hide する」挙動）
- **Context**: 実機で使ってみると、外部 editor を開くのはほぼ sheet 全体のキュレーション作業で、
  書き換えた結果をその場で確かめたい。overlay が消えていると、保存 → hotkey → 確認 → また editor、と
  往復が増える。file monitor は保存を検知して reload するので、overlay が出てさえいれば結果は即座に
  画面に出る。
- **Decision**: 「エディタで編集」で overlay は隠さない。`search` / `edit` のときは Escape と同じ経路で
  `normal` に戻し（keyboard_mode を NONE にして前の view へ focus を返す）、editor が入力を受けられる
  ようにする。`normal` のときは何もしない。開いていた下書きは view に残し、次の `edit-mode` で開き直す。
  シートが更新されたら（editor の保存を file monitor が拾ったら）表示中の overlay をその場で更新する
  ——これは既存の reload 経路のままで、追加の仕組みは要らない。
- **Alternatives**: 全モードで hide（0022。キュレーション中に結果が見えない）; hide したうえで editor の
  終了を検知して戻す（`gvim --remote-silent` では子プロセスの終了が「editor を閉じた」を意味しないため
  作れない。0022 の Consequences 参照）; grab を保ったまま出しっぱなし（editor に入力できない。F9）。
- **Consequences**: editor で保存するたびに overlay の一覧が更新される（200ms の debounce のあと）。
  overlay は editor の上に出たままなので、editor の窓が overlay と重なる位置にあると隠れる部分がある。
  気になる場合は hotkey で消す。`search` / `edit` から押すと編集モードは終わる（下書きは保持）。

## 0024 — hint sheet は言語ごとのディレクトリに置き、UI と同じ言語のものだけを読む

- **Date**: 2026-09-19
- **Status**: accepted
- **Context**: UI は `appearance.language`（`auto` は locale）で en / ja を切り替えるのに、hint は
  1 つの `hints/` しか無く、日本語の sheet を置けば UI が英語でも日本語が出る。実際 repo の
  `examples/hints/` は英語、実配置は日本語で、同じ id の sheet が別言語で二重化していた。
  紹介動画のように en 版と ja 版を切り替えて見せたい場面もある。
- **Decision**: `hints/<lang>/` を 1 言語 1 ディレクトリとし、**表示に使う言語のディレクトリだけを読む**。
  解決順は `hints/<lang>/` → `hints/en/` → `hints/*.yaml`（フラット）。言語は UI と同じ
  `resolve_language()`（設定 → locale → 未知なら en）で、UI と hint の言語がずれない。読み書きは
  すべてこのディレクトリに対して行う（新規 sheet の作成、`wayhint format` の既定対象、file monitor）。
  言語設定を変えたら config の reload で読み直し、監視も張り替える。`hints/` 自体も監視して、
  あとから言語ディレクトリを作った場合に気付けるようにする。
- **Alternatives**: `hints/*.yaml` に両言語を混ぜ、sheet の `lang:` で振り分ける（ファイル名 = id の
  ルール 0020 と衝突する）; ベース + `hints/<lang>/` の上書きレイヤー（翻訳が無い sheet を自動で
  補える代わりに、1 画面に 2 言語が混ざる）; hint 単位で `title: {ja:…, en:…}`（schema と編集
  フォームが大きくなる）。フラットを廃止する案は、既存配置と 1 言語運用を壊すので採らない。
- **Consequences**: 同じ sheet を言語ごとに書くことになる（翻訳の同期は仕組みとして持たない。
  片方だけ編集してもずれたことは検出されない）。`examples/hints/` は `en/` と `ja/` に分けた。
  実配置は `~/.config/wayhint/hints/ja/` へ移動済み。`id` = ファイル名のルール（0020）は
  ディレクトリごとに成立するので、`ja/claude.yaml` と `en/claude.yaml` は衝突しない。

## 0025 — quick add は選択中の hint の sheet に書く

- **Date**: 2026-09-19
- **Status**: accepted
- **Amends**: 0014（DESIGN「編集モード」§3 の「追加先: active sheet」）
- **Context**: `nested.parent_tags` があると、一覧には active sheet の hint と親 sheet の hint が
  混ざって並ぶ。その状態で親 sheet の hint にカーソルを置いて `a` を押すと、見ているものとは別の
  sheet（active sheet）に追加されていた。編集・削除・favorite・並べ替えは既に「選択中の hint の
  所属ファイル」に対して行う（0019）ので、追加だけが違う基準で動いていたことになる。
- **Decision**: quick add の追加先は**選択中の hint の所属 sheet**。未選択、または所属ファイルが
  消えているときは active sheet、それも無ければ従来どおり保存時に sheet を新規作成する（0014 D6）。
  どこに入るのかが選択によって変わるので、フォームの見出しに追加先の sheet 名を出す
  （`Ctrl+P` で親 sheet に切り替えたときも見出しが変わる）。
- **Alternatives**: active sheet のまま（他の編集操作と基準が食い違う）; 追加先を選ぶ UI を出す
  （1 件足すだけの操作に選択肢を増やしたくない）。
- **Consequences**: 親 sheet の hint を見ながら `a` を押すと親 sheet に入る。active sheet に入れたい
  ときは、その sheet の hint を選んでから押すか、一覧の選択を外す。見出しを見れば分かる。

## 0026 — 他の sheet の hint を混ぜる手段は sheet 側の `include` 1 本にする

- **Date**: 2026-09-19
- **Status**: accepted
- **Context**: 表示は active sheet と nested 親 sheet の 2 枚に固定で、無関係な sheet を混ぜる手段が
  無かった。要望は 3 つ——(A) WM 操作や IME のような共通 hint を全 sheet に、(B) 特定の組み合わせ
  (claude を見るときは git も)、(C) 役割の束(terminal 系の共通部分)。混ざった hint の配管は既に
  ある(`(ファイル, id)` で識別 0019、編集は所属ファイル 0014 D9、`J`/`K` はファイルを跨がない D8、
  表示順 D7)ので、足りないのは「どれを混ぜるか」の指定だけだった。
- **Decision**: sheet に `include: [sheet-id, ...]` を足し、この 1 本で 3 つとも表す。
  config.yaml のトップレベル `include: []` は、`include` を書かない sheet の既定
  (`inherit.parent_tags` と `nested.parent_tags` の関係と同じで、**足し算ではなく置き換え**)。
  include 先の hint は tag で絞らず全部入れ、量は共通 sheet を小さく作る運用で抑える。多段は
  辿らない。重複は `(ファイル, id)` で落とす。`match` の無い sheet を許可し、それは active には
  ならず include 経由でだけ出る。解決できない id と自己参照は **warning**(`Issue.severity`)で、
  その id だけ無視して sheet は表示する。表示は今の親 hint と同じ無印。IPC `context` の応答に
  解決済みの `include` を足す。詳細欄に所属ファイル名を出す(どのファイルが書き換わるかの目印)。
- **Alternatives**: 提供側に書く `applies_to`(画面から逆引きしづらい); tag ベースの
  `always_tags`(どの hint が全画面に出るか一覧しづらく、混入経路が 2 本になる); include 要素の
  tag 絞り `{sheet: x, tags: [...]}`(記法が重い。共通 sheet を分ければ足りる); 多段 include
  (循環検出が要る割に用途が無い); include 由来 hint の専用ヘッダー(親 hint と扱いを変える理由が無い)。
- **Consequences**: 一覧が長くなりやすい(件数上限は入れない)。編集モードの規則は変えないので、
  include 由来 hint の編集・削除・favorite は所属ファイルに書き、`J`/`K` はファイルを跨がず、
  quick add の追加先は選択中の hint の sheet(0025)のまま。`Issue` に severity が入ったので、
  `wayhint validate` は error のときだけ exit 1 になる。

## 0027 — terminal の foreground process は `/proc` から取り、nested 解決は desktop sheet の有無から切り離す

- **Date**: 2026-09-19
- **Status**: accepted
- **Context**: nested context を答えられるのは Herdr だけで、foot のような素の terminal
  emulator では「端末の窓」以上のことが分からなかった。端末は自分が何を動かしているかを
  外に教えないが、`/proc` には答えがある——端末の子孫のうち、tty の foreground process group
  (`pgrp == tpgid`)に居るものが、まさにユーザーが今触っているコマンドである。
  同時に 2 つの前提が表面化した。(1) `ContextResolver` は **desktop sheet がある時しか**
  nested provider を呼んでいなかった。Herdr には `herdr.yaml` が必ずあるので今まで当たらなかった
  制約だが、terminal 用の sheet を書く人はまずいないので ProcAdapter は一度も走らないことになる。
  (2) `match_rule_for_context` が `parent_context is None` を「app_id で決まった」の判定に
  使っていたため、foot 上で quick add すると foot の app_id に一致する sheet が生成されてしまう。
- **Decision**: `context/proc.py` に `ProcAdapter` を足す(現行の `NestedContextProvider`
  interface のまま。`applies_to` は `TERMINAL_APP_IDS = {"foot", "footclient"}` の定数、
  `foreground_process` は `/proc` を pathlib で直読みし、subprocess は使わない)。
  nested 解決は **app_id が何かだけで決める**——`ContextResolver` から
  「desktop sheet がある時だけ」の条件を外し、`parent_context` は desktop sheet がある時だけ
  入るようにする。`match_rule_for_context` と `create_sheet` の判定材料を `parent_context` から
  `foreground_process` に変える。登録順を決める場所は `daemon.nested_providers()` の 1 か所に
  まとめ、2 群(terminal introspection / nested resolver)をそこにコメントで書く。
  IPC `context` に `chain`(問い合わせた provider のクラス名、順番どおり)を足す。
  `/proc` を読むのはこの 1 module だけ(AGENTS.md の隔離規則に追記)。
- **Alternatives**: **`NestedContextProvider` を `supports(ctx)` / `resolve(ctx)` に作り替え、
  resolver を深さ付きループにする**——`foot → tmux → herdr → claude` のような多段を将来
  まかなえるが、今要る 2 つの provider はどちらも「app_id を見て foreground process を返す」
  だけで現行の契約に収まり、多段の要求はまだ無い。interface の作り替えは実際に多段が必要に
  なった時点で行う(それまでは 1 段固定、`chain` は 0 か 1 要素)。
  **terminal ごとの専用 adapter**(WezTerm / Kitty / foot の control protocol)——`/proc` で
  足りるかを実機で見てから判断する。
  **ShellIntegration による title 解釈**——title は将来の tie-break 用途に留める。
  **Tmux / Ssh resolver**——多段 interface が要るので上と同じ理由で見送り。
  **`HerdrContextProvider.applies_to` を foreground process 名でも真にする**——多段が前提の
  変更なので今回は入れない。2026-09-20 の実機確認でこれが効く場面が出た: 素の kitty / Ghostty で
  `herdr` を起動すると app_id が `herdr` を含まないので Herdr 経路に乗らず、`/proc` 経路が
  「`herdr` というプロセスが動いている」までしか答えない。当面は**窓の app_id 側に `herdr` を
  入れる運用**で回避し(`docs/TERMINALS.md` の Herdr 節)、気づけるように
  `proc.SELF_REPORTING` で INFO ログを 1 行出すだけにした。多段を入れても Herdr の
  `focused: true` はセッション全体で 1 つなので、窓が 2 枚あるときに正しくなる保証は無い
  (0028 の `[要判断]`)。そこを測ってから判断する。
  **`TERMINAL_APP_IDS` を config 化**——項目の条件は「子孫としてコマンドを動かす terminal
  emulator である」という program の性質で、好みではない。
  **foot の server モード(1 プロセス多窓)で窓を絞り込む**——`/proc` だけでは窓とプロセスを
  対応付けられない。同名プロセスが 2 つ以上あれば**無判定**(`None`)で返す。誤った sheet は
  sheet が出ないことより悪い。窓の絞り込みが要るなら terminal 専用 adapter とセットで再考する。
  **examples に foot 用 sheet を置いて guard を残す**——sheet を書いたかどうかで context の
  判定が変わるのは原則(context は正しく判定する)に反する。
- **Decision(追記 2026-09-20、実機確認を受けて)**: 当初の「同名 process が 1 つでなければ無判定」は
  実機で一度も発火しなかった。作者の機械では foot の窓が常時 3〜4 枚あり、Herdr の窓も
  `--app-id=foot-herdr` の foot なので `comm` は同じ `foot` になる。terminal は複数窓が前提である、
  が正しい前提だった。調査した結果、**labwc では focus 中の toplevel の pid を知る手段が無い**
  ことが確定した——`zwlr_foreign_toplevel_manager_v1`(v3) にも `ext_foreign_toplevel_list_v1` にも
  pid は無く(実機の `wayland-info` で確認)、labwc 0.20.2 に IPC は無く(`--help` / man で確認)、
  foot にも問い合わせ口が無い。そこで **窓の側が名乗る規約**にする:
  launcher が `exec foot --app-id "foot.p$$"` の形で起動し、adapter は compositor が返す app_id から
  `\.p(\d+)$` で pid を読み戻す(`matcher.APP_ID_PID_RE` / `strip_pid_suffix`。純粋なので
  `yaml_store` からも使える)。読み戻した pid は `comm` と照合してから使う——窓が閉じれば app_id は
  誰のものでもなくなり、その番号は別のプロセスに再利用されるため。照合規則は
  「base そのもの、または base の最後のドット要素」の 1 つにまとめ(`_is_process_of`)、接尾辞が
  無い app_id のときの「その端末の process が 1 つだけか」の判定にも同じ関数を使う
  (`com.mitchellh.ghostty` の `comm` は `ghostty`。`comm` は 15 文字で切れるので reverse-DNS 形は
  そもそも全体一致しない)。`NestedContextProvider.foreground_process` に
  `app_id: str | None = None` を足す(既定値付きなので既存の呼び出しは無変更)。
  `ResolvedContext.desktop_app` には接尾辞付きのまま入れ(窓が違えば context も違う)、
  **sheet の生成と overlay の表示は base を使う**——`^foot\.p12345$` の rule はその窓 1 枚にしか
  当たらず、context ラベルに launcher の内部事情を出す意味も無い。
  process の `name` は `exe` ではなく **`argv[0]` の basename** を優先する(login shell の先頭 `-` は
  落とす。argv が空なら `exe` → `comm`)。Debian の alternatives 経由だと `exe` は
  `/usr/bin/vim.gtk3` になり、ユーザーが打った `vi` で sheet を書けなくなる。実体名で当てたい
  ケースは `cmdline_regex` がある。
- **Alternatives(追記)**: **title で窓の中身を判別する**——`vim` / `neovim` は OSC で title を
  出すが `top` / `htop` / `less` / `more` は出さない。一番欲しいところで落ちるので採らない。
  title は将来 tie-break 用途に留める。
  **shell の preexec / PROMPT_COMMAND で title に実行中のコマンドを通知させる**——上の穴は
  埋まるが、title を出す TUI(`vim` 等)が起動直後にそれを上書きするので、今度はそちらが取れなく
  なる。shell 側の設定も要る。採らない。
  **対応端末を「自分で答えられるもの」に絞る**(kitty の `kitty @ ls`、WezTerm の
  `wezterm cli list-clients` → `tty_name`)——実機で両方とも動くことを確認した。kitty は
  `foreground_processes` を pid ごと直接返すので `/proc` すら要らないが、`allow_remote_control` /
  `listen_on` / `single_instance` の 3 行を kitty.conf に足す必要がある(2 つ目の kitty プロセスは
  同じ socket に bind できず `@ ls` から見えない)。Ghostty 1.3.1 には問い合わせ口が無い
  (man 全文で IPC の記述は `new-window` の 1 行のみ、D-Bus service も起動用)。
  app_id 規約なら端末を選ばず 1 本で済むので、今回はそちらを採る——kitty も `--class` で
  app_id を窓ごとに変えられる(既定で 1 窓 1 プロセス)ので規約に乗り、`kitty @ ls` も
  `allow_remote_control` / `listen_on` も、それを指す config 項目も要らなくなった。
  **WezTerm を今回の対象に含める**——WezTerm は窓ごとに app_id を変えられないので規約に乗らない。
  次に手を入れるときは `wezterm cli list-clients` → pane の `tty_name` → `/proc` の経路にする
  (実機で `/dev/pts/30 → vim` まで確認済み、端末側の設定は不要)。Lua の
  `pane:get_foreground_process_name()` は設定 Lua の中でしか呼べず、title に埋める方式は端末側の
  設定が要るので採らない。
- **Decision(追記 2026-09-20、レビュー指摘を受けて)**: 独立レビューで 3 点。
  (1) **1 つの端末の下に pty が複数あると誤答していた**。前面プロセスは pty ごとに存在するので、
  端末の PID が分かっても tab / split / `tmux` / `ssh -t` のどれが画面に出ているかは `/proc` から
  分からない。子孫から「最深・最大 PID」を採る実装は、外側の pty の `vi` より内側の pty の `top` を
  選んでしまう(fake `/proc` で再現)。**複数の tty が見つかったら無判定**にする。あわせて root 自身は
  候補から外す——別の端末から前景で起動された端末は*その*端末の前面プロセス群に居るだけで、
  自分が何を動かしているかとは無関係。
  (2) **接尾辞付き app_id が端末自身の sheet に一致していなかった**。
  `match_app([^foot$], "foot.p12345")` が `None`(再現済み)。sheet 生成と UI 表示では base を
  使っていたが、照合では生の app_id を渡していた。`app_specificity` が app_id と base の**両方**を
  候補にするようにする——base だけに正規化しないのは、たまたま `.p<数字>` で終わる app_id 向けに
  書かれた rule を壊さないため。候補が増えても 1 つの pattern は 1 つとしか数えないので、
  specificity の順序は変わらない。
  (3) **確認手順が観測で対象を変えていた**。端末の中で `wayhint context` を叩くと、その `wayhint`
  自身がその端末の前面プロセスになる。`vi memo &` も background なので前面プロセス群に居ない。
  手順を overlay の context ラベルを見る方法と、compositor の keybind から実行してファイルに
  落とす方法に差し替えた(`docs/TERMINALS.md`)。
- **[要判断](追記)**: 接尾辞が無い app_id で同名 process が複数あるときの、title / cwd 照合による
  絞り込み。今回は入れず無判定のままにした。
- **やらないこと(追記)**: **tab / split を持つ窓の pty 絞り込み**。端末自身に focus を聞く adapter
  (kitty の `kitten @ ls`、WezTerm の `wezterm cli list-clients`)が要る。`/proc` だけでは決められない
  ので推測しない。多段 resolver も新しい設定項目も依存も入れない。
- **Consequences**: terminal 用 sheet を書いていなくても、その中のコマンドの sheet が選ばれる
  ようになった。親が無いので parent tag の混入は起きず、その sheet の hint だけが出る。
  **wrapper を通さずに起動した端末の窓は、その端末の process が 1 つのときしか解決しない**
  (README「Terminal の複数窓」)。`ProcAdapter` は show / refresh のたびに `/proc` を 1 度走査する
  (polling は無い)。
  `/proc` が見えない環境(コンテナ、hidepid)では常に無判定になり、従来どおり何も変わらない。
  `chain` が増えたぶん IPC `context` の応答が伸びる(4096 byte 制限には余裕がある)。
  多段解決が要るようになった時点で `NestedContextProvider` の作り替えが必要になる。

## 0028 — Herdr は `HERDR_*` を除いた環境で呼び、focus 中の pane を解決する

- **Date**: 2026-09-20
- **Status**: accepted
- **Context**: Herdr の workspace に tab を並べて claude / codex / vi / lv / top を開く使い方で、
  どのタブに切り替えても **wayhintd を起動した pane の hint しか出なかった**。実機で切り分けた
  ところ、`herdr pane current` は環境変数 `HERDR_PANE_ID` があればその pane を返し、無いときだけ
  focus 中の pane を返す(`--current` を付けても同じ)。wayhintd を Herdr の pane の中から起動すると
  `HERDR_PANE_ID` を継承するので、adapter はセッションの間ずっとその pane を「current」と見なす。
  実機の wayhintd の環境にも `HERDR_PANE_ID=wH:p1` が入っていた。`pane process-info --pane <id>` は
  id が正しければ正しい process を返すので、壊れていたのは pane の特定だけだった。
- **Decision**: adapter が herdr を呼ぶときの環境から `HERDR_` で始まる変数を除く
  (`_herdr_env`、純粋関数)。これで `pane current` は本来の「focus 中の pane」を返す。
  **保険**として、`pane current` が `focused: false` を返したときだけ `pane list` を呼び、
  `focused: true` の pane が 1 つだけならそれを採る(0 個または 2 個以上なら pane 不明として
  従来の fallback = Herdr sheet のみに落とす)。`pane list` を常用する設計にはしない——
  `pane current` は 1 回の呼び出しで済み、環境さえ正せば正しい答えを返すため。
  呼び出し回数が 2 回から最大 3 回になるので、時間予算は call ごとではなく **lookup 開始時に
  決めた deadline** に対して使う。各 call には `min(CALL_TIMEOUT, 残り時間)` を渡し、
  残りが無ければ呼ばない。`LOOKUP_BUDGET` の値は変えないので `ipc.CLIENT_TIMEOUT` との関係も
  変わらない。変更は `context/herdr.py` に閉じる。
- **Alternatives**: **daemon 起動時に `HERDR_*` を一括 unset する**——daemon 全体の環境を書き換える
  のは影響範囲が広く、adapter の都合は adapter で閉じるべき。
  **`pane current` をやめて常に `pane list` から focus 中の pane を探す**——環境に依存しない点は
  同じだが、全 pane を毎回返させることになる(実機で 26 pane)。`pane current` は環境さえ正せば
  1 回で正しく答えるので、主経路はそちらに置き `pane list` は保険に留める。
  **wayhintd を Herdr の外から起動する運用にする**——回避策であって修正ではない。daemon の起動場所に
  よって context の解決結果が変わる設計自体が誤り。
  **`pane list` の `agent` フィールド(`claude` / `codex`)で sheet を選ぶ**——`vi` / `lv` / `top` は
  `agent` に出ないので結局 `process-info` が要る。経路を 2 本にする利点が無い。
- **Consequences**: wayhintd をどこから起動しても、Herdr のどのタブに切り替えても、そのタブの
  foreground process の sheet が出る。実機で確認済み(`HERDR_PANE_ID=w9:p3` を継承させた状態で
  focus 中の `wH:p1` の `claude` を解決)。Herdr の lookup は最悪 3 回の subprocess になるが、
  合計時間は従来と同じ上限のまま。`Runner` の signature に timeout が増えた
  (`Callable[[Sequence[str], float], str]`)。
- **[要判断] → 解消(2026-09-20)**: 「Herdr の窓を 2 枚以上開いているとき、focused pane が Wayland 側で
  active な窓に属するか」は、**問いが成立しないことが分かった**。Herdr のクライアント窓は同じ
  セッションのミラーで、2 枚目を別のタブで開くと 1 枚目もそのタブに追随する。窓ごとに違うタブを
  表示する状態が作れないので、herdr が答える focused pane はどの窓から見ても正しい。
  残る狭い穴は**名前付きセッションを複数動かしたとき**で、セッションごとに socket が分かれる
  (`herdr session list`)。adapter は `HERDR_SOCKET_PATH` も含めて `HERDR_*` を外すため、常に既定
  セッションに聞く。既定以外のセッションの窓を focus しても既定セッションの答えが返る。
  今は 1 セッション運用なので対応しない。
  なお実機では**保険経路(`pane list`)に一度も落ちなかった**(daemon ログに
  `answered an unfocused pane` が出ていない)ので、この分岐は dead code に近い。
  次に触るときは削除も選択肢。

## 0029 — 端末の設定は script で行い、ユーザーが保守する launcher 設定は書き換えない

- **Date**: 2026-09-20
- **Status**: accepted
- **Context**: `.p<pid>` 規約(0027)を有効にするには wrapper を作って**端末を起動している経路すべて**を
  そこに向ける必要があり、`docs/TERMINALS.md` の手順は長い。一度きりの作業なので手順書だけで
  よいかとも考えたが、(a) この repository を他人が使う場合、(b) 別のマシンで組み直す場合、の
  どちらでも手作業を繰り返すことになる。一方で対象ファイルは 2 種類に分かれる——wayhint が
  生成するもの(wrapper、`.desktop` の上書き)と、ユーザーが手で保守しているもの(bar の設定、
  compositor のメニュー)。
- **Decision**: `scripts/setup-terminals` を追加する。生成するファイル(wrapper、`.desktop` の
  上書き)に加え、**bar や compositor の設定の該当行も書き換える**。当初は後者を報告だけに留めた——
  JSON with comments や XML は経緯コメントを伴い(実機の `waybar/config.jsonc` には
  `// 2026-09-16: was U+F120 ...` のような行がある)、機械的な書き換えはそれを失うため。
  ただしこの懸念は**ファイルを読み直して書き出す**場合のもので、検出が「何行目のどの範囲か」まで
  特定できている以上、**その範囲だけを置換**すればパースも再シリアライズも要らず、コメントも
  整形もそのまま残る。書き換える前に `<ファイル名>.wayhint-backup-<日時>` のコピーを取る。
  引数で端末を選べ、既定は「入っている端末すべて」。
  **既定は dry run で、`--apply` を付けたときだけ書き込む**(端末指定の有無に関わらず)——
  ユーザーの home に書く script が初回に何をするかは、実行前に読めるべきである。
  残作業がある間は exit 1 を返し、dry run がそのまま健全性チェックになる。生成物には目印のコメントを入れ、**目印の無いファイルには触らない**(自分で書いた
  wrapper を潰さない)。端末の検出は「コマンドとして実行されている値の先頭語」だけを見る——
  名前を行内検索すると、実機ではコメントや tooltip の文字列に当たって 19 件中 14 件が誤検出だった。
  `TERMINAL_APP_IDS` との食い違いは起動時に検査して落とす。
- **Alternatives**: **手順書のままにする**——一度きりとはいえ、配布と再セットアップで繰り返す。
  **launcher 設定は報告だけにする**(当初の決定)——「他人が clone して 1 コマンド」が成立せず、
  4 種類のファイル形式に対する手作業が残る。範囲を限った置換とバックアップで壊す危険は下げられる。
  **`--check` だけを作る**——診断はできるが、他人に渡す目的には足りない。
  **`./scripts/check` に組み込む**——`check` は repository の検証で、ユーザーのデスクトップの
  状態は対象外。別の入口に分ける(`AGENTS.md` にもそう書く)。
- **Consequences**: `scripts/` に repository の外(ユーザーの home)へ書く script が初めて入った。
  そのため全ての path を環境変数から取り、`tests/test_setup_terminals.py` が一時ディレクトリを
  HOME に見立てて検証する(既存ファイルがある場合——最新・古い生成物・手書き・既に wrapper を
  指している launcher 行——も含む)。見に行く launcher は `LAUNCHERS` の 8 ファイルだけで、
  シェル 1 行に埋め込まれた起動は対象外。kitty の `single_instance` と Ghostty の `gtk-single-instance` は
  wrapper が引数で無効にするので、ユーザーが設定ファイルを触る必要は無くなった。

## 0030 — GUI の自動テストは「プロセス内」と「headless compositor」の 2 層にする

- **Date**: 2026-09-20
- **Status**: accepted
- **Context**: overlay の表示・配置・widget 状態は目視チェックリスト(T1–T5, T13, T24–T26)だけが
  見ていた。手法を 4 つ実地で試した(環境: labwc 0.20.2 / wlroots 0.20.2 / GTK 4.22.4)。
  a プロセス内 widget、b headless compositor + 画面取得、c AT-SPI、d 入力注入。
  sway / cage / wtype / ydotool はこのマシンに無く、**labwc 自身が `WLR_BACKENDS=headless` で
  起動する**ことが分かったので b と c は追加インストール無しで成立した。d は `wtype` を入れて検証した。
- **Decision**: **a・b・d を採用し、c は b の中の読み取り手段として採用する**。d は `wtype` が
  ある環境でだけ走る(無ければその 1 本だけ skip)。a(surface を map しない)は `./scripts/check` に入れる。b/c/d は
  `./scripts/check-gui` に分け、`WAYHINT_GUI_TESTS=1` が無ければ skip する。
  **ベースライン画像の全面比較は採らない**。同一マシンでは撮影が完全に再現する(フレーム間・
  hide/show 後・セッション再作成のいずれでも AE=0)が、font と theme が違う別マシンでは無意味に
  なる。代わりに、overlay を出した frame と出していない frame の**差分の bounding box** で位置と
  幅を測り(font 非依存)、中身は **AT-SPI の accessible name** で読む。
- **Alternatives**: **全部 a で済ませる**——layer surface は compositor への*要求*なので、anchor と
  margin が実際にどう解釈されたかはプロセス内から見えない。実際 `width: 25%`(320px)は
  ボタン行の必要幅に負けて 356px で表示されており、これは a では検出できない。
  **sway / cage を入れる**——labwc で足りた上に、実際に使う compositor で測れる方が価値が高い。
  **ベースライン画像**(上記)。**`./scripts/check` に全部入れる**——8 秒かかり compositor の binary と
  grim / ImageMagick を要求する。既定の検証は数百 ms で依存の無いままにする。
  **ydotool で入力注入**——`/dev/uinput` の権限変更と常駐デーモンが要る。wtype は labwc が出す
  `zwp_virtual_keyboard_manager_v1` を使うので権限が要らない。
- **Consequences**: `tests/headless.py` が repository の外にプロセスを立てる。巻き込み事故を
  防ぐため、compositor には専用の `XDG_RUNTIME_DIR`・`XDG_CONFIG_HOME`・`HOME`・session bus を
  与える(試作段階で、ユーザーの labwc autostart が headless セッション内で waybar と 2 つ目の
  `wayhintd` を起動した)。`XDG_RUNTIME_DIR` は AF_UNIX の 108 byte 制限のため実 runtime dir の
  隣に短い名前で作る。`./scripts/check` の skip が 5 件増える(GUI テストの存在と入口の告知を兼ねる)。
  差分で測る以上、**overlay 以外が動くと混ざる**: probe 窓のカーソル点滅を止め、hotkey テストでは
  測定前に toggle を 1 往復させて focus に伴う再描画を先に済ませる。また「差分がある」だけでは
  弱い——割当の無いキーは下の窓に届いて端末がエコーし、それも差分になるので、**位置と幅まで**
  照合する(故意に keybind を外して確認済)。

## 0031 — デモ動画は headless compositor 上の scenario 駆動 frame-stepping で生成する

- **Date**: 2026-09-21
- **Status**: accepted
- **Context**: 紹介動画を手で画面録画すると、hint の中身・タイミング・窓の配置・言語が毎回ずれ、
  機能を直すたびに撮り直しになる。再現の水準は 3 段階に分けて考える——(1) 同一マシンでは frame
  単位で一致、(2) 別マシンでは内容・順序・尺が一致(font / theme で pixel は変わってよい)、
  (3) 尺は wall-clock ではなく scenario に書いた frame 数で決まる。0030 で、labwc を
  `WLR_BACKENDS=headless` で立て grim で撮り AT-SPI で読む基盤が既にあり、同一マシンでは撮影が
  完全に再現する(AE=0)ことも確認済みだった。測定環境は labwc 0.20.2 / wlroots 0.20.2 /
  GTK 4.22.4 / at-spi2-core 2.62.0 / foot 1.28.0 / grim 1.5.0 / ImageMagick 7.1.2 / wtype 0.4 /
  ffmpeg 9.0.2。
- **Decision**: `demo/scenario.yaml`(脚本)を `./scripts/demo --record` が読み、0030 と同じ
  headless session の中で再生して録る。実装は `tools/demo/`(製品パッケージの外)。
  **実時間キャプチャは使わない**——各 step は `wait_for` の条件(toplevel の出現、overlay の
  可視、AT-SPI で読んだ label / ボタン / 行数)が満たされるまで poll し、画面が止まってから
  grim で **1 frame だけ**撮り、それを `hold × fps` 枚複製して尺を作る。ffmpeg は frame 列を
  結合するだけなので、**尺はファイルが決め、マシンの速さは関係しない**。ボタンは AT-SPI の
  Action interface(role `button`、action `click`)で押し、key は wtype で compositor の keybind に
  送る。scenario は data であり、実行できる action は固定集合・固定 argv で、置換は
  `{demo_bin}` と `{lang}` の 2 つだけ(`shell=True` は使わない)。動画(mp4 / webm)に加えて
  **contact sheet と step ごとの静止画**を出す——動画を再生できない agent / CI でも中身を見られる
  ようにするため。
- **Alternatives**: **wf-recorder などの実時間キャプチャ**——尺と frame 数がマシンの速さに依存し、
  上の (1)(3) を両方落とす。**実物の Claude Code / Codex を動かす**——出力が毎回違い、再現しない。
  stub を `demo/bin/` に置き、`/proc` 経由の照合(argv[0] の basename)だけを本物と同じにした。
  **pointer 注入**——`/dev/uinput` の権限か常駐デーモンが要る。AT-SPI の Action で足りた。
  **ベースライン画像との全面比較**——0030 と同じ理由で採らない(font / theme で別マシンでは無意味)。
  **`tests/headless.py` をそのまま import する**——テストの skip 判定と opt-in がデモに付いてくる。
  session 部分を `tools/headless.py` に移し、tests 側を薄い層にした。
- **Consequences**: headless の制約(単一 output、scale 1、既定 1280×720)はデモにも及ぶ。
  `tools/headless.py` の変更は `./scripts/check-gui` とデモの両方に影響する。録画には ffmpeg /
  grim / ImageMagick / foot / Noto fonts が要るが、`./scripts/check` の依存は増えていない
  (`scripts/demo` の中だけ)。**動画は commit しない**(`demo/out/` は `.gitignore`)。
  再現のために画面上のあらゆる動きを止める必要がある: foot は `cursor.blink=no` に加えて
  `cursor.unfocused-style=unchanged`(focus の出入りで cursor の描画が変わる)、overlay の
  text caret は **GTK 4.22 が `settings.ini` の `gtk-cursor-blink` を読まない**ため止められず、
  最後の打鍵から約 8 秒で自然に止まるのを待つ(撮影は「同じ frame が連続 7 枚」を条件にする)。
  fixtures の作業コピーは **固定パス**(`/tmp/wayhint-demo-<uid>-<lang>`)に置く——YAML error の
  場面では overlay がそのパスを表示するので、`mkdtemp` の名前だと毎回 frame が変わる。
- **Phase A(調査)で本文から変えた点**: `spawn` の argv に `{pid}` を埋める案は成立しない
  (pid は exec 後にしか決まらない)ので、README「Terminal の複数窓」と同じ wrapper
  (`demo/bin/foot-wayhint`)を通す。AT-SPI の Action は**使えた**ので `cli:` への格下げは無し。
  ただし `do_action` は処理の完了を待たないので、`press` の後は必ず状態を `wait_for` してから
  次へ進む。検索欄とフォームの中身は AT-SPI から読めないため、効果(行数・label)で確かめる。
  output 解像度は既定が 1280×720 なので設定せず、最初の frame の寸法が scenario と違えば fail
  する。1 step は 1 action とし(`press` と `type` は別の step。上の待ちの規則のため)、窓の
  配置は scenario の `windows:` に名前付きで書いて labwc の `windowRules` に落とす。
  wtype は `key:` / `type:` を含む scenario でだけ必須で、無ければその場で fail する
  (CLI に黙って置き換えない。hotkey 経路を見せるのが目的のため)。

## 0032 — 紹介動画は showcase 単位で demo 生成システムから作り、Herdr だけ実物を隔離して動かす

- **Date**: 2026-09-21
- **Status**: accepted
- **Context**: 0031 の生成システムができたので、実際の紹介動画(60 秒 / 3 分 / 5 分、字幕のみ・
  無音、日本語版)を作る。当初は実機 labwc で `wf-recorder` を回す案だった。題材は今後も増える
  (Herdr、terminal emulator、GUI アプリ)ので、動画 1 本分を 1 つの単位に閉じたい。主役の 3 場面
  (Herdr の中の Claude Code まで見て切り替わる / focus を奪わない / その場で追記して育てる)は
  **Herdr の中でしか成立しない**——Herdr の pane を切り替えて sheet が差し替わるところが要点で、
  stub では `HerdrContextProvider` の経路そのものを見せられない。測定環境は C-A の実測で
  herdr 0.8.2 / labwc 0.20.2 / GTK 4.22.4 / foot 1.28.0 / ffmpeg 9.0.2。
- **Decision**: 動画 1 本分を **showcase** とし、`demo/showcases/<name>/` に台本・scenario・生成物を
  閉じる。showcase の正体はディレクトリ名で、中のファイルは名前の末尾の役割
  (`<NN>_<showcase>_<role>.<ext>`)で探す。番号は人が工程順に並べるためのもので、ツールは見ない。
  **`01_*_storyboard.md`(人が書く台本)が訴求・場面・順序の正**、**`02_*_scenario.yaml` が action・
  `hold`・字幕の実値の正**。字幕と尺は scenario 側で詰めてから台本へ戻す。場面そのものを変える
  必要が出たら台本を書き換えず報告して止める。
  **Herdr だけは実物を動かす**(0031 の「実物の Claude Code / Codex / Herdr を使わない」を Herdr に
  ついてのみ上書き)。ただし session 専用の `HOME` / `XDG_CONFIG_HOME` / `XDG_RUNTIME_DIR` の中だけで
  動かし、**session の環境から `HERDR_*` を落とす**——落とさないと、Herdr の pane から起動した
  recorder が継承した `HERDR_SOCKET_PATH` を使い、session 内の client が**その人自身の Herdr**に
  繋がる(C-A で実測)。Claude Code / Codex は引き続き stub で、`demo/bin/` の実行ファイル名と
  `prctl(PR_SET_NAME)` だけを本物に似せる。
  scenario からは `herdr:` action で **許可 list にある subcommand だけ**を argv として呼べる。
  引数も検証する: `pane run` の起動コマンドは `demo/bin` にある実行ファイルの名前のみ(`/` も `..`
  も不可、実在を確認)、`tab create` などの生成系は `--focus` / `--no-focus` だけで、`--cwd` /
  `--env` / `--label` は recorder が握る。`server stop` は recorder の後片付け専用で scenario から
  呼べない。1 本の動画は **variant**(`60s` / `3min` / `5min`)で、それぞれが *clean session から
  その列だけを順に実行して成立する完全な action 列*でなければならない。variant 間で状態を引き継が
  ず、hidden setup も自動依存解決も持たない。同じ操作を別の尺で使いたいときは step を複製する。
  言語は **ja 先行**: `--lang` の既定は ja、`--validate` は ja の字幕だけを要求し、en の欠落は
  `--record --lang en` のときに落ちる。
- **Alternatives**: **実機 labwc で wf-recorder**——撮り直しが手作業に戻り、タイムコードを手で
  打つことになり、本番の daemon と keybind を巻き込む事故の余地が残る。0031 を作った理由がそのまま
  却下の理由になる。**Herdr も stub にする**——主役の場面が「Herdr の pane を切り替えたら sheet が
  差し替わった」なので、Herdr を偽物にするとその場面の証拠価値が消える。
  **Claude Code / Codex も実物にする**——出力が毎回違い再現しない。実際に一度 PATH の設定漏れで
  本物が起動し、初回テーマ選択の画面が録れてしまった(その経験から `DemoSession` は起動前に
  `pane run` の解決先が `demo/bin` かを確認する)。**台本を `docs/` に置く**——台本は showcase ごとの
  作業ファイルで、他の題材が増えるたびに `docs/` が動画の数だけ膨らむ。
  **Herdr を `cli:` に混ぜる**——`cli:` は wayhint の CLI で、許可の考え方(固定の command 名だけ)が
  違う。混ぜると Herdr の引数検証が `cli:` 側にも漏れる。**variant ごとに `hold` を上書きする**——
  「60 秒版だけこの step は 2 秒」を許すと、scenario を読んでも何が録れるか分からなくなる。
  step の複製は冗長だが、読めば分かる冗長さで済む。
- **Consequences**: **Herdr の CLI の出力形式が変わると demo が壊れる**。`pane current` /
  `pane process-info` は製品の adapter も使っているので、壊れれば製品側でも気づく。`tab create` /
  `pane run` の JSON は demo だけが読む。**fixtures は showcase 共通の 1 セット**なので、次の
  showcase が sheet を足すと既存の動画の一覧の行数が変わる(`wait_for` の `hints` が落ちて気づく)。
  分けるかどうかは不便が出てから決める。**scenario は step の複製で長くなる**(今は 61 step、
  3 variant)。録画は variant ごとに独立した session を立てるので、3 本で 15 分ほどかかる。
  **`demo/fixtures/hints/en/` は削除した**——0031 の 6 場面用に作った英語 sheet で、この showcase の
  題材とは合わない。英語版は `hints/en/` を新規に作る別タスクで行う。0031 が書いている
  `demo/scenario.yaml` と `demo/out/` は、それぞれ `demo/showcases/<name>/02_<name>_scenario.yaml`
  と `demo/showcases/<name>/out/` に移った。脚本の中でプログラムを指す `{demo_bin}` も無くなり、
  名前だけを書いて recorder が解決する形になった(下記のレビュー修正)。
- **レビューを受けた修正(2026-09-21)**: Codex のレビューで挙がった穴を塞いだ。
  **session に shell を置かない**——`default_shell` を `demo/bin/idle` にした。脚本は端末に文字を
  打つので、pane に shell が居ると脚本から任意のコマンドを実行できる。`idle` は隣の stub の名前
  だけに反応し、それ以外の入力は読み捨てる。`spawn` の argv も名前だけに限り(絶対パスと `..` を
  拒否)、解決は recorder が行う。**名前を file 名として安全な形に限定**——showcase 名・variant 名・
  step id は `[a-z0-9-]` のみ。出力先を消す前に `resolve()` して `out/` 配下か確かめる。
  **数値は有限に限る**——`.nan` / `.inf` は静かに比較を通り、最初に表に出るのが frame 数になる。
  **session bus に session の環境を渡す**——渡していなかったので、AT-SPI launcher が実
  `XDG_RUNTIME_DIR` に socket を作っていた。**起動途中の失敗でも畳む**——`__enter__` が返る前の
  失敗では `with` が始まっておらず `__exit__` が呼ばれないので、両 session を `ExitStack` で組んだ。
  **0031 の場面④(foot 2 枚を `.p<pid>` 規約で起動し、focus 追従で sheet が差し替わる)は demo から
  落とし、`tests/test_gui_headless.py` の GUI test 1 本に移した**。動画の題材としては Herdr の
  pane 切替と重複するが、製品挙動の回帰としては残す価値がある。この test は `demo/bin/` の stub と
  wrapper を使うので、**test が demo に依存する**(逆ではない)。`./scripts/check-gui` は 5 本から
  6 本になり、実行時間は 16.8 秒から 18.6 秒に増えた。
- **脅威モデル(2026-09-21 追記)**: demo 生成システムのレビューはこの範囲で行う。
  **untrusted(data として扱う)**——scenario の内容、`./scripts/demo` の CLI 引数、`type:` で送る
  文字列、`out/` の状態(symlink も既存ファイルも含む。人が別ディスクへ向けていることがある)。
  **trusted(code として扱う)**——`tools/`、`demo/bin/` の中身、`demo/fixtures/`、Herdr と foot の
  binary。ここに細工を置ける者は `tools/` 自体を書き換えられるので、防御の対象にしない。
  **守ること**——(a) untrusted な入力から shell に到達できない、(b) `out/` の外を削除しない、
  (c) 実ユーザーの環境(`~/.config/*`、`~/.claude*`、実 `XDG_RUNTIME_DIR`)を読み書きしない。
  この 3 つに当たらない指摘、たとえば `demo/bin/` に細工した symlink を置く経路は trusted 側の話
  なので、以降のレビューでは対象外とする。`demo/bin/idle` の symlink 拒否(下記)は修正が数行で
  済んだから入れただけで、範囲を広げたわけではない。
- **再レビューを受けた修正(2026-09-21、2 回目)**: 上の脅威モデルに照らして 6 件塞いだ。
  **`out/` の symlink を追わない**——削除の直前に `out/` / `out/<lang>/` / `out/<lang>/<variant>/`
  を *resolve する前に* 見て、どれかが symlink なら録らずに止める。`out/` を別ディスクへ向けるのは
  普通にやることで、追うと消す先がそちらに移る。別の場所に置きたいときは `--out-dir`(下)。**端末 wrapper の引数を許可 list にする**——`spawn` の argv は wrapper 名(`foot-wayhint`
  か `foot-herdr`。prefix 一致をやめて 1 つずつ列挙)、`--app-id=foot-<名前>`、そして
  `foot-wayhint` の場合だけ `-e <stub>` の形に限る。command を書かない foot は login shell を
  開くので、これが「session に shell を置かない」の最後の穴だった。wrapper 側も `"$@"` を foot に
  素通しするのをやめ、同じ list で受ける。**Herdr の絶対パスを wrapper へ環境変数で渡す**
  (`WAYHINT_DEMO_HERDR_BIN`)——`foot-herdr` の末尾が裸の `herdr` だったので、PATH 先頭の
  `demo/bin` を見に行く余地が残っていた。未設定なら wrapper は exit 1。**`idle` が exec できる
  名前を静的に書く**——ディレクトリの列挙は「隣に何があるか」を答えるだけで「pane が何を起動して
  よいか」とは別の問い。symlink も拒否する(trusted 側なので範囲外だが数行)。**名前の検査を 1 つに
  する**——`tools/demo/names.py` の `validate_name` を scenario・showcase・CLI(`--showcase`
  `--variant` `--only` `--from`)が通る。`re.match` は末尾の改行を通すので `fullmatch` にした。
  **後片付けを起動の逆順にする**——`HeadlessSession` は bus → compositor → daemon の順に上げるのに、
  停止の list を `[*_procs, _bus]` で組んでいたので bus が最初に落ちていた。生きている compositor
  の足元から session bus を抜くのが、AT-SPI client が終了時に固まる形。
- **字幕と画面を合わせるための修正(2026-09-21、B-7)**: 生成した 3 本を見て、字幕が指す出来事が
  frame に映っていない箇所を洗い出して直した。**session の作業ディレクトリは
  `/tmp/wayhint-demo/<showcase>-<lang>/`**——uid を入れない。このパスは YAML error の帯として
  画面に映るので動画の一部で、`…-1000-…` は視聴者には事故に見える。同一マシンで 2 人が同時に
  撮ることは想定しない(既存のディレクトリがあれば空けずに exit 1 する)。
  **単キー操作の場面は製品仕様に合わせて台本のほうを直した**——フォームの保存は編集モードを
  終える(0021)ので、`f` / `J` / `K` は保存の**前**に置く。後ろに置いていた初稿では overlay に
  届かず、Codex の pane に文字として入っていた。さらに編集モードには**選択行を動かすキーが無い**
  (`Down` も `Tab`+`Down` も効かないことを実測)ので、単キー操作は編集モードに入った時点の
  選択行、つまり先頭行についてしか見せられない。そのため `codex.yaml` から `favorite` を外し、
  先頭行を素の hint にした——`f` に「付けるべき ★」を用意するため。
  **`demo/bin/vi` は引数の sheet を実際に読んで表示する**——固定の抜粋を出していたころは、
  `match` / `inherit` / `include` を語る 4 枚 32 秒がそれらの行が無い画面に重なっていた。開けるのは
  session の fixtures のコピーの中だけ(`WAYHINT_DEMO_CONFIG`)で、scenario が任意のファイルを
  画面に出せてはならない。**`J` / `K` は `type:` で送る**——wtype の `-k J` も `-M shift -k j` も
  窓には小文字で届き、大文字が届くのは text mode だけだった(実測)。
- **視聴して直した点(2026-09-22、B-8)**: 生成した 3 本を人が見て決めたこと。
  **GUI アプリの場面は GTK4 の stub `notes` で撮る**——実アプリ(gedit など)は使わない。出力が
  毎回違ううえ、ロゴや文言を借りることになる。stub は label だけで、entry も scrolled window も
  置かない(caret とスクロールバーが時間で変わる)。窓は下の端末を覆う大きさにする——この場面の
  主語は GUI の窓で、後ろに端末が覗いていると何を見ればいいのか分からない。sheet は
  `match.wayland` で app_id に当て、overlay の sub-header にプロセス名が出ないことが要点になる。
  代わりに「Herdr の無い端末」の場面は落とした(直前の場面と言っていることが同じ)。
  **字幕帯の行はレイアウトで予約する**——帯を不透明にして隠すのではなく、窓と overlay を帯の上で
  止める。帯の幾何は `tools/demo/encode.py` の `caption_band_top` / `caption_text_top` が決め、
  720p では上端 638。窓は scenario の `windows` の `height` で、overlay は `config.yaml` の
  `overlay.height` で収める(実測: 窓 624 / overlay 628 / 編集フォーム 628)。labwc の `<margin>`
  は使わない——`rc.xml` を書くのは `tools/headless.py` で、demo だけの都合を持ち込みたくない。
  **共通 sheet(`wm`)には窓そのものの操作を置く**——「この overlay を出す・消す (`Super+H`)」は
  hint として成立しない。それを忘れている人はこの一覧を開けない。
- **台本と脚本は突き合わせるが、生成はしない(2026-09-22)**: `01_*_storyboard.md` から
  `02_*_scenario.yaml` を生成する案は採らない——台本に step id と action を書くことになり、
  台本が YAML の別記法になって「人が訴求を考える場所」という役割が消える。代わりに `--validate`
  が台本のうち脚本についての主張(字幕・表の秒・節見出しの範囲・合計秒)だけを検査する
  (`tools/demo/storyboard.py`)。**手で同期していたものを機械が見る**——B-7 と B-8 では場面を
  足し引きするたびに台本の秒を手で直していて、3 回とも直し漏れがあった(この検査を入れた直後に
  13 件見つかった)。どの variant の節かは `<!-- variant: <name> -->` で示す。
  `wait_for` が何も主張していない step は**警告**にとどめる——`pause:` のように画面を変えないのが
  正しい step があり、機械には区別できない。
- **警告 17 件の潰し方(2026-09-23)**: 「何も主張していない `wait_for`」は、条件を足せるものと
  足せないものに分かれた。**足せるもの**には条件を 2 つ新設した——`first_hint`(一覧の先頭行)は
  `J` / `K` の並べ替えを見るためのもので、`label` では見えない(行が動いても行の集合は変わらない)。
  `text`(入力欄の中身)は form に打った文字が overlay に届いたかを見るもので、AT-SPI の
  `EditableText` を持つ node だけを読む(label も text interface を持っているので、全部読むと
  `label` の弱い複製になる)。**足せないもの**——端末に文字が出るだけの step、字幕だけが進む
  step——には `wait_for.unchecked: "<理由>"` を書く。flag ではなく**文**にしたのは、次の人が
  「なぜこれだけ例外なのか」と訊いたときに答えが要るから(10 文字未満は exit 1)。
  実装のとき、一覧の行(`list item`)は**名前を持たない**ことが分かった——key も title も
  category も子の label 側にあるので、先頭行は dump(深さ優先)の最初の行と 2 行目の間を読む。
- **`--out-dir` は「自分のディレクトリ」しか受け取らない(2026-09-23)**: `out/` を symlink に
  するのは禁止のままで、別の場所へ出したい人には `--out-dir <path>` を用意した。録画は
  `<path>/<lang>/<variant>` を**消してから**始めるので、受け取るのは**空のディレクトリか、前に
  ここが書いたディレクトリ**だけにする(目印は `.wayhint-demo-out`)。中身のある他人の
  ディレクトリは消さずに断る——`--out-dir ~/Videos` は十分あり得る打ち間違いで、
  `~/Videos/ja/3min` は十分あり得る実在のディレクトリ。repo 内の `out/` に目印は要らない
  (repo が名前を決めていて、他のものが入らない)。
  wrapper の引数検査だけは shell script なので、`./scripts/check` の test が wrapper を**実際に
  subprocess として起動する**。起動しないのは **foot と Herdr** のほうで、どの case も
  `exec /usr/bin/foot` の数行手前で止まる——だから compositor も server も要らず、純粋な parse の
  test と同じ場所に置ける。**正規表現は `fullmatch` で照合する**——`$` は末尾の改行の手前にも
  合うので、`re.match` だと `--app-id=foot\n` や `w1:p1\n` が通る(Codex 3 回目の指摘)。

## 0033 — 検索は「入力」と「絞り込み」に分け、絞り込みは sheet ごとに state.yaml へ永続化する

- **Date**: 2026-09-23
- **Status**: accepted
- **Amends**: 0014（D3 の状態遷移表: `search` の入口・出口。D10 の「フィルタ状態は表示セッション限り」）。
  設計書 §4 / §30 / §47 / §48、DESIGN「状態と keyboard_mode」の `search` 行と §9 category フィルタ。
- **Context**: 検索に入るのも、コピーするのも、検索を終えるのもマウスが要る。検索欄にフォーカスを
  移す手段が「検索ボタン」しか無く、通常表示は NONE なので overlay 上のキーでは入れない（`edit-mode`
  と同じ事情、0014 D3）。加えて、検索を終えると絞り込みが消えて全件表示に戻る。実際の使い方では
  「この作業の間は pane 系の hint だけ見ていたい」のように、絞った状態で長く眺めたいことがあり、
  今の設計は**キーを奪う時間**（短くあるべき）と**絞り込みの寿命**（作業の間ずっと）を同じにして
  しまっている。

- **Decision**:

  **A. 検索モードの入口を IPC にする。** `wayhint search-mode` を新設し、compositor keybinding から
  呼ぶ（README の例は `W-S-h`）。非表示なら show と context 解決を行ってから `search` へ、表示中なら
  そのまま `search` へ。`search` 中にもう一度 `search-mode` が来たら Esc と同じ経路で `normal` に戻す
  （keyboard_mode NONE → 前の view へ focus 復帰）。出口を増やさない。`edit` 中の `search-mode` は
  「編集中は検索しない」（0014）に合わせて拒否し、理由を表示する。検索ボタンは残す。
  **（2026-09-23 追記）表示中でも context を取り直す。** 別の window から押したときは、`toggle` と同じく
  overlay を閉じずに中身を差し替えてから `search` へ入る。同じ window ならそのまま。実機の T45 で、
  Herdr の window で開いたままの overlay に対し、vi を動かす別の foot から押すと Herdr の hint を検索し、
  抜けると Herdr に focus が戻った。hotkey は「いま見ているものの hint」（README）なので、表示中の
  context をそのまま使う当初の文言が誤り。`edit-mode` は表示中のものを編集する意味なので取り直さない。

  **B. 検索欄の `Enter` で「コピーして戻る」。** 選択中の hint（結果の先頭行を自動選択する）に対して
  既存の「コピー」ボタンと同じ処理（`copy → command → key` の解決 → GDK clipboard）を行い、続けて
  Esc と同じ経路で `normal` に戻す。一覧にフォーカスがあるときは `c` と `Enter` が同じ動作。結果が
  0 件、またはコピーできる項目が無い hint（`note` 等）のときは何もせず理由を表示して `search` に
  留まる。元アプリへの貼り付け（キー注入）は行わない。

  **C. 「検索モード」と「絞り込み」を分ける。** `search` を抜けるすべての経路（Esc / `Enter`・`c` /
  `search-mode` 再押下 / hide）は **grab を外すだけで、絞り込みは残す**。`normal` は絞り込まれた
  一覧をそのまま表示する。一覧の描画は 1 本にし、絞り込みは通常表示（favorite 区画・category
  見出し込み）に適用する。「検索結果は title/key/command のみ」（設計書 §30）の別描画は廃止。
  `normal` では絞り込み中であることを chip で示し、chip の `×` で解除できる（マウス用）。
  キーボードでの解除は「`search-mode` → 欄を空にする → 出る」。つまり**出たときの欄の内容が
  絞り込み**で、解除専用のキーは作らない。`#category` と Tab 巡回は欄の文字列を変える操作なので
  絞り込みの一部（Tab は欄の先頭トークン `#<category> ` を書き換える）。category 無しの擬似
  category は欄では **`#-`** と書く（言語に依存しないので、`appearance.language` を切り替えても
  保存済みの絞り込みの意味が変わらない。chip には訳語 `inbox` / `未定義` を出す）。再入時は保存済みの絞り込みを欄に入れて全選択にする（打てば置き換え、`End` で追記、
  そのまま Esc なら不変）。

  **D. 絞り込みは sheet id をキーに永続化する。** 置き場所は `$XDG_STATE_HOME/wayhint/state.yaml`
  （既定 `~/.local/state/wayhint/state.yaml`）。形式は

  ```yaml
  version: 1
  filters:
    claude-code: "pane"
    herdr: "#session"
  ```

  キーは active（子）sheet の id。nested / include で混ざった親 hint 込みの一覧全体に適用する。
  `search` を抜けた時点で前回と違えば一時ファイル + rename で書き、空なら該当キーを削除する。
  このファイルは監視しない（書くのは daemon だけ）。hide/show・workspace 切り替え・daemon 再起動を
  またいで残り、同じ sheet ならどの workspace でも同じ絞り込みになる。active sheet が無い context
  では `search` に入れるが絞り込みは保存しない（メモリのみ、context が替われば消える）。
  `wayhint refresh` と reload は再解決した sheet のキーで読み直して再適用する。`search` 中に reload が
  来たとき（`git checkout` や同期ツールなど、人の手を介さない更新）は、一覧だけを再描画して検索欄には
  触らず（文字列・カーソル・IME の preedit・focus をそのまま）、絞り込みは state.yaml ではなく**欄の
  文字列から再適用**し、選択行は id で復元する（消えていれば先頭行）。「エディタで編集」は 0023 の
  とおり `normal` に戻すだけで、絞り込みは残るので、gvim で保存するたびに絞り込まれたままの一覧が
  更新される。

  ここで**ファイルの 3 区分を明文化する**: 内容は `hints/`（人が書く）、設定は `config.yaml`（人が
  書き、リサイズだけ daemon が書き戻す）、状態は `state.yaml`（daemon だけが書く）。

  **E. 壊れていても止めない。** state.yaml が無い / 読めない / YAML として壊れている / 先頭が
  mapping でない / `version` が 1 以外 / 64 KiB 超のときは**絞り込み無しとして起動**し、WARN を
  1 行出す。UI に `⚠` は出さない（hints の壊れと区別がつかなくなる）。last-known-good も `.bak` も
  持たず、次の書き込みで正常な内容に上書きされる。部分的におかしい項目（値が文字列でない、
  sheet id が `^[A-Za-z0-9][A-Za-z0-9._-]*$` に合わない、値が 200 文字超）はその項目だけ捨てる。
  項目数は 256 を超えた分を捨てる。知らない sheet id は残す（消すのは明示的な解除だけ）。知らない
  キーは無視し、書き戻しで消える。重複した sheet id は**後勝ち**（ruamel の safe loader は既定で
  重複キーをエラーにするので `allow_duplicate_keys = True` を明示する）。書き込み失敗はメモリ上の
  絞り込みを使い続けて WARN、次の変更で再試行（config の保存と同じ）。`wayhint validate` は
  state.yaml を見ない。

  **F. 絞り込み文字列は解釈しない。** regex・パス・shell・Pango markup のどれとしても扱わず、
  既存の case-insensitive substring + token AND でのみ使う（将来 RapidFuzz 等に替えても同じ）。
  文字種は制限しない（日本語で remark を探すのが主用途）。上限は入力欄 `max_length` 200、
  読み込み時も同じ 200（超えたら切り詰めず捨てる）。Unicode カテゴリ `Cc` は入力時と読み込み時に
  落とす。chip は `set_text` で出す。WARN に絞り込みの内容は書かない。state.yaml は
  **hints と同じ「人が触りうるディレクトリの中身」として untrusted 寄りに読む**
  （書くのは自分、読むときは疑う）。0032 の脅威モデルは demo 生成システムの範囲なので、そこには
  足さない。

  **G. 編集モードとの関係。** 絞り込み中に `edit` に入れる。`J` / `K` は画面上の隣と YAML 上の隣が
  ずれるので**絞り込み中は無効**（別グループの hint と同じく何も起きない）。`a` / `Enter` / `dd` /
  `u` / `f` は影響を受けない。

- **Alternatives**:
  絞り込みを sheet ファイルに書く（絞り込みは view の状態で内容ではない。`format` / schema /
  validate / examples に漏れる。hints/ の file monitor が自分の書き込みを拾うので「自分の書き込みは
  無視する」例外が監視側に要る。gvim で sheet を開いていると W11 が出る。dotfiles 管理で diff が
  出る）; workspace ごとのメモリ保持のみ（0012/0014 D4 と同じ粒度。再起動で消え、同じ sheet を別
  workspace で見ると別の絞り込みになる）; context が替わったら捨てる（sheet をキーにすれば別の
  キーを見るだけで、捨てる必要が無い）; `search` 中の hotkey を edit と同じ hide/show 保持にする
  （絞り込みは別に永続化されるので、`search` を抜けて失うものが無い）; コピー対象を「`command` の
  ある hint」に限定する（`copy → command → key` の既存規則と二重になる）; 解除専用キー / CLI
  `clear-filter`（欄を空にして出れば足りる）; 絞り込み中は `edit` に入れない（絞った状態で目視
  しながら編集したい場面があり、困るのは `J`/`K` だけ）; 文字種制限（日本語検索を壊す）;
  state.yaml のパスを config で変える、複数 daemon、他プロセスからの書き込み（今の使い方に無い。
  **defer**）。

- **Consequences**:
  `normal` で一覧が短く見えることがあるが、chip を見れば分かる（README troubleshooting に追記）。
  検索モードに入ると前回の絞り込みが欄に入っているので、別の語で探すときは打ち直し（全選択済み）。
  focus 復帰の既知の制約（同 app_id 複数 + title 変化で復帰先が決まらない、README）はキー操作の
  流れでも同じで、そこで止まったらクリックが要る。`search` の状態遷移表は「出口: Esc、Enter・c、
  `search-mode`、hide、workspace 離脱」「入口: 検索ボタン、`search-mode`」になる。DESIGN §30 の
  「結果一覧は title/key/command のみ」を削除。i18n（en/ja）に chip のラベルと「コピーできる項目が
  ありません」を追加。手動検証は DESIGN の実機チェックリストに T38–T46 として追加: keybinding → `search-mode` →
  `Enter` でコピーして focus が戻る / Esc 後も絞り込みが残る / daemon 再起動後も残る /
  state.yaml を壊しても起動して WARN が 1 行 / 絞り込み中の `edit` で `J`/`K` が無反応 /
  別 workspace の同 sheet で同じ絞り込み / `search-mode` 再押下で `normal` に戻る /
  `search` 中に別経路で sheet を書き換えても欄の文字列・focus・絞り込みが残る / `search` 中の
  「エディタで編集」で `normal` に戻り、gvim 保存後も絞り込まれた一覧が更新される。
  README に `rc.xml` の例（`W-S-h` → `wayhint search-mode`）、ファイル構成表に state.yaml、
  ファイルの 3 区分（内容 / 設定 / 状態）を追記。

## 0034 — 親 hint の既定は「未指定 = 全部」、絞りは親 sheet 側の `nested.export_tags` を基本にする

- **Date**: 2026-09-23
- **Status**: accepted
- **Supersedes**: 設計書 §18 の既定 `nested-common`。0025 Context の「`nested.parent_tags` があると」
  という前提(親 hint が混ざるには何か書く必要がある、という読み)。
- **Context**: 子 sheet が選ばれたとき(Herdr の中の Claude Code、foot の中の vi)、config.yaml にも
  sheet にも何も書かなければ親 sheet の hint が混ざる、と期待されていた。実装は global
  `nested.parent_tags` の既定が `()` で、子も global も書かなければ親 hint は **0 件**だった。これは
  foreground がどの sheet にも当たらないとき(親 hint を全部出す)とも、`include`(tag で絞らず全部、
  0026)とも既定が逆。加えて、何を渡すかの語彙を親ではなく子と global が持っており、Herdr の hint を
  どれだけ子に見せるかを Herdr の sheet 自身が決められないという責務のねじれがあった。
  `docs/PRODUCT.md` の「既定 `nested-common`」も実装(`()`)と食い違っていた。
- **Decision**:
  **D1. 解決順は 1 本の置き換え規則(intersection はしない)。**
  1. 子 sheet の `inherit.parent_tags`(明示)
  2. config.yaml の `nested.parent_tags`(明示)
  3. 親 sheet の `nested.export_tags`(明示)
  4. どれも未指定 → 親 sheet の hint を全部

  上から見て**最初に明示されていた段だけ**を使い、下の段は見ない。どの段でも `[]` の明示は
  **0 件**(opt-out)。「未指定」はキーが無いこと(`null` も未指定)で `None` で表し、`[]` と区別
  する。段 1〜3 に非空 list があれば従来どおり `wanted ∩ hint.tags` で絞る。
  **D2. 触らないもの。** foreground が無 sheet のときに親 hint を全部出す挙動。`include`(tag で
  絞らない、置き換え、多段なし)。`export_tags` は nested の親経路にだけ効き、`include` で取り込まれる
  ときは見ない。親の決まり方(resolver)。global `nested.parent_tags` のキー自体は残し、既定値だけ
  `()` → `None` にする(キーを消すと未知キー error で既存 config.yaml が壊れる)。
  quick add / `wayhint add --parent` が親 sheet に書く hint へ付ける tag も同じ規則で決め、全部渡す
  (`None`)ときは付けない。
- **Alternatives**:
  **子側で親ごとに絞りを変える `inherit.parents`**(defer)。下書き:

  ```yaml
  inherit:
    parents: {herdr: [pane], foot: []}   # 親 sheet id → その親から受け取る tag
  ```

  親はウィンドウごとに 1 つに決まるので、同じ子が親ごとに違う絞りを要求する具体例が出るまで
  入れない。「sheet 名のみで tag は問わない」を表す値(`all` / `null`)の記法も決まらない。
  **`include` の tag 絞り**(`include: [{sheet: x, tags: [...]}]`)と**横断 `always_tags`**: 0026 で
  却下済みで、再開しない。**global `nested.parent_tags` の削除**: 互換のため見送り(上の D2)。
  **`TERMINAL_APP_IDS` の設定化**: 0027 を維持。今回の動機は既定の読み違えで、新しい端末の要求では
  なかった。
- **Consequences**: 親 sheet が大きいと子の一覧が長くなる。絞るなら親に `export_tags` を書く。
  親 hint の前に区切り見出しを入れるかは、実機で長さを見てから決める(0026 の「無印」は据え置き)。
  `examples/` は `config.yaml` の `nested.parent_tags` をやめ、`herdr.yaml` の
  `nested: {export_tags: [terminal]}` に移した。demo の fixtures は config で明示しているので動画は
  変わらない。

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
