# Smoke-test reference for agents

_Read this first if you're helping run or author a clops smoke test. This doc is the only context you need beyond the scenario folder you're working in._

---

## What smoke tests are (and aren't)

Smoke tests are **human-judgment validations of the live runtime through a real Claude Code session.** They sit between Layer 2.5 simulated E2E (deterministic, no LLM, in CI) and Layer 3 free-form behavior testing. Goals:

- Prove the runtime works end-to-end against an actual Claude Code main thread + Agent tool + SubagentStop hook.
- Use the human operator's existing Claude Max subscription — no API spend.
- Be repeatable: any operator on any clean machine should get the same outcome by following the scenario.
- Be quick to execute (minutes, not hours) and quick to author (one Op, one prompt, one expected outcome).

What they are **not**:

- Not unit/integration tests. Those live in `tests/` and run in CI.
- Not LLM-quality tests. We don't grade prose. We check that the right tool calls happen and the right state transitions follow.
- Not exhaustive. Each scenario tests one shape (single leaf, composition, tool use, need path, etc.). The full coverage matrix lives at the simulated layer.

If you're in a smoke-test Claude Code session, you are the **operator's instrument** — execute the scenario as written, observe, report. Don't add steps. Don't optimize the prompt. Don't infer intent. Repeatability is the whole point.

---

## Layout convention

```
smoke-tests/
├── AGENTS.md                       ← this file
├── README.md                       ← one-time setup; index of scenarios
├── 01-hello-echo/
│   ├── SCENARIO.md                 ← the test definition (script + expected)
│   ├── library/                    ← Op library specific to this scenario
│   │   ├── pyproject.toml          ← installable mini-package
│   │   └── smoke_<n>_<slug>/
│   │       ├── __init__.py
│   │       ├── concepts.py
│   │       └── ops.py
│   └── .claude/
│       ├── settings.json           ← MCP + hook wired up; library path baked
│       └── agents/
│           └── clops-executor.md
├── 02-pipeline/
└── …
```

Every scenario folder is **self-contained**: the operator can `cd` into it, follow `SCENARIO.md`, and run the test without touching anything else.

---

## How to RUN a scenario (operator-side)

1. **One-time machine setup** (top-level `smoke-tests/README.md` covers it):
   - From the clops repo root: `uv tool install --editable .`
   - This puts `clops`, `clops-mcp`, and `clops-hook` on PATH.

2. **Per-scenario setup** (each `SCENARIO.md` repeats the exact commands):
   - `cd smoke-tests/<n>-<slug>/`
   - `pip install -e ./library` — install the scenario's Op library so its package is importable by the MCP server.

3. **Run the scenario:**
   - Open a fresh Claude Code session **in that folder** (`claude` from inside `smoke-tests/<n>-<slug>/`).
   - Paste the prompt from `SCENARIO.md` exactly as written.
   - Let the session run.
   - Compare the observed behavior against `SCENARIO.md`'s "Expected behavior" section.

4. **Record the result:**
   - Pass / Fail / Partial, with one-paragraph observation.
   - The operator's judgment is the source of truth.

---

## How to EXECUTE a scenario (agent-side)

If you are the Claude Code main thread in a smoke-test session:

1. **Read `SCENARIO.md` in the current folder.** Treat it as a script.
2. **Confirm the setup invariants** the SCENARIO.md lists (e.g. `mcp__clops__list_processes()` returns the expected entries). If any invariant fails, stop and report — don't try to repair.
3. **Execute the test prompt verbatim.** The clops-orchestration skill (auto-loaded via the `.claude/skills/` setup or the user's plugin) tells you how to relay clops MCP dispatches.
4. **Observe.** Track each MCP tool call, each Agent dispatch, each return.
5. **Report.** At the end, output a structured summary:
   ```
   Scenario: <n>-<slug>
   Result: pass | fail | partial
   Observed: <brief sequence of what happened>
   Expected: <what SCENARIO.md said should happen>
   Mismatches: <empty if pass; specific differences otherwise>
   ```

**Discipline:**
- Do not improvise. If something feels wrong, report it; don't fix it.
- Do not add tool calls beyond what the scenario and the clops-orchestration skill require.
- Do not editorialize. The operator wants to see exactly what the runtime did.
- If the runtime errors, surface the error — don't retry, don't paper over.

---

## How to AUTHOR a new scenario

When you (or the operator) need to add a scenario, follow this template:

### 1. Pick what you're testing

One architectural shape. Examples:
- A single leaf Op (the simplest dispatch).
- A `sequence` composition (verifies the relay loop across multiple dispatches).
- An Op that uses a Tool (verifies `call_tool` actually invokes the handler).
- An Op that calls `need` (verifies failure surfaces correctly).
- Two parent sessions interleaved (verifies hook discrimination — _harder to script manually; defer until needed_).

If you can't describe the shape in one sentence, split into multiple scenarios.

### 2. Write the smallest possible Op library

`library/smoke_<n>_<slug>/` is a normal Python package. Reference the existing `examples/my_company/` for the canonical shape. Keep it minimal:
- Only the Concepts you need.
- Only the Ops the scenario tests.
- Mark exactly one Op as `entry=True` — that's what the operator will invoke.
- Include a `pyproject.toml` so `pip install -e ./library` works.

### 3. Pre-wire `.claude/`

- `settings.json` — point the MCP server at your scenario's library:
  ```json
  {
    "mcpServers": {
      "clops": {
        "command": "uvx",
        "args": ["clops-mcp", "--library", "smoke_<n>_<slug>"]
      }
    },
    "hooks": {
      "SubagentStop": [{"type": "command", "command": "clops-hook"}]
    }
  }
  ```
- `agents/clops-executor.md` — copy from `clops/_plugin/agents/clops-executor.md`.
- (If plugin loading isn't reliable yet) `skills/clops-orchestration/SKILL.md` — copy from `clops/_plugin/skills/clops-orchestration/SKILL.md`.

### 4. Write `SCENARIO.md`

Required sections:

```markdown
# Scenario <n>: <slug>

## What this tests
<one sentence — the architectural shape being validated>

## Setup
<exact commands the operator runs from this folder>

## Prompt
> <the verbatim text the operator pastes into Claude Code>

## Expected behavior
<a step-by-step description of what should happen — MCP calls,
Agent dispatches, returns, final result. Specific enough that
"observed != expected" is unambiguous.>

## Pass criteria
<the operator's judgment call — what does success look like?>

## Common failure modes
<known things that can go wrong + what they look like>
```

Keep it tight. A SCENARIO.md should fit on one screen.

### 5. Verify the simulated layer covers the same shape

For every smoke scenario there should be a corresponding test in `tests/test_simulated_e2e.py` or `tests/test_simulated_e2e_adverse.py`. The simulated test is the deterministic safety net; the smoke test is the live-system check on top.

If you can't write a simulated counterpart, the scenario is probably too vague — sharpen it.

---

## Why this structure

- **Self-contained folders** mean the operator can run any scenario in isolation, drop a single folder if it goes stale, or copy a scenario as a starting point for a new one.
- **Agent-readable scripting** means the smoke runs aren't dependent on the operator remembering every step. The agent reads `SCENARIO.md`, executes, reports.
- **One shape per scenario** keeps each test cheap to author and cheap to debug. A failing smoke test points at exactly one architectural concern.
- **Pairing with simulated layer** means we never use smoke tests as the primary safety net — they're the live-judgment layer on top of deterministic coverage.

---

## Anti-patterns

- ❌ Multiple unrelated assertions in one scenario. Split.
- ❌ Vague "Expected behavior" sections like "Claude should respond appropriately." Be specific about MCP calls and dispatches.
- ❌ Scenarios that depend on a specific LLM output. Test mechanics, not prose quality.
- ❌ Scenarios that mutate state outside the scenario folder. Each scenario is its own world.
- ❌ "Helpful" agents that try to fix runtime issues during a smoke run. Report and stop.
