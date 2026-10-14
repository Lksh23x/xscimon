from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel


class CredibilityLevel(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class Account(SQLModel, table=True):
    """Global X account record. Credibility is account-wide, not per-domain."""
    id: Optional[int] = Field(default=None, primary_key=True)
    handle: str = Field(unique=True, index=True)
    display_name: Optional[str] = None
    description: Optional[str] = None
    credibility: CredibilityLevel = Field(default=CredibilityLevel.normal)
    verified: Optional[bool] = Field(default=True)
    x_user_id: Optional[str] = Field(default=None, index=True)
    last_fetched_at: Optional[datetime] = Field(default=None)
    last_post_at: Optional[datetime] = Field(default=None)
    followers_count: Optional[int] = Field(default=None)


class DomainAccount(SQLModel, table=True):
    """Join table associating accounts with domains."""
    domain_id: int = Field(foreign_key="domain.id", primary_key=True)
    account_id: int = Field(foreign_key="account.id", primary_key=True)
    added_at: Optional[datetime] = Field(default=None)
