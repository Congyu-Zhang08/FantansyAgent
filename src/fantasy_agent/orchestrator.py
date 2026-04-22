"""Orchestrator: bootstrap a project and write chapters one at a time."""
from __future__ import annotations

from pathlib import Path

from .agents import character, continuity, editor, plotter, summarizer, worldbuilder, writer
from .config import AgentConfig
from .context import (
    build_continuity_context,
    build_editor_context,
    build_plotter_context,
    build_writer_context,
)
from .state import Project


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
    """Draft → edit → revise (up to N) → extract facts → summarize → save."""
    writer_ctx = build_writer_context(project, chapter_number)

    draft = writer.run(agents["writer"], writer_ctx)

    for _ in range(max_revisions):
        edit_ctx = build_editor_context(project, chapter_number, draft)
        critique = editor.run(agents["editor"], edit_ctx)
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
    facts = continuity.run(agents["continuity"], cont_ctx)
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
