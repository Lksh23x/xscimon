# User Stories

## Domain Management

**US-01** — As a user, I want to create named domains (e.g. "Genomics", "Chemistry") so that I can track distinct niche topics independently without cross-contamination.

**US-02** — As a user, I want to maintain a curated account list per domain so that the feed reflects only sources I trust within that topic.

**US-03** — As a user, I want to add and remove accounts from a domain via the dashboard or by importing a CSV or JSON file so that I can manage curated lists both interactively and in bulk.

**US-04** — As a user, I want to write domain-specific guidance (a SKILL.md) for each domain so that I can fine-tune how the LLM evaluates relevance — for example, telling it to ignore off-topic posts or prioritise a specific sub-area.

**US-05** — As a user, I want to mark individual accounts as low, normal, or high credibility so that I can simply signal how much weight to give each voice without managing precise numbers.

---

## Daily Digest

**US-06** — As a user, I want the system to automatically fetch and process posts every day so that I have a fresh digest waiting for me each morning without manual effort.

**US-07** — As a user, I want to view today's digest organized by domain tabs so that I can focus on one topic at a time and not mix signals.

**US-08** — As a user, I want posts visually distinguished by author credibility level so that I can tell at a glance whether a post comes from a highly trusted source or a lower-credibility one without reading the metadata.

**US-09** — As a user, I want to see a separate keyword matches section in the digest so that I can distinguish what my trusted accounts posted from what the broader X conversation is saying about a topic.

**US-10** — As a user, I want to see a clear message when a domain's data is incomplete (e.g. API threshold reached) so that I know what I'm missing and why.

---

## Keyword Rules

**US-11** — As a user, I want to define keyword and hashtag search rules so that I can surface relevant posts beyond my curated account lists when needed.

**US-12** — As a user, I want to assign and adjust priority weights to keyword rules via the dashboard so that I can tune what keyword-matched content appears and how prominently over time.

**US-13** — As a user, I want to set a lookback window (N days) per keyword rule so that I can control how wide a time range each keyword search covers — broader for slow-moving topics, tighter for fast-moving ones.

**US-14** — As a user, I want to run a dynamic keyword filter on demand and immediately see the matching posts so that I can evaluate whether the query is returning useful results before committing it to the daily schedule.

**US-15** — As a user, I want to promote a dynamic filter to a preset directly from the preview so that once I'm satisfied with the output I can make it part of the daily pipeline without re-configuring it from scratch.

---

## History

**US-16** — As a user, I want to browse past daily digests by date so that I can reference what was trending or notable on a specific day.

**US-17** — As a user, I want historical digests to show the data exactly as it was captured — including incomplete or error states with their reasons — so that I have an accurate record of what happened.

**US-18** — As a user, I want to manually trigger a re-fetch for a specific domain on a past day so that I can fill in gaps caused by API limits or transient errors after resolving the underlying issue.

---

## Email Sharing

**US-19** — As a user, I want to manually trigger an email digest for any day so that I can share curated content with colleagues or collaborators.

**US-20** — As a user, I want to select a subset of posts before sending an email so that I only share the most relevant content rather than the full digest.

**US-21** — As a user, I want the email to be formatted as a clean, readable HTML digest so that it looks professional when shared externally.

---

## Admin & Logging

**US-22** — As a user, I want a simple log view showing API call counts and pipeline errors so that I can understand my API spend and diagnose failures without a full observability stack.

**US-23** — As a user, I want to filter the log by typing a search string so that I can quickly find entries for a specific domain, date, or error type.
