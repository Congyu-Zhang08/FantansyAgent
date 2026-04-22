"""Editor: draft + beat → structured Critique."""
from __future__ import annotations

from ..backends.anthropic import parse_json_response
from ..backends.base import Block, Message
from ..config import AgentConfig
from ..context import EditorContext
from ..state import Critique
from ._common import load_prompt


def run(cfg: AgentConfig, ctx: EditorContext) -> Critique:
    system = [Block(text=load_prompt("editor"))]
    user = (
        f"# Chapter {ctx.chapter_number}\n\n"
        f"## Beats the chapter was supposed to cover\n{ctx.beat}\n\n"
        f"## Draft\n{ctx.draft}\n\n"
        "Produce the critique JSON."
    )
    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=cfg.max_tokens,
        response_format={"type": "json"},
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    data = parse_json_response(resp.text)
    status = data.get("status", "approve").lower()
    if status not in ("approve", "revise"):
        status = "approve"
    return Critique(
        status=status,
        issues=list(data.get("issues", [])),
        suggestions=list(data.get("suggestions", [])),
    )
