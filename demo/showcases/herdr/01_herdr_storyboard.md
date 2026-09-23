# herdr — Herdr の中を見る

- **主語**: Herdr のウィンドウと、その中の pane で動いているコマンド
- **判定経路**: ウィンドウの app_id に `herdr` → Herdr に focused pane を聞く → その pane の前面プロセス

見つけ方 3 本の 1 本目。何ができるか（一覧の形、奪わないこと、追記）は `common` が扱うので、
ここでは**どのプロセスの hint が出ているのか**だけを追う。締めの 1 枚は 3 本で同じ文言。

---

## 0. 撮影前の準備

> `./scripts/demo --showcase herdr --record` で生成する。session は Herdr あり
> (`session: {herdr: true}`)。下の表の秒と字幕は生成物と同期してある(`--validate` が見る)。

- 映すアプリ: Herdr + Claude Code / Codex の stub、`idle` の pane、vi の stub
- 混ざる sheet は 2 段: Herdr のウィンドウが `herdr.yaml`(6 件)、その pane のコマンドが
  `claude-code.yaml`(7 件)/ `codex.yaml`(1 件)。どこにも tag の絞りを書いていないので、親の
  Herdr の hint は全部混ざる(DECISIONS 0034)。3 枚とも実機の `~/.config/wayhint/hints/ja/` の写し
  (2026-09-24)
- **映さない**: 実コード、会話内容、ホームパスに含まれるユーザー名

## 1. 本編
<!-- variant: main -->

16:9。合計 90 秒。

### §1 中で動いているものを選ぶ(0:00–0:37)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 0–4 | Herdr の窓。pane は idle | Herdr の中を見る |
| 4–7 | pane で Claude Code が立ち上がる | (字幕なし) |
| 7–15 | `Super+H`。ヘッダーは `Herdr › Claude Code` | Herdr に focused pane を聞き、前面プロセスを取る |
| 15–22 | 同じ画面 | 前提: ウィンドウの app_id に herdr を含める |
| 22–29 | 一覧に Herdr の `PgUp/PgDn` と中クリックペーストが混ざっている | 親子関係のプロセスは自動で hint を混ぜる、Herdr の操作も並ぶ |
| 29–37 | Herdr の 6 件が全部入って 15 件(収まらない分はスクロールバーで分かる) | 何も書かなければ、親の hint は全部混ざる |

### §2 pane を移る(0:37–1:00)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 37–42 | 新しいタブ → Codex | (字幕なし) |
| 42–50 | `Super+H` → `Herdr › Codex` に差し替わる | pane を移って押し直せば、その pane の sheet |
| 50–52 | 新しいタブ。pane は idle のまま | (字幕なし) |
| 52–60 | `Super+H` → Herdr 自身の sheet(6 件 + wm) | 当たる sheet が無ければ、Herdr の hint が全部出る |

### §3 書き方と切り分け(1:00–1:30)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 60–65 | overlay を閉じ、vi で `hints/ja/herdr.yaml` を開く | (字幕なし) |
| 65–73 | 同じ画面(`nested:` は書いていない) | 絞るなら、親の sheet に nested.export_tags を書く |
| 73–75 | vi の窓を閉じる | (字幕なし) |
| 75–83 | Herdr の窓だけ | wayhint context の chain と process で切り分ける |
| 83–90 | 同じ画面 | 見つけ方は 3 通り。書き方は 1 つ、match に名前を書くだけ |

## 2. 字幕の書き方メモ

規約は `demo/README.md`「字幕の書き方」が正。この showcase が守るのはその 8 番——締めの 1 枚は
見つけ方 3 本で同じ文言:「見つけ方は 3 通り。書き方は 1 つ、match に名前を書くだけ」。
主役 3 場面の見出し字幕（7 番）に触れるときも、`common` と同じ文言を使う。

## 3. 撮影後のチェック

- [ ] `Herdr › Claude Code` → `Herdr › Codex` → Herdr のみ、の 3 状態が出ている
- [ ] Herdr 側の hint が一覧に混ざっている(同じ category の hint は隣に並ぶので、scroll の 1 件は
  Claude の scroll の直後に来る)
- [ ] 画面にユーザー名・実コード・会話内容が映っていない
- [ ] 字幕帯(`demo/README.md`「字幕帯」の表の値)にウィンドウと overlay がかかっていない
