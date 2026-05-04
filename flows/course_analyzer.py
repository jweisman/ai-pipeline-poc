"""
Course Analyzer — POC pipeline.

Three tasks chained as a Prefect flow:

  1. extract_modules: read the syllabus, ask the LLM for the module structure
  2. extract_items:   ask the LLM for materials + assignments, associated to
                      the modules from step 1
  3. assemble:        purely deterministic Python — stitch items into the
                      modules they belong to, in order

The flow returns a CourseExtraction (Pydantic model). It also writes the
result as JSON to the output/ directory so it's easy to inspect.

To run:
  export ANTHROPIC_API_KEY=...
  python -m flows.course_analyzer syllabi/bellevue_engl101.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `schemas` importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging  # noqa: E402

from prefect import flow, task, get_run_logger  # noqa: E402
from prefect.exceptions import MissingContextError  # noqa: E402

from flows.ai_client import run_prompt  # noqa: E402
from flows.prompts import render_prompt  # noqa: E402
from schemas.models import (  # noqa: E402
    CourseExtraction,
    CourseInfo,
    CourseItem,
    ItemExtraction,
    Module,
    ModuleExtraction,
    ModuleWithItems,
)


def _logger():
    """Get the Prefect run logger if we're in a flow/task context, else a
    plain logger. Lets the same task functions run under unit tests without
    needing a Prefect context."""
    try:
        return get_run_logger()
    except MissingContextError:
        return logging.getLogger("course_analyzer")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@task(retries=2, retry_delay_seconds=5, name="extract_course_info")
def extract_course_info(syllabus_text: str) -> CourseInfo:
    """
    Stage 0. Pull course-level metadata (title, code, department, level,
    instructors, description, course-level objectives) from the syllabus.
    """
    logger = _logger()

    rendered, config = render_prompt(
        "extract_course_info", syllabus_text=syllabus_text
    )
    logger.info(
        "Calling LLM for course-info extraction: model=%s, prompt_chars=%d",
        config.model,
        len(rendered),
    )

    raw = run_prompt(
        prompt=rendered,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    parsed = CourseInfo.model_validate(raw)
    logger.info(
        "Extracted course info: %r (%s) — %d objectives, %d instructors",
        parsed.title,
        parsed.code or "no code",
        len(parsed.objectives),
        len(parsed.instructors),
    )
    return parsed


@task(retries=2, retry_delay_seconds=5, name="extract_modules")
def extract_modules(syllabus_text: str) -> list[Module]:
    """
    Stage 1. Identify modules in order, capturing title + any explicit
    module-level objectives.
    """
    logger = _logger()

    rendered, config = render_prompt(
        "extract_modules", syllabus_text=syllabus_text
    )
    logger.info(
        "Calling LLM for module extraction: model=%s, prompt_chars=%d",
        config.model,
        len(rendered),
    )

    raw = run_prompt(
        prompt=rendered,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    # Validate against schema. If the model returned malformed structure,
    # this raises and the task retries (or eventually fails the run).
    parsed = ModuleExtraction.model_validate(raw)
    logger.info("Extracted %d modules", len(parsed.modules))
    for m in parsed.modules:
        logger.info("  Module %d: %s", m.order_index, m.title)
    return parsed.modules


@task(retries=2, retry_delay_seconds=5, name="extract_items")
def extract_items(
    syllabus_text: str, modules: list[Module]
) -> list[CourseItem]:
    """
    Stage 2. Identify all materials and assignments, associating each with
    the module from stage 1 that it belongs to.
    """
    logger = _logger()

    # Pass the module list as compact JSON the prompt can reference
    modules_json = json.dumps(
        [{"order_index": m.order_index, "title": m.title} for m in modules],
        indent=2,
    )

    rendered, config = render_prompt(
        "extract_items",
        syllabus_text=syllabus_text,
        modules_json=modules_json,
    )
    logger.info(
        "Calling LLM for item extraction: model=%s, prompt_chars=%d",
        config.model,
        len(rendered),
    )

    raw = run_prompt(
        prompt=rendered,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    parsed = ItemExtraction.model_validate(raw)
    n_materials = sum(1 for i in parsed.items if i.item_type == "material")
    n_assignments = sum(1 for i in parsed.items if i.item_type == "assignment")
    logger.info(
        "Extracted %d items (%d materials, %d assignments)",
        len(parsed.items),
        n_materials,
        n_assignments,
    )
    return parsed.items


@task(name="assemble")
def assemble(
    source_filename: str,
    course_info: CourseInfo,
    modules: list[Module],
    items: list[CourseItem],
) -> CourseExtraction:
    """
    Stage 3. Pure-Python assembly. No LLM call here — this is deterministic
    stitching.

    For each module, collect its items in syllabus order. Items that don't
    belong to any module are surfaced under unassigned_items rather than
    silently dropped.
    """
    logger = _logger()

    # Sort modules by their order so output is stable
    modules_sorted = sorted(modules, key=lambda m: m.order_index)
    valid_module_ids = {m.order_index for m in modules_sorted}

    # Group items by module. Sort within each group by item order_index.
    items_by_module: dict[int, list[CourseItem]] = {
        m.order_index: [] for m in modules_sorted
    }
    unassigned: list[CourseItem] = []

    for item in sorted(items, key=lambda i: i.order_index):
        if item.module_order_index is None:
            unassigned.append(item)
        elif item.module_order_index in valid_module_ids:
            items_by_module[item.module_order_index].append(item)
        else:
            # The LLM referenced a module that doesn't exist. Treat as
            # unassigned and log a warning rather than crash.
            logger.warning(
                "Item %r references unknown module_order_index=%s; treating as unassigned",
                item.title,
                item.module_order_index,
            )
            unassigned.append(item)

    modules_with_items = [
        ModuleWithItems(
            order_index=m.order_index,
            title=m.title,
            objectives=m.objectives,
            items=items_by_module[m.order_index],
        )
        for m in modules_sorted
    ]

    result = CourseExtraction(
        source_filename=source_filename,
        course_info=course_info,
        modules=modules_with_items,
        unassigned_items=unassigned,
    )

    logger.info(
        "Assembled course: %d modules, %d unassigned items",
        len(result.modules),
        len(result.unassigned_items),
    )
    return result


@task(name="write_output")
def write_output(result: CourseExtraction, out_dir: Path) -> Path:
    """Write the result to disk as JSON. Returns the path written."""
    logger = _logger()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(result.source_filename).stem
    out_path = out_dir / f"{stem}.extracted.json"
    out_path.write_text(result.model_dump_json(indent=2))
    logger.info("Wrote output: %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


@flow(name="course_analyzer_poc")
def course_analyzer(syllabus_path: str) -> CourseExtraction:
    """
    Run the full extraction pipeline against a single syllabus file.

    Args:
        syllabus_path: Path to a plain-text syllabus file.

    Returns:
        CourseExtraction with modules, items, and any unassigned items.
    """
    logger = _logger()
    path = Path(syllabus_path)
    if not path.exists():
        raise FileNotFoundError(f"Syllabus not found: {path}")

    syllabus_text = path.read_text()
    logger.info(
        "Starting analysis: file=%s (%d chars)", path.name, len(syllabus_text)
    )

    course_info = extract_course_info(syllabus_text)
    modules = extract_modules(syllabus_text)
    items = extract_items(syllabus_text, modules)
    result = assemble(path.name, course_info, modules, items)

    output_dir = Path(__file__).resolve().parent.parent / "output"
    write_output(result, output_dir)

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m flows.course_analyzer <path-to-syllabus>")
        sys.exit(1)
    course_analyzer(sys.argv[1])
