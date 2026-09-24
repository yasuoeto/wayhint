# terminal — 端末の中を見る

- **主語**: multiplexer を使っていない端末のウィンドウと、その中で動いているプログラム
- **判定経路**: ウィンドウの app_id の `foot.p<pid>` → その pid の /proc → tty の前面プロセス

見つけ方 3 本の 2 本目。Herdr は起動しない(`session: {herdr: false}`)——それがこの showcase の
主張で、聞く相手がいなくても端末の中は見える。締めの 1 枚は 3 本で同じ文言。

---

## 0. 撮影前の準備

> `./scripts/demo --showcase terminal --record` で生成する。下の表の秒と字幕は生成物と同期して
> ある(`--validate` が見る)。

- 映すアプリ: foot のウィンドウ 2 枚。中身は `less` と `vi` の stub(どちらも sheet を開いて見せる)。
  §3 で `wayhint context --shown` を打った端末の stub(`wayhint-shown`。出力は本物)が 3 枚目に開く
- §3 で足す端末のシートは `foot/ja/foot.yaml`。session の作業コピーに書くだけで、`demo/fixtures/` には無い
  (§1・§2 の一覧を変えないため)
- ウィンドウの配置は 2 枚が同時に見えるようにずらしてある。pid の違う 2 枚、が画で要る
- **映さない**: 実コード、ホームパスに含まれるユーザー名

## 1. 本編
<!-- variant: main -->

16:9。合計 92 秒。

### §1 端末 1 枚(0:00–0:33)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 0–5 | foot の窓 1 枚。中で less が sheet を開いている | multiplexer を使っていない端末でも |
| 5–11 | 同じ画面 | foot / kitty / Ghostty に対応 |
| 11–19 | `Super+H`。sub-header は `foot · less` | /proc を辿り、tty の前面にいるプロセスを取る |
| 19–26 | 同じ画面 | 端末は foot.p<pid> の app_id で起動している |
| 26–33 | 同じ画面 | 配線は scripts/setup-terminals。既定は dry run |

### §2 端末 2 枚(0:33–0:58)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 33–36 | 2 枚目の foot が開く。中は vi | (字幕なし) |
| 36–43 | 窓は 2 枚、overlay はまだ less の sheet | ウィンドウが 2 枚でも、pid で取り違えない |
| 43–51 | `Super+H` → sheet が `Vi` に差し替わる | 別のウィンドウで押し直せば、その中のプロセス |
| 51–58 | 同じ画面 | 端末そのもののシートは要らない |

### §3 端末のシートと切り分け(0:58–1:32)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 58–59 | vi の窓を閉じる(session の作業コピーに `foot.yaml` を足してある) | (字幕なし) |
| 59–67 | vi の窓がもう一度開き、`foot.yaml` の `app_id_regex: ["^foot$"]` が見えている | 端末のシートを書くなら ^foot$ のまま |
| 67–75 | `Super+H` → `Foot › Vi`。Foot の 3 件が vi の後に混ざって 8 件 | foot.p<pid> のウィンドウにも当たり、ヒントが混ざる |
| 75–84 | 端末の窓が開き、`wayhint context --shown` の出力(`chain=['ProcAdapter']`、`parent foot: 3/3 shown`) | chain に ProcAdapter があれば、端末の中を見ている |
| 84–92 | 端末の窓を閉じ、`Super+H` で閉じる | 見つけ方は 3 通り。書き方は 1 つ、match に名前を書くだけ |

## 2. 字幕の書き方メモ

規約は `demo/README.md`「字幕の書き方」が正。この showcase が守るのはその 8 番——締めの 1 枚は
見つけ方 3 本で同じ文言:「見つけ方は 3 通り。書き方は 1 つ、match に名前を書くだけ」。
主役 3 場面の見出し字幕（7 番）に触れるときも、`common` と同じ文言を使う。

## 3. 撮影後のチェック

- [ ] sub-header が `less` → `vi` と変わっている
- [ ] `foot.yaml` を足した後の一覧が `Foot › Vi` で、Foot の 3 件が混ざっている
- [ ] `--shown` の出力に `chain=['ProcAdapter']` が見え、ホームパスが映っていない
- [ ] session に herdr / foot-herdr のプロセスが 1 つも無い
- [ ] 画面にユーザー名・実コード・ホームパスが映っていない
- [ ] 字幕帯(`demo/README.md`「字幕帯」の表の値)にウィンドウと overlay がかかっていない
