"""Tests for PipelineService: scoring dedup and preset keyword snapshot persistence."""
import json
from datetime import date, datetime, UTC, timedelta
from typing import Optional

from xscimon.adapters.base import FetchedPost, UserProfile
from xscimon.models import KeywordMode
from xscimon.repositories import (DomainRepo, AccountRepo, KeywordRepo,
                                  KeywordSnapshotRepo, SnapshotRepo, FetchCoverageRepo)
from xscimon.services.pipeline import PipelineService


class FixedXAPIAdapter:
    """Always returns the same posts regardless of `since`, so a second pipeline
    run re-fetches content that is already stored."""

    def __init__(self):
        now = datetime.now(UTC)
        self.posts = [
            FetchedPost(
                post_id=f"fixed-{i}",
                author_handle="researcher_x",
                text=f"Substantive announcement number {i} about protein folding "
                     f"with enough characters to pass the prefilter easily.",
                created_at=now - timedelta(hours=i),
                likes=50,
                retweets=10,
            )
            for i in range(3)
        ]

    def fetch_timeline(self, handle: str, since: datetime,
                       user_id: Optional[str] = None,
                       until: Optional[datetime] = None) -> tuple[list[FetchedPost], int, bool]:
        return list(self.posts), 1, False

    def search(self, query: str, since: datetime) -> tuple[list[FetchedPost], int]:
        return list(self.posts), 1

    def verify_account(self, handle: str):
        return True, "bio", f"uid-{handle}", 100

    def lookup_users(self, handles: list[str]):
        return {h.lower(): UserProfile(f"uid-{h}", "bio", 100) for h in handles}, 1


class WindowedXAPIAdapter(FixedXAPIAdapter):
    """Respects the since/until window, like the real X API."""

    def fetch_timeline(self, handle: str, since: datetime,
                       user_id: Optional[str] = None,
                       until: Optional[datetime] = None) -> tuple[list[FetchedPost], int, bool]:
        posts = [p for p in self.posts
                 if p.created_at >= since and (until is None or p.created_at < until)]
        return posts, 1, False


class CountingLLMAdapter:
    """Counts posts scored (not API calls), so assertions match per-post scoring."""

    def __init__(self):
        self.calls = 0

    def score_batch(self, post_texts: list[str], context: Optional[str]) -> list[float]:
        self.calls += len(post_texts)
        return [0.9] * len(post_texts)


def _make_domain_with_account(session):
    domain = DomainRepo(session).create("Test Domain", top_n=10)
    accounts = AccountRepo(session)
    account = accounts.get_or_create("researcher_x")
    accounts.add_to_domain(account.id, domain.id)
    return domain


def test_already_stored_posts_are_not_rescored(session):
    domain = _make_domain_with_account(session)
    x_api = FixedXAPIAdapter()
    llm = CountingLLMAdapter()

    PipelineService(session, x_api, llm).run()
    first_run_calls = llm.calls
    assert first_run_calls == 3  # every fetched post scored once

    # Second run re-fetches the identical posts; all are already in snapshots.
    PipelineService(session, x_api, llm).run()
    assert llm.calls == first_run_calls, (
        "posts already stored in a snapshot must not be sent to the LLM again"
    )

    # Stored posts are unchanged (no duplicates from the merge either).
    snaps = SnapshotRepo(session)
    stored_ids = set()
    for post in x_api.posts:
        snap = snaps.get(post.created_at.date(), domain.id)
        stored_ids.update(p["post_id"] for p in json.loads(snap.posts_json))
    assert stored_ids == {"fixed-0", "fixed-1", "fixed-2"}


def test_preset_keyword_run_persists_snapshot(session):
    rule = KeywordRepo(session).create(
        name="CRISPR watch", query="crispr base editing",
        mode=KeywordMode.preset, lookback_days=5,
    )
    x_api = FixedXAPIAdapter()
    result = PipelineService(session, x_api, CountingLLMAdapter()).run()

    assert result["keywords"][0]["status"] == "ok"
    snap_id = result["keywords"][0]["snapshot_id"]

    snap = KeywordSnapshotRepo(session).get_by_id(snap_id)
    assert snap is not None
    assert snap.rule_id == rule.id
    assert snap.rule_name == "CRISPR watch"
    assert snap.query == "crispr base editing"
    assert snap.lookback_days == 5
    assert snap.fetched_count == 3
    assert len(json.loads(snap.posts_json)) == 3
    assert snap.search_from < snap.search_to


