# HANDOFF — 紹介動画(showcase `herdr`)C-A → C-B0 / C-B

C-A(Fable、2026-09-21)の実測結果。**C-B は Herdr 周りをこのファイルだけで知る**。本プロンプトと
食い違えば実測に基づくこのファイルが正。C-B 完了時に内容を `docs/DECISIONS.md` 0032 /
`docs/DESIGN.md` / `demo/README.md` へ取り込み、このファイルは削除する。

試行 script は scratchpad(`/tmp/claude-1000/.../scratchpad/p12.py` `p13.py`)に置き、repo には
残していない。すべて `tools/headless.py` の `HeadlessSession` を継承した labwc headless session
(1280×720)で測った。**製品コード(`src/wayhint/`)と `tools/demo/` は変更していない。**

前提の欠落: `demo/showcases/herdr/01_herdr_storyboard.md`(ユーザーが置く台本)は C-A 終了時点で
**存在しない**。C-B0 はこれが無いと 2 番(step 一覧)を起こせないので、無ければ先にユーザーへ求める。

## 1. Herdr の版と、headless session 内での起動方法

- `herdr 0.8.2`(`~/.local/bin/herdr`、static-pie の単一 binary、channel stable、protocol 20)。
  client / server 構成で、`herdr` を実行した client が **server を detached daemon として自動起動**
  する(`status --json` の `capabilities.detached_server_daemon: true`)。session 内では 2 プロセス
  (`herdr` = foot の子、`herdr server` = daemon 化して**プロセスグループを抜ける**)になる。
- **wrapper は不要**。ただし Herdr 経路は窓の app_id に `herdr` が含まれることで選ばれる
  (`docs/TERMINALS.md`)ので、0031 の `foot-wayhint`(`.p<pid>` 方式)ではなく app_id を直接指定する。
  実測に使った argv(cwd を固定するため `env -C` を前置。shell は介さない):
  ```
  env -C /tmp/wayhint-demo-probe foot --app-id=foot-herdr --title=Herdr
      --override=cursor.blink=no --override=cursor.unfocused-style=unchanged herdr
  ```
  起動後 1〜2 秒で pane ができる。`herdr pane list` を session env で poll し、rc=0 かつ出力に
  `"panes"` が含まれたら準備完了とした。直後の `wayhint context` は
  `active_sheet=herdr parent_context=herdr desktop_app=foot-herdr process={'name': 'sh', ...} chain=['HerdrContextProvider']`。
- **session の環境変数に 2 つの処置が必須**(C-B が `tools/demo/session.py` か `tools/headless.py`
  で行う。現状の `HeadlessSession.env()` は DISPLAY / WAYLAND_DISPLAY しか除いていない):
  1. **`HERDR_*` をすべて除く**。ユーザーの shell(この作業自体が Herdr の pane 内で走っている)には
     `HERDR_SOCKET_PATH=/home/<user>/.config/herdr/herdr.sock` などが入っており、そのまま継承すると
     session 内の `herdr` client は**実 server に接続する**。実測: 隔離した HOME でも
     `HERDR_SOCKET_PATH` を残して `herdr status --json` すると `socket: /home/<user>/.config/herdr/herdr.sock, running: True`、
     外すと `socket: <HOME>/config/herdr/herdr.sock, running: False`。adapter 自身の
     `_herdr_env`(0028)は daemon → herdr の呼び出しだけを守り、foot → herdr は守らない。
  2. **`PATH` の先頭に `demo/bin` を足す**。pane に流し込むコマンドは画面に echo される(`$ claude`)
     ので、絶対パスを打つと実パスが frame に写る。PATH に載せて `claude` / `codex` と打つ。
