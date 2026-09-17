# wayhint

Wayland(wlroots 系 compositor: labwc / Wayfire など)上で hotkey 一発、いつも同じ場所
(既定: 画面右上)に、いま使っているアプリに応じたチートシートを overlay 表示する。Herdr の中で
使っているときは、focused pane の foreground process(Claude Code / Codex …)まで見て切り替える。
中身は YAML で自分で書いて育てる。

- 通常表示中は keyboard focus を奪わない(検索を明示的に開始したときだけ入力を受ける)
- hint は `~/.config/wayhint/hints/*.yaml`。overlay の編集ボタンから外部 editor で該当行を開く
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
| `style.css` | 任意。GTK CSS で見た目を上書き(class 名は `src/wayhint/ui/style.py`) |
| `hints/*.yaml` | sheet 1 ファイル 1 枚。ファイル名順に読む |

雛形は `examples/`。`cp -r examples/. ~/.config/wayhint/` で始められる。schema は
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
  <keybind key="W-slash">
    <action name="Execute" command="/home/USER/work/tools/wayhint/.venv/bin/wayhint toggle"/>
  </keybind>
</keyboard>
```

autostart は `~/.config/labwc/autostart` に 1 行(実行属性を付ける):

```sh
/home/USER/work/tools/wayhint/.venv/bin/wayhintd &
```

autostart が起動した helper の PID を記録して終了時に落とす仕組みを持っているなら、その作法に
従う(例: `spawn wayhintd`)。systemd の user unit は用意しない。理由は `docs/DECISIONS.md` 0011。

反映は `labwc --reconfigure`。

### Wayfire(`~/.config/wayfire.ini`)

```ini
[command]
binding_wayhint = <super> KEY_SLASH
command_wayhint = /home/USER/work/tools/wayhint/.venv/bin/wayhint toggle

[autostart]
wayhint = /home/USER/work/tools/wayhint/.venv/bin/wayhintd
```

手動で試すときは `wayhintd -v`(前景、info ログ。選ばれた backend が `desktop backend:` で出る)。
`wayhint ping` で応答を確認する。

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
| 検索 | 検索欄を開く。検索中だけキー入力を受ける。もう一度押すか `Esc` で終了 |
| 更新 | context を取り直す。別のアプリに移ったあと、閉じずに sheet を切り替えたいとき |
| コピー | 選択中の hint を clipboard へ。`copy` → `command` → `key` の順に、最初にある値 |
| ヒントを編集 | 選択中の hint の行を editor で開く |
| シートを編集 | 表示中の sheet を editor で開く |
| 閉じる | overlay を隠す |

検索は空白区切りの語をすべて含む hint に絞る。大文字小文字は区別しない。対象は title、`key`、
`command`、`category`、タグ、`remark`。件数の上限は `search.max_results`(既定 50)。
検索を終えると keyboard focus は元の window に戻る。

表示される context は **開いた瞬間に固定** される。別のアプリに移っても自動では追従しないので、
**更新** を押すか、一度閉じて開き直す。

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
| `reload` | `config.yaml` と `hints/*.yaml` を読み直す |
| `ping` | daemon の生死確認。pid と読み込み済み sheet 数を返す |
| `validate` | YAML を検証する。daemon を必要としない唯一の command。問題があれば exit 1 |

`validate` は `--config-dir`、それ以外は `--socket` で既定の場所を上書きできる。
daemon 側は `wayhintd -v` で info ログを前景に出す。

### daemon を再起動する

`reload` が読み直すのは `config.yaml` と `hints/*.yaml` だけで、Python 側を変えたときは daemon を
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

1. `hints/` に新しい YAML を置く(または既存の sheet に hint を足す)。
2. daemon は保存を検知して自動 reload する(overlay を閉じる必要はない)。壊れた YAML のときは
   直前の正常版を表示し続け、overlay 上部に `⚠ YAML error file:line: message` が出る。
3. overlay の **シートを編集** / **ヒントを編集** で editor が該当ファイル・該当行を開く。

全 key の一覧と制約は `docs/DESIGN.md` の Data model。ここでは書くときに迷う点だけ挙げる。

### どの sheet が選ばれるか

sheet は `match` で選ぶ。`match.wayland.app_id_regex` は window の app_id に、
`match.process.argv_regex` と `cmdline_regex` は Herdr の focused pane の foreground process に
当たる。どれも Python の正規表現で、部分一致。

複数の sheet が当たったときは `priority` の大きい方、同じなら当たった pattern の数が多い方、
それも同じならファイル名順。app_id が分かる window の中で Herdr のように別プロセスが動いている
場合は、window の sheet が親、process の sheet が子になる。

### 親 sheet の hint を混ぜる

子 sheet が選ばれたとき、親 sheet の hint はタグで絞って後ろに並ぶ。対象のタグは子の
`inherit.parent_tags`、無ければ `config.yaml` の `nested.parent_tags`。どちらも空なら親の hint は
出ない。foreground process が どの sheet にも当たらなかったときは、親 sheet の hint が全部出る。

例えば Herdr の sheet に `tags: [terminal]` を付けた「新しい pane」を置き、Claude Code の sheet に
`inherit: {parent_tags: [terminal]}` を書くと、Claude Code 使用中は Claude の hint に続けて
pane 操作だけが並ぶ。

### hint のフィールド

`id` と `title` だけが必須。あとは書きたいものだけ書く。

| キー | 用途 |
|---|---|
| `kind` | `shortcut` / `command` / `tip` / `note`。**overlay には出ない**。YAML 上の分類で、絞り込みにも使わない |
| `key` | 一覧の左端に出るキー操作。例 `Ctrl-o` |
| `command` | 一覧の title の下に出るコマンド文字列。**実行はしない**。表示とコピーのみ |
| `category` | 一覧の右端に出る見出し。同じ category の hint は隣り合って並ぶ |
| `tags` | 親 sheet として取り込まれるときの絞り込みに使う。検索の対象にもなる |
| `favorite` | `true` で `★` 付き、並び順の先頭へ |
| `copy` | コピーしたい文字列が表示と違うときだけ書く。省略時は `command`、次に `key` |
| `remark` | 選択したときだけ出る補足。一覧には出ない |
| `source` | 出典。公式ドキュメントの URL など |
| `learned` | 覚えた日。ISO 形式の日付に正規化される |

並び順は `favorite` が先頭、次に category が最初に現れた順、その中では YAML に書いた順。
`favorite` は並び順だけを変え、表示される hint の数には影響しない。

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
| Herdr の中で親 sheet しか出ない | `herdr pane process-info --current` の `foreground_processes` と `argv_regex` を照合 |
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
| `examples/` | config.yaml と sheet の雛形 |
| `scripts/` | `setup`、`check`、この repository 専用の agent hook |
| `.agents/skills/` | agent 間で共有する skill |
| `.claude/`、`.codex/` | vendor ごとの adapter 設定(手で編集しない) |

## agent 向けの取り決め

共通の指示は `AGENTS.md` にまとめてあり、`CLAUDE.md` はそこを指すだけ。vendor 固有の設定は
`.claude/` と `.codex/` に閉じている。共通の hook は user scope に一度だけ登録してあり、この
repository には置かない。
