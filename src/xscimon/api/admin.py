from typing import Optional
from fastapi import APIRouter, Depends
from sqlmodel import Session
from ..database import get_session
from ..repositories import LogRepo

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/logs")
def get_logs(q: Optional[str] = None, limit: int = 200,
             session: Session = Depends(get_session)):
    return LogRepo(session).search(query=q, limit=limit)


@router.get("/api-usage")
def get_api_usage(session: Session = Depends(get_session)):
    return {"calls_today": LogRepo(session).api_calls_today()}


@router.delete("/logs", status_code=204)
def clear_logs(session: Session = Depends(get_session)):
    LogRepo(session).clear_all()
