"""Orchestrator: bootstrap a project and write chapters one at a time."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, TypeVar

from pydantic import ValidationError

from .agents import character, continuity, editor, plotter, summarizer, worldbuilder, writer
from .config import AgentConfig
from .context import (
    build_continuity_context,
    build_editor_context,
    build_plotter_context,
    build_writer_context,
)
from .state import Critique, Project


log = logging.getLogger(__name__)

T = TypeVar("T")


def _safe_call(label: str, fn: Callable[[], T], fallback: T) -> T:
    """Run fn; if it raises a parse/validation error, log and return fallback.

    Catches the failure modes that come from a model returning malformed JSON
    or a shape that doesn't fit our pydantic schemas. Other errors (network,
    auth, programmer mistakes) are not caught — they should fail loudly.
    """
    try:
        return fn()
    except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as e:
        log.warning("%s returned malformed output (%s); using fallback", label, e)
        return fallback


def bootstrap(project: Project, agents: dict[str, AgentConfig], premise: str) -> None:
    """Init project, then run worldbuilder → plotter → character designer."""
    project.create(premise)

    world = worldbuilder.run(agents["worldbuilder"], premise=premise)
    project.write_world(world)

    # First-pass plot without characters — plotter sees premise + world.
    plot_ctx = build_plotter_context(project)
    outline = plotter.run(agents["plotter"], plot_ctx)
    project.write_outline(outline)

    # Design characters against the outline.
    sheets = character.run(
        agents["character"],
        premise=premise,
        world=world,
        outline=outline,
    )
    for sheet in sheets:
        project.write_character(sheet)


def write_chapter(
    project: Project,
    agents: dict[str, AgentConfig],
    chapter_number: int,
    max_revisions: int = 2,
) -> str:
    """Draft → persist → edit → revise (up to N) → extract facts → summarize.

    The draft is written to disk *before* the editor runs, so a crash or
    malformed editor response never loses the writer's work. The editor and
    continuity calls are wrapped in `_safe_call` so a malformed JSON response
    falls back to a safe default rather than killing the run.
    """
    writer_ctx = build_writer_context(project, chapter_number)

    draft = writer.run(agents["writer"], writer_ctx)
    project.write_chapter(chapter_number, draft)

    for _ in range(max_revisions):
        edit_ctx = build_editor_context(project, chapter_number, draft)
        critique = _safe_call(
            f"editor[ch{chapter_number}]",
            lambda: editor.run(agents["editor"], edit_ctx),
            fallback=Critique(status="approve"),
        )
        if critique.status == "approve":
            break
        draft = writer.revise(
            agents["writer"],
            writer_ctx,
            draft,
            critique.issues,
            critique.suggestions,
        )
        project.write_chapter(chapter_number, draft)

    # Post-write: extract facts and summarize, so future chapters have
    # bounded context.
    cont_ctx = build_continuity_context(chapter_number, draft)
    facts = _safe_call(
        f"continuity[ch{chapter_number}]",
        lambda: continuity.run(agents["continuity"], cont_ctx),
        fallback=[],
    )
    if facts:
        project.append_facts(facts)

    summary = summarizer.run(
        agents["continuity"],  # reuse cheap backend; summarizer is mechanical
        chapter_number=chapter_number,
        prose=draft,
    )
    project.write_summary(chapter_number, summary)

    return draft


def next_chapter_number(project: Project) -> int:
    return project.chapter_count() + 1


def default_root() -> Path:
    return Path.cwd()
