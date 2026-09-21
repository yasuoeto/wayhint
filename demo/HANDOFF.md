# HANDOFF — デモ動画生成 Phase A → Phase B

Phase A(Fable、2026-09-21)の実測結果と引き継ぎ。**Phase B はこのファイルだけを頼りに環境を知る**。
本プロンプトと食い違う箇所は、実測に基づくこのファイルが正。Phase B 完了時に内容を
`docs/DECISIONS.md` 0031 / `docs/DESIGN.md` / `demo/README.md` へ取り込み、このファイルは削除する。

試行 script は scratchpad(`/tmp/claude-1000/.../scratchpad/probe*.py`)に置き、repo には残していない。
すべて `tools/headless.py` の `HeadlessSession` を継承した labwc headless session(1280×720)で測った。
実測でない箇所は「推測」と明記する。

## 1. 事前確認 1〜6 の実測結果

### 1-1. `tests/headless.py` → `tools/headless.py` の抽出

- 移動+改名のみで成立した(commit 614abfd)。`HeadlessSession` / `difference_box` / `_A11Y_PROBE` /
  定数を `tools/headless.py` へ。`_compositor()` → `compositor()`、`requirements()` から
  `WAYHINT_GUI_TESTS` 判定を除いたものを `missing()` に。`tests/headless.py` は ENABLE 判定・
  `requirements()`・`needs_headless` / `needs_key_injection` だけの薄い層で、`HeadlessSession` と
  `difference_box` を re-export する。`tests/test_gui_headless.py` は無変更。
- `scripts/check` の compileall に `tools`、`pyproject.toml` の `[tool.ruff] src` に `tools` を追加。
- 前後で `./scripts/check` 359 tests OK(skip 6)、`./scripts/check-gui` 5 tests OK 22.2s と一致。

### 1-2. headless output の解像度を 1280×720 にする方法

- **何も設定しなくても 1280×720**。wlroots headless backend の既定 output サイズがそれで、
  session 起動直後の `grim -o HEADLESS-1` を `magick identify -format %wx%h` すると `1280x720`。
  `WLR_HEADLESS_OUTPUTS=1` は枚数の指定で、サイズは変えない。
- labwc の `rc.xml` には output のモード設定が無い(`man labwc-config` で output に関する項は
  `<core><autoEnableOutputs>` と `<core><reuseOutputMode>` だけ)。
- 別サイズが要るときは session 内で `wlr-randr --output HEADLESS-1 --custom-mode WxH` が効く
  (`1920x1080` にすると grim も 1920×1080、`1280x720` に戻すと戻る。`/usr/bin/wlr-randr` は導入済)。
- **Phase B の方針**: 既定に頼り、最初の frame の寸法が `scenario.output` と違えば fail。
  `wlr-randr` は scenario の `output` が 1280×720 以外のときだけ呼ぶ(初版では呼ばない)。

### 1-3. foot の `--app-id foot.p<pid>` と stub の照合

- foot 1.28.0 の構文は `foot [OPTIONS] command [ARGS...]`。`-e` は「互換のため無視」。
  `-a/--app-id=ID` あり。`--override=key=value` で設定を上書きできる。
- **pid は exec するまで分からない**ので、scenario の `spawn.argv` に `{pid}` を書く方式は成立しない。
  README「Terminal の複数窓」と同じ wrapper を `demo/bin/foot-wayhint` に置く:
  ```sh
  #!/bin/sh
  exec /usr/bin/foot --app-id "foot.p$$" "$@"
  ```
  これを `Popen([..., "foot-wayhint", "--override=cursor.blink=no",
  "--override=cursor.unfocused-style=unchanged", "<stub>"], start_new_session=True)` で起動する。
  `{pid}` プレースホルダは schema から外し、置換は `{demo_bin}` だけにする(決定事項の変更 → §2)。
- **stub は shebang script でよい。`exec -a` は不要**。`src/wayhint/context/proc.py` の `_name()` は
  `basename(argv[0])` を取り、それが interpreter(`sh` `bash` `zsh` `python*` `node`)なら
  `basename(argv[1])` を名前にする。実測:
  - `#!/usr/bin/env python3` の `demo/bin/claude` →
    `process={'name': 'claude', 'argv_basenames': ['python3', 'claude']}`、`active_sheet=claude-code`
  - `#!/bin/sh` の `claude` → `process={'name': 'claude', 'argv_basenames': ['sh', 'claude']}`、同じく
    `active_sheet=claude-code`
  - どちらも `chain=['ProcAdapter']`、`desktop_app=foot.p<pid>`
