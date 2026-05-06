"""
QC pipeline as a Prefect flow.

Mirrors the shape of flows/course_analyzer.py:
  - tasks are independently retryable
  - the flow returns a typed object
  - artifacts land on disk in qc_output/

Two entry points:
  - qc_one(extracted_path, ...): QC a single extraction JSON
  - qc_all(...): QC every extraction in output/

CLI:
  python -m qc.qc_flow                              # QC every output/*.extracted.json
  python -m qc.qc_flow output/foo.extracted.json    # QC just one
  python -m qc.qc_flow --no-judge ...               # skip the LLM judge (free, fast)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make sibling packages importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prefect import flow, task, get_run_logger  # noqa: E402
from prefect.exceptions import MissingContextError  # noqa: E402

from flows.ai_client import AIConfig, default_config  # noqa: E402
from flows.stage_events import emit_on_failure, emit_stage  # noqa: E402
from schemas.models import CourseExtraction  # noqa: E402

from qc.checks import run_all_checks  # noqa: E402
from qc.judge import judge_extraction  # noqa: E402
from qc.report import build_report, write_report  # noqa: E402
from qc.schemas import JudgeResult, QCCheckResult, QCReport  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_SYLLABI_DIR = PROJECT_ROOT / "syllabi"
DEFAULT_QC_DIR = PROJECT_ROOT / "qc_output"


def _logger():
    try:
        return get_run_logger()
    except MissingContextError:
        return logging.getLogger("qc_flow")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@task(name="load_extraction")
def load_extraction(path: Path, syllabi_dir: Path) -> tuple[CourseExtraction, str | None]:
    """Load the extraction and (best-effort) the matching syllabus from disk.
    Returns (extraction, syllabus_text_or_None). Bundled into one stage so
    the UI doesn't need a separate progress step for "find the syllabus"."""
    emit_stage("qc_load", "start")
    logger = _logger()

    extraction = CourseExtraction.model_validate_json(path.read_text())
    syllabus_path = syllabi_dir / extraction.source_filename
    if syllabus_path.exists():
        syllabus_text = syllabus_path.read_text()
    else:
        syllabus_text = None
        logger.warning(
            "Syllabus not found for %s under %s; judge will be skipped.",
            extraction.source_filename,
            syllabi_dir,
        )

    emit_stage(
        "qc_load",
        "complete",
        {
            "source_filename": extraction.source_filename,
            "syllabus_found": syllabus_text is not None,
            "modules": len(extraction.modules),
        },
    )
    return extraction, syllabus_text


@task(name="run_deterministic_checks")
def run_deterministic_checks(extraction: CourseExtraction) -> list[QCCheckResult]:
    emit_stage("qc_checks", "start")
    results = run_all_checks(extraction)
    n_fail = sum(1 for r in results if r.status == "fail")
    n_warn = sum(1 for r in results if r.status == "warn")
    n_pass = sum(1 for r in results if r.status == "pass")
    _logger().info(
        "Deterministic checks: %d total, %d pass, %d warn, %d fail",
        len(results),
        n_pass,
        n_warn,
        n_fail,
    )
    emit_stage(
        "qc_checks",
        "complete",
        {"total": len(results), "pass": n_pass, "warn": n_warn, "fail": n_fail},
    )
    return results


@task(retries=2, retry_delay_seconds=5, name="run_judge")
def run_judge(
    extraction: CourseExtraction,
    syllabus_text: str,
    ai_config: AIConfig,
) -> JudgeResult:
    emit_stage("qc_judge", "start")
    logger = _logger()
    logger.info(
        "Calling judge: backend=%s, model_override=%s",
        ai_config.backend,
        ai_config.model_override or "(backend default)",
    )
    result = judge_extraction(extraction, syllabus_text, ai_config)
    logger.info(
        "Judge: status=%s score=%s flagged=%d",
        result.status,
        result.score,
        len(result.flagged_fields),
    )
    emit_stage(
        "qc_judge",
        "complete",
        {
            "status": result.status,
            "score": result.score,
            "flagged": len(result.flagged_fields),
            "model": result.model,
        },
    )
    return result


