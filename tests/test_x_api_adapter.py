"""Tests for TweepyXAPIAdapter pagination, using a mocked tweepy client."""
import logging
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def adapter_with_fake_client(monkeypatch):
    for var in ["X_BEARER_TOKEN", "X_API_KEY", "X_API_SECRET",
                "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]:
        monkeypatch.setenv(var, "test")
    with patch("xscimon.adapters.x_api.tweepy.Client") as fake_tweepy:
        from xscimon.adapters.x_api import TweepyXAPIAdapter
        adapter = TweepyXAPIAdapter()
    return adapter, fake_tweepy.return_value


def _tweet(tweet_id: int):
    t = MagicMock()
    t.id = tweet_id
    t.text = f"tweet {tweet_id}"
    t.created_at = datetime.now(UTC)
    t.public_metrics = {"like_count": 1, "retweet_count": 0}
    return t


def _page(tweets, next_token=None):
    resp = MagicMock()
    resp.data = tweets
    resp.meta = {"next_token": next_token} if next_token else {}
    return resp


def test_timeline_follows_pagination_tokens(adapter_with_fake_client):
    adapter, client = adapter_with_fake_client
    client.get_users_tweets.side_effect = [
        _page([_tweet(1), _tweet(2)], next_token="tok-a"),
        _page([_tweet(3)], next_token="tok-b"),
        _page([_tweet(4)]),
    ]

    posts, calls, truncated = adapter.fetch_timeline("someone", datetime.now(UTC), user_id="42")
    assert [p.post_id for p in posts] == ["1", "2", "3", "4"]
    assert calls == 3
    assert truncated is False
    tokens = [c.kwargs["pagination_token"] for c in client.get_users_tweets.call_args_list]
    assert tokens == [None, "tok-a", "tok-b"]


def test_timeline_page_cap_logs_warning(adapter_with_fake_client, caplog):
    adapter, client = adapter_with_fake_client
    # Every page claims there is more — the adapter must stop at the cap.
    client.get_users_tweets.return_value = _page([_tweet(1)], next_token="more")

    with caplog.at_level(logging.WARNING, logger="xscimon.adapters.x_api"):
        posts, calls, truncated = adapter.fetch_timeline("someone", datetime.now(UTC), user_id="42")

    assert calls == 5  # _MAX_PAGES
    assert len(posts) == 5
    assert truncated is True
    assert any("more than 5 pages" in r.message for r in caplog.records)


def test_search_follows_next_tokens(adapter_with_fake_client):
    adapter, client = adapter_with_fake_client
    page1 = _page([_tweet(1)], next_token="tok")
    page1.includes = {"users": []}
    page2 = _page([_tweet(2)])
    page2.includes = {"users": []}
    client.search_recent_tweets.side_effect = [page1, page2]

    posts, calls = adapter.search("crispr", datetime.now(UTC))
    assert [p.post_id for p in posts] == ["1", "2"]
    assert calls == 2
    tokens = [c.kwargs["next_token"] for c in client.search_recent_tweets.call_args_list]
    assert tokens == [None, "tok"]


def test_single_page_makes_single_call(adapter_with_fake_client):
    adapter, client = adapter_with_fake_client
    client.get_users_tweets.return_value = _page([_tweet(1)])

    posts, calls, truncated = adapter.fetch_timeline("someone", datetime.now(UTC), user_id="42")
    assert calls == 1
    assert len(posts) == 1
    assert truncated is False


def _user(uid: int, username: str):
    u = MagicMock()
    u.id = uid
    u.username = username
    u.description = f"bio {username}"
    u.public_metrics = {"followers_count": uid}
    return u


def test_lookup_users_batches_100_per_call(adapter_with_fake_client):
    adapter, client = adapter_with_fake_client
    handles = [f"user{i}" for i in range(150)]

    def fake_get_users(usernames, user_fields):
        resp = MagicMock()
        # X returns canonical casing; one handle in each batch doesn't exist.
        resp.data = [_user(i, h.upper()) for i, h in enumerate(usernames[1:], 1)]
        return resp
    client.get_users.side_effect = fake_get_users

    profiles, calls = adapter.lookup_users(handles)
    assert calls == 2
    assert [len(c.kwargs["usernames"]) for c in client.get_users.call_args_list] == [100, 50]
    assert "user0" not in profiles and "user100" not in profiles
    assert profiles["user1"].user_id == "1"
    assert profiles["user1"].followers_count == 1
