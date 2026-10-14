import csv
import io
import json
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session
from ..database import get_session
from ..models import CredibilityLevel, LogEventType
from ..repositories import DomainRepo, AccountRepo, LogRepo, FetchCoverageRepo
from ..services import ProfileService
from ..adapters import get_x_adapter, XAPIAdapter

# X handle: 1–50 chars, letters/digits/underscores only
_HANDLE_RE = re.compile(r'^[A-Za-z0-9_]{1,50}$')

router = APIRouter(prefix="/api/domains", tags=["domains"])


class DomainCreate(BaseModel):
    name: str
    top_n: int = 10
    skill_md: Optional[str] = None


class DomainUpdate(BaseModel):
    name: Optional[str] = None
    top_n: Optional[int] = None
    skill_md: Optional[str] = None


class AccountAdd(BaseModel):
    handle: str
    display_name: Optional[str] = None
    description: Optional[str] = None


class CredibilityUpdate(BaseModel):
    credibility: CredibilityLevel


@router.get("")
def list_domains(session: Session = Depends(get_session)):
    return DomainRepo(session).get_all()


@router.post("", status_code=201)
def create_domain(body: DomainCreate, session: Session = Depends(get_session)):
    return DomainRepo(session).create(body.name, body.top_n, body.skill_md)


@router.patch("/{domain_id}")
def update_domain(domain_id: int, body: DomainUpdate,
                  session: Session = Depends(get_session)):
    repo = DomainRepo(session)
    domain = repo.get_by_id(domain_id)
    if not domain:
        raise HTTPException(404, "Domain not found")
    if body.name is not None:
        domain.name = body.name
    if body.top_n is not None:
        domain.top_n = body.top_n
    if body.skill_md is not None:
        domain.skill_md = body.skill_md
    return repo.update(domain)


@router.delete("/{domain_id}", status_code=204)
def delete_domain(domain_id: int, session: Session = Depends(get_session)):
    accounts = AccountRepo(session)
    accounts.delete_domain_associations(domain_id)
    FetchCoverageRepo(session).delete_for_domain(domain_id)
    if not DomainRepo(session).delete(domain_id):
        raise HTTPException(404, "Domain not found")


@router.get("/accounts/verify")
def verify_handle(handle: str, x_api: XAPIAdapter = Depends(get_x_adapter)):
    handle = handle.lstrip("@")
    try:
        exists, description, _uid, _followers = x_api.verify_account(handle)
    except Exception as exc:
        raise HTTPException(502, f"X API error while verifying @{handle}: {exc}")
    return {"exists": exists, "description": description}


@router.get("/{domain_id}/accounts")
def list_accounts(domain_id: int, session: Session = Depends(get_session)):
    return AccountRepo(session).get_for_domain(domain_id)


@router.post("/{domain_id}/accounts", status_code=201)
def add_account(domain_id: int, body: AccountAdd,
                session: Session = Depends(get_session),
                x_api: XAPIAdapter = Depends(get_x_adapter)):
    handle = body.handle.lstrip("@")
    try:
        exists, description, x_user_id, followers_count = x_api.verify_account(handle)
    except Exception as exc:
        raise HTTPException(502, f"X API error while verifying @{handle}: {exc}")
    if not exists:
        raise HTTPException(422, f"Account @{handle} not found on X")
    repo = AccountRepo(session)
    account = repo.get_or_create(handle, body.display_name, description,
                                  verified=True, x_user_id=x_user_id, followers_count=followers_count)
    repo.add_to_domain(account.id, domain_id)
    session.refresh(account)
    return account.model_dump()


@router.delete("/{domain_id}/accounts/{account_id}", status_code=204)
def remove_account(domain_id: int, account_id: int,
                   session: Session = Depends(get_session)):
    AccountRepo(session).remove_from_domain(account_id, domain_id)
    # If the account is re-added later, a re-fetch must fetch it from scratch.
    FetchCoverageRepo(session).delete_for_domain(domain_id, account_id)


@router.patch("/accounts/{account_id}/credibility")
def set_credibility(account_id: int, body: CredibilityUpdate,
                    session: Session = Depends(get_session)):
    account = AccountRepo(session).set_credibility(account_id, body.credibility)
    if not account:
        raise HTTPException(404, "Account not found")
    return account.model_dump()


@router.post("/{domain_id}/accounts/bulk", status_code=201)
def bulk_add_accounts(domain_id: int, entries: list[dict],
                      session: Session = Depends(get_session)):
    """Bulk import from JSON body. Each entry: {handle, display_name?, description?, credibility?}"""
    accounts = AccountRepo(session).upsert_bulk(domain_id, entries)
    return {"imported": len(accounts)}