- Herdr の設定ディレクトリは **`$XDG_CONFIG_HOME/herdr/`、無ければ `$HOME/.config/herdr/`**
  (`herdr --help` の `Config:` 行で確認。`HERDR_CONFIG_PATH` は config ファイルの場所だけを変え、
  socket / log の場所は変えない)。socket(`herdr.sock` `herdr-client.sock`)と log
  (`herdr-server.log` `herdr-client.log`)もその中。session の HOME / XDG_CONFIG_HOME を与えれば
  すべて session 内に閉じる。`~/.local/state/herdr` 相当は session 内には作られなかった。

## 2. pane 作成・切替に実際に使った command(argv そのまま。すべて session env で実行)

| 目的 | argv | 返り(JSON `result` の要点) |
|---|---|---|
| pane 一覧 | `herdr pane list` | `panes: [{pane_id: "w1:p1", focused: true, cwd, ...}]` |
| focus 中の pane | `herdr pane current` | `pane: {pane_id, focused, cwd, foreground_cwd, agent_status, revision, scroll, ...}` |
| pane の process | `herdr pane process-info --pane w1:p1` | 3 番 |
| pane で command を打つ | `herdr pane run w1:p1 claude` | stdout 空。pane の shell に `claude` + Enter を送る(`$ claude` と echo される) |
| tab を作る | `herdr tab create --focus` | `root_pane: {pane_id: "w1:p2", ...}`(`prompt_new_tab_name=false` のとき名前入力なし) |
| tab 一覧 | `herdr tab list` | `tabs: [{tab_id: "w1:t1", label: "1", focused}, {tab_id: "w1:t2", label: "2", ...}]` |
| tab 切替 | `herdr tab focus w1:t1` | `tab: {focused: true, label: "1", number: 1, ...}` |
| pane 分割 | `herdr pane split --pane w1:p1 --direction right --focus` | `pane: {pane_id: "w1:p2", ...}` |
| 分割 pane の focus 移動 | `herdr pane focus --direction left --current` / `--direction right --current` | `focus: {changed: true, focused_pane_id, layout}` |
| workspace を作る | `herdr workspace create --focus --cwd /tmp/wayhint-demo-probe` | `root_pane: {pane_id: "w2:p1"}` |
| workspace 一覧 / 切替 | `herdr workspace list` / `herdr workspace focus w1` | `workspaces: [{workspace_id: "w1", label: "wayhint-demo-probe", focused}]` |
| pane を閉じる | `herdr pane close w1:p2` | `{type: "ok"}` |
| 状態 | `herdr status --json` | `server.socket`(隔離確認に使う) |
| 後片付け | `herdr server stop` | stdout 空。**session 終了前に必ず呼ぶ**(6 番) |

ID は新規 state から決定的に振られる(`w1:p1` → `w1:t1`、次の tab / pane が `w1:p2` `w1:t2`、
次の workspace が `w2:p1`)。scenario に ID を直書きしてよいが、返り値から読む方が安全。
`pane run` は「shell が prompt を出してから」でないと落ちる文字が出るので、実測では
`process-info` の foreground が `sh` になるのを待ってから送った。

## 3. `HerdrAdapter` が現在の製品実装で使った Herdr CLI 経路

`src/wayhint/context/herdr.py`(0028 後)は **`herdr pane current` → `herdr pane process-info --pane <pane_id>`**
の 2 回で、環境は `HERDR_*` を除いたもの、各 call の timeout 0.75 秒・lookup 全体 1.5 秒。
`pane current` が `focused: false` を返したときだけの保険経路(`pane list`)には**今回も一度も落ちていない**。
出力形式は `docs/PHASE0.md` と一致:

```
herdr pane current
  {"result":{"pane":{"pane_id":"w1:p1","focused":true,"cwd":"/tmp/wayhint-demo-probe",
             "foreground_cwd":"...","agent_status":"unknown","revision":0,"scroll":{...},...}}}
herdr pane process-info --pane w1:p1
  {"result":{"process_info":{"foreground_process_group_id":2288828,
     "foreground_processes":[{"pid":...,"name":"python3","argv":["python3","/…/bin/claude"],
                              "cmdline":"python3 /…/bin/claude","cwd":"..."}]}}}
```

