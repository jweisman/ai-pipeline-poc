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
(`flows/ai_client.py::resolve_model`):

1. Per-run UI selector (`AIConfig.model_override`).
2. The backend's `*_DEFAULT_MODEL` env var.
3. A backend-specific hardcoded default (`_ANTHROPIC_DEFAULT_MODEL`,
   `_OPENAI_DEFAULT_MODEL`, `_AGAI_DEFAULT_MODEL` in `flows/ai_client.py`).

Prompt YAMLs no longer carry a `model:` field. Model selection lives
entirely in `flows/ai_client.py`. `PromptConfig` only exposes
`temperature`, `max_tokens`, `description`, `template`, `version`.

## AGAI backend gotchas

- AGAI ships **only OpenAI and Llama models**, no Claude. Its
  Anthropic-compatible endpoint rejects every model AGAI actually has
  ("Model X is not an Anthropic model").
- Its OpenAI-compatible endpoint is **gpt_*-only** — it 500s for
  `llama_32_instruct_90b` and other non-OpenAI models. We use the
  **native** endpoint (`/large-language-models/{model}/`) instead so
  every listed model works, including Llama.
- Auth header is `x-auth-token`, not `Authorization` / `x-api-key`.
- AGAI silently 200s on unknown / reasoning-class models with an empty
  `completion`, so `_run_agai` raises explicitly when the completion is
  missing/empty (surfacing the full `results[0]` payload) and warns when
  `output_tokens` hits the requested `max_tokens` (the parallel
  Anthropic/OpenAI checks key off `stop_reason == "max_tokens"` and
  `finish_reason == "length"`).

## QC pipeline

A second Prefect flow under `qc/` audits extractions produced by the main
pipeline. The QC pipeline operates on `output/*.extracted.json` (and the
matching syllabus in `syllabi/`) and writes its own artifacts to
`qc_output/`.

- `qc/schemas.py` — `QCCheckResult`, `JudgeResult`, `QCReport`. The
  report has `overall_status` ∈ {pass, warn, fail} and a
  `needs_human_review` boolean.
- `qc/checks.py` — deterministic, pure-function checks over a
  `CourseExtraction`. No I/O, no LLM. New checks: write a `_check_*`
  function and append it to `ALL_CHECKS` at the bottom of that file.
  Severity convention: `error` checks roll the report up to `fail` on
  failure; `warn` to `warn`; `info` never escalates.
- `qc/judge.py` — single LLM-as-judge call (faithfulness + completeness
  + categorization audit). Reuses `flows.ai_client.run_prompt` and the
  same backend dispatcher; the judge prompt lives in
  `qc_prompts/judge_extraction.yaml`. The judge audits — it does not
  re-extract.
- `qc/report.py` — rolls deterministic + judge results into a
  `QCReport`. Writes `qc_output/<stem>.qc.json` always, and
  `qc_output/<stem>.review.json` when `needs_human_review` (stub HITL
  record with placeholder `assigned_to`, `decision`, `decided_at`).
- `qc/qc_flow.py` — Prefect flow with `qc_one(...)` and `qc_all(...)`
  entry points. CLI: `python -m qc.qc_flow [path...] [--no-judge]`.

Prompt loader: `flows.prompts.render_prompt(name, prompts_dir=...)`
takes an optional directory so QC prompts live in `qc_prompts/`
without polluting `prompts/`. Existing call sites (the main flow tasks)
keep working unchanged because the kwarg is optional.
