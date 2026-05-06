"""
Pydantic models for the QC pipeline.

QC has two complementary signals:
  - deterministic checks (qc/checks.py): pure functions over a
    CourseExtraction, fast and free, run every time.
  - LLM-as-judge (qc/judge.py): a single LLM call that compares the
    extraction against the source syllabus for fidelity.

Both kinds of result roll up into a QCReport with an overall status. If
overall is "fail" — or if anything is otherwise judged review-worthy — a
companion HITL review-task JSON is written so a human can adjudicate.
The state machine for that review task is intentionally a placeholder
(`status="pending_review"`, decision=None) — the queue/UI is a later phase.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


Status = Literal["pass", "warn", "fail"]
Severity = Literal["info", "warn", "error"]


class QCCheckResult(BaseModel):
    """Outcome of a single deterministic check."""

    name: str = Field(..., description="Stable identifier for the check, e.g. 'modules_have_titles'.")
    status: Status
    severity: Severity = Field(
        ...,
        description=(
            "How loud the failure is. 'info' never escalates overall status; "
            "'warn' rolls the report up to at most 'warn'; 'error' rolls "
            "the report up to 'fail'."
        ),
    )
    message: str = Field(..., description="Human-readable description of what was checked and what happened.")
    details: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional structured payload — e.g. offending indices, field names, counts.",
    )
    flagged_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Dotted paths to fields implicated by this check, e.g. "
            "'modules[2].items[0].material_format'. Used to populate the "
            "HITL review payload."
        ),
    )


class JudgeResult(BaseModel):
    """Outcome of a single LLM-as-judge pass."""

    name: str = Field(..., description="Stable identifier for the judge, e.g. 'judge_extraction_fidelity'.")
    status: Status
    score: Optional[float] = Field(
        default=None,
        description="Optional 0..1 score returned by the judge. Higher = better.",
    )
    rationale: str = Field(..., description="Free-text explanation from the judge.")
    flagged_fields: list[str] = Field(
        default_factory=list,
        description="Dotted paths the judge thinks are wrong, missing, or hallucinated.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Model the judge ran on (resolved at call time). Useful in the report for traceability.",
    )


class QCReport(BaseModel):
    """The full QC result for one CourseExtraction."""

    source_filename: str = Field(..., description="The syllabus filename, copied from the extraction.")
    extraction_path: str = Field(..., description="Path to the extraction JSON that was checked.")
    overall_status: Status
    deterministic: list[QCCheckResult] = Field(default_factory=list)
    judge: list[JudgeResult] = Field(default_factory=list)
    needs_human_review: bool = Field(
        default=False,
        description="True if a human should look at this extraction before it's trusted.",
    )
    fields_flagged: list[str] = Field(
        default_factory=list,
        description="Union of flagged_fields from all checks and judges, deduplicated.",
    )
