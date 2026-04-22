"""Plotter: premise + world + character names → structured Outline."""
from __future__ import annotations

from ..backends.anthropic import parse_json_response
from ..backends.base import Block, Message
from ..config import AgentConfig
from ..context import PlotterContext
from ..state import Beat, Chapter, Outline
from ._common import load_prompt


def run(cfg: AgentConfig, ctx: PlotterContext) -> Outline:
    system = [Block(text=load_prompt("plotter"))]

    char_list = ", ".join(ctx.character_names) if ctx.character_names else "(characters to be designed)"
    user = (
        f"Premise:\n{ctx.premise}\n\n"
        f"World bible:\n{ctx.world}\n\n"
        f"Characters: {char_list}\n\n"
        "Produce the outline JSON."
    )

    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=cfg.max_tokens,
        response_format={"type": "json"},
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    data = parse_json_response(resp.text)
    chapters = [
        Chapter(
            number=c["number"],
            title=c["title"],
            synopsis=c.get("synopsis", ""),
            beats=[Beat(**b) for b in c.get("beats", [])],
        )
        for c in data.get("chapters", [])
    ]
    return Outline(
        premise=ctx.premise,
        act_structure=data.get("act_structure", ""),
        chapters=chapters,
    )
