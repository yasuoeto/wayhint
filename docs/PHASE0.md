# wayhint — Phase 0: 依存確認(設計書 §78)

実施日: 2026-09-16、ホスト mifuyu(Debian, Linux 7.1.12)。

| 項目 | 結果 | 備考 |
|---|---|---|
| Wayfire | **0.10.0 (wlroots 0.19.3) インストール済・未起動** | 現セッションは labwc。`~/.config/wayfire.ini` の `[core] plugins` に `ipc`, `ipc-rules` あり。IPC socket の実在は Wayfire 起動時に確認要 |
| Python | 3.14.7 (`/usr/bin/python3`) | venv も 3.14.7 |
| GTK4 | 4.22.4 (`gir1.2-gtk-4.0`, `libgtk-4-1`) | `gi.require_version("Gtk","4.0")` OK |
| PyGObject | 3.57.1 (`python3-gi`) | system site-packages。venv からは `--system-site-packages` か `PyGObject` wheel が必要 |
| gtk4-layer-shell | 1.3.0(2026-09-16 導入) | apt: `libgtk4-layer-shell0` + `gir1.2-gtk4layershell-1.0`。`gi.require_version("Gtk4LayerShell","1.0")` OK |
| PyWayfire | 4.0(2026-09-16 `.venv` に導入) | PyPI 名は `wayfire`。`pywayfire` という名前では取れない |
| ruamel.yaml | 0.19.1(2026-09-16 `.venv` に導入) | apt には無し(`python3-ruyaml` は別 fork) |
| Herdr | 0.8.2 (`~/.local/bin/herdr`) | 下記 |
| gvim | Vim 9.2 (`/usr/bin/gvim` → alternatives) | OK |

## Herdr CLI の実際の形

- `herdr pane current` → JSON `{"result":{"pane":{pane_id, focused, workspace_id, agent, agent_status, terminal_title, terminal_title_stripped, cwd, foreground_cwd, ...}}}`。focused pane を返す。
- `herdr pane process-info --current` / `--pane <ID>` → `{"result":{"process_info":{pane_id, shell_pid, foreground_process_group_id, foreground_processes:[{pid,name,argv,cmdline,cwd}]}}}`。
- **注意**: `--pane`/`--current` を省くと呼び出し元 shell の pane(必ずしも focused ではない)が返る。adapter は必ず `--current` か `pane current` の `pane_id` を渡す。
- `agent` / `terminal_title` フィールドも返るが、V1 は設計書 §15 どおり `foreground_processes` のみで判定する(title は screen scraping に近い)。

## 実装前に必要な導入(要 sudo / ネットワーク)

```sh
sudo apt install libgtk4-layer-shell0 gir1.2-gtk4layershell-1.0
```

venv 側(`scripts/setup` を更新して自動化する):

```sh
python3 -m venv --system-site-packages .venv   # PyGObject/GTK を共有
.venv/bin/pip install wayfire ruamel.yaml
```

## 未確認(Wayfire セッションでのみ確認可能)

- `WAYFIRE_SOCKET` の実在と PyWayfire での active view / output 取得。
- layer-shell `ON_DEMAND` keyboard mode の挙動(§47)。
- 実機テスト §69–§73 全般。
