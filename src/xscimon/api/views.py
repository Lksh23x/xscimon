"""HTML-serving routes for the xscimon frontend."""
import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from sqlmodel import Session

from ..database import get_session
from ..adapters import get_x_adapter, get_llm_adapter, XAPIAdapter, LLMAdapter, is_mock_mode
from ..models import LogEventType
from ..repositories import DomainRepo, KeywordRepo, KeywordSnapshotRepo, LogRepo
from ..services.digest import DigestService
from ..services.pipeline import PipelineService
from ..services.keyword import KeywordService

router = APIRouter()

_TEMPLATE_DIR = Path(__file__).parents[1] / "frontend" / "templates"
# Default template cache. cache_size=0 was a workaround for a Jinja2 LRU-cache
# issue on Python 3.14 that is fixed in Jinja2 3.1.6.
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)
TEMPLATES = Jinja2Templates(env=_jinja_env)

# ---------------------------------------------------------------------------
# Jinja2 custom filters
# ---------------------------------------------------------------------------


def _format_dt(value: str | None) -> str:
    """Format ISO datetime string as 'May 17, 10:23'."""
    if not value:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(value)
        return dt.strftime("%b %-d, %H:%M")
    except Exception:
        return str(value)


def _truncate(value: str | None, length: int = 280) -> str:
    """Truncate text to N chars, appending ellipsis."""
    if not value:
        return ""
    if len(value) <= length:
        return value
    return value[:length] + "…"


def _tojson_str(value) -> str:
    """Serialize value to a JSON string (not marked safe — autoescape will HTML-encode it)."""
    return json.dumps(value, ensure_ascii=True)


def _format_followers(count) -> str:
    if count is None:
        return ""
    count = int(count)
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def _format_date(value) -> str:
    """Format a datetime or ISO string as 'May 28'."""
    if value is None:
        return ""
    try:
        from datetime import datetime as dt
        if isinstance(value, str):
            value = dt.fromisoformat(value)
        return value.strftime("%b %-d")
    except Exception:
        return str(value)


def _relative_age(value) -> str:
    """Return a human-readable age relative to today: 'today', '2d ago', '1w ago'."""
    if not value:
        return ""
    try:
        from datetime import datetime as dt, date as date_t, UTC
        if isinstance(value, str):
            value = dt.fromisoformat(value)
        today = date_t.today()
        post_date = value.date() if hasattr(value, "date") else value
        delta = (today - post_date).days
        if delta <= 0:
            return "today"
        if delta == 1:
            return "yesterday"
        if delta < 7:
            return f"{delta}d ago"
        if delta < 14:
            return "1w ago"
        return f"{delta // 7}w ago"
    except Exception:
        return ""


TEMPLATES.env.filters["format_dt"] = _format_dt
TEMPLATES.env.filters["truncate_text"] = _truncate
TEMPLATES.env.filters["tojson_str"] = _tojson_str
TEMPLATES.env.filters["format_followers"] = _format_followers
TEMPLATES.env.filters["format_date"] = _format_date
TEMPLATES.env.filters["relative_age"] = _relative_age
TEMPLATES.env.globals["mock_mode"] = is_mock_mode()

from .. import __version__, __build__  # noqa: E402
TEMPLATES.env.globals["app_version"] = __version__
TEMPLATES.env.globals["app_build"] = __build__


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session),
          window: int = Query(default=1, ge=1, le=90)):
    digest_service = DigestService(session)
    today = date.today()
    if window == 1:
        digest = digest_service.get_digest(today)
    else:
        digest = digest_service.get_range_digest(window)
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {"digest": digest, "today": today.isoformat(), "window": window},
    )


@router.get("/history/keywords/{snapshot_id}", response_class=HTMLResponse)
def keyword_snapshot_detail(
    snapshot_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    repo = KeywordSnapshotRepo(session)
    snap = repo.get_by_id(snapshot_id)
    if not snap:
        return HTMLResponse("<p>Snapshot not found.</p>", status_code=404)
    posts = json.loads(snap.posts_json)
    return TEMPLATES.TemplateResponse(
        request,
        "keyword_snapshot.html",
        {"snap": snap, "posts": posts},
    )


@router.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    domain: int | None = Query(None),
    session: Session = Depends(get_session),
):
    digest_service = DigestService(session)
    domains = DomainRepo(session).get_all()
    if domain is not None and domain not in {d.id for d in domains}:
        domain = None
    today = date.today()
    periods = digest_service.get_history_periods(today, domain)
    raw_snaps = KeywordSnapshotRepo(session).get_all()
    keyword_snaps = [
        {
            "id": s.id,
            "rule_name": s.rule_name,
            "query": s.query,
            "lookback_days": s.lookback_days,
            "search_to": s.search_to,
            "post_count": len(json.loads(s.posts_json)),
        }
        for s in raw_snaps
    ]
    return TEMPLATES.TemplateResponse(
        request,
        "history.html",
        {
            "periods": periods,
            "keyword_snaps": keyword_snaps,
            "domains": domains,
            "selected_domain": domain,
        },
    )


