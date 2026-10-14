import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class FetchCoverage(SQLModel, table=True):
    """The span of one UTC calendar day of an account's timeline that has already
    been fetched for a domain: [covered_from, covered_until), one contiguous
    interval per day. Lets windowed fetches ask X only for the delta."""
    domain_id: int = Field(foreign_key="domain.id", primary_key=True)
    account_id: int = Field(foreign_key="account.id", primary_key=True)
    date: datetime.date = Field(primary_key=True)
    # None means 00:00 UTC of `date` (rows written before this column existed).
    covered_from: Optional[datetime.datetime] = None
    covered_until: datetime.datetime
