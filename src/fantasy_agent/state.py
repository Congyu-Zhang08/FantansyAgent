"""Project state: pydantic models and disk I/O."""
from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field


# --- Schemas ------------------------------------------------------------------


class CharacterSheet(BaseModel):
    name: str
    role: str  # protagonist | antagonist | supporting | minor
    description: str
    motivations: str
    voice: str
    arc: str


class Beat(BaseModel):
    """One plot beat within a chapter."""
    summary: str
    purpose: str = ""


class Chapter(BaseModel):
    number: int
    title: str
    synopsis: str
    beats: list[Beat] = Field(default_factory=list)


class Outline(BaseModel):
    premise: str
    act_structure: str = ""
    chapters: list[Chapter]


class Fact(BaseModel):
    """One canonical fact extracted by the continuity agent."""
    chapter: int
    kind: str  # event | character_state | setting | rule | relationship
    subject: str
    statement: str


class Critique(BaseModel):
    status: str  # "approve" | "revise"
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# --- Disk I/O -----------------------------------------------------------------


def _slug_safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "unnamed"


class Project:
    """Directory-backed project state. All reads/writes go through here."""

    def __init__(self, root: Path, slug: str):
        self.root = root
        self.slug = slug
        self.dir = root / "projects" / slug
        self.characters_dir = self.dir / "characters"
        self.chapters_dir = self.dir / "chapters"
        self.summaries_dir = self.dir / "summaries"
        self.continuity_path = self.dir / "continuity.jsonl"

    # --- Lifecycle ---

    def create(self, premise: str) -> None:
        for d in (self.dir, self.characters_dir, self.chapters_dir, self.summaries_dir):
            d.mkdir(parents=True, exist_ok=True)
        (self.dir / "premise.md").write_text(premise.strip() + "\n")
        self.continuity_path.touch(exist_ok=True)

    def exists(self) -> bool:
        return self.dir.exists()

    # --- Premise / world / outline ---

    def read_premise(self) -> str:
        return (self.dir / "premise.md").read_text().strip()

    def write_world(self, text: str) -> None:
        (self.dir / "world.md").write_text(text.strip() + "\n")

    def read_world(self) -> str:
        path = self.dir / "world.md"
        return path.read_text().strip() if path.exists() else ""

    def write_outline(self, outline: Outline) -> None:
        (self.dir / "outline.md").write_text(_outline_to_md(outline))

    def read_outline(self) -> Outline | None:
        path = self.dir / "outline.md"
        if not path.exists():
            return None
        return _outline_from_md(path.read_text())

    # --- Characters ---

    def write_character(self, c: CharacterSheet) -> None:
        path = self.characters_dir / f"{_slug_safe(c.name)}.md"
        path.write_text(_character_to_md(c))

    def read_characters(self) -> list[CharacterSheet]:
        sheets = []
        for p in sorted(self.characters_dir.glob("*.md")):
            sheets.append(_character_from_md(p.read_text()))
        return sheets

    # --- Chapters & summaries ---

    def write_chapter(self, n: int, prose: str) -> None:
        (self.chapters_dir / f"{n:02d}.md").write_text(prose.rstrip() + "\n")

    def read_chapter(self, n: int) -> str | None:
        path = self.chapters_dir / f"{n:02d}.md"
        return path.read_text() if path.exists() else None

    def chapter_count(self) -> int:
        return len(list(self.chapters_dir.glob("*.md")))

    def write_summary(self, n: int, summary: str) -> None:
        (self.summaries_dir / f"{n:02d}.md").write_text(summary.strip() + "\n")

    def read_summaries(self) -> list[tuple[int, str]]:
        out = []
        for p in sorted(self.summaries_dir.glob("*.md")):
            n = int(p.stem)
            out.append((n, p.read_text().strip()))
        return out

    # --- Continuity facts (append-only JSONL) ---

    def append_facts(self, facts: list[Fact]) -> None:
        with self.continuity_path.open("a") as f:
            for fact in facts:
                f.write(fact.model_dump_json() + "\n")

    def remove_facts_for_chapter(self, chapter_number: int) -> None:
        """Drop every fact tagged with `chapter_number` from continuity.jsonl.

        Used when re-indexing a single chapter whose prose changed, so stale
        facts from the pre-edit version are cleared before the new extraction
        appends replacements. Other chapters' facts are left untouched.
        """
        if not self.continuity_path.exists():
            return
        kept = [f for f in self.read_facts() if f.chapter != chapter_number]
        body = "\n".join(f.model_dump_json() for f in kept)
        self.continuity_path.write_text(body + ("\n" if kept else ""))

    def read_facts(self) -> list[Fact]:
        if not self.continuity_path.exists():
            return []
        out = []
        for line in self.continuity_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(Fact(**json.loads(line)))
        return out


