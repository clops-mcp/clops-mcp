# clops

A runtime for LLM-bodied functions. Define pipelines as graphs of typed steps, then let Claude Code orchestrate them via MCP.

## What it is

clops lets you decompose complex work into **Ops** — small, focused units of thought that LLM agents execute. You declare what each step does, what data flows between them, and how they compose. The runtime handles dispatch, state, and orchestration.

```python
from clops import Concept, Field, Op, Store, sequence

class ProjectBrief(Concept):
    description = "Project requirements and goals"
    goals = Field("What needs to be accomplished")

class Task(Concept):
    description = "A work item"
    name = Field("Short task name")
    status = Field("One of: pending, done")

class StatusReport(Concept):
    description = "Summary of completed work"
    completed = Field("Tasks that were finished")

class PlanTasks(Op):
    Input = ProjectBrief
    Output = StatusReport
    Intent = "Break the brief into concrete tasks and add them to the tasks store"
    Meta = "First step: creates tasks in shared state."

class ExecuteTasks(Op):
    Input = StatusReport
    Output = StatusReport
    Intent = "Read tasks from the store, complete each one, mark them done"
    Meta = "Second step: works through tasks from shared state."

class ManageProject(Op):
    Input = ProjectBrief
    Output = StatusReport
    Intent = "Manage a project from brief to completion"
    Meta = "Pipeline with shared task tracking."
    entry = True
    tasks = Store(dict[str, Task])
    body = sequence(PlanTasks, ExecuteTasks)
```

## Key ideas

- **Ops are declarations, not code.** You define Intent, Input, Output — the LLM figures out how.
- **Equip, don't prescribe.** Give agents capabilities (Tools, Stores) and let them decide when to use them.
- **State stores** share typed, mutable data across pipeline steps. Backed by TinyDB.
- **Typed Concepts** with Fields tell agents exactly what shape data should have.
- **Composition** via `sequence`, `branch_on`, `gather`, `loop` — no custom orchestration code.

## Install

clops runs via `uvx` — nothing needs to live on your `PATH`. It isn't on PyPI yet, so install it straight from this GitHub repo (the distribution is **`clops-ops`**; the import and CLI are still `clops`). Access requires a clone/read grant on the repo — `uvx` uses your configured git credentials.

```bash
# Run the CLI without installing — uvx fetches and caches on demand:
uvx --from git+https://github.com/wesley-harding/clops clops --help
```

> Prefer SSH (or want to pin a tag)? Set `CLOPS_INSTALL_SPEC` before running `clops init`, e.g. `export CLOPS_INSTALL_SPEC='git+ssh://git@github.com/wesley-harding/clops'` — `init` bakes it into the generated `.mcp.json` and hook.

### Set up a project (one command)

```bash
uvx --from git+https://github.com/wesley-harding/clops clops init --library my_ops
```

This writes a **self-contained** setup — `.mcp.json` (the clops MCP server), the SubagentStop hook, the executor agent, and the orchestration skill. The generated `.mcp.json` runs `uvx --from git+https://github.com/wesley-harding/clops clops-server` (or your `CLOPS_INSTALL_SPEC`) and pulls any Op-library sources via `--with` at server start, so a fresh clone of your project needs only `uv` installed and git access to this repo.

### Optional: the Claude Code plugin

The plugin adds clops's authoring + orchestration **skills** globally (`/clops:design`, `clops-authoring`, `clops-orchestration`, `/clops`). It does **not** register an MCP server — your project's `.mcp.json` (from `clops init`) owns that, so the two never conflict.

```bash
claude plugin marketplace add wesley-harding/clops
claude plugin install clops
```

### From source (for development)

```bash
git clone https://github.com/wesley-harding/clops
cd clops
uv sync
```

## Create a project

> Tip: for a persistent `clops` on your `PATH`, run `uv tool install git+https://github.com/wesley-harding/clops`. Otherwise prefix any command with `uvx --from git+https://github.com/wesley-harding/clops` (e.g. `uvx --from git+https://github.com/wesley-harding/clops clops new-library my_ops`).

```bash
# Scaffold a new library
clops new-library my_ops

# Set up a project to use it
clops init --library my_ops
```

Or with a library from a separate repo:

```bash
clops init --library "work_ops @ ~/work/work-ops"
```

The `.clops` file in your project root lists libraries and constants:

```
# Libraries
my_ops
work_ops @ ~/work/work-ops

[constants]
user_id = wes-dev-123
database = staging
```

## Documentation

| Doc | What it covers |
|-----|---------------|
| [Philosophy](docs/philosophy.md) | How to think about decomposing work into Ops |
| [Concepts](docs/concepts.md) | The five primitives: Concept, Snippet, Tool, Store, Op |
| [Patterns](docs/patterns.md) | Composition patterns and when to use each |
| [Examples](docs/examples.md) | Eight worked examples from simple to complex |
| [Combinators](docs/combinators.md) | sequence, branch_on, gather, loop reference |
| [Authoring Spec](authoring-spec.md) | Full authoring reference |

## Skills

| Skill | What it does |
|-------|-------------|
| `/clops:design` | Principal architect mode — design a pipeline before writing code |
| `/clops` | Bookmark a moment in the conversation for later analysis |
| `clops-authoring` | Quick scaffolding and implementation of Ops |
| `clops-orchestration` | Dispatch relay between MCP server and subagents |

## CLI

```bash
clops new-library <name>    # Scaffold a new Op library
clops init --library <lib>  # Set up a project for clops
clops lint <library>        # Validate a library
clops show <library>        # Print a library's shape
```
