"""Dispatch-time assembly: prompt text + subagent config for a leaf Op.

Per Phase 1b spec, the agent_config returned to the main thread carries
only `{description, prompt, model?}`. Tools, hooks, and maxTurns live
statically in `.claude/agents/clops-executor.md` because Claude Code's
Agent tool has no per-call override for those fields. The Op's declared
Tools are mentioned in the prompt but not enforced at the Agent level.

The rendered prompt embeds the execution_id literally so the subagent
can pass it on every `complete`/`need` call. This is the explicit
correlation mechanism for Phase 1b (see phase-1b-spec.md section 2).

It also carries the run's **workspace** — a scratch directory the runtime
hands every leaf — plus the standing instruction to put long results in a
file there and hand back a summary and a path. Long values travelling
inline (through `complete`, or worse, through a state store every later
step then re-reads) are the dominant token cost in a multi-step run, and
the cheapest place to fix that is the prompt every agent already reads.
"""

from __future__ import annotations

from typing import Any, Optional

from clops import models, naming
from clops.concept import Concept
from clops.op import Op
from clops.registry import registry
from clops.snippet import Snippet, SnippetRole


def _render_concept_fields(cls: type[Concept], indent: str = "  ") -> list[str]:
    """Render a Concept's Fields as a list of lines, or empty if no Fields."""
    fields = getattr(cls, "_fields", {})
    if not fields:
        return []
    lines = []
    for f in fields.values():
        req = "required" if f.required else "optional"
        lines.append(f"{indent}- {f.name} ({req}): {f.description}")
    return lines


#: Roughly where an inline hand-off stops being cheaper than a file. Stated in
#: the prompt as a number the agent can actually judge against, and reused by
#: the runtime's oversized-state-write nudge so the two agree — an agent told
#: one threshold and corrected against another would be right to ignore both.
#: Not enforced: the runtime never sees a value until the agent has sent it.
INLINE_BUDGET_CHARS = 2000


def _render_workspace(workspace: str, *, use_manifest: bool) -> list[str]:
    """The standing file hand-off contract, rendered into every leaf prompt.

    The rule is the same in both output contracts — a long value costs the same
    whether it travels through `complete` or through a store — so only the
    `complete` line differs, and under the manifest contract it is dropped
    entirely because that contract already asks for a one-liner.
    """
    lines = [
        "## Long results go in a file",
        f"Your workspace for this run is `{workspace}`. It already exists.",
        "",
        "Anything long — past roughly "
        f"{INLINE_BUDGET_CHARS} characters, or more than a screenful someone "
        "would scroll — gets written to a file there with your normal file "
        "tools, and you hand back the path instead of the text:",
    ]
    if not use_manifest:
        lines.append(
            "- **Your output.** Make it a summary a reader can act on, plus the "
            "absolute path of what you wrote. Not the contents."
        )
    lines.extend([
        "- **State stores.** Store the path, never the file's text. Every later "
        "step that reads that store pays for the whole value, whether it needs "
        "it or not.",
        "- **Input.** A field you receive may itself be a path an earlier step "
        "wrote. Read it when you need the contents; don't copy it forward.",
        "",
        "Short results stay inline — a file for three lines costs more than it "
        "saves. When you do write one, name it for what is in it and say so in "
        "your summary, so the next step knows whether it needs to open it.",
    ])
    return lines


