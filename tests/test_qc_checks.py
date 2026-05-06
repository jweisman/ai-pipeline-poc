"""
Tests for the deterministic QC checks. None of these call the LLM; they
build CourseExtraction objects in-memory, mutate them, and assert the
right check fires with the right severity.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas.models import (  # noqa: E402
    CourseExtraction,
    CourseInfo,
    CourseItem,
    ModuleWithItems,
)

from qc.checks import run_all_checks  # noqa: E402
from qc.report import build_report  # noqa: E402


def _material(order_index: int, title: str) -> CourseItem:
    return CourseItem(
        order_index=order_index,
        item_type="material",
        title=title,
        material_format="reading",
    )


def _assignment(order_index: int, title: str, points: float | None = None) -> CourseItem:
    return CourseItem(
        order_index=order_index,
        item_type="assignment",
        title=title,
        assignment_format="essay",
        points=points,
    )


def _good_extraction() -> CourseExtraction:
    return CourseExtraction(
        source_filename="stub.txt",
        course_info=CourseInfo(title="A Course"),
        modules=[
            ModuleWithItems(
                order_index=1,
                title="Week 1",
                objectives=[],
                items=[_material(1, "Reading A"), _assignment(2, "Essay 1")],
            ),
            ModuleWithItems(
                order_index=2,
                title="Week 2",
                objectives=[],
                items=[_material(3, "Reading B")],
            ),
        ],
    )


def _by_name(results, name):
    return next(r for r in results if r.name == name)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_clean_extraction_passes_all_checks():
    results = run_all_checks(_good_extraction())
    statuses = {r.name: r.status for r in results}
    assert all(s == "pass" for s in statuses.values()), statuses


def test_build_report_rolls_up_to_pass():
    extraction = _good_extraction()
    report = build_report(
        source_filename=extraction.source_filename,
        extraction_path=Path("output/stub.extracted.json"),
        deterministic=run_all_checks(extraction),
        judge=[],
    )
    assert report.overall_status == "pass"
    assert report.needs_human_review is False
    assert report.fields_flagged == []


# ---------------------------------------------------------------------------
# Module-level checks
# ---------------------------------------------------------------------------


def test_no_modules_fails_has_modules():
    extraction = _good_extraction()
    extraction.modules = []
    result = _by_name(run_all_checks(extraction), "has_modules")
    assert result.status == "fail"
    assert result.severity == "error"
    assert "modules" in result.flagged_fields


def test_empty_module_warns():
    extraction = _good_extraction()
    extraction.modules[1].items = []
    result = _by_name(run_all_checks(extraction), "no_empty_modules")
    assert result.status == "warn"
    assert "modules[2].items" in result.flagged_fields


def test_module_order_gap_warns():
    extraction = _good_extraction()
    extraction.modules[1].order_index = 5  # 1, 5 — not contiguous
    result = _by_name(
        run_all_checks(extraction), "module_order_unique_and_contiguous"
    )
    assert result.status == "warn"


def test_duplicate_module_order_fails():
    extraction = _good_extraction()
    extraction.modules[1].order_index = 1  # duplicate
    result = _by_name(
        run_all_checks(extraction), "module_order_unique_and_contiguous"
    )
    assert result.status == "fail"
    assert result.severity == "error"


# ---------------------------------------------------------------------------
# Item-level checks
# ---------------------------------------------------------------------------


def test_material_missing_format_fails():
    extraction = _good_extraction()
    extraction.modules[0].items[0].material_format = None
    result = _by_name(run_all_checks(extraction), "item_type_field_consistency")
    assert result.status == "fail"
    assert any("material_format" in f for f in result.flagged_fields)


def test_assignment_carrying_citation_fails():
    extraction = _good_extraction()
    bad = extraction.modules[0].items[1]  # the essay
    bad.citation = "should not be here"
    result = _by_name(run_all_checks(extraction), "item_type_field_consistency")
    assert result.status == "fail"
    assert any("citation" in f for f in result.flagged_fields)


def test_assignment_missing_format_warns():
    extraction = _good_extraction()
    extraction.modules[0].items[1].assignment_format = None
    result = _by_name(run_all_checks(extraction), "item_type_field_consistency")
    assert result.status == "warn"


def test_duplicate_item_titles_within_module_warns():
    extraction = _good_extraction()
    extraction.modules[0].items.append(_material(99, "Reading A"))  # dup
    result = _by_name(run_all_checks(extraction), "no_duplicate_titles_within_module")
    assert result.status == "warn"
    assert len(result.flagged_fields) >= 2


# ---------------------------------------------------------------------------
# Course-info checks
# ---------------------------------------------------------------------------


def test_blank_course_title_fails():
    extraction = _good_extraction()
    extraction.course_info.title = "   "
    result = _by_name(run_all_checks(extraction), "course_info_minimal")
    assert result.status == "fail"
    assert "course_info.title" in result.flagged_fields


# ---------------------------------------------------------------------------
# Rollup
# ---------------------------------------------------------------------------


def test_build_report_marks_review_when_warn():
    extraction = _good_extraction()
    extraction.modules[1].items = []  # warn-level
    report = build_report(
        source_filename=extraction.source_filename,
        extraction_path=Path("output/stub.extracted.json"),
        deterministic=run_all_checks(extraction),
        judge=[],
    )
    assert report.overall_status == "warn"
    assert report.needs_human_review is True
    assert "modules[2].items" in report.fields_flagged


def test_build_report_marks_review_when_fail():
    extraction = _good_extraction()
    extraction.modules = []
    report = build_report(
        source_filename=extraction.source_filename,
        extraction_path=Path("output/stub.extracted.json"),
        deterministic=run_all_checks(extraction),
        judge=[],
    )
    assert report.overall_status == "fail"
    assert report.needs_human_review is True