def test_dynamic_keyword_rule_is_not_persisted_by_pipeline(session):
    KeywordRepo(session).create(
        name="ad-hoc", query="something", mode=KeywordMode.dynamic,
    )
    result = PipelineService(session, FixedXAPIAdapter(), CountingLLMAdapter()).run()
    assert result["keywords"] == []
    assert KeywordSnapshotRepo(session).get_all() == []


def test_concurrent_pipeline_run_is_rejected(session):
    from xscimon.services import pipeline as pipeline_mod

    _make_domain_with_account(session)
    svc = PipelineService(session, FixedXAPIAdapter(), CountingLLMAdapter())

    # Simulate another thread holding the lock mid-run.
    assert pipeline_mod._PIPELINE_LOCK.acquire(blocking=False)
    try:
        result = svc.run()
        assert result["status"] == "already_running"
        assert result["domains"] == []

        refetch = svc.refetch_domain(1, datetime.now(UTC).date())
        assert refetch["status"] == "error"
        assert "already in progress" in refetch["reason"]
    finally:
        pipeline_mod._PIPELINE_LOCK.release()

    # Lock released — a normal run proceeds and reacquires cleanly.
    result = svc.run()
    assert result.get("status") != "already_running"
    assert len(result["domains"]) == 1


def test_dynamic_keyword_run_logs_calls_and_respects_budget(session):
    from xscimon.repositories import LogRepo
    from xscimon.services.keyword import KeywordService

    rule = KeywordRepo(session).create(name="adhoc", query="crispr")
    svc = KeywordService(session, FixedXAPIAdapter(), CountingLLMAdapter())

    log = LogRepo(session)
    before = log.api_calls_today()
    result = svc.run_dynamic(rule.id)
    assert "error" not in result
    assert log.api_calls_today() == before + result["api_calls"]

    # Exhaust the budget, then verify the run is refused without an X call.
    from xscimon.models import LogEventType
    from xscimon.config import get_config
    threshold = get_config()["pipeline"]["max_daily_api_calls"]
    log.write(LogEventType.api_call, "budget filler", call_count=threshold)
    result = svc.run_dynamic(rule.id)
    assert "error" in result
    assert "budget" in result["error"]


def test_refetch_fetches_the_target_dates_window(session):
    domain = _make_domain_with_account(session)
    accounts = AccountRepo(session)

    now = datetime.now(UTC)
    x_api = WindowedXAPIAdapter()
    # One post exactly 48h ago (same wall-clock time → its date is exactly
    # two calendar days back) and one recent post outside that window.
    old_post_date = (now - timedelta(hours=48)).date()
    x_api.posts = [
        FetchedPost(post_id="old", author_handle="researcher_x",
                    text="Old but substantive announcement about protein folding "
                         "with plenty of characters to pass the prefilter.",
                    created_at=now - timedelta(hours=48), likes=50, retweets=10),
        FetchedPost(post_id="recent", author_handle="researcher_x",
                    text="Recent substantive announcement about protein folding "
                         "with plenty of characters to pass the prefilter.",
                    created_at=now - timedelta(hours=1), likes=50, retweets=10),
    ]

    svc = PipelineService(session, x_api, CountingLLMAdapter())
    result = svc.refetch_domain(domain.id, old_post_date)
    assert result["status"] == "complete"

    snap = SnapshotRepo(session).get(old_post_date, domain.id)
    stored_ids = [p["post_id"] for p in json.loads(snap.posts_json)]
    assert stored_ids == ["old"]

    # A windowed fetch must not advance the incremental baseline.
    account = accounts.get_by_handle("researcher_x")
    assert account.last_fetched_at is None


