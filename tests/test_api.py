from datetime import date


def test_health(client):
    assert client.get("/health").status_code == 200


def test_domain_lifecycle(client):
    r = client.post("/api/domains", json={"name": "Genomics", "top_n": 5})
    assert r.status_code == 201
    domain_id = r.json()["id"]

    r = client.get("/api/domains")
    assert any(d["id"] == domain_id for d in r.json())

    r = client.patch(f"/api/domains/{domain_id}", json={"skill_md": "Focus on CRISPR."})
    assert r.status_code == 200

    r = client.delete(f"/api/domains/{domain_id}")
    assert r.status_code == 204


def test_account_management(client):
    domain_id = client.post("/api/domains", json={"name": "Bio"}).json()["id"]

    r = client.post(f"/api/domains/{domain_id}/accounts",
                    json={"handle": "researcher_a", "display_name": "Dr. A"})
    assert r.status_code == 201
    account_id = r.json()["id"]

    r = client.patch(f"/api/domains/accounts/{account_id}/credibility",
                     json={"credibility": "high"})
    assert r.status_code == 200
    assert r.json()["credibility"] == "high"

    accounts = client.get(f"/api/domains/{domain_id}/accounts").json()
    assert any(a["handle"] == "researcher_a" for a in accounts)


def test_keyword_dynamic_and_promote(client):
    r = client.post("/api/keywords", json={
        "name": "CRISPR filter", "query": "#CRISPR base editing",
        "mode": "dynamic", "lookback_days": 7,
    })
    assert r.status_code == 201
    rule_id = r.json()["id"]

    # Run the dynamic filter — uses MockXAPIAdapter, returns preview results
    r = client.post(f"/api/keywords/{rule_id}/run")
    assert r.status_code == 200
    data = r.json()
    assert "posts" in data
    assert len(data["posts"]) > 0

    # Promote to preset
    r = client.post(f"/api/keywords/{rule_id}/promote")
    assert r.status_code == 200
    assert r.json()["mode"] == "preset"


def test_pipeline_trigger(client):
    client.post("/api/domains", json={"name": "Chemistry"})
    r = client.post("/api/digest/run")
    assert r.status_code == 202


def test_digest_today(client):
    client.post("/api/domains", json={"name": "Physics"})
    client.post("/api/digest/run")
    r = client.get("/api/digest/today")
    assert r.status_code == 200
    assert "domains" in r.json()


