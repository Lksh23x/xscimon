"""Mock adapters — used in tests and when env credentials are absent."""
import math
import random
from datetime import datetime, UTC, timedelta
from typing import Optional
from .base import FetchedPost, UserProfile

_SAMPLE_TEXTS = [
    "New preprint on protein folding using diffusion models — results look promising.",
    "Thread on why #CRISPR base editing is underrated in therapeutic contexts.",
    "Interesting paper comparing gene expression across cell types at single-cell resolution.",
    "Hot take: most genomics ML papers overfit to TCGA. Here's why that matters.",
    "Just published: metabolic flux analysis at scale using isotope tracing.",
    "Unpopular opinion: benchmarking in computational biology is fundamentally broken.",
]


class MockXAPIAdapter:
    """Returns deterministic fake posts. call_count is always 1 per call."""

    def fetch_timeline(self, handle: str, since: datetime,
                       user_id: Optional[str] = None,
                       until: Optional[datetime] = None) -> tuple[list[FetchedPost], int, bool]:
        now = datetime.now(UTC)
        # Spread posts across 3 calendar days so date-bucketing is exercised.
        offsets_hours = [2, 26, 50]
        posts = [
            FetchedPost(
                post_id=f"mock-{handle}-{i}",
                author_handle=handle,
                text=_SAMPLE_TEXTS[i % len(_SAMPLE_TEXTS)],
                created_at=now - timedelta(hours=offsets_hours[i]),
                likes=random.randint(5, 500),
                retweets=random.randint(0, 100),
            )
            for i in range(3)
            if now - timedelta(hours=offsets_hours[i]) >= since
            and (until is None or now - timedelta(hours=offsets_hours[i]) < until)
        ]
        return posts, 1, False

    def search(self, query: str, since: datetime) -> tuple[list[FetchedPost], int]:
        posts = [
            FetchedPost(
                post_id=f"mock-search-{query[:8]}-{i}",
                author_handle=f"user_{i}",
                text=f"[keyword match] {_SAMPLE_TEXTS[i % len(_SAMPLE_TEXTS)]}",
                created_at=datetime.now(UTC) - timedelta(days=i),
                likes=random.randint(1, 200),
                retweets=random.randint(0, 50),
            )
            for i in range(5)
        ]
        return posts, 1

    def verify_account(self, handle: str) -> tuple[bool, str | None, str | None, int | None]:
        followers = random.randint(500, 80_000)
        return True, f"Mock bio for @{handle} — researcher and scientist.", f"mock-uid-{handle}", followers

    def lookup_users(self, handles: list[str]) -> tuple[dict[str, UserProfile], int]:
        profiles = {
            h.lower(): UserProfile(f"mock-uid-{h}",
                                   f"Mock bio for @{h} — researcher and scientist.",
                                   random.randint(500, 80_000))
            for h in handles
        }
        return profiles, math.ceil(len(handles) / 100)


class MockLLMAdapter:
    """Returns deterministic scores based on text length (good enough for tests)."""

    def score_batch(self, post_texts: list[str], context: Optional[str]) -> list[float]:
        return [min(1.0, len(text) / 280) for text in post_texts]


class MockEmailAdapter:
    """Captures sent emails in-memory instead of transmitting them."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, html_body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": html_body})
