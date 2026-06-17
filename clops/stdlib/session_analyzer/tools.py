"""Tools -- programmatic capabilities for deterministic work."""

import json
import re
from pathlib import Path
from clops import Tool


def _normalize_claude_code_jsonl(transcript: str) -> dict | None:
    """Try to parse as Claude Code native JSONL format.

    Claude Code sessions have records with type="user", type="assistant",
    type="attachment" (tool calls/results), type="system", etc.

    Returns a normalized dict with 'metadata' and 'steps', or None if
    the format doesn't match.
    """
    lines = transcript.strip().splitlines()
    if not lines:
        return None

    # Detect Claude Code format by checking first few records for type field
    is_claude_code = False
    for line in lines[:10]:
        try:
            rec = json.loads(line)
            if rec.get("type") in ("user", "assistant", "attachment", "permission-mode", "system"):
                is_claude_code = True
                break
        except (json.JSONDecodeError, TypeError):
            continue

    if not is_claude_code:
        return None

    # Parse all records
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Extract conversation turns as steps
    steps = []
    session_id = None
    total_input_tokens = 0
    total_output_tokens = 0
    tool_calls_in_turn = []

    for rec in records:
        rec_type = rec.get("type", "")

        if not session_id:
            session_id = rec.get("sessionId")

        if rec_type == "user":
            # Content lives in rec["message"]["content"]
            message = rec.get("message", {})
            content = ""
            if isinstance(message, dict):
                c = message.get("content", "")
                if isinstance(c, str):
                    content = c
                elif isinstance(c, list):
                    content = " ".join(
                        p.get("text", "") for p in c
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
            if content.strip():
                steps.append({
                    "step_index": len(steps),
                    "op_name": "user",
                    "intent": "",
                    "input_summary": content[:500],
                    "output_text": content,
                    "tools_called": [],
                    "teammate_exchanges": [],
                    "token_counts": {"input_tokens": 0, "output_tokens": 0},
                    "duration_ms": None,
                    "model": None,
                    "timestamp": rec.get("timestamp"),
                })

        elif rec_type == "assistant":
            # Content lives in rec["message"]["content"]
            message = rec.get("message", {})
            content = ""
            model = None
            input_tok = 0
            output_tok = 0

            if isinstance(message, dict):
                c = message.get("content", "")
                if isinstance(c, str):
                    content = c
                elif isinstance(c, list):
                    parts = []
                    for p in c:
                        if isinstance(p, dict):
                            if p.get("type") == "text":
                                parts.append(p.get("text", ""))
                            elif p.get("type") == "tool_use":
                                tool_calls_in_turn.append(p.get("name", "unknown"))
                    content = " ".join(parts)

                model = message.get("model")
                usage = message.get("usage", {})
                input_tok = usage.get("input_tokens", 0)
                output_tok = usage.get("output_tokens", 0)
                total_input_tokens += input_tok
                total_output_tokens += output_tok

            if content.strip() or tool_calls_in_turn:
                steps.append({
                    "step_index": len(steps),
                    "op_name": "assistant",
                    "intent": "",
                    "input_summary": "",
                    "output_text": content,
                    "tools_called": list(tool_calls_in_turn),
                    "teammate_exchanges": [],
                    "token_counts": {
                        "input_tokens": input_tok,
                        "output_tokens": output_tok,
                    },
                    "duration_ms": None,
                    "model": model,
                    "timestamp": rec.get("timestamp"),
                })
                tool_calls_in_turn = []

    metadata = {
        "total_steps": len(steps),
        "total_tokens": total_input_tokens + total_output_tokens,
        "entry_op": "claude_code_session",
        "library_name": None,
        "session_id": session_id,
        "format": "claude_code_jsonl",
    }

    return {"metadata": metadata, "steps": steps}


def _parse_transcript(transcript: str) -> dict:
    """Parse a session transcript into structured step records.

    Handles three formats:
    1. Claude Code native JSONL (auto-detected by record types).
    2. JSON-lines: each line is a JSON object with op execution data.
    3. Markdown-sectioned: sections delimited by '## Step N: OpName' headers,
       with labeled fields (Intent:, Input:, Output:, etc.).

    Returns a dict with 'metadata' and 'steps' keys.
    """
    transcript = transcript.strip()
    steps = []
    metadata = {
        "total_steps": 0,
        "total_tokens": 0,
        "entry_op": None,
        "library_name": None,
    }

    # Try Claude Code native format first
    claude_code_result = _normalize_claude_code_jsonl(transcript)
    if claude_code_result is not None:
        return claude_code_result

    # Try JSON-lines format
    if transcript.startswith("{") or transcript.startswith("["):
        try:
            # Could be a JSON array or newline-delimited JSON objects
            if transcript.startswith("["):
                records = json.loads(transcript)
            else:
                records = []
                for line in transcript.splitlines():
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))

            for i, rec in enumerate(records):
                step = {
                    "step_index": i,
                    "op_name": rec.get("op_name", rec.get("op", f"step_{i}")),
                    "intent": rec.get("intent", ""),
                    "input_summary": rec.get("input_summary", rec.get("input", "")),
                    "output_text": rec.get("output_text", rec.get("output", "")),
                    "tools_called": rec.get("tools_called", []),
                    "teammate_exchanges": rec.get("teammate_exchanges", []),
                    "token_counts": rec.get("token_counts", {
                        "input_tokens": rec.get("input_tokens", 0),
                        "output_tokens": rec.get("output_tokens", 0),
                    }),
                    "duration_ms": rec.get("duration_ms", None),
                    "model": rec.get("model", None),
                }
                steps.append(step)

            if records:
                metadata["entry_op"] = steps[0]["op_name"] if steps else None
                metadata["library_name"] = records[0].get("library", None)

        except (json.JSONDecodeError, TypeError):
            # Fall through to markdown parsing
            pass

    # Markdown-sectioned format
    if not steps:
        step_pattern = re.compile(
            r"^##\s+(?:Step\s+\d+[:\s]*)?(\w+)",
            re.MULTILINE,
        )
        field_pattern = re.compile(
            r"^(?:[-*]\s+)?(\w[\w\s]*):\s*(.*?)(?=\n(?:[-*]\s+)?\w[\w\s]*:|$)",
            re.MULTILINE | re.DOTALL,
        )

        sections = step_pattern.split(transcript)
        # sections[0] is preamble, then alternating (op_name, section_body)
        if len(sections) >= 3:
            preamble = sections[0]
            # Extract library name from preamble if present
            lib_match = re.search(r"[Ll]ibrary[:\s]+(\S+)", preamble)
            if lib_match:
                metadata["library_name"] = lib_match.group(1)

            for i in range(1, len(sections), 2):
                op_name = sections[i].strip()
                body = sections[i + 1] if i + 1 < len(sections) else ""

                fields = {}
                for m in field_pattern.finditer(body):
                    key = m.group(1).strip().lower().replace(" ", "_")
                    val = m.group(2).strip()
                    fields[key] = val

                input_tokens = 0
                output_tokens = 0
                token_str = fields.get("tokens", fields.get("token_counts", ""))
                token_match = re.findall(r"(\d+)", token_str)
                if len(token_match) >= 2:
                    input_tokens = int(token_match[0])
                    output_tokens = int(token_match[1])
                elif len(token_match) == 1:
                    output_tokens = int(token_match[0])

                tools_raw = fields.get("tools_called", fields.get("tools", ""))
                tools_called = [
                    t.strip() for t in re.split(r"[,;\n]", tools_raw) if t.strip()
                ]

                duration_str = fields.get("duration_ms", fields.get("duration", ""))
                duration_match = re.search(r"(\d+)", duration_str)
                duration_ms = int(duration_match.group(1)) if duration_match else None

                step = {
                    "step_index": len(steps),
                    "op_name": op_name,
                    "intent": fields.get("intent", ""),
                    "input_summary": fields.get("input_summary", fields.get("input", "")),
                    "output_text": fields.get("output_text", fields.get("output", "")),
                    "tools_called": tools_called,
                    "teammate_exchanges": [],
                    "token_counts": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                    "duration_ms": duration_ms,
                    "model": fields.get("model", None),
                }
                steps.append(step)

            if steps:
                metadata["entry_op"] = steps[0]["op_name"]

    # If neither format worked, treat the whole thing as a single step
    if not steps:
        steps.append({
            "step_index": 0,
            "op_name": "unknown",
            "intent": "",
            "input_summary": "",
            "output_text": transcript,
            "tools_called": [],
            "teammate_exchanges": [],
            "token_counts": {"input_tokens": 0, "output_tokens": 0},
            "duration_ms": None,
            "model": None,
        })

    metadata["total_steps"] = len(steps)
    metadata["total_tokens"] = sum(
        s["token_counts"].get("input_tokens", 0) + s["token_counts"].get("output_tokens", 0)
        for s in steps
    )

    return {"metadata": metadata, "steps": steps}


