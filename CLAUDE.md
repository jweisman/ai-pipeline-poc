# CLAUDE.md

Notes for Claude when working in this repo.

## Documentation upkeep

After every change to this codebase — code, prompts, schemas, flow shape,
dependencies, or run instructions — ensure both `CLAUDE.md` and `README.md`
still reflect reality. If a change makes any statement in either file
inaccurate (pipeline diagram, file layout, listed limitations, setup steps,
etc.), update those files in the same change. Do not defer this.

## Backends

`flows/ai_client.py` dispatches across three backends, all returning the
same parsed-dict contract to the flow:

- `anthropic` — public Anthropic API via the `anthropic` SDK.
- `openai` — public OpenAI API via the `openai` SDK.
- `agai` — Clarivate AGAI via its **native** `POST /large-language-models/{model}/`
  endpoint over `httpx`.

All three use the same model-resolution precedence
(`AIConfig.resolve_model`):

1. Per-run UI selector (`AIConfig.model_override`).
2. The backend's `*_DEFAULT_MODEL` env var.
3. For anthropic only: the prompt YAML's `model:` field. For openai/agai
   that field names a Claude model and is ignored — they fall through to
   a hardcoded default (`gpt-4o-mini`, `gpt_4o`).

## AGAI backend gotchas

- AGAI ships **only OpenAI and Llama models**, no Claude. Its
  Anthropic-compatible endpoint rejects every model AGAI actually has
  ("Model X is not an Anthropic model").
- Its OpenAI-compatible endpoint is **gpt_*-only** — it 500s for
  `llama_32_instruct_90b` and other non-OpenAI models. We use the
  **native** endpoint (`/large-language-models/{model}/`) instead so
  every listed model works, including Llama.
- Auth header is `x-auth-token`, not `Authorization` / `x-api-key`.
- When backend is `agai` (or `openai`), prompt YAML's `model:` field is
  **ignored**. The model comes from `AIConfig.model_override` (web UI
  selector) or the backend's `*_DEFAULT_MODEL` env var. For `anthropic`,
  YAML's `model:` is used only as a final fallback when neither the UI
  override nor `ANTHROPIC_DEFAULT_MODEL` is set.
