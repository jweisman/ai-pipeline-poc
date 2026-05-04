"""
Pydantic models defining the contracts between tasks in the syllabus extraction
pipeline. These also serve as the contract for what the AI prompts must return.

Why Pydantic and not just dicts:
  - Validation at task boundaries catches malformed LLM output loudly and early
  - Field descriptions double as documentation for the prompt writer
  - JSON schema can be derived for prompt instructions or for output_schema
    configuration of structured outputs
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


# -------------------------
# Stage 0: Course-level information
# -------------------------

CourseLevel = Literal["undergraduate", "graduate", "other"]


class CourseInfo(BaseModel):
    """
    Top-level metadata about the course itself: what it is, who teaches it,
    where it sits in the catalog, and what it sets out to accomplish.

    All fields except `title` are optional because syllabi vary widely in
    what they state explicitly. When in doubt the prompt is instructed to
    return null rather than guess.
    """
    title: str = Field(
        ...,
        description=(
            "The course's human-readable name, e.g. 'Basic Composition' or "
            "'Judgment and Decision Making'."
        ),
    )
    code: Optional[str] = Field(
        default=None,
        description=(
            "Course number/code as printed in the syllabus, e.g. 'ENGL 101' "
            "or 'COMM 663'."
        ),
    )
    department: Optional[str] = Field(
        default=None,
        description=(
            "Department or program offering the course, e.g. 'English' or "
            "'Marketing Division, Sauder School of Business'."
        ),
    )
    institution: Optional[str] = Field(
        default=None,
        description="University or college, e.g. 'University of British Columbia'.",
    )
    level: Optional[CourseLevel] = Field(
        default=None,
        description=(
            "Academic level. 'undergraduate' for typical 100–400 level "
            "courses, 'graduate' for masters/PhD coursework, 'other' for "
            "anything else (continuing ed, certificate, etc.). Null if not "
            "inferable."
        ),
    )
    term: Optional[str] = Field(
        default=None,
        description=(
            "Academic term as stated, e.g. 'Spring Quarter 2013' or "
            "'Fall 2024'. None if unstated."
        ),
    )
    instructors: list[str] = Field(
        default_factory=list,
        description=(
            "Names of instructors as stated in the syllabus. Empty list if "
            "not stated."
        ),
    )
    description: Optional[str] = Field(
        default=None,
        description=(
            "Free-text course description or overview, paraphrased lightly "
            "from the syllabus. None if no overview-style paragraph exists."
        ),
    )
    objectives: list[str] = Field(
        default_factory=list,
        description=(
            "Course-level learning objectives or outcomes as explicitly "
            "stated. Empty list if none are stated. Do NOT invent objectives "
            "and do NOT include module-level objectives here."
        ),
    )


# -------------------------
# Stage 1: Modules
# -------------------------

class Module(BaseModel):
    """
    A single unit of the course. In syllabi this is usually a 'week', a numbered
    'session', or a topical unit. Keep the order_index because the order modules
    appear in is meaningful and we'll re-stitch on it later.
    """
    order_index: int = Field(
        ...,
        description="1-based position of this module in the course (1 = first module).",
    )
    title: str = Field(
        ...,
        description=(
            "Short title or topic for the module, e.g. 'Week 2: Elements of "
            "Effective Writing' or 'Choice Overload'."
        ),
    )
    objectives: list[str] = Field(
        default_factory=list,
        description=(
            "Module-level learning objectives if explicitly stated in the "
            "syllabus. Empty list if no objectives are present at the module "
            "level. Do NOT invent objectives."
        ),
    )


class ModuleExtraction(BaseModel):
    """Wrapper to make the LLM's top-level JSON output a single object."""
    modules: list[Module]


# -------------------------
# Stage 2: Items (materials + assignments)
# -------------------------

ItemType = Literal["material", "assignment"]
MaterialFormat = Literal[
    "reading",       # any text-based reading: article, book chapter, etc.
    "video",
    "podcast",
    "website",
    "other",
]


class CourseItem(BaseModel):
    """
    A single piece of course content: either an instructional material the
    student consumes, or an assignment the student produces.
    """
    order_index: int = Field(
        ...,
        description="1-based position of this item in the course as it appears in the syllabus.",
    )
    item_type: ItemType = Field(
        ...,
        description=(
            "'material' for things the student reads/watches/listens to, "
            "'assignment' for things the student does and submits or completes."
        ),
    )
    title: str = Field(
        ...,
        description=(
            "Short human-readable title. For materials, the work's title. "
            "For assignments, a brief name like 'Personal Essay First Draft'."
        ),
    )
    description: Optional[str] = Field(
        default=None,
        description="Free-text description if the syllabus provides one.",
    )

    # Module association
    module_order_index: Optional[int] = Field(
        default=None,
        description=(
            "1-based order_index of the Module this item belongs to. None "
            "if the item is course-level (e.g. a final exam not tied to a "
            "specific week) or cannot be confidently associated."
        ),
    )

    # Material-only fields
    material_format: Optional[MaterialFormat] = Field(
        default=None,
        description="Required when item_type == 'material'. Otherwise None.",
    )
    citation: Optional[str] = Field(
        default=None,
        description=(
            "For materials: the full citation as it appears in the syllabus, "
            "or the closest approximation. None for assignments."
        ),
    )

    # Assignment-only fields
    assignment_format: Optional[str] = Field(
        default=None,
        description=(
            "For assignments: free-form short label like 'essay', 'quiz', "
            "'discussion post', 'group memo', 'presentation'. None for materials."
        ),
    )
    points: Optional[float] = Field(
        default=None,
        description="Point value if the syllabus assigns one. None if unstated.",
    )
    due: Optional[str] = Field(
        default=None,
        description="Due date or window as a string, exactly as stated. None if unstated.",
    )


class ItemExtraction(BaseModel):
    """Wrapper for the LLM's top-level JSON output."""
    items: list[CourseItem]


# -------------------------
# Stage 3: Final assembled output
# -------------------------

class ModuleWithItems(BaseModel):
    """Module plus the items that belong to it, in order."""
    order_index: int
    title: str
    objectives: list[str]
    items: list[CourseItem] = Field(default_factory=list)


class CourseExtraction(BaseModel):
    """Top-level result of the pipeline."""
    source_filename: str
    course_info: CourseInfo
    modules: list[ModuleWithItems]
    unassigned_items: list[CourseItem] = Field(
        default_factory=list,
        description=(
            "Items that could not be confidently associated with a specific "
            "module (e.g. course-wide final exam, semester-long project)."
        ),
    )
