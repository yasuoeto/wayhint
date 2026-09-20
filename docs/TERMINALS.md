# Terminal emulator 対応

端末の窓の中で動いているコマンドを wayhint がどう見つけるか、そのために端末と launcher を
どう設定するか。**なぜこの方法なのか**は `docs/DECISIONS.md` 0027、設計上の位置づけは
`docs/DESIGN.md`「Architecture」にある。ここは手順だけを書く。

## 何が問題か

hint を出したい相手は端末そのものではなく、その中で動いているコマンド(`vi`、`top`、`claude`)
である。端末は自分が何を動かしているかを外に教えないので、wayhint は `/proc` を辿って
「その端末の子孫のうち、tty の前面に居るプロセス」を探す。

辿り始める場所 ―― **どの端末プロセスが前面の窓を描いているか** ―― が分からない。

- Wayland の protocol は toplevel の PID を client に渡さない
  (`zwlr_foreign_toplevel_manager_v1` にも `ext_foreign_toplevel_list_v1` にも PID は無い)
- labwc に問い合わせ用の IPC は無い
- foot にも問い合わせ口は無い

端末の窓が 1 枚だけなら「その端末のプロセスは 1 つしか無い」で済む。2 枚以上あると決められない。
そして端末は複数窓で使うのが普通である。

## app_id の `.p<pid>` 規約

compositor が client に渡してくれる数少ない情報が **app_id** なので、**窓の側が app_id で名乗る**。

app_id の末尾が `.p<数字>` なら、wayhint はその数字を端末プロセスの PID として扱う。

```
app_id = "foot.p12345"  →  base "foot" / PID 12345 から /proc を辿る
app_id = "foot"         →  foot のプロセスが 1 つだけならそれ、複数なら無判定
```

読み取った PID は `/proc` の `comm` と照合してから使う。窓を閉じれば app_id は誰のものでもなく
なり、その番号は別のプロセスに再利用されるため。

接尾辞は wayhint が外してから扱うので、**設定した側が気にすることは無い**。

- sheet の `app_id_regex` は `["^foot$"]` のまま書けばよい(`foot.p12345` にも当たる)
- overlay の context ラベルにも `foot` と出る
- `wayhint context` の `desktop_app` にだけ `foot.p12345` がそのまま出る(窓の識別子なので)

## 端末ごとの対応

| 端末 | 規約への乗せ方 | 条件 |
|---|---|---|
| foot | `--app-id "foot.p$$"` | 無し(foot に tab は無い) |
| kitty | `--class "kitty.p$$"` | `single_instance` を有効にしない(既定は無効)。**tab / split は 1 枚だけ** |
| Ghostty | `--class="com.mitchellh.ghostty.p$$"` | `gtk-single-instance=false`(既定は有効)。**tab / split は 1 枚だけ** |
| Herdr | 窓の app_id に `herdr` を含める | 含まれていない窓は Herdr 経路に乗らない(下記) |
| WezTerm | 乗らない | 窓ごとに app_id を変えられない |

**tab / split は 1 枚だけ**、というのは `/proc` の限界による。tab や split は 1 枚につき 1 つの
pty を持ち、それぞれに前面プロセスが居るが、`/proc` はどれが画面に出ているかを教えない。
2 つ以上見つかった時点で無判定になる(どれかを選ぶと間違える)。同じ理由で、1 枚の中で `tmux` や
`ssh -t` を動かしていても無判定になる。tab / split を使いたい場合は端末専用の adapter が要る
(`docs/DECISIONS.md` 0027 の「やらないこと」)。

`$$` を使うために wrapper script を 1 枚挟む。`exec` しているので `$$` はそのまま端末自身の
PID になる。値の作り方には依存しないので、固定値でも一意でありさえすれば動く。

### foot

```sh
#!/bin/sh
# ~/.local/bin/foot-wayhint
exec /usr/bin/foot --app-id "foot.p$$" "$@"
```

### kitty