def test_refetch_future_date_is_rejected(session):
    domain = _make_domain_with_account(session)
    svc = PipelineService(session, WindowedXAPIAdapter(), CountingLLMAdapter())
    future = (datetime.now(UTC) + timedelta(days=2)).date()
    result = svc.refetch_domain(domain.id, future)
    assert result["status"] == "error"
    assert "future" in result["reason"]


class RecordingXAPIAdapter(FixedXAPIAdapter):
    """Records every X call so tests can assert on what was (not) requested."""

    def __init__(self, missing: set[str] = frozenset()):
        super().__init__()
        self.missing = {h.lower() for h in missing}
        self.timeline_calls: list[tuple[str, str | None]] = []
        self.lookup_batches: list[list[str]] = []

    def fetch_timeline(self, handle, since, user_id=None, until=None):
        self.timeline_calls.append((handle, user_id))
        return list(self.posts), 1, False

    def lookup_users(self, handles):
        self.lookup_batches.append(list(handles))
        return {h.lower(): UserProfile(f"uid-{h}", "bio", 100)
                for h in handles if h.lower() not in self.missing}, 1


def test_missing_user_ids_are_resolved_in_one_batch_and_persisted(session):
    domain = _make_domain_with_account(session)
    accounts = AccountRepo(session)
    for h in ("lab_a", "lab_b"):
        accounts.add_to_domain(accounts.get_or_create(h).id, domain.id)
    x_api = RecordingXAPIAdapter()

    PipelineService(session, x_api, CountingLLMAdapter()).run()
    assert len(x_api.lookup_batches) == 1
    assert sorted(x_api.lookup_batches[0]) == ["lab_a", "lab_b", "researcher_x"]
    # Timelines were fetched with the resolved id, so no per-account lookup.
    assert all(uid == f"uid-{h}" for h, uid in x_api.timeline_calls)
    assert accounts.get_by_handle("lab_a").x_user_id == "uid-lab_a"

    # Ids are stored, so the next run does no lookup at all.
    PipelineService(session, x_api, CountingLLMAdapter()).run()
    assert len(x_api.lookup_batches) == 1


def test_nonexistent_handle_is_skipped_not_fetched(session):
    _make_domain_with_account(session)
    x_api = RecordingXAPIAdapter(missing={"researcher_x"})
    PipelineService(session, x_api, CountingLLMAdapter()).run()
    assert x_api.timeline_calls == []


def test_account_in_two_domains_is_fetched_once_and_feeds_both(session):
    d1 = _make_domain_with_account(session)
    d2 = DomainRepo(session).create("Second Domain", top_n=10)
    accounts = AccountRepo(session)
    accounts.add_to_domain(accounts.get_by_handle("researcher_x").id, d2.id)
    x_api = RecordingXAPIAdapter()

    PipelineService(session, x_api, CountingLLMAdapter()).run()
    assert [h for h, _ in x_api.timeline_calls] == ["researcher_x"]

    snaps = SnapshotRepo(session)
    for domain in (d1, d2):
        ids = set()
        for post in x_api.posts:
            snap = snaps.get(post.created_at.date(), domain.id)
            ids.update(p["post_id"] for p in json.loads(snap.posts_json))
        assert ids == {"fixed-0", "fixed-1", "fixed-2"}, domain.name


class WindowRecordingXAPIAdapter(RecordingXAPIAdapter):
    """Records the (handle, since, until) of every timeline fetch."""

    def __init__(self):
        super().__init__()
        self.windows: list[tuple[str, datetime, datetime | None]] = []

    def fetch_timeline(self, handle, since, user_id=None, until=None):
        self.windows.append((handle, since, until))
        return [p for p in self.posts
                if p.created_at >= since and (until is None or p.created_at < until)], 1, False