- **選んだ方式: python3 shebang**。理由: 偽画面を複数行出して `sys.stdin.read()` で待つだけで済み、
  外部プロセスを起動しない。**stub が foreground の子プロセス(`sleep` など)を持つと、
  `_foreground_pid()` は tty の foreground group で最も深い子孫を採るので `sleep` が名前になる**。
  sh で書くなら builtin の `read` で待つこと。
- `wayhint context` の出力形式(CLI が `key=value` を空白区切りで 1 行に並べる):
  `active_sheet=claude-code desktop_app=foot.p1940820 process={'name': 'claude', 'argv_basenames': ['python3', 'claude']} include=['wm'] chain=['ProcAdapter']`。
  窓が無いときは空行(値が全部 None で何も出ない)。
- **窓の位置・大きさは labwc の windowRules で固定できる**(glob、大文字小文字無視):
  ```xml
  <windowRules>
    <windowRule identifier="foot.p*">
      <action name="MoveTo" x="40" y="60"/>
      <action name="ResizeTo" width="760" height="480"/>
    </windowRule>
  </windowRules>
  ```
  実測の窓の差分 bounding box は `(762, 508, 40, 60)`(幅 762 = 760+枠、高さ 508 = 480+SSD の
  タイトルバー)。**2 枚目の窓を別の場所に置くには foot の `--title=<name>` と rule の `title=` 条件を
  使う**(実測: `title="demo-a"` → MoveTo 40,60 / ResizeTo 600×400 で box `(602, 424, 40, 60)`、
  `title="demo-b"` → MoveTo 200,280 で 2 枚目がそこに出た)。**app_id の接頭 `foot` は変えない**
  (`ProcAdapter` は `.p<pid>` を外した base が `TERMINAL_APP_IDS` に入っていることを要求する)。
  focus を失った窓は SSD のタイトルバーの色が変わる(差分になるが決定的)。
- 場面④の経路は通る: 2 枚目の foot(`vi` stub)を起動すると focus が移り `active_sheet=vi`、
  overlay 表示中に `W-h` を押すと log に
  `hotkey from another window: replacing claude-code with vi` が出て、hide を挟まず sheet が
  差し替わる(daemon の `toggle_action` → `replace`)。
- 場面②の経路も通る: overlay 表示中(normal、grab 無し)に `wtype hello` すると端末側に
  echo され、差分は端末内 `(25, 12, 41, 123)` だけ。

### 1-4. AT-SPI の Action interface でボタンを押す

- **押せる**。GTK 4.22.4 のボタンは AT-SPI 上で **role `button`**(`push button` ではない)、
  name はラベル文字列、Action interface に action 1 個 `click`。`get_action_iface().do_action(0)` は
  `True` を返し、実際に効く:
  - `Search` → ボタン名が `Done` に変わり、daemon log `keyboard: mode=search visible=True grab=True`
  - `Edit` → `keyboard: mode=edit visible=True grab=True`(`W-C-h` の代替になる)
  - `Close` → `wayhint` frame が AT-SPI ツリーから消え、frame の差分も無し
- ボタン名は言語で変わる。en: `Search` `Copy` `Edit in editor` `Edit` `Close`、
  ja: `検索` `コピー` `エディタで編集` `編集` `閉じる`。scenario の `press: {button: search}` は
  論理名で書き、`src/wayhint/i18n.py` の対訳表(`"Search"` → `"検索"`)で言語ごとに解く。
- **タイミング**: `do_action` は click の処理完了を待たない。押した 0.4 秒後に wtype すると
  文字が届かず(一覧が絞られない)、1.0 秒後なら届いた(7 件 → `comp` で 1 件)。
  **`press` の直後は必ず状態を `wait_for` してから `type` する**(ボタン名 `Done` の出現、または
  daemon log の `keyboard: mode=search ... grab=True`)。
