# demo — 紹介動画を脚本から生成する

[English](README.md)

手で画面録画すると、hint の中身もタイミングも窓の配置も毎回ずれ、機能を直すたびに撮り直しに
なる。ここに置いた脚本から動画を作れば、**同じマシンでは frame 単位で同じものが出る**。
設計の理由は `dev-docs/DECISIONS.md` の 0031(生成のしくみ)と 0032(showcase と Herdr)。

```sh
./scripts/demo                                    # showcase の一覧。録画しない
./scripts/demo --showcase herdr                   # 予定の尺と step。録画しない
./scripts/demo --showcase herdr --validate        # 脚本の検証だけ。壊れていれば exit 1
./scripts/demo --showcase herdr --record          # 全 variant を録る → out/ja/<variant>/
./scripts/demo --showcase herdr --variant 60s --record
./scripts/demo --showcase herdr --record --out-dir ~/videos/wayhint   # 別の場所へ出す
```

依存(録画のときだけ): `ffmpeg` `grim` `imagemagick` `foot` `labwc` `wtype`、`fonts-noto-cjk`
`fonts-noto-mono`、showcase が Herdr を使うなら `herdr`。足りなければ **apt の package 名を出して
止まる**。`wtype` は `key:` / `type:` を使う脚本でだけ要る。`./scripts/check` はこれらに依存しない。

録画は自分専用の compositor をヘッドレスで立てて、その中で行う。画面には何も出ず、いま使って
いるセッションにも `~/.config/wayhint/` にも `~/.config/herdr/` にも触らない。

## showcase

動画 1 本分が 1 つの showcase で、`demo/showcases/<name>/` に閉じている。**showcase の正体は
ディレクトリ名**で、中のファイルは名前の末尾の役割で探す。

```
demo/
  fixtures/                       全 showcase 共通(config.yaml, style.css, foot.ini, hints/<lang>/)
  bin/                            全 showcase 共通の stub と wrapper
  showcases/
    herdr/
      01_herdr_storyboard.md      台本。人が書く
      02_herdr_scenario.yaml      脚本。recorder が読む
      out/<lang>/<variant>/       生成物。追跡しない
```

いまある showcase:

| showcase | variant | 中身 |
|---|---|---|
| `herdr` / `terminal` / `gui` | `main` | 見つけ方 3 本。Herdr の中・端末の中・GUI アプリ |
| `common` | `overview` / `search` / `edit` / `sheets` | 共通の動作を中身で 4 本に分けたもの(DECISIONS 0042) |
| `all` | `60s` / `180s` / `300s` | 上の 7 本の場面を写してまとめた通しの動画(DECISIONS 0043)。**字幕は元の showcase と 2 か所にある**ので、直すときは両方 |

ファイル名は `<NN>_<showcase>_<role>.<ext>`。番号は人が工程順に並べるためのもので、ツールは
見ない。役割は `storyboard`(`.md`)と `scenario`(`.yaml`)。中央部分がディレクトリ名と違えば
**警告**(名前を直しそこねたコピーでも録画は通す)、同じ役割のファイルが 2 つあれば **error**
(どちらを使うべきか決められない)。

新しい showcase を作るには、ディレクトリを 1 つ足して台本と脚本を置くだけでよい。`fixtures/` と
`bin/` は共通なので、必要な sheet や stub だけを足す。

## 台本と脚本の役割(どちらを直すか)

| 決めること | 正 |
|---|---|
| 何を訴えるか、どの場面を、どの順で | **`01_*_storyboard.md`** |
| 実行する action、`hold`、字幕の実際の文言、variant の step 構成 | **`02_*_scenario.yaml`** |

調整中は脚本の側で字幕と秒数を詰め、**確定したら台本に書き戻す**。訴求そのものや場面の増減が
必要になったときは、台本を勝手に書き換えず相談する。

| 直したいもの | 触るファイル | 確かめかた |
|---|---|---|
| 字幕の文、秒数 | 脚本の `caption` / `hold` | `--showcase X --record --only <step>` |
| 場面の追加・順序 | 脚本の `steps` / `variants` | `--showcase X`(尺を見る)→ `--record` |
| hint の中身 | `fixtures/hints/<lang>/` | `wayhint validate --config-dir demo/fixtures` |
| 端末に映る中身 | `demo/bin/` の stub | `--record --only <その場面>` |
| 訴求の方針 | 台本(要相談) | — |

