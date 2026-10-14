"""Protocols (interfaces) for all external service adapters."""
from datetime import datetime
from typing import NamedTuple, Optional, Protocol, runtime_checkable


class FetchedPost:
    __slots__ = ("post_id", "author_handle", "text", "created_at", "likes", "retweets")

    def __init__(self, post_id: str, author_handle: str, text: str,
                 created_at: datetime, likes: int = 0, retweets: int = 0):
        self.post_id = post_id
        self.author_handle = author_handle
        self.text = text
        self.created_at = created_at
        self.likes = likes
        self.retweets = retweets

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "author_handle": self.author_handle,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "likes": self.likes,
            "retweets": self.retweets,
        }


class UserProfile(NamedTuple):
    user_id: str
    description: Optional[str]
    followers_count: Optional[int]


@runtime_checkable
class XAPIAdapter(Protocol):
    def fetch_timeline(self, handle: str, since: datetime,
                       user_id: Optional[str] = None,
                       until: Optional[datetime] = None) -> tuple[list[FetchedPost], int, bool]:
        """Returns (posts, api_calls_used, truncated). Pass user_id to skip the handle→id
        lookup. `until` bounds the window on the right (exclusive); None means 'up to now'.
        `truncated` is True when the page cap stopped the fetch before it reached
        `since`, so posts older than the oldest returned one are missing."""
        ...

    def search(self, query: str, since: datetime) -> tuple[list[FetchedPost], int]:
        """Returns (posts, api_calls_used)."""
        ...

    def verify_account(self, handle: str) -> tuple[bool, str | None, str | None, int | None]:
        """Returns (exists, bio_description, x_user_id, followers_count). Costs 1 API call.
        exists=False means the account genuinely doesn't exist; transport/API
        errors (rate limit, auth, network) raise instead."""
        ...

    def lookup_users(self, handles: list[str]) -> tuple[dict[str, UserProfile], int]:
        """Batch profile lookup — up to 100 handles per API call.
        Returns ({lowercased handle: profile}, api_calls_used). Handles that don't
        exist are simply absent from the dict; API/transport errors raise."""
        ...


@runtime_checkable
class LLMAdapter(Protocol):
    def score_batch(self, post_texts: list[str], context: Optional[str]) -> list[float]:
        """Returns one relevance score (0.0–1.0) per text, in input order."""
        ...


@runtime_checkable
class EmailAdapter(Protocol):
    def send(self, to: str, subject: str, html_body: str) -> None:
        ...