def test_admin_logs(client):
    client.post("/api/digest/run")
    r = client.get("/api/admin/logs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r = client.get("/api/admin/logs?q=pipeline")
    assert r.status_code == 200


def _csv_upload(client, domain_id: int, csv_text: str):
    return client.post(
        f"/api/domains/{domain_id}/accounts/import",
        files={"file": ("handles.csv", csv_text.encode(), "text/csv")},
    )


def test_csv_import_valid(client):
    domain_id = client.post("/api/domains", json={"name": "CSV Domain"}).json()["id"]
    r = _csv_upload(client, domain_id, "researcher_a\nlab_account\nscientist_b\n")
    assert r.status_code == 201
    data = r.json()
    assert data["loaded"] == 3
    assert data["invalid"] == 0
    assert data["duplicates"] == 0


def test_csv_import_strips_at_sign(client):
    domain_id = client.post("/api/domains", json={"name": "At Domain"}).json()["id"]
    r = _csv_upload(client, domain_id, "@handle_one\n@handle_two\n")
    assert r.status_code == 201
    assert r.json()["loaded"] == 2


def test_csv_import_invalid_handles(client):
    domain_id = client.post("/api/domains", json={"name": "Invalid Domain"}).json()["id"]
    r = _csv_upload(client, domain_id, "good_handle\nbad handle!\n!!!\n")
    assert r.status_code == 201
    data = r.json()
    assert data["loaded"] == 1
    assert data["invalid"] == 2
    assert "bad handle!" in data["invalid_handles"]
    assert "!!!" in data["invalid_handles"]


def test_csv_import_duplicates(client):
    domain_id = client.post("/api/domains", json={"name": "Dup Domain"}).json()["id"]
    _csv_upload(client, domain_id, "existing_handle\n")
    r = _csv_upload(client, domain_id, "existing_handle\nnew_handle\n")
    assert r.status_code == 201
    data = r.json()
    assert data["loaded"] == 1
    assert data["duplicates"] == 1
    assert "existing_handle" in data["duplicate_handles"]


def test_csv_import_multi_column_rejected(client):
    domain_id = client.post("/api/domains", json={"name": "Multi Col"}).json()["id"]
    r = _csv_upload(client, domain_id, "handle,display_name\nresearcher_a,Dr. A\n")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "expected_formats" in detail
    assert detail["problem_rows"] == [1, 2]


def test_csv_import_empty_file_rejected(client):
    domain_id = client.post("/api/domains", json={"name": "Empty"}).json()["id"]
    r = _csv_upload(client, domain_id, "\n\n")
    assert r.status_code == 422


def test_csv_import_logs_result(client):
    domain_id = client.post("/api/domains", json={"name": "Log Domain"}).json()["id"]
    _csv_upload(client, domain_id, "handle_a\nbad handle!\n")
    logs = client.get("/api/admin/logs?q=csv_import").json()
    assert any("csv_import" in (e.get("event_type") or "") for e in logs)


def test_email_send(client):
    client.post("/api/domains", json={"name": "Bio"})
    r = client.post("/api/email/send", json={
        "date": date.today().isoformat(),
        "to": "test@example.com",
    })
    assert r.status_code == 200


def test_email_send_without_recipient_returns_400(client, monkeypatch):
    monkeypatch.delenv("EMAIL_TO_DEFAULT", raising=False)
    r = client.post("/api/email/send", json={"date": "2026-07-15"})
    assert r.status_code == 400
    assert "recipient" in r.json()["detail"].lower()


def test_x_api_failure_surfaces_as_502_not_account_missing(client):
    from xscimon.adapters import get_x_adapter

    class RaisingXAPIAdapter:
        def verify_account(self, handle):
            raise RuntimeError("rate limit exceeded")

    from xscimon.main import app
    app.dependency_overrides[get_x_adapter] = lambda: RaisingXAPIAdapter()

    r = client.get("/api/domains/accounts/verify?handle=someone")
    assert r.status_code == 502
    assert "X API error" in r.json()["detail"]

    domain_id = client.post("/api/domains", json={"name": "Err Domain"}).json()["id"]
    r = client.post(f"/api/domains/{domain_id}/accounts", json={"handle": "someone"})
    assert r.status_code == 502


def test_history_filter_by_domain(client, session):
    from xscimon.models import DomainStatus
    from xscimon.repositories import DomainRepo, SnapshotRepo

    d_repo, s_repo = DomainRepo(session), SnapshotRepo(session)
    genomics = d_repo.create("Genomics")
    physics = d_repo.create("Physics")
    today = date.today()
    s_repo.upsert(today, genomics.id, DomainStatus.complete,
                  [{"post_id": "g1", "text": "genomics post", "final_score": 0.9}], 1)
    s_repo.upsert(today, physics.id, DomainStatus.complete,
                  [{"post_id": "p1", "text": "physics post", "final_score": 0.8}], 1)

    r = client.get(f"/history?domain={genomics.id}")
    assert r.status_code == 200
    assert f'href="/history?domain={genomics.id}" class="domain-tab active"' in r.text

    r = client.get("/htmx/history/period", params={
        "from_date": today.isoformat(), "to_date": today.isoformat(),
        "domain_id": genomics.id,
    })
    assert "genomics post" in r.text
    assert "physics post" not in r.text

    r = client.get("/htmx/history/period", params={
        "from_date": today.isoformat(), "to_date": today.isoformat(),
    })
    assert "genomics post" in r.text and "physics post" in r.text


def test_enrich_uses_one_batched_call(client, session):
    from xscimon.repositories import AccountRepo, LogRepo
    r = client.post("/api/domains", json={"name": "Enrich"})
    domain_id = r.json()["id"]
    repo = AccountRepo(session)
    for i in range(5):
        a = repo.get_or_create(f"imported_{i}", description="from csv")
        repo.add_to_domain(a.id, domain_id)

    r = client.post(f"/api/domains/{domain_id}/accounts/enrich")
    assert r.json()["enriched"] == 5
    assert LogRepo(session).api_calls_today() == 1
    a = repo.get_by_handle("imported_0")
    assert a.x_user_id == "mock-uid-imported_0"
    assert a.description == "from csv"  # existing bio is kept


def test_htmx_fetch_domain_returns_panel_and_tab_count(client):
    domain_id = client.post("/api/domains", json={"name": "Fetchable"}).json()["id"]
    client.post(f"/api/domains/{domain_id}/accounts", json={"handle": "lab_x"})

    r = client.post(f"/htmx/domains/{domain_id}/fetch?days=3")
    assert r.status_code == 200
    assert f'id="domain-count-{domain_id}"' in r.text and 'hx-swap-oob="true"' in r.text
    assert f"/htmx/domains/{domain_id}/fetch?days=3&amp;force=true" in r.text \
        or f"/htmx/domains/{domain_id}/fetch?days=3&force=true" in r.text

    page = client.get("/?window=3").text
    assert 'id="fetch-domain-btn"' in page
    assert "/htmx/pipeline/run?days=3" in page


def test_90_day_window_is_accepted(client):
    r = client.get("/?window=90")
    assert r.status_code == 200
    assert "/htmx/pipeline/run?days=90" in r.text and ">90d<" in r.text.replace("\n", "").replace(" ", "")


def test_admin_log_paging_and_day_filter(client, session):
    from datetime import datetime, timedelta
    from xscimon.models import LogEntry, LogEventType
    base = datetime(2026, 3, 5, 1, 0)
    for i in range(130):
        session.add(LogEntry(event_type=LogEventType.api_call, message=f"entry {i}",
                             timestamp=base + timedelta(minutes=i)))
    session.add(LogEntry(event_type=LogEventType.error, message="other day",
                         timestamp=base + timedelta(days=2)))
    session.commit()

    page = client.get("/admin").text
    assert 'type="date"' in page and 'min="2026-03-05"' in page and 'max="2026-03-07"' in page
    assert "Showing 100 of 131" in page

    r = client.get("/htmx/logs?day=2026-03-05&offset=100")
    assert r.text.count("<tr") == 31  # 30 remaining rows + footer
    assert "All 130 entries shown" in r.text

    r = client.get("/htmx/logs?day=2026-03-06")
    assert "No log entries on 2026-03-06 (UTC)" in r.text


def test_cross_origin_write_rejected(client):
    r = client.post("/api/digest/run", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/domains", json={"name": "X"},
                    headers={"Referer": "https://evil.example/page"})
    assert r.status_code == 403


def test_same_origin_write_allowed(client):
    r = client.post("/api/domains", json={"name": "SameOrigin"},
                    headers={"Origin": "http://testserver"})
    assert r.status_code == 201


def test_untrusted_host_rejected(client):
    assert client.get("/health", headers={"Host": "rebind.evil.example"}).status_code == 400


def test_keywords_page_escapes_script_breakout(client):
    payload = "</script><script>alert(1)</script>"
    r = client.post("/api/keywords", json={"name": payload, "query": "crispr"})
    assert r.status_code == 201
    html = client.get("/keywords").text
    assert "</script><script>alert(1)" not in html
