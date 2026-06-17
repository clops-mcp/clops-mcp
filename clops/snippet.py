"""Snippet: a reusable content fragment declared inline in Op source."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Snippet:
    id: str
    content: str
    role: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            raise ValueError("Snippet.id must be non-empty.")
        if not self.content:
            raise ValueError(f"Snippet {self.id!r}.content must be non-empty.")
        from clops.registry import registry

        registry.register_snippet(self)


@dataclass(frozen=True)
class SnippetRole:
    """Role-based soft declaration. Resolved at dispatch time from registered snippets."""

    role: str

    def __post_init__(self):
        if not self.role:
            raise ValueError("SnippetRole.role must be non-empty.")
