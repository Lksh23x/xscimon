import json
import threading
from collections import defaultdict
from datetime import date, datetime, UTC, timedelta
from sqlmodel import Session
from ..adapters.base import XAPIAdapter, LLMAdapter
from ..config import get_config
from ..models import DomainStatus, LogEventType
from ..repositories import (DomainRepo, AccountRepo, KeywordRepo, KeywordSnapshotRepo,
                            SnapshotRepo, LogRepo, FetchCoverageRepo)
from .profiles import ProfileService, lookup_cost
from .scoring import score_and_rank_domain, score_and_rank_keyword, refresh_engagement

# Serialises pipeline work across REST-triggered background tasks and HTMX
# requests. Process-wide, so it guards every PipelineService instance.
_PIPELINE_LOCK = threading.Lock()

# A windowed fetch skips an account whose remaining uncovered window is shorter than this.
_MIN_REFETCH_WINDOW = timedelta(minutes=1)

# A windowed fetch ending within this of "now" may advance last_fetched_at.
_BASELINE_SLACK = timedelta(minutes=2)

def _x_api_now() -> datetime:
    # X API requires end_time to be at least ~10s in the past.
    return datetime.now(UTC) - timedelta(seconds=30)


def _utc(ts: datetime) -> datetime:
    # SQLite drops tzinfo on round-trip; all stored timestamps are UTC.
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


