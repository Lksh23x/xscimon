import datetime
from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel


class DomainStatus(str, Enum):
    complete = "complete"
    partial = "partial"
    error = "error"
    pending = "pending"


class DigestSnapshot(SQLModel, table=True):
    """One row per domain per day. Stores ranked posts as a JSON blob."""
    id: Optional[int] = Field(default=None, primary_key=True)
    date: datetime.date = Field(index=True)
    domain_id: int = Field(foreign_key="domain.id", index=True)
    status: DomainStatus = Field(default=DomainStatus.pending)
    status_reason: Optional[str] = None
    posts_json: str = Field(default="[]")   # JSON-serialised list of PostRecord dicts
    api_calls_used: int = Field(default=0)
