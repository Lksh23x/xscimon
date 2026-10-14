# Changelog

## [Unreleased] — 2026-05-19

### Fixed

- **Handle existence validation in UI** — Added ✓/✗ indicators next to accounts in the domain detail panel (`verified = true` shows green check, `false` shows red cross). Added a debounced live validation indicator inside the @handle input field that queries a new `GET /api/domains/accounts/verify?handle=` endpoint as the user types.

- **X API credential name mismatch** — The adapter was reading `X_API_KEY_SECRET` but the environment exported `X_API_SECRET`; corrected to match the actual variable name.

- **Domain tab resets to first after adding an account** — `addAccount`, `removeAccount`, and `bulkImport` all called `location.reload()`, which caused the domains page to always open on the first domain. The active domain ID is now written to `sessionStorage` on every tab switch and restored on `DOMContentLoaded`.

- **Domain tab resets to first after re-fetch** — The `/htmx/digest/.../refetch` endpoint returned `HX-Refresh: true` on success, triggering a full page reload. It now returns a rendered `domain_panel_body.html` partial that HTMX swaps directly into `#domain-{id}` with `innerHTML`, leaving the rest of the page and the active tab untouched.

### Added

- **`GET /api/domains/accounts/verify`** — Lightweight endpoint for live handle validation without adding the account.

- **X API user ID caching** — `Account` model gains an `x_user_id` column (with automatic SQLite migration). The numeric user ID is captured during `verify_account` and stored when an account is added. Subsequent `fetch_timeline` calls skip the `get_user` lookup entirely, cutting X API calls from 2 → 1 per account per pipeline run.

- **Exclude replies and retweets at source** — `get_users_tweets` now passes `exclude=["replies", "retweets"]`. Conversational exchanges and reposts are filtered by the X API before reaching the scoring pipeline.

- **Heuristic prefilter before LLM scoring** — `_prefilter()` runs zero-cost checks before any `llm.score()` call, dropping posts that start with `@`, are under 80 characters without engagement (on non-high-credibility accounts), have zero likes and retweets, or match conversational openers (`Thanks`, `Agreed`, `Congrats`, etc.). High-credibility accounts bypass the length and engagement gates.

- **Full dark theme UI redesign** — Replaced the light theme with a deep dark palette (`#09090f` base), cold teal accent (`#00cfaa`), `DM Sans` + `JetBrains Mono` typography, 1px border-defined cards, and SVG sidebar icons replacing emoji.
