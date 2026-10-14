from typing import Optional
from sqlmodel import Field, SQLModel


class Domain(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    skill_md: Optional[str] = None
    top_n: int = Field(default=10)
