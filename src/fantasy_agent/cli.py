"""CLI: init, write-chapter, status."""
from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv

from . import config as config_mod
from . import orchestrator
from .state import Project


app = typer.Typer(help="Multi-agent fantasy novel writer.")


def _load_agents(models_yaml: Path):
    load_dotenv()
    return config_mod.load(models_yaml)


@app.command()
def init(
    slug: str = typer.Argument(..., help="Project slug (directory name under projects/)"),
    premise: str = typer.Option(..., "--premise", help="One- or two-sentence premise."),
    models: Path = typer.Option(Path("models.yaml"), "--models", help="Path to models.yaml"),
):
    """Bootstrap a novel: world bible, outline, characters."""
    agents = _load_agents(models)
    project = Project(root=orchestrator.default_root(), slug=slug)
    if project.exists():
        typer.echo(f"Project '{slug}' already exists at {project.dir}")
        raise typer.Exit(code=1)

    typer.echo(f"Bootstrapping '{slug}'…")
    orchestrator.bootstrap(project, agents, premise)
    typer.echo(f"Done. See {project.dir}/world.md, outline.md, characters/")


@app.command("write-chapter")
def write_chapter(
    slug: str = typer.Argument(...),
    chapter: int = typer.Option(0, "--chapter", help="Chapter number (0 = next unwritten)"),
    revisions: int = typer.Option(2, "--revisions", help="Max writer↔editor rounds"),
    models: Path = typer.Option(Path("models.yaml"), "--models"),
):
    """Write (or rewrite) a chapter."""
    agents = _load_agents(models)
    project = Project(root=orchestrator.default_root(), slug=slug)
    if not project.exists():
        typer.echo(f"Project '{slug}' not found. Run `init` first.")
        raise typer.Exit(code=1)

    n = chapter or orchestrator.next_chapter_number(project)
    typer.echo(f"Writing chapter {n:02d}…")
    prose = orchestrator.write_chapter(project, agents, n, max_revisions=revisions)
    words = len(prose.split())
    typer.echo(f"Wrote chapters/{n:02d}.md ({words} words).")


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
