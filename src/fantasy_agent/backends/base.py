"""Backend abstraction.

A backend is anything that can turn (system, messages) into a completion.
Feature-probing via supports() lets agent code request Anthropic-specific
features (prompt caching, effort, adaptive thinking) without branching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


Role = Literal["user", "assistant"]


@dataclass
class Block:
    """One block in a system prompt. Stable blocks can be cached."""
    text: str
    stable: bool = False


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class Response:
    text: str
    usage: Usage = field(default_factory=Usage)
    raw: Any = None


@runtime_checkable
class Backend(Protocol):
    name: str
    model: str

    def generate(
        self,
        *,
        system: list[Block],
        messages: list[Message],
        max_tokens: int,
        response_format: dict | None = None,
        effort: str | None = None,
        thinking: bool = False,
    ) -> Response: ...

    def supports(self, feature: str) -> bool: ...


def make_backend(spec: dict) -> Backend:
    """Construct a backend from a models.yaml entry."""
    backend_name = spec.get("backend", "anthropic")
    if backend_name == "anthropic":
        from .anthropic import AnthropicBackend
        return AnthropicBackend(model=spec["model"])
    if backend_name == "litellm":
        from .litellm_backend import LiteLLMBackend
        return LiteLLMBackend(model=spec["model"])
    raise ValueError(f"Unknown backend: {backend_name}")
