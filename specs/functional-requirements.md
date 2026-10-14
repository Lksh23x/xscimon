# Functional Requirements

## Domain Management

**FR-01** — The system shall support up to 10 user-defined named domains.

**FR-02** — Each domain shall maintain an independent curated account list with no shared state between domains.

**FR-03** — The user shall be able to create, rename, and delete domains via the dashboard. Deleting a domain shall cascade-remove all of that domain's account associations and its SKILL.md content. Account records that still appear in other domains shall be preserved, including their global credibility level.

**FR-04** — The user shall be able to add and remove X accounts from a domain's curated list via the dashboard or by importing a CSV or JSON file with accounts and descriptions.

**FR-05** — Each domain shall have an optional guidance file (SKILL.md) containing natural language instructions injected into the LLM prompt when scoring posts for that domain (e.g. "disregard posts about topic X", "prioritise posts about sub-area Y").

**FR-06** — A domain's SKILL.md shall be editable via a textarea in the domain settings page and stored in the database; it shall also be importable and exportable as a markdown file.

---

## Data Collection

**FR-07** — The system shall fetch posts published within the last 24 hours from all accounts in each domain's curated list as part of the daily pipeline run via the X API.

**FR-08** — The daily pipeline shall execute only preset keyword rules (see Keyword Management). Dynamic filters without promotion to preset are excluded from the scheduled run.

**FR-09** — The daily pipeline shall run on a configurable schedule (default: once per day at a user-defined time).

**FR-10** — The system shall enforce a configurable maximum daily X API call threshold. When the threshold is reached, remaining unfetched domains and accounts shall be skipped and marked as incomplete with a logged reason. The threshold is set in config and adjustable without code changes.

**FR-11** — The system shall record the number of X API calls made per domain per fetch, including timestamp, domain, and call count. This record shall be updated for scheduled runs and manual re-fetches alike, and shall be used to enforce the daily threshold (FR-10).

**FR-12** — The system shall handle X API rate limit errors gracefully — logging the failure and continuing with remaining accounts rather than aborting the full run.

---

## Ranking & Scoring

**FR-13** — Each post fetched from a curated account shall be scored for relevance using an LLM (Claude Haiku), with the domain's SKILL.md guidance injected into the scoring prompt when present.

**FR-14** — Posts within a domain shall be ranked using a weighted combination of: AI relevance score, recency, raw engagement counts (likes + retweets), and author credibility level.

**FR-15** — Keyword-matched posts shall be ranked using a weighted combination of: engagement (weighted higher than recency), recency, AI relevance score, and keyword rule priority weight. Optional keyword-specific SKILL.md guidance shall be injected into the LLM scoring prompt.

**FR-16** — Ranking weights (for both domain posts and keyword matches) shall be adjustable by the user at any time without restarting the application.

---

## Author Credibility

**FR-17** — Each X account shall have a single global credibility level — low, normal, or high (default: normal) — applied consistently across all domains in which the account appears.

**FR-18** — The user shall be able to set an account's credibility level via the dashboard.

**FR-19** — The account's global credibility level shall factor into post ranking in every domain where the account appears.

**FR-20** — Post entries shall be visually distinguished by the author's credibility level (e.g. via card styling, colour accent, or badge) so that high-credibility and low-credibility sources are immediately identifiable at a glance without reading metadata. Each post entry shall also display: author handle, post text, timestamp, engagement counts, AI relevance score, and credibility level label.

---

## Dashboard

**FR-21** — The dashboard home page shall display the current day's digest with domains rendered as tabs.

**FR-22** — Each domain tab shall show the top N ranked posts for that domain (N configurable per domain).

**FR-23** — Keyword matches shall be displayed in a dedicated section, separate from curated domain posts, capped at a configurable top N (maximum 30 posts).

**FR-24** — Each domain tab shall display a status indicator: green for a complete successful fetch, red for a failed or incomplete fetch. A red indicator shall show the failure reason and offer an option to manually re-fetch that domain.

---

## History

**FR-25** — Upon completion (full or partial) of each daily pipeline run, the system shall store a snapshot of the digest including all post content, scores, metadata, and a per-domain status (complete / partial / error) with a human-readable reason for any non-complete status.

**FR-26** — The user shall be able to access historical digests via a date-based history view.

**FR-27** — A historical digest shall render the data exactly as it was captured, including any incomplete or error states with their explanations.

**FR-28** — The user shall be able to manually trigger a re-fetch for a specific domain on a specific historical date. A successful re-fetch shall update that domain's data in the existing snapshot.

---

## Keyword Management

**FR-29** — Keyword search rules shall exist in one of two modes: **dynamic filter** (ad-hoc, for exploration and testing) or **preset** (saved, included in the daily pipeline).

**FR-30** — The user shall be able to run any dynamic filter on demand from the dashboard, immediately fetching and displaying matching posts outside the daily pipeline.

**FR-31** — Results from a dynamic filter run shall be displayed in a dedicated preview view, separate from the main daily digest.

**FR-32** — The user shall be able to promote a dynamic filter to a preset directly from the preview view. On promotion, all rule settings (query terms including hashtags, priority weight, lookback window, SKILL.md) are preserved.

**FR-33** — Each keyword rule shall support plain keywords and hashtags (#term) interchangeably within the same query.

**FR-34** — Each keyword rule (dynamic or preset) shall have a configurable priority weight influencing ranking in the keyword matches section.

**FR-35** — Each keyword rule shall have a configurable lookback window (N days) defining how far back to search.

**FR-36** — Each keyword rule shall have an optional SKILL.md guidance text injected into the LLM scoring prompt when evaluating matched posts.

**FR-37** — Preset keyword rules shall be independently enable/disable-able without deleting them.

---

## Email Digest

**FR-38** — The user shall be able to manually trigger an email digest for one or more domains from any day's digest (today or historical).

**FR-39** — Before sending, the user shall be able to select a full or selective subset of posts to include in the email.

**FR-40** — The email shall be rendered as a formatted HTML digest mirroring the dashboard layout.

**FR-41** — The system shall send email via Proton Mail SMTP through the locally running Proton Mail Bridge, using Bridge SMTP credentials stored in a local `.env` file.

**FR-42** — The recipient email address shall be pre-configured in `.env` and modifiable by the user at send time.

---

## Admin & Logging

**FR-43** — The system shall provide an admin/logging view displaying a chronological log of pipeline events: API call records (timestamp, domain, call count) and errors (timestamp, domain, error type, message).

**FR-44** — The admin log view shall support text-based search and filter applied across all log fields (timestamp, domain, message content).

**FR-45** — Log entries shall be retained in the database indefinitely unless manually cleared by the user.

---

## Configuration

**FR-46** — All secrets (X API credentials, Proton Mail Bridge SMTP credentials, Claude API key) shall be stored in a `.env` file and loaded at startup.

**FR-47** — Infrastructure and startup configuration (pipeline schedule time, max daily API call threshold, server port) shall be stored in a separate config file editable without touching application code.

**FR-48** — The database shall be the single source of truth for all runtime settings: ranking weights, credibility levels, keyword rules, SKILL.md content, per-domain top N, and keyword lookback windows.

**FR-49** — The system shall support bulk import and upmerge of database content (curated account lists, keyword rules, SKILL.md text) from CSV or JSON files. On conflict, the imported value shall overwrite the existing record.
