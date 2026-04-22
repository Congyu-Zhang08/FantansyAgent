# FantansyAgent

A multi-agent LLM system that drafts a fantasy novel one chapter at a time.
Six specialist agents — **Worldbuilder, Plotter, Character designer, Writer,
Editor, Continuity keeper** — coordinate through a central orchestrator. All
state lives on disk under `projects/<slug>/`, so you can stop and resume
between chapters, hand-edit any artifact, and never lose progress.

The default setup uses Anthropic's Claude models, but every agent goes
through a `Backend` protocol — so you can route any role to OpenAI, Together,
Groq, Ollama, vLLM, etc. by editing one YAML file.

---

## Step-by-step: write your first novel

### 1. Install Python and clone the repo

You need Python 3.10 or newer.

```bash
git clone https://github.com/Congyu-Zhang08/FantansyAgent.git
cd FantansyAgent
```

### 2. Install the project

A virtual environment is recommended but not required.

```bash
python -m venv .venv && source .venv/bin/activate    # optional
pip install -e ".[dev]"
```

### 3. Get an Anthropic API key

1. Sign up at <https://console.anthropic.com/>.
2. Add a small amount of credit ($5 is plenty to write a full novel).
3. Create a key under **Settings → API Keys**.

### 4. Configure your API key

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
```

### 5. Verify the install (no API calls — uses fake data)

```bash
pytest tests/
```

You should see `24 passed`. This proves the wiring works without spending a
cent on the API. If this fails, fix it before continuing.

### 6. Bootstrap a novel project

Pick a slug (a short name for your novel) and a one-sentence premise:

```bash
fantasy-agent init my-novel \
    --premise "A cartographer discovers her maps redraw themselves overnight."
```

This runs three agents in sequence (~1–2 minutes total):

- **Worldbuilder** invents the setting, magic system, cultures.
- **Plotter** turns premise + world into a 12-chapter outline.
- **Character designer** invents 4–6 characters tied to the outline.

When it finishes, look inside `projects/my-novel/`:

```
projects/my-novel/
├── premise.md          # what you typed
├── world.md            # the world bible
├── outline.md          # chapter-by-chapter plan
└── characters/
    ├── lira-venn.md
    ├── arden-scole.md
    └── ...
```

**You can edit any of these files by hand.** The agents will respect your
edits on the next run. If the world feels off, rewrite `world.md`; if a
character is flat, edit their sheet.

### 7. Write your first chapter

```bash
fantasy-agent write-chapter my-novel
```

This runs:

1. **Continuity** filters the canonical-facts log to ~20 facts relevant to
   this chapter (cheap; uses Haiku by default).
2. **Writer** drafts the chapter using only the active characters and
   relevant facts (not the full world bible — saves tokens).
3. The draft is **immediately written to disk** so it can't be lost.
4. **Editor** critiques. If it asks for revisions, the writer rewrites
   (up to 2 rounds).
5. **Continuity** extracts new canonical facts from the final draft.
6. A short summary of the chapter is saved for future chapters to use.

Total time: ~2–4 minutes per chapter. Cost: ~$0.05–$0.20 with the default
config.

Look at `projects/my-novel/chapters/01.md` — that's your chapter.

### 8. Write more chapters

Just run the same command again — it will pick up where you left off:

```bash
fantasy-agent write-chapter my-novel
fantasy-agent write-chapter my-novel
fantasy-agent write-chapter my-novel
```

Each new chapter sees:

- Summaries of all prior chapters (not their full text — keeps cost bounded)
- The canonical facts established so far, filtered to what's relevant
- The tail of the previous chapter (last ~400 words for narrative continuity)

### 9. Check progress

```bash
fantasy-agent status my-novel
```

```
Project: my-novel
  Chapters written: 3 / 12
  Total words: 9,847
  Facts recorded: 28
  Next: Chapter 4 — The Bloodline Revealed
