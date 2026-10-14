from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel


class KeywordSnapshot(SQLModel, table=True):
    """Persisted result of a keyword search run, saved on user request."""
    id: Optional[int] = Field(default=None, primary_key=True)
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    rule_id: Optional[int] = Field(default=None, foreign_key="keywordrule.id")
    rule_name: str
    query: str
    lookback_days: int
    search_from: str   # ISO datetime — start of the search window
    search_to: str     # ISO datetime — when the run was executed
    api_calls_used: int = Field(default=0)
    fetched_count: int = Field(default=0)
    scored_count: int = Field(default=0)
    posts_json: str = Field(default="[]")