`--class`(`--app-id` は別名)が Wayland の app_id になる。既定で 1 窓 1 プロセスなのでそのまま
乗る。`single_instance` を有効にしていると全部の窓が 1 プロセスになり、`.p<pid>` が指す PID と
個々の窓が対応しなくなる。

```sh
#!/bin/sh
# ~/.local/bin/kitty-wayhint
exec /usr/bin/kitty --class "kitty.p$$" "$@"
```

### Ghostty

既定の `gtk-single-instance=true` では全部の窓が 1 プロセスになるため、`false` にしたうえで
`--class` を渡す。`class` を変えると `.desktop` や D-Bus activation からの起動が壊れることが
ある(`man 5 ghostty` の `class` 参照)。

```sh
#!/bin/sh
# ~/.local/bin/ghostty-wayhint
exec /usr/bin/ghostty --gtk-single-instance=false --class="com.mitchellh.ghostty.p$$" "$@"
```

### Herdr

Herdr は `herdr pane current` / `herdr pane process-info` で focused pane を自分で答えるので、
`/proc` 経路を通らない。ただし**前提が 1 つある**。

> **Herdr の窓の app_id に `herdr` が含まれていること。**

app_id で adapter が選ばれるので、含まれていない窓は Herdr 経路に乗らない。前提は 2 か所で効く。

| どこ | 何 | 変えられるか |
|---|---|---|
| adapter の選択 | `context/herdr.py` の `app_id_pattern`(既定 `herdr`、部分一致・大小無視) | **不可**(config.yaml に項目は無い) |
| 親 sheet の選択 | `herdr.yaml` の `match.wayland.app_id_regex: ["herdr"]` | 可(YAML) |

`foot --app-id=foot-herdr ... herdr` のような起動ならこれを満たす。素の端末で `herdr` を起動すると
app_id は `foot` や `kitty` のままなので満たさない。そのときは app_id 側に `herdr` を入れる。

```sh
kitty  --class kitty-herdr -e herdr
ghostty --gtk-single-instance=false --class=com.mitchellh.ghostty-herdr -e herdr
foot   --app-id foot-herdr herdr
```

前提を満たさない窓では、`/proc` 経路が動く端末(foot / kitty / Ghostty)なら「**`herdr` という
コマンドが動いている**」ところまでは分かるが、その中のどのタブを見ているかは分からない。
その状態になると `wayhintd -v` のログに 1 行出る:

```
herdr is running in a window whose app_id is 'kitty'; open it with 'herdr' in the app_id
to get hints for what is inside it (docs/TERMINALS.md)
```

**Herdr の窓は何枚開いてもよい。** クライアント窓は同じセッションのミラーで、2 枚目を別のタブで
開いても 1 枚目がそのタブに追随する。どの窓も同じ pane を表示するので、herdr が答える focused
pane はどの窓から見ても正しい(2026-09-20 実機確認)。ただし**どの窓も app_id に `herdr` を
含めること**——含まれていない窓だけが上の `/proc` 経路に落ちる。

唯一の例外は**名前付きセッションを複数動かした場合**(`herdr --session <名前>`)。セッションごとに
socket が分かれるが、adapter は常に既定セッションに聞く。既定以外のセッションの窓では正しく
答えられない(`docs/DECISIONS.md` 0028)。

### WezTerm

窓ごとに app_id を変えられないため、この規約に乗らない。`wezterm cli list-clients` →
`tty_name` → `/proc` の経路で別途対応できることは確認済みだが、未実装(`docs/DECISIONS.md` 0027)。

## launcher の配線

wrapper を作っただけでは何も変わらない。**端末を起動している経路すべて**を wrapper に向ける。

### 1. 起動経路を洗い出す

配線の仕方は launcher が端末をどう呼んでいるかで 3 通りに分かれる。まず調べる。

```sh
grep -rn 'foot' ~/.config/waybar/config.jsonc ~/.config/labwc/menu.xml ~/.config/labwc/rc.xml
grep -n 'Exec' /usr/share/applications/foot.desktop
```

