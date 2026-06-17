"""Coroutine driver — runs the recursive flow interpreter to quiescence.

A `Driver` drives one or more coroutines (the interpreter, `Runtime._exec_node`)
until every live coroutine is parked on a leaf `Dispatch`, then surfaces those
dispatches as a *frontier* batch. The Runtime materializes each batch into
subagent dispatches; when their results land it `resume()`s the parked
coroutines and drives again.

One Driver runs the *whole* flow: the entry Op's `_exec_node` coroutine is the
interpreter, and Python's own call stack is the control-flow position (no frame
walker). A plain sequence parks one leaf at a time (single-dispatch frontiers);
a `gather()` `fork()`s its branches so their ready leaves surface together as a
batched `dispatch_parallel` round. Joining preserves branch declaration order.

Re-entrant and synchronous: all state lives on the Driver object (stashed on the
Run between MCP round-trips). There is no event loop and no thread — the only
awaitable a flow ever blocks on is `external(Dispatch)`, so "run until quiescent"
is just "drain the ready queue."
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from typing import Any


@dataclass
class Dispatch:
    """One agent *turn* on a leaf Op the interpreter wants to run.

    A leaf's `_run_leaf` loop parks on a fresh `Dispatch` each turn. The first
    turn carries `execution_id=None`; the Runtime materializes an OpExecution
    and writes its id back here (the coroutine keeps the same object), so later
    turns of the same leaf re-dispatch that one execution. `pending_result` /
    `need_supplemental` carry the section injected into a re-dispatch prompt
    (the sub-Op return, or a resolved need). `slot` is assigned by the Driver."""

    op_cls: Any
    value: Any
    bindings: Any = None
    slot: int = -1
    execution_id: Any = None
    pending_result: Any = None
    need_supplemental: Any = None
    depth: int = 0
    caller_execution_id: Any = None


@dataclass
class _Fork:
    """Run these child coroutines concurrently; join their results in order."""

    children: tuple


class _Suspend:
    __slots__ = ("payload",)

    def __init__(self, payload):
        self.payload = payload

    def __await__(self):
        return (yield self.payload)


def external(req: Dispatch):
    """await external(Dispatch(...)) — park until the Runtime resolves it."""
    return _Suspend(req)


def fork(coros):
    """await fork([coro, ...]) — run children concurrently, return results in order."""
    return _Suspend(_Fork(tuple(coros)))


class _Task:
    __slots__ = ("coro", "on_done", "send_value", "throw_exc")

    coro: Any
    on_done: Any
    send_value: Any
    throw_exc: Any

    def __init__(self, coro, on_done):
        self.coro = coro
        self.on_done = on_done
        self.send_value = None
        self.throw_exc = None


class Driver:
    def __init__(self, top_coro):
        self.ready: collections.deque[_Task] = collections.deque()
        self.suspended: dict[int, _Task] = {}
        self.frontier: list[Dispatch] = []
        self._next_slot = 0
        self._box: dict = {}
        # Number of `fork`s (gather rounds) whose branches have not all
        # joined yet. While > 0 the run is mid-gather, so the Runtime
        # batches frontiers into parallel rounds; at 0 the flow is back on
        # its sequential spine and each frontier is a single dispatch.
        self.forks_in_flight = 0
        self.ready.append(_Task(top_coro, self._on_top_done))

    def _on_top_done(self, value, error):
        self._box = {"value": value, "error": error}

    def _new_slot(self) -> int:
        self._next_slot += 1
        return self._next_slot

    def _advance_task(self, task: _Task) -> None:
        try:
            if task.throw_exc is not None:
                exc, task.throw_exc = task.throw_exc, None
                payload = task.coro.throw(exc)
            else:
                payload = task.coro.send(task.send_value)
                task.send_value = None
        except StopIteration as stop:
            task.on_done(stop.value, None)
            return
        except Exception as exc:  # noqa: BLE001 — propagate to parent/top
            task.on_done(None, exc)
            return

        if isinstance(payload, _Fork):
            self._spawn_fork(task, payload.children)
        else:  # a Dispatch
            payload.slot = self._new_slot()
            self.suspended[payload.slot] = task
            self.frontier.append(payload)

    def _spawn_fork(self, parent: _Task, children: tuple) -> None:
        results: list[Any] = [None] * len(children)
        remaining = [len(children)]
        first_error: list[Any] = [None]
        self.forks_in_flight += 1

        def make_done(i):
            def _done(value, error):
                if error is not None and first_error[0] is None:
                    first_error[0] = error
                else:
                    results[i] = value
                remaining[0] -= 1
                if remaining[0] == 0:
                    self.forks_in_flight -= 1
                    if first_error[0] is not None:
                        parent.throw_exc = first_error[0]
                    else:
                        parent.send_value = results
                    self.ready.append(parent)

            return _done

        for i, child in enumerate(children):
            self.ready.append(_Task(child, make_done(i)))

    def drive(self) -> tuple[str, Any]:
        """Run to quiescence. Returns one of:
        ('frontier', [Dispatch, ...]) — leaves parked this round (and cleared),
        ('done', value)               — the top coroutine returned,
        ('error', exc)                — the top coroutine raised.
        """
        while self.ready:
            self._advance_task(self.ready.popleft())
        if self._box:
            if self._box["error"] is not None:
                return ("error", self._box["error"])
            return ("done", self._box["value"])
        batch = self.frontier
        self.frontier = []
        return ("frontier", batch)

    def resume(self, slot: int, value: Any) -> None:
        task = self.suspended.pop(slot)
        task.send_value = value
        self.ready.append(task)

    def resume_error(self, slot: int, exc: BaseException) -> None:
        task = self.suspended.pop(slot)
        task.throw_exc = exc
        self.ready.append(task)