def test_repeat_refetch_of_a_past_day_makes_no_calls(session):
    domain = _make_domain_with_account(session)
    x_api = WindowRecordingXAPIAdapter()
    day = (datetime.now(UTC) - timedelta(days=2)).date()

    first = PipelineService(session, x_api, CountingLLMAdapter()).refetch_domain(domain.id, day)
    assert first["api_calls"] == 1

    second = PipelineService(session, x_api, CountingLLMAdapter()).refetch_domain(domain.id, day)
    assert second["api_calls"] == 0
    assert second["skipped_covered"] == 1
    assert len(x_api.windows) == 1

    # force=True ignores coverage and fetches the whole day again.
    forced = PipelineService(session, x_api, CountingLLMAdapter()).refetch_domain(
        domain.id, day, force=True)
    assert forced["api_calls"] == 1
    _, since, _ = x_api.windows[-1]
    assert since == datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def test_refetch_today_only_fetches_after_the_daily_run(session):
    domain = _make_domain_with_account(session)
    accounts = AccountRepo(session)
    account = accounts.get_by_handle("researcher_x")
    # Last fetched yesterday, so today's daily run covers today from 00:00.
    accounts.stamp_fetched(account.id, datetime.now(UTC) - timedelta(days=1))
    x_api = WindowRecordingXAPIAdapter()

    PipelineService(session, x_api, CountingLLMAdapter()).run()
    assert FetchCoverageRepo(session).get(domain.id, account.id, datetime.now(UTC).date())

    today = datetime.now(UTC).date()
    # Right after the run there's nothing new to fetch.
    result = PipelineService(session, x_api, CountingLLMAdapter()).refetch_domain(domain.id, today)
    assert result["api_calls"] == 0 and len(x_api.windows) == 1

    # Pretend the run ended 2h ago: the re-fetch asks only for the last 2h.
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    if two_hours_ago.date() == today:
        FetchCoverageRepo(session).set(domain.id, account.id, today, two_hours_ago)
        PipelineService(session, x_api, CountingLLMAdapter()).refetch_domain(domain.id, today)
        assert x_api.windows[-1][1] == two_hours_ago


def test_refetch_fetches_newly_added_account_but_skips_covered_one(session):
    domain = _make_domain_with_account(session)
    x_api = WindowRecordingXAPIAdapter()
    day = (datetime.now(UTC) - timedelta(days=2)).date()
    PipelineService(session, x_api, CountingLLMAdapter()).refetch_domain(domain.id, day)

    accounts = AccountRepo(session)
    accounts.add_to_domain(accounts.get_or_create("new_lab").id, domain.id)
    result = PipelineService(session, x_api, CountingLLMAdapter()).refetch_domain(domain.id, day)
    assert result["api_calls"] == 1
    assert [h for h, _, _ in x_api.windows] == ["researcher_x", "new_lab"]


def test_coverage_merges_overlapping_fetches_and_keeps_newest_disjoint_span(session):
    domain = _make_domain_with_account(session)
    account = AccountRepo(session).get_by_handle("researcher_x")
    svc = PipelineService(session, WindowRecordingXAPIAdapter(), CountingLLMAdapter())
    day = date(2026, 1, 10)
    h = lambda n: datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=n)
    cov = FetchCoverageRepo(session)

    svc._record_coverage(domain.id, account.id, h(6), h(9))
    assert cov.get(domain.id, account.id, day) == (h(6), h(9))
    # Overlapping earlier fetch extends the span backwards.
    svc._record_coverage(domain.id, account.id, h(-2), h(7))
    assert cov.get(domain.id, account.id, day) == (h(0), h(9))
    # Disjoint but later fetch replaces it (delta fetches build on the newest span).
    svc._record_coverage(domain.id, account.id, h(12), h(14))
    assert cov.get(domain.id, account.id, day) == (h(12), h(14))
    # Disjoint earlier fetch doesn't replace a later span.
    svc._record_coverage(domain.id, account.id, h(1), h(2))
    assert cov.get(domain.id, account.id, day) == (h(12), h(14))
    # Spanning midnight fills the rest of the day and starts the next one.
    svc._record_coverage(domain.id, account.id, h(14), h(26))
    assert cov.get(domain.id, account.id, day) == (h(12), h(24))
    assert cov.get(domain.id, account.id, day + timedelta(days=1)) == (h(24), h(26))


