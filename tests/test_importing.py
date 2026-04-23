"""Tests for parsing user-provided project materials."""
from __future__ import annotations

import pytest

from fantasy_agent.importing import (
    ImportError,
    discover_chapter_files,
    parse_characters_path,
    parse_outline_file,
    parse_world_file,
    resolve_premise,
)


# --- Premise resolution ------------------------------------------------------


def test_resolve_premise_literal_string():
    assert resolve_premise("A simple premise.") == "A simple premise."


def test_resolve_premise_from_file(tmp_path):
    p = tmp_path / "premise.md"
    p.write_text("  A premise from disk.  \n")
    assert resolve_premise(str(p)) == "A premise from disk."


# --- World --------------------------------------------------------------------


def test_parse_world_file(tmp_path):
    p = tmp_path / "world.md"
    p.write_text("# My World\nThe sky is purple.\n")
    assert "purple" in parse_world_file(p)


def test_parse_world_file_missing(tmp_path):
    with pytest.raises(ImportError, match="not found"):
        parse_world_file(tmp_path / "nope.md")


# --- Outline ------------------------------------------------------------------


def test_parse_outline_file(tmp_path):
    p = tmp_path / "outline.md"
    p.write_text(
        "# Outline\n\n"
        "## Premise\nA test premise.\n\n"
        "## Chapters\n\n"
        "### Chapter 1: Start\n"
        "Things begin.\n\n"
        "**Beats:**\n"
        "- Lira wakes — inciting incident\n"
        "- She consults her teacher\n\n"
        "### Chapter 2: Middle\n"
        "Things continue.\n"
    )
    outline = parse_outline_file(p)
    assert outline.premise == "A test premise."
    assert len(outline.chapters) == 2
    assert outline.chapters[0].title == "Start"
    assert len(outline.chapters[0].beats) == 2
    assert outline.chapters[0].beats[0].purpose == "inciting incident"


def test_parse_outline_file_empty_raises(tmp_path):
    p = tmp_path / "outline.md"
    p.write_text("# Outline\n\n## Premise\njust a premise\n")
    with pytest.raises(ImportError, match="no chapters"):
        parse_outline_file(p)


# --- Characters ---------------------------------------------------------------


def test_parse_characters_from_directory(tmp_path):
    d = tmp_path / "chars"
    d.mkdir()
    (d / "lira.md").write_text(
        "# Lira Venn\n\n**Role:** protagonist\n\n"
        "## Description\nA cartographer.\n\n"
        "## Motivations\nTruth.\n\n"
        "## Voice\nTerse.\n\n"
        "## Arc\nGrows.\n"
    )
    (d / "arden.md").write_text(
        "# Arden Scole\n\n**Role:** supporting\n\n"
        "## Description\nA mentor.\n"
    )
    sheets = parse_characters_path(d)
    assert len(sheets) == 2
    names = {s.name for s in sheets}
    assert names == {"Lira Venn", "Arden Scole"}


def test_parse_characters_from_single_file_with_h1_sections(tmp_path):
    p = tmp_path / "chars.md"
    p.write_text(
        "# Lira Venn\n**Role:** protagonist\n\n## Description\nA cartographer.\n\n"
        "# Arden Scole\n**Role:** supporting\n\n## Description\nA mentor.\n"
    )
    sheets = parse_characters_path(p)
    assert len(sheets) == 2
    assert {s.name for s in sheets} == {"Lira Venn", "Arden Scole"}


def test_parse_characters_loose_format_falls_back_to_description(tmp_path):
    """A user's character doc without H2 sections should still parse."""
    d = tmp_path / "chars"
    d.mkdir()
    (d / "lira.md").write_text(
        "# Lira Venn\n\n"
        "Lira is a 29-year-old cartographer from Dunmire. She is haunted by "
        "her mother's disappearance and compensates with obsessive precision.\n"
    )
    sheets = parse_characters_path(d)
    assert len(sheets) == 1
    c = sheets[0]
    assert c.name == "Lira Venn"
    assert "cartographer" in c.description
    assert c.motivations == ""  # no H2 Motivations found → empty
    assert c.role == "supporting"  # default when no Role: line


def test_parse_characters_missing_raises(tmp_path):
    with pytest.raises(ImportError):
        parse_characters_path(tmp_path / "nope")


# --- Chapter discovery --------------------------------------------------------


def test_discover_chapter_files_numeric_names(tmp_path):
    d = tmp_path / "chapters"
    d.mkdir()
    (d / "01.md").write_text("ch1")
    (d / "02.md").write_text("ch2")
    (d / "10.md").write_text("ch10")
    found = discover_chapter_files(d)
    assert [n for n, _ in found] == [1, 2, 10]


def test_discover_chapter_files_prefixed_names(tmp_path):
    d = tmp_path / "chapters"
    d.mkdir()
    (d / "chapter_1.md").write_text("ch1")
    (d / "chapter-02.md").write_text("ch2")
    (d / "ch03.md").write_text("ch3")
    found = discover_chapter_files(d)
    assert [n for n, _ in found] == [1, 2, 3]


def test_discover_chapter_files_skips_unnumbered(tmp_path):
    d = tmp_path / "chapters"
    d.mkdir()
    (d / "01.md").write_text("ch1")
    (d / "notes.md").write_text("random notes")
    (d / "02.md").write_text("ch2")
    found = discover_chapter_files(d)
    assert [n for n, _ in found] == [1, 2]


def test_discover_chapter_files_duplicate_numbers_raise(tmp_path):
    d = tmp_path / "chapters"
    d.mkdir()
    (d / "01.md").write_text("ch1")
    (d / "chapter-1.md").write_text("also ch1")
    with pytest.raises(ImportError, match="duplicate chapter number"):
        discover_chapter_files(d)


def test_discover_chapter_files_empty_directory_raises(tmp_path):
    d = tmp_path / "chapters"
    d.mkdir()
    with pytest.raises(ImportError, match="no chapter files"):
        discover_chapter_files(d)