英語版を作るときは `fixtures/hints/en/` と各 `caption.en` を足して `--lang en`。`steps` と
`variants` は触らない。

## 出力

`out/<lang>/<variant>/` に次が出る。`<stem>` は `wayhint-<showcase>-<variant>.<lang>`。
`--out-dir <path>` を付けると `<path>/<lang>/<variant>/` に出る(`out/` を symlink にするのは
**不可**——録画は `<lang>/<variant>` を消してから始めるので、link をたどった先を消すことになる)。
`--out-dir` が取るのは**空のディレクトリか、前にここが書いたディレクトリ**だけで、目印の
`.wayhint-demo-out` が無い中身入りのディレクトリは消さずに断る。

| ファイル | 中身 |
|---|---|
| `<stem>.mp4` | 素。字幕なし。自分で字幕を付けたいとき用 |
| `<stem>.sub.mp4` | 字幕を焼き込んだもの。そのまま投稿できる |
| `<stem>.webm` | 焼き込み版の VP9。H.264 を再生できないページ用 |
| `<stem>.square.mp4` | `square: true` の variant だけ。右端から 1:1 に切る(overlay が右上なので) |
| `<stem>.srt` | 字幕。**素の mp4 と組にして使う**ので、焼き込みとは別に必ず出す |
| `contact-sheet.png` | 各 step の代表 frame を格子に並べたもの。**まずこれを見る** |
| `steps/<NN>-<id>.png` | step ごとの代表 frame。README に貼る静止画にも使える |
| `frames/` | `--keep` のときだけ残る。連番の hard link で、実体は `steps/` の PNG |
| `stills/` | `steps/` に動画と同じ字幕を焼き込んだもの。`.sub.mp4` のその step の frame と同じ画(圧縮による劣化だけが無い) |
| `review/` | `--review` のときだけ。採用版から変わった step の切り抜き(下の「撮り直しを見る」) |

README の画像と動画はこの出力の写しで、`out/` は追跡しないので `docs/media/` に置いてある。
`overlay.en.png` / `overlay.ja.png` は各言語の `all` の `60s` の静止画 `steps/03-q-show-hints.png` から
空の字幕帯を切ったもの(`magick <静止画> -crop 1280x640+0+0 +repage <png>`)、`wayhint-demo-60s.en.mp4`
は `all/out/en/60s/wayhint-all-60s.en.sub.mp4`。`all` を撮り直したら写し直す。

## 脚本の書き方

```yaml
output: {width: 1280, height: 720, fps: 30}
fonts: {ui: "Noto Sans CJK JP", mono: "Noto Sans Mono"}
windows:
  - {title: Herdr, x: 32, y: 48, width: 620, height: 580}
steps:
  - id: show-hints
    key: super+h
    wait_for: {overlay: visible, label: "Claude Code", hints: 10}
    caption: {ja: "hotkey 一発。いつも右上。"}
    hold: 7.0
variants:
  3min: {target: 160, tolerance: 30, steps: [open-herdr, show-hints, …]}
```

- `output` — 撮る大きさ。headless の既定は 1280×720 で、違えば録画の最初に fail する。
- `fonts` — 起動時に `fc-match` で存在を確かめ、字幕の焼き込みにも使う。
- `windows` — 窓の置き場所。`title` は `spawn` / `close` から参照する名前であり、compositor の
  `windowRules` が照合する窓 title でもある。**位置を固定しないと再現しない。**
- `steps` — 全 step を 1 回ずつ定義する。ここに書いただけでは録画されない。
- `variants` — 実際に録るもの。下記。

### variant は完全な列

`variants.<name>.steps` は step id を並べたもので、**clean session からその列だけを順に実行して
成立しなければならない**。variant 間で状態を引き継がず、隠れた準備 step も自動の依存解決も無い。
どの variant にも入っていない step があれば error になる。

同じ操作を別の尺で使いたいときは、**step を複製して別の id にする**(`show-hints` と
`show-hints-60`)。variant ごとに `hold` を上書きする仕組みはわざと持っていない——脚本を読んでも
何が録れるか分からなくなるため。

| variant の key | 意味 |
|---|---|
| `target` | 台本の尺割りから引いた秒数 |
| `tolerance` | 許容差。`--dry-run` が `target ± tolerance` を外れたら exit 1 |
| `square` | true なら `.square.mp4` も出す。60 秒版など SNS 向けのものに付ける |
| `steps` | step id の列 |

### step の key

