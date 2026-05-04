"""
Tests for the deterministic assembly task. We can test this without ever
calling the LLM by feeding it pre-built module + item lists.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flows.course_analyzer import assemble  # noqa: E402
from schemas.models import CourseInfo, CourseItem, Module  # noqa: E402


_STUB_COURSE_INFO = CourseInfo(title="Stub Course")


def _make_item(order_index: int, title: str, module_idx: int | None,
               item_type: str = "material") -> CourseItem:
    return CourseItem(
        order_index=order_index,
        item_type=item_type,
        title=title,
        module_order_index=module_idx,
        material_format="reading" if item_type == "material" else None,
        assignment_format="essay" if item_type == "assignment" else None,
    )


def test_assemble_groups_items_by_module():
    modules = [
        Module(order_index=1, title="Week 1", objectives=[]),
        Module(order_index=2, title="Week 2", objectives=[]),
    ]
    items = [
        _make_item(1, "Reading A", 1),
        _make_item(2, "Reading B", 2),
        _make_item(3, "Reading C", 1),
    ]
    # Use .fn() to bypass Prefect's task wrapping in unit tests
    result = assemble.fn("test.txt", _STUB_COURSE_INFO, modules, items)

    assert len(result.modules) == 2
    assert [i.title for i in result.modules[0].items] == ["Reading A", "Reading C"]
    assert [i.title for i in result.modules[1].items] == ["Reading B"]
    assert result.unassigned_items == []


def test_assemble_handles_unassigned_items():
    modules = [Module(order_index=1, title="Week 1", objectives=[])]
    items = [
        _make_item(1, "Course-wide final", None, item_type="assignment"),
        _make_item(2, "Week 1 reading", 1),
    ]
    result = assemble.fn("test.txt", _STUB_COURSE_INFO, modules, items)

    assert len(result.modules[0].items) == 1
    assert result.modules[0].items[0].title == "Week 1 reading"
    assert len(result.unassigned_items) == 1
    assert result.unassigned_items[0].title == "Course-wide final"


def test_assemble_handles_invalid_module_reference():
    """If the LLM hallucinates a module_order_index, treat it as unassigned."""
    modules = [Module(order_index=1, title="Week 1", objectives=[])]
    items = [_make_item(1, "Orphaned reading", 99)]  # module 99 doesn't exist

    result = assemble.fn("test.txt", _STUB_COURSE_INFO, modules, items)

    assert len(result.modules[0].items) == 0
    assert len(result.unassigned_items) == 1
    assert result.unassigned_items[0].title == "Orphaned reading"


def test_assemble_preserves_item_order_within_module():
    """Items should appear within a module in syllabus order, not random order."""
    modules = [Module(order_index=1, title="Week 1", objectives=[])]
    items = [
        _make_item(5, "Fifth item", 1),
        _make_item(1, "First item", 1),
        _make_item(3, "Third item", 1),
    ]
    result = assemble.fn("test.txt", _STUB_COURSE_INFO, modules, items)

    titles = [i.title for i in result.modules[0].items]
    assert titles == ["First item", "Third item", "Fifth item"]


def test_assemble_passes_through_course_info():
    """course_info should land on the result unchanged."""
    info = CourseInfo(
        title="Basic Composition",
        code="ENGL 101",
        level="undergraduate",
        objectives=["Write clearly", "Argue effectively"],
    )
    modules = [Module(order_index=1, title="Week 1", objectives=[])]
    result = assemble.fn("test.txt", info, modules, [])

    assert result.course_info.title == "Basic Composition"
    assert result.course_info.code == "ENGL 101"
    assert result.course_info.objectives == ["Write clearly", "Argue effectively"]


def test_assemble_preserves_module_order():
    """Modules should come out in order_index order regardless of input order."""
    modules = [
        Module(order_index=3, title="Week 3", objectives=[]),
        Module(order_index=1, title="Week 1", objectives=[]),
        Module(order_index=2, title="Week 2", objectives=[]),
    ]
    result = assemble.fn("test.txt", _STUB_COURSE_INFO, modules, [])

    assert [m.title for m in result.modules] == ["Week 1", "Week 2", "Week 3"]
