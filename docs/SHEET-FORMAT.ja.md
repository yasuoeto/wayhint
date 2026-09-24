# SHEET-FORMAT — ヒントシートの書き方

[English](SHEET-FORMAT.md)

ヒントシート(以下シート)は、あるアプリやコマンドのヒントをまとめた YAML ファイル。1 ファイルが
1 枚のシートになる。最初の 1 枚の書き方は README「ヒントを書く」、シートがどう選ばれて混ざるかは
[`SHEETS.md`](SHEETS.ja.md)。ここはシートに書ける項目の全部と、その決まりをまとめる。

## ファイルの置き場所と名前

- 置き場所は `~/.config/wayhint/hints/<言語>/`(日本語なら `hints/ja/`)。探す順は `hints/<言語>/` →
  `hints/en/` → `hints/` 直下で、最初に見つかった 1 つのディレクトリだけを読む。
- 拡張子は `.yaml` か `.yml`。ファイル名順に読む。
- **ファイル名(拡張子を除く)とシートの `id` を同じにする。** 違うファイルは読み込まず、ヒント画面の
  `⚠` と `wayhint validate` に理由が出る(`claude-backup.yaml` が `id: claude` を名乗っても二重に効かない)。
- 保存すると daemon が自動で読み直す。

## 全体の形

```yaml
version: 1                      # 任意。書くなら 1
id: claude-code                 # 必須。ファイル名と同じ
title: Claude Code              # 必須
priority: 0                     # 任意。複数のシートが当たったときに大きい方を選ぶ
match:                          # 任意。無いシートは単独では出ない
  wayland:
    app_id_regex: ["^foot$"]
  process:
    argv_regex: ["^claude$"]
    cmdline_regex: ["claude .*--resume"]
include:                        # 任意。この一覧に混ぜるシート
  - wm                          #   id だけなら全部
  - {sheet: git, categories: [基本]}   # {sheet, tags, categories} で一部だけ
display: {anchor: top-left}     # 任意。このシートを出すときだけヒント画面の位置・大きさを変える
inherit: {parent_tags: [pane]}  # 任意。子として出るとき、親のヒントを絞る(parent_categories も可)
nested: {export_tags: [pane]}   # 任意。親として出るとき、子に渡すヒントを絞る(export_categories も可)
hints:                          # ヒントの list
  - id: resume
    title: 前の会話を再開
    command: claude --resume
    category: 起動
```

知らない key はエラーになる(打ち間違いを黙って無視しないため)。

## シートの項目

| key | 必須 | 値 | 意味 |
|---|---|---|---|
| `version` | | `1` | 書式の版。省略時は 1 |
| `id` | ✓ | 英数字で始まり、英数字と `.` `_` `-` だけ | シートの名前。ファイル名と同じにする。全シートで一意 |
| `title` | ✓ | 文字列 | シートの見出し |
| `priority` | | 整数(既定 0) | 複数のシートが当たったとき、大きい方が選ばれる |
| `match` | | 下の「match」 | どのウィンドウ・コマンドのときに出すか |
| `include` | | シート id か `{sheet, tags, categories}` の list | この一覧の末尾に混ぜるシート。map にすると、そのタグか category のヒントだけを混ぜる。書かなければ `config.yaml` の `include`。`[]` で何も混ぜない |
| `display` | | `anchor` `width` `height` `margin` `output` | このシートを出すときだけ、ヒント画面の位置・大きさを上書きする。書き方は [`CONFIG.md`](CONFIG.ja.md) の overlay と同じ |
| `inherit.parent_tags` / `inherit.parent_categories` | | タグ / category の list | このシートが子として選ばれたとき、親のヒントをこれで絞る |
| `nested.export_tags` / `nested.export_categories` | | タグ / category の list | このシートが親になったとき、子の一覧に渡すヒントを絞る。書かなければ全部渡す |
| `hints` | | ヒントの list | 下の「ヒントの項目」 |

タグと category を両方書いたときは、どちらかに当たるヒント(OR)。`[]` はもう片方に関係なく 0 件。
`include` `inherit` `nested` の関係は [`SHEETS.md`](SHEETS.ja.md) に図でまとめてある。

## match

| key | 当てる相手 |
|---|---|
| `wayland.app_id_regex` | フォーカス中のウィンドウの app_id(`wayfire.app_id_regex` と書いても同じ) |
| `process.argv_regex` | 端末や Herdr の中で動いているコマンドの名前、引数の 1 つ 1 つ、引数のファイル名部分 |
| `process.cmdline_regex` | そのコマンドの行全体 |

- どれも Python の正規表現の list で、**部分一致**。全体に当てたいときは `^...$` で囲む。
- `argv_regex` は名前だけでなく引数にも当たるので、`node /path/to/codex` のように別のプログラム経由で
  動くコマンドにも `^codex$` で当たる。
- 1 つの pattern は、当たった回数にかかわらず 1 と数える。当たった pattern の数が多いシートほど優先
  される(その前に `priority`、最後はファイル名順)。
