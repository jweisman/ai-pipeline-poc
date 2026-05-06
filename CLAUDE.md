# CLAUDE.md

Notes for Claude when working in this repo.

## Documentation upkeep

After every change to this codebase — code, prompts, schemas, flow shape,
dependencies, or run instructions — ensure both `CLAUDE.md` and `README.md`
still reflect reality. If a change makes any statement in either file
inaccurate (pipeline diagram, file layout, listed limitations, setup steps,
etc.), update those files in the same change. Do not defer this.

## AGAI backend gotchas

- AGAI ships **only OpenAI and Llama models**, no Claude. The
  Anthropic-compatible endpoint exists but rejects every model AGAI
  actually has (verified: returns "Model X is not an Anthropic model").
  Use the OpenAI-compatible endpoint via the `openai` SDK instead — that's
  what `flows/ai_client.py` does for the `agai` backend.
- Auth header is `x-auth-token`, not `Authorization` / `x-api-key`. The
  OpenAI SDK still requires *some* `api_key` value, so we pass a
  placeholder and inject the real token via `default_headers`.
- When backend is `agai`, prompt YAML's `model:` field is **ignored**.
  The model comes from `AIConfig.model_override` (web UI selector) or
  `AGAI_DEFAULT_MODEL` env var.
