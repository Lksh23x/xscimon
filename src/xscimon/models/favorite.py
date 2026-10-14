from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Field, SQLModel


class FavoritePost(SQLModel, table=True):
    __tablename__ = "favorite_post"

    post_id: str = Field(primary_key=True)
    starred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
