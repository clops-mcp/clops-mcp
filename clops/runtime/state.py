"""State graph: Runs hold a graph of OpExecution records.

A Run is a thin wrapper around its single coroutine `driver` plus the
`execution_id → driver slot` bridge (`slot_for`). Control flow lives on the
interpreter coroutine's own stack; the Run only correlates external subagent
results back to the parked coroutine. `pending_executions` is a set because a
gather round dispatches several leaves at once. Hook correlation pulls from
`session_dispatches` per parent session id.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    #: Reloaded from disk after the process that was driving it went away
    #: (an /mcp reconnect, an editor restart). The record and the state
    #: stores survive and are readable; the flow itself cannot continue,
    #: because a run's control-flow position lives on the interpreter
    #: coroutine's Python stack, which does not outlive the process.
    INTERRUPTED = "interrupted"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class OpExecution:
    id: str
    op_name: str
    run_id: str
    input_snapshot: Any
    status: ExecutionStatus = ExecutionStatus.PENDING
    output_snapshot: Any = None
    parent_session_id: Optional[str] = None
    kind: str = "worker"  # retained for record shape; only workers exist now
    attempts: int = 0
    error: Optional[str] = None
    need_reason: Optional[str] = None
    # Set when main thread resolves a need() with supplemental info; the
    # re-dispatched prompt includes a section surfacing this to the subagent.
    need_supplemental: Any = None
    # True after need_supplemental has been consumed by a re-dispatch — used
    # to guard against a subagent calling need() twice after resolution.
    need_resolved: bool = False
    completed_flag: bool = False
    hook_released: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Dynamic-call state (driver-native Invoke). When this leaf's agent calls
    # call_op mid-turn, the request is recorded here; step_complete resolves the
    # parked slot with an Invoke and the leaf's turn-loop services it.
    pending_invoke: Optional[tuple] = None  # (op_name, op_cls, input) or None
    # Subroutine call stack:
    subroutine_depth: int = 0                             # depth in the call chain
    caller_execution_id: Optional[str] = None             # who invoked us as a subroutine
    # Number of dynamic sub-Op calls (call_op) this execution has originated,
    # across its re-dispatches. Bounds runaway dynamic loops (the depth cap is
    # loop-stable and so cannot bound repetition).
    invoke_count: int = 0
    # Extra dynamic-call budget granted via need() recovery; the effective
    # budget is the Runtime default + this grant. `budget_exhausted` marks that
    # this execution hit its budget, so the next resolved need() refreshes it.
    invoke_budget_grant: int = 0
    budget_exhausted: bool = False


@dataclass
class Run:
    id: str
    process: str
    input: Any
    status: RunStatus = RunStatus.PENDING
    output: Any = None
    error: Optional[str] = None
    executions: dict[str, OpExecution] = field(default_factory=dict)
    pending_executions: set[str] = field(default_factory=set)
    # The single coroutine Driver running this run's interpreter (the entry
    # Op's `_exec_node`). Control-flow position lives on the coroutine's own
    # Python stack — there is no frame walker.
    driver: Any = None
    # The irreducible bridge state: execution_id → the Driver slot of the
    # coroutine parked on that leaf's dispatch. `step_complete` /
    # `step_complete_parallel` resume the right coroutine when results land.
    slot_for: dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    completed_at: Optional[datetime] = None

    def add_execution(self, execution: OpExecution) -> None:
        self.executions[execution.id] = execution

    def get_execution(self, execution_id: str) -> OpExecution:
        return self.executions[execution_id]

    def any_pending(self) -> bool:
        return bool(self.pending_executions)

    def single_pending(self) -> Optional[str]:
        """Return the sole pending execution id (Phase 1b sequential)."""
        if len(self.pending_executions) == 1:
            return next(iter(self.pending_executions))
        return None
