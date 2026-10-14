import json
from collections import defaultdict
from datetime import date, timedelta
from sqlmodel import Session
from ..repositories import DomainRepo, SnapshotRepo, AccountRepo

_RANGE_POST_CAP = 50  # max posts shown per domain in a multi-day window


class DigestService:
    def __init__(self, session: Session):
        self._domains = DomainRepo(session)
        self._snapshots = SnapshotRepo(session)
        self._accounts = AccountRepo(session)

    def _apply_current_credibility(self, posts: list[dict]) -> list[dict]:
        """Override stored credibility_level with the account's current rating.

        Snapshot JSON preserves the credibility at fetch time, but users may
        have adjusted it since. One batch query covers all authors in the list.
        """
        handles = {p["author_handle"] for p in posts if "author_handle" in p}
        cred_map = self._accounts.get_credibility_map(handles)
        for post in posts:
            handle = post.get("author_handle")
            if handle in cred_map:
                post["credibility_level"] = cred_map[handle]
        return posts

    def get_digest(self, digest_date: date) -> dict:
        domains = self._domains.get_all()
        domain_digests = []

        for domain in domains:
            snapshot = self._snapshots.get(digest_date, domain.id)
            if snapshot:
                posts = self._apply_current_credibility(json.loads(snapshot.posts_json))
                domain_digests.append({
                    "domain_id": domain.id,
                    "domain_name": domain.name,
                    "status": snapshot.status.value,
                    "status_reason": snapshot.status_reason,
                    "api_calls_used": snapshot.api_calls_used,
                    "posts": posts,
                })
            else:
                domain_digests.append({
                    "domain_id": domain.id,
                    "domain_name": domain.name,
                    "status": "pending",
                    "status_reason": None,
                    "api_calls_used": 0,
                    "posts": [],
                })

        return {"date": digest_date.isoformat(), "days": 1, "domains": domain_digests}

    def get_range_digest(self, days: int) -> dict:
        """Merge and re-rank posts from the last `days` days by final_score.

        Posts are de-duplicated by post_id so content fetched across multiple
        pipeline runs only appears once, surfaced at its best relevance rank.
        """
        today = date.today()
        domains = self._domains.get_all()
        domain_digests = []

        # One range query for the whole window, grouped by domain in memory.
        snaps = self._snapshots.get_for_date_range(today - timedelta(days=days - 1), today)
        snaps_by_domain: dict[int, list] = defaultdict(list)
        for snap in snaps:
            snaps_by_domain[snap.domain_id].append(snap)

        for domain in domains:
            # Collect unique posts across the window, newest-snapshot-first so
            # that if the same post_id appears in two snapshots we keep the copy
            # from the more recent fetch (which may have updated engagement counts).
            merged: dict[str, dict] = {}
            domain_snaps = sorted(snaps_by_domain.get(domain.id, []),
                                  key=lambda s: s.date, reverse=True)
            latest_snapshot = domain_snaps[0] if domain_snaps else None

            for snapshot in domain_snaps:
                for post in json.loads(snapshot.posts_json):
                    if post["post_id"] not in merged:
                        merged[post["post_id"]] = post

            posts = self._apply_current_credibility(
                sorted(merged.values(), key=lambda p: p.get("final_score", 0), reverse=True)
            )

            domain_digests.append({
                "domain_id": domain.id,
                "domain_name": domain.name,
                "status": latest_snapshot.status.value if latest_snapshot else "pending",
                "status_reason": None,
                "api_calls_used": 0,
                "posts": posts[:_RANGE_POST_CAP],
            })

        return {"date": today.isoformat(), "days": days, "domains": domain_digests}

    def get_range_posts(self, from_date: date, to_date: date,
                        domain_id: int | None = None) -> list[dict]:
        """Merge and rank posts across a date range, optionally for one domain.
        Used for lazy period loading."""
        snaps = self._snapshots.get_for_date_range(from_date, to_date, domain_id)
        merged: dict[str, dict] = {}
        for snap in snaps:
            for post in json.loads(snap.posts_json):
                if post["post_id"] not in merged:
                    merged[post["post_id"]] = post
        posts = sorted(merged.values(), key=lambda p: p.get("final_score", 0), reverse=True)
        return self._apply_current_credibility(posts)

    def get_history_periods(self, today: date, domain_id: int | None = None) -> list[dict]:
        """Build the progressive period structure for the history page.
        Only loads snapshot metadata (no posts_json parsing) — posts are lazy-loaded.
        When domain_id is given, only that domain's snapshots are considered."""
        from calendar import monthrange as cal_monthrange

        rows = self._snapshots.get_date_domain_statuses(domain_id)

        # Aggregate stats per date: {date -> {total, complete, posts}}
        date_stats: dict[date, dict] = {}
        for d, _domain_id, status, post_count in rows:
            if d not in date_stats:
                date_stats[d] = {"total": 0, "complete": 0, "posts": 0}
            date_stats[d]["total"] += 1
            date_stats[d]["posts"] += post_count
            if status == "complete":
                date_stats[d]["complete"] += 1

        available = sorted(date_stats.keys(), reverse=True)

        def in_range(from_d: date, to_d: date) -> list[date]:
            return [d for d in available if from_d <= d <= to_d]

        def best_stats(days_in_range: list[date]) -> dict:
            if not days_in_range:
                return {"days": 0, "total": 0, "complete": 0, "posts": 0}
            most_recent = days_in_range[0]
            return {
                "days": len(days_in_range),
                "total": date_stats[most_recent]["total"],
                "complete": date_stats[most_recent]["complete"],
                # Summed over the whole range — drives the history status dot
                "posts": sum(date_stats[d]["posts"] for d in days_in_range),
            }

        periods = []

        # ── Last 7 days: one entry per day ──────────────────────────────
        daily = []
        for i in range(7):
            d = today - timedelta(days=i)
            if d not in date_stats:
                continue
            stats = best_stats([d])
            if i == 0:
                label = f"Today · {d.strftime('%b %-d')}"
            elif i == 1:
                label = f"Yesterday · {d.strftime('%b %-d')}"
            else:
                label = d.strftime("%A · %b %-d")
            daily.append({
                "id": f"day-{d.isoformat()}",
                "label": label,
                "sublabel": None,
                "from_date": d.isoformat(),
                "to_date": d.isoformat(),
                "stats": stats,
                "auto_open": i == 0,
            })
        if daily:
            periods.append({"section": "Last 7 days", "entries": daily})

        # ── Past 4 weeks: one entry per week ─────────────────────────────
        weekly = []
        for w in range(4):
            week_end = today - timedelta(days=7 + w * 7)
            week_start = week_end - timedelta(days=6)
            days_in = in_range(week_start, week_end)
            if not days_in:
                continue
            weekly.append({
                "id": f"week-{week_start.isoformat()}",
                "label": f"Week of {week_start.strftime('%b %-d')}",
                "sublabel": f"{week_start.strftime('%b %-d')} – {week_end.strftime('%b %-d')}",
                "from_date": week_start.isoformat(),
                "to_date": week_end.isoformat(),
                "stats": best_stats(days_in),
                "auto_open": False,
            })
        if weekly:
            periods.append({"section": "Past 4 weeks", "entries": weekly})

        # ── Earlier: one entry per calendar month ─────────────────────────
        cutoff = today - timedelta(days=28)
        old_dates = [d for d in available if d < cutoff]
        seen_months: set[tuple] = set()
        monthly = []
        for d in old_dates:
            key = (d.year, d.month)
            if key in seen_months:
                continue
            seen_months.add(key)
            _, last_day = cal_monthrange(d.year, d.month)
            month_start = date(d.year, d.month, 1)
            month_end = date(d.year, d.month, last_day)
            days_in = in_range(month_start, month_end)
            monthly.append({
                "id": f"month-{d.year}-{d.month:02d}",
                "label": month_start.strftime("%B %Y"),
                "sublabel": f"{len(days_in)} day{'s' if len(days_in) != 1 else ''} with data",
                "from_date": month_start.isoformat(),
                "to_date": month_end.isoformat(),
                "stats": best_stats(days_in),
                "auto_open": False,
            })
        if monthly:
            periods.append({"section": "Earlier", "entries": monthly})

        return periods

    def get_available_dates(self) -> list[str]:
        return [d.isoformat() for d in self._snapshots.get_dates_with_snapshots()]