| key | 意味 |
|---|---|
| `id` | step の名前。`--only` / `--from` と出力ファイル名に使う。重複不可 |
| *action* | 下の表から**ちょうど 1 つ** |
| `wait_for` | **必須**。この条件が満たされてから撮る。既定の timeout は 10 秒 |
| `hold` | 秒。`fps` を掛けて frame 数に丸める。0 なら動画には出ない(静止画には残る) |
| `caption` | `{ja: …}`。ja は必須、`en` は任意(`--lang en` で録るときだけ必要)。1 枚 25 文字まで |
| `precondition` | 任意。**action の前に**満たしているべき条件。`--only` の安全網 |

### action

| action | 書き方 | すること |
|---|---|---|
| `spawn` | `{window: <名前>, argv: [foot-herdr]}` / `{…, argv: [foot-wayhint, -e, vi]}` | 窓を起動する。argv[0] は `demo/bin` の端末 wrapper(`foot-wayhint` か `foot-herdr`)。`foot-wayhint` は **`-e <stub 名>` が必須**——command 無しの foot は login shell を開くので拒否する。`foot-herdr` は Herdr 自身を起動するので command を取らない。オプションは `--app-id=foot-<名前>` だけ。**すべて名前だけ**(絶対パス不可) |
| `close` | `{window: <名前>}` | その窓を閉じる。focus が下の窓へ戻るので、別のアプリを見せて帰ってこられる |
| `key` | `super+ctrl+h` | wtype で 1 打鍵を送る。修飾は `super` `ctrl` `shift` `alt`。**用途は修飾キー付きの操作(`super+h` など)と単独の特殊キー(`enter` `tab` `esc` `down`)**。`wtype -k` は shift レベルが乗らないので、大文字や shift の要る記号はここでは送れない(`key: J` も `key: shift+j` も窓には `j` が届く。labwc 0.20.2 / wtype 0.4 で実測) |
| `type` | `"文字列"` または `{ja: …, en: …}` | wtype の text mode で文字を打つ。**大文字・記号はこちら**——`type: "J"` なら `J` が届く。編集モードの `J` / `K` もこれで送っている |
| `press` | `{button: search}` | overlay のボタンを AT-SPI で押す。`search` `done` `copy` `editor` `edit` `close` `clear-filter`(絞り込み chip の `×`) |
| `cli` | `refresh` | `wayhint <cmd>` を直接呼ぶ(hotkey の無いもの用) |
| `herdr` | `[tab, focus, "w1:t2"]` | Herdr の CLI。下記の許可 list に限る |
| `write` | `{file: "hints/{lang}/herdr.yaml", text: …}` または `{…, source: "fixtures/…"}` | fixtures の作業コピーを書き換える(自動 reload を見せる用) |
| `pause` | `true` | 何もしない。**字幕だけを出す step** に使う |

置換は `{lang}` だけ。プログラムは**名前で**書き、パスへの解決は recorder が行うので、脚本の
文字列が PATH 解決に触れることも、command として実行されることも無い(action は固定集合、argv も
検証済み、`shell=True` は使わない)。

### `herdr:` の許可 list

Herdr は実物が動くので、呼べる subcommand と引数を固定してある。list 外は `--validate` で exit 1。

| subcommand | 許される引数 |
|---|---|
| `pane list` / `pane current` / `tab list` / `workspace list` | なし |
| `pane process-info` | `--current` または `--pane <wN:pN>` |
| `pane run` | `<wN:pN> <program>`。program は **`demo/bin` にある実行ファイルの名前だけ**(`/` も `..` も不可、実在を確認) |
| `pane split` | `--direction right\|down`(必須)、`--pane <wN:pN>` / `--current`、`--focus` / `--no-focus` |
| `pane focus` | `--direction left\|right\|up\|down`(必須)、`--pane <wN:pN>` / `--current` |
| `pane close` | `<wN:pN>` |
| `tab create` / `workspace create` | `--focus` / `--no-focus` のみ |
| `tab focus` | `<wN:tN>` |
| `workspace focus` | `<wN>` |
| `status` | `--json` |

`--cwd` `--env` `--label` は脚本から渡せない(画面に出る文字列や作業場所は recorder が決める)。
`server stop` は recorder の後片付け専用で、脚本に書くと exit 1。

### wait_for / precondition に書ける条件(すべて AND)

