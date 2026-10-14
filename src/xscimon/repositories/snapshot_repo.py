import json
from datetime import date
from typing import Optional
from sqlmodel import Session, select
from ..models import DigestSnapshot, DomainStatus


class SnapshotRepo:
    def __init__(self, session: Session):
        self._s = session

    def get(self, snapshot_date: date, domain_id: int) -> Optional[DigestSnapshot]:
        return self._s.exec(
            select(DigestSnapshot)
            .where(DigestSnapshot.date == snapshot_date)
            .where(DigestSnapshot.domain_id == domain_id)
        ).first()

    def get_all_for_date(self, snapshot_date: date) -> list[DigestSnapshot]:
        return list(self._s.exec(
            select(DigestSnapshot).where(DigestSnapshot.date == snapshot_date)
        ).all())

    def get_dates_with_snapshots(self) -> list[date]:
        rows = self._s.exec(select(DigestSnapshot.date).distinct()).all()
        return sorted(set(rows), reverse=True)

    def get_for_date_range(self, from_date: date, to_date: date,
                           domain_id: Optional[int] = None) -> list["DigestSnapshot"]:
        stmt = (
            select(DigestSnapshot)
            .where(DigestSnapshot.date >= from_date)
            .where(DigestSnapshot.date <= to_date)
        )
        if domain_id is not None:
            stmt = stmt.where(DigestSnapshot.domain_id == domain_id)
        return list(self._s.exec(stmt).all())

    def get_date_domain_statuses(self, domain_id: Optional[int] = None) -> list[tuple[date, int, str, int]]:
        """Return (date, domain_id, status, post_count) for all snapshots.
        post_count is computed in SQLite so posts_json is never loaded into Python."""
        from sqlalchemy import select as sa_select, func
        stmt = sa_select(DigestSnapshot.date, DigestSnapshot.domain_id, DigestSnapshot.status,
                         func.json_array_length(DigestSnapshot.posts_json))
        if domain_id is not None:
            stmt = stmt.where(DigestSnapshot.domain_id == domain_id)
        rows = self._s.execute(stmt).all()
        return [(r[0], r[1], r[2], r[3] or 0) for r in rows]

    def upsert(self, snapshot_date: date, domain_id: int, status: DomainStatus,
               posts: list[dict], api_calls_used: int,
               status_reason: Optional[str] = None) -> DigestSnapshot:
        snapshot = self.get(snapshot_date, domain_id)
        if snapshot:
            snapshot.status = status
            snapshot.status_reason = status_reason
            snapshot.posts_json = json.dumps(posts)
            snapshot.api_calls_used = api_calls_used
        else:
            snapshot = DigestSnapshot(
                date=snapshot_date,
                domain_id=domain_id,
                status=status,
                status_reason=status_reason,
                posts_json=json.dumps(posts),
                api_calls_used=api_calls_used,
            )
        self._s.add(snapshot)
        self._s.commit()
        self._s.refresh(snapshot)
        return snapshot

    def get_posts(self, snapshot: DigestSnapshot) -> list[dict]:
        return json.loads(snapshot.posts_json)
