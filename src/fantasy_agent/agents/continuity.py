"""Continuity: chapter prose → list of Fact."""
from __future__ import annotations

from ..backends.anthropic import parse_json_response
from ..backends.base import Block, Message
from ..config import AgentConfig
from ..context import ContinuityContext
from ..state import Fact
from ._common import load_prompt


def run(cfg: AgentConfig, ctx: ContinuityContext) -> list[Fact]:
    system = [Block(text=load_prompt("continuity"))]
    user = (
        f"Chapter number: {ctx.chapter_number}\n\n"
        f"Prose:\n{ctx.prose}\n\n"
        "Extract the facts JSON."
    )
    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=cfg.max_tokens,
        response_format={"type": "json"},
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    data = parse_json_response(resp.text)
    facts: list[Fact] = []
    for raw in data.get("facts", []):
        try:
            facts.append(Fact(**{**raw, "chapter": raw.get("chapter", ctx.chapter_number)}))
        except Exception:
            continue  # skip malformed entries silently
    return facts