| 条件 | 見るもの |
|---|---|
| `toplevel: <regex>` | 前面の窓の app_id |
| `context: {process_name: …, active_sheet: …}` | `wayhint context` が答える foreground process と sheet |
| `overlay: visible \| hidden` | overlay が AT-SPI に出ているか |
| `label: <text>` / `no_label: <text>` | overlay に見えている文字。**UI 文言は英語の原文で書く**(`src/wayhint/i18n.py` の key。ja では自動で訳が照合される) |
| `first_hint: <text>` | **一覧の先頭行**にその文字があるか。`J` / `K` の並べ替えはこれでしか見えない(行の集合は変わらない) |
| `text: <text>` | **入力欄に入っている文字**。form や検索に打った文字が overlay に届いたかを見る。label は対象外 |
| `button: <名前>` | そのボタンが出ているか(`press` と同じ名前) |
| `hints: <n>` | 一覧に見えている行数。**保存や絞り込みが効いたかはこれで確かめる** |
| `unchecked: "<理由>"` | 上のどれでも判定できない step だと**書いて**宣言する。下の警告が消える。10 文字未満は exit 1 |
| `timeout: <秒>` | 既定 10 |

**`press` の直後は必ず条件で待つ。** AT-SPI の click は要求であって完了ではないので、待たずに
`type` すると文字が overlay ではなく下の窓に落ちる。

## 新しい場面を足すとき

1. 台本を読み、足す場面がその訴求に合っているか確かめる。合っていなければ台本の相談が先。
2. 脚本に step を足し、`variants` の列に入れる。UI 文言を条件にするなら英語の原文で書く。
3. `./scripts/demo --showcase X` で尺を見る。`target ± tolerance` を外れたら `hold` を調整する。
4. `--record --variant <v> --only <新しい id> --keep` で 1 場面だけ撮り、`out/.../steps/` の PNG を
   見る。前提が要る場面は `--only` に必要な step を並べる。
5. 通しで撮る(`--record`)。行が切れていないか `contact-sheet.png` で見る。
6. 再現するか確かめる。2 回撮って全 frame を比べる:

   ```sh
   ./scripts/demo --showcase X --variant 60s --record --keep --out-dir /tmp/take-a
   ./scripts/demo --showcase X --variant 60s --record --keep --out-dir /tmp/take-b
   seq -f '%06g' 1 <frame 数> | xargs -P 8 -I{} compare -metric AE \
     /tmp/take-a/ja/60s/frames/{}.png /tmp/take-b/ja/60s/frames/{}.png null:
   ```

   `--out-dir` に出すのは、**確認のための録画で採用済みの `out/` を消さない**ため(録画は出力先を
   消してから始める)。

   差が出るのは、たいてい**画面の中で何かが動いている**とき。既に止めてあるのは foot の cursor
   (`fixtures/foot.ini`)、overlay の caret(最後の打鍵から約 8 秒で自然に止まるのを待っている)、
   Herdr の workspace 名と窓 title(下記)。新しく動くものを入れたら、止める方法を探す。

   止まっていないものが 2 つある。**Herdr の tab 脇の状態記号**(`·` と `○`)は、直近の出力からの
   経過時間で変わるので、`wait_for` を足すなどして撮る瞬間が 1 秒ずれると、その場面だけ 15px
   ほど差が出る(2026-09-23 実測、5 分版の `wrong-hints`)。同じ条件で 2 回撮る分には出ない。
   **端末の app_id に入る pid**(`demo/bin/foot-wayhint` の `foot.p$$`)は撮るたびに変わり、
   terminal の `context-cli` で 50x10px ほどの差になる(2026-09-24 実測)。wayhint が端末の中の
   プロセスを見つける仕組みそのものなので止めない。桁数は最大 7 で、行の折り返しは変わらない。

## 撮り直しを見る

撮り直しで変わるのは数十 step のうち数枚のことが多い。全部の静止画や contact sheet を見直す代わりに、
**採用版(`out/`)から変わった step だけ**を見る:

```sh
./scripts/demo --showcase X --variant main --record --out-dir /tmp/take --review
```

`--review` は `--out-dir` の新しい take と `out/` の採用版の `stills/`(字幕入り)を **step id で**
突き合わせる(番号は step を足すとずれるので使わない)。字幕だけの変更も `changed` に出る。
`stills/` ができる前に撮った採用版には無いので、そのときは `steps/`(字幕なし)で比べて警告を出す。
採用版を一度撮り直せば以後は字幕込みになる。結果は `<out-dir>/<lang>/<variant>/review/` に出る:

