# wayhint

Wayland(wlroots 系 compositor: labwc / Wayfire など)上で hotkey 一発、いつも同じ場所
(既定: 画面右上)に、いま使っているアプリに応じたチートシートを overlay 表示する。Herdr の中で
使っているときは、focused pane の foreground process(Claude Code / Codex …)まで見て切り替える。
中身は YAML で自分で書いて育てる。

- 通常表示中は keyboard focus を奪わない(検索を明示的に開始したときだけ入力を受ける)
- hint は `~/.config/wayhint/hints/<言語>/*.yaml`(日本語なら `hints/ja/`)。overlay の編集ボタンから外部 editor で該当行を開く
- YAML 内の command は表示・copy のみ。実行はしない

要件は `docs/PRODUCT.md`、構造は `docs/DESIGN.md`、経緯は `docs/DECISIONS.md`、進捗は `STATUS.md`。

## インストール

依存: Python 3.11+、GTK4 + PyGObject、gtk4-layer-shell(typelib 込み)、`wlr-foreign-toplevel-management` と `wlr-layer-shell` を
提供する Wayland compositor(labwc、Wayfire は `foreign-toplevel` plugin 有効時)、任意で Herdr と gvim。Debian/sid の場合:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0
```

```sh
git clone <this repo> ~/work/tools/wayhint && cd ~/work/tools/wayhint
./scripts/setup                 # .venv(system site-packages 共有)+ ruamel.yaml + pywayland(+ PyWayfire)
.venv/bin/pip install -e .      # wayhint / wayhintd コマンドを .venv/bin に置く
./scripts/check                 # lint + 単体テスト
```

## 設定ファイルの場所

`$XDG_CONFIG_HOME/wayhint/`(既定 `~/.config/wayhint/`):

| パス | 内容 |
|---|---|
| `config.yaml` | overlay 位置・サイズ、editor、parent tags 等。無ければ全て既定値 |
| UI 言語 | ボタン等の文字はマシンの locale(`LC_ALL` → `LC_MESSAGES` → `LANG`)から自動選択。`appearance.language: en\|ja` で固定。日英以外は英語 |
| `style.css` | 任意。GTK CSS で見た目を上書き(class 名は `src/wayhint/ui/style.py`)。雛形 `examples/style.css` は labwc のテーマ(Syscrash)に合わせた配色 |
| `hints/<言語>/*.yaml` | sheet 1 ファイル 1 枚。ファイル名順に読む。**`id` はファイル名（拡張子を除く部分）と同じにする**。違うものは読み込まず ⚠ に理由が出る(バックアップの `claude-backup.yaml` が `claude` を名乗っても二重に効かない)。言語ディレクトリについては下の「言語ごとの hint」 |

雛形は `examples/`。`cp -r examples/. ~/.config/wayhint/` で始められる
(`style.css` も入る。アプリ既定の配色で使うなら消す)。schema は
`docs/DESIGN.md` の Data model。書いたら `wayhint validate` で確認する(問題があれば exit 1)。

## compositor の設定

active window と output は Wayland 標準の `wlr-foreign-toplevel-management` protocol で取る
(`context.backend: auto`、既定)。labwc はそのまま動く。Wayfire は `[core] plugins` に
`foreign-toplevel` があればよい。この protocol が無く `$WAYFIRE_SOCKET` がある環境では Wayfire IPC
(`ipc` `ipc-rules` plugin、PyWayfire)へ自動 fallback する。`context.backend: wayland|wayfire` で固定も可。

daemon はセッションに 1 つ起動し、hotkey は compositor の keybinding から CLI を叩く。

### labwc(`~/.config/labwc/rc.xml`)

```xml
<keyboard>
  <keybind key="W-h">
    <action name="Execute" command="/home/USER/work/tools/wayhint/.venv/bin/wayhint toggle"/>
  </keybind>
  <keybind key="W-C-h">
    <action name="Execute" command="/home/USER/work/tools/wayhint/.venv/bin/wayhint edit-mode"/>
  </keybind>
</keyboard>
```

autostart は `~/.config/labwc/autostart` に 1 行(実行属性を付ける):

```sh
/home/USER/work/tools/wayhint/.venv/bin/wayhintd &
```

IME のための環境変数は要らない。overlay は layer-shell surface でも Wayland ネイティブの
text-input-v3 で入力メソッドに繋がる(効かないときは「困ったとき」参照)。

autostart が起動した helper の PID を記録して終了時に落とす仕組みを持っているなら、その作法に
従う(例: `spawn wayhintd`)。systemd の user unit は用意しない。理由は `docs/DECISIONS.md` 0011。

反映は `labwc --reconfigure`。

### Wayfire(`~/.config/wayfire.ini`)

```ini
[command]
binding_wayhint = <super> KEY_H
command_wayhint = /home/USER/work/tools/wayhint/.venv/bin/wayhint toggle
binding_wayhint_edit = <super> <ctrl> KEY_H
command_wayhint_edit = /home/USER/work/tools/wayhint/.venv/bin/wayhint edit-mode

[autostart]
wayhint = /home/USER/work/tools/wayhint/.venv/bin/wayhintd
```

手動で試すときは `wayhintd -v`(前景、info ログ。選ばれた backend が `desktop backend:` で出る)。
`wayhint ping` で応答を確認する。

## Terminal の複数窓

端末の窓が 2 枚以上あるとき、wayhint は**どの窓が前面か**を知る必要がある。ところが Wayland の
protocol にも labwc にも「この窓を描いているのはどのプロセスか」を答える口が無い。そこで
**窓の側が app_id で名乗る**規約にしている ―― app_id の末尾が `.p<pid>` なら、wayhint はその
数字を端末プロセスの PID として使う。

```sh
#!/bin/sh
# ~/.local/bin/foot-wayhint
exec /usr/bin/foot --app-id "foot.p$$" "$@"
```

この wrapper を作り、**端末を起動している経路すべて**(compositor の keybind、bar の
ショートカット、ルートメニュー、`.desktop`)をそこに向ける。接尾辞は wayhint が外してから扱う
ので、sheet の `app_id_regex` は `["^foot$"]` のままでよい。

対応端末は foot / kitty / Ghostty(それぞれ条件あり)と Herdr(**窓の app_id に `herdr` を
含めること**。`foot --app-id=foot-herdr` のような起動が前提)。WezTerm は窓ごとに
app_id を変えられないため対象外。wrapper を通さない窓でも、その端末のプロセスが 1 つだけなら
従来どおり解決する。


bar や compositor の設定だけは表示するだけで書き換えない(手で保守しているファイルのため)。
**端末ごとの条件、launcher の配線、効いているかの確認方法は
[`docs/TERMINALS.md`](docs/TERMINALS.md)。**

## overlay の使い方

hotkey は「いま見ているものの hint」を意味する。押すと表示し、同じ hint が出ている状態でもう一度
押すと閉じる。別の window に移ってから押した場合は閉じずに、その window の hint に差し替わる。
通常表示中は keyboard focus を奪わないので、overlay を出したまま元のアプリで作業を続けられる。その代わり通常表示中はキー入力が overlay に届かないので、
閉じるのは hotkey か **閉じる** ボタン。`Esc` が効くのは検索中だけ。

一覧は 1 行が 1 hint で、左に `key`、中央に title と `command`、右に `category` が出る。
`favorite: true` の hint は `★` 付きで先頭に集まる。行を選ぶと下に詳細が開き、`remark`、タグ、
出典、習得日が出る(行に出ているものは繰り返さない。どれも書いていない hint では詳細は開かない)。
`id` と `kind` は YAML を書く側のもので、overlay には出ない。

| ボタン | 動作 |
|---|---|
| 検索 | 検索欄を開く。もう一度押すか `Esc` で終了。編集中は無効なので、編集を終了してから検索する |
| コピー | 選択中の hint を clipboard へ。`copy` → `command` → `key` の順に、最初にある値 |
| エディタで編集 | 選択中の hint が属する sheet を editor で開き、その hint の行へ jump する(無選択なら表示中の sheet を先頭から)。sheet 全体を見直すとき用。overlay は出たままなので、editor で保存するたびに一覧が更新される(検索中・編集モード中に押すとそれらは終了する。keyboard を editor に渡すため。下書きは残り、次に編集モードへ入ると戻る) |
| 編集 | 編集モードに入る。hint の追加・修正・削除・並べ替えを overlay の中で行う(キー割当は `docs/DESIGN.md` の「編集モード」。`wayhint edit-mode` でも入れる)。**フォームを保存すると編集モードは終わり**、keyboard が元のアプリに戻る(favorite・並べ替え・削除・取消は編集モードのまま続けられる) |
| 閉じる | overlay を隠す |

検索は空白区切りの語をすべて含む hint に絞る。大文字小文字は区別しない。対象は title、`key`、
`command`、`category`、タグ、`remark`。件数の上限は `search.max_results`(既定 50)。
検索を終えると keyboard focus は元の window に戻る。

表示される context は **開いた瞬間に固定** される。別のアプリに移っても自動では追従しない。
切り替えたいときは移った先の window で **hotkey をもう一度押す**(閉じずに中身が差し替わる)。
マウスしか使えない場面では `wayhint refresh`(表示中なら context を取り直す)でも同じことができる。

大きさは anchor の反対側(既定の `top-right` なら**左下**)にある **grip** を掴んで変えられる。
角は縦横いっしょに、左辺・下辺の帯(6px、hover で色が付く)は幅だけ・高さだけを変える。離した時点の幅と高さが
`config.yaml` の `overlay.width` / `height` に px で書き戻るので、次に開いたときも daemon を
再起動したあとも同じ大きさで出る。`height: 60%` のように % で書いていた場合は px に置き換わる。
元に戻したいときは `config.yaml` を手で直す(保存すれば自動で反映される)。

overlay は **呼び出した workspace でだけ** 表示される。別の workspace に切り替えると隠れ、
戻ってくると同じ内容で出直す。閉じるまでその workspace に居続けるので、workspace ごとに別の
sheet を開いたままにできる。消えるのは **閉じる** か hotkey で明示的に閉じたときだけ。

全 workspace に出したままにするには `config.yaml` に `context: {workspace: all}` を書く。
この機能は compositor が `ext-workspace-v1` を出す場合だけ働く。labwc は対応、Wayfire は未対応で、
その場合は設定に関わらず全 workspace に表示される。

## CLI

`wayhint <command>` は daemon に Unix domain socket 経由で 1 行送るだけで、GUI を持たない。
hotkey に割り当てるのは `toggle`。

| コマンド | 動作 |
|---|---|
| `toggle` | 表示、表示中なら非表示 |
| `show` / `hide` | 明示的に表示 / 非表示 |
| `refresh` | 表示中なら context を取り直す |
| `reload` | `config.yaml` と使用中の `hints/<言語>/*.yaml` を読み直す |
| `ping` | daemon の生死確認。pid と読み込み済み sheet 数を返す |
| `validate` | YAML を検証する。daemon を必要としない唯一の command。問題があれば exit 1 |
| `context` | daemon が今どう context を解決するかを表示する(下の例) |
| `edit-mode` | 編集モードに入る(表示中でなければ表示してから)。編集モード中に呼ぶと抜ける |
| `add TITLE` | hint の追加 |
| `edit ID` | hint の編集 |
| `remove ID` | hint の削除 |
| `favorite ID [--off]` | hint の favorite |
| `move ID up\|down` | hint の並び替え |
| `format [PATH...]` | sheet を canonical 順・12 項目に正規化する。`--modeline` の path は `editor.schema_path` |
| `schema [--write PATH]` | hint sheet の JSON Schema を出力する。PATH 省略時は `editor.schema_path`、`--write` 無しは標準出力 |

`validate` は `--config-dir`、それ以外は `--socket` で既定の場所を上書きできる。
daemon 側は `wayhintd -v` で info ログを前景に出す。

`context` は「なぜこの sheet が出たのか」を確かめるためのもの。値の入っている項目だけを
`key=value` で並べる。foot 上で vi を動かしているときはこうなる:

```
$ wayhint context
active_sheet=vi desktop_app=foot.p12345 chain=['ProcAdapter'] \
  process={'name': 'vi', 'argv_basenames': ['vi', 'notes.txt']}
```

(実際は 1 行で出る。空の項目 — この例では `parent_context` や `include` — は省かれる)

`chain` は foreground process を探すのに使った adapter の並び。terminal 用の sheet を書いて
いなくても(`parent_context` が `null`)、その中で動いているコマンドの sheet が選ばれる。
`chain` が空なら adapter は 1 つも当たっていない(その app は terminal とみなされていない)、
`chain` はあるのに `process` が `null` なら adapter が答えを出せなかった(「Terminal の複数窓」の
規約に乗っていない窓が複数あるなど、確実に決められないときは黙る)。`desktop_app` の
`.p12345` は窓の識別子で、sheet の照合や overlay の表示には使われない。

hint を書き換える command は daemon を経由せず自分でファイルに書く。`--sheet ID` を省略すると
現在の context の sheet が対象になる。

```
wayhint add TITLE [--kind K] [--key S | --command S] [--category S] [--remark S] [--parent] [--sheet ID]
wayhint edit ID [--title S] [--kind K] [--key S | --command S] [--category S] [--remark S] [--sheet ID]
wayhint remove ID [--sheet ID]
wayhint favorite ID [--off] [--sheet ID]
wayhint move ID up|down [--sheet ID]
wayhint format [--modeline] [PATH...]        # PATH 省略時は使用中の hints/<言語>/*.yaml 全部
wayhint schema [--write PATH]
```

### daemon を再起動する

`reload` が読み直すのは `config.yaml` と使用中の `hints/<言語>/*.yaml` だけで、Python 側を変えたときは daemon を
入れ替える。頻度は低いので専用の script や panel 項目は用意しない。次の 1 行で止めて起動し直す:

```sh
cd ~/work/tools/wayhint && p=$(.venv/bin/wayhint ping | sed -n 's/^pid=\([0-9]*\).*/\1/p'); \
  [ -n "$p" ] && kill "$p" && while kill -0 "$p" 2>/dev/null; do sleep 0.1; done; \
  nohup .venv/bin/wayhintd -v >>"${XDG_RUNTIME_DIR:-/tmp}/wayhint.log" 2>&1 & disown
