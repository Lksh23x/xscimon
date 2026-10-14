import math
import re
from datetime import datetime, UTC
from typing import Optional
from ..adapters.base import FetchedPost, LLMAdapter
from ..config import get_config

# Conversational openers that indicate a reply/reaction rather than an announcement.
_CONVERSATIONAL_RE = re.compile(
    r"^(thanks|thank you|agreed?|same here|haha|lol|congrats|congratulations"
    r"|yes[,!]?|no[,!]?|exactly|absolutely|true[,!]?|fair enough|good point"
    r"|well said|totally|indeed|right[,!]?|wow[,!]?|great[,!]?|nice[,!]?)",
    re.IGNORECASE,
)

_MIN_CHARS = 80  # posts shorter than this are rarely substantive


def _is_conversational(post: FetchedPost, high_credibility: bool) -> bool:
    text = post.text.strip()
    # Residual reply (starts with @mention)
    if text.startswith("@"):
        return True
    # Too short to be an announcement (unless high-credibility account with engagement)
    if len(text) < _MIN_CHARS and not (high_credibility and post.likes + post.retweets > 0):
        return True
    # Zero engagement on a normal/low-credibility account — likely noise
    if not high_credibility and post.likes == 0 and post.retweets == 0:
        return True
    # Conversational opener
    if _CONVERSATIONAL_RE.match(text):
        return True
    return False


def _prefilter(posts: list[FetchedPost],
               credibility_level_map: dict[str, str] | None) -> tuple[list[FetchedPost], int]:
    kept, dropped = [], 0
    for post in posts:
        level = (credibility_level_map or {}).get(post.author_handle, "normal")
        if _is_conversational(post, high_credibility=(level == "high")):
            dropped += 1
        else:
            kept.append(post)
    return kept, dropped


def score_and_rank_domain(
    posts: list[FetchedPost],
    skill_md: Optional[str],
    credibility_map: dict[str, float],   # handle → numeric weight
    llm: LLMAdapter,
    credibility_level_map: dict[str, str] | None = None,  # handle → "low"/"normal"/"high"
) -> list[dict]:
    cfg = get_config()["ranking"]["domain_weights"]
    w = cfg  # relevance, recency, engagement, credibility

    posts, _ = _prefilter(posts, credibility_level_map)
    relevances = llm.score_batch([p.text for p in posts], skill_md)

    now = datetime.now(UTC)
    scored = []
    for post, relevance in zip(posts, relevances):
        age_hours = max(0.0, (now - post.created_at).total_seconds() / 3600)
        recency = max(0.0, 1.0 - age_hours / 24)
        engagement = _normalise_engagement(post.likes + post.retweets)
        cred = credibility_map.get(post.author_handle, 1.0)

        final = (
            w["relevance"] * relevance
            + w["recency"] * recency
            + w["engagement"] * engagement
            + w["credibility"] * cred
        )
        d = post.to_dict()
        d.update({"relevance_score": round(relevance, 3), "final_score": round(final, 4)})
        if credibility_level_map is not None:
            d["credibility_level"] = credibility_level_map.get(post.author_handle, "normal")
        scored.append(d)

    return sorted(scored, key=lambda x: x["final_score"], reverse=True)


def score_and_rank_keyword(
    posts: list[FetchedPost],
    skill_md: Optional[str],
    priority_weight: float,
    llm: LLMAdapter,
) -> list[dict]:
    cfg = get_config()["ranking"]["keyword_weights"]
    w = cfg  # relevance, engagement, recency, priority

    posts, _ = _prefilter(posts, None)
    relevances = llm.score_batch([p.text for p in posts], skill_md)

    now = datetime.now(UTC)
    scored = []
    for post, relevance in zip(posts, relevances):
        age_days = max(0.0, (now - post.created_at).total_seconds() / 86400)
        recency = max(0.0, 1.0 - age_days / 30)
        engagement = _normalise_engagement(post.likes + post.retweets)

        final = (
            w["relevance"] * relevance
            + w["engagement"] * engagement
            + w["recency"] * recency
            + w["priority"] * min(1.0, priority_weight)
        )
        d = post.to_dict()
        d.update({"relevance_score": round(relevance, 3), "final_score": round(final, 4)})
        scored.append(d)

    return sorted(scored, key=lambda x: x["final_score"], reverse=True)


def _normalise_engagement(raw: int) -> float:
    """Log scale, saturating at 10k likes+retweets.

    Research accounts rarely see viral numbers — a linear /10k scale left the
    engagement weight effectively dead below ~1000 interactions. On the log
    scale: 10 → 0.26, 100 → 0.50, 1000 → 0.75, 10k+ → 1.0.
    """
    return min(1.0, math.log10(1 + raw) / 4)


def refresh_engagement(post: dict, likes: int, retweets: int) -> dict:
    """Return a stored domain post with new engagement counts. final_score moves by
    the engagement term only: relevance (LLM), recency and credibility keep the
    values they were scored with, so no LLM call is needed and older posts don't
    sink just because time has passed."""
    w = get_config()["ranking"]["domain_weights"]["engagement"]
    old = _normalise_engagement(post.get("likes", 0) + post.get("retweets", 0))
    new = _normalise_engagement(likes + retweets)
    return {**post, "likes": likes, "retweets": retweets,
            "final_score": round(post.get("final_score", 0) + w * (new - old), 4)}