以下は実例(labwc + waybar + fuzzel の構成)。

### 2. 絶対パスで呼んでいる launcher

waybar の `on-click` のように絶対パスを書いてある場合は、そこを直すしかない。

```diff
     "custom/launcher-foot": {
         "format": "",
         "tooltip-format": "foot",
-        "on-click": "/usr/bin/foot"
+        "on-click": "/home/USER/.local/bin/foot-wayhint"
     },
```

### 3. PATH で解決する launcher

labwc のルートメニュー(`~/.config/labwc/menu.xml`)のように素のコマンド名を書いてある場合。
launcher が継承する PATH に `~/.local/bin` が `/usr/bin` より先に入っていれば名前だけでも
届くが、**launcher の設定は絶対パスで書くほうが後から追える**。

```diff
   <item label="Terminal emulator">
-    <action name="Execute" command="foot" />
+    <action name="Execute" command="/home/USER/.local/bin/foot-wayhint" />
   </item>
```

compositor の keybind も同じ(`~/.config/labwc/rc.xml`):

```xml
<keybind key="W-Return">
  <action name="Execute" command="/home/USER/.local/bin/foot-wayhint"/>
</keybind>
```

### 4. `.desktop` から起動する launcher

fuzzel やアプリ一覧はシステムの `.desktop` を読む(`/usr/share/applications/foot.desktop` の
`Exec=foot`)。**システムのファイルは触らず**、`~/.local/share/applications/` に同じ名前で置けば
そちらが優先される。

```ini
# ~/.local/share/applications/foot.desktop
[Desktop Entry]
Type=Application
Exec=/home/USER/.local/bin/foot-wayhint
Icon=foot
Terminal=false
Categories=System;TerminalEmulator;
Keywords=shell;prompt;command;commandline;

Name=Foot
GenericName=Terminal
Comment=A wayland native terminal emulator
```

`Exec` に `%F` などの引数書式がある `.desktop` を写すときは、wrapper の `"$@"` がそれを
受け取るので消さずに残す。

fuzzel には `terminal=` 設定もある(`Terminal=true` の `.desktop` を開くときに使う端末)。
そちらも合わせておく:

```ini
# ~/.config/fuzzel/fuzzel.ini
terminal=/home/USER/.local/bin/foot-wayhint
```

### 5. 反映

| 変えたもの | 反映 |
|---|---|
| waybar の設定 | waybar を再起動 |
| labwc の `menu.xml` / `rc.xml` | `labwc --reconfigure` |
| `~/.local/share/applications/*.desktop` | 不要。fuzzel は起動のたびに XDG のディレクトリを読み直す |
| wrapper script 自体 | 不要。次に開く窓から効く |

**alias は使えない。** alias は対話シェルの中だけのもので、launcher はシェルの設定を読まずに
実行する。

### 代替: PATH に影を置く

`~/.local/bin/foot` という**本体と同じ名前**で wrapper を置けば、PATH で解決している経路は
設定を触らずに乗る。絶対パスで呼んでいる経路(上の 2)だけは直す必要がある。

```sh
#!/bin/sh
exec /usr/bin/foot --app-id "foot.p$$" "$@"   # /usr/bin/ は必須。素の foot だと自分を呼んで無限再帰
```

手数は減るが、以後その端末を名前で起動した全てが黙って `--app-id` 付きになる。後から挙動を
追いにくいので、経路ごとに明示するほうを勧める。

## 効いているか確かめる

**端末の中で `wayhint context` を叩いてはいけない。** 前面のプロセスを知りたいのに、叩いた
瞬間その `wayhint` 自身がその端末の前面プロセスになる。同じ理由で `vi memo &` のように
background に置いたものも答えにはならない(background のプロセスは前面プロセス群に居ない)。
**観測が対象を変えない方法**で見る。

### 1. overlay で見る(いちばん簡単)

