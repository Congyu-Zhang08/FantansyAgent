"""Fake backend that routes by role keyword in the system prompt.

Keeps tests fully deterministic and offline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from fantasy_agent.backends.base import Block, Message, Response, Usage


@dataclass
class FakeBackend:
    name: str = "fake"
    model: str = "fake-model"
    supported_features: set[str] = field(default_factory=lambda: {"prompt_caching", "json_schema", "effort"})
    calls: list[dict] = field(default_factory=list)

    def supports(self, feature: str) -> bool:
        return feature in self.supported_features

    def generate(self, *, system, messages, max_tokens, response_format=None, effort=None, thinking=False) -> Response:
        system_text = "\n".join(b.text for b in system)
        user_text = messages[-1].content if messages else ""
        self.calls.append({
            "system": system_text,
            "user": user_text,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "effort": effort,
        })
        text = self._route(system_text, user_text)
        return Response(text=text, usage=Usage(input_tokens=100, output_tokens=50))

    def _route(self, system_text: str, user_text: str) -> str:
        # Match on distinctive phrases from each role prompt.
        if "worldbuilder for an original fantasy novel" in system_text:
            return _WORLD_MD
        if "You are a plotter" in system_text:
            return _OUTLINE_JSON
        if "You are a character designer" in system_text:
            return _CHARACTERS_JSON
        if "You are a novelist drafting a chapter" in system_text:
            return _chapter_prose(user_text)
        if "You are a developmental editor" in system_text:
            return _EDITOR_APPROVE_JSON
        if "You are a continuity keeper" in system_text:
            return _continuity_json(user_text)
        if "You are summarizing a chapter" in system_text:
            return "A short summary of the chapter goes here, describing events, character changes, and any unresolved threads."
        return "FAKE RESPONSE"


# --- Canned responses --------------------------------------------------------


_WORLD_MD = """# Setting
A fake world for testing.

## Geography
Mountains in the north, sea in the south.

## Cultures
Two kingdoms, one coastal, one mountain.

## Magic
Magic is rare and tied to blood.

## History
An ancient war is remembered.

## Conflicts
Border tensions simmer.

## Tone
Grounded, a little melancholic.
"""


_OUTLINE_JSON = json.dumps({
    "act_structure": "Three-act rise-crisis-resolution.",
    "chapters": [
        {
            "number": 1,
            "title": "The Redrawn Map",
            "synopsis": "Lira discovers the anomaly.",
            "beats": [
                {"summary": "Lira wakes to a changed map", "purpose": "Inciting incident"},
                {"summary": "She consults her teacher", "purpose": "Establish stakes"},
            ],
        },
        {
            "number": 2,
            "title": "The Bloodline",
            "synopsis": "Lira learns the price of mapcrafting.",
            "beats": [
                {"summary": "Arden reveals the old rule", "purpose": "Raise the cost"},
            ],
        },
    ],
})


_CHARACTERS_JSON = json.dumps({
    "characters": [
        {
            "name": "Lira Venn",
            "role": "protagonist",
            "description": "A cartographer in her late twenties.",
            "motivations": "Wants to understand the anomaly.",
            "voice": "Terse, precise.",
            "arc": "From curiosity to conviction.",
        },
        {
            "name": "Arden Scole",
            "role": "supporting",
            "description": "Lira's mentor.",
            "motivations": "Protects old knowledge.",
            "voice": "Warm, evasive.",
            "arc": "Comes clean.",
        },
        {
            "name": "The Bailiff",
            "role": "antagonist",
            "description": "A crown official.",
            "motivations": "Confiscate dangerous work.",
            "voice": "Clipped, formal.",
            "arc": "Escalates pressure.",
        },
    ],
})


def _chapter_prose(user_text: str) -> str:
    # Extract the chapter number from the user turn if present.
    header = "Chapter"
    idx = user_text.find(header)
    chap = user_text[idx : idx + 30] if idx >= 0 else "Chapter"
    body = (
        "Lira woke before dawn and saw the coastline had moved in the night. "
        "She pressed her thumb to the paper; the ink was still wet. "
        "Arden had warned her this would happen. She did not yet believe him. "
    )
    # Pad so word counts in tests are realistic.
    return f"{chap}\n\n" + (body * 80)


_EDITOR_APPROVE_JSON = json.dumps({
    "status": "approve",
    "issues": [],
    "suggestions": [],
})


def _continuity_json(user_text: str) -> str:
    # Pull a chapter number back out of the user turn.
    n = 1
    for line in user_text.splitlines():
        if line.lower().startswith("chapter number:"):
            try:
                n = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            break
    return json.dumps({
        "facts": [
            {"chapter": n, "kind": "event", "subject": "Lira",
             "statement": f"Lira discovered the anomaly in chapter {n}."},
            {"chapter": n, "kind": "character_state", "subject": "Arden",
             "statement": f"Arden knows more than he is saying as of chapter {n}."},
        ],
    })
