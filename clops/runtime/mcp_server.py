"""MCP server wrapping the Runtime.

Tool surface is intentionally minimal — a fixed set of tools, regardless
of library size:

Main-thread tools:
    list_processes, start_process, step_complete, step_complete_parallel,
    resolve_need, run_status, abort_run

Subagent tools:
    complete, need, state

Tool-dispatch tool:
    call_tool(execution_id, name, arguments) — single entry point for
    subagent invocation of Op-declared capabilities. The subagent's
    rendered prompt lists the tools available to it (name + description
    + params); MCP routes call_tool to the actual Python handler.

This is the architecture-level interface. Op libraries contribute
*data* (processes, tools, snippets) — they never add new MCP tools.
An Op library with 200 Tools adds 0 MCP tools.

The server also owns the lifecycle of the Unix-socket SubagentStop hook
endpoint (bound at startup, torn down on shutdown). See
runtime/hook_server.py for the socket handler.
"""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
from dataclasses import field
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import mcp.types as mcp_types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from clops.registry import registry
from clops.runtime.core import Runtime, RuntimeError_


MAIN_TOOL_NAMES = (
    "list_processes",
    "start_process",
    "step_complete",
    "step_complete_parallel",
    "resolve_need",
    "run_status",
    "abort_run",
)
SUBAGENT_TOOL_NAMES = ("complete", "need", "call_tool", "state")
ALL_TOOL_NAMES = MAIN_TOOL_NAMES + SUBAGENT_TOOL_NAMES


@dataclass
class ServerConfig:
    libraries: list[str] = field(default_factory=list)  # Python package import paths
    project_dir: Optional[Path] = None     # $CLAUDE_PROJECT_DIR or cwd
    hook_socket_path: Optional[Path] = None


def load_library(library: str) -> None:
    """Import the configured Op library, recursively, so the registry populates.

    Op classes register themselves into the global registry as a side
    effect of their module being imported. Importing only the top-level
    package would miss any submodule the package's ``__init__.py`` does
    not explicitly import — exactly the bear-trap that ``clops show``
    avoids by walking the package. We do the same here so the runtime
    and ``show`` agree on what's available.
    """
    pkg = importlib.import_module(library)
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        return  # Single-module library; the import above was enough.
    for mod_info in pkgutil.walk_packages(pkg_path, prefix=library + "."):
        importlib.import_module(mod_info.name)


