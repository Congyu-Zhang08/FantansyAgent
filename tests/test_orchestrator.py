"""End-to-end orchestrator test with the fake backend."""
from __future__ import annotations

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
