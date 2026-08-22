"""Long results belong in a file, and the runtime says so without being asked.

Three costs motivated this, all of them paid in tokens:

  1. A long result serialized through `complete` travels inline.
  2. A long result parked in a state store is worse — every later step that
     reads that store pays for the whole value, not just the step that needed it.
  3. The main thread relaying dispatches re-reads prompts and echoes outputs
     that were already reported directly.

The fix is guidance the server emits on payloads the agent is reading anyway:
a workspace directory named in every leaf prompt, a nudge on an oversized state
write, and relay instructions that tell the main thread to keep its hands off.
These tests pin that guidance so it cannot quietly fall out of the prompts.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

from clops import Concept, Op
from clops.runtime.core import Runtime
from clops.runtime.dispatch import INLINE_BUDGET_CHARS, render_prompt
from clops.runtime.mcp_server import (
    FlowServer,
    ServerConfig,
    next_step,
    workspace_root,
)


class Msg(Concept):
    description = "A thing."


class Out(Concept):
    description = "A result."


def _op():
    class DoThing(Op):
        Input = Msg
        Output = Out
        Intent = "Do the thing."
        Meta = "Test fixture Op for the file hand-off contract."

    return DoThing


# ---- the prompt contract ---------------------------------------------


def test_no_workspace_means_no_contract():
    """A bare Runtime has no project directory, so there is nowhere to point an
    agent. The prompt must not invent one."""
    prompt = render_prompt(_op(), {"a": 1}, execution_id="exec_x")
    assert "Long results go in a file" not in prompt
    assert "workspace" not in prompt.lower()
    assert "Include reasoning with your output." in prompt


def test_workspace_is_named_and_the_rule_is_stated():
    prompt = render_prompt(
        _op(), {"a": 1}, execution_id="exec_x", workspace="/w/run_abc"
    )
    assert "## Long results go in a file" in prompt
    assert "`/w/run_abc`" in prompt
    assert str(INLINE_BUDGET_CHARS) in prompt


def test_the_contract_covers_output_state_and_input():
    prompt = render_prompt(
        _op(), {"a": 1}, execution_id="exec_x", workspace="/w/run_abc"
    )
    section = prompt.split("## Long results go in a file", 1)[1]
    # All three directions a long value can travel.
    assert "**Your output.**" in section
    assert "**State stores.**" in section
    assert "**Input.**" in section


def test_exit_conditions_ask_for_a_summary_and_a_path():
    prompt = render_prompt(
        _op(), {"a": 1}, execution_id="exec_x", workspace="/w/run_abc"
    )
    exits = prompt.split("## Exit conditions", 1)[1]
    assert "summary" in exits
    assert "path" in exits


def test_short_results_are_explicitly_still_inline():
    """The contract has to carry its own exception, or every three-line result
    grows a file."""
    prompt = render_prompt(
        _op(), {"a": 1}, execution_id="exec_x", workspace="/w/run_abc"
    )
    assert "Short results stay inline" in prompt


def test_manifest_contract_drops_the_output_bullet_but_keeps_the_rest():
    """Under the manifest contract the agent already returns a one-liner, so
    telling it to summarize its output is noise. State and input still apply."""
    prompt = render_prompt(
        _op(),
        {"a": 1},
        execution_id="exec_x",
        workspace="/w/run_abc",
        manifest_mode=True,
        require_full_output=False,
    )
    section = prompt.split("## Long results go in a file", 1)[1]
    assert "**Your output.**" not in section
    assert "**State stores.**" in section
    assert "one-line manifest" in prompt


# ---- where the workspace goes ----------------------------------------


def test_temp_is_the_default(tmp_path):
    """Most hand-off files are traffic between steps of one run. They should not
    accumulate inside somebody's repo by default."""
    root = workspace_root(tmp_path)
    assert root is not None
    assert str(root).startswith(tempfile.gettempdir())
    assert workspace_root(tmp_path, "tmp") == root
    assert workspace_root(tmp_path, "temp") == root
    assert workspace_root(tmp_path, "") == root


