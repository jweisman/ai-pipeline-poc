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
- On any non-2xx AGAI response, `_log_agai_failure` dumps the request
  URL + body, response headers + body (first 4000 chars), and a
  copy-pasteable `curl` reproduction with the auth token replaced by a
  `$AGAI_AUTH_TOKEN` placeholder. The dump goes through `logger.error`
  so it shows up in the SSE log stream and is safe to share with AGAI
  support without leaking the token.

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
  re-extract. The judge takes its **own `AIConfig`** (separate from the
  inference config) so it can run on a different model family —
  best-practice for LLM-as-judge: a same-family judge is biased toward
  its own outputs (self-preference). `qc_one` accepts a `judge_ai_config`
  parameter; if omitted it falls back to `ai_config` (degraded but
  functional).
- `qc/report.py` — rolls deterministic + judge results into a
  `QCReport`. Writes `qc_output/<stem>.qc.json` always, and
  `qc_output/<stem>.review.json` when `needs_human_review` (stub HITL
  record with placeholder `assigned_to`, `decision`, `decided_at`).
- `qc/qc_flow.py` — Prefect flow with `qc_one(...)` and `qc_all(...)`
  entry points. CLI: `python -m qc.qc_flow [path...] [--no-judge]`.
  Each task emits `qc_load` / `qc_checks` / `qc_judge` / `qc_write`
  stage events through `flows.stage_events.emit_stage`, so the web UI
  can drive a progress diagram for QC the same way it does for
  extraction.

Web exposure: `web/app.py` adds `POST /qc`, `GET /qc/{id}/events`
(SSE — same envelope as `/runs/{id}/events`), `GET /qc/{id}/result`,
and `GET /qc-report/{stem}` (returns the most recent QC report on
disk for a syllabus stem, or 404). The result page in the UI hosts
the "Run QC" button and a structured report card — extraction and QC
are deliberately separate user actions because QC costs a (separate)
LLM call. Concurrency: at most one extraction run and one QC run at
a time (separate locks; single-user POC).

The QC panel has a **separate Judge backend/model selector** (its own
segmented control + model dropdown) that defaults to a different family
from the inference selector on first load (`anthropic` ↔ `openai`,
`agai` → `anthropic`). After the user picks a judge backend it persists
to its own localStorage prefix (`ai-pipeline-poc.judge.*`) and is no
longer auto-synced to the inference selector. `POST /qc` accepts
`judge_backend` and `judge_model` alongside `backend` / `model`; both
fall back to the inference values if omitted. The two model selectors
share an in-memory `SHARED_MODEL_CACHE` in `web/static/app.js` so each
backend's `/<backend>/models` endpoint is hit at most once per page load
even when both selectors land on the same backend.

Prompt loader: `flows.prompts.render_prompt(name, prompts_dir=...)`
takes an optional directory so QC prompts live in `qc_prompts/`
without polluting `prompts/`. Existing call sites (the main flow tasks)
keep working unchanged because the kwarg is optional.