# The exact header row produced by the CSV export endpoint.
# Only static, user-assigned fields — followers_count / last_post_at are fetched at runtime.
_CSV_EXPORT_HEADER = ["handle", "display_name", "description", "credibility"]

_FMT_SIMPLE = (
    "Single-handle format — one handle per row, no header:\n\n"
    "researcher_a\n"
    "lab_account\n"
    "scientist_b"
)

_FMT_EXPORT = (
    "Export format — CSV exported from xscimon (header row required):\n\n"
    "handle,display_name,description,credibility\n"
    "researcher_a,Dr. A,Bio text here,normal"
)

_FMT_JSON = (
    'JSON format — list of account objects (matches xscimon JSON export):\n\n'
    '[{"handle": "researcher_a", "display_name": "Dr. A", '
    '"description": "Bio here", "credibility": "normal"}, ...]'
)

# Fields that are system-generated and must never be imported from a file.
_IMPORT_EXCLUDE = frozenset({"followers_count", "last_post_at", "added_at"})


def _parse_csv_export_rows(data_rows: list[list[str]]) -> list[dict]:
    """Parse data rows from the xscimon export CSV (header already consumed)."""
    entries = []
    for row in data_rows:
        if not row or not row[0].strip():
            continue
        entry: dict = {"handle": row[0].strip().lstrip("@")}
        if len(row) > 1 and row[1].strip():
            entry["display_name"] = row[1].strip()
        if len(row) > 2 and row[2].strip():
            entry["description"] = row[2].strip()
        if len(row) > 3 and row[3].strip():
            entry["credibility"] = row[3].strip()
        entries.append(entry)
    return entries


def _apply_csv_entries(entries: list[dict], domain_id: int,
                       session, log_prefix: str) -> dict:
    """Validate handles, deduplicate, upsert new accounts, and log. Shared by both CSV paths."""
    valid_entries: list[dict] = []
    invalid_handles: list[str] = []
    seen: set[str] = set()

    for entry in entries:
        h = entry.get("handle", "")
        if not _HANDLE_RE.match(h):
            invalid_handles.append(h)
        elif h.lower() not in seen:
            seen.add(h.lower())
            valid_entries.append(entry)

    if not valid_entries and not invalid_handles:
        raise HTTPException(422, detail={
            "error": "File contains no valid handles.",
            "expected_formats": {"simple": _FMT_SIMPLE, "export": _FMT_EXPORT},
        })

    repo = AccountRepo(session)
    existing = {a.handle.lower() for a in repo.get_for_domain(domain_id)}
    to_insert = [e for e in valid_entries if e["handle"].lower() not in existing]
    duplicate_handles = [e["handle"] for e in valid_entries if e["handle"].lower() in existing]

    for entry in to_insert:
        account = repo.get_or_create(
            handle=entry["handle"],
            display_name=entry.get("display_name"),
            description=entry.get("description"),
        )
        if "credibility" in entry:
            try:
                account.credibility = CredibilityLevel(entry["credibility"])
                session.add(account)
            except ValueError:
                pass
        repo.add_to_domain(account.id, domain_id)

    LogRepo(session).write(
        LogEventType.csv_import,
        f"{log_prefix} for domain {domain_id}: "
        f"{len(to_insert)} loaded, {len(invalid_handles)} invalid, "
        f"{len(duplicate_handles)} duplicates",
        domain_id=domain_id,
    )

    return {
        "loaded": len(to_insert),
        "invalid": len(invalid_handles),
        "duplicates": len(duplicate_handles),
        "invalid_handles": invalid_handles,
        "duplicate_handles": duplicate_handles,
    }


