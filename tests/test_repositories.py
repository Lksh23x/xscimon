from xscimon.models import CredibilityLevel, KeywordMode
from xscimon.repositories import DomainRepo, AccountRepo, KeywordRepo, SnapshotRepo, LogRepo
from xscimon.models import DomainStatus, LogEventType
from datetime import date


def test_domain_crud(session):
    repo = DomainRepo(session)
    d = repo.create("Genomics", top_n=5)
    assert d.id is not None
    assert repo.get_by_id(d.id).name == "Genomics"

    d.name = "Genomics & Proteomics"
    repo.update(d)
    assert repo.get_by_id(d.id).name == "Genomics & Proteomics"

    assert repo.delete(d.id)
    assert repo.get_by_id(d.id) is None


def test_account_credibility_is_global(session):
    a_repo = AccountRepo(session)
    d_repo = DomainRepo(session)

    d1 = d_repo.create("Domain A")
    d2 = d_repo.create("Domain B")

    account = a_repo.get_or_create("researcher_x")
    a_repo.add_to_domain(account.id, d1.id)
    a_repo.add_to_domain(account.id, d2.id)

    a_repo.set_credibility(account.id, CredibilityLevel.high)

    # Credibility should be visible regardless of which domain we query through
    for_d1 = a_repo.get_for_domain(d1.id)
    for_d2 = a_repo.get_for_domain(d2.id)
    assert for_d1[0].credibility == CredibilityLevel.high
    assert for_d2[0].credibility == CredibilityLevel.high


def test_domain_deletion_cascades(session):
    a_repo = AccountRepo(session)
    d_repo = DomainRepo(session)

    d = d_repo.create("ToDelete")
    account = a_repo.get_or_create("someuser")
    a_repo.add_to_domain(account.id, d.id)

    a_repo.delete_domain_associations(d.id)
    d_repo.delete(d.id)

    assert d_repo.get_by_id(d.id) is None
    # Account record itself is preserved
    assert a_repo.get_by_handle("someuser") is not None


def test_keyword_promote(session):
    repo = KeywordRepo(session)
    rule = repo.create("test", "#CRISPR base editing", mode=KeywordMode.dynamic)
    assert rule.mode == KeywordMode.dynamic

    promoted = repo.promote_to_preset(rule.id)
    assert promoted.mode == KeywordMode.preset
    assert rule.id in [r.id for r in repo.get_presets()]


def test_snapshot_upsert(session):
    d_repo = DomainRepo(session)
    s_repo = SnapshotRepo(session)

    d = d_repo.create("Chem")
    today = date.today()

    snap = s_repo.upsert(today, d.id, DomainStatus.complete, [{"text": "post1"}], 3)
    assert snap.status == DomainStatus.complete

    # Re-upsert should update, not duplicate
    snap2 = s_repo.upsert(today, d.id, DomainStatus.partial, [{"text": "post1"}], 5,
                          status_reason="threshold")
    assert snap2.id == snap.id
    assert snap2.status == DomainStatus.partial


def test_log_search(session):
    repo = LogRepo(session)
    repo.write(LogEventType.api_call, "Fetched @alice timeline", call_count=2)
    repo.write(LogEventType.error, "Rate limit hit for domain Genomics")

    all_logs = repo.search()
    assert len(all_logs) == 2

    filtered = repo.search("alice")
    assert len(filtered) == 1
    assert "alice" in filtered[0].message


def test_log_clear_all_and_api_call_sum(session):
    log = LogRepo(session)
    log.write(LogEventType.api_call, "call one", call_count=3)
    log.write(LogEventType.api_call, "call two", call_count=2)
    log.write(LogEventType.error, "not an api call", call_count=99)  # excluded by type
    assert log.api_calls_today() == 5

    log.clear_all()
    assert log.search() == []
    assert log.api_calls_today() == 0


def test_range_digest_merges_across_days(session):
    from datetime import timedelta
    from xscimon.services.digest import DigestService

    domain = DomainRepo(session).create("Range Domain")
    snaps = SnapshotRepo(session)
    today = date.today()

    # Same post appears on two days with different scores; the newer copy wins.
    snaps.upsert(today, domain.id, DomainStatus.complete,
                 [{"post_id": "a", "final_score": 0.9},
                  {"post_id": "b", "final_score": 0.4}], 1)
    snaps.upsert(today - timedelta(days=1), domain.id, DomainStatus.partial,
                 [{"post_id": "a", "final_score": 0.2},
                  {"post_id": "c", "final_score": 0.7}], 1)

    digest = DigestService(session).get_range_digest(days=3)
    dom = next(d for d in digest["domains"] if d["domain_id"] == domain.id)

    posts = {p["post_id"]: p for p in dom["posts"]}
    assert set(posts) == {"a", "b", "c"}
    assert posts["a"]["final_score"] == 0.9  # newer snapshot's copy kept
    assert [p["post_id"] for p in dom["posts"]] == ["a", "c", "b"]  # sorted by score
    assert dom["status"] == "complete"  # status comes from the latest snapshot


def test_history_periods_count_stored_posts(session):
    """The history status dot keys off stored posts, not pipeline status:
    a 'complete' run that stored zero posts must report posts == 0."""
    from datetime import timedelta
    from xscimon.services import DigestService

    domain = DomainRepo(session).create("AI research")
    repo = SnapshotRepo(session)
    today = date.today()
    post = {"post_id": "p1", "author_handle": "a", "text": "t",
            "created_at": "2026-01-01T00:00:00+00:00", "likes": 1, "retweets": 0}
    repo.upsert(today, domain.id, DomainStatus.complete, [], 1)
    repo.upsert(today - timedelta(days=1), domain.id, DomainStatus.complete, [post], 1)
    # Two empty days in the same past week — the week must still read as empty
    repo.upsert(today - timedelta(days=8), domain.id, DomainStatus.complete, [], 1)
    repo.upsert(today - timedelta(days=9), domain.id, DomainStatus.complete, [], 1)

    periods = DigestService(session).get_history_periods(today, domain.id)
    entries = {e["from_date"]: e["stats"] for s in periods for e in s["entries"]}

    assert entries[today.isoformat()]["posts"] == 0
    assert entries[(today - timedelta(days=1)).isoformat()]["posts"] == 1
    week_stats = next(s for k, s in entries.items() if k <= (today - timedelta(days=9)).isoformat())
    assert week_stats["posts"] == 0


def test_log_search_filters_by_day_and_pages(session):
    from datetime import datetime, timedelta
    from xscimon.models import LogEntry
    repo = LogRepo(session)
    day = date(2026, 3, 5)
    base = datetime(2026, 3, 5, 0, 0)
    for i in range(5):
        session.add(LogEntry(event_type=LogEventType.api_call, message=f"on day {i}",
                             timestamp=base + timedelta(hours=i * 5)))
    session.add(LogEntry(event_type=LogEventType.error, message="day before",
                         timestamp=base - timedelta(seconds=1)))
    session.add(LogEntry(event_type=LogEventType.error, message="day after",
                         timestamp=base + timedelta(days=1)))
    session.commit()

    assert repo.count(day=day) == 5
    page1 = repo.search(day=day, limit=3)
    page2 = repo.search(day=day, limit=3, offset=3)
    assert [e.message for e in page1] == ["on day 4", "on day 3", "on day 2"]
    assert [e.message for e in page2] == ["on day 1", "on day 0"]
    assert repo.count(query="day 3", day=day) == 1
    assert repo.count() == 7
    assert repo.date_bounds() == (date(2026, 3, 4), date(2026, 3, 6))