```

よく使うなら `~/.bashrc` に `alias wayhint-restart='…'` として置く。中身の意味:

- pid は `wayhint ping` から取る。`pkill -f wayhintd` は **この 1 行を実行しているシェル自身にも
  当たる**ので使わない。
- daemon が動いていないときは `wayhint: wayhintd is not running …` が 1 行出るが、そのまま起動する。
- 前の daemon が socket を片付けるのを待ってから起動する。生きている daemon がいる間に起動すると
  `wayhintd already running on …` で終了する(死んだあとの socket は新しい daemon が自分で消す)。
- ログは `$XDG_RUNTIME_DIR/wayhint.log` に追記する。ログアウトで消える。前景で見たいだけなら
  `.venv/bin/wayhintd -v` をそのまま端末で動かす。
- daemon は SIGTERM / SIGINT で socket を消して終了する。`kill -9` は socket を残すが、次の起動が
  stale として消すので実害は無い。

編集した hint を反映するだけなら再起動は要らない(保存で自動 reload、`wayhint reload` でも可)。

## hint を書く

1. `hints/<言語>/` に新しい YAML を置く(または既存の sheet に hint を足す)。
2. daemon は保存を検知して自動 reload する(overlay を閉じる必要はない)。壊れた YAML のときは
   直前の正常版を表示し続け、overlay 上部に `⚠ YAML error file:line: message` が出る。
3. 追加・修正・削除は overlay の **編集**(編集モード)で完結する。`a` での追加先は**選択中の hint と同じ sheet**(親 sheet の hint を選んでいれば親 sheet)。フォームの見出しに追加先が出る。フォームを保存すると編集モードは
   終わり、keyboard が元のアプリに戻る(1 件書いて作業に戻る流れのため)。favorite・並べ替え・削除・
   取消はまとめて行う操作なので編集モードのまま続く。sheet 全体を見直すときは **エディタで編集** で
   editor が該当ファイル・該当行を開く。

全 key の一覧と制約は `docs/DESIGN.md` の Data model。ここでは書くときに迷う点だけ挙げる。

### 他の sheet を混ぜる(`include`)

共通の hint（WM 操作、IME、自分のツール）を 1 枚にまとめ、各 sheet から混ぜられる。

```yaml
# hints/ja/wm.yaml — match が無いので単独では表示されない。混ぜられるためだけの sheet
id: wm
title: ウィンドウマネージャ
hints:
  - {id: close-window, title: ウィンドウを閉じる, key: Super+Shift+Q}
