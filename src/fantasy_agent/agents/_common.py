"""Utilities shared by agent modules."""
from __future__ import annotations

from importlib.resources import files


def load_prompt(name: str) -> str:
    """Load a role system prompt from src/fantasy_agent/prompts/."""
    return files("fantasy_agent.prompts").joinpath(f"{name}.md").read_text()
