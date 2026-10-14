from typing import Optional
from sqlmodel import Session, select
from ..models import KeywordRule, KeywordMode


class KeywordRepo:
    def __init__(self, session: Session):
        self._s = session

    def get_all(self) -> list[KeywordRule]:
        return list(self._s.exec(select(KeywordRule)).all())

    def get_presets(self) -> list[KeywordRule]:
        return list(self._s.exec(
            select(KeywordRule)
            .where(KeywordRule.mode == KeywordMode.preset)
            .where(KeywordRule.enabled == True)
        ).all())

    def get_by_id(self, rule_id: int) -> Optional[KeywordRule]:
        return self._s.get(KeywordRule, rule_id)

    def create(self, name: str, query: str, mode: KeywordMode = KeywordMode.dynamic,
               lookback_days: int = 7, priority_weight: float = 1.0,
               skill_md: Optional[str] = None) -> KeywordRule:
        rule = KeywordRule(
            name=name, query=query, mode=mode,
            lookback_days=lookback_days, priority_weight=priority_weight,
            skill_md=skill_md,
        )
        self._s.add(rule)
        self._s.commit()
        self._s.refresh(rule)
        return rule

    def promote_to_preset(self, rule_id: int) -> Optional[KeywordRule]:
        rule = self._s.get(KeywordRule, rule_id)
        if not rule:
            return None
        rule.mode = KeywordMode.preset
        self._s.add(rule)
        self._s.commit()
        self._s.refresh(rule)
        return rule

    def update(self, rule: KeywordRule) -> KeywordRule:
        self._s.add(rule)
        self._s.commit()
        self._s.refresh(rule)
        return rule

    def delete(self, rule_id: int) -> bool:
        rule = self._s.get(KeywordRule, rule_id)
        if not rule:
            return False
        self._s.delete(rule)
        self._s.commit()
        return True
