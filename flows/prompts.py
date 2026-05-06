"""
Prompt management. Reads YAML prompt files, renders the Jinja2 template
against a context, and returns both the rendered text and the model config.

Keeping this in one place means the flows never touch yaml.safe_load or
Jinja2 directly. If we move to a prompt registry later, only this file
changes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template
from pydantic import BaseModel


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptConfig(BaseModel):
    version: str
    temperature: float
    max_tokens: int
    description: str
    template: str


@lru_cache(maxsize=64)
def _load_raw(name: str, prompts_dir: Path = PROMPTS_DIR) -> PromptConfig:
    """Load and parse the YAML once per process; the rendered text changes
    per call but the static fields don't."""
    path = prompts_dir / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return PromptConfig(**yaml.safe_load(path.read_text()))


def render_prompt(
    name: str,
    *,
    prompts_dir: Path | None = None,
    **context: Any,
) -> tuple[str, PromptConfig]:
    """
    Load prompt `name` (without .yaml extension) and render its template
    against the given context. Returns (rendered_text, config).

    `prompts_dir` lets sibling pipelines (e.g. qc/) keep their own prompt
    directory without shoehorning files into the main `prompts/` tree.
    Defaults to the main pipeline's prompts directory.
    """
    config = _load_raw(name, prompts_dir or PROMPTS_DIR)
    rendered = Template(config.template).render(**context)
    return rendered, config
