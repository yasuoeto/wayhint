# wayhint

One sentence on what `wayhint` does.

## Quick start

```sh
./scripts/setup    # prepare a working copy
./scripts/check    # the only validation entry point
```

## Layout

| Path | Contents |
|---|---|
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