**Herdr の `name` は kernel の comm(実行ファイル名)で、shebang script の stub では `python3` になる。**
sheet の照合は argv の basename も見る(`matcher.process_candidates`)ので `active_sheet=claude-code`
にはなるが、overlay の context 行(`foot-herdr · python3 · HEADLESS-1`)と `wait_for` の `process_name`
にはこの名前が出る。stub が `prctl(PR_SET_NAME, b"claude")`(ctypes、`os.path.basename(__file__)`)
を呼ぶと Herdr は**少し遅れて**(次の process 再読込で)`name: claude` を返し、context 行も
`foot-herdr · claude · HEADLESS-1` になった。実測では `pane run` 直後の `process-info` は `python3`、
その数百 ms 後の `wayhint context` は `claude`。→ stub には PR_SET_NAME を入れ、scenario の待ちは
`active_sheet` で書く(`process_name: claude` も通るが、遅れの分だけ長く待つ)。

## 4. Claude Code pane → Codex pane 切替時の `wayhint context`

session 内で claude stub を `w1:p1`、codex stub を `w1:t2` の pane `w1:p2` で動かし、`herdr tab focus`
で往復したときの出力(`wayhint context` そのまま。PR_SET_NAME 無しの stub):

```
tab focus w1:t1 →
active_sheet=claude-code parent_context=herdr desktop_app=foot-herdr process={'name': 'python3', 'argv_basenames': ['python3', 'claude']} include=['wm'] chain=['HerdrContextProvider']
tab focus w1:t2 →
active_sheet=codex parent_context=herdr desktop_app=foot-herdr process={'name': 'python3', 'argv_basenames': ['python3', 'codex']} include=['wm'] chain=['HerdrContextProvider']
```

PR_SET_NAME 付きの stub では `process={'name': 'claude', ...}` / `{'name': 'codex', ...}`。
`pane split` で横に並べて `pane focus --direction left|right` で往復しても同じ 2 行が交互に出る。
overlay を出したままの切替は daemon の `toggle_action` → `replace` 経路(0031 の場面④と同じ)で、
AT-SPI の header label は `Herdr › Claude Code` ↔ `Herdr › Codex`。
sheet は `examples/hints/en/` の `herdr.yaml`(親、`app_id_regex: ["herdr"]`)、`claude-code.yaml`
(`argv_regex: ["^claude$"]`)、`codex.yaml`(`argv_regex: ["^codex$"]`)を使った。

## 5. `HERDR_*` サニタイズが demo session でも効いていたか

- adapter 側(daemon → `herdr`): `_herdr_env` が効いている。session 内の daemon は保険経路に落ちず、
  focus 中の pane を毎回正しく答えた(4 番)。
- session 側(foot → `herdr` client): **`HeadlessSession.env()` は `HERDR_*` を除かない**ので、probe では
  `env()` を override して除いた。除かない場合の危険は 1 番の実測どおり(client が実 server に繋がる)。
  session 内の `herdr` / `herdr server` の `/proc/<pid>/environ` を読み、`HERDR_*` は Herdr 自身が
  付けた `HERDR_STARTUP_CWD` だけだったことを確認した。

## 6. 隔離の確認結果と、session 内に生成した最小の Herdr 設定・state

`strace` は未導入。代わりに次の 4 点で確認し、2 回の独立 session でいずれも問題なし:

1. session 内の `herdr` と `herdr server` の `/proc/<pid>/environ`: `HOME` `XDG_CONFIG_HOME` `XDG_RUNTIME_DIR`
   がすべて session のもの、`HERDR_*` は `HERDR_STARTUP_CWD` のみ。
2. `lsof -p <pid> -Fn`: 実 HOME 配下で開いていたのは binary `~/.local/bin/herdr` だけ。開いていた
   ファイルは `<home>/config/herdr/{herdr.sock,herdr-client.sock,herdr-server.log,herdr-client.log}`。