@router.get("/htmx/history/period", response_class=HTMLResponse)
def htmx_history_period(
    request: Request,
    from_date: str = Query(...),
    to_date: str = Query(...),
    domain_id: int | None = Query(None),
    session: Session = Depends(get_session),
):
    """Return ranked post cards for a date range — called lazily when a period is expanded."""
    digest_service = DigestService(session)
    posts = digest_service.get_range_posts(
        date.fromisoformat(from_date),
        date.fromisoformat(to_date),
        domain_id,
    )
    return TEMPLATES.TemplateResponse(
        request,
        "partials/history_posts.html",
        {"posts": posts},
    )


@router.get("/domains", response_class=HTMLResponse)
def domains(request: Request, session: Session = Depends(get_session)):
    domain_repo = DomainRepo(session)
    from ..repositories import AccountRepo
    account_repo = AccountRepo(session)
    all_domains = domain_repo.get_all()
    domains_with_accounts = []
    for domain in all_domains:
        # list of (Account, added_at) tuples
        accounts_with_meta = account_repo.get_for_domain_with_meta(domain.id)
        domains_with_accounts.append({
            "domain": domain,
            "accounts": accounts_with_meta,
        })
    return TEMPLATES.TemplateResponse(
        request,
        "domains.html",
        {"domains_with_accounts": domains_with_accounts},
    )


@router.get("/keywords", response_class=HTMLResponse)
def keywords(request: Request, session: Session = Depends(get_session)):
    keyword_repo = KeywordRepo(session)
    rules = keyword_repo.get_all()
    rules_data = [{
        "id": r.id,
        "name": r.name,
        "query": r.query,
        "mode": r.mode.value,
        "lookback_days": r.lookback_days,
        "priority_weight": r.priority_weight,
        "skill_md": r.skill_md or "",
    } for r in rules]
    return TEMPLATES.TemplateResponse(
        request,
        "keywords.html",
        {"rules": rules, "rules_data": rules_data},
    )


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request, session: Session = Depends(get_session)):
    log_repo = LogRepo(session)
    calls_today = log_repo.api_calls_today()
    oldest, newest = log_repo.date_bounds()
    from ..config import get_config
    threshold = get_config()["pipeline"]["max_daily_api_calls"]
    return TEMPLATES.TemplateResponse(
        request,
        "admin.html",
        {
            **_log_page(log_repo, None, None, 0),
            "calls_today": calls_today,
            "threshold": threshold,
            "log_oldest": oldest,
            "log_newest": newest,
        },
    )


LOG_PAGE_SIZE = 100


def _log_page(log_repo: LogRepo, q: str | None, day: date | None, offset: int) -> dict:
    """Template context for one page of the audit log plus its "load more" row."""
    logs = log_repo.search(query=q, day=day, limit=LOG_PAGE_SIZE, offset=offset)
    return {
        "logs": logs,
        "log_total": log_repo.count(query=q, day=day),
        "log_shown": offset + len(logs),
        "log_q": q or "",
        "log_day": day.isoformat() if day else "",
        "log_page_size": LOG_PAGE_SIZE,
    }


# ---------------------------------------------------------------------------
# HTMX partial routes
# ---------------------------------------------------------------------------