| 種類 | 出るもの |
|---|---|
| `changed` | 変わった画素を囲む範囲を 32px 広げて、**縮めずに**切り抜いた PNG |
| `new` | 採用版に無い step。比べる相手が無いので frame 全体 |
| `removed` | 新しい take から消えた step。一覧に出るだけ |
| `same` | 画素が同じ。数だけ出て、何も書かない |

撮り終えた take には `--record` を外して `--review` だけ付ければよい。`--out-dir` は必須
(採用版を上書きしないため)。見終えて採用するなら `out/` で撮り直す。

**agent に見させるときは `review/` の PNG だけを渡す。** 画像のトークンは面積に比例し、会話に残った
画像は以後の毎回の応答で読み直される。切り抜きは frame 全体より小さく、縮められないので行切れも
読める。見る観点(行切れ・字幕のはみ出し・写ってはいけないもの)を指示し、画像は別の文脈で読ませて
結果だけを文章で受け取る。`stills/` は動画の各 step と同じ画なので、動画そのものを見る必要は無い。
動画から frame を抜いて比べないのは、H.264 の劣化が撮るたびに違い、全 step が変わったと出るため。

## 台本から落とした場面

台本にはあるが、生成では撮れないもの。字幕で言い換えるか、単に出していない。

| 台本の箇所 | 落とした理由 |
|---|---|
| 冒頭のブラウザ検索、手元の映像 | 外部アプリと実画面。字幕で言い換えた |
| ヘッダーや一覧のズーム | 生成は 1 frame ずつの静止画。ズーム演出が無い |
| 行のクリック → 詳細ペイン | マウス操作。詳細は選択中の行で既に出ているので字幕で説明 |
| grip でのリサイズ | マウス操作 |
| 「エディタで編集」→ gvim | 本物の gvim は映さない。起動から保存ごとの再読込までは check-gui の T46b(`tests/fixtures/bin/fake-editor`)が検証している。YAML の中身は vi の stub で見せる |
| labwc の workspace 切替 | headless での workspace 操作は未検証 |
| ロゴ・URL の静止画面 | 合成の手段が無い。`pause` の字幕で代替 |
| キー表示(showmethekey) | 押したキーは字幕に含める |
| IME の変換過程 | wtype は確定した文字列を送るので変換中が映らない |
| 一覧の選択行を動かすこと | 編集モードの `↑` `↓` で動かせる(2026-09-23〜)が、動画には入れていない。単キー操作(`f` `J` `K`)は**先頭行**について見せる |

## fixtures と stub

`fixtures/` は録画のたびに `/tmp/wayhint-demo/<showcase>-<lang>/config` へ丸ごとコピーされ、
daemon が読むのはそのコピー。**編集モードの場面と YAML error の場面はそのコピーを書き換える**ので、
`fixtures/` 自身は録画で変わらない。パスが固定なのは、YAML error の場面で overlay が
そのパスを表示するため(`mkdtemp` だと毎回違う文字列が frame に写る)。

`appearance.language` だけは言語ごとに書き換えられる。それ以外は書いてあるとおりに使われるので、
`wayhint validate --config-dir demo/fixtures` が通る状態に保つこと。font は fixtures の側で固定して
ある(`style.css` と `foot.ini` が Noto を名指しする。このマシンの既定 sans-serif は VL ゴシック)。

1 本の showcase の途中でだけ使う sheet は `fixtures/` に置かず、その showcase の下に置いて `write` の
`source` で作業コピーへ入れる(`fixtures/` に置くと、他の showcase の一覧の件数まで変わる)。いまは
`showcases/herdr/narrowed/ja/herdr.yaml`(fixture の `herdr.yaml` に `nested.export_categories` の 2 行を
足したもの。`tests/test_demo_scenario.py` がずれを見る)と `showcases/terminal/foot/ja/foot.yaml`
(`^foot$` の端末シート)の 2 枚。

`bin/notes` は**GUI アプリの stub**(GTK4)。端末の中のプロセスではなく窓の `app_id`
(`dev.wayhint.demo.Notes`)で sheet が決まる側を見せるためのもので、`spawn` の許可 list では
端末 wrapper と別枠の `GUI_STUBS` に入っている(引数は取らない)。中身は label だけ——entry も
scrolled window もアニメーションも置かない。3 秒空けて 2 回撮って AE=0 を確認してある。

