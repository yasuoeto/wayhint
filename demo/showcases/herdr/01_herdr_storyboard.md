# herdr — Herdr の中を見る

- **主語**: Herdr のウィンドウと、その中の pane で動いているコマンド
- **判定経路**: ウィンドウの app_id に `herdr` → Herdr に focused pane を聞く → その pane の前面プロセス

見つけ方 3 本の 1 本目。何ができるか（一覧の形、奪わないこと、追記）は `common` が扱うので、
ここでは**どのプロセスの hint が出ているのか**だけを追う。締めの 1 枚は 3 本で同じ文言。

---

## 0. 撮影前の準備

> `./scripts/demo --showcase herdr --record` で生成する。session は Herdr あり
> (`session: {herdr: true}`)。下の表の秒と字幕は生成物と同期してある(`--validate` が見る)。

- 映すアプリ: Herdr + Claude Code / Codex の stub、`idle` の pane、vi の stub、
  `wayhint context --shown` を打った端末の stub(`wayhint-shown`。出力は本物)
- §1 の前準備は stub `herdr-launch` が `docs/TERMINALS.md` の Herdr の起動例をその場で読んで出す
  (動画と文書が別のことを言わないため)
- 字幕は使う人の言葉で書く。Herdr の中の単位は、見る人に見えている「タブ」と言う
- 混ざる sheet は 2 段: Herdr のウィンドウが `herdr.yaml`(6 件)、その pane のコマンドが
  `claude-code.yaml`(7 件)/ `codex.yaml`(1 件)。どこにも tag の絞りを書いていないので、親の
  Herdr の hint は全部混ざる(DECISIONS 0034)。3 枚とも実機の `~/.config/wayhint/hints/ja/` の写し
  (2026-09-24)
- §3 で絞るときは `herdr.yaml` を `narrowed/ja/herdr.yaml`(写しに `nested.export_categories` の 2 行を
  足したもの)で置き換える。作業コピーを書き換えるだけで、`demo/fixtures/` は変わらない
- **映さない**: 実コード、会話内容、ホームパスに含まれるユーザー名

## 1. 本編
<!-- variant: main -->

16:9。合計 105 秒。

### §1 前準備と、中で動いているものを選ぶ(0:00–0:39)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 0–4 | Herdr の窓。pane は idle | Herdr の中を見る |
| 4–13 | 横長の端末の窓に `docs/TERMINALS.md` の起動例 3 行(kitty / Ghostty / foot を herdr の名前付きで開く)。13 秒で閉じる | 前準備: Herdr は、名前に herdr を付けた端末で開く |
| 13–16 | pane で Claude Code が立ち上がる | (字幕なし) |
| 16–24 | `Super+H`。ヘッダーは `Herdr › Claude Code` | Herdr にフォーカス中のタブを聞き、動いているプロセスを取る |
| 24–31 | 一覧に Herdr の `PgUp/PgDn` と中クリックペーストが混ざっている | 親子関係にあるプロセスのヒントを同時に表示する、親である Herdr の操作も並ぶ |
| 31–39 | Herdr の 6 件が全部入って 15 件(収まらない分はスクロールバーで分かる) | 何も書かなければ、親に当たる Herdr のヒントが全て一緒に表示される |

### §2 タブを移る(0:39–1:03)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 39–45 | 新しいタブ → Codex。overlay は `Herdr › Claude Code` のまま | ヒント画面は、押し直すまで前のタブのまま |
| 45–53 | `Super+H` → `Herdr › Codex` に差し替わる | タブを移って押し直せば、そのタブのシート |
| 53–55 | 新しいタブ。pane は idle のまま | (字幕なし) |
| 55–63 | `Super+H` → Herdr 自身の sheet(6 件 + wm) | 動いているプロセスに対応したシートが無ければ、Herdr のヒントが全部出る |

### §3 絞り方と確かめ方(1:03–1:45)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 63–68 | overlay を閉じ、`herdr.yaml` に `nested.export_categories: [scroll, input]` を足して vi で開く | (字幕なし) |
| 68–76 | vi の上の方に `nested:` の 2 行が見えている | 表示内容を絞り込みたい場合は、設定を書く |
| 76–80 | vi の窓を閉じ、Claude Code のタブへ戻る | (字幕なし) |
| 80–88 | `Super+H` → `Herdr › Claude Code` が 12 件。Herdr の分は PgUp/PgDn と貼り付けの 3 件 | Herdr のヒントは scroll と input だけになる |
| 88–97 | 端末の窓が開き、`wayhint context --shown` の出力(`parent herdr: 3/6 shown`、`categories: scroll, input -- nested.export_categories (herdr.yaml)`) | wayhint context --shown で、どこで絞ったかが分かる |
| 97–105 | 端末の窓を閉じ、`Super+H` で閉じる | Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる |

## 2. 字幕の書き方メモ

規約は `demo/README.md`「字幕の書き方」が正。この showcase が守るのはその 8 番——締めの 1 枚は
見つけ方 3 本で同じ文言:「Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる」。
主役 3 場面の見出し字幕（7 番）に触れるときも、`common` と同じ文言を使う。

## 3. 撮影後のチェック

- [ ] `Herdr › Claude Code` → `Herdr › Codex` → Herdr のみ → 絞った `Herdr › Claude Code`、の 4 状態が出ている
- [ ] 絞った一覧に `Cycle theme` と tab の 2 件が無い。`--shown` の出力が一覧と同じ件数(3/6)を言っている
- [ ] Herdr 側の hint が一覧に混ざっている(同じ category の hint は隣に並ぶので、scroll の 1 件は
  Claude の scroll の直後に来る)
- [ ] 画面にユーザー名・実コード・会話内容が映っていない
- [ ] 字幕帯(`demo/README.md`「字幕帯」の表の値)にウィンドウと overlay がかかっていない