@task(name="write_qc")
def write_qc(report: QCReport, qc_dir: Path) -> tuple[Path, Path | None]:
    emit_stage("qc_write", "start")
    qc_path, review_path = write_report(report, qc_dir)
    logger = _logger()
    logger.info("Wrote QC report: %s", qc_path)
    if review_path is not None:
        logger.info("Wrote HITL review task: %s", review_path)
    emit_stage(
        "qc_write",
        "complete",
        {
            "qc_path": str(qc_path),
            "review_path": str(review_path) if review_path else None,
            "overall_status": report.overall_status,
            "needs_human_review": report.needs_human_review,
        },
    )
    return qc_path, review_path


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


@flow(name="qc_one")
def qc_one(
    extracted_path: str,
    *,
    syllabi_dir: str | None = None,
    qc_dir: str | None = None,
    ai_config: AIConfig | None = None,
    judge_ai_config: AIConfig | None = None,
    use_judge: bool = True,
) -> QCReport:
    """QC a single extraction JSON. Returns the QCReport.

    `ai_config` is currently unused inside QC (no extraction calls happen
    here) but is accepted symmetrically with the main flow so the web
    layer can pass a single context. `judge_ai_config` configures the
    LLM-as-judge backend/model independently — running the judge on a
    different model family from inference mitigates self-preference bias.
    Defaults to `ai_config` if not provided (degraded but functional).
    """
    cfg = ai_config or default_config()
    judge_cfg = judge_ai_config or cfg
    extraction_path = Path(extracted_path)
    syllabi_path = Path(syllabi_dir) if syllabi_dir else DEFAULT_SYLLABI_DIR
    qc_path = Path(qc_dir) if qc_dir else DEFAULT_QC_DIR

    logger = _logger()
    logger.info(
        "QC starting on %s (use_judge=%s, judge_backend=%s, judge_model=%s)",
        extraction_path,
        use_judge,
        judge_cfg.backend,
        judge_cfg.model_override or "(backend default)",
    )

    with emit_on_failure("qc_load"):
        extraction, syllabus_text = load_extraction(extraction_path, syllabi_path)

    with emit_on_failure("qc_checks"):
        deterministic = run_deterministic_checks(extraction)

    judge: list[JudgeResult] = []
    if use_judge and syllabus_text is not None:
        with emit_on_failure("qc_judge"):
            judge.append(run_judge(extraction, syllabus_text, judge_cfg))

    report = build_report(
        source_filename=extraction.source_filename,
        extraction_path=extraction_path,
        deterministic=deterministic,
        judge=judge,
    )
    with emit_on_failure("qc_write"):
        write_qc(report, qc_path)

    logger.info(
        "QC done for %s: overall=%s, needs_human_review=%s",
        extraction.source_filename,
        report.overall_status,
        report.needs_human_review,
    )
    return report


@flow(name="qc_all")
def qc_all(
    *,
    output_dir: str | None = None,
    syllabi_dir: str | None = None,
    qc_dir: str | None = None,
    ai_config: AIConfig | None = None,
    judge_ai_config: AIConfig | None = None,
    use_judge: bool = True,
) -> list[QCReport]:
    """QC every `*.extracted.json` under output_dir."""
    out = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    extraction_paths = sorted(out.glob("*.extracted.json"))
    logger = _logger()
    logger.info("QC sweep: %d extraction file(s) under %s", len(extraction_paths), out)

    reports: list[QCReport] = []
    for p in extraction_paths:
        reports.append(
            qc_one(
                str(p),
                syllabi_dir=syllabi_dir,
                qc_dir=qc_dir,
                ai_config=ai_config,
                judge_ai_config=judge_ai_config,
                use_judge=use_judge,
            )
        )
    return reports


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    use_judge = True
    if "--no-judge" in args:
        use_judge = False
        args = [a for a in args if a != "--no-judge"]

    if not args:
        qc_all(use_judge=use_judge)
    else:
        for path in args:
            qc_one(path, use_judge=use_judge)
