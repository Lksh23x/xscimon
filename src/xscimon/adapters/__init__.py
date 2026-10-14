"""
Adapter factory — returns real adapters when env vars are present,
mock adapters otherwise. Services depend only on the protocols in base.py.
"""
import os
from .base import XAPIAdapter, LLMAdapter, EmailAdapter, FetchedPost, UserProfile
from .mock import MockXAPIAdapter, MockLLMAdapter, MockEmailAdapter


def is_mock_mode() -> bool:
    return not bool(os.environ.get("X_BEARER_TOKEN"))


def get_x_adapter() -> XAPIAdapter:
    if os.environ.get("X_BEARER_TOKEN"):
        from .x_api import TweepyXAPIAdapter
        return TweepyXAPIAdapter()
    return MockXAPIAdapter()


def get_llm_adapter() -> LLMAdapter:
    if os.environ.get("ANTHROPIC_API_KEY"):
        from .llm import ClaudeLLMAdapter
        return ClaudeLLMAdapter()
    return MockLLMAdapter()


def get_email_adapter() -> EmailAdapter:
    if os.environ.get("SMTP_USER"):
        from .email import ProtonMailAdapter
        return ProtonMailAdapter()
    return MockEmailAdapter()


__all__ = [
    "XAPIAdapter", "LLMAdapter", "EmailAdapter", "FetchedPost", "UserProfile",
    "MockXAPIAdapter", "MockLLMAdapter", "MockEmailAdapter",
    "get_x_adapter", "get_llm_adapter", "get_email_adapter",
]