def render_prompt(
    op_cls: type[Op],
    input_value: Any,
    *,
    execution_id: str,
    need_supplemental: Any = None,
    pending_subroutine_result: Optional[dict] = None,
    state_manager: Optional[Any] = None,
    manifest_mode: bool = False,
    require_full_output: bool = True,
    workspace: Optional[str] = None,
) -> str:
    """Assemble the full prompt for a single leaf dispatch.

    Includes Intent, pinned + role-resolved Snippets, Concept descriptions,
    Op-declared Tools (mentioned, not enforced), exit conditions with the
    literal execution_id, the input value, and optionally:
      - a supplemental section for need-resolution retries.
      - a "Result from <subroutine>" section after a subroutine completes.
      - a workspace section, when the run has one, telling the agent to put
        long results in a file and hand back a summary plus the path.
    """
    intent = (op_cls.Intent or "").strip()

    uses_snippets = [u for u in op_cls.Uses if isinstance(u, Snippet)]
    required_snippets: list[Snippet] = []
    for req in op_cls.Requires:
        if isinstance(req, SnippetRole):
            matches = registry.snippets_with_role(req.role)
            if matches:
                required_snippets.append(matches[0])

    input_cls = op_cls.Input
    output_cls = op_cls.Output

    # Manifest contract: when the run is configured for manifest output AND this
    # leaf's output is not consumed in-band (no branch/loop decision, no loop
    # accumulator, not the run's terminal output), the agent confirms what it is
    # holding by name instead of serializing the full Output. Downstream steps
    # pull specifics on demand.
    use_manifest = manifest_mode and not require_full_output

    lines: list[str] = []
    lines.append(f"# {op_cls.__name__}")
    lines.append("")
    lines.append("## Your task")
    lines.append(intent)

    policy_blocks: list[tuple[str, str]] = []
    for s in uses_snippets:
        policy_blocks.append((s.id.replace("_", " ").title(), s.content))
    for s in required_snippets:
        label = (s.role or s.id).replace("_", " ").title()
        policy_blocks.append((label, s.content))
    if policy_blocks:
        lines.append("")
        lines.append("## Policies")
        for heading, content in policy_blocks:
            lines.append("")
            lines.append(f"### {heading}")
            lines.append(content.strip())

    lines.append("")
    lines.append("## What you'll receive")
    lines.append(f"{input_cls.__name__}: {input_cls.description.strip()}")
    lines.extend(_render_concept_fields(input_cls))
    lines.append("")
    if use_manifest:
        lines.append("## What to hold by the end")
        lines.append(
            f"By the end of this step you should be holding {output_cls.__name__} "
            f"({output_cls.description.strip()}). Keep it in your working memory and "
            "reply — you do NOT need to write it all out for clops. A later step will "
            "ask you for any piece it actually needs."
        )
        lines.extend(_render_concept_fields(output_cls))
    else:
        lines.append("## What you'll produce")
        lines.append(f"{output_cls.__name__}: {output_cls.description.strip()}")
        lines.extend(_render_concept_fields(output_cls))

    if workspace:
        lines.append("")
        lines.extend(_render_workspace(workspace, use_manifest=use_manifest))

    # Separate programmatic Tools from Op subroutine capabilities.
    tool_entries = [t for t in op_cls.Tools if not (isinstance(t, type) and issubclass(t, Op))]
    op_entries = [t for t in op_cls.Tools if isinstance(t, type) and issubclass(t, Op)]

    if tool_entries or op_entries:
        lines.append("")
        lines.append("## Capabilities available to you")
        lines.append(
            "Invoke any of these through "
            f"`{naming.tool('call_tool')}(execution_id, name, arguments)`."
        )
        for t in tool_entries:
            param_block = ""
            if t.parameters:
                rendered = ", ".join(
                    f"{k}: {_render_type(v)}" for k, v in t.parameters.items()
                )
                param_block = f" — arguments: {{{rendered}}}"
            lines.append(f"- `{t.name}` — {t.description.strip()}{param_block}")
        for sub_op in op_entries:
            sub_intent = (getattr(sub_op, "Intent", "") or "").strip().splitlines()
            first_line = sub_intent[0] if sub_intent else sub_op.__name__
            input_desc = sub_op.Input.description.strip() if hasattr(sub_op.Input, "description") else ""
            output_desc = ""
            variants = getattr(sub_op, "_output_variants", None) or (sub_op.Output,)
            if len(variants) == 1 and hasattr(variants[0], "description"):
                output_desc = variants[0].description.strip()
            lines.append(f"- `{sub_op.__name__}` — {first_line}")
            if input_desc:
                lines.append(f"  Input: {input_desc}")
                for fl in _render_concept_fields(sub_op.Input, indent="    "):
                    lines.append(fl)
            if output_desc:
                lines.append(f"  Returns: {output_desc}")
                for fl in _render_concept_fields(sub_op.Output, indent="    "):
                    lines.append(fl)
            lines.append("  Result delivered on your next dispatch.")

    if state_manager and state_manager.stores:
        lines.append("")
        lines.append("## " + state_manager.render_for_prompt())
        lines.append("")
        lines.append(state_manager.render_operations_for_prompt())
        lines.append("")
        lines.append(
            "Read or write state via "
            f'`{naming.tool("state")}(execution_id="{execution_id}", store=<name>, '
            "operation=<op>, ...)`."
        )

    # Resolve: pre-computed queries from input + state.
    resolve_spec = getattr(op_cls, "Resolve", None)
    if resolve_spec and state_manager:
        from clops.runtime.resolver import render_resolved_for_prompt, resolve

        resolved = resolve(resolve_spec, state_manager, input_value)
        # Register aliases for scoped operations (update/delete).
        for item in resolved:
            if item.source_op == "get" and "id" in item.bound_kwargs and item.value is not None:
                state_manager.register_resolved(
                    execution_id, item.name,
                    item.source_store, item.bound_kwargs,
                )
        rendered = render_resolved_for_prompt(resolved)
        if rendered:
            lines.append("")
            lines.append(rendered)

    lines.append("")
    lines.append("## Exit conditions")
    lines.append(f"Your execution_id is `{execution_id}`. Pass it on every call.")
    lines.append("")
    if use_manifest:
        lines.append(
            f"- Call `{naming.tool('complete')}(execution_id=\"{execution_id}\", output=…)` "
            "when your step is done. For `output`, pass a SHORT one-line manifest "
            "naming what you are now holding that a later step could ask you for "
            '(e.g. "parsed_config, error_list, summary"). Do not write out the full '
            "contents — your actual work stays in your reply, and you'll be asked for "
            "specifics only if a later step needs them."
        )
    elif workspace:
        lines.append(
            f"- Call `{naming.tool('complete')}(execution_id=\"{execution_id}\", output=…)` "
            "when your step is done. Include reasoning with your output. If the "
            "result runs long, write it to a file in your workspace first and "
            "make `output` a summary plus that path — a summary the caller can "
            "act on without opening the file, and a path for when it must."
        )
    else:
        lines.append(
            f"- Call `{naming.tool('complete')}(execution_id=\"{execution_id}\", output=…)` "
            "when your step is done. Include reasoning with your output."
        )
    lines.append(
        f"- Call `{naming.tool('need')}(execution_id=\"{execution_id}\", reason=…)` "
        "if you cannot proceed (missing info, malformed input)."
    )
    lines.append("- You must call exactly one of these before ending your turn.")

    lines.append("")
    lines.append("## Your input")
    lines.append(_format_input(input_value))

    if need_supplemental is not None:
        lines.append("")
        lines.append("## Supplemental input (resolving your need)")
        lines.append(
            "You previously called `need(...)`. The main thread has provided "
            "this additional information to help you proceed. Use it together "
            "with 'Your input' above; do not call `need` again unless the "
            "supplemental truly does not resolve the gap — doing so will fail "
            "the run."
        )
        lines.append("")
        lines.append(_format_input(need_supplemental))

    if pending_subroutine_result is not None:
        sr = pending_subroutine_result
        lines.append("")
        lines.append(f"## Result from {sr['op_name']}")
        lines.append(
            f"You previously invoked `{sr['op_name']}`. "
            "Its output is below. Use it to continue your work, "
            "then call `complete` with your final output."
        )
        lines.append("")
        lines.append(_format_input(sr["output"]))

    return "\n".join(lines)


