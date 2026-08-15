"""The dispatch payload has to teach the caller how to use it.

A run only advances if the main thread relays correctly: spawn the subagent,
then report back. That instruction used to live only in the
`clops-orchestration` skill, which meant a client without the skill installed
received a payload it had no idea what to do with — and a gateway client never
has the skill.

These tests pin the behaviour that makes the skill optional rather than
required.
"""

from __future__ import annotations

import json

import pytest

from clops import Concept, Op, naming
from clops.runtime.mcp_server import FlowServer, ServerConfig, next_step


@pytest.fixture(autouse=True)
def restore_naming():
    server, pattern = naming.server_name(), naming.tool_pattern()
    yield
    naming.set_server_name(server)
    naming.set_tool_pattern(pattern)


# ---- which payloads get an instruction -------------------------------


@pytest.mark.parametrize(
    "action",
    ["dispatch", "dispatch_parallel", "needs_resolution", "done", "failed"],
)
def test_every_action_explains_itself(action):
    assert next_step({"action": action})


def test_payloads_without_an_action_are_left_alone():
    """`list_processes`, `state` and friends are answers, not instructions.
    Appending 'here is what to do next' to a read would be noise."""
    assert next_step({"processes": []}) is None
    assert next_step({}) is None


# ---- the instruction has to be actionable ----------------------------


def test_dispatch_names_the_template_and_the_tool_to_report_with():
    text = next_step(
        {"action": "dispatch", "agent_template": "clops-executor", "report_via": "step_complete"}
    )
    assert "clops-executor" in text
    assert naming.tool("step_complete") in text
    # The single most common failure mode is the main thread doing the work
    # itself instead of delegating, so the instruction says not to.
    assert "yourself" in text


def test_parallel_dispatch_asks_for_one_message_so_they_actually_run_concurrently():
    text = next_step(
        {
            "action": "dispatch_parallel",
            "agent_template": "clops-executor",
            "report_via": "step_complete_parallel",
        }
    )
    assert naming.tool("step_complete_parallel") in text
    assert "single message" in text


def test_needs_resolution_points_at_resolve_need():
    assert naming.tool("resolve_need") in next_step({"action": "needs_resolution"})


def test_failed_discourages_a_blind_retry():
    """A rerun restarts from the beginning, so an automatic retry repeats the
    whole run — including whatever failed."""
    assert "retry" in next_step({"action": "failed"})


# ---- it must survive a client that renames tools ---------------------


def test_instruction_uses_the_configured_tool_pattern():
    """The reason this matters: behind a gateway the skill is not installed AND
    the tool names differ. An instruction naming `mcp__clops__step_complete`
    there would send the caller after a tool that does not exist."""
    naming.set_tool_pattern("clops-support-{name_hyphenated}")
    text = next_step({"action": "dispatch", "report_via": "step_complete"})
    assert "clops-support-step-complete" in text
    assert "mcp__" not in text


# ---- end to end through the MCP surface ------------------------------


class Msg(Concept):
    description = "a message"


class Res(Concept):
    description = "a result"


def _server():
    class Echo(Op):
        Input = Msg
        Output = Res
        Intent = "echo the input back"
        Meta = "Test fixture Op for checking the shape of MCP tool results."
        entry = True

    srv = FlowServer(ServerConfig(libraries=[]))
    return srv


def test_start_process_result_carries_next_step():
    srv = _server()
    payload = json.loads(srv._dispatch_tool_call("start_process", {"process": "Echo", "input": "hi"})[0].text)
    assert payload["action"] == "dispatch"
    assert naming.tool("step_complete") in payload["next_step"]


def test_list_processes_result_does_not():
    srv = _server()
    payload = json.loads(srv._dispatch_tool_call("list_processes", {})[0].text)
    assert "next_step" not in json.dumps(payload)


def test_a_supplied_next_step_is_not_overwritten():
    """Leaves room for a payload to carry a more specific instruction of its
    own without this clobbering it."""
    from clops.runtime.mcp_server import _text

    out = json.loads(_text({"action": "done", "next_step": "custom"})[0].text)
    assert out["next_step"] == "custom"
