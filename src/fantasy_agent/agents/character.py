"""Character designer: premise + world + outline → list of CharacterSheet."""
from __future__ import annotations

from ..backends.anthropic import parse_json_response
from ..backends.base import Block, Message
from ..config import AgentConfig
from ..state import CharacterSheet, Outline
from ._common import load_prompt


def run(cfg: AgentConfig, *, premise: str, world: str, outline: Outline) -> list[CharacterSheet]:
    system = [Block(text=load_prompt("character"))]
    chapters_summary = "\n".join(
        f"Ch {c.number}: {c.title} — {c.synopsis}" for c in outline.chapters
    )
    user = (
        f"Premise:\n{premise}\n\n"
        f"World bible:\n{world}\n\n"
        f"Outline:\n{chapters_summary}\n\n"
        "Produce the character JSON."
    )
    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=cfg.max_tokens,
        response_format={"type": "json"},
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    data = parse_json_response(resp.text)
    return [CharacterSheet(**c) for c in data.get("characters", [])]