def test_the_temp_root_is_scoped_to_the_user_and_the_project(tmp_path):
    root = workspace_root(tmp_path)
    assert f"clops-{os.getuid()}" in root.parts
    # Legible: the project's own directory name survives into the path.
    assert tmp_path.name in root.name
    # And unique: a different checkout of the same-named project does not collide.
    twin = tmp_path.parent / "twin" / tmp_path.name
    twin.mkdir(parents=True)
    assert workspace_root(twin) != root


def test_local_puts_runs_in_the_gitignored_tree(tmp_path):
    assert workspace_root(tmp_path, "local") == tmp_path / ".claude" / ".clops" / "runs"
    assert workspace_root(tmp_path, "project") == workspace_root(tmp_path, "local")


def test_off_means_no_root_at_all(tmp_path):
    for value in ("off", "none", "no", "false", "0"):
        assert workspace_root(tmp_path, value) is None, value


def test_the_setting_is_case_and_space_insensitive(tmp_path):
    assert workspace_root(tmp_path, "  Local  ") == workspace_root(tmp_path, "local")
    assert workspace_root(tmp_path, "OFF") is None


def test_an_explicit_path_is_taken_literally(tmp_path):
    assert workspace_root(tmp_path, "/var/clops") == Path("/var/clops")
    assert workspace_root(tmp_path, "~/runs") == Path.home() / "runs"


def test_a_relative_path_hangs_off_the_project(tmp_path):
    assert workspace_root(tmp_path, "./build/runs") == tmp_path / "build" / "runs"


def test_a_relative_path_is_normalised_not_resolved(tmp_path):
    """It gets rendered into agent prompts, where `<project>/../shared` reads
    badly — but resolving it could follow a symlink somewhere nobody named."""
    assert workspace_root(tmp_path, "../shared") == tmp_path.parent / "shared"


def test_a_mistyped_keyword_falls_back_rather_than_making_a_directory(tmp_path):
    """`workspace = tmpp` used to become `<project>/tmpp/` — a stray directory
    in somebody's repo, from a typo, silently. A bare word is a keyword or
    nothing."""
    default = workspace_root(tmp_path)
    for typo in ("tmpp", "lokal", "runs", "workspace"):
        assert workspace_root(tmp_path, typo) == default, typo


# ---- workspace allocation --------------------------------------------


def test_workspace_is_created_under_the_root(tmp_path):
    rt = Runtime()
    rt.set_workspace_root(tmp_path / "runs")
    path = rt.workspace_for("run_abc")
    assert path == str(tmp_path / "runs" / "run_abc")
    assert (tmp_path / "runs" / "run_abc").is_dir()


def test_no_root_means_no_workspace():
    assert Runtime().workspace_for("run_abc") is None


def test_workspace_off_suppresses_the_workspace():
    rt = Runtime()
    rt.set_workspace_root(None)
    assert rt.workspace_root is None
    assert rt.workspace_for("run_abc") is None


def test_an_unwritable_root_degrades_rather_than_failing(tmp_path):
    """A run that cannot get a workspace still runs; it just hands off inline."""
    blocker = tmp_path / "runs"
    blocker.write_text("not a directory")
    rt = Runtime()
    rt.set_workspace_root(blocker)
    assert rt.workspace_for("run_abc") is None


def test_an_empty_workspace_is_released_when_the_run_ends(tmp_path):
    rt = Runtime()
    rt.set_workspace_root(tmp_path / "runs")
    rt.workspace_for("run_abc")
    rt.release_workspace("run_abc")
    assert not (tmp_path / "runs" / "run_abc").exists()


def test_a_workspace_holding_files_survives_the_run(tmp_path):
    """The path the run reported has to keep resolving after the run ends."""
    rt = Runtime()
    rt.set_workspace_root(tmp_path / "runs")
    path = rt.workspace_for("run_abc")
    (tmp_path / "runs" / "run_abc" / "report.md").write_text("findings")
    rt.release_workspace("run_abc")
    assert (tmp_path / "runs" / "run_abc" / "report.md").read_text() == "findings"
    assert path


# ---- the oversized-state-write nudge ---------------------------------


class Big(Concept):
    description = "A store-using process."


