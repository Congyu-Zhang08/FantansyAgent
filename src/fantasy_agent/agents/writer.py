"""Writer: WriterContext → chapter prose.

Receives only what it needs: active characters, retrieved facts, previous
chapter tail, prior-chapter summaries. Never the full world bible or all
character sheets.
"""
from __future__ import annotations

from ..backends.base import Block, Message
from ..config import AgentConfig
from ..context import WriterContext
from ._common import load_prompt


def run(cfg: AgentConfig, ctx: WriterContext) -> str:
    # Stable-ish prefix: role prompt + active character cards. We mark these
    # as stable so the Anthropic backend caches them; the editor call next can
    # reuse this prefix if it shares the same character set.
    char_block = _render_characters(ctx.active_characters)
    system = [
        Block(text=load_prompt("writer")),
        Block(text=char_block, stable=True),
    ]

    user = _build_user_turn(ctx)

    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=cfg.max_tokens,
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    return resp.text.strip()


def revise(cfg: AgentConfig, ctx: WriterContext, draft: str, critique_issues: list[str], critique_suggestions: list[str]) -> str:
    char_block = _render_characters(ctx.active_characters)
    system = [
        Block(text=load_prompt("writer")),
        Block(text=char_block, stable=True),
    ]

    user = (
        _build_user_turn(ctx)
        + "\n\n---\n\nPrevious draft:\n"
        + draft
        + "\n\n---\n\nEditor issues to address:\n"
        + "\n".join(f"- {i}" for i in critique_issues)
        + "\n\nEditor suggestions:\n"
        + "\n".join(f"- {s}" for s in critique_suggestions)
        + "\n\nProduce a revised chapter addressing every issue."
    )

    resp = cfg.backend.generate(
        system=system,
        messages=[Message(role="user", content=user)],
        max_tokens=cfg.max_tokens,
        effort=cfg.effort if cfg.backend.supports("effort") else None,
    )
    return resp.text.strip()


def _render_characters(chars) -> str:
    if not chars:
        return "## Active characters\n(none specified)"
    parts = ["## Active characters in this chapter"]
    for c in chars:
        parts.append(
            f"\n### {c.name} ({c.role})\n"
            f"{c.description}\n\n"
            f"**Motivations:** {c.motivations}\n\n"
            f"**Voice:** {c.voice}\n\n"
            f"**Arc:** {c.arc}\n"
        )
    return "\n".join(parts)


def _build_user_turn(ctx: WriterContext) -> str:
    lines = [f"# Chapter {ctx.chapter_number}: {ctx.chapter_title}"]
    lines.append(f"\n## Chapter synopsis\n{ctx.chapter_synopsis}")
    lines.append(f"\n## Beats to cover\n{ctx.beat}")

    if ctx.prior_summaries:
        summary_block = "\n".join(f"Ch {n}: {s}" for n, s in ctx.prior_summaries)
        lines.append(f"\n## Story so far (summaries of prior chapters)\n{summary_block}")

    if ctx.relevant_facts:
        fact_block = "\n".join(
            f"- ({f.kind}, ch {f.chapter}) {f.subject}: {f.statement}"
            for f in ctx.relevant_facts
        )
        lines.append(f"\n## Established facts relevant to this chapter\n{fact_block}")

    if ctx.previous_chapter_tail:
        lines.append(f"\n## Last passage of previous chapter\n{ctx.previous_chapter_tail}")

    lines.append("\n## Task\nDraft this chapter. Cover every beat. Prose only.")
    return "\n".join(lines)
