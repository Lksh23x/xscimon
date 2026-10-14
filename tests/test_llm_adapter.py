"""Tests for ClaudeLLMAdapter batch scoring: chunking, parsing, clamping, fallback."""
import json
import logging
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def adapter_with_fake_client(monkeypatch):
    """Build a ClaudeLLMAdapter whose Anthropic client is a MagicMock."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("xscimon.adapters.llm.anthropic.Anthropic") as fake_anthropic:
        from xscimon.adapters.llm import ClaudeLLMAdapter
        adapter = ClaudeLLMAdapter()
    return adapter, fake_anthropic.return_value


def _response_with_scores(scores):
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps({"scores": scores}))]
    return msg


def test_scores_parsed_and_clamped(adapter_with_fake_client):
    adapter, client = adapter_with_fake_client
    client.messages.create.return_value = _response_with_scores([0.2, 1.7, -0.3])

    scores = adapter.score_batch(["a", "b", "c"], context="genomics research")
    assert scores == [0.2, 1.0, 0.0]
    assert client.messages.create.call_count == 1

    # Context is sent as a cacheable system block, posts in the user message.
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert "genomics research" in kwargs["system"][1]["text"]
    assert "POST 3" in kwargs["messages"][0]["content"]


def test_large_batches_are_chunked(adapter_with_fake_client):
    adapter, client = adapter_with_fake_client
    client.messages.create.side_effect = lambda **kw: _response_with_scores(
        [0.5] * kw["messages"][0]["content"].count("POST ")
    )

    scores = adapter.score_batch([f"text {i}" for i in range(45)], context=None)
    assert len(scores) == 45
    assert client.messages.create.call_count == 3  # 20 + 20 + 5


def test_score_count_mismatch_falls_back_and_logs(adapter_with_fake_client, caplog):
    adapter, client = adapter_with_fake_client
    client.messages.create.return_value = _response_with_scores([0.9])  # 1 score for 3 posts

    with caplog.at_level(logging.WARNING, logger="xscimon.adapters.llm"):
        scores = adapter.score_batch(["a", "b", "c"], context=None)

    assert scores == [0.5, 0.5, 0.5]
    assert any("falling back" in r.message for r in caplog.records)


def test_api_error_falls_back_and_logs(adapter_with_fake_client, caplog):
    adapter, client = adapter_with_fake_client
    client.messages.create.side_effect = RuntimeError("overloaded")

    with caplog.at_level(logging.WARNING, logger="xscimon.adapters.llm"):
        scores = adapter.score_batch(["a", "b"], context=None)

    assert scores == [0.5, 0.5]
    assert any("overloaded" in r.message for r in caplog.records)


def test_empty_batch_makes_no_api_call(adapter_with_fake_client):
    adapter, client = adapter_with_fake_client
    assert adapter.score_batch([], context=None) == []
    client.messages.create.assert_not_called()