```

```yaml
# hints/ja/claude-code.yaml
id: claude-code
include: [wm]          # この sheet の一覧の末尾に wm の hint が並ぶ
```

```yaml
# config.yaml — include を書いていない sheet 全部に効く既定
include: [wm]
```

- sheet に `include:` があれば config の既定を**置き換える**（足し算ではない）。`include: []` と
  書けば「この sheet には何も混ぜない」
- 混ぜた hint はタグで絞らず全部出る。量を抑えたいときは共通 sheet を小さく分ける
- 混ぜた先の `include` は辿らない（1 段だけ）
- 存在しない id を書いても sheet は表示され、⚠ と `wayhint validate` に警告が出る（終了コードは 0）
- 混ざった hint を編集・削除すると**その hint の所属ファイル**が変わる。詳細欄の `ファイル:` が
  書き換え先の目安

### 言語ごとの hint

sheet は言語ごとのディレクトリに置く。**表示に使う言語のディレクトリだけ**が読まれる。

```
~/.config/wayhint/hints/
  ja/   claude-code.yaml  herdr.yaml   # 日本語環境ではこちらだけ
  en/   claude-code.yaml  herdr.yaml
```

- 言語は UI と同じ決め方(`appearance.language`、`auto` なら `LC_ALL` / `LC_MESSAGES` / `LANG`)。
  UI が日本語なら hint も日本語になり、両者がずれない
- 探す順は `hints/<言語>/` → `hints/en/` → `hints/*.yaml`(フラット)。1 言語だけで使うならフラットの
  ままでよい
- 同じ id の sheet を言語ごとに置ける(同時に読まれないため衝突しない)。翻訳の同期は自動では
  行われない
- 切り替えは `appearance.language` を書き換えるだけ(daemon の再起動は不要)。`LANG=en_US.UTF-8`
  で daemon を起動しても同じ。雛形は `examples/hints/en/` と `examples/hints/ja/`

### どの sheet が選ばれるか

sheet は `match` で選ぶ。`match.wayland.app_id_regex` は window の app_id に、
`match.process.argv_regex` と `cmdline_regex` は terminal の中で動いている foreground process に
当たる。どれも Python の正規表現で、部分一致。

foreground process を誰が答えるかは window の app_id で決まる。Herdr は自分で答えるが、
そのためには**窓の app_id に `herdr` が含まれている必要がある**(`herdr.yaml` の `app_id_regex` と
同じ前提。詳細は「Terminal の複数窓」から辿る `docs/TERMINALS.md`)。foot / footclient は
答えないので wayhint が `/proc` を辿り、
端末の子孫のうち tty の前面に居るプロセスを採る。**端末の窓が 2 枚以上あるときは
「Terminal の複数窓」の起動規約が要る**。規約に乗っていない窓が複数あるときは、どれか
決められないので何も答えない(間違った sheet を出すより出さない)。

複数の sheet が当たったときは `priority` の大きい方、同じなら当たった pattern の数が多い方、
それも同じならファイル名順。window の sheet と process の sheet が両方当たった場合は、window の
sheet が親、process の sheet が子になる。terminal 用の sheet を書いていなくてもよく、その場合は
親が無いのでコマンドの sheet の hint だけが出る。

### 親 sheet の hint を混ぜる

子 sheet が選ばれたとき、親 sheet の hint はタグで絞って後ろに並ぶ。対象のタグは子の
`inherit.parent_tags`、無ければ `config.yaml` の `nested.parent_tags`。どちらも空なら親の hint は
出ない。foreground process が どの sheet にも当たらなかったときは、親 sheet の hint が全部出る。

例えば Herdr の sheet に `tags: [terminal]` を付けた「新しい pane」を置き、Claude Code の sheet に
`inherit: {parent_tags: [terminal]}` を書くと、Claude Code 使用中は Claude の hint に続けて
pane 操作だけが並ぶ。

### hint のフィールド

`id` と `title` 以外は省略可。GUI / CLI / format が書く 12 項目と canonical 順は
`docs/DESIGN.md` の Data model「hints/*.yaml」を参照。

| キー | 用途 |
|---|---|
| `kind` | hint の種別。`shortcut` は `key` だけ、`command` は `command` だけ、`tip` は両方、`note` はどちらも持たない(tip と note は覚え書き)。`note` は YAML に `key` / `command` が残っていても一覧に出さない。`kind` 自体は **overlay には出ない**。絞り込みにも使わない |
| `key` | 一覧の左端に出るキー操作。例 `Ctrl-o`。長いものは 12 文字前後で折り返す(YAML に書いた改行もそのまま出る) |
| `command` | 一覧の title の下に出るコマンド文字列。**実行はしない**。表示とコピーのみ |
| `category` | 一覧の右端に出る見出し。同じ category の hint は隣り合って並ぶ |
| `tags` | 親 sheet として取り込まれるときの絞り込みに使う。検索の対象にもなる |
| `favorite` | `true` で `★` 付き、並び順の先頭へ |
| `copy` | コピーしたい文字列が表示と違うときだけ書く。省略時は `command`、次に `key` |
| `remark` | 選択したときだけ出る補足。一覧には出ない |
| `source` | 出典。公式ドキュメントの URL など |
| `learned` | 覚えた日。ISO 形式の日付に正規化される |

並び順は `docs/DESIGN.md` の Data model「hints/*.yaml」を参照。category を書かなかった hint には
擬似 category(`inbox` / `未定義`)のラベルが付く。`favorite` は並び順だけを変え、表示される
hint の数には影響しない。

### editor の補完を効かせる(任意)

`wayhint schema` が hint sheet の JSON Schema を出力する。editor の
yaml-language-server に読ませると、key の補完と検証が効く。

```sh
wayhint schema --write        # 出力先は editor.schema_path(既定 ~/.config/wayhint/schema.json)
```

各 sheet の先頭行にモードラインを置くと、その sheet に schema が結び付く。path は絶対で書く。

```yaml
# yaml-language-server: $schema=/home/USER/.config/wayhint/schema.json
```

`config.yaml` の `editor.schema_modeline` を true にすると、新規に作られる sheet と
`wayhint format` がこの 1 行を自動で付ける(既定値と意味は `docs/DESIGN.md` の Data model
「config.yaml」が正)。

## editor を変える

`config.yaml` の `editor.command` は argv の list。placeholder は `{file}` `{line}` `{hint_id}`。
shell を通らないので引用符やパイプは書けない。

```yaml
editor:
  command: [code, --goto, "{file}:{line}"]
```

## 困ったとき

| 症状 | 確認すること |
|---|---|
| `wayhint: wayhintd is not running` | `wayhintd -v` を前景で起動してログを見る。socket は `$XDG_RUNTIME_DIR/wayhint.sock` |
| `⚠ compositor does not provide wlr-foreign-toplevel-management` | labwc なら出ない。Wayfire は `[core] plugins` に `foreign-toplevel`、または `ipc` を入れて IPC fallback に任せる |
| `⚠ Wayfire IPC unavailable` | `context.backend: wayfire` 固定時のみ。`echo $WAYFIRE_SOCKET`、`[core] plugins` に `ipc` |
| `this Wayland session has no layer-shell support` | `gir1.2-gtk4layershell-1.0` が入っているか。X11/Xwayland では動かない |
| Herdr の中で親 sheet しか出ない | `herdr pane process-info --pane <focus 中の pane id>` の `foreground_processes` と `argv_regex` を照合 |
| Herdr でタブを切り替えてもヒントが変わらない | adapter は継承した `HERDR_*` に影響されず focus 中の pane を解決する(DECISIONS 0028)。それでも変わらないなら `herdr pane current` の `focused` と `pane_id` を確認する。常駐 daemon の起動元としては Herdr の pane 内のほか、compositor の autostart や `systemd --user` も使える |
| 検索欄や編集フォームで日本語(IME)が入らない | GTK が Wayland ネイティブの text-input-v3 を選べていない。`gsettings get org.gnome.desktop.interface gtk-im-module` が空でなければ GTK はその値を優先するので `gsettings reset org.gnome.desktop.interface gtk-im-module`。`GTK_IM_MODULE` も未設定にする(空なら GTK は `zwp_text_input_manager_v3` を広告する compositor で `wayland` context を自動で選ぶ)。確認は `GTK_IM_MODULE= WAYLAND_DEBUG=1 wayhintd` の出力に `zwp_text_input_v3.enter` と `enable` が出るか。layer-shell surface でも届く(labwc 0.20.2 + GTK 4.22 で確認) |
| 検索後にキー入力が元アプリに戻らない | 検索を終える(完了 / Esc)と keyboard_mode は必ず none に戻る。focus 復帰は foreign-toplevel `activate`(wayfire backend では IPC `set_focus`)。同じ app_id の window が複数あり title が変わっていると復帰先を決められない。`wayhintd -v` に `could not return focus` が出るか |

## ファイル構成

| パス | 内容 |
|---|---|
| `STATUS.md` | 何が終わっていて、何が残っていて、実機がどうなっているか |
| `src/` | 実装 |
| `tests/` | テスト |
| `docs/PRODUCT.md` | 要件 |
| `docs/DESIGN.md` | 設計 |
| `docs/DECISIONS.md` | 決定の記録 |
| `docs/TERMINALS.md` | terminal emulator と launcher の設定 |
| `examples/` | config.yaml と sheet の雛形 |
| `scripts/` | `setup`、`check`、この repository 専用の agent hook |
| `.agents/skills/` | agent 間で共有する skill |
| `.claude/`、`.codex/` | vendor ごとの adapter 設定(手で編集しない) |

## agent 向けの取り決め

共通の指示は `AGENTS.md` にまとめてあり、`CLAUDE.md` はそこを指すだけ。vendor 固有の設定は
`.claude/` と `.codex/` に閉じている。共通の hook は user scope に一度だけ登録してあり、この
repository には置かない。
