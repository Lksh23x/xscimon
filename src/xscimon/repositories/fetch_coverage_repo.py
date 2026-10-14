from datetime import date, datetime, UTC
from typing import Optional
from sqlmodel import Session, select
from ..models import FetchCoverage

Span = tuple[datetime, datetime]


def _aware(ts: datetime) -> datetime:
    # SQLite drops tzinfo on round-trip; all stored timestamps are UTC.
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _span(row: FetchCoverage) -> Span:
    start = row.covered_from or datetime.combine(row.date, datetime.min.time())
    return _aware(start), _aware(row.covered_until)


class FetchCoverageRepo:
    def __init__(self, session: Session):
        self._s = session

    def get(self, domain_id: int, account_id: int, day: date) -> Optional[Span]:
        """(covered_from, covered_until) for one account and day, or None."""
        row = self._s.get(FetchCoverage, (domain_id, account_id, day))
        return _span(row) if row else None

    def get_for_day(self, domain_id: int, day: date) -> dict[int, Span]:
        """account_id -> (covered_from, covered_until) for one domain and day."""
        rows = self._s.exec(
            select(FetchCoverage)
            .where(FetchCoverage.domain_id == domain_id)
            .where(FetchCoverage.date == day)
        ).all()
        return {r.account_id: _span(r) for r in rows}

    def get_for_range(self, domain_id: int, from_day: date,
                      to_day: date) -> dict[date, dict[int, Span]]:
        """day -> {account_id: (covered_from, covered_until)} for an inclusive range."""
        rows = self._s.exec(
            select(FetchCoverage)
            .where(FetchCoverage.domain_id == domain_id)
            .where(FetchCoverage.date >= from_day)
            .where(FetchCoverage.date <= to_day)
        ).all()
        out: dict[date, dict[int, Span]] = {}
        for r in rows:
            out.setdefault(r.date, {})[r.account_id] = _span(r)
        return out

    def set(self, domain_id: int, account_id: int, day: date,
            covered_until: datetime, covered_from: Optional[datetime] = None) -> None:
        """covered_from=None means from 00:00 UTC of `day`."""
        row = self._s.get(FetchCoverage, (domain_id, account_id, day))
        if row is None:
            row = FetchCoverage(domain_id=domain_id, account_id=account_id, date=day,
                                covered_until=covered_until)
        row.covered_from = covered_from
        row.covered_until = covered_until
        self._s.add(row)
        self._s.commit()

    def delete_for_domain(self, domain_id: int, account_id: Optional[int] = None) -> None:
        """Drop coverage for a domain, or for one account within it."""
        stmt = select(FetchCoverage).where(FetchCoverage.domain_id == domain_id)
        if account_id is not None:
            stmt = stmt.where(FetchCoverage.account_id == account_id)
        for row in self._s.exec(stmt).all():
            self._s.delete(row)
        self._s.commit()
