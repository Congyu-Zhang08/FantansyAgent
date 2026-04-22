"""Round-trip tests for project state serialization."""
from __future__ import annotations

from fantasy_agent.state import Beat, Chapter, CharacterSheet, Fact, Outline, Project


def test_project_creates_directory_layout(project_root):
    p = Project(project_root, "novel")
    p.create("A premise for testing.")
    assert (p.dir / "premise.md").exists()
    assert p.characters_dir.exists()
    assert p.chapters_dir.exists()
    assert p.summaries_dir.exists()
    assert p.continuity_path.exists()


def test_character_round_trip(project_root):
    p = Project(project_root, "novel")
    p.create("x")
    original = CharacterSheet(
        name="Lira Venn",
        role="protagonist",
        description="A cartographer.",
        motivations="Truth.",
        voice="Terse.",
        arc="Grows.",
    )
    p.write_character(original)
    sheets = p.read_characters()
    assert len(sheets) == 1
    loaded = sheets[0]
    assert loaded.name == original.name
    assert loaded.role == original.role
    assert loaded.description == original.description
    assert loaded.motivations == original.motivations
    assert loaded.voice == original.voice
    assert loaded.arc == original.arc


def test_outline_round_trip(project_root):
    p = Project(project_root, "novel")
    p.create("x")
    outline = Outline(
        premise="Test premise.",
        act_structure="Three-act rise-crisis-resolution.",
        chapters=[
            Chapter(number=1, title="Opening", synopsis="Stuff happens.",
                    beats=[Beat(summary="A", purpose="B"), Beat(summary="C")]),
            Chapter(number=2, title="Middle", synopsis="More stuff.",
                    beats=[Beat(summary="D", purpose="E")]),
        ],
    )
    p.write_outline(outline)
    loaded = p.read_outline()
    assert loaded is not None
    assert loaded.premise == outline.premise
    assert loaded.act_structure == outline.act_structure
    assert len(loaded.chapters) == 2
    assert loaded.chapters[0].title == "Opening"
    assert loaded.chapters[0].beats[0].summary == "A"
    assert loaded.chapters[0].beats[0].purpose == "B"
    assert loaded.chapters[0].beats[1].summary == "C"
    assert loaded.chapters[0].beats[1].purpose == ""


def test_facts_append_and_read(project_root):
    p = Project(project_root, "novel")
    p.create("x")
    facts = [
        Fact(chapter=1, kind="event", subject="Lira", statement="She woke."),
        Fact(chapter=1, kind="character_state", subject="Arden", statement="He lies."),
    ]
    p.append_facts(facts)
    p.append_facts([Fact(chapter=2, kind="event", subject="Lira", statement="She left.")])
    loaded = p.read_facts()
    assert len(loaded) == 3
    assert loaded[0].statement == "She woke."
    assert loaded[2].chapter == 2


def test_chapter_count(project_root):
    p = Project(project_root, "novel")
    p.create("x")
    assert p.chapter_count() == 0
    p.write_chapter(1, "prose")
    p.write_chapter(2, "more prose")
    assert p.chapter_count() == 2
