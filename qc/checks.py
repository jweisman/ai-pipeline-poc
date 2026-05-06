"""
Deterministic QC checks for CourseExtraction.

Each check is a pure function: takes a CourseExtraction, returns a
QCCheckResult. No I/O, no LLM calls. Cheap enough to run on every
extraction and easy to test.

Severity convention:
  - error: structural problems that should block trust (missing modules,
    item_type/material_format mismatch).
  - warn:  suspicious but not necessarily wrong (empty module, duplicate
    titles, missing assignment_format).
  - info:  observational only (unassigned-item count).

Add new checks by writing another `_check_*` function and appending it
to ALL_CHECKS at the bottom.
"""

from __future__ import annotations

from typing import Callable

from schemas.models import CourseExtraction, CourseItem

from qc.schemas import QCCheckResult


CheckFn = Callable[[CourseExtraction], QCCheckResult]


# ---------------------------------------------------------------------------
# Module-level checks
# ---------------------------------------------------------------------------


def _check_has_modules(extraction: CourseExtraction) -> QCCheckResult:
    n = len(extraction.modules)
    if n == 0:
        return QCCheckResult(
            name="has_modules",
            status="fail",
            severity="error",
            message="Course has no modules.",
            flagged_fields=["modules"],
        )
    return QCCheckResult(
        name="has_modules",
        status="pass",
        severity="error",
        message=f"Course has {n} module(s).",
    )


def _check_modules_have_titles(extraction: CourseExtraction) -> QCCheckResult:
    bad: list[str] = []
    for m in extraction.modules:
        if not m.title or not m.title.strip():
            bad.append(f"modules[{m.order_index}].title")
    if bad:
        return QCCheckResult(
            name="modules_have_titles",
            status="fail",
            severity="error",
            message=f"{len(bad)} module(s) have empty titles.",
            details={"empty_title_module_indices": [int(p.split("[")[1].split("]")[0]) for p in bad]},
            flagged_fields=bad,
        )
    return QCCheckResult(
        name="modules_have_titles",
        status="pass",
        severity="error",
        message="All modules have titles.",
    )


def _check_module_order_unique_and_contiguous(extraction: CourseExtraction) -> QCCheckResult:
    indices = [m.order_index for m in extraction.modules]
    if not indices:
        return QCCheckResult(
            name="module_order_unique_and_contiguous",
            status="pass",
            severity="warn",
            message="No modules to check ordering on.",
        )
    if len(set(indices)) != len(indices):
        dupes = sorted({i for i in indices if indices.count(i) > 1})
        return QCCheckResult(
            name="module_order_unique_and_contiguous",
            status="fail",
            severity="error",
            message=f"Duplicate module order_index values: {dupes}.",
            details={"duplicates": dupes},
            flagged_fields=[f"modules[{i}].order_index" for i in dupes],
        )
    expected = list(range(1, len(indices) + 1))
    if sorted(indices) != expected:
        return QCCheckResult(
            name="module_order_unique_and_contiguous",
            status="warn",
            severity="warn",
            message=(
                f"Module order_index values are not a contiguous 1..N sequence. "
                f"Got {sorted(indices)}, expected {expected}."
            ),
            details={"actual": sorted(indices), "expected": expected},
            flagged_fields=["modules[*].order_index"],
        )
    return QCCheckResult(
        name="module_order_unique_and_contiguous",
        status="pass",
        severity="warn",
        message=f"Module order_index is a contiguous 1..{len(indices)} sequence.",
    )


def _check_no_empty_modules(extraction: CourseExtraction) -> QCCheckResult:
    empty = [m.order_index for m in extraction.modules if not m.items]
    if empty:
        return QCCheckResult(
            name="no_empty_modules",
            status="warn",
            severity="warn",
            message=f"{len(empty)} module(s) have no items: {empty}.",
            details={"empty_module_indices": empty},
            flagged_fields=[f"modules[{i}].items" for i in empty],
        )
    return QCCheckResult(
        name="no_empty_modules",
        status="pass",
        severity="warn",
        message="All modules have at least one item.",
    )


# ---------------------------------------------------------------------------
# Item-level checks
# ---------------------------------------------------------------------------


def _all_items(extraction: CourseExtraction) -> list[tuple[str, CourseItem]]:
    """Yield (path-prefix, item) pairs for every item in the extraction.

    Path-prefix is dotted, e.g. 'modules[2].items[0]' or 'unassigned_items[3]'.
    """
    out: list[tuple[str, CourseItem]] = []
    for m in extraction.modules:
        for i, item in enumerate(m.items):
            out.append((f"modules[{m.order_index}].items[{i}]", item))
    for i, item in enumerate(extraction.unassigned_items):
        out.append((f"unassigned_items[{i}]", item))
    return out