@pytest.fixture
def state_server(tmp_path):
    from clops import Store

    class Stash(Op):
        Input = Big
        Output = Big
        Intent = "Put something in the store."
        Meta = "Test fixture Op for the oversized-write nudge."
        entry = True
        notes = Store(str)

    srv = FlowServer(ServerConfig(project_dir=tmp_path))
    srv.runtime.set_workspace_root(tmp_path / "runs")
    payload = srv._handle_start_process({"process": "Stash", "input": {}})
    run = srv.runtime.get_run(payload["run_id"])
    return srv, next(iter(run.pending_executions))


def _write(srv, execution_id, value):
    return srv._handle_state({
        "execution_id": execution_id,
        "store": "notes",
        "operation": "set",
        "value": value,
    })


def test_a_short_write_is_not_nagged(state_server):
    srv, execution_id = state_server
    assert "note" not in _write(srv, execution_id, "fine")


def test_an_oversized_write_is_stored_and_nudged(state_server):
    """The write stands — refusing it would strand an agent mid-step over a
    policy it can still satisfy on its next write."""
    srv, execution_id = state_server
    big = "x" * (INLINE_BUDGET_CHARS + 1)
    result = _write(srv, execution_id, big)
    assert result["result"] == big
    assert "note" in result
    assert "belongs in a file" in result["note"]


def test_the_nudge_names_the_run_workspace(state_server, tmp_path):
    srv, execution_id = state_server
    note = _write(srv, execution_id, "x" * (INLINE_BUDGET_CHARS + 1))["note"]
    assert str(tmp_path / "runs") in note


def test_the_nudge_measures_serialized_size_not_string_length(state_server):
    """A structured value is as expensive to read back as a string of the same
    serialized size."""
    srv, execution_id = state_server
    result = _write(srv, execution_id, {"rows": ["y" * 200] * 20})
    assert "note" in result


def test_reads_are_never_nudged(state_server):
    srv, execution_id = state_server
    _write(srv, execution_id, "x" * (INLINE_BUDGET_CHARS + 1))
    result = srv._handle_state({
        "execution_id": execution_id,
        "store": "notes",
        "operation": "get",
    })
    assert "note" not in result


def test_workspace_off_silences_the_nudge(state_server):
    """With nowhere to write a file, telling an agent to write one is noise."""
    srv, execution_id = state_server
    srv.runtime.set_workspace_root(None)
    assert "note" not in _write(srv, execution_id, "x" * (INLINE_BUDGET_CHARS + 1))


# ---- relay guidance ---------------------------------------------------


def test_dispatch_guidance_forbids_restating_the_prompt():
    guidance = next_step({"action": "dispatch"})
    assert "restate" in guidance


def test_dispatch_guidance_still_forbids_echoing_the_output():
    guidance = next_step({"action": "dispatch"})
    assert "no second argument" in guidance


def test_dispatch_guidance_offers_a_background_subagent():
    guidance = next_step({"action": "dispatch"})
    assert "background" in guidance


def test_dispatch_guidance_keeps_the_main_thread_out_of_the_files():
    guidance = next_step({"action": "dispatch"})
    assert "closed" in guidance


def test_parallel_guidance_also_forbids_restating_the_prompts():
    guidance = next_step({"action": "dispatch_parallel"})
    assert "restating" in guidance
    assert "single message" in guidance


# ---- end to end through the server -----------------------------------


def test_a_dispatched_prompt_names_a_real_directory(tmp_path):
    class Solo(Op):
        Input = Msg
        Output = Out
        Intent = "Do it."
        Meta = "Test fixture Op for end-to-end workspace wiring."
        entry = True

    srv = FlowServer(ServerConfig(project_dir=tmp_path))
    srv.runtime.set_workspace_root(tmp_path / "runs")
    payload = srv._handle_start_process({"process": "Solo", "input": {"a": 1}})
    prompt = payload["agent_config"]["prompt"]
    expected = tmp_path / "runs" / payload["run_id"]
    assert f"`{expected}`" in prompt
    assert expected.is_dir()


