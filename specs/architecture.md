# Architecture

## Principles

- **API-first**: the backend exposes a REST API; the frontend is a separate consumer. Swapping the UI (e.g. HTMX → React) requires touching only the frontend layer.
- **Adapter pattern for external services**: X API, Claude, and Proton Mail are behind thin interfaces. Each can be swapped or mocked independently.
- **Service layer owns business logic**: no domain logic in route handlers or repositories. Routes validate and delegate; repositories persist and query; services orchestrate.
- **Pipeline is standalone**: can be triggered by the scheduler, an API call, or directly from the CLI. Not coupled to the web server.
- **Database is source of truth**: all runtime settings live in SQLite. Config file contains only infrastructure concerns (port, schedule, API threshold).

---

## Layer Diagram

```
┌─────────────────────────────────────────────────┐
│                  Frontend                       │
│         HTMX + Jinja2 templates                 │  ← swappable
│   Dashboard / History / Admin / Keyword Preview │
└────────────────────┬────────────────────────────┘
                     │ HTTP (JSON)
┌────────────────────▼────────────────────────────┐
│               REST API Layer                    │
│                  FastAPI                        │  ← swappable
│  /digest  /domains  /keywords  /admin  /email   │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│               Service Layer                     │
│  DigestService     — assemble and serve digests │
│  PipelineService   — orchestrate daily runs     │
│  ScoringService    — LLM relevance scoring      │
│  KeywordService    — dynamic filter + preset    │
│  CredibilityService— account credibility mgmt   │
│  EmailService      — compose and send digest    │
│  LogService        — pipeline event logging     │
└──────────┬──────────────────┬───────────────────┘
           │                  │
┌──────────▼──────┐  ┌────────▼───────────────────┐
│  Repository     │  │     External Adapters       │
│  (SQLite via    │  │  XAPIAdapter   (tweepy)     │  ← swappable
│   SQLModel)     │  │  LLMAdapter    (Claude)     │  ← swappable
└─────────────────┘  │  EmailAdapter  (Proton      │  ← swappable
                     │                Mail Bridge) │
                     └────────────────────────────┘
```

---

## Module Breakdown

### `api/`
FastAPI route handlers. Thin: validate input, call a service, return a response. No business logic.

### `services/`
| Module | Responsibility |
|---|---|
| `pipeline.py` | Orchestrates a full or partial daily run: fetch → score → rank → store snapshot |
| `digest.py` | Reads snapshots from the DB and assembles the digest view for a given date |
| `scoring.py` | Calls the LLM adapter, injects SKILL.md context, returns a relevance score |
| `keyword.py` | Runs dynamic filters on demand; promotes to preset; routes preset queries into the pipeline |
| `credibility.py` | Manages account credibility levels; applies level to ranking weight mapping |
| `email.py` | Builds the HTML digest and dispatches via the email adapter |
| `log.py` | Writes and queries pipeline event log entries |

### `adapters/`
| Module | Responsibility |
|---|---|
| `x_api.py` | Wraps tweepy; exposes `fetch_timeline(account, since)` and `search(query, days)` |
| `llm.py` | Wraps Claude API; exposes `score(post, context)` returning 0.0–1.0 |
| `email.py` | Wraps smtplib pointed at Proton Mail Bridge; exposes `send(to, subject, html)` |

Each adapter implements a protocol (interface) defined in `adapters/base.py`. Swapping an adapter requires only a new implementation of that protocol.

### `repositories/`
SQLModel-based data access. One repository per aggregate: `DomainRepo`, `AccountRepo`, `PostRepo`, `SnapshotRepo`, `KeywordRuleRepo`, `LogRepo`. No SQL outside this layer.

### `scheduler/`
APScheduler job that calls `PipelineService.run()` on the configured schedule. The scheduler process starts alongside the web server but is independently testable.

### `pipeline/`
Standalone entry point (`python -m xscimon.pipeline`) for running a full pipeline cycle from the CLI, bypassing the web server and scheduler entirely.

---

## Data Model (simplified)

```
Domain          Account         DomainAccount (join)
------          -------         ----------------
id              id              domain_id
name            handle          account_id
skill_md        credibility     
top_n           

KeywordRule     Post            DigestSnapshot
-----------     ----            --------------
id              id              id
query           author_handle   date
mode            text            domain_id
priority_weight timestamp       status (complete/partial/error)
lookback_days   likes           status_reason
skill_md        retweets        posts (JSON blob)
enabled         relevance_score api_call_count
                credibility_level

LogEntry
--------
id
timestamp
domain_id (nullable)
event_type (api_call / error / pipeline_start / pipeline_end)
message
call_count (nullable)
```

---

## Key Flows

### Daily pipeline run
```
Scheduler triggers PipelineService.run()
  For each domain (until API threshold reached):
    XAPIAdapter.fetch_timeline(accounts, since=24h)
    Record API calls → LogEntry
    For each post:
      ScoringService.score(post, domain.skill_md)
    Rank posts (relevance + recency + engagement + credibility)
    Store top N → DigestSnapshot (status: complete)
  For each preset KeywordRule:
    XAPIAdapter.search(query, days=rule.lookback_days)
    Record API calls → LogEntry
    Score and rank results
    Store → DigestSnapshot keyword section
  If threshold reached mid-run:
    Remaining domains → DigestSnapshot (status: incomplete, reason: threshold)
```

### Dynamic keyword filter (on demand)
```
User submits query via dashboard
KeywordService.run_dynamic(rule)
  XAPIAdapter.search(query, days)
  ScoringService.score each result
  Return ranked results to preview view (not stored in DigestSnapshot)
User optionally promotes → rule.mode = preset
```

### Manual re-fetch
```
User triggers re-fetch for domain D on date X
PipelineService.refetch(domain_id, date)
  Check today's API call count against threshold
  XAPIAdapter.fetch_timeline(...)
  Score + rank
  Update DigestSnapshot for date X, domain D (status → complete)
  API calls recorded against today's threshold
```

---

## Flexibility Points

| Concern | Current choice | Swap path |
|---|---|---|
| Frontend | HTMX + Jinja2 | Any JS framework consuming the REST API |
| Web framework | FastAPI | Flask, Django — change `api/` layer only |
| Database | SQLite | PostgreSQL — change `repositories/` layer only |
| LLM provider | Claude Haiku | Any model — implement `LLMAdapter` protocol |
| Email | Proton Mail Bridge | Any SMTP — implement `EmailAdapter` protocol |
| Scheduler | APScheduler | External cron or task queue — replace `scheduler/` only |
