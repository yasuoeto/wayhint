# CONFIG — config.yaml と style.css の書き方

wayhint 全体の設定は `config.yaml`、見た目は `style.css` に書く。ヒントそのものの書き方は
README「ヒントを書く」。

## 置き場所

`$XDG_CONFIG_HOME/wayhint/`(既定 `~/.config/wayhint/`)の下。

| ファイル | 内容 |
|---|---|
| `config.yaml` | ヒント画面の位置・大きさ、言語、エディタ、混ぜるシートなど |
| `style.css` | 任意。GTK CSS で見た目を上書きする |
| `hints/<言語>/*.yaml` | ヒントのシート(README「ヒントを書く」) |

雛形は repository の `examples/` にある。`cp -r examples/. ~/.config/wayhint/` でまとめてコピーできる。

## 書き方の基本

- YAML で書く。**全部の項目が省略できる**。ファイル自体が無くても、下の既定値で動く。
- 知らない section や key は**エラー**になる(打ち間違いを黙って無視しないため)。
- 書いたら `wayhint validate` で確かめる。問題があれば `file:line: message` が出て exit 1 になる。
- 保存すると daemon が自動で読み直す。壊れている間は直前の正しい設定のまま動き、ヒント画面の上部に
  `⚠` で理由が出る。
- ヒント画面の大きさを grip で変えると、daemon が `overlay.width` / `height` だけを書き戻す。
  ほかの行やコメントはそのまま残る。

## 既定値の全体

何も書かないとこの内容になる。変えたい項目だけを書けばよい。

```yaml
overlay:
  anchor: top-right
  width: 420px
  height: 60%
  margin: {top: 24, right: 24}
  output: null
appearance:
  style: style.css
  language: auto
  show_category: true
editor:
  command: [gvim, --remote-silent, "+{line}", "{file}"]
  schema_modeline: false
  schema_path: ~/.config/wayhint/schema.json
nested:
  parent_tags: null
  parent_categories: null
include: []
context:
  backend: auto
  workspace: current
  live_update: false
search:
  max_results: 50
logging:
  level: warning
```

## overlay — ヒント画面の位置と大きさ

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `anchor` | `top-left` `top` `top-right` `left` `center` `right` `bottom-left` `bottom` `bottom-right` | `top-right` | 画面のどこに寄せるか |
| `width` / `height` | `420`、`"420px"`、`"30%"` | `420px` / `60%` | 大きさ。`%` は表示先の画面(output)の大きさに対する割合(0〜100) |
| `margin` | 整数(全辺)か `{top, right, bottom, left}` | `{top: 24, right: 24}` | 画面端からの距離(px)。書かなかった辺は 0 |
| `output` | output 名(例 `eDP-1`) | なし | 表示先が決められないときに使う output |

表示先の画面は、シートの `display.output` → 見ているウィンドウがある画面 → compositor がフォーカス中と
言う画面 → この `output`、の順に決まる。

```yaml
overlay:
  anchor: bottom-right
  width: 30%
  height: 500
  margin: 0          # 画面の角にぴったり付ける
```

### シートごとに変える

シートの `display:` に同じ key を書くと、そのシートを表示するときだけ上書きできる。書かなかった key は
`config.yaml` の値を使う。

```yaml
# hints/ja/inkscape.yaml(match とヒントは省略)
id: inkscape
title: Inkscape
display: {anchor: top-left, width: 360px}
```

## appearance — 見た目と言語

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `style` | ファイル名かパス | `style.css` | 読み込む CSS。相対パスは `~/.config/wayhint/` から |
| `language` | `auto` `en` `ja` | `auto` | ボタンの文字と、読むヒントのディレクトリ(`hints/<言語>/`)。`auto` はマシンの locale(`LC_ALL` → `LC_MESSAGES` → `LANG`)で、日英以外は英語 |
| `show_category` | `true` `false` | `true` | 一覧の右端に category を出すか |

`language` を変えると、ボタンの文字もヒントもその場で切り替わる。

## editor — エディタ

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `command` | 文字列の list(argv) | `[gvim, --remote-silent, "+{line}", "{file}"]` | 「エディタで編集」で起動するコマンド |
| `schema_modeline` | `true` `false` | `false` | 新しく作るシートと `wayhint format` の先頭に schema の行を付けるか |
| `schema_path` | パス | `~/.config/wayhint/schema.json` | schema の行に書くパス。`wayhint schema --write` の既定の出力先 |

