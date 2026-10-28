# Contributing

## Before committing

- Keep a change focused on one concern.
- Do not commit `.env` files, logs, SQLite databases, stored PDFs, Chroma data, build output or temporary files.
- Run `npm run check` and `npm test` from the root. Run `npm run test:backend` for API/storage changes and the isolated browser suite for UI/lifecycle changes; see [testing](docs/TESTING.md).
- Check `git diff --check` and review `git status` before staging.
- Stage reviewed paths explicitly, never `.env` files or local n8n exports.
- After staging, run `python scripts/check_git_index.py` and `git diff --cached --check` against the exact index before committing. The check rejects runtime artifacts and recognizable secrets, but is not an exhaustive secret scan.

## Commit style

Use concise, imperative commits:

```text
feat: add evidence timeline
fix: preserve retrieved evidence in ask responses
docs: clarify local authentication setup
```

## Pull requests

Describe the user impact, verification performed and any configuration changes. Include screenshots for visible workspace changes and never include production credentials in descriptions, logs or images.

Keep transport independent of UI, and domain/storage independent of HTTP
composition. The working-tree check resolves local imports, rejects cycles
and checks documentation targets. It is a boundary convention, not a complete
compiler or secret scanner. Add a small architecture decision when changing
ownership, persistence, trust boundaries or delivery semantics; see the
[first decision](docs/engineering/adr/0001-adapt-patterns-not-service-topology.md).

Do not retry a timed-out mutation unless its actual result is known. New
async work needs cancellation and stale-response tests. New evidence sources
need tenant isolation and malformed/unavailable-output tests. Do not treat
mocked browser success as real authentication, scanner or model verification.
