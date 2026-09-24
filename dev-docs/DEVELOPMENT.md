# DEVELOPMENT — 開発するときの手順と repository の構成

使う人向けの説明は `README.md` と `docs/`。ここは wayhint 自体を直すときに要るものだけを置く。
agent 向けの取り決めは `AGENTS.md` が正。

## 準備と検証

```sh
./scripts/setup                 # .venv(system site-packages 共有)+ ruamel.yaml + pywayland(+ PyWayfire)+ dev 依存
.venv/bin/pip install -e .      # wayhint / wayhintd を .venv/bin に置く
./scripts/check                 # lint + 単体テスト。検証の入口はこれ 1 本
```

合否は exit code で判断する(`AGENTS.md` §3)。

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

## Python を変えたあと

`wayhint reload` が読み直すのは YAML だけなので、コードを変えたら daemon を入れ替える。手順は
`README.md`「daemon を再起動する」。

## ファイル構成

| パス | 内容 |
|---|---|
| `STATUS.md` | 何が終わっていて、何が残っていて、実機がどうなっているか |
| `src/` | 実装 |
| `tests/` | テスト |
| `docs/` | 使う人向けの説明(`CONFIG.md`、`HOTKEYS.md`、`SHEET-FORMAT.md`、`SHEETS.md`、`TERMINALS.md`) |
| `dev-docs/PRODUCT.md` | 要件 |
| `dev-docs/DESIGN.md` | 設計 |
| `dev-docs/DECISIONS.md` | 決定の記録 |
| `dev-docs/PHASE0.md` | Phase 0 の依存確認 |
| `examples/` | config.yaml と sheet の雛形 |
| `demo/` | 紹介動画。`showcases/<name>/` に台本と脚本、`fixtures/` と `bin/` は共通(`demo/README.md`) |
| `tools/` | repository の道具。headless session(テストとデモで共有)と動画生成 |
| `scripts/` | `setup`、`check`、`check-gui`、`demo`、`setup-terminals`、この repository 専用の agent hook |
| `.agents/skills/` | agent 間で共有する skill |
| `.claude/`、`.codex/` | vendor ごとの adapter 設定(手で編集しない) |

## agent 向けの取り決め

共通の指示は `AGENTS.md` にまとめてあり、`CLAUDE.md` はそこを指すだけ。vendor 固有の設定は
`.claude/` と `.codex/` に閉じている。共通の hook は user scope に一度だけ登録してあり、この
repository には置かない。
