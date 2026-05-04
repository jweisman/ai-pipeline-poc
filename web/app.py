"""
Small web UI around the course-analyzer Prefect flow.

Single FastAPI process that serves a one-page frontend, accepts a syllabus
selection, runs the flow in a background thread, and streams logs + the
final result back to the browser via Server-Sent Events.

To run:
    python -m web.app
or
    uvicorn web.app:app --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Make the project root importable when running this file directly
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402

from flows.course_analyzer import course_analyzer  # noqa: E402


SYLLABI_DIR = ROOT / "syllabi"
WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(title="onCourse — Course Analyzer")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


# ---------------------------------------------------------------------------
# Pipeline stages — kept in sync with flows/course_analyzer.py
# ---------------------------------------------------------------------------

STAGES = [
    {"key": "course_info", "label": "Course info", "task": "extract_course_info"},
    {"key": "modules", "label": "Modules", "task": "extract_modules"},
    {"key": "items", "label": "Items", "task": "extract_items"},
    {"key": "assemble", "label": "Assemble", "task": "assemble"},
    {"key": "write", "label": "Write JSON", "task": "write_output"},
]


def _detect_stage(record: logging.LogRecord) -> Optional[str]:
    """
    Best-effort mapping from a log record to a pipeline stage. Prefect's task
    loggers are named like 'prefect.task_runs.extract_modules-...'; outside
    a Prefect context, our fallback logger is 'course_analyzer' and we use
    the message to disambiguate.
    """
    name = record.name.lower()
    msg = record.getMessage().lower()
    for stage in STAGES:
        if stage["task"] in name:
            return stage["key"]
    if "course-info" in msg or "extracted course info" in msg:
        return "course_info"
    if "module extraction" in msg or "extracted" in msg and "modules" in msg:
        return "modules"
    if "item extraction" in msg or "items (" in msg:
        return "items"
    if "assembled course" in msg:
        return "assemble"
    if "wrote output" in msg:
        return "write"
    return None


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    run_id: str
    syllabus: str
    status: str = "pending"  # pending | running | done | error
    events: queue.Queue = field(default_factory=queue.Queue)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


_runs: dict[str, RunState] = {}
_runs_lock = threading.Lock()


class _QueueLogHandler(logging.Handler):
    """Push every log record into a run-specific queue as a structured event."""

    def __init__(self, state: RunState):
        super().__init__()
        self.state = state
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.state.events.put(
            {
                "type": "log",
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
                "stage": _detect_stage(record),
            }
        )


def _run_flow(state: RunState, syllabus_path: Path) -> None:
    """Worker that runs the Prefect flow and publishes events to the queue."""
    handler = _QueueLogHandler(state)
    root_logger = logging.getLogger()
    prior_level = root_logger.level
    root_logger.addHandler(handler)
    if prior_level > logging.INFO or prior_level == logging.NOTSET:
        root_logger.setLevel(logging.INFO)

    try:
        state.status = "running"
        state.events.put({"type": "status", "status": "running"})

        result = course_analyzer(str(syllabus_path))
        state.result = json.loads(result.model_dump_json())
        state.status = "done"
        state.events.put({"type": "result", "data": state.result})
        state.events.put({"type": "status", "status": "done"})

    except Exception as e:
        state.error = f"{type(e).__name__}: {e}"
        state.status = "error"
        state.events.put({"type": "error", "message": state.error})
        state.events.put({"type": "status", "status": "error"})

    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(prior_level)
        state.events.put(None)  # sentinel — closes the SSE stream


def _list_syllabi() -> list[dict[str, Any]]:
    if not SYLLABI_DIR.exists():
        return []
    out = []
    for p in sorted(SYLLABI_DIR.iterdir()):
        if p.suffix.lower() == ".txt" and p.is_file():
            out.append(
                {
                    "name": p.name,
                    "size_bytes": p.stat().st_size,
                    "preview": p.read_text(errors="replace")[:160].strip(),
                }
            )
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "syllabi": _list_syllabi(),
            "stages": STAGES,
        },
    )


@app.post("/runs")
async def start_run(payload: dict):
    syllabus = payload.get("syllabus")
    if not syllabus:
        raise HTTPException(400, "Missing 'syllabus'")
    syllabus_path = SYLLABI_DIR / syllabus
    if not syllabus_path.is_file() or syllabus_path.parent != SYLLABI_DIR:
        raise HTTPException(404, f"Unknown syllabus: {syllabus}")

    with _runs_lock:
        if any(r.status == "running" for r in _runs.values()):
            raise HTTPException(409, "Another run is already in progress")
        run_id = str(uuid.uuid4())
        state = RunState(run_id=run_id, syllabus=syllabus)
        _runs[run_id] = state

    threading.Thread(
        target=_run_flow, args=(state, syllabus_path), daemon=True
    ).start()
    return {"run_id": run_id}


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request):
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(404, "Unknown run_id")

    async def gen():
        # Replay any events that arrived before the client connected.
        # (Race-y but cheap; it's a POC, single user.)
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.to_thread(state.events.get, True, 1.0)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/runs/{run_id}/result")
async def get_result(run_id: str):
    state = _runs.get(run_id)
    if state is None:
        raise HTTPException(404)
    if state.status != "done":
        raise HTTPException(409, f"Run is {state.status}")
    return state.result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=False)