- **読めないもの**: `Gtk.SearchEntry` は AT-SPI ツリーに text ノードとして現れない。フォームの
  `Gtk.Entry` は role `text` で現れるが Text interface の `get_text` は入力後も空だった。
  → 検索文字列・フォーム内容は AT-SPI で検証できない。**効果で検証する**: 検索は list item の数、
  フォーム保存は一覧の label(`Ctrl+X` / `Demo hint`)と fixtures の YAML の中身。
- AT-SPI probe は毎回 python3 子プロセス(`Atspi.init()`)で 0.3〜0.5 秒。`wait_for` の poll 間隔に
  使える速さ。frame は `get_role_name() == "frame" and get_name() == "wayhint"` で特定する。
- **押し損ねたら即 fail すること**。押せていない状態で `type` を続けると、grab が無いので文字は
  端末へ落ちて echo される(試行中に stub の画面へ `pane^[` が出た)。

### 1-5. ツールと font の有無

| もの | 結果 |
|---|---|
| **ffmpeg** | **無い**。`apt-cache policy ffmpeg` の候補は `7:8.1.2-2+b3`。**Phase B の B-4 前に `sudo apt install ffmpeg` が要る**。drawtext / libx264 / libvpx-vp9 の有無は未確認(推測: Debian の ffmpeg は全部入り) |
| wtype | `/usr/bin/wtype`、dpkg `0.4-3`(`wtype --version` は非対応) |
| grim | `/usr/bin/grim`、dpkg `1.5.0+ds-1` |
| ImageMagick | `magick` `compare` `convert` あり、`ImageMagick 7.1.2-31 Q16`(dpkg `8:7.1.2.31+dfsg1-1`) |
| foot | `1.28.0 +pgo +ime +graphemes +toplevel-tag +blur` |
| labwc | `0.20.2 (+xwayland +nls +rsvg +libsfdo) wlroots-0.20.2` |
| GTK / layer-shell / AT-SPI | GTK 4.22.4、libgtk4-layer-shell0 1.3.0、at-spi2-core 2.62.0 |
| wlr-randr / dbus-daemon | あり |
| sway / cage / wf-recorder / ydotool | 無い(不要) |
| Noto Sans CJK JP | あり(`fc-match` → `NotoSansCJK-Regular.ttc`、fonts-noto-cjk `1:20240730+repack1-1`) |
| Noto Sans Mono | あり(`fc-match` → `NotoSansMono-Regular.ttf`、fonts-noto-mono `20201225-6`) |

- このマシンの `sans-serif` / `monospace` の既定は **VL ゴシック**に解ける。fixtures の `style.css` と
  foot の `font=` で Noto を明示しないと、別マシンで font が変わるだけでなくこのマシンでも
  Noto では撮れない。
- font 欠落の検出は `fc-match -f '%{family}' 'Noto Sans CJK JP'` の結果が要求 family と一致するかで
  判定できる(欠けていると別 family に fallback して返す)。apt package 名は `fonts-noto-cjk` と
  `fonts-noto-mono`。

### 1-6. 編集モードの key を wtype で送る

- **すべて届いた**。経路は `check-gui` の hotkey テストと同じ(`wtype` → labwc の
  `zwp_virtual_keyboard_manager_v1`)。rc.xml に `W-h` → `wayhint toggle`、`W-C-h` → `wayhint edit-mode`
  を書いた session で:
  1. `wtype -M logo -M ctrl -k h -m ctrl -m logo` → `keyboard: mode=edit visible=True grab=True`
  2. `wtype -k a` → フォームが開く(AT-SPI に label `Title` `Key` `Category` `Remark` `Kind`、
     role `text` の entry 4 個、`combo box 'shortcut'`、help label
     `Enter save and leave · Esc discard · Tab next field · Ctrl+P parent sheet`)
  3. `wtype "Demo hint"` → `wtype -k Tab` → `wtype "Ctrl+X"` → `wtype -k Return` → 保存。
     一覧に `Ctrl+X` / `Demo hint` が増え、fixtures の `claude-code.yaml` 末尾に
     `- id: demo-hint / title: Demo hint / kind: shortcut / key: Ctrl+X / ... / learned: '2026-09-21'`
     が書かれ、log に `reloaded claude-code.yaml: ok`、mode は `normal` に戻る(DECISIONS 0021)。
  4. `wtype -M logo -k h -m logo` → hide。