def _render_type(py_type: Any) -> str:
    if hasattr(py_type, "__name__"):
        return py_type.__name__
    return repr(py_type)


def _format_input(value: Any) -> str:
    if isinstance(value, str):
        return value
    import json

    try:
        return json.dumps(value, indent=2, default=str)
    except TypeError:
        return repr(value)



def build_agent_config(
    op_cls: type[Op],
    input_value: Any,
    run_id: str,
    execution_id: str,
    *,
    need_supplemental: Any = None,
    pending_subroutine_result: Optional[dict] = None,
    state_manager: Optional[Any] = None,
    manifest_mode: bool = False,
    require_full_output: bool = True,
    workspace: Optional[str] = None,
) -> dict[str, Any]:
    """Build the per-dispatch subagent config payload.

    Shape matches the Agent tool's accepted parameters:
    `description`, `prompt`, and optional `model`. Tools/hooks/maxTurns
    are set statically in `.claude/agents/clops-executor.md` and are not
    per-dispatch overridable in Claude Code today.

    `need_supplemental`: set on need-resolution retries; appends a section.
    `pending_subroutine_result`: set on worker re-dispatches after a subroutine
    completes; appends a Result section with the subroutine's output.
    `state_manager`: if set, injects a State section with store values and operations.
    `workspace`: if set, injects the file hand-off contract naming that directory.
    """
    prompt = render_prompt(
        op_cls,
        input_value,
        execution_id=execution_id,
        need_supplemental=need_supplemental,
        pending_subroutine_result=pending_subroutine_result,
        state_manager=state_manager,
        manifest_mode=manifest_mode,
        require_full_output=require_full_output,
        workspace=workspace,
    )

    config: dict[str, Any] = {
        "description": f"Execute {op_cls.__name__} for {run_id}",
        "prompt": prompt,
    }
    if op_cls.Model:
        config["model"] = models.resolve(op_cls.Model)

    config["_metadata"] = {
        "run_id": run_id,
        "execution_id": execution_id,
        "op_name": op_cls.__name__,
    }
    return config
