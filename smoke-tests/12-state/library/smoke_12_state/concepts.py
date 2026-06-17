"""Concepts for smoke test 12: state stores + typed fields."""

from clops import Concept, Field


class ProjectBrief(Concept):
    description = "A project brief describing what needs to be done."

    goals = Field("The project goals and requirements")
    constraints = Field("Any constraints or limitations", required=False)


class Task(Concept):
    description = "A work item tracked in the tasks store."

    name = Field("Short descriptive name of the task")
    status = Field("One of: pending, done")
    notes = Field("Additional context or results", required=False)


class StatusReport(Concept):
    description = "A summary report of what was accomplished."

    completed = Field("List of tasks that were completed")
    remaining = Field("Any remaining work or follow-ups", required=False)
