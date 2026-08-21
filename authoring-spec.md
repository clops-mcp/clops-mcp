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

**Fields.** A Concept may optionally declare `Field`s to sketch its structure. A Field is a name plus prose — there is no type parameter, and the renderer flattens one level rather than recursing into nested Concepts.

```python
from clops import Concept, Field

class Task(Concept):
    description = "A work item."

    name = Field("The task name")
    status = Field("One of: pending, in_progress, done")
    assignee = Field("Who is working on this", required=False)
```

Fields render into the dispatched prompt under "What you'll receive" / "What you'll produce" as `- name (required): description`. They are guidance for the agent, not runtime validation — nothing checks that the produced value actually has them.

**A composite field's description must be self-sufficient — and self-sufficiency is not a licence to request bulk.** Both halves matter, and authors reliably take the first and miss the second. Because there is no type and no recursion, a field describing a composite shape has to carry that shape in its own prose; from that constraint it is easy to infer that a good field description is a long one. It isn't. A description of the form _"for each X: a, b, c, d"_ over an unbounded collection is not describing a field — it is instructing the agent to emit a large array inline, and that array then has to travel back through `complete()` on the relay.

**Don't — an Output field that instructs the agent to emit an unbounded array inline:**

```python
class Output(Concept):
    description = "The characterised flows."

    flows = Field("for each flow: the name, the expression that supplies it, "
                  "where the value comes from, and the code evidence")
```

**Do — a manifest on the relay, bulk behind a handle:**

```python
class Output(Concept):
    description = "A manifest of the characterised flows."

    handle = Field("the spill handle holding the full flow records")
    flow_count = Field("how many records are behind the handle")
    flow_ids = Field("the ids, so the consumer can assert coverage")
    verdict = Field("your judgment: what the set shows, and what is missing")
```