@router.get("/htmx/logs", response_class=HTMLResponse)
def htmx_logs(
    request: Request,
    q: str | None = None,
    day: str | None = None,
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Audit log rows, filtered by text and/or UTC day. offset > 0 returns the next
    page, which replaces the previous page's "load more" row."""
    try:
        day_filter = date.fromisoformat(day) if day else None
    except ValueError:
        day_filter = None
    return TEMPLATES.TemplateResponse(
        request,
        "partials/log_entries.html",
        _log_page(LogRepo(session), q or None, day_filter, offset),
    )


@router.post("/htmx/pipeline/run", response_class=HTMLResponse)
def htmx_pipeline_run(
    request: Request,
    days: int | None = Query(None, ge=1, le=90),
    session: Session = Depends(get_session),
    x_api: XAPIAdapter = Depends(get_x_adapter),
    llm: LLMAdapter = Depends(get_llm_adapter),
):
    pipeline_service = PipelineService(session, x_api, llm)
    try:
        result = pipeline_service.run(days=days)
        if result.get("status") == "already_running":
            status = "pending"
            message = "A pipeline run is already in progress."
        else:
            status = "complete"
            message = f"Pipeline finished for {result['date']}. Domains: {len(result['domains'])}"
    except Exception as exc:
        status = "error"
        message = str(exc)
    return TEMPLATES.TemplateResponse(
        request,
        "partials/domain_status_badge.html",
        {"status": status, "message": message},
    )


@router.post("/htmx/keywords/{rule_id}/run", response_class=HTMLResponse)
def htmx_keyword_run(
    rule_id: int,
    request: Request,
    session: Session = Depends(get_session),
    x_api: XAPIAdapter = Depends(get_x_adapter),
    llm: LLMAdapter = Depends(get_llm_adapter),
):
    keyword_service = KeywordService(session, x_api, llm)
    try:
        result = keyword_service.run_dynamic(rule_id)
    except Exception as exc:
        result = {"error": str(exc)}
    return TEMPLATES.TemplateResponse(
        request,
        "partials/keyword_results.html",
        {"result": result},
    )


@router.post("/htmx/keywords/{rule_id}/save", response_class=HTMLResponse)
def htmx_keyword_save(
    rule_id: int,
    request: Request,
    rule_name: str = Form(...),
    query: str = Form(...),
    lookback_days: int = Form(...),
    api_calls_used: int = Form(...),
    fetched_count: int = Form(...),
    scored_count: int = Form(...),
    search_from: str = Form(...),
    search_to: str = Form(...),
    posts_json: str = Form(...),
    session: Session = Depends(get_session),
):
    snap_repo = KeywordSnapshotRepo(session)
    log_repo = LogRepo(session)
    try:
        posts = json.loads(posts_json)
        snap = snap_repo.save(
            rule_id=rule_id,
            rule_name=rule_name,
            query=query,
            lookback_days=lookback_days,
            search_from=search_from,
            search_to=search_to,
            api_calls_used=api_calls_used,
            fetched_count=fetched_count,
            scored_count=scored_count,
            posts=posts,
        )
        log_repo.write(
            LogEventType.keyword_save,
            f'Keyword search saved: "{rule_name}" | query: {query!r} | '
            f"lookback {lookback_days}d | fetched {fetched_count}, kept {scored_count}, "
            f"showing {len(posts)} | window {search_from} → {search_to}",
        )
        return TEMPLATES.TemplateResponse(
            request,
            "partials/keyword_save_confirm.html",
            {"snap_id": snap.id},
        )
    except Exception as exc:
        return HTMLResponse(
            f'<div style="color:var(--status-error);font-size:13px;padding:8px 0">'
            f"Save failed: {exc}</div>",
            status_code=200,
        )


@router.post("/htmx/domains/{domain_id}/fetch", response_class=HTMLResponse)
def htmx_fetch_domain(
    domain_id: int,
    request: Request,
    days: int = Query(1, ge=1, le=90),
    force: bool = False,
    session: Session = Depends(get_session),
    x_api: XAPIAdapter = Depends(get_x_adapter),
    llm: LLMAdapter = Depends(get_llm_adapter),
):
    """Fetch one domain for the last `days` days and return its refreshed panel.
    Delta by default (header "Fetch"); force=true re-fetches everything ("Re-fetch")."""
    result = PipelineService(session, x_api, llm).fetch_domain(domain_id, days, force=force)

    if result.get("status") != "error":
        digest_service = DigestService(session)
        digest = (digest_service.get_digest(date.today()) if days == 1
                  else digest_service.get_range_digest(days))
        domain_data = next(
            (dom for dom in digest["domains"] if dom["domain_id"] == domain_id), None
        )
        if domain_data:
            return TEMPLATES.TemplateResponse(
                request,
                "partials/domain_panel_body.html",
                {"domain": domain_data, "digest_date": digest["date"],
                 "window": days, "oob_count": True},
            )

    message = result.get("reason", "Unknown error")
    return TEMPLATES.TemplateResponse(
        request,
        "partials/domain_status_badge.html",
        {"status": "error", "message": message},
    )
