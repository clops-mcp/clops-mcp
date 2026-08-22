# Authoring Spec — writing an Op library

_For use by Claude Code (and humans) when authoring clops Op libraries. This is the syntax-and-spec surface. Not a tutorial; it's the reference the authoring agent reads while writing code._

_Companion to: agent-framework-design-direction.md (for "why"), concrete-op-walkthrough.md (for a worked example)._

---

## What you are writing

A **Python package** that declares `Concept`s, `Snippet`s, `Tool`s, and `Op`s. The package is installed into a project that has clops set up; the clops MCP server loads the package at startup and exposes every entry-point Op as a runnable process.

Authoring is plain Python. No MCP, no subagents, no runtime involved. You write classes, you run pytest, you iterate.

---

## Starting a new library

Quickest way to get from zero to a working library:

```bash
clops new-library my_company.support_ops
pip install -e ./my_company
```

Scaffolds the package layout shown below with one demo Echo Op (delete or replace it) and a `pyproject.toml`. Pass `--target DIR` to scaffold somewhere other than cwd, or `--force` to overwrite an existing root directory.

## Package layout

```
my_company_ops/
├── __init__.py          # imports every submodule so the registry populates
├── concepts.py          # Concept subclasses (named, described data types)
├── snippets.py          # Module-level Snippet constants for shared content
├── tools.py             # Tool instances for external capabilities
└── ops/
    ├── __init__.py
    ├── classify_intent.py
    ├── draft_response.py
    └── handle_support.py
```

Any layout works as long as every Op gets imported (imports trigger registration via the metaclass). The convention above mirrors the reference library in `examples/my_company/`.

---

## Primitives

### `Concept`

A named, described handle for a thing that flows between Ops. Not a schema. The value at runtime is whatever the producing agent produced (prose, dict, mixed).

```python
from clops import Concept

class UserMessage(Concept):
    description = "A customer's support message, including any context that came with it."

class Intent(Concept):
    description = """A classification of the customer's support need.

    Categories: billing, technical, or general.
    Includes reasoning and a rough sense of confidence."""
```

**Rules:**
- Must define `description` as a non-empty string.
- Class name is the Concept's identity.
- Description is rendered into prompts as loose guidance — write it like you'd describe the concept to a colleague in one paragraph.

### `Snippet`

A reusable content fragment. Two forms: inline (declared where used) or shared (module-level constant).

```python
from clops import Snippet

# Shared — referenced by multiple Ops
safety_rules = Snippet(
    id="safety_rules",
    content="Never acknowledge account details the user hasn't provided.",
)

# With a role — for Requires-style resolution
brand_voice = Snippet(
    id="brand_voice_v3",
    role="brand_voice",
    content="Warm, direct, no jargon.",
)
```

**Rules:**
- `id` must be unique across the library.
- `content` must be non-empty.
- `role` is optional; when set, Ops can reference it by role via `SnippetRole`.
- Soft limit: keep content around 500–1000 characters. Linter warns above 1000.
- If multiple Snippets share a role, the Op's `Requires` resolves to one of them (currently first-registered).

### `Tool`

An external capability the Op can invoke during reasoning. At Phase 1a, Tools are metadata holders; they become real MCP tool calls in Phase 1b.

```python
from clops import Tool

query_customer_history = Tool(
    name="query_customer_history",
    description="Retrieve the last 10 support interactions for a customer.",
    parameters={"customer_id": str},
    handler=lambda customer_id: fetch_support_history(customer_id),
)
```

**Rules:**
- `name` must be unique across the library. Subagents invoke tools through the single `mcp__clops__call_tool(execution_id, name, arguments)` MCP entry — there is no per-Tool MCP registration. A library with 200 Tools adds 0 MCP tools; they're all routed through `call_tool`.
- `description` must be non-empty. Rendered into the dispatched subagent's prompt so it knows when to use the tool.
- `parameters` is a dict of `{name: type}`. Rendered into the prompt as an argument hint. Not validated at runtime.
- `handler` is the Python callable invoked when the agent calls the tool. Optional; if missing, the tool can be referenced but not executed.

**Design note.** Tool libraries can grow to dozens or hundreds without expanding the MCP surface. This is deliberate: agents don't need to reason about the harness's tool catalog — they need to know "call `call_tool` with these args." The prompt is the interface; `call_tool` is the transport.

### `Store`

A run-scoped state container shared across all Ops in a composition. Composition Ops declare stores as class attributes; child Ops in the body inherit access. Backed by TinyDB (pure Python, zero deps) — one database per run, each store is one table.

**Three store shapes:**

```python
from clops import Store

# Scalar — single value, read/written as a whole
notes = Store(str)

# List — ordered collection with append/remove/list
findings = Store(list[Finding])

# Dict — keyed collection with get/set/delete/list
tasks = Store(dict[str, Task])
```

