"""
Thin client for whatever LLM backend we're talking to. Today this calls the
Anthropic API directly. When AGAI is the backend, only this file changes:
the function signatures stay the same, but the implementation calls AGAI's
endpoint instead.

The function returns a parsed dict from the model's JSON output. JSON parsing
and validation happen in the calling task so that errors surface at task
boundaries with full Prefect observability.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
load_dotenv()

import anthropic


# Single shared client. The Anthropic SDK reads ANTHROPIC_API_KEY from env.
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it before running the flow."
            )
        _client = anthropic.Anthropic()
    return _client


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model added them despite instructions."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    if fence:
        return fence.group(1)
    return text


def run_prompt(
    *,
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """
    Send a single-shot prompt to the LLM and parse the response as JSON.

    Raises ValueError if the response is not parseable as JSON. We let that
    propagate up to the Prefect task so the failure is visible in the run UI
    rather than swallowed.
    """
    client = _get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )

    # Concatenate all text blocks (in practice there's one, but be defensive)
    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    raw = "".join(text_parts)
    cleaned = _strip_fences(raw)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Include a snippet of the response to make debugging easier
        snippet = cleaned[:500]
        raise ValueError(
            f"Model returned non-JSON response. Parse error: {e}. "
            f"Response starts with: {snippet!r}"
        ) from e
