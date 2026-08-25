# Smoke Test 14: The Run Workspace

## What it tests

Whether a long result leaves the message path on its own. Nothing in this
scenario's library mentions files — the workspace and the rule live in the
runtime's rendered prompt, and this checks that they land.

1. `DraftAndAssess` (composition, entry) — `sequence(DraftSpec, AssessSpec)`
2. `DraftSpec` (leaf, step 1) is asked for a document "well over a thousand
   words". Its Intent says nothing about writing a file.
3. `AssessSpec` (leaf, step 2) has to judge specifics of that document, so a
   summary alone will not answer it.

## How to run

```
Run the DraftAndAssess process on "a rate limiter for a public HTTP API"
```

## Expected behavior

1. `start_process("DraftAndAssess", "a rate limiter...")` returns a dispatch
   for `DraftSpec`. Its `prompt` contains a `## Long results go in a file`
   section naming a directory — under the system temp dir by default.
2. `DraftSpec` agent:
   - Writes the specification to a file in that directory with `Write`
   - Calls `mcp__clops__complete(execution_id, "<summary> ... <path>")` — a
     summary and the path, **not** the specification itself
3. `step_complete` advances to `AssessSpec`, whose input is that summary and path
4. `AssessSpec` agent:
   - Calls `Read` on the path it was given
   - Calls `mcp__clops__complete(execution_id, "<assessment>")` citing specifics
     that only appear in the file
5. `step_complete` returns `action: "done"`, and — because the run left files
   behind — the payload carries a `workspace` field
6. The main thread reports the assessment and names the workspace path

## Pass criteria

- `DraftSpec`'s `complete` output is short: a summary plus a path, not the document
- The file exists at the path it reported, and holds the full specification
- `AssessSpec` reads that file and cites material from it
- The terminal payload carries `workspace`, and the main thread names it
- The main thread never reads the file itself

## Variations worth running once

- `[runtime] workspace = local` in `.clops` — the same run, with the workspace
  under `.claude/.clops/runs/<run_id>/` instead of the temp dir
- `[runtime] workspace = off` — no workspace section in the prompt, and the
  specification comes back inline, as it did before this contract existed

## Common failure modes

- Contract ignored: `DraftSpec` returns the whole specification through
  `complete` anyway — the section rendered but did not persuade
- Over-applied: a three-line result gets a file too, which costs more than it saves
- Broken hand-off: `AssessSpec` gets a path that does not resolve, or assesses
  the summary without opening the file, and its verdict stays generic
- Main thread reads the file to summarise it, putting back in its context
  exactly what the workspace exists to keep out
- No `workspace` on the terminal payload despite files being written