def test_uncovered_span_partial_first_day_and_exact_gaps():
    day = date(2026, 1, 10)
    h = lambda n: datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=n)
    span = PipelineService._uncovered_span
    # Window starts at 22:00 (local midnight ahead of UTC); that tail is covered.
    cov = {day: {1: (h(22), h(24))}, day + timedelta(days=1): {1: (h(24), h(30))}}
    assert span(cov, 1, h(22), h(30)) is None
    assert span(cov, 1, h(22), h(36)) == (h(30), h(36))
    # Gaps on both sides: one request spanning both.
    assert span(cov, 1, h(20), h(36)) == (h(20), h(36))
    assert span({}, 1, h(22), h(36)) == (h(22), h(36))
    # Only an older gap (e.g. window widened, or a capped fetch kept only the
    # newest posts): fetch exactly that gap, not the covered recent part again.
    assert span(cov, 1, h(10), h(30)) == (h(10), h(22))


def test_fetch_domain_delta_over_days_then_skips_everything(session):
    domain = _make_domain_with_account(session)
    x_api = WindowRecordingXAPIAdapter()

    first = PipelineService(session, x_api, CountingLLMAdapter()).fetch_domain(domain.id, days=3)
    assert first["api_calls"] == 1
    _, since, _ = x_api.windows[0]
    start, _ = PipelineService._days_window(3)
    assert since == start  # nothing covered yet → whole window

    second = PipelineService(session, x_api, CountingLLMAdapter()).fetch_domain(domain.id, days=3)
    assert second["api_calls"] == 0 and second["skipped_covered"] == 1

    forced = PipelineService(session, x_api, CountingLLMAdapter()).fetch_domain(
        domain.id, days=3, force=True)
    assert forced["api_calls"] == 1
    assert x_api.windows[-1][1] <= start + timedelta(seconds=1)