`bin/` の `claude` `codex` `vi` `less` は**本物ではない**。stdin で待つだけの python script で、
`claude` と `codex` は起動直後の待ち受け画面を出す。`vi` と `less` は**引数の sheet を実際に開いて**
先頭 14 行を固定幅で表示する(`common` が `match` / `include` と `hints/ja/` を画面で
指すため。固定の抜粋を出していたころは、字幕が画面に無い行を語っていた)。開けるのは session の
fixtures のコピーの中だけで、場所は `WAYHINT_DEMO_CONFIG` で渡す。`less` は最終行に
`<ファイル名> (END)` 相当を出し、`q` で終わる——**同じ端末で違うプロセスを動かす**ための 2 本目で、
`terminal` showcase の「窓が 2 枚、中のプロセスは別」はこれが無いと作れない。大事なのは 2 つ:

* **ファイル名**。wayhint は端末の foreground process を `/proc` から見つけ、`argv[0]` の basename
  (interpreter なら `argv[1]` の basename)を名前にするので、`#!/usr/bin/env python3` の script
  `claude` は `claude` として照合される。
* **`prctl(PR_SET_NAME)`**。Herdr が答える `name` は kernel の `comm` なので、これを呼ばないと
  overlay の context 行が `python3` になる。

**stub の中から別のプロセスを起動しないこと**——`sleep` のような子を作ると、そちらが foreground
process として答えられてしまう。

`bin/wayhint-shown` だけは子を 1 つ起動する: リポジトリの `.venv/bin/wayhint context --shown` を固定の
argv・shell 無しで呼び、**本物の出力**を `$ wayhint context --shown` の行の下に出す(字幕が
`wayhint context` を語る場面に、その出力を映すため)。子が終わって出力を書き終えてから `comm` を
`wayhint-shown` に変えるので、脚本は `wait_for: {context: {process_name: wayhint-shown}}` で
「出力が画面にある」ことを待てる。`--shown` は調べ直さないので、端末の窓に focus が移っても
ヒント画面を開いたときの中身を答える。行は 620 px の窓に合わせて空白で折り返す。この窓に
focus があるまま `Super+H` を押すと別のウィンドウの hotkey として一覧が差し替わるので、閉じる前に
`close: {window: shown}` で元のウィンドウへ戻す。

`bin/setup-dry-run` も同じ作りで、`./scripts/setup-terminals` を**引数無し**(dry run。何も書かない)で
session の使い捨て `$HOME` に対して実行し、本物の出力を出す。画面では `$HOME` を `~` にする(session の
home は録画ごとに名前が変わる runtime ディレクトリで、人が自分のパスを読む形でもない)。dry run は
やることが残っていれば exit 1 なので、1 までは成功として扱い、2 以上なら rename せずに止める。

`bin/herdr-launch` はコマンドを実行しない。`docs/TERMINALS.md` の `### Herdr` の下にある `sh` の
ブロック(kitty / Ghostty / foot の起動例)を起動時に読んで出す。動画と文書が別のことを言わないため
で、ブロックが見つからなければ rename せずに止める。

`bin/foot-wayhint` は README「Terminal の複数窓」の wrapper(app_id に自分の pid を入れる)、
`bin/foot-herdr` は Herdr 用(app_id に `herdr` を含める。`docs/TERMINALS.md` の前提)。どちらも
`fixtures/foot.ini` を読む。

**どちらの wrapper も引数を素通ししない。** 受け取るのは `--app-id=` と `--title=` だけで、
`foot-wayhint` はさらに `-e <stub>` を要求する(stub は隣にある `claude` `codex` `vi` `less`
`wayhint-shown` `setup-dry-run` `herdr-launch` のいずれかで、symlink は拒否)。stub に渡せる引数は **`WAYHINT_DEMO_CONFIG` の中のファイル 1 つ**だけ。`"$@"` をそのまま foot に渡すと、scenario 側から `--override=shell=…` で pane に
shell を入れられる——scenario は data であって code ではない(DECISIONS 0032 の脅威モデル)。
`foot-herdr` が起動する Herdr の絶対パスは環境変数 `WAYHINT_DEMO_HERDR_BIN` で渡す。未設定なら
wrapper は起動せず exit 1 する(裸の `herdr` に落とすと、PATH 先頭の `demo/bin` を見に行く)。

## 台本と脚本のずれを見る

台本(`01_*_storyboard.md`)と脚本(`02_*_scenario.yaml`)は**別々に人が書く**。台本から脚本を
生成はしない——台本は訴求を決める場所で、生成物にすると YAML の別記法になってしまう。代わりに
`--validate` が、台本のうち**脚本についての主張になっている部分**だけを突き合わせる
(`tools/demo/storyboard.py`)。