3. 実ユーザーの `~/.config/herdr/` と `~/.local/state/herdr/` の全ファイルの size+mtime を実行前後で比較:
   **変化なし**。`pgrep -a herdr` の baseline(実 server pid 42863 と実 client)は実行後も同じで、
   実 `herdr status --json` の socket も `/home/<user>/.config/herdr/herdr.sock` のまま。
4. session env の `herdr status --json` は `server.socket = <home>/config/herdr/herdr.sock`。

生成した最小設定 `<XDG_CONFIG_HOME>/herdr/config.toml`(session 起動前に書く。これ以外は無し。
Herdr が自分で `.plugins.lock` と log と socket を足す。`session.json` は作られなかった):

```toml
onboarding = false            # 初回オンボーディング UI を出さない
[update]
version_check = false         # herdr.dev への版チェックを止める
manifest_check = false        # agent-detection manifest の取得を止める
[ui]
prompt_new_tab_name = false   # `tab create` で名前入力を出さない
[terminal]
default_shell = "/bin/sh"     # pane の shell を固定(prompt は `$ `。ユーザーの zsh 設定を読まない)
```

**追加で入れるべき 1 行**(probe では未使用、7 番の理由): `[ui]` に `window_title = "{workspace}"`。
既定 `"{hostname}: {workspace}"` は foot の title(labwc の SSD title bar に出る)を
`mifuyu: wayhint-demo-probe` にし、**ホスト名が frame に写る**。既定 config のコメントに token 一覧
(`{hostname}` `{workspace}` `{tab}` `{pane}` `{terminal_title}`)がある。

**後片付け**: `herdr server` は daemon 化して session のプロセスグループを抜けるため、
`HeadlessSession.__exit__` の group kill では死なない。probe を途中で落としたとき、HOME が消えた後も
`herdr server`(pid 2286177)が残った(手で SIGTERM した)。**session を閉じる前に session env で
`herdr server stop` を呼ぶ**と、直後に `pgrep` から消え、孤児は残らなかった(2 session とも)。
保険として、終了後に `herdr server` の `/proc/<pid>/environ` の `HOME` が session の home と一致する
pid があれば SIGTERM する処理を C-B で入れること。実 server(pid 42863)を pid や `pkill -f herdr` で
巻き込まない。**順序も重要**: 孤児 server を後から SIGTERM すると、終了時に `session.json`(784 byte)を
`<home>/config/herdr/` に書き、`rmtree` 済みの session home を作り直す(実測: 中断 probe の home が
`session.json` 1 個だけの状態で復活した)。`herdr server stop` → session の `__exit__`(rmtree)の順なら
起きない。保険で SIGTERM したときは、その後にもう一度 home を消す。

## 7. 主役場面の再現性

独立した demo session を 2 回立て、同じ手順(herdr 起動 → claude stub → tab 作成 → codex stub →
tab 往復 → `wayhint show`)の最後の frame(Codex tab が focus、overlay `Herdr › Codex`)を比べた:
**`compare -metric AE` = 0**(`0 (0)`、差分 box `0x0`)。同一 session 内で続けて撮った 2 枚も 0。
Herdr の UI に時刻・PID・ランダム ID は写っていない。写る可変要素と、AE=0 にするために効いた設定:

| 写るもの | 実測値 | 固定に効いたもの |
|---|---|---|
| workspace 名(sidebar `spaces`、agents 欄) | `wayhint-demo-probe` = cwd の basename | `env -C <固定 cwd>` で foot を起動(`mkdtemp` の名前だと毎回変わる) |
| 窓 title(SSD) | `mifuyu: wayhint-demo-probe` | このマシン内では一定だが**ホスト名**。`window_title = "{workspace}"` で除く(未実測) |
| tab label | `1` `2` | `prompt_new_tab_name = false`(生成名) |
| pane の shell prompt と echo | `$ claude` | `default_shell = "/bin/sh"`、PATH に `demo/bin` |
| agents 欄 | `wayhint-demo-probe · 1 claude` / `· 2 codex` | Herdr が stub を agent として検出して並べる(名前は決定的) |
| overlay context 行 | `foot-herdr · python3 · HEADLESS-1` | stub の PR_SET_NAME で `claude` / `codex` に(3 番) |
| pane ID / tab ID | `w1:p1` `w1:t1` `w1:p2` `w1:t2` | 新規 state から決定的 |

