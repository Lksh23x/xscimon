# Seed data

Starter configuration for xscimon: research domains, the X accounts each one tracks,
the scoring prompts, and keyword rules. Everything here is plain text, so you can edit
it without touching code.

```
seed/
├── seed.yaml          # manifest: lists domains + keyword rules, points at the files below
├── skills/            # one markdown prompt per domain (LLM context for relevance scoring)
└── accounts/          # one CSV of X handles per domain
```

## Load it

```bash
uv run python scripts/seed.py
```

This creates `data/xscimon.db` if it doesn't exist and loads the seed. It's safe to run
again: domains and keyword rules are matched by name and updated, and accounts are
added if they're missing (accounts you added in the UI are kept).

To build a separate database instead: `uv run python scripts/seed.py --db path/to/file.db`.

## Customise

**Change how posts are scored.** Edit the domain's `skills/*.md`, then re-run the seed.
The prompt tells Claude what counts as high, medium or low relevance for that domain.

**Add or remove tracked accounts.** Edit `accounts/*.csv`. Only `handle` is required:

```csv
handle,display_name,description,credibility
EricTopol,,,high
some_researcher,,,
```

`credibility` is `low`, `normal` (default) or `high`. It's account-wide and weights the
account's posts in every domain. The same CSV format works with **Import** on the
Domains page, and **Export** there produces it.

Re-running the seed doesn't remove accounts. Remove them in the UI.

**Add a domain.** Create `skills/<name>.md` and `accounts/<name>.csv`, then add an entry
to `seed.yaml`:

```yaml
  - name: Climate Science
    top_n: 10                         # posts kept per daily digest
    skill: skills/climate-science.md
    accounts: accounts/climate-science.csv
```

**Keyword rules** go under `keywords:` in `seed.yaml`. See the main README for the query
syntax. `mode: preset` runs the rule in the daily pipeline; `dynamic` runs only on demand.

## What's deliberately not here

Seed data is configuration only. Fetched posts, digests, logs and favorites stay in your
local `data/` (git-ignored). X's developer terms don't allow republishing post content,
and that data is personal to whoever runs the instance.
