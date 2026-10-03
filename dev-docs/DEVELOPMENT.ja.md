# DEVELOPMENT — 開発するときの手順と repository の構成

[English](DEVELOPMENT.md)

使う人向けの説明は `README.md` と `docs/`。ここは wayhint 自体を直すときに要るものだけを置く。

## 準備と検証

```sh
./scripts/setup                 # .venv(system site-packages 共有)+ ruamel.yaml + pywayland + regex(+ PyWayfire)+ dev 依存
.venv/bin/pip install -e .      # wayhint / wayhintd を .venv/bin に置く
./scripts/check                 # lint + 単体テスト。検証の入口はこれ 1 本
```

合否は exit code で判断し、最後に出た数行では判断しない。`| tail` `| grep` `| head` で絞った出力を
`&&` や `if` の条件にしない——pipeline は最後のコマンドの status で終わるので、失敗した検査が通った
ように見える。絞らずに実行するか、前に `set -o pipefail` を置くか、出力をファイルか変数に取って後で
出す。新しい検査は別のコマンドにせず `./scripts/check` に足す。

文書には日本語版 `<name>.ja.md` が隣にある(DECISIONS 0044)。両方を同じ commit で直す。片方が無いか、
見出しの並びが食い違うと `./scripts/check` が失敗する。

## GUI テスト

`./scripts/check-gui` は compositor を headless backend で立て、その中で overlay を実際に
表示させて位置と中身を測る(DECISIONS 0030)。画面には何も出ず、いま使っているセッションにも触らない。
配置、overlay の中身、command から window までの経路を変えたときに `./scripts/check` と合わせて流す。

```sh
sudo apt install grim imagemagick        # 位置の測定に使う
sudo apt install wtype                   # 任意: hotkey 経路のテスト。無ければその 1 本だけ skip
./scripts/check-gui
```

compositor は `labwc` / `sway` / `cage` のうち PATH にあるものを使う。`at-spi2-core` は
overlay の中身を読むのに使うが、GTK の依存として通常すでに入っている。追加の権限は要らない
(`wtype` は compositor の virtual-keyboard protocol を使うので `/dev/uinput` に触らない)。

## 紹介動画

`./scripts/demo` は `demo/showcases/<name>/` の脚本を同じ headless compositor の中で再生して録画する
(DECISIONS 0031、0032)。`--record` を付けない限り、何を撮るかと尺を表示するだけで録らない。

```sh
sudo apt install ffmpeg grim imagemagick foot wtype fonts-noto-cjk fonts-noto-mono
./scripts/demo                                  # showcase の一覧
./scripts/demo --showcase herdr                 # 予定の尺と step
./scripts/demo --showcase herdr --record        # out/ja/<variant>/ に mp4 / webm / contact sheet
```

脚本の書き方、showcase の作り方、場面の足し方は `demo/README.md`。

## Debian パッケージ

`./scripts/build-deb [unstable|trixie]` は、`debian/` から各リリースのまっさらなコンテナで `.deb` を作り
(指定しなければ両方)、別のまっさらなコンテナに入れて一度動かし、lintian の指摘を出す。docker と
ネットワークが要り、`./scripts/check` には入っていない。作るのは git から見た作業ツリーで、未コミットの
変更も含む。できたものは `build/deb/<dist>/` に置かれる。trixie 版の版数は `<version>~deb13+1` で、
unstable 版より小さく並ぶ。版数そのものは `debian/changelog` の先頭の entry から取るので、
`pyproject.toml` の版数を変えたらそこにも entry を足し、`man/` のページの `.TH` 行の版数と日付も変える。

コードは、パッケージが依存するライブラリのうち一番古い版、つまり trixie の版(pywayland 0.4.18、
GTK 4.18、gtk4-layer-shell 1.0.4、Python 3.13)で動き続ける必要がある。特に `_wlr_foreign_toplevel.py`
は `scripts/gen-protocol` でだけ作り直す。scanner の出力を、0.4.18 にもあるものを import する形に書き換える。

## Python を変えたあと

`wayhint reload` が読み直すのは YAML だけなので、コードを変えたら daemon を入れ替える。手順は
`README.md`「daemon を再起動する」。

## ファイル構成

| パス | 内容 |
|---|---|
| `src/` | 実装 |
| `tests/` | テスト |
| `docs/` | 使う人向けの説明(`CONFIG.md`、`HOTKEYS.md`、`SHEET-FORMAT.md`、`SHEETS.md`、`TERMINALS.md`) |
| `dev-docs/PRODUCT.md` | 要件 |
| `dev-docs/DESIGN.md` | 設計 |
| `dev-docs/DECISIONS.md` | 決定の記録 |
| `dev-docs/PHASE0.md` | Phase 0 の依存確認 |
| `examples/` | config.yaml と sheet の雛形 |
| `skills/` | コードと一緒に公開する coding agent 向けの skill(`wayhint-add-sheet`: シートを書く。DECISIONS 0047) |
| `demo/` | 紹介動画。`showcases/<name>/` に台本と脚本、`fixtures/` と `bin/` は共通(`demo/README.md`) |
| `tools/` | repository の道具。headless session(テストとデモで共有)と動画生成 |
| `scripts/` | `setup`、`check`、`check-gui`、`demo`、`setup-terminals`、`gen-protocol`、`build-deb` |
| `man/` | man ページ `wayhint(1)` と `wayhintd(1)`。英語と `.ja`(コマンドとオプションが全部載っていることをテストが確かめる) |
| `debian/` | Debian パッケージ。`scripts/build-deb` が unstable と trixie 向けに作る(DECISIONS 0048) |

作者の coding agent 用の設定と作業記録は、公開 repository の外で持つ(DECISIONS 0045)。`.gitignore`
に並べてあるので、自分の設定を置いた clone でも commit されない。
