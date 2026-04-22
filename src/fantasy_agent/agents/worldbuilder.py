"""Worldbuilder: premise → world bible markdown."""
from __future__ import annotations

from ..backends.base import Block, Message
from ..config import AgentConfig
from ._common import load_prompt


def run(cfg: AgentConfig, *, premise: str) -> str:
    system = [Block(text=load_prompt("worldbuilder"))]
    user = f"Premise:\n{premise}\n\nProduce the world bible."
    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=cfg.max_tokens,
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    return resp.text.strip()
