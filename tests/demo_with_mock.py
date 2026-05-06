"""
Demo runner with a mocked LLM client. Useful for showing the pipeline shape
and output format without burning API calls.

Run: python tests/demo_with_mock.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flows.course_analyzer import course_analyzer  # noqa: E402


# Hand-crafted expected outputs that match what we'd want the real LLM to
# produce for the Bellevue syllabus.

MOCK_MODULES_RESPONSE = {
    "modules": [
        {"order_index": 1, "title": "Week 1: Getting Started", "objectives": []},
        {"order_index": 2, "title": "Week 2: Elements of Effective Writing", "objectives": []},
        {"order_index": 3, "title": "Week 3: Collaborative Work", "objectives": []},
        {"order_index": 4, "title": "Week 4: Writing About the Self - The Personal Essay", "objectives": []},
        {"order_index": 5, "title": "Week 5: Developing Effective Arguments", "objectives": []},
        {"order_index": 6, "title": "Week 6: Developing Effective Arguments", "objectives": []},
        {"order_index": 7, "title": "Week 7: Peer to Peer Editing", "objectives": []},
        {"order_index": 8, "title": "Week 8: The Expository Essay", "objectives": []},
        {"order_index": 9, "title": "Week 9: The Expository Essay", "objectives": []},
        {"order_index": 10, "title": "Week 10: Peer to Peer Editing", "objectives": []},
        {"order_index": 11, "title": "Week 11: Final Exams", "objectives": []},
    ]
}

MOCK_ITEMS_RESPONSE = {
    "items": [
        {
            "order_index": 1, "item_type": "assignment",
            "title": "Grammar Assessment", "description": None,
            "module_order_index": 1,
            "material_format": None, "citation": None,
            "assignment_format": "assessment", "points": 5, "due": "Week 1, Tuesday April 2",
        },
        {
            "order_index": 2, "item_type": "material",
            "title": "The Curious Case of Nicki Minaj", "description": "Reading to annotate",
            "module_order_index": 1,
            "material_format": "reading", "citation": "The Curious Case of Nicki Minaj",
            "assignment_format": None, "points": None, "due": None,
        },
        {
            "order_index": 3, "item_type": "assignment",
            "title": "100-word Personal Biography", "description": None,
            "module_order_index": 1,
            "material_format": None, "citation": None,
            "assignment_format": "biography", "points": 5, "due": "Friday April 5, 11:55pm",
        },
        {
            "order_index": 4, "item_type": "material",
            "title": "Topic Sentence; Paragraph Structure; Support and Analysis; Concluding Sentence",
            "description": "Reading on writing fundamentals",
            "module_order_index": 2,
            "material_format": "reading", "citation": None,
            "assignment_format": None, "points": None, "due": None,
        },
        {
            "order_index": 5, "item_type": "assignment",
            "title": "1-page Cover Letter", "description": None,
            "module_order_index": 2,
            "material_format": None, "citation": None,
            "assignment_format": "cover letter", "points": 5, "due": "Friday April 12, 11:55pm",
        },
        {
            "order_index": 6, "item_type": "assignment",
            "title": "2-page Collaborative Essay Memo (First)", "description": None,
            "module_order_index": 2,
            "material_format": None, "citation": None,
            "assignment_format": "memo", "points": 5, "due": None,
        },
        {
            "order_index": 7, "item_type": "assignment",
            "title": "Discussion Board: Collaborative Work Self-Assessment", "description": None,
            "module_order_index": 3,
            "material_format": None, "citation": None,
            "assignment_format": "discussion post", "points": None, "due": "Friday April 19, 11:55pm",
        },
        {
            "order_index": 8, "item_type": "assignment",
            "title": "Personal Essay - First Draft", "description": None,
            "module_order_index": 4,
            "material_format": None, "citation": None,
            "assignment_format": "essay", "points": None, "due": None,
        },
        {
            "order_index": 9, "item_type": "assignment",
            "title": "Personal Essay - Final Draft", "description": None,
            "module_order_index": 4,
            "material_format": None, "citation": None,
            "assignment_format": "essay", "points": 5, "due": None,
        },
        {
            "order_index": 10, "item_type": "assignment",
            "title": "Argumentative Case Study Essay - Final Draft", "description": None,
            "module_order_index": 6,
            "material_format": None, "citation": None,
            "assignment_format": "essay", "points": 5, "due": None,
        },
        {
            "order_index": 11, "item_type": "assignment",
            "title": "Expository Essay - Final Draft", "description": None,
            "module_order_index": 9,
            "material_format": None, "citation": None,
            "assignment_format": "essay", "points": 5, "due": None,
        },
        {
            "order_index": 12, "item_type": "assignment",
            "title": "2-page Final Self-Assessment Essay (Final Exam)", "description": "Reflective essay serving as final exam",
            "module_order_index": 11,
            "material_format": None, "citation": None,
            "assignment_format": "essay", "points": 5, "due": "Friday June 14",
        },
        {
            "order_index": 13, "item_type": "assignment",
            "title": "E-Copy Portfolio", "description": "Portfolio of all major assignments",
            "module_order_index": None,
            "material_format": None, "citation": None,
            "assignment_format": "portfolio", "points": 5, "due": None,
        },
    ]
}


# Sequence of mock responses to return in order
_responses = [MOCK_MODULES_RESPONSE, MOCK_ITEMS_RESPONSE]
_call_count = [0]


def fake_run_prompt(*, prompt, temperature, max_tokens, config=None):
    """Return the next pre-baked response and ignore the prompt."""
    response = _responses[_call_count[0]]
    _call_count[0] += 1
    return response


def main():
    syllabus = "syllabi/bellevue_engl101.txt"
    print(f"Running mocked pipeline on {syllabus}...")
    print("(LLM calls are stubbed with hand-crafted responses)\n")

    with patch("flows.course_analyzer.run_prompt", side_effect=fake_run_prompt):
        result = course_analyzer(syllabus)

    print("\n=== RESULT SUMMARY ===")
    print(f"Source: {result.source_filename}")
    print(f"Modules: {len(result.modules)}")
    print(f"Unassigned items: {len(result.unassigned_items)}")
    print()
    for m in result.modules:
        print(f"Module {m.order_index}: {m.title}")
        for item in m.items:
            tag = "[M]" if item.item_type == "material" else "[A]"
            pts = f" ({item.points}pt)" if item.points else ""
            print(f"  {tag} {item.title}{pts}")
    if result.unassigned_items:
        print("\nUnassigned items:")
        for item in result.unassigned_items:
            print(f"  - {item.title}")


if __name__ == "__main__":
    main()
