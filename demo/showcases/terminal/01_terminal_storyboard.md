# terminal — 端末の中を見る

- **主語**: multiplexer を使っていない端末のウィンドウと、その中で動いているプログラム
- **判定経路**: ウィンドウの app_id の `foot.p<pid>` → その pid の /proc → tty の前面プロセス
  (`setup-terminals` が端末をこの形で起動させる。字幕では「前準備」とだけ言う)

見つけ方 3 本の 2 本目。Herdr は起動しない(`session: {herdr: false}`)——それがこの showcase の
主張で、聞く相手がいなくても端末の中は見える。締めの 1 枚は 3 本で同じ文言。

---

## 0. 撮影前の準備

> `./scripts/demo --showcase terminal --record` で生成する。下の表の秒と字幕は生成物と同期して
> ある(`--validate` が見る)。

- 映すアプリ: foot のウィンドウ 2 枚。中身は `less` と `vi` の stub(どちらも sheet を開いて見せる)。
  ほかに、打ったコマンドの本物の出力を見せる端末の stub が 2 つ: §2 の `setup-dry-run`
  (`./scripts/setup-terminals` の dry run。何も書かない。HOME は `~` で出す)と、§5 の `wayhint-shown`
  (`wayhint context --shown`)
- §4 で足す端末のシートは `foot/ja/foot.yaml`。session の作業コピーに書くだけで、`demo/fixtures/` には無い
  (§1–§3 の一覧を変えないため)
- ウィンドウの配置は 2 枚が同時に見えるようにずらしてある。中身の違う 2 枚、が画で要る
- 字幕は使う人の言葉で書く。`/proc`・pid・`foot.p<pid>`・`chain` の中身など、wayhint の内部の見え方は
  字幕に出さない(画面に映るのは構わない)
- **映さない**: 実コード、ホームパスに含まれるユーザー名

## 1. 本編
<!-- variant: main -->

16:9。合計 85 秒。

### §1 端末でも(0:00–0:11)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 0–5 | foot の窓 1 枚。中で less が sheet を開いている | herdr などの multiplexer を使っていない端末でも |
| 5–11 | 同じ画面 | foot / kitty / Ghostty に対応 |

### §2 前準備(0:11–0:25)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 11–17 | 横長の端末の窓が開き、`$ ./scripts/setup-terminals` と dry run の出力(foot / kitty / Ghostty ごとに wrapper と `.desktop` を「作成します」) | 端末で使うには、前準備が 1 つ要る |
| 17–25 | 同じ画面。最終行の「書き込むには --apply を付けてください」。25 秒で窓を閉じる | 準備は scripts/setup-terminals 一発。既定は確認だけ |

### §3 使う(0:25–0:51)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 25–33 | `Super+H`。sub-header は `foot · less` | 端末の中で動いているプロセスのヒントが出る |
| 33–36 | 2 枚目の foot が開く。中は vi | (字幕なし) |
| 36–43 | 窓は 2 枚、overlay はまだ less の sheet | ウィンドウが 2 枚でも、それぞれの中身を取り違えない |
| 43–51 | `Super+H` → sheet が `Vi` に差し替わる | 別のウィンドウで押し直せば、その中のプロセス |

### §4 端末自体のヒント(0:51–1:08)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 51–52 | vi の窓を閉じる(session の作業コピーに `foot.yaml` を足してある) | (字幕なし) |
| 52–60 | vi の窓がもう一度開き、`foot.yaml`(コピー・貼り付け・検索の 3 件)が見えている | 端末自体のヒント（コピー・貼り付け）も書ける |
| 60–68 | `Super+H` → `Foot › Vi`。Foot の 3 件が vi の後に混ざって 8 件 | 中のプロセスのヒントと一緒に出る |

### §5 確かめ方と締め(1:08–1:25)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 68–77 | 端末の窓が開き、`wayhint context --shown` の出力(`chain=['ProcAdapter']`、`parent foot: 3/3 shown`) | 出ないときは wayhint context --shown で確かめる |
| 77–85 | 端末の窓を閉じ、`Super+H` で閉じる | Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる |

## 2. 字幕の書き方メモ

規約は `demo/README.md`「字幕の書き方」が正。この showcase が守るのはその 8 番——締めの 1 枚は
見つけ方 3 本で同じ文言:「Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる」。
主役 3 場面の見出し字幕（7 番）に触れるときも、`common` と同じ文言を使う。

## 3. 撮影後のチェック

- [ ] setup の出力のパスが `~/` で始まり、runtime ディレクトリの名前が映っていない
- [ ] sub-header が `less` → `vi` と変わっている
- [ ] `foot.yaml` を足した後の一覧が `Foot › Vi` で、Foot の 3 件が混ざっている
- [ ] `--shown` の出力に `chain=['ProcAdapter']` が見え、ホームパスが映っていない
- [ ] session に herdr / foot-herdr のプロセスが 1 つも無い
- [ ] 画面にユーザー名・実コード・ホームパスが映っていない
- [ ] 字幕帯(`demo/README.md`「字幕帯」の表の値)にウィンドウと overlay がかかっていない
