# AI Pipeline POC (Prefect)

A working Prefect pipeline that demonstrates an  encapsulated AI architecture: Prefect orchestrates a sequence of LLM calls, prompts live as
versioned YAML files, data flows between tasks as typed Pydantic models,
and the result is a single structured JSON document.

This pipeline takes a syllabus and returns course-level metadata plus the
course's modules with their assignments and instructional materials, in order.

The LLM backend is selectable per run. Three options, all with a live
model dropdown sourced from each provider's API:

- **Anthropic** (default) — public Anthropic API. Models listed live via
  `client.models.list()`. UI selection overrides the per-backend defaults.
- **OpenAI** — public OpenAI API. Chat-capable models listed live via
  `client.models.list()`, filtered server-side.
- **AGAI Platform** — Clarivate's internal LLM gateway, hit via its
  **native** `/large-language-models/{model}/` endpoint (not the
  OpenAI-compatible facade — that one rejects Llama and other non-GPT
  models). Models listed live from AGAI.

## What's in here

```
ai-pipeline-poc/
├── flows/
│   ├── course_analyzer.py        # The Prefect flow itself (4 tasks)
│   ├── prompts.py                # YAML loader + Jinja2 renderer
│   ├── ai_client.py              # Thin wrapper: dispatches to anthropic / openai / AGAI backend
│   └── stage_events.py           # Lightweight progress hook for the web UI
├── web/
│   ├── app.py                    # FastAPI server: index, /runs, SSE event stream
│   ├── templates/index.html      # Single-page UI
│   └── static/                   # CSS + vanilla JS frontend
├── prompts/
│   ├── extract_course_info.yaml  # Stage 0 prompt (course-level metadata)
│   ├── extract_modules.yaml      # Stage 1 prompt
│   └── extract_items.yaml        # Stage 2 prompt
├── qc/
│   ├── schemas.py            # QCCheckResult, JudgeResult, QCReport
│   ├── checks.py             # Deterministic checks over CourseExtraction
│   ├── judge.py              # LLM-as-judge wrapper (reuses flows/ai_client.py)
│   ├── report.py             # Status rollup + qc_output/ writers
│   └── qc_flow.py            # Prefect flow: qc_one / qc_all
├── qc_prompts/
│   └── judge_extraction.yaml # LLM-as-judge prompt (faithfulness audit)
├── schemas/
│   └── models.py             # Pydantic data contracts
├── syllabi/
│   ├── bellevue_engl101.txt  # Real syllabus #1 (Bellevue College ENGL 101)
│   └── ubc_comm663.txt       # Real syllabus #2 (UBC marketing PhD course)
├── tests/
│   ├── test_prompts.py       # Verifies prompt rendering
│   ├── test_assemble.py      # Verifies deterministic assembly logic
│   └── test_qc_checks.py     # Verifies QC deterministic checks + rollup
├── output/                   # Generated extraction JSON lands here
├── qc_output/                # Generated QC reports + HITL review tasks land here
└── requirements.txt
```

## How the pipeline works

```
syllabus.txt
     │
     ▼
┌─────────────────────┐
│ extract_course_info │  ── LLM call #1 ──▶  CourseInfo
└─────────────────────┘                      (title, code, department, level,
     │                                        institution, term, instructors,
     │                                        description, course-level objectives)
     ▼
┌─────────────────────┐
│ extract_modules     │  ── LLM call #2 ──▶  list[Module]
└─────────────────────┘                      (order, title, objectives)
     │
     ▼
┌─────────────────────┐
│ extract_items       │  ── LLM call #3 ──▶  list[CourseItem]
└─────────────────────┘  (gets modules as       (materials + assignments,
     │                    context input)         each tagged with module_order_index)
     ▼
┌─────────────────────┐
│ assemble            │  ── pure Python ──▶  CourseExtraction
└─────────────────────┘                      (course_info + modules with items
     │                                        nested in order)
     ▼
┌─────────────────────┐
│ write_output        │  ── pure Python ──▶  output/<name>.extracted.json
└─────────────────────┘
```

Three LLM calls, one assembly step, one write. Each task is independently
retryable; data passes between them as validated Pydantic models.

## Setup

```bash
cd ai-pipeline-poc
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pick one or more backends (the web UI lets you toggle per run; only
unused backends can be left unset):

```bash
# Anthropic (default)
export ANTHROPIC_API_KEY=sk-ant-...
export ANTHROPIC_DEFAULT_MODEL=claude-sonnet-4-20250514   # optional; default for Anthropic runs

# OpenAI
export OPENAI_API_KEY=sk-...
export OPENAI_DEFAULT_MODEL=gpt-4o-mini   # optional; default for OpenAI runs

