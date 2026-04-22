"""Summarizer: chapter prose → ~200-word summary.

Routed through the continuity agent's backend for cost reasons — this is
mechanical work that doesn't need Opus or Sonnet.
"""
from __future__ import annotations

from ..backends.base import Block, Message
from ..config import AgentConfig
from ._common import load_prompt


def run(cfg: AgentConfig, *, chapter_number: int, prose: str) -> str:
    system = [Block(text=load_prompt("summarizer"))]
    user = f"Chapter {chapter_number}:\n\n{prose}\n\nSummarize."
    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=500,
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    return resp.text.strip()
