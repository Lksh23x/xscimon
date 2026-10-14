# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (Python 3.13, pinned in .python-version)
uv sync --extra dev

# Load seed data (domains, skill prompts, accounts, keyword rules from seed/) — idempotent
uv run python scripts/seed.py

# Run the server (dev mode, auto-reload)
uvicorn xscimon.main:app --reload

# Managed server lifecycle (background, logs to server.log)
./start.sh      # starts server as background process
./stop.sh       # stops it
./restart.sh    # stop + start

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_api.py::test_domain_lifecycle

# Trigger the pipeline manually (server must be running)
curl -X POST localhost:8000/api/digest/run
# or use the "Run Pipeline" button in the Admin UI at /admin
```

Use `uv` for all Python commands, never `pip` directly.

## Architecture

xscimon is a research-focused X (Twitter) digest tool. It fetches posts from tracked accounts and keyword searches, scores them with Claude for relevance, and serves a daily digest via HTMX/Jinja2 templates backed by a FastAPI REST API.

**Layer contract** (enforced strictly):
- `models/` — SQLModel table definitions only. No logic.
- `api/` — thin route handlers: validate, delegate to a service, return a response. No business logic.
- `services/` — all business logic lives here. Services call repositories and adapters only.
- `repositories/` — SQLModel-based data access. All SQL stays here. One class per aggregate.
- `adapters/` — external service wrappers behind `Protocol` interfaces defined in `adapters/base.py`.

**Adapter pattern**: `XAPIAdapter`, `LLMAdapter`, and `EmailAdapter` are runtime-checkable `Protocol`s. The factory in `adapters/__init__.py` returns real adapters when env vars are present, mock adapters otherwise (`X_BEARER_TOKEN` absent → mock X API; `ANTHROPIC_API_KEY` absent → mock LLM; `SMTP_USER` absent → mock email). Tests always use mock adapters via `conftest.py` dependency overrides.

**Frontend**: `api/views.py` serves all HTML pages and HTMX partials using Jinja2 templates in `frontend/templates/`. The admin page at `/admin` provides live log search (HTMX), pipeline trigger, and API call tracking.

**Config split**: `config.yaml` holds infrastructure concerns (host, port, thresholds, ranking weights). All runtime settings (domains, accounts, keywords) live in SQLite and are managed via API.

**Seed data**: `seed/seed.yaml` lists domains and keyword rules; each domain's `skill_md` lives in `seed/skills/*.md` and its handles in `seed/accounts/*.csv` (same format as the UI's account import/export). `SeedService` loads them, upserting by name. Seed is configuration only: never add fetched posts, logs or favorites to it.

**Database**: SQLite at `data/xscimon.db`, managed by SQLModel. Schema migrations are lightweight `ALTER TABLE` calls in `database._apply_migrations()` — no migration framework.

**No scheduler**: the pipeline never runs unattended (removed to avoid unsupervised X API spend). It runs only when triggered from the REST API (`POST /api/digest/run`) or the UI buttons.

## Key data flow

Daily pipeline (`PipelineService.run()`):
1. For each domain: fetch timelines for all tracked accounts via `XAPIAdapter`
2. Pre-filter conversational/low-signal posts in `services/scoring._prefilter()`
3. Score each post with `LLMAdapter.score(text, domain.skill_md)` → 0.0–1.0
4. Rank by weighted sum: relevance (0.40) + recency (0.25) + engagement (0.20) + credibility (0.15)
5. Store top N as `DigestSnapshot` in SQLite
6. Repeat for preset `KeywordRule`s (different weights: engagement 0.40, relevance 0.30)
7. All API call counts are tracked in `LogEntry` and checked against `max_daily_api_calls`

`domain.skill_md` is a free-text markdown field injected as LLM context to bias relevance scoring per domain.

## Key model constraints

**`Account.credibility`** (`low`/`normal`/`high`) is account-wide, not per-domain. Changing credibility affects the account's score across all domains.

**`KeywordRule.mode`** — two modes:
- `dynamic`: run on-demand via UI, results are previewed but **not** stored automatically. User must explicitly save.
- `preset`: included in the daily pipeline; results stored as `KeywordSnapshot`.

## Keyword search syntax

The query field accepts X API v2 search syntax. The app automatically appends `-is:retweet lang:en` to every query.

- `AND` is implicit (space-separated terms all must match)
- `OR` must be uppercase
- `"exact phrase"`, `-exclude`, `#hashtag`, `from:handle`, `url:domain`
- **No** commas (use `OR`), no wildcards (`*`), no newlines
- X API basic tier caps lookback at 7 days regardless of `lookback_days` setting

## Environment

Copy `.env.example` → `.env`. The app runs in mock mode (no external calls) when `X_BEARER_TOKEN` is absent, making it fully testable without credentials. Email requires Proton Mail Bridge running locally (SMTP on 127.0.0.1:1025).

ANTHROPIC_API_KEY and X_* credentials are also available from `~/.zshrc` (see root CLAUDE.md for sourcing pattern).
