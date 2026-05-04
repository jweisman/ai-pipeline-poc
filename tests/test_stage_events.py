"""
Tests for the stage-event sink. No LLM, no Prefect, just the ContextVar-based
plumbing that the web UI relies on for live progress updates.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from flows.stage_events import emit_on_failure, emit_stage, stage_sink  # noqa: E402


def test_emit_is_noop_without_sink():
    # Should not raise even when nothing is listening.
    emit_stage("anything", "start")
    emit_stage("anything", "complete", {"k": 1})


def test_sink_captures_events_only_within_context():
    captured = []

    def cb(stage, phase, payload):
        captured.append((stage, phase, payload))

    emit_stage("before", "start")  # outside sink → ignored

    with stage_sink(cb):
        emit_stage("course_info", "start")
        emit_stage("course_info", "complete", {"objectives": 3})

    emit_stage("after", "start")  # outside sink again → ignored

    assert captured == [
        ("course_info", "start", None),
        ("course_info", "complete", {"objectives": 3}),
    ]


def test_sink_swallows_callback_errors():
    """A buggy sink should never break the flow."""
    def bad(stage, phase, payload):
        raise RuntimeError("boom")

    with stage_sink(bad):
        emit_stage("modules", "start")  # must not raise


def test_emit_on_failure_emits_error_and_reraises():
    captured = []

    def cb(stage, phase, payload):
        captured.append((stage, phase, payload))

    with stage_sink(cb):
        with pytest.raises(ValueError, match="boom"):
            with emit_on_failure("items"):
                raise ValueError("boom")

    assert captured == [("items", "error", {"error": "boom", "type": "ValueError"})]


def test_emit_on_failure_silent_on_success():
    captured = []

    def cb(stage, phase, payload):
        captured.append((stage, phase, payload))

    with stage_sink(cb):
        with emit_on_failure("items"):
            pass  # no exception → no error event

    assert captured == []
