"""
Aggregate QC results into a QCReport, decide overall status, and write
artifacts to qc_output/.

Status rollup rules:
  - any check or judge returning "fail" → overall "fail"
  - else any "warn" with severity in {warn, error} → overall "warn"
  - else "pass"

needs_human_review fires whenever overall is not "pass". When it fires,
we also write a sibling `<stem>.review.json` — a stub HITL review-task
record that a future review queue can pick up. The state machine on
that record (assigned_to / decision / notes / decided_at) is left as
placeholders; this phase only writes the task, it doesn't process one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from qc.schemas import JudgeResult, QCCheckResult, QCReport, Status


def _rollup_status(
    deterministic: list[QCCheckResult], judge: list[JudgeResult]
) -> Status:
    has_fail = any(c.status == "fail" for c in deterministic) or any(
        j.status == "fail" for j in judge
    )
    if has_fail:
        return "fail"
    has_warn = any(
        c.status == "warn" and c.severity in ("warn", "error") for c in deterministic
    ) or any(j.status == "warn" for j in judge)
    if has_warn:
        return "warn"
    return "pass"


def _collect_flagged_fields(
    deterministic: list[QCCheckResult], judge: list[JudgeResult]
) -> list[str]:
    seen: dict[str, None] = {}  # preserve insertion order, dedupe
    for c in deterministic:
        if c.status == "pass":
            continue
        for f in c.flagged_fields:
            seen.setdefault(f, None)
    for j in judge:
        if j.status == "pass":
            continue
        for f in j.flagged_fields:
            seen.setdefault(f, None)
    return list(seen.keys())


def build_report(
    *,
    source_filename: str,
    extraction_path: Path,
    deterministic: list[QCCheckResult],
    judge: list[JudgeResult],
) -> QCReport:
    overall = _rollup_status(deterministic, judge)
    return QCReport(
        source_filename=source_filename,
        extraction_path=str(extraction_path),
        overall_status=overall,
        deterministic=deterministic,
        judge=judge,
        needs_human_review=overall != "pass",
        fields_flagged=_collect_flagged_fields(deterministic, judge),
    )


def _review_task_payload(report: QCReport, qc_path: Path) -> dict:
    """Stub HITL record. Real review systems will replace this writer with
    one that posts to a queue / database; the JSON shape is the contract."""
    n_fail_checks = sum(1 for c in report.deterministic if c.status == "fail")
    n_warn_checks = sum(1 for c in report.deterministic if c.status == "warn")
    judge_statuses = [j.status for j in report.judge]
    return {
        "source_filename": report.source_filename,
        "extraction_path": report.extraction_path,
        "qc_report_path": str(qc_path),
        "overall_status": report.overall_status,
        "summary": (
            f"deterministic: {n_fail_checks} fail / {n_warn_checks} warn; "
            f"judge: {judge_statuses or 'none'}"
        ),
        "flagged_fields": report.fields_flagged,
        # Placeholder review-task state — a real reviewer/UI fills these in.
        "status": "pending_review",
        "assigned_to": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": None,
        "decision": None,
        "notes": None,
    }


def write_report(report: QCReport, qc_dir: Path) -> tuple[Path, Path | None]:
    """Write the report to `qc_dir/<stem>.qc.json`. If `needs_human_review`,
    also write `qc_dir/<stem>.review.json` with the HITL stub. Returns the
    paths written (review path is None when no review was needed)."""
    qc_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(report.source_filename).stem
    qc_path = qc_dir / f"{stem}.qc.json"
    qc_path.write_text(report.model_dump_json(indent=2))

    review_path: Path | None = None
    if report.needs_human_review:
        review_path = qc_dir / f"{stem}.review.json"
        review_path.write_text(
            json.dumps(_review_task_payload(report, qc_path), indent=2)
        )

    return qc_path, review_path