```

### 10. Read the result

Each `chapters/NN.md` is plain Markdown — open in any editor or paste them
together into one document.

---

## Customizing the agents

Open `models.yaml`. Each agent has its own backend, model, token budget, and
optional knobs (`effort`, `cache`, `thinking`). Defaults:

```yaml
worldbuilder: {backend: anthropic, model: claude-sonnet-4-6, effort: high}
plotter:      {backend: anthropic, model: claude-sonnet-4-6, effort: high}
character:    {backend: anthropic, model: claude-sonnet-4-6}
writer:       {backend: anthropic, model: claude-sonnet-4-6, cache: true}
editor:       {backend: anthropic, model: claude-opus-4-7, cache: true, effort: medium}
continuity:   {backend: anthropic, model: claude-haiku-4-5, effort: low}
```

### Switch the writer to a different model

```yaml
writer: {backend: anthropic, model: claude-opus-4-7, cache: true}
```

### Route an agent to an open-source model via Together

Add `TOGETHER_API_KEY=...` to your `.env`, then:

```yaml
writer:
  backend: litellm
  model: together_ai/Qwen/Qwen2.5-72B-Instruct
  max_tokens: 8000
```

### Run entirely locally with Ollama

Install [Ollama](https://ollama.ai/), pull a model (`ollama pull qwen2.5:14b`),
then in `models.yaml`:

```yaml
writer:
  backend: litellm
  model: ollama/qwen2.5:14b
```

LiteLLM speaks ~100 providers; full list at
<https://docs.litellm.ai/docs/providers>.

---

## How robust is it?

Three layers of resilience are built in:

1. **Drafts are persisted before the editor runs.** A crash or malformed
   editor response can't lose the writer's work.
2. **Editor and continuity calls are wrapped in `_safe_call`.** If a model
   returns malformed JSON, we log a warning and fall back to a safe default
   (editor → "approve", continuity → empty fact list) instead of crashing.
3. **All state is on disk.** You can re-run `write-chapter` after any
   failure — it picks up from the last persisted artifact.

Run the test suite to see the failure modes covered:

```bash
pytest tests/test_orchestrator.py -v
```

---

## Project layout

```
src/fantasy_agent/
├── cli.py              # Typer commands: init, write-chapter, status
├── orchestrator.py     # bootstrap() and write_chapter() flow
├── context.py          # per-agent context assembly (the cost lever)
├── state.py            # pydantic models + disk I/O
├── config.py           # loads models.yaml
├── backends/
│   ├── base.py             # Backend protocol
│   ├── anthropic.py        # native SDK with caching, effort, thinking
│   └── litellm_backend.py  # universal adapter
├── agents/             # one module per role; each ~30 lines
└── prompts/            # the role system prompts as editable .md

projects/<slug>/        # gitignored; your novels live here
tests/                  # offline test suite using a fake backend
```

---

## Troubleshooting

**`AuthenticationError` / 401 on the first chapter.** Your API key is wrong
or missing. Check `.env` is in the project root and has no quotes around
the key.

**`json.JSONDecodeError` in the plotter or character designer.** A model
returned malformed JSON for one of the bootstrap agents (these aren't
wrapped in `_safe_call` because there's no good default). Re-run `init`.
If it keeps happening, the model probably isn't strong enough — try switching
that agent to a more capable model in `models.yaml`.

**A chapter is much shorter than expected.** Hit the `max_tokens` cap. Edit
`models.yaml` and bump the writer's `max_tokens` to something larger (16000
is safe; over that, you need streaming, which isn't yet wired in).

**Continuity facts feel off.** Edit `continuity.jsonl` directly — one fact
per line as JSON. Future chapters will use your edits.

**A chapter contradicts an earlier one.** Either (a) the relevant fact
wasn't extracted (add it to `continuity.jsonl` by hand), or (b) it was
extracted but didn't score high enough on the retrieval filter. Re-run the
chapter; if it still drifts, tighten the prose in the prior chapter's
summary file.

**Want to rewrite chapter 3 from scratch.** Delete `chapters/03.md` and
`summaries/03.md`, then `fantasy-agent write-chapter my-novel --chapter 3`.

---

## What this project doesn't do (yet)

- No web UI — CLI only.
- No multi-POV scheduling, no re-plotting after early chapters.
- No vector DB for continuity (keyword filter handles up to ~50k words).
- No parallel agent execution.
- No streaming output — chapters arrive when they're done.

Pull requests welcome.
