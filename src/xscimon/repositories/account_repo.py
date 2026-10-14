from datetime import datetime, UTC
from typing import Optional
from sqlmodel import Session, select
from ..models import Account, DomainAccount, CredibilityLevel


class AccountRepo:
    def __init__(self, session: Session):
        self._s = session

    def get_by_handle(self, handle: str) -> Optional[Account]:
        return self._s.exec(select(Account).where(Account.handle == handle)).first()

    def get_credibility_map(self, handles: set[str]) -> dict[str, str]:
        """Return {handle: credibility_value} for a set of handles in one query."""
        if not handles:
            return {}
        accounts = self._s.exec(
            select(Account).where(Account.handle.in_(list(handles)))
        ).all()
        return {a.handle: a.credibility.value for a in accounts}

    def get_or_create(self, handle: str, display_name: Optional[str] = None,
                      description: Optional[str] = None,
                      verified: Optional[bool] = True,
                      x_user_id: Optional[str] = None,
                      followers_count: Optional[int] = None) -> Account:
        account = self.get_by_handle(handle)
        if account:
            if description is not None:
                account.description = description
            if verified is not None:
                account.verified = verified
            if x_user_id is not None:
                account.x_user_id = x_user_id
            if followers_count is not None:
                account.followers_count = followers_count
            self._s.add(account)
            self._s.commit()
            self._s.refresh(account)
            return account
        account = Account(handle=handle, display_name=display_name,
                          description=description, verified=verified,
                          x_user_id=x_user_id, followers_count=followers_count)
        self._s.add(account)
        self._s.commit()
        self._s.refresh(account)
        return account

    def update_profile(self, account_id: int, description: Optional[str],
                       x_user_id: Optional[str], followers_count: Optional[int]) -> Optional[Account]:
        account = self._s.get(Account, account_id)
        if not account:
            return None
        if description is not None:
            account.description = description
        if x_user_id is not None:
            account.x_user_id = x_user_id
        if followers_count is not None:
            account.followers_count = followers_count
        account.verified = True
        self._s.add(account)
        self._s.commit()
        self._s.refresh(account)
        return account

    def get_for_domain(self, domain_id: int) -> list[Account]:
        stmt = (
            select(Account)
            .join(DomainAccount, DomainAccount.account_id == Account.id)
            .where(DomainAccount.domain_id == domain_id)
        )
        return list(self._s.exec(stmt).all())

    def get_for_domain_with_meta(self, domain_id: int) -> list[tuple[Account, datetime | None]]:
        """Returns (account, added_at) pairs for display and export."""
        accounts = self.get_for_domain(domain_id)
        da_rows = self._s.exec(
            select(DomainAccount).where(DomainAccount.domain_id == domain_id)
        ).all()
        added_at_map = {da.account_id: da.added_at for da in da_rows}
        return [(a, added_at_map.get(a.id)) for a in accounts]

    def add_to_domain(self, account_id: int, domain_id: int) -> None:
        existing = self._s.exec(
            select(DomainAccount)
            .where(DomainAccount.account_id == account_id)
            .where(DomainAccount.domain_id == domain_id)
        ).first()
        if not existing:
            self._s.add(DomainAccount(
                account_id=account_id,
                domain_id=domain_id,
                added_at=datetime.now(UTC),
            ))
            self._s.commit()

    def remove_from_domain(self, account_id: int, domain_id: int) -> None:
        link = self._s.exec(
            select(DomainAccount)
            .where(DomainAccount.account_id == account_id)
            .where(DomainAccount.domain_id == domain_id)
        ).first()
        if link:
            self._s.delete(link)
            self._s.commit()

    def stamp_fetched(self, account_id: int, ts: datetime,
                      latest_post_at: Optional[datetime] = None) -> None:
        account = self._s.get(Account, account_id)
        if account:
            account.last_fetched_at = ts
            if latest_post_at is not None:
                if account.last_post_at is None or latest_post_at > account.last_post_at:
                    account.last_post_at = latest_post_at
            self._s.add(account)
            self._s.commit()

    def set_credibility(self, account_id: int, level: CredibilityLevel) -> Optional[Account]:
        account = self._s.get(Account, account_id)
        if not account:
            return None
        account.credibility = level
        self._s.add(account)
        self._s.commit()
        self._s.refresh(account)
        return account

    def delete_domain_associations(self, domain_id: int) -> None:
        links = self._s.exec(
            select(DomainAccount).where(DomainAccount.domain_id == domain_id)
        ).all()
        for link in links:
            self._s.delete(link)
        self._s.commit()

    def upsert_bulk(self, domain_id: int, entries: list[dict]) -> list[Account]:
        """Bulk import from JSON body or file. Recognized fields: handle, display_name,
        description, credibility, followers_count. System fields (last_post_at, added_at) ignored."""
        results = []
        for entry in entries:
            account = self.get_or_create(
                handle=entry["handle"],
                display_name=entry.get("display_name"),
                description=entry.get("description"),
                followers_count=entry.get("followers_count"),
            )
            if "credibility" in entry and entry["credibility"]:
                try:
                    account.credibility = CredibilityLevel(entry["credibility"])
                    self._s.add(account)
                except ValueError:
                    pass
            self.add_to_domain(account.id, domain_id)
            results.append(account)
        self._s.commit()
        return results
