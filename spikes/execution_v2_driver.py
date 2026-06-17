"""Execution Model v2 — bridge spike.

Proves the thesis in docs/execution-model-v2.md: keep the combinator DSL, swap
the hand-rolled `_advance` trampoline for a tiny recursive async interpreter
riding a custom coroutine driver.

What this demonstrates, against the REAL `clops` combinators + Op classes:
  - Issue #1: a `branch_on` arm that is a bare `sequence(gather(...), Op)` runs.
  - Issue #3: `gather()` of composition Ops (each a multi-step `sequence`) runs,
    including a nested `gather` inside one parallel track.
  - The "frontier" is emergent: composite tracks dispatch their own next steps
    as they progress, so the driver sees 1..N concurrent dispatches per round.
  - Out-of-order completion (the sim resolves each frontier in reverse).
  - Exception injection: a failed subagent `.throw()`s into its coroutine and
    propagates through the gather exactly like a normal Python exception.

No MCP, no asyncio — the whole point is that the driver is ~90 lines and we own
.send()/.throw() (the determinism the durability/replay story needs).

Run:  .venv/bin/python spikes/execution_v2_driver.py
"""

from __future__ import annotations

import collections
from dataclasses import dataclass

from clops import Concept, Op, branch_on, gather, sequence
from clops.combinators import BoundOp, BranchOn, Gather, Loop, Sequence

# --------------------------------------------------------------------------
# The bridge: one suspension primitive. Dispatch is one request kind.
# --------------------------------------------------------------------------


@dataclass
class Dispatch:
    """A leaf Op wants to run as a subagent. `id` is stamped by the driver
    in traversal order (the deterministic id the replay story relies on)."""

    op_name: str
    value: object
    bindings: object = None
    id: int = -1


@dataclass
class _Fork:
    """gather → run these child coroutines concurrently, join their results."""

    children: tuple


class _Suspend:
    def __init__(self, payload):
        self.payload = payload

    def __await__(self):
        return (yield self.payload)


def external(req):
    """await external(Dispatch(...)) — park until the driver resolves it."""
    return _Suspend(req)


def fork(coros):
    return _Suspend(_Fork(tuple(coros)))


# --------------------------------------------------------------------------
# The interpreter — the whole thing. Replaces Runtime._advance.
# --------------------------------------------------------------------------


async def exec_node(node, value):
    if isinstance(node, type) and issubclass(node, Op):
        if node.is_leaf():
            return await external(Dispatch(node.__name__, value))
        return await exec_node(node.body, value)  # composition Op → run its body

    if isinstance(node, BoundOp):
        return await external(Dispatch(node.op_cls.__name__, value, node.bindings))

    if isinstance(node, Sequence):
        for step in node.steps:
            value = await exec_node(step, value)
        return value

    if isinstance(node, BranchOn):
        key = node.key(value)
        if key not in node.arms:
            raise RuntimeError(f"no arm for branch key {key!r}")
        return await exec_node(node.arms[key], value)  # arm may be a bare combinator

    if isinstance(node, Gather):
        return await fork([exec_node(b, value) for b in node.branches])

    if isinstance(node, Loop):
        it = 0
        while not node.until(value):
            if it >= node.max_iterations:
                raise RuntimeError("loop exceeded max_iterations")
            value = await exec_node(node.body, value)
            it += 1
        return value

    raise RuntimeError(f"unsupported node: {node!r}")


# --------------------------------------------------------------------------
# The custom driver — run-until-quiescent, surface a frontier, resume.
# --------------------------------------------------------------------------


class _Task:
    __slots__ = ("coro", "on_done", "send_value", "throw_exc")

    def __init__(self, coro, on_done):
        self.coro = coro
        self.on_done = on_done
        self.send_value = None
        self.throw_exc = None


