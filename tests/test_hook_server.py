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
from clops.runtime.hook_server import HookServer, block_reason, decide


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
    assert block_reason() in result["reason"]


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


# ---- start() degrades instead of crashing --------------------------------
#
# The hook is enforcement, not transport: `clops-hook` already fails open on
# every error, so a server that can't bind still runs flows correctly. It just
# can't catch a subagent that ends its turn without calling complete or need.
# Losing the whole server over that is the wrong trade — and it happened for
# real, both in a deep project path and in a container.


def test_start_returns_false_when_path_too_long_instead_of_raising(tmp_path, capsys):
    """Reproduces `OSError: AF_UNIX path too long`, which used to kill startup.

    macOS caps AF_UNIX paths near 104 bytes, so a deep project directory took
    the server down at boot with an unhandled OSError.
    """
    deep = tmp_path.joinpath(*["a-reasonably-long-directory-name"] * 6)
    sock = deep / "hook.sock"
    assert len(str(sock)) > 104, "test needs a path over the AF_UNIX limit"

    server = HookServer(Runtime(), sock)
    assert server.start() is False

    err = capsys.readouterr().err
    assert "SubagentStop enforcement disabled" in err
    assert "too long" in err
    server.stop()  # must be safe to call after a failed start


def test_start_returns_false_when_directory_is_not_creatable(tmp_path, capsys):
    """The container case: the project directory isn't writable."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file")

    server = HookServer(Runtime(), blocker / "sub" / "hook.sock")
    assert server.start() is False
    assert "SubagentStop enforcement disabled" in capsys.readouterr().err
    server.stop()


def test_start_returns_true_on_a_normal_path(short_tmp):
    # `short_tmp`, not pytest's `tmp_path` — on macOS the latter is itself long
    # enough to trip the AF_UNIX limit, which is why that fixture exists at all.
    server = HookServer(Runtime(), short_tmp / "hook.sock")
    try:
        assert server.start() is True
        assert (short_tmp / "hook.sock").exists()
    finally:
        server.stop()
