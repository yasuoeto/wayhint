# wayhint

Wayland(wlroots 系 compositor: labwc / Wayfire など)上で hotkey 一発、いつも同じ場所(既定: 画面右上)に、現在使っているアプリ ── Herdr の中なら
focused pane の foreground process(Claude Code / Codex …)── に応じた自分用チートシートを
overlay 表示する。YAML で育てる context-aware personal cheatsheet。

- 通常表示中は keyboard focus を奪わない(検索を明示的に開始したときだけ入力を受ける)
- hint は `~/.config/wayhint/hints/*.yaml`。overlay の Edit ボタンから外部 editor で該当行を開く
- YAML 内の command は表示・copy のみ。実行はしない

要件は `docs/PRODUCT.md`、構造は `docs/DESIGN.md`、経緯は `docs/DECISIONS.md`、進捗は `STATUS.md`。

## Install

依存: Python 3.11+、GTK4 + PyGObject、gtk4-layer-shell(typelib 込み)、`wlr-foreign-toplevel-management` と `wlr-layer-shell` を
提供する Wayland compositor(labwc、Wayfire は `foreign-toplevel` plugin 有効時)、任意で Herdr と gvim。Debian/sid の場合:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0
```

```sh
git clone <this repo> ~/work/tools/wayhint && cd ~/work/tools/wayhint
./scripts/setup                 # .venv (system site-packages 共有) + ruamel.yaml + pywayland (+ PyWayfire)
.venv/bin/pip install -e .      # wayhint / wayhintd コマンドを .venv/bin に置く
./scripts/check                 # lint + unit tests
```

## Config location

`$XDG_CONFIG_HOME/wayhint/`(既定 `~/.config/wayhint/`):

| Path | Contents |
|---|---|
| `config.yaml` | overlay 位置・サイズ、editor、parent tags 等。無ければ全て既定値 |
| `style.css` | 任意。GTK CSS で見た目を上書き(class 名は `src/wayhint/ui/style.py`) |
| `hints/*.yaml` | sheet 1 ファイル 1 枚。ファイル名順に読む |

雛形は `examples/`。`cp -r examples/. ~/.config/wayhint/` で始められる。schema は
`docs/DESIGN.md` の Data model。書いたら `wayhint validate` で確認する(問題があれば exit 1)。

## Compositor setup

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

## Adding hints

1. `hints/` に新しい YAML を置く(または既存の sheet に hint を足す)。
2. daemon は保存を検知して自動 reload する(overlay を閉じる必要はない)。壊れた YAML のときは
   直前の正常版を表示し続け、overlay 上部に `⚠ YAML error file:line: message` が出る。
3. overlay の **Edit sheet** / **Edit hint** で editor が該当ファイル・該当行を開く。

## Changing the editor

`config.yaml` の `editor.command` は argv の list。placeholder は `{file}` `{line}` `{hint_id}`。
shell を通らないので引用符やパイプは書けない。

```yaml
editor:
  command: [code, --goto, "{file}:{line}"]
```

## Troubleshooting

| 症状 | 確認 |
|---|---|
| `wayhint: wayhintd is not running` | `wayhintd -v` を前景で起動してログを見る。socket は `$XDG_RUNTIME_DIR/wayhint.sock` |
| `⚠ compositor does not provide wlr-foreign-toplevel-management` | labwc なら出ない。Wayfire は `[core] plugins` に `foreign-toplevel`、または `ipc` を入れて IPC fallback に任せる |
| `⚠ Wayfire IPC unavailable` | `context.backend: wayfire` 固定時のみ。`echo $WAYFIRE_SOCKET`、`[core] plugins` に `ipc` |
| `this Wayland session has no layer-shell support` | `gir1.2-gtk4layershell-1.0` が入っているか。X11/Xwayland では動かない |
| Herdr の中で親 sheet しか出ない | `herdr pane process-info --current` の `foreground_processes` と `argv_regex` を照合 |
| 検索後にキー入力が元アプリに戻らない | Search を終える(Done / Esc)と keyboard_mode は必ず none に戻る。focus 復帰は foreign-toplevel `activate`(wayfire backend では IPC `set_focus`)。同じ app_id の window が複数あり title が変わっていると復帰先を決められない。`wayhintd -v` に `could not return focus` が出るか |

## 実機チェックリスト(設計書 §69–§73、手動)

labwc と Wayfire それぞれのセッションで実施し、結果は `STATUS.md` に日付付きで記録する。

- [ ] T1 hotkey で右上に表示、元アプリへの入力が続く(keyboard grab なし)
- [ ] T2 同じ hotkey で非表示(toggle)
- [ ] T3 別 output 上のアプリから起動 → そのアプリの output に出る
- [ ] T4 sheet の `display.output` override が効く
- [ ] T5 `width: 30%` / `height: 60%` が対象 output の logical size 基準
- [ ] T6 Search 中だけ入力を受け、Done/Esc 後に grab が残らず前の view に focus が戻る
- [ ] T7 Edit sheet で gvim が sheet を開く、Edit hint で該当行に jump
- [ ] T8 Herdr で bash → Herdr hints、`claude` → Claude sheet + tag 付き Herdr hints
- [ ] T9 Herdr で unknown process → Herdr hints のみ
- [ ] T10 表示中に YAML を編集 → 閉じずに更新
- [ ] T11 YAML を壊す → crash せず last-known-good + `⚠ YAML error`、直すと復帰

## Layout

| Path | Contents |
|---|---|
| `STATUS.md` | what is done, what is left, what the machine looks like |
| `src/` | implementation |
| `tests/` | tests |
| `docs/PRODUCT.md` | requirements |
| `docs/DESIGN.md` | design |
| `docs/DECISIONS.md` | decision log |
| `examples/` | config.yaml と sheet の雛形 |
| `scripts/` | `setup`, `check`, and repository-specific agent hooks |
| `.agents/skills/` | skills shared across agents |
| `.claude/`, `.codex/` | per-vendor adapter settings (do not edit by hand) |

## Working with agents

`AGENTS.md` holds the shared instructions. `CLAUDE.md` points at it. Vendor-specific
configuration is confined to `.claude/` and `.codex/`; shared hooks are registered once at user
scope, not in this repository.
