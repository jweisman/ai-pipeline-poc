"""
Thin client for whatever LLM backend we're talking to.

Three backends are supported. All three accept a per-run model override
from the UI selector; without an override the backend falls back to its
*_DEFAULT_MODEL env var, then to the prompt YAML's `model:` (anthropic
only — that field names a Claude model and isn't applicable to the
others), then to a hardcoded default.

  - "anthropic": calls the public Anthropic API via the anthropic SDK.
  - "openai": calls the public OpenAI API via the openai SDK.
  - "agai": calls Clarivate's AGAI Platform via its **native** endpoint
    (POST /large-language-models/{model}/). We use this rather than AGAI's
    OpenAI-compatible facade because the facade is family-restricted (only
    accepts gpt_*; rejects llama_* and any non-OpenAI model AGAI proxies).

Backend selection is per call (via AIConfig), with env-var defaults so the
CLI keeps working without arguments:

  AI_BACKEND=anthropic|openai|agai            (default: anthropic)
  ANTHROPIC_API_KEY=...                       (anthropic backend)
  ANTHROPIC_DEFAULT_MODEL=claude-...          (anthropic backend, optional)
  OPENAI_API_KEY=...                          (openai backend)
  OPENAI_DEFAULT_MODEL=gpt-4o-mini            (openai backend, optional)
  AGAI_BASE_URL=https://...                   (agai backend)
  AGAI_AUTH_TOKEN=...                         (agai backend)
  AGAI_DEFAULT_MODEL=gpt_4o                   (agai backend, optional)

All backends return a parsed dict from the model's JSON output. JSON
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
import httpx
from openai import OpenAI


Backend = Literal["anthropic", "openai", "agai"]


@dataclass(frozen=True)
class AIConfig:
    """Per-run AI backend configuration. Threaded through the flow so a single
    process can serve multiple backends (e.g. the web UI lets the user pick)."""
    backend: Backend = "anthropic"
    model_override: str | None = None  # honored by all backends; UI selector wins


def default_config() -> AIConfig:
    """Read the default backend from env. Used when no explicit config is
    passed (CLI runs, unit tests)."""
    backend = os.environ.get("AI_BACKEND", "anthropic").lower()
    if backend not in ("anthropic", "openai", "agai"):
        raise RuntimeError(
            f"AI_BACKEND must be 'anthropic', 'openai', or 'agai', got {backend!r}"
        )
    return AIConfig(backend=backend)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Clients (lazy, cached per backend)
# ---------------------------------------------------------------------------

_anthropic_client: anthropic.Anthropic | None = None
_openai_client: OpenAI | None = None
_agai_http: httpx.Client | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it before running the flow."
            )
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY not set. Export it before running the flow."
            )
        _openai_client = OpenAI()
    return _openai_client


def _get_agai_http() -> httpx.Client:
    global _agai_http
    if _agai_http is None:
        base = os.environ.get("AGAI_BASE_URL")
        token = os.environ.get("AGAI_AUTH_TOKEN")
        if not base:
            raise RuntimeError(
                "AGAI_BASE_URL not set. Point this at the AGAI host root, "
                "e.g. https://agai-platform-api.prod.int.proquest.com"
            )
        if not token:
            raise RuntimeError("AGAI_AUTH_TOKEN not set.")
        _agai_http = httpx.Client(
            base_url=base.rstrip("/"),
            headers={"x-auth-token": token},
            timeout=120.0,
        )
    return _agai_http


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


# OpenAI's "reasoning" model families (o-series and gpt-5+) require
# `max_completion_tokens` instead of `max_tokens` and only accept the
# default temperature (1.0). Detect by ID prefix.
_OPENAI_REASONING_PREFIXES = ("o1", "o3", "o4", "o5", "gpt-5")


def _is_openai_reasoning_model(model: str) -> bool:
    low = model.lower()
    return any(low.startswith(p) for p in _OPENAI_REASONING_PREFIXES)


def _run_openai(
    *, prompt: str, model: str, temperature: float, max_tokens: int
) -> str:
    client = _get_openai_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        # `max_completion_tokens` works on every current chat-completions
        # model and is required for reasoning models. `max_tokens` is the
        # deprecated alias.
        "max_completion_tokens": max_tokens,
    }
    if not _is_openai_reasoning_model(model):
        kwargs["temperature"] = temperature
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _run_agai(
    *, prompt: str, model: str, temperature: float, max_tokens: int
) -> str:
    """Hit AGAI's native completion endpoint. Accepts every model AGAI lists,
    including Llama — unlike the OpenAI-compatible facade which is gpt_*-only."""
    http = _get_agai_http()
    response = http.post(
        f"/large-language-models/{model}/",
        json={
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results") or []
    if not results:
        raise RuntimeError(
            f"AGAI returned no completions for model={model!r}: {data}"
        )
    completion = results[0].get("completion")
    if not completion:
        raise RuntimeError(
            f"AGAI returned an empty/missing completion for model={model!r}. "
            f"results[0] keys={list(results[0].keys())!r}, "
            f"results[0]={results[0]!r}"
        )
    return completion


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_model(config: AIConfig, prompt_model: str) -> str:
    """Decide which model name to send to the backend.

    All three backends use the same precedence: UI selector wins, then the
    backend's *_DEFAULT_MODEL env var, then a backend-specific final
    fallback. For anthropic, the prompt YAML's `model:` is treated as that
    final fallback (it names a Claude model so it actually applies); for
    openai/agai it's irrelevant and ignored.
    """
    if config.backend == "anthropic":
        return (
            config.model_override
            or os.environ.get("ANTHROPIC_DEFAULT_MODEL")
            or prompt_model
        )
    if config.backend == "openai":
        return (
            config.model_override
            or os.environ.get("OPENAI_DEFAULT_MODEL")
            or "gpt-4o-mini"
        )
    # agai
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
    decides whether to honor it (anthropic) or substitute via resolve_model().

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
    elif cfg.backend == "openai":
        raw = _run_openai(
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