wrapper で開いた端末で `vi` などを**前景のまま**動かし、そこに focus を置いて hotkey を押す。
overlay の見出しの下に context が出る。

```
foot  ·  vi  ·  eDP-1
```

`foot`(接尾辞は外れる)と、その端末で動かしているコマンド名が並んでいれば効いている。

### 2. `wayhint context` の全文が要るとき

compositor の keybind から実行してファイルに落とす。keybind から起動したプロセスは制御端末を
持たないので、端末の前面プロセスは変わらない。

```sh
cat > ~/.local/bin/wayhint-ctx <<'EOF'
#!/bin/sh
exec wayhint context > /tmp/wayhint-context.txt 2>&1
EOF
chmod +x ~/.local/bin/wayhint-ctx
```

```xml
<!-- ~/.config/labwc/rc.xml -->
<keybind key="W-S-c">
  <action name="Execute" command="/home/USER/.local/bin/wayhint-ctx"/>
</keybind>
```

端末で `vi` を前景のまま動かし、その窓に focus を置いて `W-S-c` を押してから、別の窓で読む。

```
$ cat /tmp/wayhint-context.txt
active_sheet=vi desktop_app=foot.p12345 chain=['ProcAdapter'] process={'name': 'vi', ...}
```

### 出ないときの読み方

| 症状 | 原因 |
|---|---|
| `desktop_app` に `.p<pid>` が無い | その窓が wrapper を通っていない。別の経路から開いていないか(「起動経路を洗い出す」に戻る) |
| `chain` が出ない | その app_id は対象外。`.p<pid>` を外した残りが `foot` `footclient` `kitty` `com.mitchellh.ghostty` のどれかと**完全一致**する必要がある(Herdr の窓は別経路なので `chain=['HerdrContextProvider']` になる) |
| `chain` は出るが `process` が無い | 端末プロセスか、その中の pty を特定できていない。(a) kitty の `single_instance` / Ghostty の `gtk-single-instance` が有効で全窓が 1 プロセスになっている (b) wrapper 無しの窓が複数ある (c) **その窓が tab / split を複数持っている、または tmux や `ssh -t` で pty が増えている**(下の「対応していないもの」) |
| `process` に `wayhint` と出る | 端末の中で `wayhint context` を叩いている。上の 1 か 2 の方法で見る |
| `process` は出るが `active_sheet` が出ない | 規約は効いている。そのコマンドの sheet をまだ書いていないだけ(`README.md`「hint を書く」) |

## 対応していないもの

- **wrapper を通さない窓** ―― その端末のプロセスが 1 つだけなら従来どおり解決する。2 つ以上に
  なった時点で無判定になる(間違った sheet を出すより出さない)。**Herdr をその端末で動かして
  いる場合は「1 つだけ」にならない**: Herdr を `foot --app-id=foot-herdr` で開いていると foot の
  プロセスは常に 2 つ以上あるので、wrapper を通さない foot の窓は常に無判定になる。
- **1 つの窓が複数の pty を持つ状態** ―― tab、split、`tmux`、`ssh -t`。前面プロセスは pty ごとに
  存在し、`/proc` はどの pty が画面に出ているかを持たない。深さや PID の大小で推測せず、無判定に
  する。対応するには端末自身に focus を聞く adapter が要る(kitty なら `kitten @ ls`、WezTerm なら
  `wezterm cli list-clients`)。
- **foot の server モード**(`foot --server` + `footclient`) ―― 窓を開いた client の PID と、shell の
  親になっている server の PID が別なので規約に乗らない。
- **端末の title で判別する方法** ―― `vim` / `neovim` は title を出すが `top` / `htop` / `less` /
  `more` は出さない。shell 側から通知させても、title を出す TUI が起動直後に上書きする。
- **`TERMINAL_APP_IDS` の設定項目化** ―― 対象は「コマンドを子孫として動かす端末である」という
  プログラムの性質で決まるもので、好みではない。`src/wayhint/context/proc.py` の定数。
