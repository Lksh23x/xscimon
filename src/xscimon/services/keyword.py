from datetime import datetime, UTC, timedelta
from sqlmodel import Session
from ..adapters.base import XAPIAdapter, LLMAdapter
from ..models import LogEventType
from ..repositories import KeywordRepo, LogRepo
from .scoring import score_and_rank_keyword
from ..config import get_config


class KeywordService:
    def __init__(self, session: Session, x_api: XAPIAdapter, llm: LLMAdapter):
        self._rules = KeywordRepo(session)
        self._log = LogRepo(session)
        self._x = x_api
        self._llm = llm
        self._cfg = get_config()

    def run_dynamic(self, rule_id: int) -> dict:
        """Execute a dynamic filter on demand. Results are not stored in snapshots."""
        rule = self._rules.get_by_id(rule_id)
        if not rule:
            return {"error": "Rule not found."}
        threshold = self._cfg["pipeline"]["max_daily_api_calls"]
        if self._log.api_calls_today() >= threshold:
            return {"error": f"Daily API call budget ({threshold}) reached. "
                             "Try again after midnight UTC."}
        search_to = datetime.now(UTC)
        since = search_to - timedelta(days=rule.lookback_days)
        posts, calls = self._x.search(rule.query, since)
        self._log.write(LogEventType.api_call,
                        f"Dynamic keyword search: '{rule.query}'", call_count=calls)
        fetched_count = len(posts)
        max_results = self._cfg["keyword"]["max_results"]
        ranked = score_and_rank_keyword(posts, rule.skill_md, rule.priority_weight, self._llm)
        return {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "query": rule.query,
            "lookback_days": rule.lookback_days,
            "api_calls": calls,
            "fetched_count": fetched_count,
            "scored_count": len(ranked),
            "search_from": since.isoformat(),
            "search_to": search_to.isoformat(),
            "posts": ranked[:max_results],
        }

    def promote_to_preset(self, rule_id: int) -> dict:
        rule = self._rules.promote_to_preset(rule_id)
        if not rule:
            return {"error": "Rule not found."}
        return {"rule_id": rule.id, "name": rule.name, "mode": rule.mode.value}
