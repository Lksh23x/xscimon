from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel


class KeywordMode(str, Enum):
    dynamic = "dynamic"
    preset = "preset"


class KeywordRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    query: str                          # plain keywords and/or #hashtags
    mode: KeywordMode = Field(default=KeywordMode.dynamic)
    enabled: bool = Field(default=True)
    priority_weight: float = Field(default=1.0)
    lookback_days: int = Field(default=7)
    skill_md: Optional[str] = None
