from datetime import date
from fastapi import APIRouter, Depends, BackgroundTasks, Query
from sqlmodel import Session
from ..database import get_session
from ..adapters import get_x_adapter, get_llm_adapter, XAPIAdapter, LLMAdapter
from ..services import DigestService, PipelineService

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("/today")
def get_today(session: Session = Depends(get_session)):
    return DigestService(session).get_digest(date.today())


@router.get("/dates")
def get_available_dates(session: Session = Depends(get_session)):
    return DigestService(session).get_available_dates()


@router.get("/{digest_date}")
def get_by_date(digest_date: date, session: Session = Depends(get_session)):
    return DigestService(session).get_digest(digest_date)


@router.post("/run", status_code=202)
def trigger_pipeline(background_tasks: BackgroundTasks,
                     days: int | None = Query(None, ge=1, le=90),
                     session: Session = Depends(get_session),
                     x_api: XAPIAdapter = Depends(get_x_adapter),
                     llm: LLMAdapter = Depends(get_llm_adapter)):
    """Trigger a full pipeline run asynchronously. Without `days` it is an incremental
    run (each account since its last fetch); with `days` it fetches the last N days, skipping what's already fetched."""
    # Background tasks run after the request's yield-dependencies are closed,
    # so the task opens its own session on the same engine instead of reusing
    # the (by then closed) request session.
    engine = session.get_bind()

    def _run():
        with Session(engine) as task_session:
            svc = PipelineService(task_session, x_api, llm)
            svc.run(days=days)
    background_tasks.add_task(_run)
    return {"status": "pipeline started"}


@router.post("/{digest_date}/domains/{domain_id}/refetch", status_code=202)
def refetch_domain(digest_date: date, domain_id: int,
                   background_tasks: BackgroundTasks,
                   force: bool = False,
                   session: Session = Depends(get_session),
                   x_api: XAPIAdapter = Depends(get_x_adapter),
                   llm: LLMAdapter = Depends(get_llm_adapter)):
    """Manually re-fetch a specific domain for a date. Only the part of the day not
    already fetched is requested from X; pass ?force=true to fetch the whole day."""
    engine = session.get_bind()

    def _run():
        with Session(engine) as task_session:
            svc = PipelineService(task_session, x_api, llm)
            svc.refetch_domain(domain_id, digest_date, force=force)
    background_tasks.add_task(_run)
    return {"status": "refetch started", "domain_id": domain_id, "date": str(digest_date)}


@router.post("/domains/{domain_id}/fetch", status_code=202)
def fetch_domain(domain_id: int, background_tasks: BackgroundTasks,
                 days: int = Query(1, ge=1, le=90), force: bool = False,
                 session: Session = Depends(get_session),
                 x_api: XAPIAdapter = Depends(get_x_adapter),
                 llm: LLMAdapter = Depends(get_llm_adapter)):
    """Fetch one domain for the last `days` days. Only the delta is fetched unless
    force=true, which re-fetches the whole window for every account."""
    engine = session.get_bind()

    def _run():
        with Session(engine) as task_session:
            svc = PipelineService(task_session, x_api, llm)
            svc.fetch_domain(domain_id, days, force=force)
    background_tasks.add_task(_run)
    return {"status": "fetch started", "domain_id": domain_id, "days": days, "force": force}