Each shape gets auto-generated CRUD operations exposed through the MCP tool `mcp__clops__state(execution_id, store, operation, ...)`. Scalars support `get` / `set`. Lists support `append` / `remove` / `list`. Dicts support `get` / `set` / `delete` / `list`.

**Declaring stores on a composition Op:**

```python
from clops import Op, Store, sequence

class ManageProject(Op):
    Input = ProjectBrief
    Output = StatusReport
    Intent = "Manage a project"
    Meta = "Composition Op with shared state."
    entry = True
    tasks = Store(dict[str, Task])
    notes = Store(str)
    body = sequence(PlanTasks, ExecuteTasks)
```

Both `PlanTasks` and `ExecuteTasks` can read and write `tasks` and `notes` via the MCP tool. Scalars are injected inline into the dispatched subagent's prompt; collections show summaries (count, keys, or first few items) so agents know what's available without flooding the context.

**Custom queries via Store subclasses:**

For stores that need domain-specific lookups beyond basic CRUD, subclass `Store`:

```python
from clops import Store
from tinydb import where

class TaskStore(Store):
    type_hint = dict[str, Task]
    queries = {
        "pending": where('status') == 'pending',
    }
    def by_assignee(self, table, assignee: str):
        return table.search(where('assignee') == assignee)
```

Named queries (`queries` dict) are pre-built TinyDB `where` expressions. Custom methods receive the TinyDB table and any arguments. Both are invocable through `mcp__clops__state`.

**Rules:**
- Stores are declared only on composition Ops (Ops with a `body`). Leaf Ops access stores inherited from their parent composition.
- Store names must be valid Python identifiers and unique within the Op.
- Type hints must be one of `str`, `list[X]`, or `dict[str, X]`.
- Stores are run-scoped: created when the run starts, destroyed when it ends.
- Keep stored values small. A store is rendered into every prompt that can see it, so a long value is paid for by every later step, not just the one that needed it. For anything long, agents are told to write a file in the run's workspace and store the path — design your Concepts so that reads naturally.

### `Op`

The unit of computation. Every Op has typed `Input`, `Output`, and an `Intent` string. Leaf Ops have no `body` and become an LLM dispatch. Composition Ops have a `body` built from combinators and never dispatch themselves — only their leaves do.

**Minimal leaf Op:**

```python
from clops import Op
from my_company_ops.concepts import UserMessage, Intent

class ClassifyIntent(Op):
    Input = UserMessage
    Output = Intent
    Intent = "Classify a customer support message as billing, technical, or general."
```

That's complete. Runnable as a process. Additive fields below are optional.

**All Op fields:**

| Field | Type | Purpose |
|---|---|---|
| `Input` | `Concept` subclass | Required. What this Op consumes. |
| `Output` | `Concept` subclass | Required. What this Op produces. |
| `Intent` | `str` | Required. Purpose + anti-scope + success criteria. |
| `Uses` | `list` of `Snippet` \| `Op` | Pinned references (by ID). |
| `Requires` | `list` of `SnippetRole` | Role-based soft declarations. |
| `Tools` | `list` of `Tool` | External capabilities available to this Op. |
| _`name`_ `= Store(T)` | `Store` attribute | Run-scoped state. Composition Ops only. |
| `Resolve` | `dict[str, resolver spec]` | Pre-computed queries evaluated before dispatch. |
| `Examples` | iterable | Few-shot demonstrations. |
| `Model` | `str` \| `None` | Optional model override. |
| `body` | combinator tree | Absent on leaves; present on compositions. |
| `entry` | `bool` | Marks an Op as a top-level entry point. |
| `exit` | `bool` | Marks an Op as a final exit point. |
| `before_run` / `after_run` | callables | Rails-style callbacks. |

**Rules enforced at class definition (metaclass, hard errors):**
- `Input` and `Output` must be Concept subclasses.
- `Intent` must be a non-empty string.

**Rules enforced by the linter (soft warnings):**
- `Intent` around 1000–2000 characters.
- `Uses + Requires` around 10 total entries.
- `Tools` around 10 entries.
- `body` around 10–15 Op references.
- `Snippet.content` around 500–1000 characters.

Warnings don't block. They exist to make you feel the friction when an Op is getting too big — at which point split it or keep going with intent.

### Composition combinators

Inside `body`:

