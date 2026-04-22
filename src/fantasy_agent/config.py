"""Load models.yaml and build per-agent backends."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .backends import Backend, make_backend


AGENT_NAMES = ("worldbuilder", "plotter", "character", "writer", "editor", "continuity")


@dataclass
class AgentConfig:
    backend: Backend
    max_tokens: int
    effort: str | None = None
    cache: bool = False
    thinking: bool = False


def load(models_yaml: Path) -> dict[str, AgentConfig]:
    data = yaml.safe_load(models_yaml.read_text()) or {}
    configs: dict[str, AgentConfig] = {}
    for name in AGENT_NAMES:
        spec = data.get(name)
        if not spec:
            raise ValueError(f"models.yaml missing agent: {name}")
        backend = make_backend(spec)
        configs[name] = AgentConfig(
            backend=backend,
            max_tokens=int(spec.get("max_tokens", 4000)),
            effort=spec.get("effort"),
            cache=bool(spec.get("cache", False)),
            thinking=bool(spec.get("thinking", False)),
        )
    return configs
