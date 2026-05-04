# onCourse — Course Analyzer POC (Prefect)

A working Prefect pipeline that demonstrates an  encapsulated AI architecture: Prefect orchestrates a sequence of LLM calls, prompts live as
versioned YAML files, data flows between tasks as typed Pydantic models,
and the result is a single structured JSON document.

This pipeline takes a syllabus and returns course-level metadata plus the
course's modules with their assignments and instructional materials, in order.

## What's in here

```
oncourse-poc/
├── flows/
│   ├── course_analyzer.py        # The Prefect flow itself (4 tasks)
│   ├── prompts.py                # YAML loader + Jinja2 renderer
│   ├── ai_client.py              # Thin wrapper around the LLM (swap for AGAI later)
│   └── stage_events.py           # Lightweight progress hook for the web UI
├── web/
│   ├── app.py                    # FastAPI server: index, /runs, SSE event stream
│   ├── templates/index.html      # Single-page UI
│   └── static/                   # CSS + vanilla JS frontend
├── prompts/
│   ├── extract_course_info.yaml  # Stage 0 prompt (course-level metadata)
│   ├── extract_modules.yaml      # Stage 1 prompt
│   └── extract_items.yaml        # Stage 2 prompt
├── schemas/
│   └── models.py             # Pydantic data contracts
├── syllabi/
│   ├── bellevue_engl101.txt  # Real syllabus #1 (Bellevue College ENGL 101)
│   └── ubc_comm663.txt       # Real syllabus #2 (UBC marketing PhD course)
├── tests/
│   ├── test_prompts.py       # Verifies prompt rendering
│   └── test_assemble.py      # Verifies deterministic assembly logic
├── output/                   # Generated JSON results land here
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
cd oncourse-poc
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
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
string-matching on log lines. Any other consumer (the real onCourse app,
a CLI wrapper, a test harness) gets the same start/complete/error contract
for free. Outside any sink (CLI runs, unit tests) the emits are no-ops.

This is a single-process POC: the flow runs in a background thread inside
the same Python process as the web server. Concurrent runs are intentionally
blocked (HTTP 409); the UI is single-user.

## Run the tests (no API key required)

```bash
pytest tests/
```

These tests cover prompt rendering and the assembly logic without ever
hitting the LLM. They run in well under a second and can sit in CI.

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

**Prompts as versioned YAML.** The `version` field, `model`, `temperature`,
and `max_tokens` are co-located with the prompt text. When we move to
production we can either keep this in Git (current setup) or move it to a
prompt registry (only `flows/prompts.py` changes).

**Swap-in point for AGAI.** When the real AGAI client is available, only
`flows/ai_client.py` changes. The flow code, prompts, and schemas all
stay put.

## Known limitations of the POC

- Only handles plain text input. PDF/DOCX extraction is a separate concern
  that the real Course Analyzer would handle upstream of this pipeline.
- No structured outputs / tool use. The prompts ask for JSON and we parse
  it. Anthropic's tool use API would give stronger guarantees and is a
  natural next iteration.
- No cost or token tracking yet. For the real pipeline we'd log token
  usage from each response into Prefect task metadata.
- No evals. Once we have a few golden extractions hand-curated, we can
  run regression evals against prompt changes.
