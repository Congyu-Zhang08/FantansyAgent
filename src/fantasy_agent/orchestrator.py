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

    Appends facts and writes (overwriting) the summary file. If the chapter
    was previously indexed, old facts remain in continuity.jsonl — use
    `reindex_chapter` to replace them instead.
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


def reindex_chapter(
    project: Project, agents: dict[str, AgentConfig], chapter_number: int
) -> None:
    """Re-index a single chapter: drop its old facts + summary, regenerate from disk.

    This is the primitive that makes user edits propagate to future chapters.
    When a user rewrites `chapters/03.md`, calling reindex_chapter(.., 3)
    rebuilds the summary and continuity facts to match the edited prose,
    without touching any other chapter's state.
    """
    project.remove_facts_for_chapter(chapter_number)
    summary_path = project.summaries_dir / f"{chapter_number:02d}.md"
    if summary_path.exists():
        summary_path.unlink()
    index_existing_chapter(project, agents, chapter_number)


def _chapter_numbers_on_disk(project: Project) -> list[int]:
    return sorted(
        int(p.stem) for p in project.chapters_dir.glob("*.md") if p.stem.isdigit()
    )


def sync_stale_indexes(
    project: Project,
    agents: dict[str, AgentConfig],
    up_to_chapter: int,
    on_progress: Callable[[str], None] | None = None,
) -> list[int]:
    """Re-index any chapters < `up_to_chapter` whose prose is newer than their summary.

    Compares file mtimes:
    - If `chapters/M.md` exists but `summaries/M.md` does not, M was never
      indexed (e.g. generated with --hold); index it.
    - If `chapters/M.md` is newer than `summaries/M.md`, the user edited the
      chapter since it was last indexed; re-index to match.

    Called automatically at the top of `write_chapter` so user edits to any
    prior chapter propagate to the writer's context without ceremony. Returns
    the chapter numbers that were reindexed (for tests / reporting).
    """
    progress = on_progress or (lambda _msg: None)
    reindexed: list[int] = []

    for n in _chapter_numbers_on_disk(project):
        if n >= up_to_chapter:
            continue
        chapter_path = project.chapters_dir / f"{n:02d}.md"
        summary_path = project.summaries_dir / f"{n:02d}.md"
        if not summary_path.exists():
            progress(f"Chapter {n:02d} not yet indexed; indexing now…")
            index_existing_chapter(project, agents, n)
            reindexed.append(n)
        elif chapter_path.stat().st_mtime > summary_path.stat().st_mtime:
            progress(f"Chapter {n:02d} was edited since last index; reindexing…")
            reindex_chapter(project, agents, n)
            reindexed.append(n)

    return reindexed


def reindex(
    project: Project, agents: dict[str, AgentConfig],
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Wipe and rebuild summaries + continuity facts from every chapter on disk.

    The nuclear option: forces a full re-index even for chapters whose
    summaries look fresh. Use when you've done something the mtime check
    can't see (e.g. hand-edited continuity.jsonl, changed prompts).
    For single-chapter refresh, use `reindex_chapter`; for auto-detection,
    that's built into `write_chapter`.
    """
    progress = on_progress or (lambda _msg: None)
    for n in _chapter_numbers_on_disk(project):
        progress(f"Reindexing chapter {n:02d}…")
        reindex_chapter(project, agents, n)


def write_chapter(
    project: Project,
    agents: dict[str, AgentConfig],
    chapter_number: int,
    max_revisions: int = 2,
    *,
    hold: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Draft → persist → edit → revise (up to N) → index (unless held).

    Before drafting, auto-sync any prior chapters the user edited since they
    were last indexed. This means the writer sees the user's edits as canon,
    not the AI's original drafts.

    The draft is written to disk *before* the editor runs, so a crash or
    malformed editor response never loses the writer's work. Editor and
    continuity calls are wrapped in `_safe_call` so a malformed JSON response
    falls back to a safe default rather than killing the run.

    With `hold=True`, the chapter is drafted and edited but NOT indexed
    (no summary written, no facts extracted). Use this when you plan to
    rewrite the chapter yourself before it becomes canon. Follow up with
    `approve_chapter(project, agents, N)` once you're satisfied with the
    final version.
    """
    progress = on_progress or (lambda _msg: None)

    # Auto-sync stale summaries/facts from earlier chapters the user edited.
    reindexed = sync_stale_indexes(project, agents, chapter_number, progress)
    if reindexed:
        progress(f"Synced {len(reindexed)} edited chapter(s) before writing.")

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

    if hold:
        progress(
            f"Chapter {chapter_number:02d} held (not indexed). "
            f"Edit chapters/{chapter_number:02d}.md, then run `approve-chapter`."
        )
        return draft

    # Post-write: extract facts and summarize, so future chapters have
    # bounded context.
    _index_from_prose(project, agents, chapter_number, draft)
    return draft


def _index_from_prose(
    project: Project,
    agents: dict[str, AgentConfig],
    chapter_number: int,
    prose: str,
) -> None:
    """Shared post-write indexing: extract facts, write summary."""
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


def approve_chapter(
    project: Project,
    agents: dict[str, AgentConfig],
    chapter_number: int,
) -> None:
    """Mark a chapter's on-disk version as canon: extract facts, write summary.

    Idempotent: if the chapter was already indexed (e.g. it was generated
    without `--hold`), this drops the old facts/summary and rebuilds from
    whatever is currently on disk. That's exactly what you want if you
    edited the chapter by hand — your version replaces the AI's.
    """
    if project.read_chapter(chapter_number) is None:
        raise ValueError(f"no chapter {chapter_number} to approve")
    reindex_chapter(project, agents, chapter_number)


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