| 見るもの | 落ちる条件 |
|---|---|
| 表の字幕 | 脚本にその字幕の step が無い / 脚本の字幕が台本のどこにも無い |
| 表の秒 | 字幕を持つ step の区間が、その行の秒の外に出た |
| 節見出しの `(m:ss–m:ss)` | その節の表の最初と最後の秒と合わない |
| `合計 N 秒` | variant の実尺と 1 秒以上ずれた |

どの variant の話かは、`##` 見出しの直後の `<!-- variant: 60s -->` で示す(人が自由に書く見出しから
推測はできない)。表を持たない節、`### 環境` のような説明の節は無視される。

**警告**も出る(落ちはしない): `wait_for` が「overlay が出ている」しか見ていない step、前の step と
同じ条件しか持たない step。B-7 で `f` / `J` / `K` が overlay に届かず端末に流れていた 3 step は、
まさにこれを素通りして 3 本とも撮り切ってしまった。`pause:` は画面を変えないのが仕事なので対象外で、
同じ理由の step には `wait_for` に `unchecked: "<理由>"` を書く(理由を書くことが条件。端末に文字が
出るだけの step のように、daemon に聞ける形で何も残らないものがある)。

`./scripts/check` の test が実際の showcase について同じ検査を通すので、ずれたまま commit すると
落ちる。

## 字幕の書き方

4 本の showcase で同じ規約に従う。文言そのものは脚本の `caption` が正で、台本の表はその写し(9)。

1. 1 枚 20 文字前後、2 行まで。動作が起きる**直前**に出し、動作中は消さない
2. 末尾に句点を置かない。文中の区切りは「。」「、」どちらも可
3. 製品用語は日本語で書く: `hint` → ヒント、`sheet` → シート、`pane` → ペイン、`focus` → フォーカス、
   `editor` → エディタ、`overlay` → ヒント画面、窓 → ウィンドウ(2026-09-24 に英字から変更、ヒント画面以下は
   README と揃えて追加)。`hotkey` `context` は英字のまま。コマンド名・引数・YAML の key は変えない
4. キー・コマンド・ファイル名・YAML の key は前後に半角空白を空ける(「Enter で保存」
   「match に名前を書く」)。**字幕の中に backtick は書かない**——焼き込みは 1 書体なので記号が
   そのまま画面に出る。等幅で書くのは台本の地の文と、この README の側だけ
5. 「窓」は字幕では使わない。focus 中の toplevel は「ウィンドウ」、器と中身の対比も
   「ウィンドウ」と「一番前のプロセス」。「窓」は台本の `画面` 列(内部記述)でだけ使ってよい
6. 親子は**プロセス(context)の関係**として書く。「親シート」「子シート」「親子シート」は使わない
   (実装用語。`dev-docs/DESIGN.md` では `parent_context` の sheet の略として残っている)。
   例: 「親子関係にあるプロセスのヒントを同時に表示する」
7. 主役 3 場面の見出し字幕は次の 3 枚。他の showcase が同じ場面に触れるときも同じ文言を使う。
   英語版はこの 3 枚と締めの原則文から訳す
   - 見ているのはウィンドウではなく、一番前のプロセス
   - ヒント画面を出したまま、そのまま入力できる
   - 忘れていた操作を見つけたら、その場で書く
8. 見つけ方 3 本(`herdr` / `terminal` / `gui`)の締めは同じ 1 枚:
   Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる
9. 台本の表の秒と字幕は脚本と同期する。**同期を保つのは人**——字幕を変えるときは台本と
   `02_*_scenario.yaml` の `caption` を同じ commit で直す。ずれたまま commit すれば
   `--validate` と `./scripts/check` が落ちる(「台本と脚本のずれを見る」)が、落ちたものを
   直すのは人の側

字幕を 1 枚でも変えたら、その showcase は**撮り直し**になる(焼き込みは録画のあとの工程だが、
`.sub.mp4` も frame も作り直しになる)。

### 英語の字幕

上の規約は日本語の字幕のもの。英語の字幕(`caption.en`、`--lang en` で録る)は次に従う。

1. 短く平易に。なるべく 1 行(45 文字程度)、2 行まで。末尾に句点を置かず、backtick は書かない。
   コマンド・キー・ファイル名・YAML の key はそのまま