```python
from clops import sequence, branch_on, gather, loop

body = sequence(OpA, OpB, OpC)

body = branch_on(
    key=lambda intent_output: extract_category(intent_output),
    arms={
        "billing":   HandleBilling,
        "technical": HandleTechnical,
        "general":   HandleGeneral,
    },
)

body = gather(OpA, OpB, OpC)  # concurrent, all must complete

body = loop(OpA, until=lambda output: is_done(output))

body = sequence(
    ClassifyIntent,
    branch_on(
        key=lambda intent: intent["category"],
        arms={"billing": HandleBilling, "technical": HandleTechnical},
    ),
)
```

### Resolve — pre-computed store queries

Leaf Ops can declare `Resolve` to pull values from stores before dispatch. The resolved values are injected into the subagent's prompt alongside the input.

```python
class ExecuteWork(Op):
    Input = TaskAssignment
    Output = TaskResult
    Intent = "Execute one task from the backlog."
    Resolve = {
        "current_task": {"store": "tasks", "op": "get", "bind": {"id": "input.task_id"}},
    }
```

Each entry maps a name to a store operation. `bind` substitutes values from the input — `"input.task_id"` reads `task_id` from whatever the upstream Op produced. The resolved value appears in the prompt under the name `current_task`, so the subagent sees it without needing to call `mcp__clops__state` first.

Use Resolve when the Op needs specific store data to begin work. Don't use it for exploratory reads — let the agent call `mcp__clops__state` interactively for those.

### The `.clops` project file

The `.clops` file in the project root lists libraries, external sources, and constants:

```
# Plain module names (already importable).
my_ops
clops.example_library.core

# Libraries from a local path (installed via uv --with).
work_ops @ ~/work/work-ops

# Libraries from a git repo (installed via uv --with).
team_ops @ git+https://github.com/company/team-ops

[constants]
project_name = Acme Support
max_retries = 3
escalation_email = support-leads@acme.com
```

The `module @ source` syntax tells `clops init` to generate `uv run --with source` in the project's `.mcp.json`. This is how you use libraries from separate repos without `pip install` — `uv` handles installation from the path or git URL automatically.

Run `clops init --library "work_ops @ ~/work/work-ops"` to add an entry and regenerate the MCP config.

**Constants** are registered as read-only scalar stores, accessible via `mcp__clops__state` like any other store but not writable. They are available to all Ops in every run — useful for configuration values that agents need during reasoning without hardcoding them in Intent strings or Snippets.

**Phase 2 status:** `sequence`, `branch_on`, `loop`, and `gather` execute. `need()` routes to main thread as of slice 04. See `phase-2-spec.md` for live status. `gather` requires the main thread to issue N parallel Agent calls — the clops-orchestration skill teaches this automatically.

**Rules for `branch_on` keys:** the key function receives the upstream Op's output (prose, dict, or whatever the agent produced). Write a lightweight parser — string match, regex, lookup on a known-structured field. Don't assume schema. If parsing is painful, insert a dedicated extraction Op upstream.

---

## How an Op's prompt gets assembled

The framework dispatches a leaf Op by rendering a prompt from:
1. `Intent` (your docstring — the "what and why")
2. `Uses` snippets (rendered as policy sections)
3. `Requires` snippets (resolved by role, same treatment)
4. `Input` Concept description ("What you'll receive")
5. `Output` Concept description ("What you'll produce")
6. The run's workspace, and the rule that long results go in a file there rather than travelling inline (unless `[runtime] workspace = off`)
7. `Resolve` values (pre-fetched store data, rendered inline)
8. Store summaries (scalar values inline; collections as count/key summaries)
9. Exit conditions (`complete(execution_id, output)` / `need(execution_id, reason)`)
10. The actual input value

You don't write the prompt. You write the source; the framework assembles. This is deliberate: source expresses intent, not prompt text.

**What this means for authoring:**
- Write `Intent` to describe purpose + anti-scope + success criteria. It's the single biggest lever over behavior.
- Use Concept `description`s to shape expectations. Not schemas — prose. "The first line is the category; the rest is reasoning" is fine.
- Use Snippets for concerns that span Ops (safety rules, brand voice, format conventions).
- Don't try to pack everything into `Intent`. Extract into Snippets when the same concern shows up twice.
- Use Stores when Ops in a composition need to share evolving state (task lists, accumulated findings, running notes). The agent reads and writes stores via `mcp__clops__state`; mention in `Intent` which stores exist and when the agent should consult them.

---

## Testing your library

Phase 1b ships no CLI yet. Authoring testing is plain pytest against the importable runtime.

```python
# tests/test_classify_intent.py
from clops.runtime import Runtime
from my_company_ops.ops.classify_intent import ClassifyIntent

def test_classifies_billing(registry_loaded):
    rt = Runtime()
    dispatch = rt.start("ClassifyIntent", {"content": "double charged"})
    assert dispatch["action"] == "dispatch"
    # Manual persona that mimics what a subagent would do:
    rt.complete(dispatch["agent_config"]["_metadata"]["execution_id"], "billing: high confidence")
    result = rt.step_complete(dispatch["run_id"], "billing: high confidence")
    assert result["action"] == "done"
```

