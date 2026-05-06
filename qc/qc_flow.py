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
def load_extraction(path: Path) -> CourseExtraction:
    return CourseExtraction.model_validate_json(path.read_text())


@task(name="load_syllabus")
def load_syllabus(source_filename: str, syllabi_dir: Path) -> str | None:
    """Look up the original syllabus by the extraction's source_filename.

    Returns None if the syllabus can't be found — the judge step will be
    skipped rather than crashing the run, since QC over disk artifacts
    has no way to recover the source if it's been moved."""
    candidate = syllabi_dir / source_filename
    if candidate.exists():
        return candidate.read_text()
    _logger().warning(
        "Syllabus not found for %s under %s; skipping judge.",
        source_filename,
        syllabi_dir,
    )
    return None


@task(name="run_deterministic_checks")
def run_deterministic_checks(extraction: CourseExtraction) -> list[QCCheckResult]:
    results = run_all_checks(extraction)
    logger = _logger()
    n_fail = sum(1 for r in results if r.status == "fail")
    n_warn = sum(1 for r in results if r.status == "warn")
    logger.info(
        "Deterministic checks: %d total, %d fail, %d warn",
        len(results),
        n_fail,
        n_warn,
    )
    return results


@task(retries=2, retry_delay_seconds=5, name="run_judge")
def run_judge(
    extraction: CourseExtraction,
    syllabus_text: str,
    ai_config: AIConfig,
) -> JudgeResult:
    logger = _logger()
    logger.info(
        "Calling judge: backend=%s, model_override=%s",
        ai_config.backend,
        ai_config.model_override or "(prompt default)",
    )
    result = judge_extraction(extraction, syllabus_text, ai_config)
    logger.info(
        "Judge: status=%s score=%s flagged=%d",
        result.status,
        result.score,
        len(result.flagged_fields),
    )
    return result


@task(name="write_qc")
def write_qc(report: QCReport, qc_dir: Path) -> tuple[Path, Path | None]:
    qc_path, review_path = write_report(report, qc_dir)
    logger = _logger()
    logger.info("Wrote QC report: %s", qc_path)
    if review_path is not None:
        logger.info("Wrote HITL review task: %s", review_path)
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
    use_judge: bool = True,
) -> QCReport:
    """QC a single extraction JSON. Returns the QCReport."""
    cfg = ai_config or default_config()
    extraction_path = Path(extracted_path)
    syllabi_path = Path(syllabi_dir) if syllabi_dir else DEFAULT_SYLLABI_DIR
    qc_path = Path(qc_dir) if qc_dir else DEFAULT_QC_DIR

    logger = _logger()
    logger.info("QC starting on %s (use_judge=%s)", extraction_path, use_judge)

    extraction = load_extraction(extraction_path)
    deterministic = run_deterministic_checks(extraction)

    judge: list[JudgeResult] = []
    if use_judge:
        syllabus_text = load_syllabus(extraction.source_filename, syllabi_path)
        if syllabus_text is not None:
            judge.append(run_judge(extraction, syllabus_text, cfg))

    report = build_report(
        source_filename=extraction.source_filename,
        extraction_path=extraction_path,
        deterministic=deterministic,
        judge=judge,
    )
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