# --- Markdown serialization ---------------------------------------------------


def _character_to_md(c: CharacterSheet) -> str:
    return (
        f"# {c.name}\n\n"
        f"**Role:** {c.role}\n\n"
        f"## Description\n{c.description}\n\n"
        f"## Motivations\n{c.motivations}\n\n"
        f"## Voice\n{c.voice}\n\n"
        f"## Arc\n{c.arc}\n"
    )


def _character_from_md(text: str) -> CharacterSheet:
    """Parse a character sheet from markdown.

    Strict path: H1 for name, `**Role:**` line, H2 sections for Description,
    Motivations, Voice, Arc. This is what `_character_to_md` writes.

    Fallback for user-provided files: if no H2 sections are found, the
    entire body below the H1 (minus the Role line) goes into `description`,
    with empty strings for the other fields. Lets users bring loose
    character docs without having to restructure them.
    """
    sections = _parse_sections(text)
    name = sections.get("_title", "Unknown")
    role_match = re.search(r"\*\*Role:\*\*\s*(.+)", text)
    role = role_match.group(1).strip() if role_match else "supporting"

    structured_keys = {"Description", "Motivations", "Voice", "Arc"}
    has_structured = bool(structured_keys & set(sections.keys()))
    if has_structured:
        return CharacterSheet(
            name=name,
            role=role,
            description=sections.get("Description", "").strip(),
            motivations=sections.get("Motivations", "").strip(),
            voice=sections.get("Voice", "").strip(),
            arc=sections.get("Arc", "").strip(),
        )

    # Loose fallback: strip the H1 line and the Role line; use the rest as prose.
    body = re.sub(r"^#\s+.+\n", "", text, count=1)
    body = re.sub(r"\*\*Role:\*\*\s*.+\n?", "", body, count=1)
    return CharacterSheet(
        name=name,
        role=role,
        description=body.strip(),
        motivations="",
        voice="",
        arc="",
    )


def _outline_to_md(o: Outline) -> str:
    lines = [f"# Outline\n\n## Premise\n{o.premise}\n"]
    if o.act_structure:
        lines.append(f"\n## Act Structure\n{o.act_structure}\n")
    lines.append("\n## Chapters\n")
    for ch in o.chapters:
        lines.append(f"\n### Chapter {ch.number}: {ch.title}\n")
        lines.append(f"{ch.synopsis}\n")
        if ch.beats:
            lines.append("\n**Beats:**\n")
            for b in ch.beats:
                suffix = f" — {b.purpose}" if b.purpose else ""
                lines.append(f"- {b.summary}{suffix}\n")
    return "".join(lines)


def _outline_from_md(text: str) -> Outline:
    premise_match = re.search(r"##\s*Premise\s*\n(.+?)(?=\n##|\Z)", text, re.S)
    act_match = re.search(r"##\s*Act Structure\s*\n(.+?)(?=\n##|\Z)", text, re.S)
    chapters = []
    for m in re.finditer(
        r"###\s*Chapter\s*(\d+):\s*(.+?)\n(.*?)(?=\n###|\Z)", text, re.S
    ):
        num = int(m.group(1))
        title = m.group(2).strip()
        body = m.group(3).strip()
        syn, _, beats_block = body.partition("**Beats:**")
        beats = []
        for line in beats_block.splitlines():
            line = line.strip()
            if line.startswith("- "):
                item = line[2:]
                if " — " in item:
                    summary, purpose = item.split(" — ", 1)
                else:
                    summary, purpose = item, ""
                beats.append(Beat(summary=summary.strip(), purpose=purpose.strip()))
        chapters.append(Chapter(number=num, title=title, synopsis=syn.strip(), beats=beats))
    return Outline(
        premise=premise_match.group(1).strip() if premise_match else "",
        act_structure=act_match.group(1).strip() if act_match else "",
        chapters=chapters,
    )


def _parse_sections(text: str) -> dict[str, str]:
    """Split a markdown doc into its H2 sections, with '_title' for the H1."""
    sections: dict[str, str] = {}
    title = re.match(r"#\s+(.+)", text)
    if title:
        sections["_title"] = title.group(1).strip()
    for m in re.finditer(r"##\s+(.+?)\n(.*?)(?=\n##|\Z)", text, re.S):
        sections[m.group(1).strip()] = m.group(2).strip()
    return sections
