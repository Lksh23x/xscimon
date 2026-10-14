from typing import Optional
from sqlmodel import Session, select
from ..models import Domain


class DomainRepo:
    def __init__(self, session: Session):
        self._s = session

    def get_all(self) -> list[Domain]:
        return list(self._s.exec(select(Domain)).all())

    def get_by_id(self, domain_id: int) -> Optional[Domain]:
        return self._s.get(Domain, domain_id)

    def get_by_name(self, name: str) -> Optional[Domain]:
        return self._s.exec(select(Domain).where(Domain.name == name)).first()

    def create(self, name: str, top_n: int = 10, skill_md: Optional[str] = None) -> Domain:
        domain = Domain(name=name, top_n=top_n, skill_md=skill_md)
        self._s.add(domain)
        self._s.commit()
        self._s.refresh(domain)
        return domain

    def update(self, domain: Domain) -> Domain:
        self._s.add(domain)
        self._s.commit()
        self._s.refresh(domain)
        return domain

    def delete(self, domain_id: int) -> bool:
        domain = self._s.get(Domain, domain_id)
        if not domain:
            return False
        self._s.delete(domain)
        self._s.commit()
        return True
