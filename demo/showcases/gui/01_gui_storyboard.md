# gui — GUI アプリのウィンドウを見る

- **主語**: 端末ではない GTK アプリのウィンドウ
- **判定経路**: ウィンドウの app_id を `match.wayland` に照合するだけ。中のプロセスは探さない

見つけ方 3 本の 3 本目で、いちばん短い。覗き込む foreground process が無い側を見せる
(DECISIONS 0024)。Herdr は起動しない。締めの 1 枚は 3 本で同じ文言。

---

## 0. 撮影前の準備

> `./scripts/demo --showcase gui --record` で生成する。下の表の秒と字幕は生成物と同期して
> ある(`--validate` が見る)。

- 映すアプリ: demo の GTK4 stub `notes`(`dev.wayhint.demo.Notes`)。**実アプリは使わない**——
  出力が毎回変わるうえ、ロゴや文言を借りることになる
- ウィンドウは端末を置かない画面いっぱい寄りの配置。この場面の主語はウィンドウそのもの
- **映さない**: 実アプリ、実データ

## 1. 本編
<!-- variant: main -->

16:9。合計 42 秒。

### §1 ウィンドウだけで決まる(0:00–0:42)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 0–5 | Notes の窓が開く | GUI アプリでも同じ |
| 5–13 | `Super+H` → `Notes` の sheet | ウィンドウの app_id だけで選ぶ。プロセスは探さない |
| 13–21 | sub-header に app_id だけが出ている | 覗き込むプロセスが無いので、sub-header は app_id |
| 21–28 | 同じ画面 | match.wayland に app_id を書くだけ |
| 28–35 | 同じ画面 | wayhint context の desktop_app と突き合わせる |
| 35–42 | `Super+H` で閉じる | 見つけ方は 3 通り。書き方は 1 つ、match に名前を書くだけ |

## 2. 字幕の書き方メモ

規約は `demo/README.md`「字幕の書き方」が正。この showcase が守るのはその 8 番——締めの 1 枚は
見つけ方 3 本で同じ文言:「見つけ方は 3 通り。書き方は 1 つ、match に名前を書くだけ」。
主役 3 場面の見出し字幕（7 番）に触れるときも、`common` と同じ文言を使う。

## 3. 撮影後のチェック

- [ ] sub-header にプロセス名が出ていない(app_id だけ)
- [ ] 一覧の末尾に wm の hint が付いている
- [ ] session に herdr / foot-herdr のプロセスが 1 つも無い
- [ ] 字幕帯(`demo/README.md`「字幕帯」の表の値)にウィンドウと overlay がかかっていない
