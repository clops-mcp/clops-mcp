"""Tests for the clops-hook forwarder."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from clops import Concept, Op
from clops.cli.hook import resolve_socket_path, resolve_socket_paths, run, run_broadcast
from clops.runtime import Runtime
from clops.runtime.hook_server import HookServer


class M(Concept):
    description = "m"


class R(Concept):
    description = "r"


@pytest.fixture
def library():
    class OpA(Op):
        Input = M
        Output = R
        Intent = "a"
        Meta = "Test fixture Op for validating hook forwarding."
        entry = True

    return OpA


# ---- Socket path resolution -----------------------------------------


def test_resolve_socket_path_uses_explicit_env_first(tmp_path):
    custom = tmp_path / "custom.sock"
    path = resolve_socket_path(
        env={"CLOPS_HOOK_SOCKET": str(custom), "CLAUDE_PROJECT_DIR": str(tmp_path)},
        cwd=tmp_path,
    )
    assert path == custom


def test_resolve_socket_path_uses_project_dir_when_no_explicit(tmp_path):
    path = resolve_socket_path(env={"CLAUDE_PROJECT_DIR": str(tmp_path)}, cwd=Path("/nowhere"))
    assert path == tmp_path / ".claude" / ".clops" / "hook.sock"


def test_resolve_socket_path_falls_back_to_cwd(tmp_path):
    path = resolve_socket_path(env={}, cwd=tmp_path)
    assert path == tmp_path / ".claude" / ".clops" / "hook.sock"


# ---- run() fail-open behavior ---------------------------------------


def test_run_fails_open_when_socket_missing(tmp_path):
    payload = json.dumps({"session_id": "p"}).encode("utf-8")
    out, code = run(payload, tmp_path / "nope.sock")
    assert out == "{}"
    assert code == 0


def test_run_fails_open_on_invalid_json_input(tmp_path):
    out, code = run(b"not json", tmp_path / "nope.sock")
    assert out == "{}"
    assert code == 0


def test_run_fails_open_on_empty_input(tmp_path):
    out, code = run(b"", tmp_path / "nope.sock")
    assert out == "{}"


@pytest.fixture
def short_tmp():
    """Short temp dir to avoid AF_UNIX path length limits on macOS."""
    d = tempfile.mkdtemp(prefix="cf-", dir="/tmp")
    yield Path(d)
    for f in Path(d).iterdir():
        f.unlink(missing_ok=True)
    os.rmdir(d)


# ---- End-to-end through a live HookServer ---------------------------


def test_run_forwards_to_live_server_and_gets_block(short_tmp, library):
    rt = Runtime()
    rt.start("OpA", "hi", enforce_entry=True)
    rt.note_session("parent-1")  # known-session; queue empty → block

    sock = short_tmp / "hook.sock"
    srv = HookServer(rt, sock)
    srv.start()
    try:
        out, code = run(json.dumps({"session_id": "parent-1"}).encode("utf-8"), sock)
    finally:
        srv.stop()

    assert code == 0
    decoded = json.loads(out)
    assert decoded["decision"] == "block"


def test_run_forwards_to_live_server_and_gets_allow(short_tmp, library):
    rt = Runtime()
    d = rt.start("OpA", "hi", enforce_entry=True)
    exec_id = next(iter(rt.get_run(d["run_id"]).pending_executions))
    rt.complete(exec_id, "done", parent_session_id="parent-1")

    sock = short_tmp / "hook.sock"
    srv = HookServer(rt, sock)
    srv.start()
    try:
        out, code = run(json.dumps({"session_id": "parent-1"}).encode("utf-8"), sock)
    finally:
        srv.stop()

    assert code == 0
    assert json.loads(out) == {}
