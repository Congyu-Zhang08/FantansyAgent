"""Anthropic backend with prompt caching, adaptive thinking, and effort."""
from __future__ import annotations

import json
from typing import Any

from .base import Block, Message, Response, Usage


_SUPPORTED = {"prompt_caching", "json_schema", "thinking", "effort"}


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, model: str):
        import anthropic  # imported lazily so LiteLLM-only users don't need it
        self.model = model
        self._client = anthropic.Anthropic()

    def supports(self, feature: str) -> bool:
        return feature in _SUPPORTED

    def generate(
        self,
        *,
        system: list[Block],
        messages: list[Message],
        max_tokens: int,
        response_format: dict | None = None,
        effort: str | None = None,
        thinking: bool = False,
    ) -> Response:
        # System blocks: mark the last stable block with cache_control to cache
        # the whole stable prefix (role prompt + world + characters, etc.).
        system_blocks = self._render_system(system)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system_blocks,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }

        output_config: dict[str, Any] = {}
        if effort:
            output_config["effort"] = effort
        if response_format == {"type": "json"}:
            # Nudge Claude to respond with JSON. We don't use strict schema here
            # because each agent validates with pydantic after parsing.
            kwargs["messages"][-1] = {
                "role": "user",
                "content": messages[-1].content + "\n\nRespond with valid JSON only.",
            }
        if output_config:
            kwargs["output_config"] = output_config

        if thinking:
            kwargs["thinking"] = {"type": "adaptive"}

        resp = self._client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")

        usage = resp.usage
        return Response(
            text=text,
            usage=Usage(
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            ),
            raw=resp,
        )

    @staticmethod
    def _render_system(blocks: list[Block]) -> list[dict]:
        """Render system blocks with a cache breakpoint on the last stable one."""
        rendered = [{"type": "text", "text": b.text} for b in blocks]
        # Find the last stable block and put a 1-hour cache_control on it.
        last_stable = -1
        for i, b in enumerate(blocks):
            if b.stable:
                last_stable = i
        if last_stable >= 0:
            rendered[last_stable]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        return rendered


def parse_json_response(text: str) -> dict:
    """Best-effort JSON extraction from a model response."""
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences if present
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Try full parse first, then fall back to the first {...} span.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise
