# PRD-21318 · Code review

## Round 1 · 2026-11-04 · reviewed dev/PRD-21318 @ 4124227 (base 0aa8aea)

Verdict: approved
Status: frozen @ 4124227

### Scope

`git diff 0aa8aea...4124227` on `MSPbotsAIFramework/square-mcp` — the entire repository content, since this is a brand-new vendor MCP connector (30 files, 3668 insertions). Reviewed against the product design, tech design, `docs/tickets/PRD-21318.ac.json`, and the Self-test section in `docs/tickets/PRD-21318.md`, plus `references/REVIEW.md` and the vendor-mcp-development SOP (`~/.claude/skills/vendor-mcp-development/reference/vendor-mcp-development-sop.md`).

Independently re-verified in a fresh worktree (not just read from the Self-test section):
- `uv sync && uv run ruff check src tests` → `All checks passed!`
- `uv run ruff format --check src tests` → `19 files already formatted`
- `uv run pytest -v` → `30 passed in 1.72s`, same 30 test ids as the Self-test list
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` → no output (no Chinese)
- README "MSPbots Connector" section (lines 5–75) byte-for-byte diff against `vendor-mcp-development/reference/readme-connector-section.md` → identical (71 lines, `diff` exit 0)
- Secret-scan fallback regex → only placeholder values and code identifiers (`your_access_token_here`, `_token`, `token=`), no real credential
- README "Tool List" lists all 12 registered tools; `git status --short` in the worktree is clean

### Findings

No must-fix. One already-disclosed item, confirmed and accepted as-is:

1. [suggestion] `src/square_mcp/api_client.py:103` (inside `SquareClient.get`'s retry loop) — a new `httpx.AsyncClient()` is constructed on every retry attempt, not reused across the retries of one logical call. This is the same per-call-client pattern the tech design's "Reuse & cleanup" section and the Self-test's "Known gaps" section already flag as a pre-existing gap carried from the sibling `pax8-mcp` connector (no connection pooling), proposed as a connector-family-wide follow-up rather than a per-repo fix. Verified it is not a correctness bug: each client is scoped with `async with` and closed properly, bounded by `_MAX_RETRY_ATTEMPTS = 3` / `_MAX_TOTAL_SECONDS = 100.0` (confirmed by `tests/test_api_client.py::test_429_retries_honoring_retry_after_then_gives_up`, which asserts exactly 4 calls, no retry-loop runaway). No action needed on this ticket.

### Checklist spot-checks (SOP §14, vendor-mcp-development)

- Credentials read only from `X-Square-Access-Token` / `X-Square-Environment` headers via `contextvars`, reset in `finally` (`src/square_mcp/server.py:67-116`); never logged, never persisted; concurrent-isolation covered by `tests/test_middleware.py::test_concurrent_calls_do_not_leak_credentials_across_tenants` (two real concurrent requests through the ASGI app, mocked only at the outbound-HTTP boundary).
- Structured error envelope `{"error":{"code","message","retryable"}}` with `code` from the SOP §4 vocabulary, including `not_configured` for the (gateway-mode-unreachable-in-production, env-mode-only) no-credential path — this is in the SOP's own fixed table, not an undocumented addition.
- `readOnlyHint=True` on all 11 read tools, `readOnlyHint=False, destructiveHint=True, idempotentHint=True` on `square_create_refund` (`tests/test_tools.py::test_tools_list_snapshot` asserts both).
- Timeouts (5s connect / 30s read), bounded retry+backoff honoring `Retry-After` on `GET` only, POST never auto-retried (`tests/test_api_client.py::test_post_is_never_retried_on_5xx`).
- Dockerfile: multi-stage, non-root `square` user in the production stage, `curl` installed, `EXPOSE 8080`, `HEALTHCHECK` against `/health`; MCP app lifespan explicitly propagated to the outer Starlette app (`src/square_mcp/__main__.py:29-32`), avoiding the known "Task group is not initialized" `Mount()` pitfall.
- No migrations, no UI — not applicable to this connector.

### Conclusion

The connector matches its tech design, all 12 tools match AC1–AC24, the one destructive tool (`square_create_refund`) carries a caller-or-server idempotency key and the correct annotations, multi-tenant credential isolation is tested with real concurrent requests, and all gates reproduce independently. Approved; proceeding to merge into `main`, `/api/vendor-register`, and the connector wiki.
