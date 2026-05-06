"""
Tests for prompt rendering. These don't call the LLM — they just verify the
template machinery works and that the rendered prompts contain the right
variables in the right places. Cheap, fast, runs in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make project root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flows.prompts import render_prompt  # noqa: E402


def test_extract_modules_prompt_includes_syllabus_text():
    syllabus = "WEEK 1: Intro\nWEEK 2: Foundations"
    rendered, config = render_prompt("extract_modules", syllabus_text=syllabus)

    assert "WEEK 1: Intro" in rendered
    assert "WEEK 2: Foundations" in rendered
    assert config.temperature == 0.0


def test_extract_modules_prompt_has_required_instructions():
    """Sanity-check: critical instructions survive into the rendered prompt."""
    rendered, _ = render_prompt("extract_modules", syllabus_text="x")

    # Order preservation rule
    assert "order_index" in rendered
    # JSON-only output rule
    assert "valid JSON" in rendered
    # Don't-invent rule
    assert "Do NOT invent" in rendered or "do not invent" in rendered.lower()


def test_extract_items_prompt_renders_modules_json():
    modules_json = json.dumps(
        [
            {"order_index": 1, "title": "Week 1: Intro"},
            {"order_index": 2, "title": "Week 2: Foundations"},
        ],
        indent=2,
    )
    rendered, _ = render_prompt(
        "extract_items",
        syllabus_text="some syllabus body",
        modules_json=modules_json,
    )

    assert "Week 1: Intro" in rendered
    assert "Week 2: Foundations" in rendered
    assert "some syllabus body" in rendered


def test_extract_items_prompt_distinguishes_materials_and_assignments():
    rendered, _ = render_prompt(
        "extract_items", syllabus_text="x", modules_json="[]"
    )
    # The prompt should clearly label what's a material vs assignment
    assert "MATERIAL" in rendered
    assert "ASSIGNMENT" in rendered
