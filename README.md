<!-- mcp-name: io.github.clops-mcp/clops-mcp -->

# clops

Long-running, multi-step Claude Code workflows, written in Python and run one
focused step at a time.

## The problem

You write a skill for a workflow you run every week. It works. Then you add the
edge cases, the exceptions, the "don't forget to check X" — and it stops
working. Claude cheats the steps it finds boring. It forgets details buried in
the middle. It overcorrects on whatever you emphasised last. The more detail you
add to make it reliable, the less reliable it gets, because the entire document
is in context the entire time and Claude has to keep deciding, unprompted, which
part applies right now.

clops inverts that. Each step of the workflow is a separate **Op** with its own
prompt, its own input, and its own subagent. The runtime decides which Op runs
next and renders the prompt for it. The agent doing the work sees one step's
worth of instruction — not the workflow.

The whole goal of clops is to help Claude think about what it needs to think
about right now, and not a whole lot else.

The payoff compounds: a workflow you get right once stays right, and you can
compose it into bigger ones instead of rewriting it. Your workflows stop being
disposable.

## What this is not

**This is not an agent framework.** clops has no API key, no provider SDK, and
no model calls of its own. It runs inside Claude Code, which supplies the model
and the subagents. If what you want is durable execution, retries, and
observability for unattended production agents, you want LangGraph or Temporal,
not this.

**This is not for unattended work.** clops targets interactive and
semi-interactive workflows — the ones where you are in the loop, or will be
shortly. The value is *preparation*: the machine spends twenty minutes building
context, and when your attention arrives the work is ready to go. If nobody is
coming back, clops buys you nothing.

## Why not just write a skill?

| Objection | Answer |
|---|---|
| "Just write a skill." | A detailed skill is one long document Claude must self-apply. clops hands the agent one step at a time, with only that step's context. |
| "Skills and slash commands are simpler." | They are, until you have twenty of them. A clops Op library of any size adds **zero** MCP tools — the surface is fixed at 12. Two hundred Ops do not crowd the namespace. |
| "Isn't that the same thing?" | Invocation is explicit: *run the dev workflow*, *run the support triage*. It runs the same way each time without you re-steering it. |
| "Where does the reliability come from?" | Structure the model can't skip. Sequencing, branching, and state live in Python and are walked by the runtime, not inferred by an agent reading instructions. |

## How it works

Worth stating plainly, because it is backwards from most MCP servers: **clops
drives Claude Code, not the other way round.**

1. You ask Claude to run a process. It calls `start_process` on the clops MCP
   server.
2. The runtime walks your composition, picks the next leaf Op, and returns a
   **fully rendered prompt** plus a dispatch instruction.
3. Claude Code's main thread relays: it spawns the `clops-executor` subagent
   with that prompt verbatim. It does not write the prompt, choose the step, or
   see the rest of the workflow.
4. The subagent does the work and calls `complete(execution_id, output)`.
5. The main thread calls `step_complete(run_id)`. The runtime advances and
   returns the next dispatch — or `done`.

The main thread holds a `run_id` and a relay loop. Flow state, step selection,
prompt assembly, and shared storage all live in the runtime. That is the whole
trick: the thing that forgets is never the thing keeping track.

A real `start_process` payload, from a freshly scaffolded library:

```
action: dispatch | agent_template: clops-executor
prompt:
  # Echo
  ## Your task
  Echo the greeting back, prefixed with 'echo: '.
  ## What you'll receive
  Greeting: A short greeting from the user.
  ## Exit conditions
  Your execution_id is `exec_fcc7187c`. Pass it on every call.
  ...
```

## Install

Two ways in. Pick one — doing both registers the MCP server twice.