- app_id に `.p<数字>` の接尾辞が付いたウィンドウ(README「端末の複数ウィンドウ」)には、接尾辞を
  外した名前でも当てる。`^foot$` と書けば `foot.p12345` にも当たる。

```yaml
match:
  wayland: {app_id_regex: ["^org\\.inkscape\\.Inkscape$"]}    # GUI アプリ
```

```yaml
match:
  process: {argv_regex: ["^vi$", "^vim$", "^nvim$"]}           # 端末の中のコマンド
```

## ヒントの項目

| key | 必須 | 値 | 意味 |
|---|---|---|---|
| `id` | ✓ | シートの `id` と同じ形 | シートの中で一意な名前。ヒント画面には出ない |
| `title` | ✓ | 文字列 | 一覧に出る説明 |
| `kind` | | `shortcut`(既定)`command` `tip` `note` | 種別。下の「kind」 |
| `key` | | 文字列 | 一覧の左端に出るキー操作(例 `Ctrl-o`)。長いものは折り返し、YAML に書いた改行もそのまま出る |
| `command` | | 文字列 | title の下に出るコマンド。**実行はしない**。表示とコピーのみ |
| `category` | | 文字列 | 一覧の右端に出る見出し。同じ category は隣り合って並ぶ。書かなければ擬似 category(`inbox` / `未定義`) |
| `tags` | | 文字列の list | 親シートや `include` から混ざるときの絞り込み。検索の対象にもなる |
| `favorite` | | `true` / `false`(既定) | `true` で `★` 付きになり、一覧の先頭に並ぶ |
| `copy` | | 文字列 | コピーする文字列が表示と違うときだけ書く |
| `remark` | | 文字列 | 行を選んだときだけ出る補足 |
| `source` | | 文字列 | 出典(公式ドキュメントの URL など) |
| `learned` | | 日付 | 覚えた日。`2026-09-24` のように書く |

- `key` `command` などに数字だけを書いても(`key: 5`)文字列として扱う。
- コピーされるのは `copy`、無ければ `command`。`key` だけのヒントはコピーしない(キーは押すもので貼るものではない)。
- 同じシートの中で `id` が重なるとエラーになる。別のシートなら同じ `id` を使ってよい。

### kind

| kind | 使いどころ | 一覧での出方 |
|---|---|---|
| `shortcut` | キー操作。ふつうは `key` を書く | 書いてある `key` と `command` を出す |
| `command` | コマンド。ふつうは `command` を書く | 同上 |
| `tip` | キー操作とコマンドの両方がある覚え書き | 同上 |
| `note` | 文章だけの覚え書き | `key` と `command` を書いてあっても出さない |

`kind` そのものはヒント画面には出ず、絞り込みにも使わない。YAML を手で書くときは `kind` に関係なく
`key` と `command` を書けるが、編集モードのフォームと CLI では `kind` に合う欄しか入力できない
(`shortcut` は key、`command` は command、`tip` は両方、`note` はどちらも無し)。

## 並び順

一覧の並びは、次の順で決まる。

1. `favorite: true` のヒント。シートに書いた順(category は見ない)
2. それ以外。category ごとにまとまり、category の順番は最初に出てきた順。同じ category の中は書いた順

順番を変えたいときは YAML の中でヒントを並べ替える。編集モードの `J` / `K` も同じことをする。
親シートや `include` から混ざったヒントの位置は [`SHEETS.md`](SHEETS.ja.md) §2。

## 間違いがあったとき

- シートに 1 つでも間違いがあると、そのシートは読み込まない。前に正しく読めていれば**その内容を出し
  続け**、ヒント画面の上部に `⚠ YAML error file:line: message` が出る。
- `wayhint validate` で全部のシートと `config.yaml` を確かめられる。間違いがあれば exit 1。
- `include` に無いシートの id を書いたときだけは警告で、シートは出る(`validate` も exit 0)。
- 表示中のシートが壊れている間は、編集モードに入れない(壊れたファイルを上書きしないため)。

## ヒント画面や CLI が書くとき

編集モードや `wayhint add` などがヒントを書き込むときは、次の形にそろえる。自分で書くときは従わなくて
よく、key の順番や省略は自由。

- ヒントの 12 項目を `id` `title` `kind` `key` `command` `category` `tags` `favorite` `copy` `remark`
  `source` `learned` の順に、書いていない項目も空(`key:` のように値なし)で並べる。
- `wayhint format [PATH...]` で、手で書いたシートも同じ形に整えられる。
- 編集モードの `a` で、当たるシートがまだ無いときは新しいシートを作る。ファイル名はアプリかコマンドの名前、
  `match` は今のウィンドウ(端末ならその中のコマンド)に当たる形で自動で入る。

## エディタの補完

`wayhint schema --write` でシートの JSON Schema を書き出し、シートの先頭に次の 1 行を置くと、
yaml-language-server に対応したエディタで key の補完と検証が効く(設定は [`CONFIG.md`](CONFIG.ja.md) の editor)。

```yaml
# yaml-language-server: $schema=/home/USER/.config/wayhint/schema.json
```
