# xscimon

A research digest for X (Twitter). You choose the research areas ("domains") you
follow and the accounts worth reading in each. xscimon fetches their recent posts,
has Claude score each one for relevance to that domain, and gives you a short ranked
digest instead of a timeline.

It runs locally as a small web app (FastAPI + HTMX, SQLite storage) and never fetches
on its own: every X API call starts from a button or an API request you trigger, so
you stay in control of API spend.

## What it does

- **Domain digests.** Each domain has a list of tracked accounts and a *skill prompt*,
  a markdown brief telling Claude what counts as important in that field. Posts are
  pre-filtered for obvious noise (replies, short or zero-engagement chatter), scored
  0–1 by Claude, then ranked by relevance (40%), recency (25%), engagement (20%) and
  account credibility (15%). The top N per domain are saved as that day's digest.
- **Keyword searches.** Rules using X search syntax (see [Keyword search](#keyword-search)).
  *Dynamic* rules run on demand, and you choose which results to save. *Preset* rules
  also run with the daily pipeline.
- **History and favorites.** Browse past digests and saved keyword results, and star
  posts to keep them.
- **Email.** Send a day's digest to an address through Proton Mail Bridge (optional).
- **Admin.** Searchable logs, X API call counts against a daily budget, and pipeline
  controls.

Pages: `/` today's digest, `/history`, `/domains`, `/keywords`, `/admin`.

## Requirements

| Need | Why | Without it |
|---|---|---|
| Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/) | runs the app | — |
| [X API](https://developer.x.com) access, **Basic tier or higher**, with a bearer token *and* user-context keys | fetching timelines and searches | **Mock mode:** simulated posts, so you can explore the UI for free |
| [Anthropic API key](https://console.anthropic.com) | relevance scoring (Claude Haiku) | mock scores |
| [Proton Mail Bridge](https://proton.me/mail/bridge) running locally | emailing digests | sending is simulated (nothing is delivered) |

Each integration switches on independently based on which variables are set in `.env`.

X API access costs money and is metered. The pipeline stops once it reaches
`pipeline.max_daily_api_calls` in `config.yaml` (default 500). Keyword search only reaches
back 7 days.

## Setup

```bash
git clone https://github.com/Lksh23x/xscimon.git && cd xscimon
uv venv && uv pip install -e ".[dev]"
cp .env.example .env              # then fill in what you have (see below)
uv run python scripts/seed.py     # load starter domains, accounts and skill prompts
./start.sh                        # → http://127.0.0.1:8000
```

`./start.sh` runs the server in the background, logging to `server.log`. Use
`./stop.sh` and `./restart.sh` to manage it. For development with auto-reload, run
`uv run uvicorn xscimon.main:app --reload` instead.

Once it's running, open **Admin → Run Pipeline**, or a domain's fetch button, to
build your first digest.

### `.env`

```bash
# X API: all five are needed once X_BEARER_TOKEN is set
X_BEARER_TOKEN=
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_TOKEN_SECRET=

ANTHROPIC_API_KEY=

# Email via Proton Mail Bridge (copy the SMTP credentials Bridge shows you)
SMTP_HOST=127.0.0.1
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
EMAIL_FROM=
EMAIL_TO_DEFAULT=        # optional default recipient
```

`.env` is git-ignored. Never commit real keys.

### `config.yaml`

This file holds infrastructure settings: host and port (default `127.0.0.1:8000`),
the daily API-call budget, the database path, ranking weights, credibility
multipliers and keyword defaults. Domains, accounts and rules are not configured
here; they live in the database and come from the seed or the UI.

## Seed data

The `seed/` folder holds a ready-made configuration as plain files, separate from the code:

```
seed/
├── seed.yaml       which domains and keyword rules to create
├── skills/*.md     the scoring prompt for each domain
└── accounts/*.csv  the X handles each domain tracks
```

It ships with three example domains: *Pharma and Research*, *AI Research, GenAI
Technology* and *Uranium*.

```bash
uv run python scripts/seed.py                # seed data/xscimon.db
uv run python scripts/seed.py --db other.db  # or a different file
```

Re-running is safe. Domains and rules are updated by name, missing accounts are
added, and nothing is deleted. To adapt xscimon to your own field, edit or replace
the skill prompts and account CSVs, then run the script again. See
[`seed/README.md`](seed/README.md) for the file formats.

The account CSVs use the same format as **Import** and **Export** on the Domains
page, so you can also manage accounts in the UI and export them back into `seed/`.

## Security

xscimon has no login and is meant to run on `127.0.0.1` for a single user. It
rejects state-changing requests from other websites (Origin check) and requests with
an unexpected `Host` header (DNS rebinding). Don't bind it to `0.0.0.0` or expose it
to a network without putting authentication in front of it.

## Keyword search

Keyword rules let you search X on demand (dynamic) or as part of the daily pipeline (preset). The query field accepts X API v2 search syntax.

### Operators

| Syntax | Matches |
|---|---|
| `CRISPR` | posts containing the word CRISPR |
| `"gene editing"` | exact phrase |
| `CRISPR OR "base editing"` | either term — use `OR` (uppercase) |
| `genomics -GWAS` | contains *genomics* but not *GWAS* |
| `#proteomics` | posts with that hashtag |
| `"protein folding" #AlphaFold` | both must appear |
| `(AI OR ML) drug discovery` | grouping with parentheses |
| `from:OpenAI` | posts from a specific account |
| `url:biorxiv` | posts linking to biorxiv |

**AND is implicit** — multiple terms or phrases separated by spaces all must match.

### What the app adds automatically

Every query is sent to the API with `-is:retweet lang:en` appended, so you never need to include those yourself.

### What doesn't work

- **Commas** — `,` is not a valid operator and will cause a 400 error from the API. Use `OR` instead.
- **Newlines** — the query must be a single line.
- **Wildcards** — `*` is not supported in v2 search.

### Lookback window

The X API free/basic tier only returns posts from the **last 7 days**. Setting `lookback_days` higher than 7 will still only retrieve the last 7 days of results.

### Example queries

```
"AI drug discovery" OR "ML for chemistry" OR cheminformatics
"single cell RNA-seq" OR "spatial transcriptomics" OR "multi-omics"
"protein language model" OR "protein design" #AlphaFold
```

## Development

```bash
uv run pytest                               # run tests (always mock adapters, no API calls)
curl -X POST localhost:8000/api/digest/run  # trigger the pipeline via the API
curl -X POST "localhost:8000/api/digest/run?days=3"   # backfill the last 3 days
```

The REST API is documented at `/docs` (OpenAPI) while the server is running.
`CLAUDE.md` covers the architecture and layer rules.
