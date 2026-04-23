"""Tests for the bring-your-own-content bootstrap flow."""
from __future__ import annotations

from fantasy_agent import orchestrator
from fantasy_agent.state import Project


# --- Helpers: scratch user-provided materials --------------------------------


def _write_world(path):
    path.write_text("# The World\nAn unusual world with purple skies.\n")


def _write_outline(path):
    path.write_text(
        "# Outline\n\n"
        "## Premise\nA cartographer discovers her maps redraw themselves overnight.\n\n"
        "## Chapters\n\n"
        "### Chapter 1: The Anomaly\n"
        "Lira wakes to a changed map.\n\n"
        "**Beats:**\n"
        "- Lira notices the map has shifted\n"
        "- She consults Arden — inciting incident\n\n"
        "### Chapter 2: The Rule\n"
        "Arden reveals the price of mapcrafting.\n\n"
        "### Chapter 3: The Choice\n"
        "Lira must decide whether to pay it.\n"
    )


def _write_characters_dir(path):
    path.mkdir()
    (path / "lira.md").write_text(
        "# Lira Venn\n\n**Role:** protagonist\n\n"
        "## Description\nA cartographer.\n\n## Motivations\nTruth.\n\n"
        "## Voice\nTerse.\n\n## Arc\nGrows.\n"
    )
    (path / "arden.md").write_text(
        "# Arden Scole\n\n**Role:** supporting\n\n"
        "## Description\nA mentor who knows too much.\n"
    )


def _write_existing_chapter(path, n, prose_snippet):
    path.write_text(
        f"# Chapter {n}\n\n"
        + (prose_snippet + " ") * 50
    )


# --- Tests -------------------------------------------------------------------


def test_bootstrap_imports_all_four_pieces(fake_agents, project_root, tmp_path):
    """With all four flags set, bootstrap does no LLM bootstrap calls for
    world/outline/characters, but DOES index imported chapters."""
    # Arrange: scratch materials outside the project.
    src = tmp_path / "src"
    src.mkdir()
    _write_world(src / "world.md")
    _write_outline(src / "outline.md")
    chars_dir = src / "chars"
    _write_characters_dir(chars_dir)
    chapters_dir = src / "existing"
    chapters_dir.mkdir()
    _write_existing_chapter(chapters_dir / "01.md", 1, "Lira studied the map.")

    # Track which backends got called.
    wb = fake_agents["worldbuilder"].backend
    pl = fake_agents["plotter"].backend
    ch = fake_agents["character"].backend
    wb.calls.clear(); pl.calls.clear(); ch.calls.clear()

    project = Project(project_root, "novel")
    orchestrator.bootstrap(
        project, fake_agents,
        premise="A cartographer discovers her maps redraw themselves overnight.",
        world_path=src / "world.md",
        outline_path=src / "outline.md",
        characters_path=chars_dir,
        chapters_path=chapters_dir,
    )

    # Imported world is on disk (our content, not the fake's).
    assert "purple skies" in project.read_world()

    # Outline loaded — 3 chapters from our file.
    outline = project.read_outline()
    assert outline is not None
    assert len(outline.chapters) == 3
    assert outline.chapters[0].title == "The Anomaly"

    # Characters loaded — 2 from our dir.
    chars = project.read_characters()
    assert {c.name for c in chars} == {"Lira Venn", "Arden Scole"}

    # Existing chapter copied in.
    assert project.read_chapter(1) is not None
    assert "Lira studied" in project.read_chapter(1)

    # Indexing happened: summary and at least one fact for the imported chapter.
    summaries = dict(project.read_summaries())
    assert 1 in summaries
    assert project.read_facts()

    # No calls to the bootstrap agents whose outputs we provided.
    assert not wb.calls, "worldbuilder should not have been called"
    assert not pl.calls, "plotter should not have been called"
    assert not ch.calls, "character designer should not have been called"


def test_bootstrap_with_partial_imports_generates_the_rest(fake_agents, project_root, tmp_path):
    """Only world provided — plotter and character designer still run."""
    src = tmp_path / "src"
    src.mkdir()
    _write_world(src / "world.md")

    wb = fake_agents["worldbuilder"].backend
    pl = fake_agents["plotter"].backend
    ch = fake_agents["character"].backend
    wb.calls.clear(); pl.calls.clear(); ch.calls.clear()

    project = Project(project_root, "novel")
    orchestrator.bootstrap(
        project, fake_agents,
        premise="A test premise.",
        world_path=src / "world.md",
    )

    # Our world survived.
    assert "purple skies" in project.read_world()
    # Outline and characters were generated via the fake.
    assert project.read_outline() is not None
    assert project.read_characters()

    assert not wb.calls, "worldbuilder should be skipped when --world is provided"
    assert pl.calls, "plotter should have run"
    assert ch.calls, "character designer should have run"


