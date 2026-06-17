"""Synthetic reference Op library.

Imports every submodule so the global registry is populated on
`import examples.my_company`.
"""

from examples.my_company import concepts, snippets, tools
from examples.my_company.ops import classify_intent, draft_response, handle_support

__all__ = [
    "concepts",
    "snippets",
    "tools",
    "classify_intent",
    "draft_response",
    "handle_support",
]
