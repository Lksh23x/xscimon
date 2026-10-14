from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from ..database import get_session
from ..adapters import get_email_adapter, EmailAdapter
from ..services import EmailService

router = APIRouter(prefix="/api/email", tags=["email"])


class SendRequest(BaseModel):
    date: date
    domain_ids: Optional[list[int]] = None   # None = all domains
    post_ids: Optional[list[str]] = None     # None = all posts in selected domains
    to: Optional[str] = None                 # overrides EMAIL_TO_DEFAULT


@router.post("/send")
def send_digest(body: SendRequest, session: Session = Depends(get_session),
                email: EmailAdapter = Depends(get_email_adapter)):
    svc = EmailService(session, email)
    result = svc.send_digest(body.date, body.domain_ids, body.post_ids, body.to)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result
