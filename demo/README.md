# demo — 紹介動画を scenario から生成する

手で画面録画すると、hint の中身もタイミングも窓の配置も毎回ずれ、機能を直すたびに撮り直しに
なる。ここに置いた脚本(`scenario.yaml`)から動画を作れば、**同じマシンでは frame 単位で同じ
ものが出る**。設計の理由は `docs/DECISIONS.md` 0031。

```sh
./scripts/demo                     # 脚本を読んで、何を撮るかと尺を表示する(録画しない)
./scripts/demo --validate          # 脚本の検証だけ。壊れていれば exit 1
./scripts/demo --record            # en と ja を録る → demo/out/<lang>/
./scripts/demo --record --lang ja  # 片方だけ
```

依存(録画のときだけ): `ffmpeg` `grim` `imagemagick` `foot` `labwc` `wtype` と
`fonts-noto-cjk` `fonts-noto-mono`。足りなければ **apt の package 名を出して止まる**。
`wtype` は `key:` / `type:` を使う脚本でだけ要る。`./scripts/check` はこれらに依存しない。

録画は自分専用の compositor をヘッドレスで立てて、その中で行う。画面には何も出ず、いま使って
いるセッションにも `~/.config/wayhint/` にも触らない(DECISIONS 0030 の隔離をそのまま使う)。

## 出力

| ファイル | 中身 |
|---|---|
| `wayhint-demo.mp4` / `.webm` | H.264 / VP9。caption は焼き込み(`--no-burn` で外せる) |
| `contact-sheet.png` | 各 step の代表 frame を格子に並べたもの。**まずこれを見る** |
| `steps/NN-<id>.png` | step ごとの代表 frame。README に貼る静止画にも使える |
| `captions.srt` | 焼き込み無しで使うとき用の字幕 |
| `frames/` | `--keep` のときだけ残る。連番の hard link で、実体は `steps/` の PNG |

`demo/out/` は `.gitignore`。**動画も PNG も commit しない。**

## 反復するとき

```sh
./scripts/demo --record --only show-hints,mixed-in   # この step だけ
./scripts/demo --record --from enter-edit            # ここから最後まで
./scripts/demo --record --lang en --keep             # frame の PNG を残す
```

step には前提が書いてあるものがある(`precondition`)。overlay が出ていないと意味のない step を
`--only` で単独に撮ろうとすると、**空の動画を作らずに** そう言って止まる。`--from` で前を含める。

## scenario の書き方

```yaml
output: {width: 1280, height: 720, fps: 30}
fonts: {ui: "Noto Sans CJK JP", mono: "Noto Sans Mono"}
windows:
  - {title: Claude Code, x: 36, y: 52, width: 620, height: 430}
steps:
  - id: show-hints
    key: super+h
    wait_for: {overlay: visible, label: "Claude Code", hints: 11}
    caption: {en: "Super+H — …", ja: "Super+H — …"}
    hold: 4.0
```

- `output` — 撮る大きさ。headless の既定は 1280×720 で、違えば録画の最初に fail する。
- `fonts` — 起動時に `fc-match` で存在を確かめ、caption の焼き込みにも使う。
- `windows` — 窓の置き場所。`title` は `spawn` から参照する名前であり、compositor の
  `windowRules` が照合する窓 title でもある。**位置を固定しないと再現しない。**
- `steps` — 上から順に。**1 step に action はちょうど 1 つ**。

### step の key

| key | 意味 |
|---|---|
| `id` | step の名前。`--only` / `--from` で使い、出力ファイル名にも入る。重複不可 |
| *action* | 下の表から**ちょうど 1 つ** |
| `wait_for` | **必須**。この条件が満たされてから撮る。既定の timeout は 10 秒 |
| `hold` | 秒。`fps` を掛けて frame 数に丸める。0 なら動画には出ない(静止画には残る) |
| `caption` | `{en: …, ja: …}`。両方書く。省略すれば caption 無し |
| `precondition` | 任意。**action の前に**満たしているべき条件。`--only` の安全網 |

### action

| action | 書き方 | すること |
|---|---|---|
| `spawn` | `{window: <名前>, argv: [...]}` | 窓を起動する。`argv` の `{demo_bin}` は `demo/bin` に展開 |
| `key` | `super+ctrl+h` | wtype で compositor に送る。修飾は `super` `ctrl` `shift` `alt` |
| `type` | `"文字列"` または `{en: …, ja: …}` | wtype で文字を打つ |
| `press` | `{button: search}` | overlay のボタンを AT-SPI で押す。`search` `done` `copy` `editor` `edit` `close` |
| `cli` | `refresh` | `wayhint <cmd>` を直接呼ぶ(hotkey の無いもの用) |
| `write` | `{file: "hints/{lang}/foot.yaml", text: …}` または `{… , source: "fixtures/…"}` | fixtures の作業コピーを書き換える(自動 reload を見せる用) |