Both need [uv](https://docs.astral.sh/uv/). Nothing needs a global Python
install; `uvx` fetches clops on demand.

### A. Plugin (Claude Code, one command)

```bash
claude plugin marketplace add clops-mcp/clops-mcp
claude plugin install clops@clops
```

That is the whole install. The plugin carries the MCP server, the
`SubagentStop` hook, the orchestration skill and the `clops-executor` agent, so
there is nothing to wire up. Restart Claude Code, then tell each project which
Op libraries it uses:

```bash
mkdir demo && cd demo
uvx --from clops-mcp clops init --plugin \
  --library clops.example_library.session_analyzer
```

`--plugin` writes only `.clops` — the library list is the one thing a global
server cannot know. Restart again and the server picks it up.

### B. Per-project (any MCP client)

Use this outside Claude Code, or when you want the wiring committed to the repo
so a fresh clone needs nothing but `uv`.

```bash
uv tool install clops-mcp

mkdir demo && cd demo
clops init --library clops.example_library.session_analyzer
```

`init` writes `.mcp.json` (the server, invoked through `uvx`), `.clops` (the
library list), the `SubagentStop` hook in `.claude/settings.json`, the
`clops-executor` agent, the orchestration skill, and a `.gitignore` line for the
runtime's scratch directory.

To register the server by hand instead — in Cursor, Zed, or behind a gateway:

```json
{
  "mcpServers": {
    "clops": {
      "command": "uvx",
      "args": ["clops-mcp"]
    }
  }
}
```

With no `--library`, the server reads `.clops` from the project directory.

> **Mind the distribution name.** It is **`clops-mcp`**; the import package and
> the CLI are both `clops`. `pip install clops` gets you an unrelated project.

## Quickstart

**Look at what you got.**

```bash
clops show clops.example_library.session_analyzer
```

```
Ops (6):
  AnalyzeSession  [ENTRY]
    Input:    SessionTranscript
    Output:   ImprovementPlan
    body:
      └─ sequence
        └─ ParseTranscript
        └─ FindInflectionPoints
        └─ ExtractThinkingContext
        └─ EvaluateThinkingEffectiveness
        └─ EncodeAsPriming
  ...
```

**Run it.** Open `claude` in that directory and ask:

```
Run the AnalyzeSession process on my latest session.
```

Claude loads the orchestration skill, calls `start_process`, and relays five
dispatches — one per Op in the sequence — reporting the final `ImprovementPlan`
when the run completes.

### Or start your own library

```bash
clops new-library my_ops                       # scaffolds an installable package
clops init --library "my_ops @ ./my_ops"       # wires it into the project
PYTHONPATH=./my_ops clops lint my_ops          # check it
PYTHONPATH=./my_ops clops show my_ops          # see its shape
```

`new-library` writes a real Python package (`pyproject.toml`, `concepts.py`,
`ops.py`) with one working demo Op. The `module @ source` form in `--library`
tells `init` to pull the library in via `uv --with` at server start, so nothing
needs to be pip-installed for the *runtime* to see it.

`lint` and `show` are a different story: they run in whatever environment the
`clops` CLI lives in, so an uninstalled library has to be put on the path.
`PYTHONPATH=./my_ops` is the quick way; `pip install -e ./my_ops` into your
project's venv is the durable one.

## Writing an Op

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

Three things to notice:

- **`PlanTasks` and `ExecuteTasks` have no `body`.** An Op without a body is a
  *leaf*: it becomes one subagent dispatch. An Op with a body is a
  *composition*: it is never dispatched at all, it only tells the runtime what
  order to walk in.
- **`Intent` is the prompt.** `Meta` is why the Op exists — required on every
  Op, so a library explains its own design to whoever inherits it (including
  the next agent).
- **`Concept` and `Field` are descriptions, not schemas.** Nothing validates the
  runtime value; it is whatever the producing agent produced. The descriptions
  are rendered into the prompt so the agent knows what it is receiving and what
  to hand back.

What *is* enforced is the declaration. `OpMeta` raises `TypeError` at
class-definition time if `Intent`, `Meta`, `Input`, or `Output` is missing or
the wrong shape — the import fails, not the run. `clops lint` covers the
cross-artifact checks a metaclass can't see: unresolvable snippet roles,
unregistered references, oversized Intents.

### The primitives

| | |
|---|---|
| **Concept** | A named, described handle for data flowing between Ops. |
| **Snippet** | Reusable prompt text — policy, format rules — pinned by reference or resolved by role. |
| **Tool** | A Python function an Op's subagent can call mid-reasoning. Not a Claude Code tool. |
| **Store** | Run-scoped mutable state shared across a composition's steps. TinyDB-backed. The declared type (`str`, `list[X]`, `dict[str, X]`) selects which operations the agent gets. |
| **Op** | The unit of computation. Leaf or composition. |

Compose with `sequence`, `branch_on`, `gather`, and `loop`. `gather` surfaces
its branches as a single parallel dispatch round; the rest are what they sound
like.

## What's rough

Version 0.4.4, alpha, one author. Specifically:

- **The orchestrator is an LLM following a skill.** It is asked not to
  improvise, and mostly it doesn't, but "semi-deterministic" is the honest word.
  The structure is enforced; the relay is a well-behaved convention.
- **Stores are run-scoped.** State exists for the duration of a run and is gone
  after. There is no persistence between runs.
- **Claude Code only.** clops needs an MCP server, subagents, and the
  `SubagentStop` hook working together. No other host is supported.
- **`sequence` is a strict pipeline.** Each step sees only the previous step's
  output — there is no implicit access to the run's original input from step
  five. If a later Op needs something from the top, an earlier Op has to put it
  in a `Store`. This catches people out; design for it.
- **No shared library registry.** The bundled examples ship four libraries — `core`,
  `code_review`, `session_analyzer`, `business_designer` — and they are
  demonstrations, not products. `business_designer` needs you to supply a
  `landscape_intelligence` Snippet before two of its Ops will dispatch, and
  `code_review`'s per-file assessment step doesn't yet receive the diff it is
  meant to assess (see the pipeline note above). Beyond that you write your own.
- **Long-form docs are still being written.** `authoring-spec.md` is the
  reference for now. Where anything written disagrees with the code, the code is
  right. File an issue.

## Documentation

| Doc | What it covers |
|-----|---------------|
| [Authoring Spec](https://github.com/clops-mcp/clops-mcp/blob/main/authoring-spec.md) | Full authoring reference — the five primitives, combinators, and the rules the linter enforces |

The link is absolute so it also resolves from the PyPI project page.

## CLI

```bash
clops init --library <lib>   # set up a project for clops
clops new-library <name>     # scaffold a new Op library package
clops lint <library>         # validate a library
clops show <library>         # print a library's shape
```

All four are non-interactive. `init` merges into an existing `.clops` and
`.claude/settings.json`, and `new-library` refuses to overwrite an existing
directory without `--force`.

> **`clops init` overwrites `.mcp.json` wholesale.** If your project already
> registers other MCP servers there, back the file up and merge the `clops`
> entry back in by hand. This is a known rough edge, not intended behaviour.

## Project configuration

`clops init` writes a `.clops` file listing the project's libraries. You can
add constants and standing guidance:

```
# Libraries
my_ops
work_ops @ ~/work/work-ops
team_ops @ git+https://github.com/company/team-ops

[constants]
user_id = wes-dev-123
database = staging

[system_prompt]
Prefer the strongest agent for design and review steps; use lighter
agents for mechanical edits.
```

Constants are registered as read-only stores on every run and appear in every
Op's prompt. `[system_prompt]` is standing direction for the *orchestrator* —
guidance on how to size the agent it dispatches to a given step — not for the
leaf agents. Omit it and a small built-in default applies.

## What the plugin contains

Install instructions are up in [Install](#a-plugin-claude-code-one-command);
this is what you get.

| Component | What it does |
|---|---|
| MCP server `clops` | `uvx clops-mcp`, no `--library` — it reads each project's `.clops` |
| `SubagentStop` hook | Forwards the stop payload to the run's socket so the runtime sees step completion |
| Skill `clops-orchestration` | The dispatch relay loop |
| Agent `clops-executor` | The subagent template each step is dispatched to |

Four components, one skill among them. It stays thin because every payload the
server returns carries a `next_step` field spelling out what the caller has to
do with it. The relay is self-describing, so the skill is a convenience rather
than a dependency — which is also why clops works unchanged through a gateway,
where nothing has copied a skill file anywhere.

**Do not run plain `clops init` with the plugin installed.** You would get two
MCP servers both called `clops` and the hook firing twice. Use
`clops init --plugin`, which writes only `.clops`.

## From source

```bash
git clone https://github.com/clops-mcp/clops-mcp
cd clops-mcp
uv sync
uv run pytest
```

> Installing from a fork or a pinned tag? Set `CLOPS_INSTALL_SPEC` before
> running `clops init` — e.g.
> `export CLOPS_INSTALL_SPEC='git+ssh://git@github.com/clops-mcp/clops-mcp'` —
> and `init` bakes it into the generated `.mcp.json` and hook.

## Sharing Ops

An Op library is just a Python package, and `clops new-library` scaffolds a
publishable one. If you write something generally useful, publish it like any
other package; another project picks it up with a one-line `.clops` entry
pointing at a path, a git URL, or a distribution name. There is no registry and
no central index — this is a nice-to-have, not the point. The point is that your
own workflows accumulate.

## License

Apache-2.0. See [LICENSE](LICENSE).
