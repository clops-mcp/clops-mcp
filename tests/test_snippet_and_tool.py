import pytest

from clops import Snippet, SnippetRole, Tool
from clops.registry import registry


def test_snippet_registers():
    s = Snippet(id="rule_a", content="do the thing")
    assert registry.snippet("rule_a") is s


def test_snippet_rejects_empty_fields():
    with pytest.raises(ValueError):
        Snippet(id="", content="x")
    with pytest.raises(ValueError):
        Snippet(id="a", content="")


def test_snippet_role_lookup():
    Snippet(id="brand_default", role="brand_voice", content="warm")
    Snippet(id="brand_formal", role="brand_voice", content="formal")
    matches = registry.snippets_with_role("brand_voice")
    assert len(matches) == 2


def test_duplicate_snippet_id_rejected():
    Snippet(id="dup", content="one")
    with pytest.raises(ValueError):
        Snippet(id="dup", content="two")


def test_snippet_role_requires_value():
    with pytest.raises(ValueError):
        SnippetRole("")


def test_tool_registers():
    t = Tool(name="search", description="search stuff")
    assert registry.tool("search") is t


def test_tool_rejects_empty_fields():
    with pytest.raises(ValueError):
        Tool(name="", description="x")
    with pytest.raises(ValueError):
        Tool(name="a", description="")
