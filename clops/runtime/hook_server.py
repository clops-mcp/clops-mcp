"""Unix-socket SubagentStop hook handler.

Claude Code's SubagentStop hook fires a command (`clops-hook`) that
reads the payload from stdin and forwards it to this server over a Unix
domain socket. The server consults the Runtime's per-session completion
queue and returns either `{}` (allow termination) or a block decision.

Rationale for Unix sockets over HTTP+port-file:
- No port negotiation, no port-conflict risk.
- Well-known path derived from project directory.
- Fails cleanly when MCP is down (connection refused; hook fail-opens).

Trade-off: Unix sockets on Windows are recent and patchy. Acceptable for
personal-infra tooling.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import Any

from clops import naming
from clops.runtime.core import Runtime


def block_reason() -> str:
    """Block payload returned to Claude Code when the hook sees a subagent
    attempting to terminate without calling complete or need.

    A function rather than a constant because the tool prefix depends on the
    server name, which is only known once the server has started (`naming`).
    Naming the wrong tool here would tell the subagent to call something that
    does not exist.
    """
    return (
        f"Call {naming.tool('complete')}(execution_id, output) or "
        f"{naming.tool('need')}(execution_id, reason) before ending your turn."
    )


def decide(runtime: Runtime, payload: dict[str, Any]) -> dict[str, Any]:
    """Pure decision function — used by the socket server and by tests.

    Decision rules (in order):
      1. No `session_id` in payload → fail-open. Without an identifier
         we can't correlate.
      2. Subagent isn't one of ours (`runtime.is_known_session` is
         False) → fail-open. Other agents in the same Claude Code
         session — the user's other subagents, plugins, etc. — must not
         be blocked. We only enforce against subagents that have made
         at least one clops MCP call and thereby identified themselves.
      3. Otherwise: release one queued completion. If queue is empty,
         block — the subagent failed to call complete or need despite
         being one of ours.
    """
    parent_session_id = payload.get("session_id")
    if not parent_session_id:
        return {}
    if not runtime.is_known_session(parent_session_id):
        return {}

    released = runtime.release_one_completed(parent_session_id)
    if released is None:
        return {"decision": "block", "reason": block_reason()}
    return {}


class HookServer:
    """Thread-backed Unix-socket listener.

    One thread accepts connections; each connection is a single
    request/response exchange. The hook script is synchronous, so
    sequential handling is fine — this is a few calls per run, not
    a hot path.
    """

    def __init__(self, runtime: Runtime, socket_path: Path):
        self.runtime = runtime
        self.socket_path = Path(socket_path)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> bool:
        """Bind and serve. Returns False if the socket could not be bound.

        Best-effort by design. The hook is an *enforcement* mechanism, not a
        transport: `clops-hook` already fails open on every error
        (`clops/cli/hook.py`), so a server without a bound socket still runs
        flows correctly — it just can't catch a subagent that ends its turn
        without calling complete or need.

        Failing to bind must therefore not take the whole server down with it.
        Two ways this happens in practice:

        - **Path length.** The socket path is derived from the project
          directory, and AF_UNIX paths cap near 104 bytes on macOS, so a
          deeply-nested project raises `OSError: AF_UNIX path too long`.
        - **Containers and read-only mounts**, where the project directory
          isn't writable.

        Both used to be an unhandled crash at startup.
        """
        try:
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._warn_disabled(f"cannot create {self.socket_path.parent}: {exc}")
            return False

        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(self.socket_path))
        except OSError as exc:
            sock.close()
            detail = f"{exc}"
            if "too long" in detail:
                detail += (
                    f" (path is {len(str(self.socket_path))} bytes; AF_UNIX caps "
                    "near 104 on macOS — use a shorter project path, or set "
                    "CLOPS_HOOK_SOCKET to somewhere short)"
                )
            self._warn_disabled(detail)
            return False

        self._sock = sock
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return True

    @staticmethod
    def _warn_disabled(reason: str) -> None:
        # stderr, not stdout: stdout is the MCP JSON-RPC channel on stdio
        # transport, and writing anything else there corrupts the protocol.
        print(
            f"clops: SubagentStop enforcement disabled — {reason}",
            file=sys.stderr,
            flush=True,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        try:
            self.socket_path.unlink()
        except OSError:
            pass

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop_event.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        try:
            data = _recv_all(conn)
            if not data:
                return
            payload = json.loads(data)
            response = decide(self.runtime, payload)
            conn.sendall(json.dumps(response).encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            # Fail-open: return empty (allow) rather than block on our bug.
            try:
                conn.sendall(
                    json.dumps({"_internal_error": f"{type(exc).__name__}: {exc}"}).encode("utf-8")
                )
            except OSError:
                pass


def _recv_all(conn: socket.socket) -> bytes:
    chunks = []
    while True:
        conn.settimeout(1.0)
        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        chunks.append(chunk)
        if len(chunk) < 4096:
            break
    return b"".join(chunks)
