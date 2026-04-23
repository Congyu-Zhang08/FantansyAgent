"""Parsers for user-provided project materials.

Used by `orchestrator.bootstrap` when the user supplies their own world,
outline, characters, or existing chapters via CLI flags. Keeping the
parsing here keeps the orchestrator readable.
"""
from __future__ import annotations

import re
from pathlib import Path

from .state import CharacterSheet, Outline, _character_from_md, _outline_from_md


class ImportError(Exception):
    """Raised when a user-provided file cannot be parsed into our schemas."""


def resolve_premise(value: str) -> str:
    """If `value` is a path to an existing file, read its text; else treat as literal."""
    path = Path(value)
    if path.is_file():
        return path.read_text().strip()
    return value.strip()


def parse_world_file(path: Path) -> str:
    """World bible is free text — just read and return."""
    if not path.is_file():
        raise ImportError(f"world file not found: {path}")
    return path.read_text().strip()


def parse_outline_file(path: Path) -> Outline:
    """Parse a user-provided outline in our markdown format."""
    if not path.is_file():
        raise ImportError(f"outline file not found: {path}")
    text = path.read_text()
    outline = _outline_from_md(text)
    if not outline.chapters:
        raise ImportError(
            f"no chapters parsed from {path}. Expected `### Chapter N: Title` "
            "headings under a `## Chapters` section. See README for format."
        )
    return outline


def parse_characters_path(path: Path) -> list[CharacterSheet]:
    """Parse characters from either a directory of .md files or a single .md.

    Directory: one character per .md file.
    Single file: split by H1 (`# Name`) into one character per H1 section.
    """
    if path.is_dir():
        sheets = []
        for p in sorted(path.glob("*.md")):
            text = p.read_text()
            if not text.strip():
                continue
            sheets.append(_character_from_md(text))
        if not sheets:
            raise ImportError(f"no .md character files found in directory {path}")
        return sheets

    if path.is_file():
        text = path.read_text()
        # Split on H1 headers. Each chunk is "Name\nbody..." after the split.
        parts = re.split(r"^#\s+", text, flags=re.M)
        sheets = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            sheets.append(_character_from_md("# " + part))
        if not sheets:
            raise ImportError(f"no characters parsed from {path} (expected `# Name` sections)")
        return sheets

    raise ImportError(f"characters path not found: {path}")


def discover_chapter_files(path: Path) -> list[tuple[int, Path]]:
    """Find chapter files in a directory and derive their chapter numbers.

    Chapter number is the first run of digits in the filename stem. Files
    without any digits are skipped. Results sorted by chapter number.
    """
    if not path.is_dir():
        raise ImportError(f"chapters directory not found: {path}")
    found: list[tuple[int, Path]] = []
    for p in sorted(path.glob("*.md")):
        m = re.search(r"\d+", p.stem)
        if not m:
            continue
        found.append((int(m.group()), p))
    if not found:
        raise ImportError(
            f"no chapter files with numeric names found in {path}. "
            "Expected filenames like `01.md`, `chapter_01.md`, `ch-1.md`."
        )
    found.sort(key=lambda x: x[0])
    # Warn about duplicates — shouldn't happen but signal clearly if it does.
    seen = set()
    for n, p in found:
        if n in seen:
            raise ImportError(f"duplicate chapter number {n} (file: {p})")
        seen.add(n)
    return found
