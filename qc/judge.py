"""
LLM-as-judge for CourseExtraction.

This is a single LLM call that compares an extraction against the source
syllabus and returns a JudgeResult. It deliberately reuses the existing
backend dispatcher (flows.ai_client.run_prompt) and the existing prompt
loader (flows.prompts.render_prompt) — same backends, same model
selection, same JSON contract.

The judge does NOT re-extract; the prompt is explicit about that. It
audits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flows.ai_client import AIConfig, default_config, resolve_model, run_prompt
from flows.prompts import render_prompt
from schemas.models import CourseExtraction

from qc.schemas import JudgeResult


QC_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "qc_prompts"


def judge_extraction(
    extraction: CourseExtraction,
    syllabus_text: str,
    ai_config: AIConfig | None = None,
) -> JudgeResult:
    """
    Run the fidelity judge over (syllabus_text, extraction) and return a
    JudgeResult. Raises ValueError if the model returns malformed JSON;
    let it propagate so failures are visible at the task boundary.
    """
    cfg = ai_config or default_config()

    rendered, prompt_config = render_prompt(
        "judge_extraction",
        prompts_dir=QC_PROMPTS_DIR,
        syllabus_text=syllabus_text,
        extraction_json=extraction.model_dump_json(indent=2),
    )

    raw: dict[str, Any] = run_prompt(
        prompt=rendered,
        temperature=prompt_config.temperature,
        max_tokens=prompt_config.max_tokens,
        config=cfg,
    )

    return JudgeResult(
        name="judge_extraction_fidelity",
        status=raw.get("status", "warn"),
        score=raw.get("score"),
        rationale=raw.get("rationale", ""),
        flagged_fields=list(raw.get("flagged_fields") or []),
        model=resolve_model(cfg),
    )
