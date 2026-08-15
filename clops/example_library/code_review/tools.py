"""Filesystem tools for the code review pipeline.

`sequence` hands each step only the previous step's output, so the diff that
enters at DetermineScope does not survive to AssessFile - by then the input is
an assessment plan naming files, not the files themselves. These tools are how
AssessFile reaches the code the plan points at: the handlers run in the clops
server process against the project's real working tree, so the Op reads the
file rather than a description of it.

Paths resolve against CLAUDE_PROJECT_DIR (cwd as fallback) and may not escape
it - a review step has no business reading outside the project under review.
"""

import json
import os
import re
from pathlib import Path

from clops import Tool


MAX_READ_BYTES = 200_000
MAX_GREP_MATCHES = 200
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist"}


def _project_root() -> Path:
    """The tree these tools are allowed to read.

    Claude Code sets CLAUDE_PROJECT_DIR for the server process; cwd is the
    fallback for direct runtime use (tests, internal tooling).
    """
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()


def _resolve(path: str) -> Path:
    """Resolve path inside the project root, refusing anything outside it."""
    root = _project_root()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(
            f"{path!r} resolves outside the project directory {str(root)!r}."
        )
    return candidate


def _read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
    """Return a file's contents with 1-based line numbers.

    start_line/end_line bound the slice returned; 0 means unbounded on that
    side. Output is capped at MAX_READ_BYTES with a note naming the line it
    stopped at, so a large file is re-readable in slices rather than silently
    truncated.
    """
    try:
        target = _resolve(path)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    if not target.is_file():
        return json.dumps({"error": f"No such file in the project: {path}"})
    try:
        lines = target.read_text(errors="replace").splitlines()
    except OSError as exc:
        return json.dumps({"error": f"Could not read {path}: {exc}"})

    first = max(start_line, 1)
    last = min(end_line, len(lines)) if end_line else len(lines)
    if first > len(lines):
        return json.dumps(
            {"error": f"{path} has {len(lines)} lines; start_line={start_line} is past the end."}
        )

    rendered: list[str] = []
    budget = MAX_READ_BYTES
    for number in range(first, last + 1):
        row = f"{number:>6}\t{lines[number - 1]}"
        budget -= len(row) + 1
        if budget < 0:
            rendered.append(
                f"... truncated at line {number} ({MAX_READ_BYTES} byte cap); "
                "re-read with start_line/end_line for the rest."
            )
            break
        rendered.append(row)
    return "\n".join(rendered)


def _grep_pattern(pattern: str, path: str = "", max_matches: int = 0) -> str:
    """Search the project for a regex, returning `path:line: text` matches."""
    try:
        root = _resolve(path) if path else _project_root()
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    if not root.exists():
        return json.dumps({"error": f"No such file or directory in the project: {path}"})
    try:
        expression = re.compile(pattern)
    except re.error as exc:
        return json.dumps({"error": f"Not a valid regular expression: {pattern!r} ({exc})"})

    limit = max_matches if max_matches > 0 else MAX_GREP_MATCHES
    project = _project_root()
    if root.is_file():
        targets = [root]
    else:
        targets = sorted(
            candidate
            for candidate in root.rglob("*")
            if candidate.is_file()
            and not SKIP_DIRS.intersection(candidate.relative_to(root).parts)
        )

    matches: list[str] = []
    for target in targets:
        try:
            text = target.read_text(errors="replace")
        except OSError:
            continue
        label = target.relative_to(project) if project in target.parents else target
        for number, line in enumerate(text.splitlines(), 1):
            if expression.search(line):
                matches.append(f"{label}:{number}: {line.strip()}")
                if len(matches) >= limit:
                    return "\n".join(matches) + f"\n... stopped at {limit} matches."
    if not matches:
        return f"No match for {pattern!r}."
    return "\n".join(matches)


read_file = Tool(
    name="read_file",
    description=(
        "Read a file from the project under review and return its contents with "
        "1-based line numbers. Pass `path` relative to the project root. "
        "`start_line`/`end_line` bound the slice returned; 0 means unbounded on "
        "that side."
    ),
    parameters={"path": str, "start_line": int, "end_line": int},
    handler=_read_file,
)


grep_pattern = Tool(
    name="grep_pattern",
    description=(
        "Search the project under review for a Python regular expression and "
        "return matching lines as `path:line: text`. `path` narrows the search "
        "to one file or directory (empty searches the whole project); "
        "`max_matches` caps the result (0 uses the default cap)."
    ),
    parameters={"pattern": str, "path": str, "max_matches": int},
    handler=_grep_pattern,
)
