# FantansyAgent

Multi-agent LLM system that writes a fantasy novel chapter by chapter. Agents
include Worldbuilder, Plotter, Character designer, Writer, Editor, and
Continuity keeper. A central orchestrator dispatches tasks; all state lives
on disk so runs are resumable.

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env   # then add ANTHROPIC_API_KEY

fantasy-agent init demo \
    --premise "A cartographer discovers her maps redraw themselves overnight."

fantasy-agent write-chapter demo
fantasy-agent write-chapter demo
fantasy-agent status demo
```

Artifacts land under `projects/demo/`:

```
projects/demo/
├── premise.md
├── world.md
├── outline.md
├── characters/<name>.md
├── chapters/NN.md
├── summaries/NN.md         # ~200-word chapter summaries
└── continuity.jsonl        # canonical facts, one per line
```

## Pluggable backends

Every agent routes through a `Backend` protocol. The default `models.yaml`
uses Anthropic, but any agent can be swapped to an OpenAI-compatible provider
(OpenAI, Together, Groq, Fireworks, OpenRouter, Ollama, vLLM, …) by editing
`models.yaml`:

```yaml
writer:
  backend: litellm
  model: together_ai/Qwen/Qwen2.5-72B-Instruct
```

Anthropic-specific features (prompt caching, adaptive thinking, effort) are
feature-probed: they activate on the Anthropic backend and silently no-op on
LiteLLM backends.

## Testing

```bash
pytest tests/   # uses a fake backend; no API key required
```
