"""CLI: init, write-chapter, reindex, status."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from . import config as config_mod
from . import orchestrator
from .importing import ImportError as ImportFailure
from .importing import resolve_premise
from .state import Project


app = typer.Typer(help="Multi-agent fantasy novel writer.")


def _load_agents(models_yaml: Path):
    load_dotenv()
    return config_mod.load(models_yaml)


@app.command()
def init(
    slug: str = typer.Argument(..., help="Project slug (directory name under projects/)"),
    premise: Optional[str] = typer.Option(
        None, "--premise",
        help="One-sentence premise (or path to a .md file containing it). "
             "Optional if --outline is provided (premise will be read from it).",
    ),
    world: Optional[Path] = typer.Option(
        None, "--world", help="Path to your own world bible markdown file."),
    outline: Optional[Path] = typer.Option(
        None, "--outline", help="Path to an outline file in our markdown format."),
    characters: Optional[Path] = typer.Option(
        None, "--characters",
        help="Path to characters: a directory of one .md per character, "
             "or a single .md with `# Name` headers per character."),
    chapters: Optional[Path] = typer.Option(
        None, "--chapters",
        help="Path to a directory of existing chapters (e.g. `01.md`, `ch-02.md`). "
             "Each will be indexed (facts extracted, summary written) unless "
             "--skip-indexing is set."),
    skip_indexing: bool = typer.Option(
        False, "--skip-indexing",
        help="When importing existing chapters, skip the continuity+summary step. "
             "Faster and cheaper, but future chapters won't know what happened."),
    models: Path = typer.Option(Path("models.yaml"), "--models", help="Path to models.yaml"),
):
    """Bootstrap a novel project.

    With no flags, generates world, outline, and characters from the premise
    using the LLM. With flags, substitutes your own files for any piece
    you provide — bring your own world, plot, characters, and even
    existing chapters to continue writing from.
    """
    project = Project(root=orchestrator.default_root(), slug=slug)
    if project.exists():
        typer.echo(f"Project '{slug}' already exists at {project.dir}")
        raise typer.Exit(code=1)

    # Resolve premise. If user gave a file path, read it. If not given,
    # try to read it from the outline file.
    premise_text: str
    if premise:
        premise_text = resolve_premise(premise)
    elif outline and outline.is_file():
        try:
            from .importing import parse_outline_file
            parsed = parse_outline_file(outline)
            premise_text = parsed.premise
            if not premise_text:
                typer.echo("--premise is required when the outline file has no premise field.")
                raise typer.Exit(code=1)
        except ImportFailure as e:
            typer.echo(f"Failed to read premise from outline: {e}")
            raise typer.Exit(code=1)
    else:
        typer.echo("--premise is required (or provide --outline with a premise field).")
        raise typer.Exit(code=1)

    agents = _load_agents(models)

    typer.echo(f"Bootstrapping '{slug}'…")
    try:
        orchestrator.bootstrap(
            project,
            agents,
            premise_text,
            world_path=world,
            outline_path=outline,
            characters_path=characters,
            chapters_path=chapters,
            skip_indexing=skip_indexing,
            on_progress=lambda msg: typer.echo(f"  {msg}"),
        )
    except ImportFailure as e:
        typer.echo(f"\nImport failed: {e}")
        raise typer.Exit(code=1)

    typer.echo(f"\nDone. See {project.dir}/")
    if chapters and not skip_indexing:
        typer.echo(f"Next chapter will be {orchestrator.next_chapter_number(project):02d}.")


@app.command("write-chapter")
def write_chapter(
    slug: str = typer.Argument(...),
    chapter: int = typer.Option(0, "--chapter", help="Chapter number (0 = next unwritten)"),
    revisions: int = typer.Option(2, "--revisions", help="Max writer↔editor rounds"),
    hold: bool = typer.Option(
        False, "--hold",
        help="Draft the chapter but skip indexing (no summary or facts yet). "
             "Use when you plan to edit the chapter yourself before it becomes canon. "
             "Run `approve-chapter` afterwards to commit your edited version.",
    ),
    models: Path = typer.Option(Path("models.yaml"), "--models"),
):
    """Write (or rewrite) a chapter.

    Before drafting, any prior chapter files you've edited since the last run
    are detected (by mtime) and reindexed automatically — so the writer
    sees your edits as canon, not the AI's original drafts.
    """
    agents = _load_agents(models)
    project = Project(root=orchestrator.default_root(), slug=slug)
    if not project.exists():
        typer.echo(f"Project '{slug}' not found. Run `init` first.")
        raise typer.Exit(code=1)

    n = chapter or orchestrator.next_chapter_number(project)
    typer.echo(f"Writing chapter {n:02d}…")
    prose = orchestrator.write_chapter(
        project, agents, n,
        max_revisions=revisions,
        hold=hold,
        on_progress=lambda msg: typer.echo(f"  {msg}"),
    )
    words = len(prose.split())
    typer.echo(f"Wrote chapters/{n:02d}.md ({words} words).")
    if hold:
        typer.echo(
            f"\nHeld (not indexed). Edit chapters/{n:02d}.md, then run:\n"
            f"  fantasy-agent approve-chapter {slug} --chapter {n}"
        )


@app.command("approve-chapter")
def approve_chapter(
    slug: str = typer.Argument(...),
    chapter: int = typer.Option(
        0, "--chapter",
        help="Chapter number (0 = most recent chapter without a summary, or the latest if all are indexed)",
    ),
    models: Path = typer.Option(Path("models.yaml"), "--models"),
):
    """Mark a chapter's on-disk version as canon.

    Runs the continuity agent to extract facts and the summarizer to write a
    recap from the current chapter file. Any previous facts or summary for
    this chapter are replaced. Typical use: generated a chapter with
    `--hold`, edited it yourself, now tell the system to use your version.

    Also works as a manual re-index after you've edited an already-approved
    chapter, though `write-chapter` normally detects edits automatically.
    """
    agents = _load_agents(models)
    project = Project(root=orchestrator.default_root(), slug=slug)
    if not project.exists():
        typer.echo(f"Project '{slug}' not found.")
        raise typer.Exit(code=1)

    if chapter:
        n = chapter
    else:
        # Default: prefer the highest chapter without a summary (held), else latest.
        chapters_on_disk = sorted(
            int(p.stem) for p in project.chapters_dir.glob("*.md") if p.stem.isdigit()
        )
        if not chapters_on_disk:
            typer.echo("No chapters on disk yet.")
            raise typer.Exit(code=1)
        unindexed = [
            n for n in chapters_on_disk
            if not (project.summaries_dir / f"{n:02d}.md").exists()
        ]
        n = unindexed[-1] if unindexed else chapters_on_disk[-1]

    if project.read_chapter(n) is None:
        typer.echo(f"No chapter {n} on disk.")
        raise typer.Exit(code=1)

    typer.echo(f"Approving chapter {n:02d}…")
    orchestrator.approve_chapter(project, agents, n)
    typer.echo(f"Done. Future chapters will see your version as canon.")


@app.command()
def reindex(
    slug: str = typer.Argument(...),
    chapter: int = typer.Option(
        0, "--chapter",
        help="Reindex only this chapter (0 = reindex every chapter)",
    ),
    models: Path = typer.Option(Path("models.yaml"), "--models"),
):
    """Rebuild summaries + continuity facts from chapters already on disk.

    Without --chapter, rebuilds every chapter (the nuclear option). With
    --chapter N, rebuilds only chapter N. `write-chapter` auto-detects edits
    via mtime, so you rarely need this manually — reach for it only when
    mtimes don't reflect reality (e.g. after `git checkout`).
    """
    agents = _load_agents(models)
    project = Project(root=orchestrator.default_root(), slug=slug)
    if not project.exists():
        typer.echo(f"Project '{slug}' not found.")
        raise typer.Exit(code=1)

    if chapter:
        if project.read_chapter(chapter) is None:
            typer.echo(f"No chapter {chapter} on disk.")
            raise typer.Exit(code=1)
        typer.echo(f"Reindexing chapter {chapter:02d}…")
        orchestrator.reindex_chapter(project, agents, chapter)
    else:
        typer.echo(f"Reindexing all chapters of '{slug}'…")
        orchestrator.reindex(
            project, agents, on_progress=lambda msg: typer.echo(f"  {msg}")
        )
    typer.echo("Done.")


@app.command()
def status(
    slug: str = typer.Argument(...),
):
    """Show project progress."""
    project = Project(root=orchestrator.default_root(), slug=slug)
    if not project.exists():
        typer.echo(f"Project '{slug}' not found.")
        raise typer.Exit(code=1)

    outline = project.read_outline()
    chapters_written = project.chapter_count()
    total_chapters = len(outline.chapters) if outline else 0
    total_words = 0
    for n in range(1, chapters_written + 1):
        prose = project.read_chapter(n) or ""
        total_words += len(prose.split())

    typer.echo(f"Project: {slug}")
    typer.echo(f"  Chapters written: {chapters_written} / {total_chapters}")
    typer.echo(f"  Total words: {total_words}")
    typer.echo(f"  Facts recorded: {len(project.read_facts())}")
    if outline and chapters_written < total_chapters:
        next_ch = outline.chapters[chapters_written]
        typer.echo(f"  Next: Chapter {next_ch.number} — {next_ch.title}")


if __name__ == "__main__":
    app()
