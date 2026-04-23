"""Tests for the edit-in-loop workflow: per-chapter reindex, auto-detect on edit,
--hold, and approve-chapter.

These are the Tier-0 interactions that let a human rewrite AI drafts and have
the system treat the rewrite as canon for future chapters.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from fantasy_agent import orchestrator
from fantasy_agent.state import Fact, Project


# --- Helpers -----------------------------------------------------------------


def _bootstrap(project: Project, fake_agents):
    orchestrator.bootstrap(project, fake_agents, "A test premise.")


def _write_chapter_quietly(project, fake_agents, n, **kwargs):
    """write_chapter with max_revisions=0 so we skip the editor loop in tests."""
    return orchestrator.write_chapter(
        project, fake_agents, n, max_revisions=0, **kwargs
    )


def _set_mtime_ordering(chapter_path: Path, summary_path: Path, chapter_is_newer: bool):
    """Force chapter.mtime vs summary.mtime relationship regardless of FS precision."""
    now = time.time()
    if chapter_is_newer:
        os.utime(summary_path, (now - 100, now - 100))
        os.utime(chapter_path, (now, now))
    else:
        os.utime(chapter_path, (now - 100, now - 100))
        os.utime(summary_path, (now, now))


# --- remove_facts_for_chapter (the Project-level primitive) ------------------


def test_remove_facts_for_chapter_keeps_other_chapters(project_root):
    p = Project(project_root, "novel")
    p.create("x")
    p.append_facts([
        Fact(chapter=1, kind="event", subject="Lira", statement="ch1 event"),
        Fact(chapter=1, kind="event", subject="Lira", statement="ch1 event 2"),
        Fact(chapter=2, kind="event", subject="Arden", statement="ch2 event"),
        Fact(chapter=3, kind="event", subject="Lira", statement="ch3 event"),
    ])

    p.remove_facts_for_chapter(2)

    remaining = p.read_facts()
    assert {f.chapter for f in remaining} == {1, 3}
    assert len(remaining) == 3


def test_remove_facts_for_chapter_is_noop_when_no_matches(project_root):
    p = Project(project_root, "novel")
    p.create("x")
    p.append_facts([Fact(chapter=1, kind="event", subject="L", statement="s")])

    p.remove_facts_for_chapter(99)

    assert len(p.read_facts()) == 1


# --- reindex_chapter ---------------------------------------------------------


def test_reindex_chapter_replaces_facts_and_summary_for_one_chapter_only(
    fake_agents, project_root
):
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    _write_chapter_quietly(project, fake_agents, 1)
    _write_chapter_quietly(project, fake_agents, 2)

    initial_ch1_facts = [f for f in project.read_facts() if f.chapter == 1]
    initial_ch2_facts = [f for f in project.read_facts() if f.chapter == 2]
    initial_ch2_summary = dict(project.read_summaries())[2]
    assert initial_ch1_facts
    assert initial_ch2_facts

    # Rewrite chapter 1 by hand.
    (project.chapters_dir / "01.md").write_text("# Chapter 1\nA completely different chapter.\n")

    orchestrator.reindex_chapter(project, fake_agents, 1)

    # Chapter 1's facts were replaced (same count from fake, but refreshed).
    all_facts = project.read_facts()
    new_ch1_facts = [f for f in all_facts if f.chapter == 1]
    assert new_ch1_facts  # new ones written
    assert len(new_ch1_facts) == len(initial_ch1_facts)  # fake returns 2 each time

    # Chapter 2's facts and summary were NOT touched.
    new_ch2_facts = [f for f in all_facts if f.chapter == 2]
    assert new_ch2_facts == initial_ch2_facts
    assert dict(project.read_summaries())[2] == initial_ch2_summary


# --- Auto-detect on write-chapter --------------------------------------------


def test_auto_sync_reindexes_chapter_whose_mtime_is_newer_than_summary(
    fake_agents, project_root
):
    """The core user-edit path: edit ch1, write ch2, ch1 is auto-reindexed first."""
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    _write_chapter_quietly(project, fake_agents, 1)

    # Simulate a human edit: overwrite chapter 1's file and force its mtime ahead.
    chapter1 = project.chapters_dir / "01.md"
    summary1 = project.summaries_dir / "01.md"
    chapter1.write_text(
        "# Chapter 1\n\nThe heavily revised human version of chapter 1. "
        + "New content here. " * 30
    )
    _set_mtime_ordering(chapter1, summary1, chapter_is_newer=True)

    # Snapshot what the continuity backend has seen so far.
    cont_fake = fake_agents["continuity"].backend
    calls_before = len(cont_fake.calls)

    # Writing chapter 2 should auto-reindex chapter 1 first.
    _write_chapter_quietly(project, fake_agents, 2)

    # The continuity backend should have been called for chapter 1 during
    # the auto-sync (plus chapter 2's own post-write indexing).
    ch1_calls = [
        c for c in cont_fake.calls[calls_before:]
        if "Chapter number: 1" in c["user"]
    ]
    assert ch1_calls, "chapter 1 should have been reindexed by auto-sync"

    # After the sync, summary1 mtime should now be >= chapter1 mtime.
    assert summary1.stat().st_mtime >= chapter1.stat().st_mtime - 1


def test_auto_sync_does_not_reindex_untouched_chapter(fake_agents, project_root):
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    _write_chapter_quietly(project, fake_agents, 1)

    # Force chapter1 mtime BEFORE summary1 mtime (the normal post-write state).
    chapter1 = project.chapters_dir / "01.md"
    summary1 = project.summaries_dir / "01.md"
    _set_mtime_ordering(chapter1, summary1, chapter_is_newer=False)

    cont_fake = fake_agents["continuity"].backend
    calls_before = len(cont_fake.calls)

    _write_chapter_quietly(project, fake_agents, 2)

    # Continuity should have been called ONCE — only for chapter 2.
    new_calls = cont_fake.calls[calls_before:]
    ch1_calls = [c for c in new_calls if "Chapter number: 1" in c["user"]]
    assert not ch1_calls, "chapter 1 should not be reindexed when untouched"


def test_sync_stale_indexes_indexes_a_never_indexed_chapter(fake_agents, project_root):
    """If a chapter file exists without a summary (e.g. from --hold), sync indexes it."""
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    _write_chapter_quietly(project, fake_agents, 1, hold=True)

    assert not (project.summaries_dir / "01.md").exists()

    reindexed = orchestrator.sync_stale_indexes(project, fake_agents, up_to_chapter=2)

    assert reindexed == [1]
    assert (project.summaries_dir / "01.md").exists()


# --- --hold flag -------------------------------------------------------------


def test_hold_skips_indexing(fake_agents, project_root):
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)

    cont_fake = fake_agents["continuity"].backend
    calls_before = len(cont_fake.calls)

    _write_chapter_quietly(project, fake_agents, 1, hold=True)

    # Chapter is on disk, but no summary, no facts.
    assert project.read_chapter(1) is not None
    assert not (project.summaries_dir / "01.md").exists()
    assert project.read_facts() == []

    # Continuity + summarizer were not called for chapter 1.
    ch1_calls = [
        c for c in cont_fake.calls[calls_before:]
        if "Chapter number: 1" in c["user"] or "Chapter 1:" in c["user"]
    ]
    assert not ch1_calls


# --- approve-chapter ---------------------------------------------------------


def test_approve_chapter_indexes_a_held_draft(fake_agents, project_root):
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    _write_chapter_quietly(project, fake_agents, 1, hold=True)

    # User edits.
    (project.chapters_dir / "01.md").write_text("# Chapter 1\nEdited by human.\n")

    orchestrator.approve_chapter(project, fake_agents, 1)

    # Now indexed.
    assert (project.summaries_dir / "01.md").exists()
    facts = [f for f in project.read_facts() if f.chapter == 1]
    assert facts


def test_approve_chapter_replaces_existing_index(fake_agents, project_root):
    """Approving a chapter that was already indexed drops the old facts/summary."""
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    _write_chapter_quietly(project, fake_agents, 1)  # without --hold

    initial_fact_count = len([f for f in project.read_facts() if f.chapter == 1])
    assert initial_fact_count > 0

    # User edits.
    (project.chapters_dir / "01.md").write_text("# Chapter 1\nEdited.\n")

    orchestrator.approve_chapter(project, fake_agents, 1)

    # Count should stay the same (fake returns 2 each time), not double.
    new_fact_count = len([f for f in project.read_facts() if f.chapter == 1])
    assert new_fact_count == initial_fact_count


def test_approve_chapter_errors_on_missing_chapter(fake_agents, project_root):
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    with pytest.raises(ValueError, match="no chapter"):
        orchestrator.approve_chapter(project, fake_agents, 99)


# --- End-to-end: user edits, next chapter uses the edited version -----------


def test_end_to_end_user_edit_propagates_to_next_chapter(fake_agents, project_root):
    """The headline user story: AI drafts ch1, user rewrites ch1, writer ch2
    sees the user's version reflected in its summary input."""
    project = Project(project_root, "novel")
    _bootstrap(project, fake_agents)
    _write_chapter_quietly(project, fake_agents, 1)

    # User rewrites chapter 1.
    chapter1 = project.chapters_dir / "01.md"
    summary1 = project.summaries_dir / "01.md"
    chapter1.write_text(
        "# Chapter 1\n\nThe human's rewrite. Arden is actually an ally here. "
        * 30
    )
    _set_mtime_ordering(chapter1, summary1, chapter_is_newer=True)

    writer_fake = fake_agents["writer"].backend
    writer_fake.calls.clear()

    _write_chapter_quietly(project, fake_agents, 2)

    # Writer's prompt for ch2 should include ch1's summary (which was just
    # rebuilt from the edit). The FakeBackend's summary routing is
    # generic ("A short summary..."), but the key test is that the summary
    # file's mtime is now AFTER the edited chapter's mtime — proving the
    # rebuild happened.
    assert summary1.stat().st_mtime >= chapter1.stat().st_mtime - 1
