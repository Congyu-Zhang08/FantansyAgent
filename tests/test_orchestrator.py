"""End-to-end orchestrator test with the fake backend."""
from __future__ import annotations

import pytest

from fantasy_agent import orchestrator
from fantasy_agent.state import Project


def test_bootstrap_produces_world_outline_characters(fake_agents, project_root):
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "A test premise.")

    assert (project.dir / "world.md").read_text().strip() != ""
    outline = project.read_outline()
    assert outline is not None
    assert len(outline.chapters) >= 2
    characters = project.read_characters()
    assert len(characters) >= 2
    assert any(c.role == "protagonist" for c in characters)


def test_write_chapter_end_to_end(fake_agents, project_root):
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "A test premise.")

    prose = orchestrator.write_chapter(project, fake_agents, 1)

    # Chapter, summary, and facts all land on disk.
    assert project.read_chapter(1) is not None
    summaries = project.read_summaries()
    assert len(summaries) == 1 and summaries[0][0] == 1
    facts = project.read_facts()
    assert len(facts) >= 1
    assert len(prose.split()) > 100


def test_writer_context_does_not_contain_world_bible(fake_agents, project_root):
    """The one that really matters: the writer never sees the full world bible."""
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "A test premise.")

    fake = fake_agents["writer"].backend
    fake.calls.clear()

    orchestrator.write_chapter(project, fake_agents, 1, max_revisions=0)

    writer_calls = [
        c for c in fake.calls
        if "You are a novelist drafting a chapter" in c["system"]
    ]
    assert writer_calls, "expected at least one writer call"

    world_text = project.read_world()
    for call in writer_calls:
        combined = call["system"] + call["user"]
        # The world bible should never have leaked into the writer's turn.
        assert world_text not in combined, "world bible leaked into writer context"


def test_second_chapter_uses_prior_summary(fake_agents, project_root):
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "A test premise.")
    orchestrator.write_chapter(project, fake_agents, 1, max_revisions=0)

    fake = fake_agents["writer"].backend
    fake.calls.clear()

    orchestrator.write_chapter(project, fake_agents, 2, max_revisions=0)

    writer_calls = [
        c for c in fake.calls
        if "You are a novelist drafting a chapter" in c["system"]
    ]
    assert writer_calls
    # Chapter 2's writer turn should reference the chapter 1 summary block.
    assert any("Story so far" in c["user"] for c in writer_calls)


def test_next_chapter_number(fake_agents, project_root):
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "x")
    assert orchestrator.next_chapter_number(project) == 1
    orchestrator.write_chapter(project, fake_agents, 1, max_revisions=0)
    assert orchestrator.next_chapter_number(project) == 2


# --- Failure-mode tests ------------------------------------------------------


def _patch_route(fake, predicate, replacement):
    """Override the fake's _route to substitute a response when predicate matches."""
    original = fake._route

    def patched(system_text, user_text):
        if predicate(system_text):
            return replacement
        return original(system_text, user_text)

    fake._route = patched


def test_write_chapter_recovers_from_broken_editor_json(fake_agents, project_root):
    """If the editor returns garbage, we fall back to approve and keep going."""
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "A test premise.")

    # Make the editor return something that is not JSON at all.
    _patch_route(
        fake_agents["editor"].backend,
        lambda s: "You are a developmental editor" in s,
        "Sure! Here's my critique: this draft is fantastic.",
    )

    # Should not raise.
    prose = orchestrator.write_chapter(project, fake_agents, 1, max_revisions=2)

    assert project.read_chapter(1) is not None
    assert len(prose.split()) > 100
    # Continuity + summary still ran.
    assert project.read_summaries()
    assert project.read_facts()


def test_write_chapter_recovers_from_broken_continuity_json(fake_agents, project_root):
    """If the continuity agent returns garbage, the chapter is still saved."""
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "A test premise.")

    _patch_route(
        fake_agents["continuity"].backend,
        lambda s: "You are a continuity keeper" in s,
        "I cannot extract facts right now.",
    )

    orchestrator.write_chapter(project, fake_agents, 1, max_revisions=0)

    assert project.read_chapter(1) is not None
    assert project.read_facts() == []  # graceful empty, not a crash


def test_draft_persisted_before_editor_runs(fake_agents, project_root, monkeypatch):
    """If the editor crashes hard, the writer's draft is already on disk."""
    project = Project(project_root, "demo")
    orchestrator.bootstrap(project, fake_agents, "A test premise.")

    fake_editor_backend = fake_agents["editor"].backend
    real_generate = fake_editor_backend.generate

    def explode_when_called_as_editor(*, system, **kwargs):
        is_editor = any("You are a developmental editor" in b.text for b in system)
        if is_editor:
            # Verify chapter 1 already exists when editor is invoked.
            assert project.read_chapter(1) is not None, \
                "draft must be persisted before editor runs"
            raise RuntimeError("simulated unrecoverable editor crash")
        return real_generate(system=system, **kwargs)

    monkeypatch.setattr(fake_editor_backend, "generate", explode_when_called_as_editor)

    # _safe_call only catches parse errors; a RuntimeError still propagates.
    with pytest.raises(RuntimeError, match="simulated"):
        orchestrator.write_chapter(project, fake_agents, 1, max_revisions=1)

    # Even though the run failed, the draft survived.
    assert project.read_chapter(1) is not None
