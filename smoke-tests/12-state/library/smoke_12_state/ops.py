"""Ops for smoke test 12: state stores across a pipeline.

ManageProject (entry, composition):
  Declares a `tasks` Store(dict[str, Task]).
  body = sequence(PlanTasks, ExecuteTasks)

PlanTasks (leaf):
  Reads the project brief, creates tasks in the tasks store.

ExecuteTasks (leaf):
  Reads the tasks store, marks them done, produces a status report.
"""

from clops import Op, Store, sequence
from smoke_12_state.concepts import ProjectBrief, StatusReport, Task


class PlanTasks(Op):
    Input = ProjectBrief
    Output = StatusReport
    Intent = (
        "Read the project brief and break it down into 2-3 concrete tasks. "
        "For each task, call mcp__clops__state to add it to the 'tasks' store: "
        "state(execution_id, 'tasks', 'set', id='task-1', "
        "value={'name': '<task name>', 'status': 'pending'}). "
        "After creating the tasks, call complete with a brief summary of "
        "what tasks you created."
    )
    Meta = "First step: breaks a brief into tasks stored in shared state."


class ExecuteTasks(Op):
    Input = StatusReport
    Output = StatusReport
    Intent = (
        "Read all tasks from the 'tasks' store by calling "
        "state(execution_id, 'tasks', 'list'). For each pending task, "
        "mark it as done by calling state(execution_id, 'tasks', 'set', "
        "id='<task-id>', value={'name': '<name>', 'status': 'done'}). "
        "Then call complete with a final status report listing what was done."
    )
    Meta = "Second step: reads tasks from state, marks them done."


class ManageProject(Op):
    Input = ProjectBrief
    Output = StatusReport
    Intent = "Manage a project from brief to completion."
    Meta = "Composition Op with shared state store for task tracking."
    entry = True

    tasks = Store(dict[str, Task])
    body = sequence(PlanTasks, ExecuteTasks)
