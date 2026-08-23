"""Runtime — the execution engine that drives Ops through dispatches.

Phase 1b: the MCP server wraps `Runtime` and exposes its methods as
tools. Main-thread-facing: `list_processes`, `start_process`,
`step_complete`, `run_status`, `list_runs`, `abort_run`. Subagent-facing:
`complete(execution_id, output)` and `need(execution_id, reason)` —
execution_id is baked into the subagent's rendered prompt. The hook
handler calls `release_one_completed(parent_session_id)` on SubagentStop.
"""

from clops.runtime.core import Runtime
from clops.runtime.state import (
    ExecutionStatus,
    OpExecution,
    Run,
    RunStatus,
)

__all__ = [
    "Runtime",
    "Run",
    "OpExecution",
    "RunStatus",
    "ExecutionStatus",
]