**製品コードの変更は不要。** 未計測の可変要素: Herdr の agents 欄が `working` / `idle` 状態で経過時間を
表示するか(stub は `agent_status: unknown` のままで何も出なかった)。長い場面では frame ごとに
確認が要る(`--keep` で 2 回撮って全 frame 比較)。

## 8. `herdr:` action で許可する subcommand(2 番の実測から)

```
pane list · pane current · pane process-info · pane run · pane split · pane focus · pane close
tab create · tab list · tab focus
workspace create · workspace list · workspace focus
status · server stop
```

許可 list は **subcommand(先頭 2 語、`status` `server stop` は固定)** で判定し、引数は argv の
配列としてそのまま渡す(shell 無し)。上の表に無い subcommand(`agent *`、`pane send-keys`、
`session *`、`update`、`--remote` 等)は list に入れない。`server stop` は scenario からではなく
session の後片付けだけで使うなら list から外してもよい。

## 9. C-B が再調査してはいけない事項と、触ると壊れやすい箇所

- 上の 1〜8 は再調査しない。特に「Herdr が headless で動くか」「隔離できるか」「AE=0 になるか」は
  済んでいる。合わないと分かったら「HANDOFF の N 番が実際と異なる」と報告して停止。
- **壊れやすい順**:
  1. session env の `HERDR_*` 除去を忘れる → 実 server に接続(1 番)。demo の session env を作る
     1 か所で除き、`herdr` を呼ぶ経路(`herdr:` action、後片付け、`wait_for`)はすべてその env を使う。
  2. `herdr server stop` を session 終了**前**に呼ばない → 孤児 server(6 番)。
  3. app_id を `foot.p<pid>` にすると `ProcAdapter` 経路に乗り、Herdr が `herdr` という
     プロセスとして見えるだけで sheet が出ない(`docs/TERMINALS.md`)。`foot-herdr` 固定。
  4. `pane run` を shell の prompt 前に送ると文字が落ちる。`process-info` の foreground が `sh` に
     なるのを待つ(2 番)。
  5. cwd を固定しない / `window_title` を既定のままにする → frame にランダム名やホスト名(7 番)。
  6. stub の PR_SET_NAME を外す → context 行が `python3`(3 番)。stub は子プロセスを作らない(0031)。
- `tools/headless.py` の既存挙動(0031 の HANDOFF §5 と同じ): `__exit__` の group kill、`env()` の
  DISPLAY 除去、`autostart` の空ファイル、runtime dir の短い名前は変えない。`HERDR_*` 除去を
  `env()` に**足す**のは可(check-gui 5 本が基準)。
- `tests/`、`src/wayhint/`、`~/.config/herdr/`、実 `XDG_RUNTIME_DIR` に触らない。
- 0031 の HANDOFF の内容は `docs/DECISIONS.md` 0031 と `demo/README.md` に移してある(caret の 8 秒、
  固定 workspace パス、AT-SPI の `press` 後の待ち)。そちらも前提として有効。

## 10. `./scripts/check` / `./scripts/check-gui` の C-A 終了時点の結果

| command | 結果 |
|---|---|
| `./scripts/check` | exit 0。**359 tests OK(skipped=6)**、unittest 0.9 秒 |
| `./scripts/check-gui` | **5 tests OK**、16.6 秒 |

probe 終了後に `pgrep -a herdr` は baseline(実 server 42863、実 client)のみ、`/tmp/wayhint-headless-*`
`/run/user/1000/wh-*` は無し。probe 用の固定 cwd `/tmp/wayhint-demo-probe`(空ディレクトリ)は
C-A 終了時に削除した。
