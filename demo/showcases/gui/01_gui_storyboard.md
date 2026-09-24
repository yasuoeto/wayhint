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
- 最後に `wayhint context --shown` を打った端末の stub(`wayhint-shown`。出力は本物)が開く
- Notes の窓は画面いっぱい寄りの配置(端末は最後の 1 枚だけ)。この場面の主語はウィンドウそのもの
- **映さない**: 実アプリ、実データ
- `notes.yaml` は demo 専用(実機の写しではない)。画面で読まれるので先頭にコメントを置かない。GUI アプリには
  端末の中のような前面プロセスが無く、ウィンドウの app_id だけで選ばれる(DECISIONS 0024)

## 1. 本編
<!-- variant: main -->

16:9。合計 47 秒。

### §1 ウィンドウだけで決まる(0:00–0:47)

| 秒 | 画面 | 字幕 |
|---|---|---|
| 0–5 | Notes の窓が開く | GUI アプリでも同じ |
| 5–13 | `Super+H` → `Notes` の sheet | アプリごとに、そのアプリのヒントが出る |
| 13–21 | sub-header に app_id だけが出ている | 上の行に、どのアプリのヒントかが出る |
| 21–30 | vi の窓が開き、`notes.yaml` の `match:` → `wayland:` → `app_id_regex` が見えている。30 秒で閉じる | シートの match に、アプリの名前（app_id）を書くだけ |
| 30–39 | 端末の窓が開き、`wayhint context --shown` の出力(`desktop_app=dev.wayhint.demo.Notes`、`process` も `chain` も無い) | 出ないときは wayhint context --shown で確かめる |
| 39–47 | 端末の窓を閉じ、`Super+H` で閉じる | Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる |

## 2. 字幕の書き方メモ

規約は `demo/README.md`「字幕の書き方」が正。この showcase が守るのはその 8 番——締めの 1 枚は
見つけ方 3 本で同じ文言:「Herdr の中・端末の中・GUI、どこで動いていても、ヒントは自動で切り替わる」。
主役 3 場面の見出し字幕（7 番）に触れるときも、`common` と同じ文言を使う。

## 3. 撮影後のチェック

- [ ] sub-header にプロセス名が出ていない(app_id だけ)
- [ ] `--shown` の出力の `desktop_app` が sub-header の app_id と同じで、`chain` が出ていない
- [ ] 一覧の末尾に wm の hint が付いている
- [ ] session に herdr / foot-herdr のプロセスが 1 つも無い
- [ ] 字幕帯(`demo/README.md`「字幕帯」の表の値)にウィンドウと overlay がかかっていない