@router.post("/{domain_id}/accounts/import", status_code=201)
async def import_accounts(domain_id: int, file: UploadFile = File(...),
                          session: Session = Depends(get_session)):
    """Bulk import accounts. Accepts the xscimon JSON/CSV export formats or a plain handle list."""
    content = await file.read()

    # ── JSON ──────────────────────────────────────────────────────────────────
    if file.filename and file.filename.endswith(".json"):
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(422, detail={"error": f"Invalid JSON: {exc}", "expected_format": _FMT_JSON})

        if not isinstance(data, list):
            raise HTTPException(422, detail={"error": "JSON must be a list of account objects.", "expected_format": _FMT_JSON})

        bad = [i for i, e in enumerate(data) if not isinstance(e, dict) or not e.get("handle")]
        if bad:
            raise HTTPException(422, detail={
                "error": f"Entries at index {bad[:5]} are missing a 'handle' field.",
                "expected_format": _FMT_JSON,
            })

        # Strip runtime-only fields — followers_count / last_post_at are fetched from X, not imported
        entries = [{k: v for k, v in e.items() if k not in _IMPORT_EXCLUDE} for e in data]
        accounts = AccountRepo(session).upsert_bulk(domain_id, entries)
        LogRepo(session).write(
            LogEventType.csv_import,
            f"JSON import for domain {domain_id}: {len(accounts)} accounts processed",
            domain_id=domain_id,
        )
        return {"imported": len(accounts)}

    # ── CSV ───────────────────────────────────────────────────────────────────
    try:
        text = content.decode()
    except UnicodeDecodeError:
        raise HTTPException(422, detail={"error": "File must be UTF-8 encoded."})

    rows = list(csv.reader(io.StringIO(text)))
    non_empty = [r for r in rows if any(c.strip() for c in r)]
    if not non_empty:
        raise HTTPException(422, detail={
            "error": "File is empty.",
            "expected_formats": {"simple": _FMT_SIMPLE, "export": _FMT_EXPORT},
        })

    first_row = [c.strip() for c in rows[0]]

    # Export format: header matches exactly
    if [c.lower() for c in first_row] == _CSV_EXPORT_HEADER:
        entries = _parse_csv_export_rows(rows[1:])
        return _apply_csv_entries(entries, domain_id, session, "CSV (export format) import")

    # Simple format: every row has at most one non-empty cell
    bad_rows = [i + 1 for i, row in enumerate(rows) if sum(1 for c in row if c.strip()) > 1]
    if bad_rows:
        raise HTTPException(422, detail={
            "error": (
                "Unrecognized CSV format: file has multiple columns but the header "
                f"does not match the xscimon export format. "
                f"First row found: {', '.join(first_row[:4])}..."
            ),
            "problem_rows": bad_rows[:20],
            "expected_formats": {"simple": _FMT_SIMPLE, "export": _FMT_EXPORT},
        })

    entries = [{"handle": row[0].strip().lstrip("@")} for row in rows if row and row[0].strip()]
    return _apply_csv_entries(entries, domain_id, session, "CSV (simple) import")


@router.get("/{domain_id}/accounts/export")
def export_accounts(domain_id: int, format: str = Query("csv", pattern="^(csv|json)$"),
                    session: Session = Depends(get_session)):
    """Download the domain's account list. Only static fields exported — runtime data
    (followers_count, last_post_at) is excluded and must be refreshed after import."""
    accounts = AccountRepo(session).get_for_domain(domain_id)
    if format == "json":
        data = [
            {
                "handle": a.handle,
                "display_name": a.display_name,
                "description": a.description,
                "credibility": a.credibility.value,
            }
            for a in accounts
        ]
        return Response(
            content=json.dumps(data, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=domain_{domain_id}_accounts.json"},
        )
    # CSV
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(_CSV_EXPORT_HEADER)
    for a in accounts:
        writer.writerow([a.handle, a.display_name or "", a.description or "", a.credibility.value])
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=domain_{domain_id}_accounts.csv"},
    )


@router.post("/{domain_id}/accounts/enrich")
def enrich_accounts(domain_id: int, session: Session = Depends(get_session),
                    x_api: XAPIAdapter = Depends(get_x_adapter)):
    """Fetch profile data (X user id, bio, followers) for accounts in this domain that
    are missing any of it. Batched: one X API call per 100 accounts."""
    accounts = AccountRepo(session).get_for_domain(domain_id)
    targets = [a for a in accounts
               if a.x_user_id is None or a.description is None or a.followers_count is None]
    log = LogRepo(session)
    try:
        result = ProfileService(session, x_api).refresh(targets, domain_id, reason="Profile enrich")
    except Exception as exc:
        log.write(LogEventType.error, f"Profile enrich: X API error: {exc}", domain_id=domain_id)
        return {"enriched": 0, "total": len(accounts), "error": f"X API error: {exc}"}
    log.write(
        LogEventType.profile_enrich,
        f"Profile enrich complete for domain {domain_id}: "
        f"{result['found']}/{len(accounts)} accounts updated",
        domain_id=domain_id,
    )
    return {"enriched": result["found"], "total": len(accounts),
            "not_found": result["not_found"]}
