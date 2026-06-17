"""Protocol tests for the SubagentStop hook transport.

Covers:
    - The pure `decide()` function (logic without transport).
    - The Unix-socket round-trip (real socket, same process, no fork).
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
from pathlib import Path

import pytest

from clops import Concept, Op
from clops.runtime import Runtime
from clops.runtime.hook_server import BLOCK_REASON, HookServer, decide


class M(Concept):
    description = "a message"


class R(Concept):
    description = "a result"


@pytest.fixture
def library():
    class OpA(Op):
        Input = M
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating hook server protocol."
        entry = True

    return OpA


# ---- decide() logic --------------------------------------------------


def test_decide_allows_when_completed_in_queue(library):
    rt = Runtime()
    d = rt.start("OpA", "hi", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))
    rt.complete(exec_id, "done", parent_session_id="parent-1")

    result = decide(rt, {"session_id": "parent-1"})
    assert result == {}


def test_decide_blocks_when_known_session_has_empty_queue(library):
    """A subagent that's ours (known session) but failed to call
    complete or need before stopping must be blocked."""
    rt = Runtime()
    rt.start("OpA", "hi", enforce_entry=True)
    rt.note_session("parent-1")  # subagent already made some clops MCP call
    result = decide(rt, {"session_id": "parent-1"})
    assert result["decision"] == "block"
    assert BLOCK_REASON in result["reason"]


def test_decide_fails_open_without_session_id():
    rt = Runtime()
    # No session_id → nothing to correlate against; must not block exits.
    assert decide(rt, {}) == {}


def test_decide_fails_open_for_unknown_session():
    """A subagent we've never seen is not one of ours; must not block.
    Critical: the user's other subagents (non-clops-executor) share the
    Claude Code session-id space."""
    rt = Runtime()
    assert decide(rt, {"session_id": "some-other-agents-session"}) == {}


def test_decide_consumes_one_per_call_fifo(library):
    rt = Runtime()
    OpA = library

    # Two sequential dispatches from the same parent session.
    d1 = rt.start("OpA", "hi", enforce_entry=True)
    exec1 = next(iter(rt.get_run(d1["run_id"]).pending_executions))
    rt.complete(exec1, "a", parent_session_id="p")
    rt.step_complete(d1["run_id"], "a")

    d2 = rt.start("OpA", "hi", enforce_entry=True)
    exec2 = next(iter(rt.get_run(d2["run_id"]).pending_executions))
    rt.complete(exec2, "b", parent_session_id="p")

    # Two hook fires release both completions in order; a third blocks.
    assert decide(rt, {"session_id": "p"}) == {}
    assert decide(rt, {"session_id": "p"}) == {}
    assert decide(rt, {"session_id": "p"})["decision"] == "block"


@pytest.fixture
def short_tmp():
    """Provide a short temp directory to avoid AF_UNIX path length limits."""
    d = tempfile.mkdtemp(prefix="cf-", dir="/tmp")
    yield Path(d)
    # Cleanup
    for f in Path(d).iterdir():
        f.unlink(missing_ok=True)
    os.rmdir(d)


# ---- Unix-socket round-trip -----------------------------------------


def _round_trip(socket_path: Path, payload: dict) -> dict:
    """Client side: connect, write, read, close."""
    # Small retry loop — server thread may need a blip to start accepting.
    last_err = None
    for _ in range(20):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(socket_path))
            break
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            last_err = exc
            time.sleep(0.05)
    else:
        raise RuntimeError(f"could not connect to hook socket: {last_err}")

    with s:
        s.sendall(json.dumps(payload).encode("utf-8"))
        s.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


def test_unix_socket_round_trip_blocks_known_session_without_completion(short_tmp, library):
    rt = Runtime()
    rt.start("OpA", "hi", enforce_entry=True)
    rt.note_session("parent-1")  # ours, but never called complete

    sock_path = short_tmp / "hook.sock"
    srv = HookServer(rt, sock_path)
    srv.start()
    try:
        response = _round_trip(sock_path, {"session_id": "parent-1"})
    finally:
        srv.stop()

    assert response["decision"] == "block"


def test_unix_socket_round_trip_allows_after_completion(short_tmp, library):
    rt = Runtime()
    d = rt.start("OpA", "hi", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))
    rt.complete(exec_id, "done", parent_session_id="parent-1")

    sock_path = short_tmp / "hook.sock"
    srv = HookServer(rt, sock_path)
    srv.start()
    try:
        response = _round_trip(sock_path, {"session_id": "parent-1"})
    finally:
        srv.stop()

    assert response == {}


def test_hook_server_tears_down_socket_on_stop(short_tmp, library):
    rt = Runtime()
    sock_path = short_tmp / "hook.sock"
    srv = HookServer(rt, sock_path)
    srv.start()
    assert sock_path.exists()
    srv.stop()
    assert not sock_path.exists()