`command` で使える placeholder は `{file}`(必須)、`{line}`、`{hint_id}` の 3 つ。shell を通さずに
そのまま起動するので、引用符・パイプ・環境変数の展開は書けない。

```yaml
editor:
  command: [code, --goto, "{file}:{line}"]
```

```yaml
editor:
  command: [foot, -e, nvim, "+{line}", "{file}"]   # 端末の中で開く
```

## nested — 親シートのヒント

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `parent_tags` | タグの list | なし | 子シートの一覧に並べる親のヒントを、このタグで絞る |
| `parent_categories` | category の list | なし | 同じく category で絞る。タグと両方書けば OR |

**ふつうは書かない。** 何も書かなければ親のヒントは全部並び、絞りたいときは親のシートに
`nested.export_tags` / `export_categories` を書く。ここは「どの親のヒントも子に混ぜない」ときに `[]` を
書くためのもの(`[]` はもう片方に何が書いてあっても 0 件)。

```yaml
nested: {parent_tags: []}   # 親のヒントを一切混ぜない
```

ここに絞りを書くと全部の親シートの `export_*` より優先されるので、親ごとに絞りを変えられなくなる。
規則の全体は [`SHEETS.md`](SHEETS.md) §3。

## include — 全シートに混ぜるシート

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `include` | シート id か `{sheet, tags, categories}` の list | `[]` | `include:` を書いていないシート全部に混ぜるシート。map にすると一部だけ混ぜる |

シートに `include:` を書くと、そのシートではこの値を**置き換える**(足し算ではない)。

```yaml
include:
  - wm
  - {sheet: git, categories: [基本]}   # git の「基本」category だけ
```

規則の全体は [`SHEETS.md`](SHEETS.md) §4。

## context — ウィンドウの調べ方

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `backend` | `auto` `wayland` `wayfire` | `auto` | どうやってフォーカス中のウィンドウを調べるか。`auto` は Wayland 標準の protocol を使い、無ければ Wayfire IPC |
| `workspace` | `current` `all` | `current` | `current` は出した workspace にだけ出す。`all` は全 workspace に出す(compositor が `ext-workspace-v1` を出す場合だけ効く) |
| `live_update` | `true` `false` | `false` | 書けるが、いまは効果が無い。中身は常にヒント画面を出した瞬間のウィンドウで決まる |

## search — 検索

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `max_results` | 1 以上の整数 | `50` | 検索で表示する件数の上限 |

## logging — ログ

| key | 値 | 既定 | 意味 |
|---|---|---|---|
| `level` | `debug` `info` `warning` `error` | `warning` | daemon のログの細かさ。`wayhintd -v` で起動すると info が前景に出る |

## style.css — 見た目

GTK4 の CSS で書く。wayhint 既定の見た目の上に重ねて読まれるので、変えたいところだけ書けばよい。
雛形 `examples/style.css` は labwc のテーマ(Syscrash)に合わせた配色で、使える class 名と書き方の例は
そこを見るのが早い。

- **反映には daemon の再起動が要る**(README「daemon を再起動する」)。`config.yaml` やシートと違い、
  保存しても自動では読み直さない。
- ファイルが無ければ既定の見た目で動く。
- 別の名前や場所にしたいときは `appearance.style` を変える。

使える class 名:

| セレクタ | 部分 |
|---|---|
| `window.wayhint` | ヒント画面全体(背景色・文字色・角の丸み) |
| `.wayhint-header` | 上部のシート名 |
| `.wayhint-context` | シート名の下の context(`foot · vi · eDP-1`) |
| `.wayhint-error` | `⚠` の行 |
| `.wayhint-row` | 一覧の 1 行。favorite の行には `.favorite` も付く |
| `.wayhint-key` / `.wayhint-title` / `.wayhint-command` / `.wayhint-category` | 行の中の key / title / command / category |
| `.wayhint-detail` | 行を選んだときに開く詳細 |
| `.wayhint-chip` | 絞り込み中を示す chip |
| `.wayhint-toolbar` | 下部のボタン列(`.wayhint-toolbar button` でボタン) |
| `.wayhint-form` / `.wayhint-form-title` / `.wayhint-form-label` / `.wayhint-form-note` | 編集モードのフォーム |
| `.wayhint-help` | 編集モードで下に出るキーの説明 |
| `.wayhint-grip-both` / `.wayhint-grip-x` / `.wayhint-grip-y` | 大きさを変える grip(角 / 横 / 縦) |

```css
/* 例: 少し大きな文字で、key を黄色に */
window.wayhint { font-size: 1.1em; }
.wayhint-key { color: #f9e2af; }
```