Nothing about the first version is malformed — it is a well-written field, and the agent emitting a large array is the specified behaviour, not a bug. That is exactly why it is worth naming: the cost shows up downstream, in a relay that was never good at payload. See [Keeping the relay thin](#keeping-the-relay-thin).

**Thin by construction is the default.** Ids, counts, verdicts, and a handle on the relay; bulk behind the handle. Reach for an inline collection only when it is bounded and small — a category, a five-item checklist, a verdict per named service.

**Declare a count alongside every collection, and assert it on receipt.** A count is the cheapest possible integrity check: the producer says 25, the consumer receives 7 and fails loudly instead of proceeding on a short set it had no way to notice. Give the consuming Op a Field for the expected count and say in its `Intent` that a mismatch is a hard stop, not a note.

**`bulk=True` marks a field as carrying an unbounded collection:**

```python
class Output(Concept):
    description = "A manifest of the characterised flows."

    handle = Field("the spill handle holding the full flow records")
    flow_count = Field("how many records are behind the handle")
    flows = Field("the full flow records", bulk=True)
```

The marker is a declaration, and two things act on it. The renderer appends an instruction to relay a reference and a count for that field rather than its contents, and to disclose in as many words when fewer items are relayed than were found. The linter warns (`output_bulk_only`) when an Op's Output declares *nothing but* bulk fields — at which point the relay carries pure payload with nothing thin for the consumer to assert against.

Marking a field `bulk=True` is not a way to make bulk safe to relay. It is a way to say out loud that this field is bulk, so the prompt and the linter can push back.

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
- `Output` declares nothing but `bulk=True` Fields (`output_bulk_only`) — the relay would carry pure payload.

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

[runtime]
output_contract = manifest
```

The `module @ source` syntax tells `clops init` to generate `uv run --with source` in the project's `.mcp.json`. This is how you use libraries from separate repos without `pip install` — `uv` handles installation from the path or git URL automatically.

Run `clops init --library "work_ops @ ~/work/work-ops"` to add an entry and regenerate the MCP config.

**Constants** are registered as read-only scalar stores, accessible via `mcp__clops__state` like any other store but not writable. They are available to all Ops in every run — useful for configuration values that agents need during reasoning without hardcoding them in Intent strings or Snippets.

**Runtime settings** live under `[runtime]`. `output_contract` governs what a leaf writes back through `complete()`: `full` (the default) serialises the whole Output; `manifest` has the agent hold its Output and reply with a one-line manifest instead. See [Keeping the relay thin](#keeping-the-relay-thin).

**Phase 2 status:** `sequence`, `branch_on`, `loop`, and `gather` execute. `need()` routes to main thread as of slice 04. See `phase-2-spec.md` for live status. `gather` requires the main thread to issue N parallel Agent calls — the clops-orchestration skill teaches this automatically.

**Rules for `branch_on` keys:** the key function receives the upstream Op's output (prose, dict, or whatever the agent produced). Write a lightweight parser — string match, regex, lookup on a known-structured field. Don't assume schema. If parsing is painful, insert a dedicated extraction Op upstream.

---

## Keeping the relay thin

Every leaf dispatch ends with the agent calling `complete(execution_id, output)`, and that value travels back to the runtime as the **relay**. The relay is good at judgments and references. It has never been good at payload: a long composition accumulates state, prompts grow as it goes, and an oversized output gets cut in transit. Worse, the cut is not always announced — a step that quietly relays 20 of the 30 records it characterised is indistinguishable from a step that found 20.

So size the Output contract deliberately. Three habits, in order of leverage.

**1. Manifest on the relay, bulk behind a handle.** Write the bulk somewhere durable, hand back a reference. A handle plus a count plus a verdict is tens of bytes where the records were kilobytes, and the consumer fetches exactly the slice it needs rather than being handed the whole set on the relay and reading whatever survived the trip.

```python
spill_payload = Tool(
    name="spill_payload",
    description=(
        "Write a large result to disk and get back a short handle. Use this "
        "whenever your output is bulky — an artifact array, an inventory, a "
        "violation list. Then relay the handle, the item count and your "
        "judgment through complete(), and let the next step read the bulk "
        "with read_spill. The relay is for references and conclusions."
    ),
    parameters={"run_id": str, "label": str, "payload": dict},
    handler=_spill_payload,
)

read_spill = Tool(
    name="read_spill",
    description=(
        "Read a spilled payload by handle, a page at a time. Always states "
        "how much of the whole it is showing and how to get the rest, so a "
        "partial read can never be mistaken for the complete set."
    ),
    parameters={"run_id": str, "handle": str, "offset": int, "limit": int},
    handler=_read_spill,
)
```

Have `spill_payload` return `{handle, bytes, item_count, sha256}` — the count and the digest are what let a consumer prove it got the whole thing. Bulk that is genuinely *state* rather than a one-hop handoff belongs in a `Store` instead; the same discipline applies to reading it back.

**2. Always label an elision.** Any tool or store read that returns a window must say it is a window: `"showing": "showing 1-4 of 45"`, plus an `elided` flag and a hint for fetching the rest. Never return an unlabelled prefix. An agent handed four entries with no indication that forty-one more exist will treat those four as its whole input — and the cheaper the model, the more reliably it draws that inference. `_read_file` in `clops/example_library/code_review/tools.py` is the shape to copy: it caps its output and names the line it stopped at, so the caller can re-read the rest in slices.

**3. Declare a count and assert it on receipt.** Cheap, and it converts a silent short set into a hard failure. The producer declares 25; the consuming Op has a Field for the expected count and an `Intent` that says a mismatch stops the step rather than annotating it.

### The `output_contract` runtime setting

The framework has one global lever here. In the project's `.clops`:

```
[runtime]
output_contract = manifest
```

Under `manifest`, a leaf's prompt asks the agent to *hold* its Output and reply with a one-line manifest of what it is holding, rather than serialising the whole thing back — the harness already carries the real result, and later steps pull the specifics they need. The runtime still asks for the real value wherever a `branch_on` key, a `loop` predicate, or the run's terminal output consumes it in-band. The default is `full`.

`manifest` is a run-wide default, not a substitute for a thin Output contract. An Output whose fields instruct the agent to produce an unbounded array still produces one; the manifest setting only changes what gets written back on that hop.

### A store write instructed in prose is a request, not a guarantee

This one has the widest blast radius, because it looks like durability and isn't. Telling an Op in its `Intent` or a `Snippet` to append its findings to a store is **advisory**. The agent may call `mcp__clops__state`; it may also not, and nothing in the runtime can tell the difference. Static ordering can be entirely correct while the store stays empty across every snapshot of the run.

So:

- Don't build an Op-level guarantee on a store write that depends on the model choosing to make it. If three parallel branches are each told to append and the consumer needs all three, the consumer needs a way to detect two.
- Give the consumer a count or an id set to check against, and make the mismatch fatal in its `Intent`.
- Where the data must not be lost, prefer a path the runtime executes rather than one the agent elects: a `Tool` whose `handler` performs the write as a side effect of work the agent has to do anyway is a real write; a sentence asking for one is a request.

---

## How an Op's prompt gets assembled

The framework dispatches a leaf Op by rendering a prompt from:
1. `Intent` (your docstring — the "what and why")
2. `Uses` snippets (rendered as policy sections)
3. `Requires` snippets (resolved by role, same treatment)
4. `Input` Concept description ("What you'll receive")
5. `Output` Concept description ("What you'll produce")
6. `Resolve` values (pre-fetched store data, rendered inline)
7. Store summaries (scalar values inline; collections as count/key summaries)
8. Exit conditions (`complete(execution_id, output)` / `need(execution_id, reason)`)
9. The actual input value

You don't write the prompt. You write the source; the framework assembles. This is deliberate: source expresses intent, not prompt text.

**What this means for authoring:**
- Write `Intent` to describe purpose + anti-scope + success criteria. It's the single biggest lever over behavior.
- Use Concept `description`s to shape expectations. Not schemas — prose. "The first line is the category; the rest is reasoning" is fine.
- Size the `Output` Concept deliberately. Its Fields are the instruction the agent follows, and whatever they ask for has to travel back on the relay. Ask for a manifest, not a payload — see [Keeping the relay thin](#keeping-the-relay-thin).
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
- **Mention stores in Intent.** The agent needs to know stores exist and what they're for. A sentence like "The `tasks` store contains the current backlog; update task status as you complete each one" is enough to make the store *discoverable* — but see the Don't below: it does not make the write happen.
- **Keep Outputs thin.** A manifest — ids, counts, a verdict, and a handle — belongs on the relay; bulk belongs behind the handle. Inline a collection only when it's bounded and small. See [Keeping the relay thin](#keeping-the-relay-thin).
- **Declare a count alongside every collection, and assert it on receipt.** The producer says 25, the consumer receives 7 and stops. Without the count, a short set is indistinguishable from a complete one.
- **Label every elision.** A tool or store read that returns a window must say so — "showing 1-4 of 45", plus how to get the rest. Never an unlabelled prefix.
- **Use constants for project-level config.** Company names, thresholds, and contact info belong in `.clops` `[constants]`, not hardcoded in Intent strings.
- **Mark top-level Ops with `entry=True`** — this is the **procedure tag**. Only entry-tagged Ops appear in `list_processes` and only they can be started by the main thread through `start_process`. Internal / composition-only Ops are invisible to the MCP surface by design. The MCP doesn't expose one tool per Op; the procedure catalog _is_ the extension point.

### Don't

- **Don't invent schemas.** Concepts are name + description. No Pydantic, no JSON schema, no `@dataclass`. The agent produces prose; the runtime stores it as-is.
- **Don't write prompt text in source.** Intent expresses purpose. The framework assembles the prompt. If you find yourself writing instructions _to the model_, you're writing a Snippet.
- **Don't stuff everything into one Op.** The soft limits are friction, not prohibitions; heed the friction.
- **Don't rely on `branch_on` reading structured output without a key function.** The key is your parser.
- **Don't add Tools speculatively.** Only add when an Op actually needs external data.
- **Don't use Stores for ephemeral data that flows naturally between Ops.** If Op A produces output and Op B consumes it in a sequence, that's Input/Output, not a store. Stores are for state that accumulates across multiple steps or that multiple Ops read/write independently.
- **Don't over-resolve.** Resolve is for data the Op needs before it starts reasoning. If the agent might or might not look something up, let it call `mcp__clops__state` interactively.
- **Don't write an Output field of the form _"for each X: a, b, c, d"_ over an unbounded collection.** That's a payload field, and it will be relayed. It is well-formed and it is still the wrong shape — spill the bulk and relay a handle, a count and your judgment instead.
- **Don't mistake a long field description for a good one.** A composite field's description has to be self-sufficient, because there's no type parameter and the renderer doesn't recurse. Self-sufficiency is about being unambiguous, not about asking for more.
- **Don't treat a store write instructed in prose as a durability mechanism.** Asking an Op to append to a store is a request the model may decline, silently. If the write has to happen, run it from a `Tool` handler and give the consumer a count to check.

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
