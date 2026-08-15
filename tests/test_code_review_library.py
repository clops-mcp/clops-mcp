"""The code review pipeline's assessment step must be able to reach the code.

`sequence` hands each step only the previous step's output, so the diff that
enters at DetermineScope is gone by step 5: AssessFile's input is an assessment
plan. The library shipped that way once — AssessFile was asked to analyse files
it had no access to. Its `read_file` / `grep_pattern` Tools are the access, so
these tests drive a real run to that step and prove the Op can pull the code
through them.
"""

import importlib

import pytest

from clops.runtime.mcp_server import FlowServer, ServerConfig
from clops.example_library.code_review.tools import _grep_pattern, _read_file


DIFF = """\
diff --git a/app/auth.py b/app/auth.py
--- a/app/auth.py
+++ b/app/auth.py
@@ -1,3 +1,5 @@
 def login(request):
     user = lookup(request.form["user"])
+    if request.form.get("admin") == "1":
+        user.role = "admin"
     return issue_token(user)
"""

SOURCE = '''\
def login(request):
    user = lookup(request.form["user"])
    if request.form.get("admin") == "1":
        user.role = "admin"
    return issue_token(user)
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project tree the tools resolve against, as the server would see it."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "auth.py").write_text(SOURCE)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def review_server():
    """A FlowServer with the code review library loaded into a clean registry."""
    # conftest clears the registry per test, so the library has to re-register.
    importlib.reload(importlib.import_module("clops.example_library.code_review.concepts"))
    importlib.reload(importlib.import_module("clops.example_library.code_review.snippets"))
    importlib.reload(importlib.import_module("clops.example_library.code_review.tools"))
    importlib.reload(importlib.import_module("clops.example_library.code_review.ops"))
    return FlowServer(ServerConfig())


def _advance_to(srv, op_name):
    """Drive ReviewDiff with stub step outputs until `op_name` is dispatched."""
    payload = srv._handle_start_process({"process": "ReviewDiff", "input": DIFF})
    for _ in range(20):
        config = payload["agent_config"]
        if config["description"].startswith(f"Execute {op_name} "):
            run = srv.runtime.get_run(payload["run_id"])
            return config, next(iter(run.pending_executions))
        payload = srv._handle_step_complete({
            "run_id": payload["run_id"],
            "result": "app/auth.py: auth, input-validation",
        })
    raise AssertionError(f"{op_name} was never dispatched")


def test_assess_file_receives_no_code_in_its_prompt(review_server):
    """The premise: the diff does not survive the sequence."""
    config, _ = _advance_to(review_server, "AssessFile")
    assert "issue_token" not in config["prompt"]
    assert "diff --git" not in config["prompt"]


def test_assess_file_is_offered_the_tools_that_reach_the_code(review_server):
    config, _ = _advance_to(review_server, "AssessFile")
    assert "read_file" in config["prompt"]
    assert "grep_pattern" in config["prompt"]


def test_assess_file_can_pull_the_code_through_read_file(project, review_server):
    """End to end: the dispatched execution calls read_file and gets the source.

    This is the property that was broken — not that a handler works in
    isolation, but that the Op running as step 5 of a live run can reach the
    file the plan names.
    """
    _, execution_id = _advance_to(review_server, "AssessFile")
    result = review_server._handle_call_tool({
        "execution_id": execution_id,
        "name": "read_file",
        "arguments": {"path": "app/auth.py"},
    })
    assert "issue_token" in result
    assert 'user.role = "admin"' in result
    # Line numbers, so a finding can cite a location the reviewer can find.
    assert "     4\t" in result


def test_a_step_without_the_tools_cannot_call_them(project, review_server):
    """The capability is AssessFile's, not the whole pipeline's."""
    from clops.runtime.core import RuntimeError_

    _, execution_id = _advance_to(review_server, "DetermineScope")
    with pytest.raises(RuntimeError_, match="did not declare"):
        review_server._handle_call_tool({
            "execution_id": execution_id,
            "name": "read_file",
            "arguments": {"path": "app/auth.py"},
        })


# ---- Handler behaviour ------------------------------------------------


def test_read_file_returns_a_slice_when_bounded(project):
    assert _read_file("app/auth.py", 3, 4).splitlines() == [
        '     3\t    if request.form.get("admin") == "1":',
        '     4\t        user.role = "admin"',
    ]


def test_read_file_refuses_to_escape_the_project(project):
    assert "outside the project directory" in _read_file("../secrets.txt")


def test_read_file_reports_a_missing_file_rather_than_raising(project):
    assert "No such file" in _read_file("app/nope.py")


def test_grep_pattern_locates_a_usage(project):
    assert _grep_pattern(r"role\s*=") == 'app/auth.py:4: user.role = "admin"'


def test_grep_pattern_reports_a_bad_regex(project):
    assert "not a valid regular expression" in _grep_pattern("(unclosed").lower()
