"""Backend protocol and feature probe tests."""
from __future__ import annotations

from fantasy_agent.backends.base import Backend, Block, Message

from .fake_backend import FakeBackend


def test_fake_backend_satisfies_protocol():
    b = FakeBackend()
    assert isinstance(b, Backend)


def test_feature_probing():
    b = FakeBackend()
    assert b.supports("prompt_caching")
    assert b.supports("json_schema")
    assert not b.supports("nonexistent_feature")


def test_generate_records_calls():
    b = FakeBackend()
    resp = b.generate(
        system=[Block(text="You are a plotter", stable=True)],
        messages=[Message(role="user", content="premise")],
        max_tokens=1000,
        response_format={"type": "json"},
        effort="medium",
    )
    assert b.calls[0]["max_tokens"] == 1000
    assert b.calls[0]["effort"] == "medium"
    assert b.calls[0]["response_format"] == {"type": "json"}
    assert resp.text  # got something back


def test_anthropic_feature_set():
    """The Anthropic backend claims the features we rely on."""
    from fantasy_agent.backends.anthropic import _SUPPORTED
    assert "prompt_caching" in _SUPPORTED
    assert "effort" in _SUPPORTED
    assert "thinking" in _SUPPORTED
    assert "json_schema" in _SUPPORTED


def test_anthropic_renders_cache_breakpoint_on_last_stable_block():
    from fantasy_agent.backends.anthropic import AnthropicBackend

    # We don't instantiate the real client; just test the static render.
    blocks = [
        Block(text="role prompt"),
        Block(text="world bible", stable=True),
        Block(text="character sheets", stable=True),
    ]
    rendered = AnthropicBackend._render_system(blocks)
    # Only the last stable block gets cache_control.
    assert "cache_control" not in rendered[0]
    assert "cache_control" not in rendered[1]
    assert rendered[2]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_parse_json_handles_fences():
    from fantasy_agent.backends.anthropic import parse_json_response

    assert parse_json_response('{"a": 1}') == {"a": 1}
    assert parse_json_response('```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_json_response('sure: {"a": 3} end') == {"a": 3}
