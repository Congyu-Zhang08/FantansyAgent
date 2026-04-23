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
from .importing import (
    discover_chapter_files,
    parse_characters_path,
    parse_outline_file,
    parse_world_file,
)
from .state import CharacterSheet, Critique, Outline, Project


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


def bootstrap(
    project: Project,
    agents: dict[str, AgentConfig],
    premise: str,
    *,
    world_path: Path | None = None,
    outline_path: Path | None = None,
    characters_path: Path | None = None,
    chapters_path: Path | None = None,
    skip_indexing: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Initialize a project, optionally seeding it with user-provided materials.

    For each piece (world, outline, characters, existing chapters), if a path
    is given the file is read and used directly; otherwise the corresponding
    agent is run to generate it. Existing chapters (if any) are automatically
    indexed via the continuity and summarizer agents so future chapters have
    the right context — pass `skip_indexing=True` to opt out.
    """
    project.create(premise)
    progress = on_progress or (lambda _msg: None)

    # --- World ---
    if world_path is not None:
        progress(f"Importing world from {world_path}")
        world = parse_world_file(world_path)
        project.write_world(world)
    else:
        progress("Running worldbuilder…")
        world = worldbuilder.run(agents["worldbuilder"], premise=premise)
        project.write_world(world)

    # --- Outline ---
    outline: Outline
    if outline_path is not None:
        progress(f"Importing outline from {outline_path}")
        outline = parse_outline_file(outline_path)
        project.write_outline(outline)
    else:
        progress("Running plotter…")
        plot_ctx = build_plotter_context(project)
        outline = plotter.run(agents["plotter"], plot_ctx)
        project.write_outline(outline)

    # --- Characters ---
    sheets: list[CharacterSheet]
    if characters_path is not None:
        progress(f"Importing characters from {characters_path}")
        sheets = parse_characters_path(characters_path)
    else:
        progress("Running character designer…")
        sheets = character.run(
            agents["character"],
            premise=premise,
            world=world,
            outline=outline,
        )
    for sheet in sheets:
        project.write_character(sheet)

    # --- Existing chapters ---
    if chapters_path is not None:
        files = discover_chapter_files(chapters_path)
        progress(f"Importing {len(files)} existing chapter(s) from {chapters_path}")
        for n, src in files:
            project.write_chapter(n, src.read_text())
        if skip_indexing:
            progress("Skipping indexing of existing chapters (--skip-indexing)")
        else:
            for n, _src in files:
                progress(f"Indexing chapter {n:02d} (extracting facts + summary)…")
                index_existing_chapter(project, agents, n)


def index_existing_chapter(
    project: Project, agents: dict[str, AgentConfig], chapter_number: int
) -> None:
    """Extract canonical facts and write a summary for a chapter already on disk.

    Used after importing user-provided chapters so future chapters have the
    right continuity context. Idempotent-ish: running it twice appends the
    facts twice (the continuity file is append-only). Tests cover this.
    """
    prose = project.read_chapter(chapter_number)
    if prose is None:
        raise ValueError(f"no chapter {chapter_number} on disk")

    cont_ctx = build_continuity_context(chapter_number, prose)
    facts = _safe_call(
        f"continuity[ch{chapter_number}]",
        lambda: continuity.run(agents["continuity"], cont_ctx),
        fallback=[],
    )
    if facts:
        project.append_facts(facts)

    summary = summarizer.run(
        agents["continuity"],
        chapter_number=chapter_number,
        prose=prose,
    )
    project.write_summary(chapter_number, summary)


def reindex(
    project: Project, agents: dict[str, AgentConfig],
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Wipe and rebuild summaries + continuity facts from the chapters on disk.

    Useful if you've hand-edited chapter files or added them outside of
    `write-chapter` and want future chapters to see the updated state.
    """
    progress = on_progress or (lambda _msg: None)

    # Wipe existing facts and summaries so we don't double-count.
    project.continuity_path.write_text("")
    for p in project.summaries_dir.glob("*.md"):
        p.unlink()

    for n in range(1, project.chapter_count() + 1):
        if project.read_chapter(n) is None:
            continue
        progress(f"Reindexing chapter {n:02d}…")
        index_existing_chapter(project, agents, n)


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
    """Return max existing chapter + 1, or 1 if none exist.

    Uses max (not count) so imported chapters with gaps still advance
    correctly — e.g. if you import 1, 2, 5, next is 6, not 4.
    """
    existing = [
        int(p.stem) for p in project.chapters_dir.glob("*.md") if p.stem.isdigit()
    ]
    return (max(existing) + 1) if existing else 1


def default_root() -> Path:
    return Path.cwd()
