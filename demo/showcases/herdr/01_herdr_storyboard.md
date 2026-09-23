# herdr — Herdr の中を見る

- **主語**: Herdr の窓と、その中の pane で動いているコマンド
- **判定経路**: 窓の app_id に `herdr` → Herdr に focused pane を聞く → その pane の前面プロセス

見つけ方 3 本の 1 本目。何ができるか（一覧の形、奪わないこと、追記）は `common` が扱うので、
ここでは**どのプロセスの hint が出ているのか**だけを追う。締めの 1 枚は 3 本で同じ文言。

---

## 0. 撮影前の準備

> `./scripts/demo --showcase herdr --record` で生成する。session は Herdr あり
> (`session: {herdr: true}`)。下の表の秒と字幕は生成物と同期してある(`--validate` が見る)。

- 映すアプリ: Herdr + Claude Code / Codex の stub、`idle` の pane、vi の stub
- 親子 sheet は `herdr.yaml`(親、4 件のうち 3 件に `tags: [terminal]`)と
  `claude-code.yaml` / `codex.yaml`(子、`inherit.parent_tags: [terminal]`)
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
| 15–22 | 同じ画面 | 前提: 窓の app_id に herdr を含める |
| 22–29 | 一覧の後ろに Herdr の pane 操作が続いている | 後ろに続くのは親 sheet、Herdr の hint |
| 29–37 | 続いているのは `tags: [terminal]` の 3 件だけ | 子の inherit.parent_tags で親の hint を絞る |

### §2 pane を移る(0:37–1:00)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 37–42 | 新しいタブ → Codex | (字幕なし) |
| 42–50 | `Super+H` → `Herdr › Codex` に差し替わる | pane を移って押し直せば、その pane の sheet |
| 50–52 | 新しいタブ。pane は idle のまま | (字幕なし) |
| 52–60 | `Super+H` → Herdr 自身の sheet(4 件 + wm) | 当たる sheet が無ければ、Herdr の hint が全部出る |

### §3 書き方と切り分け(1:00–1:30)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 60–65 | overlay を閉じ、vi で `hints/ja/claude-code.yaml` を開く | (字幕なし) |
| 65–73 | 8–9 行目の `inherit:` | inherit.parent_tags — 親から混ぜるタグ |
| 73–75 | vi の窓を閉じる | (字幕なし) |
| 75–83 | Herdr の窓だけ | wayhint context の chain と process で切り分ける |
| 83–90 | 同じ画面 | 見つけ方は 3 通り。書き方は 1 つ、match に名前を書くだけ |

## 2. 撮影後のチェック

- [ ] `Herdr › Claude Code` → `Herdr › Codex` → Herdr のみ、の 3 状態が出ている
- [ ] 親 sheet の hint が一覧の**後ろ**に続いている(先頭に来ていない)
- [ ] 画面にユーザー名・実コード・会話内容が映っていない
- [ ] 字幕帯(y=638 から下)に窓と overlay がかかっていない