parse_transcript = Tool(
    name="parse_transcript",
    description=(
        "Parse a raw session transcript into structured step records. "
        "Accepts the full transcript text. Returns a dict with 'metadata' "
        "(total_steps, total_tokens, entry_op, library_name) and 'steps' "
        "(list of step records each with op_name, intent, input_summary, "
        "output_text, tools_called, teammate_exchanges, token_counts, "
        "duration_ms, model). Handles JSON-lines and markdown-sectioned formats."
    ),
    parameters={"transcript": str},
    handler=_parse_transcript,
)


def _resolve_session_path(session_id: str, project_path: str = "") -> str:
    """Find and return the raw content of a Claude Code session log.

    Resolution order:
    1. If project_path is given, look in ~/.claude/projects/{project_path}/{session_id}.jsonl
    2. If only session_id, scan all project dirs for a matching .jsonl file
    3. If session_id is "latest", find the most recently modified .jsonl across all projects

    Returns the raw file content as a string.
    """
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.exists():
        return json.dumps({"error": "No Claude Code projects directory found at ~/.claude/projects/"})

    # Normalize session_id
    if not session_id.endswith(".jsonl"):
        session_id_file = session_id + ".jsonl"
    else:
        session_id_file = session_id
        session_id = session_id.replace(".jsonl", "")

    # If project_path given, go direct
    if project_path:
        # Convert filesystem path to Claude's mangled format
        mangled = project_path.replace("/", "-")
        if mangled.startswith("-"):
            mangled = mangled  # keep leading dash
        target = claude_projects / mangled / session_id_file
        if target.exists():
            return target.read_text()
        # Try unmangled too
        target = claude_projects / project_path / session_id_file
        if target.exists():
            return target.read_text()
        return json.dumps({"error": f"Session {session_id} not found in project {project_path}"})

    # "latest" — find most recent .jsonl across all projects
    if session_id == "latest":
        latest_file = None
        latest_mtime = 0
        for project_dir in claude_projects.iterdir():
            if not project_dir.is_dir():
                continue
            for f in project_dir.glob("*.jsonl"):
                mtime = f.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_file = f
        if latest_file:
            return latest_file.read_text()
        return json.dumps({"error": "No session logs found"})

    # Scan all project dirs for the session_id
    for project_dir in claude_projects.iterdir():
        if not project_dir.is_dir():
            continue
        target = project_dir / session_id_file
        if target.exists():
            return target.read_text()

    return json.dumps({"error": f"Session {session_id} not found in any project"})