For real behavior validation against actual LLM dispatches, use the framework's integration hooks (Phase 1b spec, section "Integration test"). Don't try to unit-test LLM output.

**Linter:** the linter is importable; run it from a pytest fixture or your library's `__init__.py` during tests.

```python
from clops.linter import check_library
from clops.linter import Severity

def test_library_lints_clean():
    result = check_library("my_company_ops")
    assert not result.errors
    # warnings are fine
```

Or from the CLI (Phase 3 slice 01):

```bash
clops lint my_company.ops
# [OK] 5 Ops registered (...). No lint findings.
```

Exits non-zero on any error-level finding, making it suitable for pre-commit or CI.

## Exploring an existing library

`clops show <pkg>` prints a library's shape — Ops (entry-tagged first), composition body trees, snippets, tools. Useful for orienting in a library you didn't write:

```bash
clops show examples.my_company
# Ops (3):
#   HandleSupport  [ENTRY]
#     body:
#       └─ sequence
#         └─ ClassifyIntent
#         └─ DraftResponse
#   ClassifyIntent
#     ...
```

Reads the registry only; no side effects on disk.

---

## Patterns and anti-patterns

### Do

- **Write bare Ops first.** `Intent + Input + Output` is complete. Ship it. Add `Uses` / `Requires` / `Tools` when you hit the concrete need.
- **Extract Snippets from repetition.** When two Ops need the same policy paragraph, promote it to a module-level Snippet.
- **Name Concepts after what they _are_,** not how they're structured. `Intent`, not `IntentDict`. `DraftResponse`, not `ResponseJSON`.
- **Use `sequence` for linear flows,** `branch_on` for category-driven flows, `gather` for fan-out, `loop` for iteration until satisfied.
- **Write `Intent` for a colleague, not a model.** Plain prose, clear anti-scope.
- **Declare Stores on the outermost composition.** Child Ops inherit access automatically. Prefer one composition owning the store over duplicating state across siblings.
- **Use Resolve for data the Op needs up front.** If a leaf Op always needs a specific record from a store to start work, declare it in `Resolve` rather than instructing the agent to fetch it manually.
- **Mention stores in Intent.** The agent needs to know stores exist and what they're for. A sentence like "The `tasks` store contains the current backlog; update task status as you complete each one" is enough.
- **Use constants for project-level config.** Company names, thresholds, and contact info belong in `.clops` `[constants]`, not hardcoded in Intent strings.
- **Mark top-level Ops with `entry=True`** — this is the **procedure tag**. Only entry-tagged Ops appear in `list_processes` and only they can be started by the main thread through `start_process`. Internal / composition-only Ops are invisible to the MCP surface by design. The MCP doesn't expose one tool per Op; the procedure catalog _is_ the extension point.

### Don't

- **Don't invent schemas.** Concepts are name + description. No Pydantic, no JSON schema, no `@dataclass`. The agent produces prose; the runtime stores it as-is.
- **Don't write prompt text in source.** Intent expresses purpose. The framework assembles the prompt. If you find yourself writing instructions _to the model_, you're writing a Snippet.
- **Don't stuff everything into one Op.** The soft limits are friction, not prohibitions; heed the friction.
- **Don't rely on `branch_on` reading structured output without a key function.** The key is your parser.
- **Don't add Tools speculatively.** Only add when an Op actually needs external data.
- **Don't use Stores for ephemeral data that flows naturally between Ops.** If Op A produces output and Op B consumes it in a sequence, that's Input/Output, not a store. Stores are for state that accumulates across multiple steps or that multiple Ops read/write independently.
- **Don't design an Op around a long value in a store.** Stores are summarised into every prompt that can see them. If a step produces a report, a transcript, or a big list, the agent will write it to a file in the run's workspace and store the path; write your Concept descriptions to expect a path, not the text.
- **Don't over-resolve.** Resolve is for data the Op needs before it starts reasoning. If the agent might or might not look something up, let it call `mcp__clops__state` interactively.

---

## Canonical example

The reference library lives at `examples/my_company/` in the framework repo. Read it start-to-finish before writing your first Op library.

```
examples/my_company/
├── concepts.py          — UserMessage, Intent, Response
├── snippets.py          — safety_rules (shared), brand_voice (role)
├── tools.py             — query_customer_history
└── ops/
    ├── classify_intent.py   — leaf Op with Uses, Requires, Tools
    ├── draft_response.py    — leaf Op
    └── handle_support.py    — composition Op: sequence(ClassifyIntent, DraftResponse), entry=True
```
