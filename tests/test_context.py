"""Context scoping: the writer must NOT receive the world bible or inactive characters."""
from __future__ import annotations

from fantasy_agent.context import (
    active_characters,
    build_writer_context,
    retrieve_facts,
)
from fantasy_agent.state import Beat, Chapter, CharacterSheet, Fact, Outline, Project


def _seed_project(root):
    p = Project(root, "novel")
    p.create("A test premise.")
    p.write_world("A vast world bible that must not leak into the writer context. " * 200)
    p.write_outline(
        Outline(
            premise="A test premise.",
            chapters=[
                Chapter(
                    number=1, title="Ch1", synopsis="Lira acts.",
                    beats=[Beat(summary="Lira does a thing", purpose="start")],
                ),
                Chapter(
                    number=2, title="Ch2", synopsis="More.",
                    beats=[Beat(summary="Lira confronts Arden", purpose="escalate")],
                ),
            ],
        )
    )
    p.write_character(CharacterSheet(name="Lira Venn", role="protagonist",
                                     description="d", motivations="m", voice="v", arc="a"))
    p.write_character(CharacterSheet(name="Arden Scole", role="supporting",
                                     description="d", motivations="m", voice="v", arc="a"))
    p.write_character(CharacterSheet(name="Mira Fole", role="minor",
                                     description="d", motivations="m", voice="v", arc="a"))
    return p


def test_writer_context_excludes_inactive_characters(project_root):
    p = _seed_project(project_root)
    ctx = build_writer_context(p, chapter_number=1)
    names = [c.name for c in ctx.active_characters]
    assert "Lira Venn" in names
    # Mira is minor and not named in the beat, should not be active.
    assert "Mira Fole" not in names


def test_writer_context_includes_beat_mentioned_character(project_root):
    p = _seed_project(project_root)
    ctx = build_writer_context(p, chapter_number=2)
    names = [c.name for c in ctx.active_characters]
    assert "Lira Venn" in names
    assert "Arden Scole" in names  # mentioned in the beat


def test_active_characters_falls_back_to_protagonists():
    chars = [
        CharacterSheet(name="Lira", role="protagonist", description="d", motivations="m", voice="v", arc="a"),
        CharacterSheet(name="Bob", role="minor", description="d", motivations="m", voice="v", arc="a"),
    ]
    active = active_characters(chars, "a beat mentioning nobody specific")
    assert [c.name for c in active] == ["Lira"]


def test_retrieve_facts_prefers_character_mention():
    facts = [
        Fact(chapter=1, kind="event", subject="Lira", statement="Lira left the capital."),
        Fact(chapter=1, kind="event", subject="Weather", statement="It rained."),
        Fact(chapter=1, kind="event", subject="Arden", statement="Arden wrote a letter."),
    ]
    result = retrieve_facts(facts, beat="Lira confronts Arden", character_names=["Lira", "Arden"], k=2)
    assert len(result) == 2
    subjects = {f.subject for f in result}
    assert subjects == {"Lira", "Arden"}


def test_previous_chapter_tail_truncated(project_root):
    p = _seed_project(project_root)
    # Write a very long chapter 1 to make sure only a tail is returned.
    long_prose = " ".join([f"word{i}" for i in range(5000)])
    p.write_chapter(1, long_prose)
    ctx = build_writer_context(p, chapter_number=2)
    assert ctx.previous_chapter_tail != ""
    # The tail should be well under the original length.
    assert len(ctx.previous_chapter_tail.split()) < 500
