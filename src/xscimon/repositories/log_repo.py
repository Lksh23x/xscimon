from datetime import date, datetime, timedelta, UTC
from typing import Optional
from sqlalchemy import delete, func
from sqlmodel import Session, select, or_
from ..models import LogEntry, LogEventType


class LogRepo:
    def __init__(self, session: Session):
        self._s = session

    def write(self, event_type: LogEventType, message: str,
              domain_id: Optional[int] = None,
              call_count: Optional[int] = None) -> LogEntry:
        entry = LogEntry(
            event_type=event_type,
            message=message,
            domain_id=domain_id,
            call_count=call_count,
        )
        self._s.add(entry)
        self._s.commit()
        self._s.refresh(entry)
        return entry

    @staticmethod
    def _filtered(stmt, query: Optional[str], day: Optional[date]):
        if query:
            q = f"%{query}%"
            stmt = stmt.where(or_(LogEntry.message.ilike(q), LogEntry.event_type.ilike(q)))
        if day:
            # Timestamps are stored as naive UTC; `day` is a UTC calendar day.
            start = datetime(day.year, day.month, day.day)
            stmt = stmt.where(LogEntry.timestamp >= start,
                              LogEntry.timestamp < start + timedelta(days=1))
        return stmt

    def search(self, query: Optional[str] = None, limit: int = 200,
               day: Optional[date] = None, offset: int = 0) -> list[LogEntry]:
        """Newest first, optionally filtered by text and/or UTC day, paged."""
        stmt = self._filtered(select(LogEntry), query, day)
        stmt = stmt.order_by(LogEntry.timestamp.desc(), LogEntry.id.desc())
        return list(self._s.exec(stmt.offset(offset).limit(limit)).all())

    def count(self, query: Optional[str] = None, day: Optional[date] = None) -> int:
        stmt = self._filtered(select(func.count()).select_from(LogEntry), query, day)
        return int(self._s.exec(stmt).one())

    def date_bounds(self) -> tuple[Optional[date], Optional[date]]:
        """(oldest, newest) UTC day that has log entries."""
        lo, hi = self._s.exec(
            select(func.min(LogEntry.timestamp), func.max(LogEntry.timestamp))
        ).one()
        return (lo.date() if lo else None, hi.date() if hi else None)

    def api_calls_today(self) -> int:
        today = datetime.now(UTC).date()
        start_of_day = datetime(today.year, today.month, today.day, tzinfo=UTC)
        total = self._s.exec(
            select(func.sum(LogEntry.call_count))
            .where(LogEntry.event_type == LogEventType.api_call)
            .where(LogEntry.timestamp >= start_of_day)
        ).one()
        return int(total or 0)

    def clear_all(self) -> None:
        self._s.execute(delete(LogEntry))
        self._s.commit()
