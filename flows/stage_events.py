"""
Lightweight stage-event mechanism for the course analyzer flow.

Each task calls ``emit_stage(stage, phase[, payload])`` at start and
completion. A caller (the web UI) installs a sink via ``stage_sink(...)``
before running the flow. With no sink installed (CLI runs, unit tests),
emits are no-ops, so this adds zero overhead off the hot path.

A ``ContextVar`` is used rather than a thread-local so the sink propagates
correctly through Prefect's task scheduling under both sync and async
execution.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional

# (stage_key, phase, payload). phase is "start" or "complete".
StageCallback = Callable[[str, str, Optional[dict[str, Any]]], None]

_sink: ContextVar[Optional[StageCallback]] = ContextVar(
    "stage_sink", default=None
)


def emit_stage(
    stage: str,
    phase: str,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Send a stage transition event to the active sink, if any."""
    cb = _sink.get()
    if cb is None:
        return
    try:
        cb(stage, phase, payload)
    except Exception:
        # Observability must never break the flow.
        pass


@contextmanager
def stage_sink(callback: StageCallback) -> Iterator[None]:
    """Install a stage callback for the duration of the with-block."""
    token = _sink.set(callback)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def emit_on_failure(stage: str) -> Iterator[None]:
    """
    Wrap a task call in the flow so that if it raises (after any orchestrator
    retries are exhausted), a single ``error`` event is emitted before the
    exception propagates. Use at the flow level, not inside the task body —
    by the time an exception escapes the task call, retries are done.

    Example:

        with emit_on_failure("modules"):
            modules = extract_modules(syllabus_text)
    """
    try:
        yield
    except BaseException as e:
        emit_stage(
            stage,
            "error",
            {"error": str(e), "type": type(e).__name__},
        )
        raise