2. 製品用語: hint、sheet、the overlay、tab(Herdr のタブ)、window、terminal
3. 同じ日本語の字幕には、`all` も含めてどこでも同じ英語を当てる
4. 主役 3 場面の見出しと、見つけ方 3 本の締めは固定:「It follows the frontmost process, not the
   window」「Keep typing with the overlay on screen」「Forgot something? Write it down right
   there」「In Herdr, in a terminal or in a GUI app, the hints switch by themselves」
5. 英語の台本では、字幕の無い行を「(no caption)」と書く(日本語の台本は「(字幕なし)」)

## 字幕帯

字幕は録画のあとで ffmpeg が焼き込む(`tools/demo/encode.py`)。**帯の行はレイアウトから予約して
ある**——720p では

| | y |
|---|---|
| 帯の上端(`caption_band_top`) | **638** |
| 文字の上端(`caption_text_top`) | 652 |
| 帯の下端(1 行の実測) | 692 |
| 窓・overlay が使ってよい下端 | **634**(帯の 3px 上まで) |

窓は scenario の `windows` の `height` で、overlay は `fixtures/config.yaml` の `overlay.height` で
帯の上に収める。実測は窓の下端 624、overlay の下端 628 で、どちらも 10px 以上空いている。
**帯を不透明にして重なりを隠すのではなく、重ならないように置く**——半透明の帯の下にアプリの縁が
透けるのは、字幕が窓にかかっているのと同じに見える。

字幕は **1 行**であること。`drawtext` は折り返さないので、改行を書かない限り 1 行に収まる
(1 行の帯は 55px)。2 行にすると箱が下端を 6px ほど越えるので、そのときは `caption_text_top` を
上げ、あわせて overlay の高さも下げる必要がある。

## Herdr の隔離

showcase `herdr` は**実物の Herdr を動かす**(DECISIONS 0032)。使う binary は録画の開始時に
PATH から 1 回だけ解決し(このマシンでは `~/.local/bin/herdr`、0.8.2)、以降はその絶対パスで
呼ぶ——session の PATH は `demo/bin` が先頭なので、名前で呼び続けるとそこに置かれたものに
すり替わりうる。

録画のたびに session 専用の `XDG_CONFIG_HOME` へ最小の `config.toml` が書かれる
(`tools/demo/session.py` の `HERDR_CONFIG`)。効かせている設定と理由:

| 設定 | 理由 |
|---|---|
| `onboarding = false` | 初回のオンボーディング画面を出さない |
| `[theme] name = "catppuccin"` | 決めないと初回にテーマ選択を聞かれ、それが録画に写る |
| `[update] version_check = false` | herdr.dev への版チェックを止める(ネットワーク到達) |
| `[update] manifest_check = false` | herdr.dev からの agent-detection manifest の取得を止める。**ネットワーク到達を防ぐと同時に**、取得の有無で agent 判定が変わる非決定性も防ぐ。session の state は空なので同梱版が使われる |
| `[ui] prompt_new_tab_name = false` | `tab create` が名前を聞かずに済む(生成名 `1` `2` になる) |
| `[ui] window_title = "{workspace}"` | 既定は `"{hostname}: {workspace}"` で、**ホスト名が窓 title として全 frame に写る** |
| `[terminal] default_shell = <demo_bin>/idle` | pane に shell を置かない(下記) |

**session に shell は無い。** `default_shell` は `demo/bin/idle` で、これは 1 行出して stdin を
読み、行が `claude` `codex` `vi`(`idle` 内に静的に書いた list)ならそれに `exec` するだけ。`herdr pane run <pane> claude` がまさに
その 1 行になる。脚本は端末に文字を打つ(「キーボードを奪わない」場面)ので、shell が居ると
そこから何でも実行できてしまう。録画中に session 内の `comm` を数えて、`sh` / `bash` / `dash` が
1 つも無いことを確かめてある。

session の環境からは **`HERDR_*` をすべて落とす**。落とさないと、Herdr の pane から
`./scripts/demo` を実行したときに `HERDR_SOCKET_PATH` が継承され、session 内の herdr client が
**その人自身の Herdr server** に繋がる。

Herdr の server は daemon 化して session のプロセスグループを抜けるので、session を畳む**前**に
`herdr server stop` を呼ぶ。止まらなければ `/proc/*/environ` の `HOME` が session のものである
herdr だけを SIGTERM する(`pkill -f herdr` は実ユーザーの Herdr を巻き込むので使わない)。