def resolve_project_dir(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path.cwd()


def runtime_state_dir(project_dir: Path) -> Path:
    return project_dir / ".claude" / ".clops"


def hook_socket_path(project_dir: Path) -> Path:
    return runtime_state_dir(project_dir) / f"hook-{os.getpid()}.sock"


def clean_stale_hook_sockets(project_dir: Path) -> None:
    """Remove hook sockets left behind by dead server processes."""
    state_dir = runtime_state_dir(project_dir)
    if not state_dir.exists():
        return
    for sock in state_dir.glob("hook-*.sock"):
        try:
            pid = int(sock.stem.split("-", 1)[1])
        except (ValueError, IndexError):
            continue
        try:
            os.kill(pid, 0)  # Check if process is alive.
        except ProcessLookupError:
            # Process is dead; socket is stale.
            try:
                sock.unlink()
            except OSError:
                pass
        except PermissionError:
            # Process exists but we can't signal it — leave it.
            pass


def _jsonify(value: Any) -> str:
    return json.dumps(value, default=str, indent=None)


def _text(payload: Any) -> list[mcp_types.TextContent]:
    return [mcp_types.TextContent(type="text", text=_jsonify(payload))]


def _error_text(message: str) -> list[mcp_types.TextContent]:
    return [mcp_types.TextContent(type="text", text=_jsonify({"error": message}))]


class FlowServer:
    """Stateful wrapper: owns the Runtime and the MCP Server glue."""

    def __init__(self, config: ServerConfig):
        self.config = config
        self.runtime = Runtime()
        self.project_dir = resolve_project_dir(config.project_dir)
        self.state_dir = runtime_state_dir(self.project_dir)
        self.hook_socket = config.hook_socket_path or hook_socket_path(self.project_dir)
        self._library_import_error: Optional[str] = None
        self._constants: dict[str, str] = {}  # From .clops [constants]
        self.server: Server = Server("clops")
        self._register_handlers()

    # ---- Library loading (called at boot) -----------------------------

    def load_library_safe(self) -> None:
        if not self.config.libraries:
            return
        for lib in self.config.libraries:
            try:
                load_library(lib)
            except Exception as exc:
                # Hold the error; surface on first tool call.
                self._library_import_error = (
                    f"Failed to import library {lib!r}: {exc!r}"
                )

    # ---- Handlers ----------------------------------------------------

    def _register_handlers(self) -> None:
        srv = self.server

        @srv.list_tools()
        async def _list_tools() -> list[mcp_types.Tool]:
            return self._build_tool_catalog()

        @srv.call_tool()
        async def _call_tool(name: str, arguments: dict) -> list[mcp_types.TextContent]:
            return self._dispatch_tool_call(name, arguments or {})

    def _build_tool_catalog(self) -> list[mcp_types.Tool]:
        tools: list[mcp_types.Tool] = []

        # Main-thread tools
        tools.append(mcp_types.Tool(
            name="list_processes",
            description="List available clops processes (Ops declared with entry=True).",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ))
        tools.append(mcp_types.Tool(
            name="start_process",
            description="Start a clops process. Returns a dispatch instruction or a terminal result.",
            inputSchema={
                "type": "object",
                "properties": {
                    "process": {"type": "string"},
                    "input": {},
                },
                "required": ["process"],
                "additionalProperties": False,
            },
        ))
        tools.append(mcp_types.Tool(
            name="step_complete",
            description="Relay a subagent's final output. Returns the next dispatch or a terminal result.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "result": {},
                },
                "required": ["run_id"],
                "additionalProperties": False,
            },
        ))
        tools.append(mcp_types.Tool(
            name="step_complete_parallel",
            description=(
                "Relay ALL N parallel subagents' final outputs after a "
                "dispatch_parallel. `results` is a dict keyed by execution_id; "
                "every execution_id from the dispatch_parallel payload must "
                "appear exactly once."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "results": {"type": "object", "additionalProperties": True},
                },
                "required": ["run_id", "results"],
                "additionalProperties": False,
            },
        ))
        tools.append(mcp_types.Tool(
            name="resolve_need",
            description=(
                "Resolve a subagent's need() by providing supplemental input. "
                "Runtime re-dispatches the same Op with the supplemental "
                "attached to its prompt. One resolution attempt per "
                "execution — a second need() on the re-dispatch fails the run."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "execution_id": {"type": "string"},
                    "supplemental_input": {},
                },
                "required": ["run_id", "execution_id"],
                "additionalProperties": False,
            },
        ))
        tools.append(mcp_types.Tool(
            name="run_status",
            description="Read a run's current status and execution summary.",
            inputSchema={
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        ))
        tools.append(mcp_types.Tool(
            name="abort_run",
            description="Abort an in-flight run.",
            inputSchema={
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
        ))

        # Subagent tools
        tools.append(mcp_types.Tool(
            name="complete",
            description="Subagent: signal this step is done with the given output.",
            inputSchema={
                "type": "object",
                "properties": {
                    "execution_id": {"type": "string"},
                    "output": {},
                },
                "required": ["execution_id"],
                "additionalProperties": False,
            },
        ))
        tools.append(mcp_types.Tool(
            name="need",
            description="Subagent: signal you cannot proceed. Fails this execution with the reason.",
            inputSchema={
                "type": "object",
                "properties": {
                    "execution_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["execution_id", "reason"],
                "additionalProperties": False,
            },
        ))

        tools.append(mcp_types.Tool(
            name="state",
            description=(
                "Read or write state stores. See the State section in your "
                "dispatch prompt for available stores and operations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "execution_id": {"type": "string"},
                    "store": {"type": "string", "description": "Store name"},
                    "operation": {
                        "type": "string",
                        "description": "Operation: get, set, list, add, delete, append, remove",
                    },
                    "id": {"type": "string", "description": "Entry key (dict stores)"},
                    "index": {"type": "integer", "description": "Position (list stores)"},
                    "value": {"description": "Value to set/add/append"},
                },
                "required": ["execution_id", "store", "operation"],
                "additionalProperties": False,
            },
        ))

        # Single dispatch tool for all Op-declared capabilities.
        # The subagent's prompt tells it what `name` to pass and what
        # `arguments` shape each tool expects. No per-Tool MCP entry.
        tools.append(mcp_types.Tool(
            name="call_tool",
            description=(
                "Subagent: invoke an Op-declared tool by name with the given arguments. "
                "The available tools, their descriptions, and their parameters are listed "
                "in your dispatch prompt under 'Tools available to you'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "execution_id": {"type": "string"},
                    "name": {"type": "string"},
                    "arguments": {"type": "object", "additionalProperties": True},
                },
                "required": ["execution_id", "name"],
                "additionalProperties": False,
            },
        ))
        return tools

    # ---- Dispatch -----------------------------------------------------

    def _dispatch_tool_call(self, name: str, args: dict) -> list[mcp_types.TextContent]:
        if self._library_import_error and name in MAIN_TOOL_NAMES:
            return _error_text(self._library_import_error)

        handler = self._resolve_tool(name)
        if handler is None:
            return _error_text(f"Unknown tool {name!r}.")
        try:
            return _text(handler(args))
        except RuntimeError_ as exc:
            return _error_text(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error_text(f"{type(exc).__name__}: {exc}")

    def _resolve_tool(self, name: str) -> Optional[Callable[[dict], Any]]:
        handlers = {
            "list_processes": self._handle_list_processes,
            "start_process": self._handle_start_process,
            "step_complete": self._handle_step_complete,
            "step_complete_parallel": self._handle_step_complete_parallel,
            "resolve_need": self._handle_resolve_need,
            "run_status": self._handle_run_status,
            "abort_run": self._handle_abort_run,
            "complete": self._handle_complete,
            "need": self._handle_need,
            "call_tool": self._handle_call_tool,
            "state": self._handle_state,
        }
        return handlers.get(name)

    # Main-thread handlers

    def _handle_list_processes(self, _args: dict) -> Any:
        return self.runtime.list_processes()

    def _handle_start_process(self, args: dict) -> Any:
        process = args["process"]
        return self.runtime.start(process, args.get("input"), enforce_entry=True)

    def _handle_step_complete(self, args: dict) -> Any:
        return self.runtime.step_complete(args["run_id"], args.get("result"))

    def _handle_step_complete_parallel(self, args: dict) -> Any:
        return self.runtime.step_complete_parallel(args["run_id"], args["results"])

    def _handle_resolve_need(self, args: dict) -> Any:
        return self.runtime.resolve_need(
            args["run_id"],
            args["execution_id"],
            args.get("supplemental_input"),
        )

    def _handle_run_status(self, args: dict) -> Any:
        return self.runtime.status(args["run_id"])

    def _handle_abort_run(self, args: dict) -> Any:
        return self.runtime.abort(args["run_id"])

    # Subagent handlers
    # parent_session_id is captured from the MCP _meta field when the
    # harness provides it; absent, the SubagentStop hook won't be able
    # to correlate and will fail-block. Acceptable for Phase 1b —
    # backlog.md tracks tightening.

    def _handle_complete(self, args: dict) -> Any:
        return self.runtime.complete(
            args["execution_id"],
            args.get("output"),
            parent_session_id=args.get("_parent_session_id"),
        )

    def _handle_need(self, args: dict) -> Any:
        return self.runtime.need(
            args["execution_id"],
            args["reason"],
            parent_session_id=args.get("_parent_session_id"),
        )

    def _handle_call_tool(self, args: dict) -> Any:
        # execution_id is carried for audit/logging and future per-execution
        # tool authorization. MVP: we validate the tool name is allowed
        # for the execution's Op and route to the appropriate handler.
        # Also: note the parent session so SubagentStop enforcement can
        # discriminate between our subagents and other agents in the session.
        self.runtime.note_session(args.get("_parent_session_id"))
        execution_id = args["execution_id"]
        tool_name = args["name"]
        tool_args = args.get("arguments") or {}

        _, execution = self.runtime._locate_execution(execution_id)
        op_cls = registry.op(execution.op_name)
        if op_cls is None:
            raise RuntimeError_(f"Op {execution.op_name!r} vanished from registry.")

        # Check if name resolves to an Op subroutine capability
        from clops.op import Op as _OpBase

        for entry in op_cls.Tools:
            if (
                isinstance(entry, type)
                and issubclass(entry, _OpBase)
                and entry.__name__ == tool_name
            ):
                return self.runtime.call_op(
                    execution_id,
                    tool_name,
                    entry,  # pass the resolved Op class
                    tool_args,
                    parent_session_id=args.get("_parent_session_id"),
                )

        # Otherwise: programmatic Tool (existing logic)
        from clops.tool import Tool as _ToolCls

        allowed_names = {t.name for t in op_cls.Tools if isinstance(t, _ToolCls)}
        if tool_name not in allowed_names:
            raise RuntimeError_(
                f"Op {execution.op_name!r} did not declare tool {tool_name!r}. "
                f"Declared tools: {sorted(allowed_names)}."
            )
        tool = registry.tool(tool_name)
        if tool is None:
            raise RuntimeError_(f"Unknown tool {tool_name!r}.")
        if tool.handler is None:
            raise RuntimeError_(f"Tool {tool_name!r} has no handler.")
        return tool.handler(**tool_args)

    def _handle_state(self, args: dict) -> Any:
        self.runtime.note_session(args.get("_parent_session_id"))
        execution_id = args["execution_id"]
        store = args["store"]
        operation = args["operation"]
        kwargs: dict[str, Any] = {}
        for key in ("id", "index", "value"):
            if key in args:
                kwargs[key] = args[key]
        return {"result": self.runtime.state(execution_id, store, operation, **kwargs)}


async def _run_stdio(server: FlowServer) -> None:
    async with stdio_server() as (read, write):
        init_opts = server.server.create_initialization_options()
        await server.server.run(read, write, init_opts)


def build_server_from_argv(argv: list[str]) -> FlowServer:
    import argparse

    from clops.runtime.clops import read_clops, read_clops_config

    parser = argparse.ArgumentParser(prog="clops-server")
    parser.add_argument(
        "--library",
        action="append",
        default=[],
        help="Python import path to an Op library package (repeatable).",
    )
    parser.add_argument("--project-dir", help="Project directory; falls back to $CLAUDE_PROJECT_DIR or cwd.")
    ns = parser.parse_args(argv)

    project_dir = Path(ns.project_dir) if ns.project_dir else None
    resolved_dir = resolve_project_dir(project_dir)

    # Read full config (libraries + constants).
    clops_config = read_clops_config(resolved_dir)

    # --library flags override .clops libraries; otherwise use .clops.
    libraries = ns.library if ns.library else clops_config.libraries

    config = ServerConfig(libraries=libraries, project_dir=project_dir)
    srv = FlowServer(config)
    srv._constants = clops_config.constants
    srv.runtime._project_constants = clops_config.constants
    srv.runtime._settings = clops_config.settings
    # A configured [system_prompt] overrides the built-in default; leaving the
    # section out keeps DEFAULT_SYSTEM_PROMPT (set on the Runtime).
    if clops_config.system_prompt is not None:
        srv.runtime._system_prompt = clops_config.system_prompt
    srv.load_library_safe()
    return srv


def main(argv: Optional[list[str]] = None) -> int:
    import sys

    srv = build_server_from_argv(sys.argv[1:] if argv is None else argv)
    srv.state_dir.mkdir(parents=True, exist_ok=True)
    clean_stale_hook_sockets(srv.project_dir)

    from clops.runtime.hook_server import HookServer

    hook_server = HookServer(srv.runtime, srv.hook_socket)
    hook_server.start()
    try:
        asyncio.run(_run_stdio(srv))
    finally:
        hook_server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