class PipelineService:
    def __init__(self, session: Session, x_api: XAPIAdapter, llm: LLMAdapter):
        self._session = session
        self._x = x_api
        self._llm = llm
        self._domains = DomainRepo(session)
        self._accounts = AccountRepo(session)
        self._keywords = KeywordRepo(session)
        self._keyword_snaps = KeywordSnapshotRepo(session)
        self._snapshots = SnapshotRepo(session)
        self._log = LogRepo(session)
        self._coverage = FetchCoverageRepo(session)
        self._profiles = ProfileService(session, x_api)
        self._cfg = get_config()
        # Per-run state, reset at the start of each run/refetch:
        # account.id -> (posts, since, until) fetched this run, so an account shared
        # by several domains costs one timeline fetch (and every domain gets its posts).
        self._timeline_cache: dict[int, tuple[list, datetime, datetime]] = {}
        # Handles X reported as nonexistent this run — skipped instead of
        # paying for a per-account handle->id lookup that would fail anyway.
        self._missing_handles: set[str] = set()

    def run(self, run_date: date | None = None, days: int | None = None) -> dict:
        """Fetch every domain, then preset keyword rules.
        days=None: incremental — each account since its last fetch.
        days=N (UI): the last N days, skipping whatever each domain already has."""
        run_date = run_date or date.today()
        if not _PIPELINE_LOCK.acquire(blocking=False):
            self._log.write(LogEventType.error,
                            "Pipeline run skipped: another run is already in progress.")
            return {"date": run_date.isoformat(), "status": "already_running",
                    "domains": [], "keywords": []}
        try:
            return self._run_locked(run_date, days)
        finally:
            _PIPELINE_LOCK.release()

    def _run_locked(self, run_date: date, days: int | None = None) -> dict:
        threshold = self._cfg["pipeline"]["max_daily_api_calls"]
        calls_used = self._log.api_calls_today()
        results = {"date": run_date.isoformat(), "domains": [], "keywords": []}

        window = self._days_window(days) if days else None
        self._log.write(LogEventType.pipeline_start,
                        f"Pipeline started for {run_date}"
                        + (f" (last {days} day(s), delta only)" if days else ""))

        domains = self._domains.get_all()
        self._timeline_cache = {}
        calls_used += self._resolve_user_ids(
            [a for d in domains for a in self._accounts.get_for_domain(d.id)],
            threshold - calls_used,
        )

        # --- Domain fetches ---
        for domain in domains:
            if calls_used >= threshold:
                reason = f"Daily API threshold ({threshold}) reached before fetching domain."
                self._snapshots.upsert(run_date, domain.id, DomainStatus.error, [], 0, reason)
                self._log.write(LogEventType.error, reason, domain_id=domain.id)
                results["domains"].append({"domain": domain.name, "status": "skipped"})
                continue

            result = self._fetch_domain(domain, run_date, threshold - calls_used, window=window)
            calls_used += result["api_calls"]
            results["domains"].append(result)

        # --- Preset keyword searches ---
        for rule in self._keywords.get_presets():
            if calls_used >= threshold:
                self._log.write(LogEventType.error,
                                f"Threshold reached, skipping keyword rule '{rule.name}'")
                break
            result = self._fetch_keyword(rule, threshold - calls_used)
            calls_used += result["api_calls"]
            results["keywords"].append(result)

        self._log.write(LogEventType.pipeline_end,
                        f"Pipeline finished. Total API calls today: {calls_used}")
        return results

    def refetch_domain(self, domain_id: int, refetch_date: date, force: bool = False) -> dict:
        """Fetch one domain's posts for one UTC day. Only the part of the day not
        already fetched for each account is requested from X (see FetchCoverage);
        force=True ignores that and fetches the whole day for every account."""
        # Fetch exactly the target date's window instead of the incremental
        # last_fetched_at baseline — otherwise a historical re-fetch would
        # only see posts newer than the most recent pipeline run.
        window_start = datetime.combine(refetch_date, datetime.min.time(), tzinfo=UTC)
        # X API requires end_time strictly in the past.
        window_end = min(window_start + timedelta(days=1), _x_api_now())
        if window_end <= window_start:
            return {"status": "error", "reason": "Cannot re-fetch a future date."}
        return self._fetch_single_domain(domain_id, refetch_date, (window_start, window_end),
                                         force, f"for {refetch_date}")

    def fetch_domain(self, domain_id: int, days: int, force: bool = False) -> dict:
        """Fetch one domain's posts for the last `days` days. Without force only the
        delta is fetched: accounts whose window is already covered are skipped, and
        the rest are fetched from where their coverage ends. force=True re-fetches
        the whole window for every account."""
        return self._fetch_single_domain(domain_id, date.today(), self._days_window(days),
                                         force, f"for the last {days} day(s)")

    def _fetch_single_domain(self, domain_id: int, run_date: date,
                             window: tuple[datetime, datetime], force: bool,
                             label: str) -> dict:
        if not _PIPELINE_LOCK.acquire(blocking=False):
            return {"status": "error", "reason": "A pipeline run is already in progress."}
        try:
            threshold = self._cfg["pipeline"]["max_daily_api_calls"]
            calls_used = self._log.api_calls_today()
            if calls_used >= threshold:
                return {"status": "error", "reason": "Daily API threshold already reached."}

            domain = self._domains.get_by_id(domain_id)
            if not domain:
                return {"status": "error", "reason": "Domain not found."}

            self._log.write(LogEventType.refetch,
                            f"Manual {'re-fetch (forced)' if force else 'fetch (delta)'}: "
                            f"domain '{domain.name}' {label}",
                            domain_id=domain_id)
            self._timeline_cache = {}
            calls_used += self._resolve_user_ids(self._accounts.get_for_domain(domain_id),
                                                 threshold - calls_used, domain_id)
            return self._fetch_domain(domain, run_date, threshold - calls_used,
                                      window=window, force=force)
        finally:
            _PIPELINE_LOCK.release()

    @staticmethod
    def _days_window(days: int) -> tuple[datetime, datetime]:
        """[start, end) covering the last `days` calendar days up to now. Starts at
        whichever midnight is earlier — UTC or local — so neither the UTC-bucketed
        snapshots nor the local-date digest view lose part of their first day."""
        first_day = timedelta(days=days - 1)
        utc_start = datetime.combine(datetime.now(UTC).date() - first_day,
                                     datetime.min.time(), tzinfo=UTC)
        local_start = datetime.combine(date.today() - first_day,
                                       datetime.min.time()).astimezone(UTC)
        return min(utc_start, local_start), _x_api_now()

    def _resolve_user_ids(self, accounts: list, budget: int,
                          domain_id: int | None = None) -> int:
        """Batch-resolve X user ids for accounts that lack one (100 per call) and
        store them, so timeline fetches never pay a per-account handle->id lookup.
        Returns API calls used."""
        self._missing_handles = set()
        unique = {a.id: a for a in accounts if not a.x_user_id}
        pending = list(unique.values())
        if not pending:
            return 0
        if lookup_cost(len(pending)) > budget:
            # Fall back to fetch_timeline's per-account lookup within what's left.
            return 0
        try:
            result = self._profiles.refresh(pending, domain_id, reason="Resolve user ids")
        except Exception as exc:
            self._log.write(LogEventType.error,
                            f"Batch user-id lookup failed, falling back to "
                            f"per-account lookups: {exc}", domain_id=domain_id)
            return 0
        self._missing_handles = {h.lower() for h in result["not_found"]}
        return result["api_calls"]

    def _record_coverage(self, domain_id: int, account_id: int,
                         start: datetime, end: datetime) -> None:
        """Merge a successful fetch of [start, end) into each UTC day's coverage.
        A day keeps one contiguous span: an overlapping or touching fetch extends
        it; a disjoint one replaces it only if it reaches later (the newest span
        is the one delta fetches build on)."""
        day = start.date()
        while day <= end.date():
            day_start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
            s, e = max(start, day_start), min(end, day_start + timedelta(days=1))
            if s < e:
                current = self._coverage.get(domain_id, account_id, day)
                if current is None:
                    new = (s, e)
                else:
                    cf, cu = current
                    if e < cf or s > cu:
                        new = (s, e) if e > cu else None
                    else:
                        new = (min(s, cf), max(e, cu))
                if new and new != current:
                    self._coverage.set(domain_id, account_id, day, new[1], new[0])
            day += timedelta(days=1)

    @staticmethod
    def _uncovered_span(coverage_by_day: dict[date, dict[int, tuple[datetime, datetime]]],
                        account_id: int, start: datetime,
                        end: datetime) -> tuple[datetime, datetime] | None:
        """The part of [start, end) to request from X for one account: None when it
        is all covered, the exact gap when there is one, otherwise from the first gap
        to the end of the last (one timeline request spans them all). Fetching only
        the exact gap matters for long windows: a fetch capped by the page limit
        keeps only the newest posts, and the next fetch then fills the older gap."""
        gaps: list[tuple[datetime, datetime]] = []
        cursor = start
        day = start.date()
        while day <= end.date():
            span = coverage_by_day.get(day, {}).get(account_id)
            if span:
                cf, cu = max(span[0], start), min(span[1], end)
                if cf < cu:
                    if cf > cursor:
                        gaps.append((cursor, cf))
                    cursor = max(cursor, cu)
            day += timedelta(days=1)
        if cursor < end:
            gaps.append((cursor, end))
        gaps = [g for g in gaps if g[1] - g[0] >= _MIN_REFETCH_WINDOW]
        if not gaps:
            return None
        return gaps[0][0], gaps[-1][1]

    def _fetch_domain(self, domain, run_date: date, budget: int,
                      window: tuple[datetime, datetime] | None = None,
                      force: bool = False) -> dict:
        accounts = self._accounts.get_for_domain(domain.id)
        cfg = self._cfg["credibility"]
        cred_map = {a.handle: cfg[a.credibility.value] for a in accounts}
        cred_level_map = {a.handle: a.credibility.value for a in accounts}

        now = datetime.now(UTC)
        all_new_posts = []
        total_calls = 0
        any_error = False
        covered_skips = 0
        coverage_by_day: dict[date, dict[int, tuple[datetime, datetime]]] = {}
        if window is not None and not force:
            coverage_by_day = self._coverage.get_for_range(
                domain.id, window[0].date(), window[1].date())

        for account in accounts:
            if account.handle.lower() in self._missing_handles:
                continue  # already logged by _resolve_user_ids
            if window is not None:
                since, until = window
                if not force:
                    # Only ask X for what this domain doesn't have yet.
                    span = self._uncovered_span(coverage_by_day, account.id, since, until)
                    if span is None:
                        covered_skips += 1
                        continue
                    since, until = span
            else:
                # Use last successful fetch as baseline; fall back to 24 h on first run.
                since = _utc(account.last_fetched_at) if account.last_fetched_at \
                    else now - timedelta(hours=24)
                until = None
            cached = self._timeline_cache.get(account.id)
            if cached and (window is None or (cached[1] <= since and cached[2] >= until)):
                # Already fetched for another domain this run, over a span that
                # includes what this domain needs — reuse instead of paying again.
                # (Incrementally, re-fetching would also return nothing, since
                # last_fetched_at was just advanced.)
                posts, cached_since, cached_until = cached
                all_new_posts.extend(posts)
                self._record_coverage(domain.id, account.id, cached_since, cached_until)
                continue
            if total_calls >= budget:
                break
            try:
                posts, calls, truncated = self._x.fetch_timeline(account.handle, since,
                                                      user_id=account.x_user_id,
                                                      until=until)
                self._log.write(LogEventType.api_call,
                                f"Fetched timeline for @{account.handle} "
                                f"(since {since.date().isoformat()})",
                                domain_id=domain.id, call_count=calls)
                all_new_posts.extend(posts)
                total_calls += calls
                # Only a fetch the page cap cut short is missing its oldest posts;
                # otherwise the whole requested window is covered, however many
                # posts it returned.
                covered_from = min(p.created_at for p in posts) if truncated and posts \
                    else since
                fetched_until = until or now
                self._record_coverage(domain.id, account.id, covered_from, fetched_until)
                self._timeline_cache[account.id] = (posts, covered_from, fetched_until)
                # Advance the incremental baseline only when this fetch reached
                # (nearly) now and joins up with the previous baseline. A historical
                # window, or one starting after the last fetch, must not, or the
                # next incremental run would skip the posts in between.
                last = _utc(account.last_fetched_at) if account.last_fetched_at else None
                if fetched_until >= now - _BASELINE_SLACK and (last is None or covered_from <= last):
                    latest_post_at = max((p.created_at for p in posts), default=None)
                    self._accounts.stamp_fetched(account.id, fetched_until,
                                                 latest_post_at=latest_post_at)
            except Exception as exc:
                any_error = True
                self._log.write(LogEventType.error,
                                f"Error fetching @{account.handle}: {exc}",
                                domain_id=domain.id)

        # Drop posts already stored in their date's snapshot BEFORE scoring, so
        # re-fetched content doesn't burn LLM calls only to be discarded in the merge.
        existing_ids_by_date: dict[date, set[str]] = {}

        def _seen_before(post) -> bool:
            post_date = post.created_at.date()
            if post_date not in existing_ids_by_date:
                snap = self._snapshots.get(post_date, domain.id)
                existing_ids_by_date[post_date] = (
                    {p["post_id"] for p in json.loads(snap.posts_json)} if snap else set()
                )
            return post.post_id in existing_ids_by_date[post_date]

        fresh_posts = []
        # Forced re-fetch: refresh engagement of posts already stored, by date.
        engagement_updates: dict[date, dict[str, object]] = defaultdict(dict)
        for p in all_new_posts:
            if not _seen_before(p):
                fresh_posts.append(p)
            elif force:
                engagement_updates[p.created_at.date()][p.post_id] = p

        # Score fresh posts in one pass (prefilter is inside score_and_rank_domain).
        scored_new = score_and_rank_domain(fresh_posts, domain.skill_md, cred_map, self._llm,
                                           credibility_level_map=cred_level_map)

        # Bucket by the post's actual calendar date (UTC).
        by_date: dict[date, list[dict]] = defaultdict(list)
        for post in scored_new:
            post_date = datetime.fromisoformat(post["created_at"]).date()
            by_date[post_date].append(post)

        # Always write a snapshot for run_date so the pipeline run is visible in History.
        if run_date not in by_date:
            by_date[run_date] = []

        status = DomainStatus.partial if any_error else DomainStatus.complete

        refreshed = 0
        for post_date in sorted(set(by_date) | set(engagement_updates)):
            new_posts = by_date.get(post_date, [])
            updates = engagement_updates.get(post_date, {})
            existing_snap = self._snapshots.get(post_date, domain.id)
            if existing_snap and existing_snap.posts_json != "[]":
                existing_posts = json.loads(existing_snap.posts_json)
                for idx, stored in enumerate(existing_posts):
                    fetched = updates.get(stored["post_id"])
                    if fetched and (fetched.likes, fetched.retweets) != \
                            (stored.get("likes"), stored.get("retweets")):
                        existing_posts[idx] = refresh_engagement(
                            stored, fetched.likes, fetched.retweets)
                        refreshed += 1
                seen_ids = {p["post_id"] for p in existing_posts}
                merged = existing_posts + [p for p in new_posts if p["post_id"] not in seen_ids]
            else:
                merged = list(new_posts)
            merged.sort(key=lambda p: p["final_score"], reverse=True)
            self._snapshots.upsert(post_date, domain.id, status,
                                   merged[:domain.top_n], total_calls)

        if window is not None:
            self._log.write(LogEventType.refetch,
                            f"Fetch of '{domain.name}' {'(forced)' if force else '(delta)'}: "
                            f"{total_calls} API call(s), {covered_skips} account(s) "
                            f"skipped as already fetched"
                            + (f", engagement refreshed on {refreshed} stored post(s)"
                               if force else ""),
                            domain_id=domain.id)

        return {"domain": domain.name, "status": status.value,
                "posts": len(scored_new), "api_calls": total_calls,
                "skipped_covered": covered_skips, "engagement_refreshed": refreshed,
                "dates_updated": sorted({d.isoformat() for d in by_date}
                                        | {d.isoformat() for d in engagement_updates})}

    def _fetch_keyword(self, rule, budget: int) -> dict:
        search_to = datetime.now(UTC)
        since = search_to - timedelta(days=rule.lookback_days)
        try:
            posts, calls = self._x.search(rule.query, since)
            self._log.write(LogEventType.api_call,
                            f"Keyword search: '{rule.query}'", call_count=calls)
        except Exception as exc:
            self._log.write(LogEventType.error, f"Keyword search error '{rule.query}': {exc}")
            return {"rule": rule.name, "status": "error", "api_calls": 0}

        cfg = self._cfg["keyword"]
        ranked = score_and_rank_keyword(posts, rule.skill_md, rule.priority_weight, self._llm)
        top_posts = ranked[:cfg["max_results"]]
        snap = self._keyword_snaps.save(
            rule_id=rule.id,
            rule_name=rule.name,
            query=rule.query,
            lookback_days=rule.lookback_days,
            search_from=since.isoformat(),
            search_to=search_to.isoformat(),
            api_calls_used=calls,
            fetched_count=len(posts),
            scored_count=len(ranked),
            posts=top_posts,
        )
        self._log.write(LogEventType.keyword_save,
                        f'Preset keyword snapshot saved: "{rule.name}" | '
                        f"fetched {len(posts)}, kept {len(ranked)}, stored {len(top_posts)}")
        return {"rule": rule.name, "status": "ok", "snapshot_id": snap.id,
                "posts": top_posts, "api_calls": calls}
