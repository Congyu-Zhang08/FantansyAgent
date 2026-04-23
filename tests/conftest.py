"""Shared fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from fantasy_agent.config import AgentConfig

from .fake_backend import FakeBackend


@pytest.fixture
def fake_agents() -> dict[str, AgentConfig]:
    """A full agent config dict wired up to the fake backend.

    Each agent gets its OWN FakeBackend instance, so tests can inspect
    per-agent call logs (`fake_agents["writer"].backend.calls`) without
    mixing calls from other agents.
    """
    return {
        name: AgentConfig(backend=FakeBackend(), max_tokens=2000)
        for name in ("worldbuilder", "plotter", "character", "writer", "editor", "continuity")
    }


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return tmp_path
