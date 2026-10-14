# Non-Functional Requirements

## Performance

**NFR-01** — The dashboard shall load any digest page (today or historical) within 2 seconds under normal local conditions.

**NFR-02** — The daily pipeline shall complete a full run (all domains + keyword searches + LLM scoring) within 15 minutes, assuming the API call threshold is not reached first.

**NFR-03** — LLM scoring shall be performed with batching or concurrency to avoid sequential per-post latency becoming a bottleneck.

---

## Reliability

**NFR-04** — A failure in one domain's pipeline (e.g. X API error, LLM timeout) shall not prevent other domains from completing their run; the failed domain shall display the error reason in place of posts until a successful re-fetch is performed.

**NFR-05** — Pipeline failures shall be logged with sufficient detail (domain, account, error type, timestamp) to diagnose issues without re-running.

**NFR-06** — Partial pipeline results shall be stored rather than discarded — a domain with 8/10 accounts fetched is still useful.

**NFR-07** — The system shall implement retry logic with exponential backoff for transient X API and LLM API errors, and minimise total X API calls per run.

---

## Cost

**NFR-08** — LLM scoring costs shall remain under $1/month at expected daily usage (~200 posts/day scored with Haiku).

**NFR-09** — The system shall expose a configurable daily X API call threshold (set in config, adjustable without code changes). The pipeline shall halt and record an incomplete status when the threshold is reached rather than exceeding it silently. The user is expected to calibrate this threshold based on observed real spend.

---

## Security

**NFR-10** — No API keys, credentials, or secrets shall be committed to version control. A `.gitignore` entry for `.env` shall be present from project initialization.

**NFR-11** — The dashboard shall be accessible only on localhost — no external network binding.

**NFR-12** — Proton Mail Bridge SMTP credentials shall be stored exclusively in `.env` and never logged or exposed in the UI.

---

## Maintainability

**NFR-13** — Curated account lists and keyword rules shall be manageable through the dashboard UI, and also support batch loads/updates/merges via static files.

**NFR-14** — The database is the single source of truth for all runtime settings (ranking weights, credibility levels, keyword rules, per-domain top N, keyword lookback windows). Infrastructure settings (schedule, API threshold) live in a config file. Bulk file import/upmerge is the supported mechanism for batch-updating database content without code changes.

**NFR-15** — The codebase shall use clear module boundaries separating: data collection, scoring/ranking, storage, scheduling, and web serving.

---

## Portability & Operations

**NFR-16** — The application shall run on macOS with no external hosting or cloud infrastructure required.

**NFR-17** — All persistent data shall be stored in a local SQLite database — zero database server administration.

**NFR-18** — The application architecture shall not preclude future migration to a cloud host (e.g. a Linux VPS). The only macOS-specific runtime dependency is Proton Mail Bridge; all other core logic shall be platform-neutral.

**NFR-19** — Setup from a fresh clone shall require no more than: installing Python dependencies, populating `.env`, ensuring Proton Mail Bridge is running locally, and running one start command.