- 検索モードの `Escape` も wtype で届き、`Search` に戻って grab が外れる。
- wtype の key 名は xkb keysym(`Tab` `Return` `Escape` `h` `a`)、修飾は `-M/-m logo|ctrl|shift`。
- 各 wtype の後に 0.4 秒置いて AT-SPI を読めば状態が追えた(wtype 自体は同期)。
- **`learned:` に当日の日付が書かれる**。画面の一覧には出ない(title / key / category のみ。
  詳細欄は remark と `ファイル:`)ので frame には影響しないが、fixtures は**毎回 temp へコピーして
  使い、`demo/fixtures/` 自体を書き換えない**こと。

### 1-7. 追加で分かったこと(再現性)

- foot に `--override=cursor.blink=no` だけだと、focus の出入りで cursor が hollow ↔ 塗りに
  変わり `(3, 10, 42, 124)` の差分が残る。**`--override=cursor.unfocused-style=unchanged` を足す**と、
  show/hide 3 往復と `W-h` 2 連打のどれも基準 frame と差分無し(AE=0 相当、`difference_box` が None)。
- config.yaml に validation error があると **config 全体が既定に落ち**、`appearance.language` も
  `auto`(= このマシンでは locale `ja_JP.UTF-8` → ja)になる。試行中に
  `editor.command: [true]` が bool 扱いで落ちて UI が日本語になった。fixtures の config は
  `wayhint validate` を通してから使う。`editor.command` は非空文字列のリスト。
- `wayhintd -v` の log(`HeadlessSession.log`、`<home>/session.log`)に
  `wayhint.ui.window DEBUG keyboard: mode=<normal|search|edit> visible=<bool> grab=<bool>` と
  `wayhintd INFO overlay open on workspace ...: sheet <id>` / `hotkey from another window: replacing A with B`
  が出る。`wait_for` の判定材料に使える(AT-SPI より速い)。
- session 起動(compositor + bus + daemon + 初回 show/hide)は 1.6 秒。probe 1 本の全工程で 18〜24 秒。

## 2. 決定事項のうち変更したもの

1. **`spawn.argv` の `{pid}` は廃止**。pid は exec 後にしか決まらないので、README と同じ wrapper
   `demo/bin/foot-wayhint`(`exec /usr/bin/foot --app-id "foot.p$$" "$@"`)を経由する。置換は
   `{demo_bin}` のみ。scenario 例:
   `spawn: {name: foot, argv: ["{demo_bin}/foot-wayhint", "--override=cursor.blink=no", "--override=cursor.unfocused-style=unchanged", "{demo_bin}/claude"]}`。
2. **AT-SPI Action は使える**ので `cli:` への格下げは無し。ただし `press` の後は状態の `wait_for` が
   必須(§1-4)。ボタンの role は `button`。
3. **foot の起動オプションに `cursor.unfocused-style=unchanged` を追加**(§1-7)。0030 の知見
   (blink 停止)だけでは focus 変化の差分が残る。
4. **output 解像度は設定しない**(既定が 1280×720)。最初の frame の寸法を検証して違えば fail。
5. **ffmpeg は未導入**。`--record` は ffmpeg が無ければ apt package 名(`ffmpeg`)を出して fail、
   `--dry-run` / `--validate` は ffmpeg 無しでも動くこと。
6. 検索文字列・フォーム内容は AT-SPI で読めない(§1-4)。`wait_for` の条件に「entry の中身」は
   入れず、list item 数・label・ボタン名・log 行で判定する。
7. stub の方式は **python3 shebang**(`exec -a` 不要、理由は §1-3)。

## 3. `tools/headless.py` の公開 API(Phase A 終了時点)

module 定数: `REPO`(repo root)、`COMPOSITORS = ("labwc", "sway", "cage")`、`TOOLS = ("grim", "magick")`、
`INJECT = "wtype"`、`HEADLESS_OUTPUT = "HEADLESS-1"`、`START_TIMEOUT = 15.0`。

- `compositor() -> str | None` — PATH 上の最初の compositor 名。
- `missing() -> str | None` — 無いもの(compositor / grim / magick / `XDG_RUNTIME_DIR` /
  `.venv/bin/wayhintd`)の説明、揃っていれば None。**wtype と ffmpeg は見ない**(Phase B 側で確認)。
- `difference_box(on: Path, off: Path) -> tuple[w, h, x, y] | None` — 2 frame の差分の bounding box
  (`magick ... -threshold 5%`)。差が無ければ None。
