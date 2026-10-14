from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from ..database import get_session
from ..adapters import get_x_adapter, get_llm_adapter, XAPIAdapter, LLMAdapter
from ..models import KeywordMode
from ..repositories import KeywordRepo
from ..services import KeywordService

router = APIRouter(prefix="/api/keywords", tags=["keywords"])


class KeywordCreate(BaseModel):
    name: str
    query: str
    mode: KeywordMode = KeywordMode.dynamic
    lookback_days: int = 7
    priority_weight: float = 1.0
    skill_md: Optional[str] = None


class KeywordUpdate(BaseModel):
    name: Optional[str] = None
    query: Optional[str] = None
    mode: Optional[KeywordMode] = None
    lookback_days: Optional[int] = None
    priority_weight: Optional[float] = None
    skill_md: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("")
def list_rules(session: Session = Depends(get_session)):
    return KeywordRepo(session).get_all()


@router.post("", status_code=201)
def create_rule(body: KeywordCreate, session: Session = Depends(get_session)):
    return KeywordRepo(session).create(
        name=body.name, query=body.query, mode=body.mode,
        lookback_days=body.lookback_days, priority_weight=body.priority_weight,
        skill_md=body.skill_md,
    )


@router.patch("/{rule_id}")
def update_rule(rule_id: int, body: KeywordUpdate,
                session: Session = Depends(get_session)):
    repo = KeywordRepo(session)
    rule = repo.get_by_id(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(rule, field, val)
    return repo.update(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    if not KeywordRepo(session).delete(rule_id):
        raise HTTPException(404, "Rule not found")


@router.post("/{rule_id}/run")
def run_dynamic(rule_id: int, session: Session = Depends(get_session),
                x_api: XAPIAdapter = Depends(get_x_adapter),
                llm: LLMAdapter = Depends(get_llm_adapter)):
    """Execute a dynamic filter on demand. Returns preview results, not stored."""
    svc = KeywordService(session, x_api, llm)
    return svc.run_dynamic(rule_id)


@router.post("/{rule_id}/promote")
def promote_to_preset(rule_id: int, session: Session = Depends(get_session),
                      x_api: XAPIAdapter = Depends(get_x_adapter),
                      llm: LLMAdapter = Depends(get_llm_adapter)):
    svc = KeywordService(session, x_api, llm)
    result = svc.promote_to_preset(rule_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result
