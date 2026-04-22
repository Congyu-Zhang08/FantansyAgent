"""LiteLLM universal adapter: OpenAI, Gemini, Together, Groq, Ollama, vLLM, etc."""
from __future__ import annotations

from typing import Any

from .base import Block, Message, Response, Usage


class LiteLLMBackend:
    name = "litellm"

    def __init__(self, model: str):
        import litellm  # lazy import
        self._litellm = litellm
        self.model = model

    def supports(self, feature: str) -> bool:
        # Anthropic-specific features become no-ops. JSON mode is widely
        # supported by OpenAI-compatible providers.
        return feature == "json_schema"

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
        # Collapse system blocks into a single system message.
        system_text = "\n\n".join(b.text for b in system if b.text)
        oai_messages = [{"role": "system", "content": system_text}]
        oai_messages += [{"role": m.role, "content": m.content} for m in messages]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
        }
        if response_format == {"type": "json"}:
            kwargs["response_format"] = {"type": "json_object"}

        resp = self._litellm.completion(**kwargs)
        choice = resp.choices[0]
        text = choice.message.content or ""

        usage_obj = getattr(resp, "usage", None) or {}
        get = (lambda k: getattr(usage_obj, k, 0)) if not isinstance(usage_obj, dict) else usage_obj.get
        return Response(
            text=text,
            usage=Usage(
                input_tokens=get("prompt_tokens") or 0,
                output_tokens=get("completion_tokens") or 0,
            ),
            raw=resp,
        )
