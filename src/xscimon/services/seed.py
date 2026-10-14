import csv
from pathlib import Path

import yaml
from sqlmodel import Session

from ..models import KeywordMode
from ..repositories import AccountRepo, DomainRepo, KeywordRepo


class SeedService:
    """Load domains, tracked accounts, skill prompts and keyword rules from a seed
    directory (see seed/seed.yaml). Idempotent: re-running updates domains and rules
    by name and adds missing accounts, so it is safe on an existing database."""

    def __init__(self, session: Session):
        self._domains = DomainRepo(session)
        self._accounts = AccountRepo(session)
        self._keywords = KeywordRepo(session)

    def load(self, seed_dir: Path) -> dict:
        manifest = yaml.safe_load((seed_dir / "seed.yaml").read_text())
        summary = {"domains": [], "keywords": 0}

        for d in manifest.get("domains", []):
            skill_md = self._read_skill(seed_dir, d.get("skill"))
            domain = self._domains.get_by_name(d["name"])
            if domain:
                domain.top_n = d.get("top_n", domain.top_n)
                domain.skill_md = skill_md
                domain = self._domains.update(domain)
            else:
                domain = self._domains.create(d["name"], d.get("top_n", 10), skill_md)

            entries = self._read_accounts(seed_dir / d["accounts"]) if d.get("accounts") else []
            self._accounts.upsert_bulk(domain.id, entries)
            summary["domains"].append({"name": domain.name, "accounts": len(entries)})

        existing_rules = {r.name: r for r in self._keywords.get_all()}
        for k in manifest.get("keywords", []):
            skill_md = self._read_skill(seed_dir, k.get("skill"))
            rule = existing_rules.get(k["name"])
            if rule:
                rule.query = k["query"]
                rule.mode = KeywordMode(k.get("mode", rule.mode))
                rule.lookback_days = k.get("lookback_days", rule.lookback_days)
                rule.priority_weight = k.get("priority_weight", rule.priority_weight)
                rule.skill_md = skill_md
                self._keywords.update(rule)
            else:
                self._keywords.create(
                    k["name"], k["query"], KeywordMode(k.get("mode", "dynamic")),
                    k.get("lookback_days", 7), k.get("priority_weight", 1.0), skill_md,
                )
            summary["keywords"] += 1

        return summary

    @staticmethod
    def _read_skill(seed_dir: Path, rel: str | None) -> str | None:
        if not rel:
            return None
        return (seed_dir / rel).read_text().strip() or None

    @staticmethod
    def _read_accounts(path: Path) -> list[dict]:
        """CSV with header handle,display_name,description,credibility — only handle is required."""
        with open(path, newline="") as f:
            entries = []
            for row in csv.DictReader(f):
                handle = (row.get("handle") or "").strip().lstrip("@")
                if not handle:
                    continue
                entry = {"handle": handle}
                for field in ("display_name", "description", "credibility"):
                    if (row.get(field) or "").strip():
                        entry[field] = row[field].strip()
                entries.append(entry)
            return entries
