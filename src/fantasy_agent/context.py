"""Per-agent context assembly.

Each role gets only what it needs — this is the single largest token lever.
Agents are stateless; all shared memory lives in Project.
"""
from __future__ import annotations

from dataclasses import dataclass

from .state import Chapter, CharacterSheet, Fact, Project


@dataclass
class WriterContext:
    beat: str
    chapter_number: int
    chapter_title: str
    chapter_synopsis: str
    active_characters: list[CharacterSheet]
    relevant_facts: list[Fact]
    previous_chapter_tail: str  # last ~400 words of the prior chapter
    prior_summaries: list[tuple[int, str]]  # all chapters before this one


@dataclass
class EditorContext:
    draft: str
    beat: str
    chapter_number: int


@dataclass
class ContinuityContext:
    chapter_number: int
    prose: str


@dataclass
class PlotterContext:
    premise: str
    world: str
    character_names: list[str]
    existing_chapters: list[Chapter]  # so re-plotting doesn't forget prior beats


# --- Retrieval / filtering ---------------------------------------------------


def retrieve_facts(facts: list[Fact], beat: str, character_names: list[str], k: int = 20) -> list[Fact]:
    """Filter continuity facts to those relevant to the current beat.

    Ranked by: character mention, keyword overlap with beat, recency.
    """
    if not facts:
        return []

    beat_lower = beat.lower()
    beat_words = {w for w in _tokenize(beat_lower) if len(w) > 3}
    char_set = {c.lower() for c in character_names}

    scored: list[tuple[float, Fact]] = []
    max_chapter = max(f.chapter for f in facts)
    for f in facts:
        score = 0.0
        subject_lower = f.subject.lower()
        statement_lower = f.statement.lower()
        # Character mention in subject is a strong signal.
        if any(c in subject_lower for c in char_set):
            score += 3.0
        # Keyword overlap with the beat.
        fact_words = set(_tokenize(statement_lower))
        score += len(beat_words & fact_words) * 1.0
        # Recency: more recent facts break ties.
        score += 0.1 * (f.chapter / max(max_chapter, 1))
        scored.append((score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for s, f in scored[:k] if s > 0][:k] or facts[-k:]


def active_characters(chars: list[CharacterSheet], beat: str) -> list[CharacterSheet]:
    """Return character sheets mentioned by name in the beat, plus protagonists."""
    beat_lower = beat.lower()
    active: list[CharacterSheet] = []
    for c in chars:
        name_lower = c.name.lower()
        first_name = name_lower.split()[0] if name_lower else ""
        if (name_lower in beat_lower) or (first_name and first_name in beat_lower):
            active.append(c)
        elif c.role.lower() in ("protagonist", "antagonist"):
            active.append(c)
    # If nothing matched, fall back to protagonists + antagonists only.
    if not active:
        active = [c for c in chars if c.role.lower() in ("protagonist", "antagonist")]
    return active


def _tokenize(text: str) -> list[str]:
    out, cur = [], []
    for ch in text:
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    return out


# --- Builders ----------------------------------------------------------------


def build_writer_context(project: Project, chapter_number: int) -> WriterContext:
    outline = project.read_outline()
    if outline is None:
        raise ValueError("No outline found. Run `init` first.")
    chapter = _find_chapter(outline.chapters, chapter_number)
    beat = "\n".join(f"- {b.summary}" for b in chapter.beats) or chapter.synopsis

    chars = project.read_characters()
    active = active_characters(chars, beat)

    facts = project.read_facts()
    relevant = retrieve_facts(facts, beat, [c.name for c in chars])

    tail = ""
    if chapter_number > 1:
        prior = project.read_chapter(chapter_number - 1) or ""
        tail = _tail(prior, words=400)

    return WriterContext(
        beat=beat,
        chapter_number=chapter_number,
        chapter_title=chapter.title,
        chapter_synopsis=chapter.synopsis,
        active_characters=active,
        relevant_facts=relevant,
        previous_chapter_tail=tail,
        prior_summaries=[(n, s) for n, s in project.read_summaries() if n < chapter_number],
    )


def build_editor_context(project: Project, chapter_number: int, draft: str) -> EditorContext:
    outline = project.read_outline()
    if outline is None:
        raise ValueError("No outline found.")
    chapter = _find_chapter(outline.chapters, chapter_number)
    beat = "\n".join(f"- {b.summary}" for b in chapter.beats) or chapter.synopsis
    return EditorContext(draft=draft, beat=beat, chapter_number=chapter_number)


def build_continuity_context(chapter_number: int, prose: str) -> ContinuityContext:
    return ContinuityContext(chapter_number=chapter_number, prose=prose)


def build_plotter_context(project: Project) -> PlotterContext:
    premise = project.read_premise()
    world = project.read_world()
    chars = project.read_characters()
    existing = project.read_outline().chapters if project.read_outline() else []
    return PlotterContext(
        premise=premise,
        world=world,
        character_names=[c.name for c in chars],
        existing_chapters=existing,
    )


def _find_chapter(chapters: list[Chapter], n: int) -> Chapter:
    for ch in chapters:
        if ch.number == n:
            return ch
    raise ValueError(f"Chapter {n} not in outline (have {len(chapters)} chapters).")


def _tail(text: str, words: int) -> str:
    tokens = text.split()
    if len(tokens) <= words:
        return text
    return "… " + " ".join(tokens[-words:])