- `class HeadlessSession(config_dir, *, width=1280, height=720, keybind: tuple[str, str] | None = None)`
  context manager。`keybind` は `("W-h", "toggle")` の形で **1 個だけ**、labwc のときだけ rc.xml に書く。
  `width` / `height` は保持するだけで output には反映しない(既定 1280×720 に一致)。
  - 属性: `config_dir` `compositor` `display="wayland-0"` `runtime`(`$XDG_RUNTIME_DIR/wh-t<pid>`)
    `home`(`mkdtemp("wayhint-headless-")`)`log`(`<home>/session.log` の file object)`keybind`。
  - `env(*, inside=True) -> dict` — DISPLAY / WAYLAND_DISPLAY を除き、専用 `XDG_RUNTIME_DIR`
    `XDG_CONFIG_HOME=<home>/config` `HOME=<home>` `DBUS_SESSION_BUS_ADDRESS` を足した環境。
    `inside=True` で `WAYLAND_DISPLAY` も付く。**session 内で何か起動するときは必ずこれを渡す**。
  - `__enter__` — runtime dir と `<home>/config/<compositor>/autostart`(空)を作り、
    `_write_compositor_config()`、session bus、compositor(`WLR_BACKENDS=headless`
    `WLR_LIBINPUT_NO_DEVICES=1` `WLR_HEADLESS_OUTPUTS=1` `WLR_RENDERER=pixman`)、`wayhintd -v` を起動し、
    socket を待ち、初回の `show` / `hide` を 1 往復して renderer の初期化を済ませる。
  - `__exit__` — 起動した全プロセスを **process group ごと** SIGTERM → 5 秒待ち → SIGKILL、
    runtime dir と home を削除。**`_procs` に登録した Popen だけが後片付けされる**。
  - `press(*keys)` — `wtype -M k1 -M k2 -k last -m k2 -m k1`(修飾を先に押し逆順に離す)。
  - `wayhint(*args) -> str` — `.venv/bin/wayhint <args>` を session 内で実行し stdout を返す。
    非 0 なら RuntimeError。
  - `toplevel(app_id) -> Popen` — `foot --app-id=<app_id> --override=cursor.blink=no sh -c "sleep 3600"`
    を起動し、`wayhint context` に app_id が出るまで待つ。**foot と `sleep` 固定**(stub は渡せない)。
  - `grab(path, settle=0.3) -> Path` — `settle` 秒待って `grim -o HEADLESS-1 <path>`。
  - `overlay_box(work) -> box | None` — hide → 撮影 → show → 差分が出るまで poll。
  - `a11y_names(role) -> list[str]` — `wayhint` frame 配下で role が一致するノードの name。
    **読み取りのみ**(Action は無い)。
  - `log_tail(lines=25) -> str`。
  - 非公開だが Phase B が差し替え・拡張する候補: `_write_compositor_config()`(rc.xml。keybind 1 個・
    labwc 限定)、`_spawn(argv, env)`(`_procs` 登録 + start_new_session + stdout を log へ)、
    `_signal_group`、`_wait_for(path, what)`、`_start_bus`、`_A11Y_PROBE`(文字列の python script)。

**Phase B で足す必要があるもの**(既存 method の挙動は変えず、追加で入れる。check-gui 5 本が
基準):
- 複数 keybind(`W-h` と `W-C-h`)と `<windowRules>` を rc.xml に書く手段(引数追加か、rc.xml 断片の
  差し込み)。
- `<home>/config/gtk-4.0/settings.ini` に `[Settings]\ngtk-cursor-blink=false`(overlay 側の
  entry の cursor 点滅停止。Phase A の probe で書いていた)。
- 任意 argv の toplevel 起動(`_spawn` 相当を公開し `_procs` に登録して後片付けに乗せる。
  stdout / stderr は DEVNULL でよい)。
- AT-SPI の Action 実行(role `button` × name で探し `do_action(0)`)と、role / name / action の
  dump(`wait_for` 用)。probe script の骨組みは `_A11Y_PROBE` と同じ書き方でよい。
- runtime dir の名前(`wh-t<pid>` 固定)。テストと同時に走らせないなら共用でもよいが、
  区別したいなら接頭を引数にする。**AF_UNIX の 108 byte 制限のため短く**。
