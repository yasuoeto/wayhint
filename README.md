# wayhint

Wayfire 上で hotkey 一発、いつも同じ場所(既定: 画面右上)に、現在使っているアプリ ── Herdr の中なら
focused pane の foreground process(Claude Code / Codex …)── に応じた自分用チートシートを
overlay 表示する。YAML で育てる context-aware personal cheatsheet。

- 通常表示中は keyboard focus を奪わない(検索を明示的に開始したときだけ入力を受ける)
- hint は `~/.config/wayhint/hints/*.yaml`。overlay の Edit ボタンから外部 editor で該当行を開く
- YAML 内の command は表示・copy のみ。実行はしない

要件は `docs/PRODUCT.md`、構造は `docs/DESIGN.md`、経緯は `docs/DECISIONS.md`。
以下の節は実装が進んだ時点で埋める: install / Wayfire IPC setup / Wayfire hotkey setup /
autostart / config location / hint 追加方法 / editor 変更方法 / troubleshooting。

## Quick start

```sh
./scripts/setup    # prepare a working copy
./scripts/check    # the only validation entry point
```

## Layout

| Path | Contents |
|---|---|
| `STATUS.md` | what is done, what is left, what the machine looks like |
| `src/` | implementation |
| `tests/` | tests |
| `docs/PRODUCT.md` | requirements |
| `docs/DESIGN.md` | design |
| `docs/DECISIONS.md` | decision log |
| `scripts/` | `setup`, `check`, and repository-specific agent hooks |
| `.agents/skills/` | skills shared across agents |
| `.claude/`, `.codex/` | per-vendor adapter settings (do not edit by hand) |

## Working with agents

`AGENTS.md` holds the shared instructions. `CLAUDE.md` points at it. Vendor-specific
configuration is confined to `.claude/` and `.codex/`; shared hooks are registered once at user
scope, not in this repository.
