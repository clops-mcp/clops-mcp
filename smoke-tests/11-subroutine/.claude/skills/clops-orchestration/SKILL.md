---
name: clops-orchestration
description: Run a clops process — relay dispatches from the clops MCP server to subagents.
when-to-use: >
  When the user asks to run a clops process or workflow, when they ask what
  clops can do, or when a clops tool returns a payload with an "action" field.
  Also when clops appears to be installed but has no processes available.
---

## Running a process

1. `list_processes()` — what this project can run. If it comes back empty, or a
   library failed to import, call `configure_clops()`; it explains what to fix.
2. `start_process(process=…, input=…)`.
3. **Do what the response's `next_step` field says**, then call the tool it
   names. Repeat until `action` is `done` or `failed`.

That is the whole loop. Every payload carrying an `action` also carries a
`next_step` written by the server that produced it — which subagent to spawn,
with which prompt, and what to call when it finishes. Follow that rather than
anything remembered from a previous run: it is generated against the running
server, so it is correct about tool names even when they have been renamed by a
gateway, and it cannot drift out of date the way this file can.

## Discipline

The main thread's job is mechanical relay, and the failure mode is doing the
work yourself.

- Copy `description` and `prompt` **verbatim** into the Agent tool. Do not
  summarise, reword, or append to them. They are rendered by the runtime for a
  reason.
- Do not spawn agents the payload did not ask for, and do not re-plan the
  workflow. The runtime chooses the steps.

The second failure mode is quieter and costs more: handling the payloads
instead of relaying them. A dispatch prompt is a whole step's worth of
instruction, and a run is many of them.

- **Do not restate the prompt.** Paste it into the Agent call and say one line
  about which step is running. Reading it back to the user copies it a second
  time for nothing.
- **Do not pass the output back.** `step_complete(run_id)` takes no second
  argument — the subagent already reported directly. A `result` is only for a
  subagent that stopped *without* reporting.
- **Do not open the files steps write.** Long results live in the run's
  workspace and travel as paths; the step that needs one reads it. Reading it
  yourself pulls into the main thread exactly the content the workspace exists
  to keep out.
- **Background the subagent if your host can.** The relay needs to know the
  step finished, not what it said.