class Driver:
    def __init__(self, main_sim):
        self.main_sim = main_sim
        self.ready = collections.deque()
        self.suspended = {}  # dispatch id -> parked task
        self.frontier = []  # (id, Dispatch) parked since last quiescence
        self._next_id = 0
        self.max_concurrency = 0

    def _advance(self, task):
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
        except Exception as exc:  # the coroutine raised — hand it to its parent
            task.on_done(None, exc)
            return

        if isinstance(payload, _Fork):
            self._spawn_fork(task, payload.children)
        else:  # a Dispatch (or any future external-request kind)
            payload.id = self._new_id()
            self.suspended[payload.id] = task
            self.frontier.append((payload.id, payload))

    def _spawn_fork(self, parent, children):
        results = [None] * len(children)
        remaining = [len(children)]
        first_error = [None]

        def make_done(i):
            def _done(value, error):
                if error is not None and first_error[0] is None:
                    first_error[0] = error
                else:
                    results[i] = value
                remaining[0] -= 1
                if remaining[0] == 0:
                    if first_error[0] is not None:
                        parent.throw_exc = first_error[0]
                    else:
                        parent.send_value = results
                    self.ready.append(parent)

            return _done

        for i, child in enumerate(children):
            self.ready.append(_Task(child, make_done(i)))

    def _new_id(self):
        self._next_id += 1
        return self._next_id

    def run(self, top_coro):
        box = {}
        self.ready.append(_Task(top_coro, lambda v, e: box.update(value=v, error=e)))

        round_no = 0
        while True:
            while self.ready:  # drive everything runnable to quiescence
                self._advance(self.ready.popleft())

            if box:
                if box["error"] is not None:
                    raise box["error"]
                return box["value"]

            if not self.frontier:
                raise RuntimeError("deadlock: quiescent with nothing pending")

            round_no += 1
            frontier, self.frontier = self.frontier, []
            self.max_concurrency = max(self.max_concurrency, len(frontier))
            names = [d.op_name for _, d in frontier]
            print(f"  round {round_no}: {len(frontier)} in flight  {names}")

            for did, dispatch in self.main_sim.order(frontier):  # out-of-order ok
                value, error = self.main_sim.resolve(dispatch)
                task = self.suspended.pop(did)
                if error is not None:
                    task.throw_exc = error
                else:
                    task.send_value = value
                self.ready.append(task)


class MainSim:
    """Stands in for the main thread + subagents."""

    def __init__(self, fail_ops=()):
        self.fail_ops = set(fail_ops)
        self.dispatched = []

    def order(self, frontier):
        return list(reversed(frontier))  # prove resolution order is irrelevant

    def resolve(self, dispatch):
        self.dispatched.append(dispatch.op_name)
        if dispatch.op_name in self.fail_ops:
            return None, RuntimeError(f"subagent {dispatch.op_name!r} failed")
        return f"{dispatch.op_name}->ok", None


# --------------------------------------------------------------------------
# A toy library built from the REAL DSL, exercising both open bugs at once.
# --------------------------------------------------------------------------


class Blob(Concept):
    description = "an opaque value flowing between Ops"


def leaf(name):
    return type(name, (Op,), {
        "Intent": f"{name} does one step.",
        "Meta": f"spike leaf {name}.",
        "Input": Blob,
        "Output": Blob,
    })


def composite(name, body):
    return type(name, (Op,), {
        "Intent": f"{name} composes steps.",
        "Meta": f"spike composition {name}.",
        "Input": Blob,
        "Output": Blob,
        "body": body,
    })


# Issue #1: a branch_on arm that is a bare sequence(gather(...), Op).
Check, Simple = leaf("Check"), leaf("Simple")
OpA, OpB, Assemble = leaf("OpA"), leaf("OpB"), leaf("Assemble")
Branch = branch_on(
    key=lambda upstream: "path_b" if "ok" in str(upstream) else "path_a",
    arms={
        "path_a": Simple,
        "path_b": sequence(gather(OpA, OpB), Assemble),  # <-- fails on main today
    },
)

# Issue #3: gather() of composition Ops, each a multi-step track; one track has
# a nested gather of its own.
SoftTrack = composite("SoftTrack", sequence(leaf("SoftA"), leaf("SoftB"), leaf("SoftC")))
HardTrack = composite("HardTrack", sequence(leaf("HardA"), leaf("HardB")))
DeepTrack = composite("DeepTrack", sequence(leaf("DeepA"), gather(leaf("DeepB"), leaf("DeepC"))))
SecurityGather = gather(SoftTrack, HardTrack, DeepTrack)  # <-- fails on main today

Top = composite("Top", sequence(Check, Branch, SecurityGather, leaf("FinalSynth")))


def _run(label, fail_ops=()):
    print(f"\n=== {label} ===")
    sim = MainSim(fail_ops=fail_ops)
    driver = Driver(sim)
    try:
        output = driver.run(exec_node(Top, {"seed": True}))
        print(f"  DONE. peak concurrency = {driver.max_concurrency}")
        print(f"  output = {output}")
        return True
    except Exception as exc:
        print(f"  RAISED ({type(exc).__name__}): {exc}")
        print(f"  peak concurrency before failure = {driver.max_concurrency}")
        return False


if __name__ == "__main__":
    ok = _run("happy path (both bug scenarios in one flow)")
    failed = _run("fault injection (HardB subagent fails)", fail_ops={"HardB"})

    print("\n--- verdict ---")
    print(f"happy path completed:            {ok}")
    print(f"injected failure propagated:     {not failed}")
    assert ok, "happy path should complete"
    assert not failed, "injected failure should propagate through the gather"
    print("SPIKE PASS: combinator DSL drives unchanged; both bugs structurally gone.")
