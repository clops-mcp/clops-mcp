"""clops-hook — tiny forwarder script for Claude Code's SubagentStop.

Wiring:
    stdin  → Claude Code writes the SubagentStop payload here (JSON).
    socket → We forward the payload to `.claude/.clops/hook.sock`.
    stdout → We echo the MCP's decision JSON back to Claude Code.

Fail-open: any socket error (MCP down, socket missing, timeout) prints
`{}` and exits 0 rather than blocking a legitimate subagent exit. Better
to miss an enforcement than wedge every stop.

Socket path resolution:
    $CLOPS_HOOK_SOCKET, if set (tests, custom setups)
    $CLAUDE_PROJECT_DIR/.claude/.clops/hook.sock
    ./.claude/.clops/hook.sock (cwd fallback)
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Optional


def resolve_socket_path(env: Optional[dict[str, str]] = None, cwd: Optional[Path] = None) -> Path:
    """Resolve a single explicit socket path (for tests / env override)."""
    env = env if env is not None else os.environ
    explicit = env.get("CLOPS_HOOK_SOCKET")
    if explicit:
        return Path(explicit)
    project = env.get("CLAUDE_PROJECT_DIR")
    if project:
        return Path(project) / ".claude" / ".clops" / "hook.sock"
    base = cwd if cwd is not None else Path.cwd()
    return base / ".claude" / ".clops" / "hook.sock"


def resolve_socket_paths(env: Optional[dict[str, str]] = None, cwd: Optional[Path] = None) -> list[Path]:
    """Discover all active hook sockets (PID-namespaced).

    If CLOPS_HOOK_SOCKET is set, returns just that one path
    (backwards compat / tests).  Otherwise globs for hook-*.sock.
    """
    env = env if env is not None else os.environ
    explicit = env.get("CLOPS_HOOK_SOCKET")
    if explicit:
        return [Path(explicit)]
    project = env.get("CLAUDE_PROJECT_DIR")
    if project:
        state_dir = Path(project) / ".claude" / ".clops"
    else:
        base = cwd if cwd is not None else Path.cwd()
        state_dir = base / ".claude" / ".clops"
    # Glob PID-namespaced sockets; fall back to legacy hook.sock.
    sockets = sorted(state_dir.glob("hook-*.sock"))
    if not sockets:
        legacy = state_dir / "hook.sock"
        if legacy.exists():
            return [legacy]
    return sockets


def forward(payload_bytes: bytes, socket_path: Path, timeout: float = 2.0) -> bytes:
    """Connect, send, read, return. Raises on transport failure."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(socket_path))
        s.sendall(payload_bytes)
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        s.close()


def run(stdin_bytes: bytes, socket_path: Path) -> tuple[str, int]:
    """Forward to a single socket. Pure function: bytes in, (stdout text, exit code) out.

    Fail-open on any error: return `{}` and exit 0.
    """
    try:
        # Validate JSON; invalid payload = fail-open to avoid wedging.
        if not stdin_bytes.strip():
            return "{}", 0
        json.loads(stdin_bytes)
    except Exception:
        return "{}", 0

    try:
        response = forward(stdin_bytes, socket_path)
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError):
        return "{}", 0

    if not response:
        return "{}", 0
    try:
        # Validate the MCP's response is JSON; otherwise fail-open.
        json.loads(response)
    except Exception:
        return "{}", 0
    return response.decode("utf-8"), 0


def run_broadcast(stdin_bytes: bytes, socket_paths: list[Path]) -> tuple[str, int]:
    """Broadcast to all sockets, return the first non-trivial decision.

    Each server only recognises its own sessions, so unknown payloads
    get ``{}`` (fail-open).  We return the first ``{"decision": ...}``
    response, or ``{}`` if none match.
    """
    if not stdin_bytes.strip():
        return "{}", 0
    try:
        json.loads(stdin_bytes)
    except Exception:
        return "{}", 0

    for sock_path in socket_paths:
        try:
            response = forward(stdin_bytes, sock_path)
        except FileNotFoundError:
            # Socket file gone — skip.
            continue
        except ConnectionRefusedError:
            # Server died; clean up stale socket.
            try:
                sock_path.unlink()
            except OSError:
                pass
            continue
        except (socket.timeout, OSError):
            continue
        if not response:
            continue
        try:
            parsed = json.loads(response)
        except Exception:
            continue
        # Non-trivial response — a server recognised this session.
        if parsed.get("decision"):
            return response.decode("utf-8"), 0

    return "{}", 0


def main() -> int:
    payload = sys.stdin.buffer.read()
    socket_paths = resolve_socket_paths()
    if not socket_paths:
        # No servers running — fail-open.
        sys.stdout.write("{}")
        return 0
    out, code = run_broadcast(payload, socket_paths)
    sys.stdout.write(out)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
