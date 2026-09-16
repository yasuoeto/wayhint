# wayhint — Decisions

Lightweight ADRs. Newest last. One entry per decision that took discussion; a decision that was
obvious does not need one.

Entry format (this block is an example, not an entry -- it is fenced so that it cannot be
mistaken for one, and so the first real decision gets number 0001):

```markdown
## 0001 — Title of the decision

- **Date**: YYYY-MM-DD
- **Status**: accepted | superseded by 000N | rejected
- **Context**: what forced a choice, and what constrained it.
- **Decision**: what was chosen, in one or two sentences.
- **Alternatives**: what else was considered, and why it lost.
- **Consequences**: what this now costs or forecloses.
```

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
