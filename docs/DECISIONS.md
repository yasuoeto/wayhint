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

## 0004 — hotkey は Wayfire に委譲し、CLI ↔ daemon は Unix domain socket

- **Date**: 2026-09-16
- **Status**: accepted
- **Context**: global hotkey を Wayland client 側で取るのは困難で、compositor が担うのが自然。
  toggle の入口は1つに固定したい。
- **Decision**: Wayfire の keybinding から `wayhint toggle` を実行。CLI は
  `$XDG_RUNTIME_DIR/wayhint.sock` へ送るだけ。ネットワーク socket は使わない。
- **Alternatives**: D-Bus(依存と定型が増える); daemon 自身で keybinding を取る(Wayland では
  不可・不安定)。
- **Consequences**: Wayfire 以外へ移植する際は keybinding 設定を各 compositor 側に書く。
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
