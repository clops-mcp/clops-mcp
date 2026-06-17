---
name: clops
description: Bookmark this moment in the conversation for later analysis.
when-to-use: >
  When the user types /clops to tag the current point in the conversation
  as interesting. Used to build an index of notable moments across sessions.
  The /clops marker itself is greppable in transcripts for retrieval.
---

## What to do

The user wants to bookmark this moment. Do this quickly:

1. Check if the user provided a note after `/clops` (e.g., `/clops decided on TinyDB for state`).
2. Write a one-line summary: use the user's note if provided, otherwise generate one (10-15 words max).
3. Append a JSON line to `.claude/.clops/tags.jsonl` using the Bash tool:

```bash
mkdir -p .claude/.clops && echo '{"timestamp":"<ISO 8601 now>","summary":"<your summary>","note":"<user note if any, else null>"}' >> .claude/.clops/tags.jsonl
```

4. Respond with just: **Tagged.** followed by your summary on the next line. Nothing else. Don't interrupt the user's flow.

## Rules

- Be fast. Don't ask questions. Don't elaborate.
- The summary should capture *what's being discussed*, not *what the user said*.
- If the user provides a note, use it verbatim as the summary. Don't rewrite it.
- `/clops` with no note → auto-generate summary from context.
- `/clops decided on TinyDB` → summary is "decided on TinyDB".
- `/clops this is the key design decision` → summary is "this is the key design decision".