def test_a_finished_run_leaves_no_empty_directory_behind(tmp_path):
    class Solo2(Op):
        Input = Msg
        Output = Out
        Intent = "Do it."
        Meta = "Test fixture Op for workspace cleanup."
        entry = True

    srv = FlowServer(ServerConfig(project_dir=tmp_path))
    srv.runtime.set_workspace_root(tmp_path / "runs")
    payload = srv._handle_start_process({"process": "Solo2", "input": {"a": 1}})
    run_id = payload["run_id"]
    execution_id = next(iter(srv.runtime.get_run(run_id).pending_executions))
    srv._handle_complete({"execution_id": execution_id, "output": "done"})
    final = srv._handle_step_complete({"run_id": run_id})
    assert final["action"] == "done"
    assert not (tmp_path / "runs" / run_id).exists()
    assert "workspace" not in final


def test_boot_prunes_workspaces_abandoned_runs_left_behind(tmp_path):
    """A run killed mid-relay cannot release its own workspace. The next server
    start collects the empty ones — and only the empty ones."""
    from clops.runtime.mcp_server import clean_empty_workspaces

    root = tmp_path / "runs"
    (root / "run_dead").mkdir(parents=True)
    (root / "run_useful").mkdir(parents=True)
    (root / "run_useful" / "report.md").write_text("findings")

    clean_empty_workspaces(root)

    assert not (root / "run_dead").exists()
    assert (root / "run_useful" / "report.md").read_text() == "findings"


def test_boot_prune_is_a_no_op_before_any_run(tmp_path):
    from clops.runtime.mcp_server import clean_empty_workspaces

    clean_empty_workspaces(tmp_path / "never-created")  # must not raise
    clean_empty_workspaces(None)  # nor when the workspace is off


def test_a_project_can_turn_the_contract_off_in_dot_clops(tmp_path):
    """`workspace = off` reaches the prompt, not just the Runtime flag."""
    from clops.runtime.mcp_server import build_server_from_argv

    class Solo3(Op):
        Input = Msg
        Output = Out
        Intent = "Do it."
        Meta = "Test fixture Op for the workspace switch."
        entry = True

    (tmp_path / ".clops").write_text("[runtime]\nworkspace = off\n")
    srv = build_server_from_argv(["--project-dir", str(tmp_path)])
    payload = srv._handle_start_process({"process": "Solo3", "input": {"a": 1}})

    assert "Long results go in a file" not in payload["agent_config"]["prompt"]
    assert srv.runtime.workspace_root is None


def test_a_temp_workspace_is_not_readable_by_other_users(tmp_path):
    """A run's hand-off files are whatever the workflow handles, and the default
    root lives in a directory everyone on the box can write to."""
    rt = Runtime()
    rt.set_workspace_root(tmp_path / "clops-root" / "proj")
    path = Path(rt.workspace_for("run_abc"))

    for directory in (path, path.parent, path.parent.parent):
        mode = stat.S_IMODE(directory.stat().st_mode)
        assert not mode & 0o077, f"{directory} is {oct(mode)}"


def test_a_finished_run_reports_the_files_it_left(tmp_path):
    """The default workspace is a temp directory nobody would think to look in,
    so the terminal payload has to name it."""
    class Solo4(Op):
        Input = Msg
        Output = Out
        Intent = "Do it."
        Meta = "Test fixture Op for terminal workspace reporting."
        entry = True

    srv = FlowServer(ServerConfig(project_dir=tmp_path))
    srv.runtime.set_workspace_root(tmp_path / "runs")
    payload = srv._handle_start_process({"process": "Solo4", "input": {"a": 1}})
    run_id = payload["run_id"]
    (tmp_path / "runs" / run_id / "report.md").write_text("findings")

    execution_id = next(iter(srv.runtime.get_run(run_id).pending_executions))
    srv._handle_complete({"execution_id": execution_id, "output": "see report.md"})
    final = srv._handle_step_complete({"run_id": run_id})

    assert final["workspace"] == str(tmp_path / "runs" / run_id)
    assert "workspace" in next_step(final)


def test_a_run_that_wrote_nothing_reports_no_workspace():
    assert "workspace" not in next_step({"action": "done"})