def test_fetch_domain_starts_at_first_gap_across_days(session):
    domain = _make_domain_with_account(session)
    account = AccountRepo(session).get_by_handle("researcher_x")
    cov = FetchCoverageRepo(session)
    start, end = PipelineService._days_window(3)
    # Fully cover the first UTC day of the window, half-cover the next one.
    d0 = start.date()
    d0_end = datetime.combine(d0, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    cov.set(domain.id, account.id, d0, d0_end)
    cov.set(domain.id, account.id, d0 + timedelta(days=1), d0_end + timedelta(hours=12))

    x_api = WindowRecordingXAPIAdapter()
    PipelineService(session, x_api, CountingLLMAdapter()).fetch_domain(domain.id, days=3)
    expected = d0_end + timedelta(hours=12)
    if expected < end:
        assert x_api.windows[0][1] == expected


def test_run_with_days_is_delta_for_every_domain(session):
    d1 = _make_domain_with_account(session)
    d2 = DomainRepo(session).create("Second", top_n=10)
    accounts = AccountRepo(session)
    accounts.add_to_domain(accounts.get_or_create("lab_b").id, d2.id)
    x_api = WindowRecordingXAPIAdapter()

    PipelineService(session, x_api, CountingLLMAdapter()).run(days=7)
    assert sorted(h for h, _, _ in x_api.windows) == ["lab_b", "researcher_x"]

    PipelineService(session, x_api, CountingLLMAdapter()).run(days=7)
    assert len(x_api.windows) == 2  # second run: everything already covered


def test_window_fetch_advances_baseline_only_when_contiguous(session):
    domain = _make_domain_with_account(session)
    accounts = AccountRepo(session)
    account = accounts.get_by_handle("researcher_x")
    x_api = WindowRecordingXAPIAdapter()

    # Last fetched 10 days ago: a 1-day window leaves a gap, so the incremental
    # baseline must still pick up from 10 days ago.
    ten_days_ago = datetime.now(UTC) - timedelta(days=10)
    accounts.stamp_fetched(account.id, ten_days_ago)
    PipelineService(session, x_api, CountingLLMAdapter()).fetch_domain(domain.id, days=1)
    session.refresh(account)
    assert abs(account.last_fetched_at.replace(tzinfo=UTC) - ten_days_ago) < timedelta(seconds=1)

    # Last fetched inside the window: the fetch joins up, so the baseline advances.
    accounts.stamp_fetched(account.id, datetime.now(UTC) - timedelta(minutes=30))
    PipelineService(session, x_api, CountingLLMAdapter()).fetch_domain(
        domain.id, days=1, force=True)
    session.refresh(account)
    assert account.last_fetched_at.replace(tzinfo=UTC) > datetime.now(UTC) - timedelta(minutes=2)


class BusyAccountXAPIAdapter(WindowRecordingXAPIAdapter):
    """An account posting every few hours: a long window returns well over 100
    posts. `truncated` says whether the page cap cut the fetch short."""

    def __init__(self, truncated: bool):
        super().__init__()
        self.truncated = truncated
        now = datetime.now(UTC)
        self.posts = [
            FetchedPost(
                post_id=f"busy-{i}",
                author_handle="researcher_x",
                text=f"Substantive research update number {i} on protein design "
                     f"with enough characters to pass the prefilter easily.",
                created_at=now - timedelta(hours=1 + 5 * i),
                likes=5,
                retweets=1,
            )
            for i in range(150)  # spans ~31 days
        ]

    def fetch_timeline(self, handle, since, user_id=None, until=None):
        posts, calls, _ = super().fetch_timeline(handle, since, user_id, until)
        return posts, calls, self.truncated


def test_complete_fetch_of_100_plus_posts_advances_baseline(session):
    _make_domain_with_account(session)
    accounts = AccountRepo(session)
    account = accounts.get_by_handle("researcher_x")
    forty_days_ago = datetime.now(UTC) - timedelta(days=40)
    accounts.stamp_fetched(account.id, forty_days_ago)

    # 150 posts but the fetch reached `since`: the whole backlog is covered, so
    # the next incremental run must start from now, not re-read 40 days again.
    x_api = BusyAccountXAPIAdapter(truncated=False)
    PipelineService(session, x_api, CountingLLMAdapter()).run()
    session.refresh(account)
    assert account.last_fetched_at.replace(tzinfo=UTC) > datetime.now(UTC) - timedelta(minutes=2)

    PipelineService(session, x_api, CountingLLMAdapter()).run()
    _, second_since, _ = x_api.windows[-1]
    assert second_since > datetime.now(UTC) - timedelta(minutes=2)


def test_truncated_fetch_keeps_baseline(session):
    _make_domain_with_account(session)
    accounts = AccountRepo(session)
    account = accounts.get_by_handle("researcher_x")
    forty_days_ago = datetime.now(UTC) - timedelta(days=40)
    accounts.stamp_fetched(account.id, forty_days_ago)

    # The page cap stopped short of `since`: posts in between are missing, so the
    # baseline must stay put.
    PipelineService(session, BusyAccountXAPIAdapter(truncated=True), CountingLLMAdapter()).run()
    session.refresh(account)
    assert abs(account.last_fetched_at.replace(tzinfo=UTC) - forty_days_ago) < timedelta(seconds=1)


def test_forced_refetch_refreshes_engagement_without_llm(session):
    domain = _make_domain_with_account(session)
    x_api = WindowRecordingXAPIAdapter()
    llm = CountingLLMAdapter()
    PipelineService(session, x_api, llm).fetch_domain(domain.id, days=1)
    scored = llm.calls

    def stored():
        out = {}
        for p in x_api.posts:
            snap = SnapshotRepo(session).get(p.created_at.date(), domain.id)
            if snap:
                out.update({d["post_id"]: d for d in json.loads(snap.posts_json)})
        return out

    before = stored()["fixed-1"]
    x_api.posts[1].likes = 5000

    # Delta fetch skips (covered), so counts stay stale.
    PipelineService(session, x_api, llm).fetch_domain(domain.id, days=1)
    assert stored()["fixed-1"]["likes"] == before["likes"]

    result = PipelineService(session, x_api, llm).fetch_domain(domain.id, days=1, force=True)
    after = stored()["fixed-1"]
    assert after["likes"] == 5000
    assert after["final_score"] > before["final_score"]
    assert after["relevance_score"] == before["relevance_score"]
    assert result["engagement_refreshed"] == 1
    assert llm.calls == scored  # no re-scoring
