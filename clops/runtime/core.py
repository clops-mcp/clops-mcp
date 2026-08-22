"""Runtime core — the execution surface the MCP server wraps.

Runs are driven by the main thread (`start`, `step_complete`,
`step_complete_parallel`, `resolve_need`) and by subagents (`complete`,
`need`, `call_op`). A Runtime instance is the authoritative state
container for all active runs.

Scope notes:
    - `sequence`, `branch_on`, `gather` and `loop` all execute; `gather`
      surfaces its branches as one `dispatch_parallel` round.
    - `need` does not fail the run. It parks the execution and returns
      `needs_resolution` to the main thread; `resolve_need` re-dispatches
      the same Op with the supplemental attached.
    - Concurrent runs are not prevented, and share the pool.
    - Run state is held in memory for the process's lifetime.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from clops.combinators import BranchOn, Gather, Loop, Sequence, walk
from clops.op import Op
from clops.registry import registry
from clops.runtime.dispatch import build_agent_config
from clops.runtime.driver import Dispatch, Driver, external, fork
from clops.runtime.state import (
    ExecutionStatus,
    OpExecution,
    Run,
    RunStatus,
)


#: Orchestrator guidance applied to every run unless a project overrides it
#: with a `[system_prompt]` section in `.clops`. Kept deliberately small and
#: mechanical: it steers how the main execution flow sizes its dispatches,
#: nothing more. Surfaced verbatim on the first `start_process` payload.
DEFAULT_SYSTEM_PROMPT = (
    "When you dispatch agents, weigh the skill each task demands and "
    "right-size the agent (and its model) to that task — reserve the most "
    "capable agents for the steps that genuinely need them."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RuntimeError_(Exception):
    pass


@dataclass
class Invoke:
    """Turn outcome: the agent issued a dynamic call (call_op). `_run_leaf`
    services it (runs the callee beneath the parked leaf), then re-dispatches
    the leaf with the result. Leaf or composite callee — `_exec_invoke` picks."""

    op_cls: type[Op]
    value: Any
    op_name: str


@dataclass
class NeedResolved:
    """Turn outcome: the main thread resolved a need(). `_run_leaf` re-dispatches
    the same leaf with the supplemental injected into its prompt."""

    supplemental: Any


def _consumes_in_band(node: Any) -> bool:
    """Does ``node``, fed the upstream step's output as its input, consume that
    value *in-band* — i.e. the runtime branches on it, or a loop threads it as
    an accumulator — rather than merely handing it to an agent?

    When True, the upstream step must emit its real ``Output`` value rather than
    a one-line manifest: ``branch_on`` keys and ``loop`` ``until`` predicates run
    on ``str(output)``, and a loop carry must thread the actual accumulator. When
    False, the value is only ever read by another agent, which can pull specifics
    on demand — so a manifest suffices under the manifest output contract.
    """
    if isinstance(node, (BranchOn, Loop)):
        return True
    if isinstance(node, type) and issubclass(node, Op):
        body = getattr(node, "body", None)
        return body is not None and _consumes_in_band(body)
    if isinstance(node, Sequence):
        return bool(node.steps) and _consumes_in_band(node.steps[0])
    return False


class Runtime:
    """Authoritative state container for active runs.

    `session_dispatches` keeps per-parent-session FIFO queues of
    completed-but-unreleased execution ids. The SubagentStop hook consumes
    from these queues to decide whether a subagent's stop is legal.
    """

    def __init__(
        self,
        *,
        hook_endpoint: str | None = None,
        max_subroutine_depth: int = 8,
        max_invokes_per_execution: int = 64,
    ):
        # Dynamic in-Op flow control (call_op) limits. Configurable so a long
        # flow with nested decision sub-Ops has headroom; the budget bounds
        # runaway agent-driven loops (which the loop-stable depth cap does not).
        self._max_subroutine_depth = max_subroutine_depth
        self._max_invokes_per_execution = max_invokes_per_execution
        self._runs: dict[str, Run] = {}
        # execution_id → parent session id (when known; None until first claim)
        self._execution_to_session: dict[str, str] = {}
        # parent session id → FIFO of execution_ids that called complete/need
        # and are awaiting a SubagentStop hook release
        self._session_dispatches: dict[str, deque[str]] = {}
        # Parent session ids we've ever seen on a subagent-facing call.
        # The SubagentStop hook only enforces against known sessions —
        # other subagents in the same Claude Code session (anything that
        # isn't a clops-executor we dispatched) must not be blocked.
        self._known_sessions: set[str] = set()
        self._hook_endpoint = hook_endpoint
        # State stores: one StateManager per run.
        self._state_managers: dict[str, "StateManager"] = {}
        # Project-level constants from .clops [constants] section.
        # Set by the MCP server at boot; injected as read-only stores on each run.
        self._project_constants: dict[str, str] = {}
        # Runtime settings from .clops [runtime] section (set at boot). The
        # `output_contract` key governs the complete() prompt contract:
        #   "full"     (default) — agent serializes its structured Output.
        #   "manifest"           — agent emits a one-line manifest of what it's
        #                          holding; the harness already carries the real
        #                          result, and downstream steps pull specifics on
        #                          demand. The runtime still asks for the real
        #                          value wherever a branch/loop or the run's
        #                          terminal output consumes it in-band.
        self._settings: dict[str, str] = {}
        # Guidance surfaced to the orchestrator at the top of every start()
        # payload as `system_prompt` — standing direction for how the main
        # execution flow manages the run's dispatches (e.g. how to size the
        # agent it dispatches to a task). Defaults to DEFAULT_SYSTEM_PROMPT;
        # a project's .clops [system_prompt] section overrides it at boot.
        # Set to None to suppress the field entirely.
        self._system_prompt: Optional[str] = DEFAULT_SYSTEM_PROMPT

    @property
    def _manifest_mode(self) -> bool:
        return (
            self._settings.get("output_contract", "full").strip().lower()
            == "manifest"
        )

    # ---- Introspection ------------------------------------------------

    def list_processes(self) -> list[dict[str, Any]]:
        """Return only Ops explicitly marked as entry points.

        `entry=True` is the procedure tag — Ops the main thread is
        allowed to invoke. Internal / composition-only Ops are not
        surfaced; they exist to be sub-dispatched, not kicked off.
        """
        return [
            {"name": registry.ref(op), "intent": (op.Intent or "").strip()}
            for op in registry.ops().values()
            if getattr(op, "entry", False)
        ]

    def status(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        return {
            "run_id": run.id,
            "process": run.process,
            "status": run.status.value,
            "output": run.output,
            "error": run.error,
            "pending_executions": sorted(run.pending_executions),
            "executions": [
                {
                    "id": e.id,
                    "op_name": e.op_name,
                    "status": e.status.value,
                    "error": e.error,
                    "need_reason": e.need_reason,
                }
                for e in run.executions.values()
            ],
        }

    def get_run(self, run_id: str) -> Run:
        return self._get_run(run_id)

    # ---- Main-thread API ---------------------------------------------

    def start(self, process: str, input_value: Any, *, enforce_entry: bool = False) -> dict[str, Any]:
        """Start a run.

        When `enforce_entry=True`, only Ops marked `entry=True` can be
        started. The MCP server passes this flag; direct Runtime use
        (tests, internal tooling) defaults to permissive.
        """
        op_cls = registry.op(process)
        if op_cls is None:
            raise RuntimeError_(f"Unknown process {process!r}.")
        if enforce_entry and not getattr(op_cls, "entry", False):
            raise RuntimeError_(
                f"Process {process!r} is not an entry point. Only Ops "
                "declared with `entry = True` are invocable as processes."
            )

        # A bare top-level control combinator has no upstream output to drive
        # its decision; require it be wrapped in a sequence with a seed step.
        body = op_cls.body
        if isinstance(body, BranchOn):
            raise RuntimeError_(
                "Top-level body=branch_on(...) is not supported. "
                "Wrap in sequence(<upstream_op>, branch_on(...))."
            )
        if isinstance(body, Loop):
            raise RuntimeError_(
                "Top-level body=loop(...) is not supported. "
                "Wrap in sequence(<seed_op>, loop(...))."
            )
        if isinstance(body, Gather):
            raise RuntimeError_(
                "Top-level body=gather(...) is not supported. "
                "Wrap in sequence(<seed_op>, gather(...))."
            )

        run = self._make_run(op_cls, process, input_value)
        payload = self._drive(run)
        # Surface the configured system prompt once, at the start of the run,
        # on the first dispatch the orchestrator receives. Purely additive:
        # runs advance via step_complete, which never carries it again.
        if self._system_prompt and payload.get("action") in (
            "dispatch",
            "dispatch_parallel",
        ):
            payload["system_prompt"] = self._system_prompt
        return payload

    def _make_run(self, op_cls: type[Op], process: str, input_value: Any) -> Run:
        """Create and register a Run: its state stores and the single coroutine
        Driver running the Op's interpreter (`_exec_node`)."""
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run = Run(id=run_id, process=process, input=input_value, status=RunStatus.RUNNING)
        self._runs[run_id] = run

        # Initialize state stores for this run.
        stores = self._collect_stores(op_cls)
        if stores or self._project_constants:
            from clops.runtime.state_manager import StateManager

            sm = StateManager(run_id)
            for name, store in stores.items():
                sm.register_store(
                    name, store.kind, store.value_type,
                    custom_queries=store._static_queries or None,
                    custom_methods={
                        k: lambda table, _m=m, _s=store, **kw: _m(_s, table, **kw)
                        for k, m in store._custom_methods.items()
                    } or None,
                )
            # Inject project-level constants as read-only scalar stores.
            for key, value in self._project_constants.items():
                sd = sm.register_store(key, "scalar", str, read_only=True)
                sd._scalar_set(value)
            self._state_managers[run_id] = sm

        # One driver runs the whole flow: the Op's interpreter coroutine. Leaf or
        # composite, it drives to the first quiescence and surfaces the frontier.
        # require_full=True at the root: the run's terminal leaf produces the run
        # output, so it must emit a real value, not a manifest.
        run.driver = Driver(self._exec_node(op_cls, input_value, require_full=True))
        return run

    def step_complete(self, run_id: str, result: Any) -> dict[str, Any]:
        """Main thread reports what the dispatched subagent returned for the one
        leaf on the sequential spine.

        The leaf's turn resolves to one of: a dynamic call (`call_op` fired →
        resume with `Invoke`), a `need` (surface for resolution), a failure, or
        a completion (resume with the output). `_resolve_execution_turn` handles
        all of these; we then drive the flow to its next action.
        """
        run = self._get_run(run_id)
        if run.status != RunStatus.RUNNING:
            raise RuntimeError_(f"Run {run_id} is not running ({run.status}).")
        pending_id = run.single_pending()
        if pending_id is None:
            if not run.pending_executions:
                raise RuntimeError_(f"Run {run_id} has no pending dispatch.")
            raise RuntimeError_(
                f"Run {run_id} has multiple pending dispatches; sequential "
                "step_complete only resolves one at a time (Phase 2)."
            )

        execution = run.get_execution(pending_id)
        terminal = self._resolve_execution_turn(run, execution, result, parallel=False)
        if terminal is not None:
            return terminal
        return self._drive(run)

    def _resolve_execution_turn(
        self, run: Run, execution: OpExecution, result: Any, *, parallel: bool
    ) -> Optional[dict[str, Any]]:
        """Resolve one leaf's agent turn against its parked Driver slot.

        Returns None when the slot was resumed (the caller should `_drive`), or a
        terminal action dict (needs_resolution / failure) that short-circuits.

        Three turn outcomes resume the coroutine; the leaf re-dispatches itself
        across them (same OpExecution) until it completes:
          - dynamic call (`pending_invoke` set) → resume with `Invoke`; the
            coroutine runs the callee beneath this slot, then re-dispatches.
          - need() → on the spine, surface `needs_resolution` (slot stays parked
            for `resolve_need`); inside a gather, or for a callee, fail the run.
          - completion → resume with the captured output.
        """
        # Dynamic call this turn: hand the coroutine an Invoke to service.
        if execution.pending_invoke is not None:
            op_name, op_cls, inp = execution.pending_invoke
            execution.pending_invoke = None
            execution.status = ExecutionStatus.SUSPENDED
            run.pending_executions.discard(execution.id)
            slot = run.slot_for.pop(execution.id)
            run.driver.resume(slot, Invoke(op_cls=op_cls, value=inp, op_name=op_name))
            return None

        # need() surfaced as FAILED with a reason.
        if execution.status == ExecutionStatus.FAILED and execution.need_reason is not None:
            if execution.need_resolved:
                return self._fail_run(
                    run, f"need persisted after resolution: {execution.need_reason}"
                )
            if parallel:
                return self._fail_run(
                    run,
                    f"Gather branch {execution.op_name} called need "
                    f"(unsupported in a gather): {execution.need_reason}",
                )
            if execution.caller_execution_id is not None:
                return self._fail_run(
                    run,
                    f"Subroutine {execution.op_name} called need: "
                    f"{execution.need_reason}",
                )
            execution.status = ExecutionStatus.SUSPENDED
            execution.error = None
            return {
                "run_id": run.id,
                "action": "needs_resolution",
                "execution_id": execution.id,
                "op_name": execution.op_name,
                "reason": execution.need_reason,
                "resolve_via": "resolve_need",
                "abort_via": "abort_run",
            }

        # Any other failure.
        if execution.status == ExecutionStatus.FAILED:
            return self._fail_run(run, execution.error or "Execution failed.")

        # Completion: resume the slot with the leaf's terminal output.
        if not execution.completed_flag:
            execution.output_snapshot = result
            execution.status = ExecutionStatus.COMPLETED
            execution.completed_at = _now()
            execution.completed_flag = True
        run.pending_executions.discard(execution.id)
        slot = run.slot_for.pop(execution.id, None)
        if slot is None:
            raise RuntimeError_(
                f"Execution {execution.id} completed with no driver slot to resume."
            )
        run.driver.resume(slot, execution.output_snapshot)
        return None

    def abort(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        run.status = RunStatus.ABORTED
        run.completed_at = _now()
        run.pending_executions.clear()
        # Cancel all non-terminal executions (including suspended subroutine callers)
        for execution in run.executions.values():
            if execution.status in (
                ExecutionStatus.SUSPENDED,
                ExecutionStatus.RUNNING,
                ExecutionStatus.PENDING,
            ):
                execution.status = ExecutionStatus.FAILED
                execution.error = "Run aborted"
        return {"run_id": run.id, "status": run.status.value}

    def resolve_need(
        self,
        run_id: str,
        execution_id: str,
        supplemental_input: Any,
    ) -> dict[str, Any]:
        """Main thread resolves a need() by providing supplemental info.

        Re-dispatches the same Op with the supplemental attached. The
        execution keeps its id; `attempts` increments. A second need()
        on the re-dispatch will fail the run ("need persisted").
        """
        run = self._get_run(run_id)
        if run.status != RunStatus.RUNNING:
            raise RuntimeError_(f"Run {run_id} is not running ({run.status}).")
        try:
            _, execution = self._locate_execution(execution_id)
        except RuntimeError_:
            raise RuntimeError_(f"Execution {execution_id!r} not found.")
        if execution.need_reason is None or execution.status != ExecutionStatus.SUSPENDED:
            raise RuntimeError_(
                f"Execution {execution_id!r} is not awaiting need resolution "
                f"(status={execution.status.value}, need_reason={execution.need_reason!r})."
            )
        slot = run.slot_for.get(execution.id)
        if slot is None:
            raise RuntimeError_(
                f"Execution {execution_id!r} has no parked slot to resume."
            )

        # Mark resolved and reset completion bookkeeping; the leaf is "fresh"
        # for its next turn from the subagent's perspective.
        execution.need_supplemental = supplemental_input
        execution.need_resolved = True
        execution.completed_flag = False
        execution.output_snapshot = None
        execution.error = None
        execution.completed_at = None

        # Budget recovery: if this execution hit its dynamic-call budget, a
        # resolved need refreshes it so the agent can keep making calls.
        if execution.budget_exhausted:
            execution.invoke_budget_grant += self._max_invokes_per_execution
            execution.budget_exhausted = False

        # Resume the parked leaf with the supplemental; its turn-loop
        # re-dispatches itself (same execution) with the '## Supplemental'
        # section, exactly as a completed Invoke re-dispatches with a result.
        run.pending_executions.discard(execution.id)
        run.slot_for.pop(execution.id, None)
        run.driver.resume(slot, NeedResolved(supplemental=supplemental_input))
        return self._drive(run)

    # ---- Subagent-facing API -----------------------------------------

    def complete(
        self,
        execution_id: str,
        output: Any,
        *,
        parent_session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Subagent signals its step is done.

        `execution_id` is taken from the subagent's rendered prompt.
        `parent_session_id` is the Claude Code parent session that
        dispatched the subagent; tracked so the SubagentStop hook can
        release a completion when it fires for that session.
        """
        execution_id = self._identify_caller(execution_id)
        _, execution = self._locate_execution(execution_id)
        self._assert_not_terminal(execution)
        execution.output_snapshot = output
        execution.completed_flag = True
        execution.status = ExecutionStatus.COMPLETED
        execution.completed_at = _now()
        self._record_dispatch_completion(execution, parent_session_id)
        return {"ok": True}

    def need(
        self,
        execution_id: str,
        reason: str,
        *,
        parent_session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        execution_id = self._identify_caller(execution_id)
        _, execution = self._locate_execution(execution_id)
        self._assert_not_terminal(execution)
        execution.need_reason = reason
        execution.completed_flag = True  # hook should allow termination
        execution.status = ExecutionStatus.FAILED
        execution.error = f"need: {reason}"
        execution.completed_at = _now()
        self._record_dispatch_completion(execution, parent_session_id)
        return {"ok": True}

    def call_op(
        self,
        execution_id: str,
        op_name: str,
        subroutine_cls: type[Op],
        input_value: Any,
        *,
        parent_session_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a dynamic call (`Invoke`) on the caller's execution.

        Called by the call_tool MCP handler when the name resolves to an Op. The
        caller ends its turn; `step_complete` resolves the parked leaf with an
        `Invoke`, and the leaf's `_run_leaf` turn-loop runs the callee (leaf or
        composite, in the same run) beneath the parked slot before re-dispatching
        the caller with the result. The bookkeeping the bespoke path needed is
        gone — the only state is the recorded invoke plus the limit counters.
        """
        execution_id = self._identify_caller(execution_id)
        _, caller_execution = self._locate_execution(execution_id)

        # Per-execution call budget: bound runaway agent-driven loops. The depth
        # cap is loop-stable (a re-call from the same caller is the same depth),
        # so only a budget can bound sheer repetition. The budget is recoverable:
        # an agent that legitimately needs more calls a need(), and resolving it
        # refreshes the budget (see resolve_need).
        budget = self._max_invokes_per_execution + caller_execution.invoke_budget_grant
        if caller_execution.invoke_count >= budget:
            caller_execution.budget_exhausted = True
            raise RuntimeError_(
                f"Dynamic call budget exhausted: {caller_execution.op_name!r} has "
                f"originated {caller_execution.invoke_count} sub-Op calls "
                f"(limit {budget}). If you genuinely need more to finish, call "
                "need(...) to request additional budget, then continue."
            )

        # Depth check (configurable; counts genuine nesting, not repetition).
        depth = caller_execution.subroutine_depth + 1
        if depth > self._max_subroutine_depth:
            raise RuntimeError_(
                f"Subroutine depth limit exceeded ({depth} > {self._max_subroutine_depth})."
            )

        # Cycle check: walk the live caller chain looking for a repeated op_name.
        walk_id = caller_execution.caller_execution_id
        while walk_id:
            _, walk_exec = self._locate_execution(walk_id)
            if walk_exec.op_name == op_name:
                raise RuntimeError_(
                    f"Subroutine cycle detected: {op_name!r} already in call chain."
                )
            walk_id = walk_exec.caller_execution_id

        caller_execution.pending_invoke = (op_name, subroutine_cls, input_value)
        caller_execution.completed_flag = True  # hook: allow agent termination
        caller_execution.invoke_count += 1

        self._record_dispatch_completion(caller_execution, parent_session_id)
        return {"ok": True}

    def has_completed(self, execution_id: str) -> bool:
        """Diagnostic helper: did this execution call complete or need?"""
        try:
            _, execution = self._locate_execution(execution_id)
        except RuntimeError_:
            return False
        return execution.completed_flag

    def note_session(self, parent_session_id: Optional[str]) -> None:
        """Mark a parent session as one of ours.

        Called from every subagent-facing handler. The SubagentStop hook
        consults `is_known_session` to decide whether to enforce.
        """
        if parent_session_id:
            self._known_sessions.add(parent_session_id)

    def is_known_session(self, parent_session_id: str) -> bool:
        return parent_session_id in self._known_sessions

    # ---- SubagentStop hook surface -----------------------------------

    def release_one_completed(self, parent_session_id: str) -> Optional[str]:
        """Called by the SubagentStop hook.

        Returns an execution_id if a completed-but-unreleased dispatch
        exists for this parent session (releasing it from the queue),
        or None if none does (the hook blocks in that case).

        Under Phase 1b sequential dispatch this is exact. Under Phase 2
        parallel dispatch it's approximate — it acknowledges "some"
        completion, not "this specific agent's" completion. Backlog:
        tighten when `agent_id` becomes available at tool-call time.
        """
        queue = self._session_dispatches.get(parent_session_id)
        if not queue:
            return None
        execution_id = queue.popleft()
        try:
            _, execution = self._locate_execution(execution_id)
            execution.hook_released = True
        except RuntimeError_:
            pass
        if not queue:
            self._session_dispatches.pop(parent_session_id, None)
        return execution_id

    # ---- Internals ----------------------------------------------------

    def _get_run(self, run_id: str) -> Run:
        run = self._runs.get(run_id)
        if run is None:
            raise RuntimeError_(f"Unknown run {run_id!r}.")
        return run

    def _locate_execution(self, execution_id: str) -> tuple[str, OpExecution]:
        for run in self._runs.values():
            if execution_id in run.executions:
                return run.id, run.executions[execution_id]
        raise RuntimeError_(f"Execution {execution_id!r} not found.")

    def _identify_caller(self, explicit_execution_id: str) -> str:
        """Seam for implicit caller identification.

        Phase 1b: trust the explicit execution_id the subagent passed
        (baked into its prompt at dispatch time). Phase 2+ may try to
        derive it from MCP request metadata before falling back to
        the explicit arg. Backlog entry tracks this.
        """
        if not explicit_execution_id:
            raise RuntimeError_("execution_id is required.")
        return explicit_execution_id

    def _assert_not_terminal(self, execution: OpExecution) -> None:
        if execution.status in (ExecutionStatus.COMPLETED, ExecutionStatus.FAILED):
            raise RuntimeError_(
                f"Execution {execution.id} already terminal "
                f"({execution.status.value}); refusing to overwrite."
            )

    def _record_dispatch_completion(
        self,
        execution: OpExecution,
        parent_session_id: Optional[str],
    ) -> None:
        """Queue a completion for the SubagentStop hook to release."""
        if parent_session_id is None:
            # Accept missing parent session id (e.g., direct Runtime use
            # in tests). Hook can still enforce if provided later.
            return
        self.note_session(parent_session_id)
        if execution.parent_session_id is None:
            execution.parent_session_id = parent_session_id
        self._execution_to_session[execution.id] = parent_session_id
        queue = self._session_dispatches.setdefault(parent_session_id, deque())
        queue.append(execution.id)

    def _fail_run(self, run: Run, error: str) -> dict[str, Any]:
        """Mark a run as failed, clear pending state, return the failure payload.

        Used wherever the runtime catches a structural error during composition
        walking (branch resolution, loop predicate, etc.) — failures land
        cleanly in the run's status instead of bubbling as exceptions.
        """
        run.status = RunStatus.FAILED
        run.error = error
        run.completed_at = _now()
        run.pending_executions.clear()
        run.slot_for.clear()
        return {"run_id": run.id, "action": "failed", "error": run.error}

    def _resolve_branch(self, branch: BranchOn, upstream_output: Any) -> type[Op]:
        """Evaluate a branch_on against the upstream output and pick the arm.

        Raises RuntimeError_ with a structured message on:
          - key function raising
          - key value not in declared arms

        Raised inside the interpreter coroutine, both propagate through the
        Driver as an ('error', exc) and land as a failed run via `_drive`.
        """
        try:
            key_value = branch.key(upstream_output)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError_(
                f"branch_on key function raised: {type(exc).__name__}: {exc}"
            ) from exc
        if key_value not in branch.arms:
            raise RuntimeError_(
                f"No arm for branch key {key_value!r}. "
                f"Declared arms: {sorted(branch.arms.keys(), key=repr)}."
            )
        return branch.arms[key_value]

    async def _run_leaf(
        self,
        node: type[Op],
        value: Any,
        *,
        depth: int = 0,
        caller_execution_id: Optional[str] = None,
        require_full: bool = True,
    ) -> Any:
        """Run one leaf Op as a sequence of agent *turns*, parking the coroutine
        each turn. A turn ends in one of three outcomes (resolved by the Runtime
        when results land):

          - completion → the agent called complete(); return its output.
          - `Invoke`   → the agent issued a dynamic call; run the callee beneath
            this parked slot (`_exec_invoke`), then re-dispatch this same leaf
            with the result under '## Result from <op>'.
          - `NeedResolved` → the main thread resolved a need(); re-dispatch this
            leaf with the supplemental.

        Re-dispatches reuse one OpExecution: the first turn parks with
        `execution_id=None`, the Runtime writes the id onto the (shared) Dispatch
        object, and subsequent turns carry it back. Because every turn — and
        every callee leaf — is a plain parked `external`, dynamic calls inside a
        gather branch and multi-step composite callees need no special handling:
        the Driver batches them like any other frontier item."""
        req = Dispatch(
            op_cls=node, value=value,
            depth=depth, caller_execution_id=caller_execution_id,
            require_full_output=require_full,
        )
        while True:
            outcome = await external(req)
            if isinstance(outcome, Invoke):
                sub_output = await self._exec_invoke(
                    outcome.op_cls, outcome.value,
                    depth=depth + 1, caller_execution_id=req.execution_id,
                )
                req = Dispatch(
                    op_cls=node, value=value,
                    execution_id=req.execution_id, depth=depth,
                    caller_execution_id=caller_execution_id,
                    pending_result={"op_name": outcome.op_name, "output": sub_output},
                    require_full_output=require_full,
                )
                continue
            if isinstance(outcome, NeedResolved):
                req = Dispatch(
                    op_cls=node, value=value,
                    execution_id=req.execution_id, depth=depth,
                    caller_execution_id=caller_execution_id,
                    need_supplemental=outcome.supplemental,
                    require_full_output=require_full,
                )
                continue
            return outcome

    async def _exec_invoke(
        self,
        op_cls: type[Op],
        value: Any,
        *,
        depth: int,
        caller_execution_id: Optional[str],
    ) -> Any:
        """Service an `Invoke`: run the callee beneath the caller's parked slot
        and return its terminal output. A leaf callee is its own turn-loop (so it
        may itself make dynamic calls); a composite callee runs its `body` as a
        sub-flow in the *same* run (shared stores), its leaves dispatching through
        the normal frontier."""
        # A subroutine's output is an explicit deliverable injected into the
        # caller's next prompt, so it must be the real value (require_full=True),
        # never a manifest.
        if op_cls.is_leaf():
            return await self._run_leaf(
                op_cls, value, depth=depth, caller_execution_id=caller_execution_id,
                require_full=True,
            )
        return await self._exec_node(
            op_cls.body, value, depth=depth, caller_execution_id=caller_execution_id,
            require_full=True,
        )

    async def _exec_node(
        self,
        node: Any,
        value: Any,
        *,
        depth: int = 0,
        caller_execution_id: Optional[str] = None,
        require_full: bool = True,
    ) -> Any:
        """Recursive interpreter for a flow node — the whole runtime.

        The entry Op's node is driven by the run's single Driver. Each leaf runs
        a `_run_leaf` turn-loop; all composition (sequence, branch_on, gather,
        loop, composite Ops) is handled by Python's own recursion plus the
        Driver's `fork`. `depth`/`caller_execution_id` thread the dynamic-call
        chain through composite callees (incremented only at `_exec_invoke`).

        `require_full` carries whether *this* node's output is consumed in-band
        (by a branch/loop, or as the run's terminal output) versus only by a
        downstream agent. It is propagated to each leaf so the manifest output
        contract can lighten only the outputs nobody reads directly."""
        kw = {"depth": depth, "caller_execution_id": caller_execution_id}

        # Leaf or composition Op.
        if isinstance(node, type) and issubclass(node, Op):
            if node.is_leaf():
                return await self._run_leaf(node, value, require_full=require_full, **kw)
            return await self._exec_node(node.body, value, require_full=require_full, **kw)

        if isinstance(node, Sequence):
            out = value
            steps = node.steps
            last = len(steps) - 1
            for i, step in enumerate(steps):
                # The terminal step inherits this sequence's consumer; an
                # intermediate step feeds the next step (agent-consumed → a
                # manifest suffices) unless that successor consumes the value
                # in-band (branch_on/loop), which needs the real value.
                step_full = require_full if i == last else _consumes_in_band(steps[i + 1])
                out = await self._exec_node(step, out, require_full=step_full, **kw)
            return out

        if isinstance(node, BranchOn):
            arm = self._resolve_branch(node, value)  # raises RuntimeError_ on bad key
            return await self._exec_node(arm, value, require_full=require_full, **kw)

        if isinstance(node, Gather):
            # A gather exists to collect N branch deliverables for a join that,
            # by construction, needs all of them — so each branch's *deliverable*
            # (its terminal output) stays full regardless of the manifest
            # contract; a manifest there would just force the join to pull every
            # branch back. Branch-*internal* intermediate steps still lighten:
            # require_full=True only reaches each branch subtree's terminal leaf.
            return await fork([
                self._exec_node(b, value, require_full=True, **kw)
                for b in node.branches
            ])

        if isinstance(node, Loop):
            body = node.body
            if not (isinstance(body, type) and issubclass(body, Op)):
                raise RuntimeError_(f"loop body must be an Op; got {body!r}.")
            out = value
            iterations = 0
            while True:
                # The body's output feeds until() and the next iteration's input
                # (the accumulator) — always consumed in-band, never a manifest.
                out = await self._exec_node(body, out, require_full=True, **kw)
                iterations += 1
                try:
                    done = bool(node.until(out))
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError_(
                        f"loop until predicate raised: {type(exc).__name__}: {exc}"
                    ) from exc
                if done:
                    return out
                if iterations >= node.max_iterations:
                    raise RuntimeError_(
                        f"loop exceeded max_iterations ({node.max_iterations}) "
                        "without satisfying until predicate"
                    )

        raise RuntimeError_(f"Unsupported flow node: {node!r}.")

    def _drive(self, run: Run) -> dict[str, Any]:
        """Drive the run's single Driver to its next quiescence and surface it.

        The Driver runs the entry Op's interpreter coroutine. Each `drive()`
        returns one of:
          - ('error', exc)      → the flow raised; fail the run.
          - ('done', value)     → the flow returned; the run is complete.
          - ('frontier', batch) → leaves parked this round; materialize them
            into a dispatch (single, sequential spine) or a dispatch_parallel
            (a gather round — `forks_in_flight > 0`).
        """
        kind, payload = run.driver.drive()
        if kind == "error":
            return self._fail_run(run, str(payload))
        if kind == "done":
            run.output = payload
            run.status = RunStatus.COMPLETED
            run.completed_at = _now()
            return {"run_id": run.id, "action": "done", "output": run.output}
        return self._materialize_frontier(run, payload)

    def _materialize_frontier(self, run: Run, batch: list) -> dict[str, Any]:
        """Turn a Driver frontier batch into the next dispatch action.

        Each parked `Dispatch` is one agent turn. The first turn of a leaf
        creates an OpExecution and writes its id back onto the (shared) Dispatch
        object; later turns of that same leaf carry the id and **reuse** the
        execution (re-dispatch), injecting the sub-Op result or resolved-need
        supplemental into the prompt. The execution's id maps to the Driver slot
        so the resume path can wake the right coroutine. A single leaf on the
        sequential spine reports via `step_complete`; a round with a fork in
        flight reports via `step_complete_parallel`.
        """
        parallel = run.driver.forks_in_flight > 0
        execution_ids: list[str] = []
        agent_configs: list[dict[str, Any]] = []
        for dispatch in batch:
            op_cls = dispatch.op_cls
            if not (isinstance(op_cls, type) and issubclass(op_cls, Op)):
                return self._fail_run(
                    run,
                    f"gather() branch must resolve to Op references; got {op_cls!r}.",
                )
            if dispatch.execution_id is not None and dispatch.execution_id in run.executions:
                # Re-dispatch of the same leaf (next turn): reuse the execution.
                execution = run.executions[dispatch.execution_id]
                execution.status = ExecutionStatus.RUNNING
                execution.completed_flag = False
                execution.output_snapshot = None
                execution.attempts += 1
            else:
                execution = OpExecution(
                    id=f"exec_{uuid.uuid4().hex[:8]}",
                    op_name=registry.ref(op_cls),
                    run_id=run.id,
                    input_snapshot=dispatch.value,
                    kind="worker",
                    status=ExecutionStatus.RUNNING,
                    started_at=_now(),
                    attempts=1,
                    subroutine_depth=dispatch.depth,
                    caller_execution_id=dispatch.caller_execution_id,
                )
                run.add_execution(execution)
                dispatch.execution_id = execution.id
            run.pending_executions.add(execution.id)
            run.slot_for[execution.id] = dispatch.slot
            execution_ids.append(execution.id)
            config = build_agent_config(
                op_cls,
                dispatch.value,
                run_id=run.id,
                execution_id=execution.id,
                pending_subroutine_result=dispatch.pending_result,
                need_supplemental=dispatch.need_supplemental,
                state_manager=self._state_managers.get(run.id),
                manifest_mode=self._manifest_mode,
                require_full_output=dispatch.require_full_output,
            )
            agent_configs.append(
                {k: v for k, v in config.items() if not k.startswith("_")}
            )

        if parallel:
            return {
                "run_id": run.id,
                "action": "dispatch_parallel",
                "agent_template": "clops-executor",
                "agent_configs": agent_configs,
                "execution_ids": list(execution_ids),
                "report_via": "step_complete_parallel",
            }
        # Sequential spine: exactly one leaf parks per round.
        return {
            "run_id": run.id,
            "action": "dispatch",
            "agent_template": "clops-executor",
            "agent_config": agent_configs[0],
            "report_via": "step_complete",
        }

    def step_complete_parallel(
        self, run_id: str, results: dict[str, Any]
    ) -> dict[str, Any]:
        """Main thread reports a gather round's subagent results.

        `results` maps execution_id → final text for exactly the current
        pending parallel batch. Branch outputs feed back into the run Driver,
        which either dispatches the next round or, once every branch has
        completed, joins them (declaration order) and resumes the parent.
        """
        run = self._get_run(run_id)
        if run.status != RunStatus.RUNNING:
            raise RuntimeError_(f"Run {run_id} is not running ({run.status}).")
        if run.driver.forks_in_flight <= 0 or not run.pending_executions:
            raise RuntimeError_(
                f"Run {run_id} has no active gather; use step_complete instead."
            )

        # The current parallel batch is exactly the pending executions.
        batch_ids = sorted(run.pending_executions)
        expected = set(batch_ids)
        got = set(results.keys())
        if got != expected:
            missing = expected - got
            extra = got - expected
            parts = []
            if missing:
                parts.append(f"missing execution_ids: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected execution_ids: {sorted(extra)}")
            raise RuntimeError_(
                "step_complete_parallel results mismatch: " + "; ".join(parts)
            )

        # Resolve each branch's turn against its parked slot — the same
        # `_resolve_execution_turn` the spine uses. A branch that made a dynamic
        # call resumes with an `Invoke` and parks its callee's dispatch on the
        # *next* frontier round; a completed branch returns into the fork's join.
        # So a dynamic call inside a gather branch needs no special handling: the
        # Driver batches the callee dispatch and the branch re-dispatch like any
        # other frontier item, and peers keep running. A need() inside a gather
        # branch fails the run (no mid-gather resolution in v1).
        for execution_id in batch_ids:
            execution = run.get_execution(execution_id)
            terminal = self._resolve_execution_turn(
                run, execution, results[execution_id], parallel=True
            )
            if terminal is not None:
                return terminal

        # Drive the fork: invoked branches park their callee dispatches as the
        # next parallel round; once every branch returns, the fork joins
        # (declaration order) and the spine continues.
        return self._drive(run)

    # ---- State stores ---------------------------------------------------

    def _collect_stores(self, op_cls: type[Op]) -> dict[str, "Store"]:
        """Collect all Store declarations from an Op and its body tree."""
        from clops.store import Store

        stores: dict[str, Store] = dict(getattr(op_cls, "_stores", {}))
        body = getattr(op_cls, "body", None)
        if body is not None:
            for child_cls in walk(body):
                for name, store in getattr(child_cls, "_stores", {}).items():
                    if name in stores and stores[name].kind != store.kind:
                        raise RuntimeError_(
                            f"Store {name!r} type conflict: "
                            f"{stores[name].kind!r} vs {store.kind!r}"
                        )
                    stores.setdefault(name, store)
        return stores

    def state(
        self, execution_id: str, store: str, operation: str, **kwargs: Any
    ) -> Any:
        """Execute a state operation for a running execution."""
        _, execution = self._locate_execution(execution_id)
        sm = self._state_managers.get(execution.run_id)
        if sm is None:
            raise RuntimeError_(f"No state stores for run {execution.run_id!r}.")
        return sm.execute(store, operation, execution_id=execution_id, **kwargs)

    def get_state_manager(self, run_id: str):
        """Return the StateManager for a run, or None."""
        return self._state_managers.get(run_id)
