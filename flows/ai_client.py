"""
Thin client for whatever LLM backend we're talking to.

Two backends are supported:

  - "anthropic": calls the public Anthropic API directly using the anthropic
    SDK. Models come from each prompt YAML's `model:` field.
  - "agai": calls Clarivate's AGAI Platform via its OpenAI-compatible
    endpoint. AGAI ships only OpenAI/Llama models, so the prompt YAML's
    `model:` field is ignored and the model is chosen at runtime (web UI
    selector or AGAI_DEFAULT_MODEL env var).

Backend selection is per call (via AIConfig), with env-var defaults so the
CLI keeps working without changes:

  AI_BACKEND=anthropic|agai     (default: anthropic)
  ANTHROPIC_API_KEY=...         (anthropic backend)
  AGAI_BASE_URL=https://...     (agai backend)
  AGAI_AUTH_TOKEN=...           (agai backend)
  AGAI_DEFAULT_MODEL=gpt_4o     (agai backend, optional fallback)

Both backends return a parsed dict from the model's JSON output. JSON
parsing and validation happen in the calling task so errors surface at
task boundaries with full Prefect observability.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from dotenv import load_dotenv
load_dotenv()

import anthropic
from openai import OpenAI


Backend = Literal["anthropic", "agai"]


@dataclass(frozen=True)
class AIConfig:
    """Per-run AI backend configuration. Threaded through the flow so a single
    process can serve multiple backends (e.g. the web UI lets the user pick)."""
    backend: Backend = "anthropic"
    model_override: str | None = None  # only honored by the AGAI backend


def default_config() -> AIConfig:
    """Read the default backend from env. Used when no explicit config is
    passed (CLI runs, unit tests)."""
    backend = os.environ.get("AI_BACKEND", "anthropic").lower()
    if backend not in ("anthropic", "agai"):
        raise RuntimeError(
            f"AI_BACKEND must be 'anthropic' or 'agai', got {backend!r}"
        )
    return AIConfig(backend=backend)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Clients (lazy, cached per backend)
# ---------------------------------------------------------------------------

_anthropic_client: anthropic.Anthropic | None = None
_agai_client: OpenAI | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it before running the flow."
            )
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def _get_agai_client() -> OpenAI:
    global _agai_client
    if _agai_client is None:
        base = os.environ.get("AGAI_BASE_URL")
        token = os.environ.get("AGAI_AUTH_TOKEN")
        if not base:
            raise RuntimeError(
                "AGAI_BASE_URL not set. Point this at the AGAI host root, "
                "e.g. https://agai-platform-api.prod.int.proquest.com"
            )
        if not token:
            raise RuntimeError("AGAI_AUTH_TOKEN not set.")
        # AGAI authenticates via x-auth-token, not the OpenAI Authorization
        # header. The OpenAI SDK still requires *some* api_key value, so a
        # placeholder is fine — AGAI ignores it.
        _agai_client = OpenAI(
            api_key="unused",
            base_url=base.rstrip("/") + "/large-language-models-openai-compatible",
            default_headers={"x-auth-token": token},
        )
    return _agai_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` fences if the model added them despite instructions."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    if fence:
        return fence.group(1)
    return text


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        snippet = cleaned[:500]
        raise ValueError(
            f"Model returned non-JSON response. Parse error: {e}. "
            f"Response starts with: {snippet!r}"
        ) from e


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def _run_anthropic(
    *, prompt: str, model: str, temperature: float, max_tokens: int
) -> str:
    client = _get_anthropic_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    return "".join(text_parts)


def _run_agai(
    *, prompt: str, model: str, temperature: float, max_tokens: int
) -> str:
    client = _get_agai_client()
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_model(config: AIConfig, prompt_model: str) -> str:
    """Decide which model name to send to the backend.

    Anthropic: the prompt YAML's `model:` is authoritative.
    AGAI: the YAML's model name doesn't apply (AGAI has no Claude models).
          Use the per-run override from the UI, falling back to
          AGAI_DEFAULT_MODEL, then a reasonable default.
    """
    if config.backend == "anthropic":
        return prompt_model
    return (
        config.model_override
        or os.environ.get("AGAI_DEFAULT_MODEL")
        or "gpt_4o"
    )


def run_prompt(
    *,
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    config: AIConfig | None = None,
) -> dict[str, Any]:
    """
    Send a single-shot prompt to the configured LLM backend and parse the
    response as JSON.

    `model` is the prompt's declared model (from YAML). The active backend
    decides whether to honor it (anthropic) or substitute an AGAI model name
    via resolve_model().

    Raises ValueError if the response isn't parseable as JSON. We let that
    propagate up to the Prefect task so the failure is visible in the run UI.
    """
    cfg = config or default_config()
    effective_model = resolve_model(cfg, model)

    if cfg.backend == "anthropic":
        raw = _run_anthropic(
            prompt=prompt,
            model=effective_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    else:
        raw = _run_agai(
            prompt=prompt,
            model=effective_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return _parse_json(raw)