def _check_items_have_titles(extraction: CourseExtraction) -> QCCheckResult:
    bad = [
        f"{path}.title"
        for path, item in _all_items(extraction)
        if not item.title or not item.title.strip()
    ]
    if bad:
        return QCCheckResult(
            name="items_have_titles",
            status="fail",
            severity="error",
            message=f"{len(bad)} item(s) have empty titles.",
            flagged_fields=bad,
        )
    return QCCheckResult(
        name="items_have_titles",
        status="pass",
        severity="error",
        message="All items have titles.",
    )


def _check_item_type_field_consistency(extraction: CourseExtraction) -> QCCheckResult:
    """Materials must declare a material_format and not carry assignment fields,
    and vice versa. The schema is permissive (everything Optional) so we enforce
    the cross-field invariant here."""
    errors: list[str] = []
    warnings: list[str] = []
    for path, item in _all_items(extraction):
        if item.item_type == "material":
            if item.material_format is None:
                errors.append(f"{path}.material_format")
            if item.assignment_format is not None:
                errors.append(f"{path}.assignment_format")
            if item.points is not None:
                errors.append(f"{path}.points")
        elif item.item_type == "assignment":
            if item.material_format is not None:
                errors.append(f"{path}.material_format")
            if item.citation is not None:
                errors.append(f"{path}.citation")
            if item.assignment_format is None:
                # Common but not strictly invalid — warn rather than fail.
                warnings.append(f"{path}.assignment_format")
    if errors:
        return QCCheckResult(
            name="item_type_field_consistency",
            status="fail",
            severity="error",
            message=(
                f"{len(errors)} field(s) violate item_type rules "
                f"(materials need material_format and no assignment fields; "
                f"assignments must not carry citation/material_format)."
            ),
            details={"violations": errors, "warnings": warnings},
            flagged_fields=errors + warnings,
        )
    if warnings:
        return QCCheckResult(
            name="item_type_field_consistency",
            status="warn",
            severity="warn",
            message=f"{len(warnings)} assignment(s) missing assignment_format.",
            details={"warnings": warnings},
            flagged_fields=warnings,
        )
    return QCCheckResult(
        name="item_type_field_consistency",
        status="pass",
        severity="error",
        message="All items have type-consistent fields.",
    )


def _check_no_duplicate_titles_within_module(extraction: CourseExtraction) -> QCCheckResult:
    """Two items with identical titles inside the same module is almost
    always an extraction artifact (the LLM repeated itself). Warn, don't fail."""
    flagged: list[str] = []
    dup_count = 0
    for m in extraction.modules:
        seen: dict[str, list[int]] = {}
        for i, item in enumerate(m.items):
            seen.setdefault(item.title.strip().lower(), []).append(i)
        for title, idxs in seen.items():
            if len(idxs) > 1:
                dup_count += 1
                flagged.extend(f"modules[{m.order_index}].items[{i}].title" for i in idxs)
    if flagged:
        return QCCheckResult(
            name="no_duplicate_titles_within_module",
            status="warn",
            severity="warn",
            message=f"{dup_count} duplicate item title group(s) within modules.",
            flagged_fields=flagged,
        )
    return QCCheckResult(
        name="no_duplicate_titles_within_module",
        status="pass",
        severity="warn",
        message="No duplicate item titles within any module.",
    )


def _check_unassigned_count(extraction: CourseExtraction) -> QCCheckResult:
    """Informational: surface unassigned-item count without changing status.
    Lots of unassigned items isn't necessarily wrong — final exams,
    semester-long projects — but it's worth a glance."""
    n = len(extraction.unassigned_items)
    return QCCheckResult(
        name="unassigned_item_count",
        status="pass" if n <= 3 else "warn",
        severity="info",
        message=f"{n} unassigned item(s).",
        details={"count": n},
        flagged_fields=[f"unassigned_items[{i}]" for i in range(n)] if n > 3 else [],
    )


# ---------------------------------------------------------------------------
# Course-info-level checks
# ---------------------------------------------------------------------------


def _check_course_info_minimal(extraction: CourseExtraction) -> QCCheckResult:
    """course_info.title is required by the schema; this catches empty/whitespace-only
    titles that pass Pydantic's `str` type but are clearly broken."""
    title = (extraction.course_info.title or "").strip()
    if not title:
        return QCCheckResult(
            name="course_info_minimal",
            status="fail",
            severity="error",
            message="course_info.title is empty.",
            flagged_fields=["course_info.title"],
        )
    return QCCheckResult(
        name="course_info_minimal",
        status="pass",
        severity="error",
        message=f"course_info.title is set ({title!r}).",
    )


# ---------------------------------------------------------------------------
# Registry + driver
# ---------------------------------------------------------------------------


ALL_CHECKS: list[CheckFn] = [
    _check_course_info_minimal,
    _check_has_modules,
    _check_modules_have_titles,
    _check_module_order_unique_and_contiguous,
    _check_no_empty_modules,
    _check_items_have_titles,
    _check_item_type_field_consistency,
    _check_no_duplicate_titles_within_module,
    _check_unassigned_count,
]


def run_all_checks(extraction: CourseExtraction) -> list[QCCheckResult]:
    """Run every registered check against an extraction and return all results."""
    return [check(extraction) for check in ALL_CHECKS]
