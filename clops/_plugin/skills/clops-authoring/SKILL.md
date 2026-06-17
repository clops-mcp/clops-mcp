---
name: clops-authoring
description: Author clops Op libraries — Concepts, Snippets, Tools, and Ops.
when-to-use: >
  When the user asks to create, scaffold, or edit a clops Op library
  (process definitions, Ops, Concepts, Snippets, Tools).
---

## Start here

Read the docs in order — they do the teaching:

1. `docs/philosophy.md` — how to decompose work into Ops (read first).
2. `docs/concepts.md` — the four primitives (Concept, Snippet, Tool, Op) and Registry.
3. `docs/patterns.md` — composition patterns (sequence, branch, gather, need).
4. `docs/examples.md` — annotated library walkthroughs.

## CLI commands

| Command | Purpose |
|---|---|
| `clops new-library <name>` | Scaffold a new library package |
| `clops lint <path>` | Validate a library against the spec |
| `clops show <name>` | Inspect a registered library's Ops and Concepts |

The CLI lives at the project's `.venv/bin/clops`. Outside the venv, use `uv run --project <project-root> clops`.

## Library file structure

A library package contains four modules:

- `concepts.py` — Concept definitions (named data handles between Ops).
- `snippets.py` — Reusable prompt fragments and guardrails.
- `ops.py` — Op definitions (intent, inputs/outputs, model, tools).
- `__init__.py` — Registry wiring; exposes the library to the runtime.

Keep Ops to one cognitive step each. If the intent takes more than a short paragraph, split.