def test_bootstrap_skip_indexing_does_not_call_continuity(
    fake_agents, project_root, tmp_path
):
    src = tmp_path / "src"
    src.mkdir()
    _write_world(src / "world.md")
    _write_outline(src / "outline.md")
    chars_dir = src / "chars"; _write_characters_dir(chars_dir)
    chapters_dir = src / "existing"; chapters_dir.mkdir()
    _write_existing_chapter(chapters_dir / "01.md", 1, "Existing chapter 1 prose.")

    cont = fake_agents["continuity"].backend
    cont.calls.clear()

    project = Project(project_root, "novel")
    orchestrator.bootstrap(
        project, fake_agents,
        premise="x",
        world_path=src / "world.md",
        outline_path=src / "outline.md",
        characters_path=chars_dir,
        chapters_path=chapters_dir,
        skip_indexing=True,
    )

    # Chapter imported, but no summary / facts.
    assert project.read_chapter(1) is not None
    assert project.read_summaries() == []
    assert project.read_facts() == []
    assert not cont.calls


def test_next_chapter_number_respects_max_not_count(fake_agents, project_root, tmp_path):
    """If user imports 1, 2, 5, next chapter is 6 (not 4)."""
    src = tmp_path / "src"
    src.mkdir()
    _write_world(src / "world.md")
    _write_outline(src / "outline.md")
    _write_characters_dir(src / "chars")
    chapters_dir = src / "existing"; chapters_dir.mkdir()
    _write_existing_chapter(chapters_dir / "01.md", 1, "ch1.")
    _write_existing_chapter(chapters_dir / "02.md", 2, "ch2.")
    _write_existing_chapter(chapters_dir / "05.md", 5, "ch5.")

    project = Project(project_root, "novel")
    orchestrator.bootstrap(
        project, fake_agents,
        premise="x",
        world_path=src / "world.md",
        outline_path=src / "outline.md",
        characters_path=src / "chars",
        chapters_path=chapters_dir,
        skip_indexing=True,
    )

    assert orchestrator.next_chapter_number(project) == 6


def test_write_chapter_continues_from_imported_chapters(
    fake_agents, project_root, tmp_path
):
    """After importing chapter 1, write-chapter(2) uses its summary as context."""
    src = tmp_path / "src"
    src.mkdir()
    _write_world(src / "world.md")
    _write_outline(src / "outline.md")
    _write_characters_dir(src / "chars")
    chapters_dir = src / "existing"; chapters_dir.mkdir()
    _write_existing_chapter(chapters_dir / "01.md", 1,
                            "Lira studied the changed coastline.")

    project = Project(project_root, "novel")
    orchestrator.bootstrap(
        project, fake_agents,
        premise="x",
        world_path=src / "world.md",
        outline_path=src / "outline.md",
        characters_path=src / "chars",
        chapters_path=chapters_dir,
    )

    # Now write chapter 2 and verify the writer's prompt includes the summary
    # block for chapter 1.
    writer_fake = fake_agents["writer"].backend
    writer_fake.calls.clear()
    orchestrator.write_chapter(project, fake_agents, 2, max_revisions=0)

    writer_calls = [
        c for c in writer_fake.calls
        if "You are a novelist drafting a chapter" in c["system"]
    ]
    assert writer_calls
    assert any("Story so far" in c["user"] for c in writer_calls)


def test_reindex_rebuilds_summaries_and_facts(fake_agents, project_root, tmp_path):
    """reindex() wipes and rebuilds summaries + continuity from existing chapters."""
    src = tmp_path / "src"
    src.mkdir()
    _write_world(src / "world.md")
    _write_outline(src / "outline.md")
    _write_characters_dir(src / "chars")
    chapters_dir = src / "existing"; chapters_dir.mkdir()
    _write_existing_chapter(chapters_dir / "01.md", 1, "ch1 prose.")

    project = Project(project_root, "novel")
    orchestrator.bootstrap(
        project, fake_agents,
        premise="x",
        world_path=src / "world.md",
        outline_path=src / "outline.md",
        characters_path=src / "chars",
        chapters_path=chapters_dir,
        skip_indexing=True,  # no indexing yet
    )
    assert project.read_summaries() == []
    assert project.read_facts() == []

    orchestrator.reindex(project, fake_agents)

    assert dict(project.read_summaries()).get(1) is not None
    assert project.read_facts()