`{demo_bin}` と `{lang}` 以外の置換は無い。scenario の文字列が command として実行されることも
無い(action は固定集合、argv も固定、`shell=True` は使わない)。

### wait_for / precondition に書ける条件(すべて AND)

| 条件 | 見るもの |
|---|---|
| `toplevel: <regex>` | 前面の窓の app_id |
| `context: {process_name: …, active_sheet: …}` | `wayhint context` が答える foreground process と sheet |
| `overlay: visible \| hidden` | overlay が AT-SPI に出ているか |
| `label: <text>` / `no_label: <text>` | overlay に見えている文字。**UI 文言は英語の原文で書く**(`src/wayhint/i18n.py` の key。ja では自動で訳が照合される) |
| `button: <名前>` | そのボタンが出ているか(`press` と同じ名前) |
| `hints: <n>` | 一覧に見えている行数 |
| `timeout: <秒>` | 既定 10 |

**`press` の直後は必ず条件で待つ。** AT-SPI の click は要求であって完了ではないので、待たずに
`type` すると文字が overlay ではなく下の窓に落ちる。

## 新しい場面を足すとき

1. `scenario.yaml` に step を足す。UI 文言を条件にするなら英語の原文(i18n の key)で書く。
2. `./scripts/demo` で尺を確認する。
3. `./scripts/demo --record --lang en --only <新しい id> --keep` で 1 場面だけ撮り、
   `demo/out/en/steps/` の PNG を見る。前提が要る場面は `--from` で前を含める。
4. 両言語を通す(`./scripts/demo --record`)。ja は文字幅が違うので、行が切れていないか
   `contact-sheet.png` で見る。
5. 再現するか確かめる。2 回撮って全 frame を比べる:

   ```sh
   ./scripts/demo --record --lang en --keep && mv demo/out/en demo/out/_a
   ./scripts/demo --record --lang en --keep
   seq -f '%06g' 1 <frame 数> | xargs -P 8 -I{} \
     compare -metric AE demo/out/_a/frames/{}.png demo/out/en/frames/{}.png null:
   ```

   差が出るのは、たいてい**画面の中で何かが動いている**とき。既に止めてあるのは foot の
   cursor(`fixtures/foot.ini`)と overlay の caret(最後の打鍵から約 8 秒で自然に止まるのを
   待っている)。新しく動くものを画面に入れたら、止める方法を探すか、止まるまで待つ。

## fixtures と stub

`fixtures/` は録画のたびに `/tmp/wayhint-demo-<uid>-<lang>/config` へ丸ごとコピーされ、daemon が
読むのはそのコピー。**編集モードの場面と YAML error の場面はそのコピーを書き換える**ので、
`fixtures/` 自身は録画で変わらない。パスが固定なのは、YAML error の場面で overlay が
そのパスを表示するため(`mkdtemp` だと毎回違う文字列が frame に写る)。

`appearance.language` だけは言語ごとに書き換えられる。それ以外は書いてあるとおりに使われるので、
`wayhint validate --config-dir demo/fixtures` が通る状態に保つこと。

font は **fixtures の側で固定してある**——`style.css` は `examples/style.css` の `sans-serif` /
`monospace` を `Noto Sans CJK JP` / `Noto Sans Mono` に置き換えたもので、`foot.ini` も同じ
mono を指す。このマシンの `sans-serif` は VL ゴシックに解けるので、pin しないと Noto では
撮れない。`scenario.yaml` の `fonts:` は起動時の存在確認と caption の焼き込みに使う。

`bin/` の `claude` と `vi` は**本物ではない**。固定の偽画面を出して stdin で待つだけの
python script で、大事なのは **ファイル名**だけ——wayhint は端末の foreground process を
`/proc` から見つけ、`argv[0]` の basename(interpreter なら `argv[1]` の basename)を名前に
するので、`#!/usr/bin/env python3` の script `claude` は `claude` として照合される
(`exec -a` は要らない)。**stub の中から別のプロセスを起動しないこと**——`sleep` のような子を
作ると、そちらが foreground process として答えられてしまう。

`bin/foot-wayhint` は README「Terminal の複数窓」の wrapper そのもので、窓の app_id に自分の
pid を入れる。デモは利用者と同じ経路を通っていて、daemon にデモ用の分岐は一切無い。
