import json
import logging
import os
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)

# Posts scored per API request. Keeps each response small while amortising the
# system prompt + domain context over many posts.
_CHUNK_SIZE = 20
_FALLBACK_SCORE = 0.5

# Structured-output schema: guarantees the response parses as {"scores": [...]}.
_SCORES_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {"type": "array", "items": {"type": "number"}},
    },
    "required": ["scores"],
    "additionalProperties": False,
}


class ClaudeLLMAdapter:
    _SYSTEM = (
        "You are a relevance scoring assistant. "
        "You will receive a numbered list of social media posts and, optionally, "
        "domain context describing what is relevant. For each post, produce a float "
        "between 0.0 and 1.0 representing how relevant the post is to the domain. "
        "Return exactly one score per post, in the same order as the input."
    )

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def score_batch(self, post_texts: list[str], context: Optional[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(post_texts), _CHUNK_SIZE):
            scores.extend(self._score_chunk(post_texts[start:start + _CHUNK_SIZE], context))
        return scores

    def _score_chunk(self, texts: list[str], context: Optional[str]) -> list[float]:
        system: list[dict] = [{"type": "text", "text": self._SYSTEM}]
        if context:
            # Domain context is identical across chunks and daily runs — mark it
            # cacheable so large skill_md blocks are only paid for once per TTL.
            system.append({
                "type": "text",
                "text": f"Domain context:\n{context}",
                "cache_control": {"type": "ephemeral"},
            })
        numbered = "\n\n".join(f"POST {i + 1}:\n{text}" for i, text in enumerate(texts))
        try:
            msg = self._client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": f"Posts to score:\n\n{numbered}"}],
                output_config={"format": {"type": "json_schema", "schema": _SCORES_SCHEMA}},
            )
            raw = json.loads(msg.content[0].text)["scores"]
            if len(raw) != len(texts):
                raise ValueError(f"expected {len(texts)} scores, got {len(raw)}")
            return [max(0.0, min(1.0, float(s))) for s in raw]
        except Exception as exc:
            logger.warning(
                "LLM relevance scoring failed for a chunk of %d posts, "
                "falling back to %.1f for all of them: %s",
                len(texts), _FALLBACK_SCORE, exc,
            )
            return [_FALLBACK_SCORE] * len(texts)
