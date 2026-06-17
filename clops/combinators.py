"""Composition combinators — return inspectable data structures; do not execute.

In Phase 0 these are pure descriptions of flow shape. The runtime will walk them later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Sequence:
    steps: tuple[Any, ...]


@dataclass(frozen=True)
class BranchOn:
    key: Callable[[Any], Any]
    arms: dict[Any, Any]


@dataclass(frozen=True)
class Gather:
    branches: tuple[Any, ...]


@dataclass(frozen=True)
class Loop:
    body: Any
    until: Callable[[Any], bool]
    max_iterations: int = 10


def sequence(*steps: Any) -> Sequence:
    if not steps:
        raise ValueError("sequence() requires at least one step.")
    return Sequence(steps=tuple(steps))


def branch_on(key: Callable[[Any], Any], arms: dict[Any, Any]) -> BranchOn:
    if not callable(key):
        raise TypeError("branch_on(key=...) must be callable.")
    if not arms:
        raise ValueError("branch_on(arms=...) must be non-empty.")
    return BranchOn(key=key, arms=dict(arms))


def gather(*branches: Any) -> Gather:
    if len(branches) < 2:
        raise ValueError("gather() requires at least two branches.")
    return Gather(branches=tuple(branches))


def loop(body: Any, until: Callable[[Any], bool], max_iterations: int = 10) -> Loop:
    if not callable(until):
        raise TypeError("loop(until=...) must be callable.")
    if max_iterations < 1:
        raise ValueError("loop(max_iterations=...) must be >= 1.")
    return Loop(body=body, until=until, max_iterations=max_iterations)


def walk(node: Any):
    """Yield every Op class referenced by a combinator tree (depth-first)."""
    from clops.op import Op

    if isinstance(node, type) and issubclass(node, Op):
        yield node
        return
    if isinstance(node, Sequence):
        for step in node.steps:
            yield from walk(step)
    elif isinstance(node, BranchOn):
        for arm in node.arms.values():
            yield from walk(arm)
    elif isinstance(node, Gather):
        for branch in node.branches:
            yield from walk(branch)
    elif isinstance(node, Loop):
        yield from walk(node.body)


def describe(node: Any, indent: int = 0):
    """Yield (indent_level, label) tuples describing a combinator tree.

    Used for human-readable renders of an Op's body. Mirrors walk()'s
    shape but includes structural labels (sequence, branch_on, gather,
    loop) — not just the Op classes.
    """
    from clops.op import Op

    if isinstance(node, type) and issubclass(node, Op):
        yield indent, node.__name__
        return
    if isinstance(node, Sequence):
        yield indent, "sequence"
        for step in node.steps:
            yield from describe(step, indent + 1)
        return
    if isinstance(node, BranchOn):
        yield indent, "branch_on"
        for key, arm in node.arms.items():
            yield indent + 1, f"{key!r}:"
            yield from describe(arm, indent + 2)
        return
    if isinstance(node, Gather):
        yield indent, "gather"
        for branch in node.branches:
            yield from describe(branch, indent + 1)
        return
    if isinstance(node, Loop):
        yield indent, f"loop (max_iterations={node.max_iterations})"
        yield from describe(node.body, indent + 1)
        return
    yield indent, repr(node)