- fixtures を temp にコピーして `config_dir` に渡す(session は `config_dir` を読み書きする)。

## 4. 環境依存の具体値

- output: 既定 1280×720、scale 1、名前 `HEADLESS-1`、変更は `wlr-randr --output HEADLESS-1 --custom-mode WxH`。
- stub の argv[0]: shebang script のまま(`#!/usr/bin/env python3`)。`_name()` が interpreter の次を
  採る。`exec -a` 不要。foreground の子を作らない。
- foot: `demo/bin/foot-wayhint` wrapper、`--override=cursor.blink=no --override=cursor.unfocused-style=unchanged`、
  font は `--override=font=Noto Sans Mono:size=10` のように明示(未実測。推測: foot の `font` は
  fontconfig 名)。
- 窓の固定: labwc `windowRules` の `MoveTo` / `ResizeTo`(§1-3)。
- 必要 apt package: **ffmpeg(未導入)**、wtype、grim、imagemagick、foot、labwc、fonts-noto-cjk、
  fonts-noto-mono、wlr-randr(任意)。
- font: `Noto Sans CJK JP`(fonts-noto-cjk)、`Noto Sans Mono`(fonts-noto-mono)。既定の
  sans-serif / monospace は VL ゴシックなので明示必須。
- version: wtype 0.4、grim 1.5.0、ffmpeg 無し(候補 7:8.1.2)、ImageMagick 7.1.2-31、foot 1.28.0、
  labwc 0.20.2 / wlroots 0.20.2、GTK 4.22.4、at-spi2-core 2.62.0、gtk4-layer-shell 1.3.0、
  Python 3.14.7(`.venv`)。
- locale: `LANG=ja_JP.UTF-8`。`appearance.language` を明示しないと ja になる。
- AT-SPI: ボタン role `button`、action `click`、frame name `wayhint`。
- ボタン名(en / ja): Search/検索、Copy/コピー、Edit in editor/エディタで編集、Edit/編集、Close/閉じる。
  検索中は Search が `Done`(ja は `src/wayhint/i18n.py` を参照)。
- daemon log の判定行: `keyboard: mode=... visible=... grab=...`、`overlay open on workspace ...: sheet <id>`、
  `hotkey from another window: replacing <a> with <b>`、`reloaded <file>: ok`。

## 5. Phase B が触ってはいけないもの

- `src/wayhint/` 全部(禁止事項どおり)。
- `tools/headless.py` の既存挙動: `__exit__` の group kill と削除順、`env()` の DISPLAY /
  WAYLAND_DISPLAY 除去、`autostart` を空にする処理(ユーザーの labwc autostart 巻き込み対策、
  STATUS 2026-09-20 に事故の記録)、`runtime` の短い名前、`grab` の settle 既定、`overlay_box` の
  poll、`_A11Y_PROBE` の frame 特定。**追加はしてよいが変更・削除はしない**。
- `tests/headless.py` と `tests/test_gui_headless.py`(demo の依存を持ち込まない。ffmpeg / foot の
  有無で skip が増えてはいけない)。
- `./scripts/check` / `./scripts/check-gui` の所要時間と件数(§6)。
- `demo/fixtures/` を session に直接渡さない(編集モードと `write` で書き換わる。§1-6)。
- `press` → `type` の間に `wait_for` を省かない(§1-4)。
- wtype の無い環境で `key:` を CLI に置き換えない(決定事項どおり fail)。

## 6. `./scripts/check` / `./scripts/check-gui` の Phase A 終了時点の結果

| command | 結果 |
|---|---|
| `./scripts/check` | exit 0。ruff check / format OK、compileall OK、**359 tests OK(skipped=6)**、unittest 1.5 秒、全体 1.9 秒 |
| `./scripts/check-gui` | **5 tests OK**、22.2 秒(A-1 時点も 22.2 秒。STATUS 0030 の 16.4 秒より遅いのは負荷差と推測) |

実行後に labwc の孤児・`/run/user/1000/wh-*`・`/tmp/wayhint-*` は残らなかった(probe 5 本と
check-gui 2 回のあと確認)。

補足: clean tree の `./scripts/check` は Phase A 開始時点で ruff I001(`tests/test_daemon_window.py`)により
exit 1 だった。ab0b057 で修正済。
