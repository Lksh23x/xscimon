import json
from datetime import datetime
from typing import Optional
from sqlmodel import Session, select
from ..models.keyword_snapshot import KeywordSnapshot


class KeywordSnapshotRepo:
    def __init__(self, session: Session):
        self._s = session

    def save(
        self,
        rule_id: Optional[int],
        rule_name: str,
        query: str,
        lookback_days: int,
        search_from: str,
        search_to: str,
        api_calls_used: int,
        fetched_count: int,
        scored_count: int,
        posts: list[dict],
    ) -> KeywordSnapshot:
        snap = KeywordSnapshot(
            rule_id=rule_id,
            rule_name=rule_name,
            query=query,
            lookback_days=lookback_days,
            search_from=search_from,
            search_to=search_to,
            api_calls_used=api_calls_used,
            fetched_count=fetched_count,
            scored_count=scored_count,
            posts_json=json.dumps(posts, ensure_ascii=False),
        )
        self._s.add(snap)
        self._s.commit()
        self._s.refresh(snap)
        return snap

    def get_all(self) -> list[KeywordSnapshot]:
        return list(self._s.exec(
            select(KeywordSnapshot).order_by(KeywordSnapshot.saved_at.desc())
        ).all())

    def get_by_id(self, snapshot_id: int) -> Optional[KeywordSnapshot]:
        return self._s.get(KeywordSnapshot, snapshot_id)