# AGAI Platform
export AGAI_BASE_URL=https://agai-platform-api.prod.int.proquest.com
export AGAI_AUTH_TOKEN=...
export AGAI_DEFAULT_MODEL=gpt_4o          # optional; default for AGAI runs

# Optional: change the default backend for CLI runs (UI overrides per run)
export AI_BACKEND=anthropic               # or: openai | agai
```

## Run the demo

Run against either of the included syllabi:

```bash
python -m flows.course_analyzer syllabi/bellevue_engl101.txt
python -m flows.course_analyzer syllabi/ubc_comm663.txt
```

Output appears in `output/<syllabus-name>.extracted.json`.

You'll also see Prefect's run logs in the terminal — for each task, it will
log the model used, the prompt size, and the count of items extracted. This
is the same observability you'd get in the Prefect Cloud UI.

## Run the web UI

A small FastAPI app wraps the pipeline in a browser interface: pick a
syllabus from `syllabi/`, watch the workflow run in real time, and view the
extracted course as a structured page (with a JSON download).

```bash
python -m web.app
# or, with auto-reload during development:
# uvicorn web.app:app --reload
```

Then open http://127.0.0.1:8000.

What you get:
- Backend selector (Anthropic / OpenAI / AGAI). When OpenAI or AGAI is
  selected, a model dropdown is populated live from `GET /openai/models`
  or `GET /agai/models` respectively (server-side proxies of the
  upstream listings). The chosen backend and per-backend model selection
  persist to `localStorage` between visits.
- Live diagram of the 5-task pipeline, with the active stage highlighted.
- Streaming logs (Server-Sent Events) as each task runs — same lines you'd
  see in the terminal.
- Error state with the failure message if a task fails.
- Result page rendering: course-info card (title, code, level, instructors,
  term, description, course objectives), then each module with its items
  in a clean table, then unassigned items if any.

How progress works: each task emits explicit `stage:start` / `stage:complete`
events through `flows/stage_events.py` (a `ContextVar`-scoped sink), and
the flow function wraps each task call in `emit_on_failure(...)` so a
single `stage:error` event is emitted on terminal failure (after retries
are exhausted). The web layer installs a sink that translates these into
SSE messages, so the diagram is driven by the flow itself rather than by
string-matching on log lines. Any other consumer (the real app,
a CLI wrapper, a test harness) gets the same start/complete/error contract
for free. Outside any sink (CLI runs, unit tests) the emits are no-ops.

This is a single-process POC: the flow runs in a background thread inside
the same Python process as the web server. Concurrent runs are intentionally
blocked (HTTP 409); the UI is single-user.

## QC pipeline (evals + LLM-as-judge + HITL)

A second Prefect flow under `qc/` audits extractions produced by the
main pipeline. It runs over `output/*.extracted.json` and writes its
own artifacts to `qc_output/`. Two complementary signals:

- **Deterministic checks** (`qc/checks.py`) — pure-function checks over
  a `CourseExtraction`: required fields populated, module ordering
  unique and contiguous, item-type/format consistency
  (materials carry `material_format`, assignments don't carry
  `citation`), no duplicate item titles within a module, etc. No LLM,
  free, runs every time.
- **LLM-as-judge** (`qc/judge.py` + `qc_prompts/judge_extraction.yaml`)
  — one LLM call that compares the extraction against the source
  syllabus for faithfulness, completeness, and correct categorization.
  Reuses the same backend dispatcher as the main pipeline, so the
  Anthropic / OpenAI / AGAI selection works identically.

The two streams roll up into a `QCReport` with:

- `overall_status` ∈ `pass` / `warn` / `fail`
- `needs_human_review` (true whenever overall is not `pass`)
- `fields_flagged` — deduped list of dotted paths into the extraction
  (e.g. `modules[2].items[0].material_format`).

Outputs:

- `qc_output/<stem>.qc.json` — always written.
- `qc_output/<stem>.review.json` — written when
  `needs_human_review`. This is a stub HITL (human-in-the-loop)
  review-task record with placeholder `assigned_to`, `decision`,
  `decided_at`, `notes` fields. The shape is the contract a real
  review queue / UI would consume; the queue itself is a later phase.

```
output/foo.extracted.json
        │
        ▼
┌────────────────────────────┐
│ run_deterministic_checks   │  ── pure Python ──▶  list[QCCheckResult]
└────────────────────────────┘
        │
        ▼
┌────────────────────────────┐
│ run_judge                  │  ── LLM call ─────▶  JudgeResult
└────────────────────────────┘  (skipped with --no-judge,
        │                       or if syllabus not found)
        ▼
┌────────────────────────────┐
│ build_report + write_qc    │  ── pure Python ──▶  qc_output/foo.qc.json
└────────────────────────────┘                      qc_output/foo.review.json (if review needed)
```

Run it:

```bash
# QC every output/*.extracted.json
python -m qc.qc_flow

# QC just one
python -m qc.qc_flow output/bellevue_engl101.extracted.json

# Skip the LLM judge (free, fast — only deterministic checks)
python -m qc.qc_flow --no-judge
```

The QC flow uses the same `AI_BACKEND` / `*_DEFAULT_MODEL` env vars as
the main pipeline. To add a new deterministic check, write a
`_check_*` function in `qc/checks.py` and append it to `ALL_CHECKS`.

## Run the tests (no API key required)

```bash
pytest tests/
```

These tests cover prompt rendering, the assembly logic, and the QC
deterministic checks + rollup without ever hitting the LLM. They run in
well under a second and can sit in CI.

## Trying it through the Prefect UI

If you want to see this in the Prefect Cloud UI rather than just CLI logs:

```bash
prefect cloud login              # one-time
prefect deploy flows/course_analyzer.py:course_analyzer \
    --name course-analyzer-poc --pool default-agent-pool
prefect worker start --pool default-agent-pool
```

Then trigger a run from the UI with `syllabus_path` as the parameter. You
get the full DAG view, per-task inputs/outputs, and retry history.

## Design notes for the demo

A few things this POC deliberately does — and doesn't — that map to the
architecture conversation:

**Three LLM calls, not one.** A single mega-prompt could in principle do all
this, but separate prompts give us cleaner per-stage debugging, smaller
prompts (better latency and cost), and the option to use different models
per stage if we want. Course-level metadata, module structure, and the
items inside modules are independent enough to be extracted independently.

**Module list passed as JSON to stage 2.** This is the "data flowing
between prompts" pattern in action — stage 1's output is parsed, validated,
and re-serialized as input context for stage 2. We never just shovel raw
text from one LLM call to the next.

**Pydantic everywhere.** Every task input and output is a typed model. If
the LLM returns malformed JSON or the wrong shape, validation fails at
the task boundary with full visibility, not silently three steps later.

**Assembly is pure Python.** Once the LLM has done its job (semantic
understanding), the rest is deterministic stitching. No LLM call needed
for "group items by module and sort by order_index" — and no LLM
non-determinism creeping into output we can compute exactly.

**Prompts as versioned YAML.** The `version` field, `temperature`, and
`max_tokens` are co-located with the prompt text. Model selection is
deliberately *not* in the YAML — it's a per-backend concern handled in
`flows/ai_client.py` (UI selector → `*_DEFAULT_MODEL` env var → hardcoded
fallback). When we move to production we can either keep this in Git
(current setup) or move it to a prompt registry (only `flows/prompts.py`
changes).

**Backends are pluggable.** `flows/ai_client.py` dispatches on an
`AIConfig.backend` value (`anthropic` | `openai` | `agai`) that the flow
threads through every task. Adding a new backend means adding a branch
in `run_prompt(...)` and an env-var-fed client constructor — flow code,
prompts, and schemas don't move.

**AGAI uses its native endpoint, not either compatibility facade.** AGAI
exposes Anthropic-compatible and OpenAI-compatible facades on top of its
real `/large-language-models/{model}/` endpoint. Both facades are
family-restricted: the Anthropic-compatible one rejects every model AGAI
actually has ("Model X is not an Anthropic model"), and the
OpenAI-compatible one 500s for `llama_32_instruct_90b` and other
non-OpenAI models. The native endpoint accepts every model the listing
returns, so we use that. The runtime model comes from the UI selector,
falling back to the relevant `*_DEFAULT_MODEL` env var, then to a
hardcoded default in `flows/ai_client.py`.

## Known limitations of the POC

- Only handles plain text input. PDF/DOCX extraction is a separate concern
  that the real Course Analyzer would handle upstream of this pipeline.
- No structured outputs / tool use. The prompts ask for JSON and we parse
  it. Anthropic's tool use API would give stronger guarantees and is a
  natural next iteration.
- No cost or token tracking yet. For the real pipeline we'd log token
  usage from each response into Prefect task metadata.
- QC is intentionally limited in this phase. The LLM judge is a single
  generic fidelity pass (no rubric ensembles, no calibration). No golden
  datasets / partial-expected comparison yet — that lands once we have
  enough hand-curated extractions for "golden" to be meaningful. The
  HITL review-task writer produces the record but no queue / UI consumes
  it yet. The web UI does not yet expose a "Run QC" action.
