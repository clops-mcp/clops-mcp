from clops.runtime.state import (
    ExecutionStatus,
    OpExecution,
    Run,
    RunStatus,
)


def test_run_default_fields():
    run = Run(id="r1", process="Foo", input={"x": 1})
    assert run.status == RunStatus.PENDING
    assert run.executions == {}
    assert run.driver is None
    assert run.slot_for == {}
    assert run.pending_executions == set()
    assert run.any_pending() is False
    assert run.single_pending() is None


def test_run_single_pending_returns_only_when_exactly_one():
    run = Run(id="r1", process="Foo", input={})
    run.pending_executions.add("exec_a")
    assert run.single_pending() == "exec_a"
    run.pending_executions.add("exec_b")
    assert run.single_pending() is None  # ambiguous
    assert run.any_pending() is True


def test_execution_default_kind_is_worker():
    e = OpExecution(id="e1", op_name="Foo", run_id="r1", input_snapshot={})
    assert e.kind == "worker"
    assert e.hook_released is False
    assert e.parent_session_id is None


def test_execution_status_transitions():
    e = OpExecution(id="e1", op_name="Foo", run_id="r1", input_snapshot={})
    assert e.status == ExecutionStatus.PENDING
    e.status = ExecutionStatus.RUNNING
    assert e.status == ExecutionStatus.RUNNING