load_session = Tool(
    name="load_session",
    description=(
        "Load a Claude Code session log by session ID. Pass session_id='latest' "
        "to get the most recent session. Optionally pass project_path to narrow "
        "the search to a specific project. Returns the raw JSONL content."
    ),
    parameters={"session_id": str, "project_path": str},
    handler=_resolve_session_path,
)


def _summarize_session(session_id: str, project_path: str = "", max_chars_per_turn: int = 300) -> str:
    """Load a session and produce a compact digest for LLM analysis.

    Strips tool results, system messages, and file-history-snapshots.
    Keeps only user and assistant messages, truncated to max_chars_per_turn.
    Produces a numbered conversation digest that's ~50x smaller than raw JSONL.
    """
    raw = _resolve_session_path(session_id, project_path)
    if raw.startswith('{"error"'):
        return raw

    lines = raw.strip().splitlines()
    turns = []
    turn_num = 0
    total_user = 0
    total_assistant = 0

    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue

        rec_type = rec.get("type", "")
        if rec_type not in ("user", "assistant"):
            continue

        message = rec.get("message", {})
        if not isinstance(message, dict):
            continue

        content = message.get("content", "")
        role = rec_type
        text = ""

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            tool_names = []
            for p in content:
                if isinstance(p, dict):
                    if p.get("type") == "text":
                        parts.append(p.get("text", ""))
                    elif p.get("type") == "tool_use":
                        tool_names.append(p.get("name", "?"))
            text = " ".join(parts)
            if tool_names:
                text += f" [tools: {', '.join(tool_names)}]"

        # Skip empty turns and system-injected content
        text = text.strip()
        if not text:
            continue
        if text.startswith("<system-reminder>") or text.startswith("<command-"):
            continue

        # Truncate
        if len(text) > max_chars_per_turn:
            text = text[:max_chars_per_turn] + "..."

        turn_num += 1
        if role == "user":
            total_user += 1
        else:
            total_assistant += 1

        timestamp = rec.get("timestamp", "")
        ts_short = timestamp[11:16] if len(timestamp) > 16 else ""  # HH:MM

        turns.append(f"[{turn_num}] {ts_short} {role.upper()}: {text}")

    header = (
        f"Session digest: {session_id}\n"
        f"Turns: {turn_num} ({total_user} user, {total_assistant} assistant)\n"
        f"Truncated to {max_chars_per_turn} chars/turn\n"
        f"---\n"
    )
    return header + "\n".join(turns)


summarize_session = Tool(
    name="summarize_session",
    description=(
        "Load a Claude Code session and produce a compact digest for LLM analysis. "
        "Strips tool results, system messages, and noise. Keeps only user and "
        "assistant message text, truncated to max_chars_per_turn (default 300). "
        "Produces a ~50x smaller representation suitable for finding inflection "
        "points and thinking patterns. Pass session_id='latest' for most recent."
    ),
    parameters={"session_id": str, "project_path": str, "max_chars_per_turn": int},
    handler=_summarize_session,
)
