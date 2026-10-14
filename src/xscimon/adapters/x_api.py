import logging
import os
from datetime import datetime, UTC
from typing import Optional
import tweepy
from .base import FetchedPost, UserProfile

logger = logging.getLogger(__name__)

# Pagination cap per fetch/search. Each page is one API call against the daily
# budget, so this bounds the worst case for a single account or query.
_MAX_PAGES = 5

# X API v2 GET /2/users/by accepts at most 100 usernames per request.
_USERS_PER_LOOKUP = 100


class TweepyXAPIAdapter:
    def __init__(self):
        self._client = tweepy.Client(
            bearer_token=os.environ["X_BEARER_TOKEN"],
            consumer_key=os.environ["X_API_KEY"],
            consumer_secret=os.environ["X_API_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
            wait_on_rate_limit=False,
        )

    def fetch_timeline(self, handle: str, since: datetime,
                       user_id: str | None = None,
                       until: datetime | None = None) -> tuple[list[FetchedPost], int, bool]:
        calls = 0
        if not user_id:
            user_resp = self._client.get_user(username=handle)
            if not user_resp.data:
                return [], 1, False
            user_id = str(user_resp.data.id)
            calls += 1

        posts: list[FetchedPost] = []
        next_token = None
        for _ in range(_MAX_PAGES):
            resp = self._client.get_users_tweets(
                id=user_id,
                start_time=since,
                end_time=until,
                tweet_fields=["created_at", "public_metrics"],
                exclude=["replies", "retweets"],
                max_results=100,
                pagination_token=next_token,
            )
            calls += 1
            posts.extend(self._parse(resp, handle))
            next_token = (resp.meta or {}).get("next_token")
            if not next_token:
                break
        if next_token:
            logger.warning(
                "Timeline for @%s has more than %d pages since %s; "
                "older posts in the window were not fetched.",
                handle, _MAX_PAGES, since.isoformat(),
            )
        return posts, calls, next_token is not None

    def search(self, query: str, since: datetime) -> tuple[list[FetchedPost], int]:
        posts: list[FetchedPost] = []
        calls = 0
        next_token = None
        for _ in range(_MAX_PAGES):
            resp = self._client.search_recent_tweets(
                query=f"{query} -is:retweet lang:en",
                start_time=since,
                tweet_fields=["created_at", "public_metrics", "author_id"],
                expansions=["author_id"],
                user_fields=["username"],
                max_results=100,
                next_token=next_token,
            )
            calls += 1
            posts.extend(self._parse_search(resp))
            next_token = (resp.meta or {}).get("next_token")
            if not next_token:
                break
        if next_token:
            logger.warning(
                "Search '%s' has more than %d pages of results; remainder not fetched.",
                query, _MAX_PAGES,
            )
        return posts, calls

    def verify_account(self, handle: str) -> tuple[bool, str | None, str | None, int | None]:
        # Only a genuine miss maps to exists=False; rate limits, auth failures
        # and network errors propagate so callers don't mistake them for
        # "account does not exist".
        try:
            resp = self._client.get_user(
                username=handle, user_fields=["description", "public_metrics"]
            )
        except tweepy.NotFound:
            return False, None, None, None
        if not resp.data:
            return False, None, None, None
        metrics = getattr(resp.data, "public_metrics", None) or {}
        followers = metrics.get("followers_count") if metrics else None
        return True, getattr(resp.data, "description", None), str(resp.data.id), followers

    def lookup_users(self, handles: list[str]) -> tuple[dict[str, UserProfile], int]:
        profiles: dict[str, UserProfile] = {}
        calls = 0
        for i in range(0, len(handles), _USERS_PER_LOOKUP):
            resp = self._client.get_users(
                usernames=handles[i:i + _USERS_PER_LOOKUP],
                user_fields=["description", "public_metrics"],
            )
            calls += 1
            # Unknown/suspended handles come back in resp.errors, not resp.data.
            for user in resp.data or []:
                metrics = getattr(user, "public_metrics", None) or {}
                profiles[user.username.lower()] = UserProfile(
                    user_id=str(user.id),
                    description=getattr(user, "description", None),
                    followers_count=metrics.get("followers_count"),
                )
        return profiles, calls

    def _parse(self, resp, handle: str) -> list[FetchedPost]:
        if not resp.data:
            return []
        posts = []
        for tweet in resp.data:
            m = tweet.public_metrics or {}
            posts.append(FetchedPost(
                post_id=str(tweet.id),
                author_handle=handle,
                text=tweet.text,
                created_at=tweet.created_at or datetime.now(UTC),
                likes=m.get("like_count", 0),
                retweets=m.get("retweet_count", 0),
            ))
        return posts

    def _parse_search(self, resp) -> list[FetchedPost]:
        if not resp.data:
            return []
        users = {u.id: u.username for u in (resp.includes.get("users") or [])}
        posts = []
        for tweet in resp.data:
            m = tweet.public_metrics or {}
            posts.append(FetchedPost(
                post_id=str(tweet.id),
                author_handle=users.get(tweet.author_id, "unknown"),
                text=tweet.text,
                created_at=tweet.created_at or datetime.now(UTC),
                likes=m.get("like_count", 0),
                retweets=m.get("retweet_count", 0),
            ))
        return posts
