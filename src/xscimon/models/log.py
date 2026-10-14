from datetime import datetime, UTC
from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel


class LogEventType(str, Enum):
    pipeline_start = "pipeline_start"
    pipeline_end = "pipeline_end"
    api_call = "api_call"
    error = "error"
    refetch = "refetch"
    csv_import = "csv_import"
    keyword_save = "keyword_save"
    profile_enrich = "profile_enrich"


class LogEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    event_type: LogEventType
    domain_id: Optional[int] = Field(default=None, foreign_key="domain.id")
    message: str
    call_count: Optional[int] = None    # populated for api_call events
