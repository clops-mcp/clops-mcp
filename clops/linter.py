"""Save-time linter.

Hard rules are enforced by the metaclass at class definition (see op.py).
The linter covers cross-artifact checks and soft (warning) rules.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from enum import Enum
from types import ModuleType
from typing import Any

from clops.combinators import walk as walk_body
from clops.concept import Concept
from clops.op import Op
from clops.registry import registry
from clops.snippet import Snippet, SnippetRole
from clops.tool import Tool


SNIPPET_SOFT_MAX = 1000
INTENT_SOFT_MAX = 2000
USES_REQUIRES_SOFT_MAX = 10
TOOLS_SOFT_MAX = 10
BODY_STEPS_SOFT_MAX = 15


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class LintFinding:
    severity: Severity
    op_name: str | None
    rule: str
    message: str

    def __str__(self) -> str:
        scope = f"[{self.op_name}] " if self.op_name else ""
        return f"{self.severity.value.upper()} {scope}({self.rule}) {self.message}"


@dataclass
class LintResult:
    findings: list[LintFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(
        self,
        severity: Severity,
        op_name: str | None,
        rule: str,
        message: str,
    ) -> None:
        self.findings.append(LintFinding(severity, op_name, rule, message))


def check_op(op_cls: type[Op], result: LintResult) -> None:
    name = op_cls.__name__

    intent = getattr(op_cls, "Intent", "")
    if isinstance(intent, str) and len(intent) > INTENT_SOFT_MAX:
        result.add(
            Severity.WARNING,
            name,
            "intent_size",
            f"Intent is {len(intent)} chars (soft limit {INTENT_SOFT_MAX}). "
            "Consider splitting.",
        )

    output_cls = getattr(op_cls, "Output", None)
    if isinstance(output_cls, type) and issubclass(output_cls, Concept):
        out_fields = list(getattr(output_cls, "_fields", {}).values())
        bulk = [f for f in out_fields if getattr(f, "bulk", False)]
        if bulk and len(bulk) == len(out_fields):
            result.add(
                Severity.WARNING,
                name,
                "output_bulk_only",
                f"Output {output_cls.__name__!r} declares only bulk field(s) "
                f"({', '.join(f.name for f in bulk)}), so the relay carries "
                "nothing but payload. Add at least one thin field — a handle "
                "or reference, a count, or your verdict — so the consumer has "
                "something to assert against.",
            )

    uses = list(getattr(op_cls, "Uses", []))
    requires = list(getattr(op_cls, "Requires", []))

    for item in uses:
        if isinstance(item, Snippet):
            registered = registry.snippet(item.id)
            if registered is None:
                result.add(
                    Severity.ERROR,
                    name,
                    "snippet_integrity",
                    f"Uses references Snippet {item.id!r} that isn't in the registry.",
                )
            elif registered != item:
                result.add(
                    Severity.ERROR,
                    name,
                    "snippet_integrity",
                    f"Snippet {item.id!r} in Uses doesn't match the registered content.",
                )
            if len(item.content) > SNIPPET_SOFT_MAX:
                result.add(
                    Severity.WARNING,
                    name,
                    "snippet_size",
                    f"Snippet {item.id!r} is {len(item.content)} chars "
                    f"(soft limit {SNIPPET_SOFT_MAX}).",
                )
        elif isinstance(item, type) and issubclass(item, Op):
            if registry.op(item.__name__) is None:
                result.add(
                    Severity.ERROR,
                    name,
                    "op_reference",
                    f"Uses references Op {item.__name__!r} that isn't registered.",
                )
        else:
            result.add(
                Severity.ERROR,
                name,
                "uses_type",
                f"Uses contains unsupported item {item!r}. Expected Snippet or Op.",
            )

    for item in requires:
        if isinstance(item, SnippetRole):
            if not registry.snippets_with_role(item.role):
                result.add(
                    Severity.WARNING,
                    name,
                    "requires_resolution",
                    f"No registered Snippet has role {item.role!r}. "
                    "Dispatch will fail until one is provided.",
                )
        else:
            result.add(
                Severity.ERROR,
                name,
                "requires_type",
                f"Requires contains unsupported item {item!r}. Expected SnippetRole.",
            )

    if len(uses) + len(requires) > USES_REQUIRES_SOFT_MAX:
        result.add(
            Severity.WARNING,
            name,
            "uses_requires_count",
            f"{len(uses) + len(requires)} entries across Uses+Requires "
            f"(soft limit {USES_REQUIRES_SOFT_MAX}).",
        )

    tools = list(getattr(op_cls, "Tools", []))
    for t in tools:
        if isinstance(t, Tool):
            if registry.tool(t.name) is None:
                result.add(
                    Severity.ERROR,
                    name,
                    "tool_integrity",
                    f"Tools references Tool {t.name!r} that isn't in the registry.",
                )
        elif isinstance(t, type) and issubclass(t, Op):
            # Op subroutine reference. The metaclass accepts these (op.py),
            # the renderer gives them their own capability section
            # (dispatch.py) and the server routes them to call_op
            # (mcp_server.py). Only integrity is worth checking here.
            if registry.op(t.__name__) is None:
                result.add(
                    Severity.ERROR,
                    name,
                    "tool_integrity",
                    f"Tools references Op subroutine {t.__name__!r} that isn't registered.",
                )
        else:
            result.add(
                Severity.ERROR,
                name,
                "tools_type",
                f"Tools contains {t!r}. Expected a Tool instance or an Op subclass.",
            )

    if len(tools) > TOOLS_SOFT_MAX:
        result.add(
            Severity.WARNING,
            name,
            "tools_count",
            f"{len(tools)} tools (soft limit {TOOLS_SOFT_MAX}).",
        )

    body = getattr(op_cls, "body", None)
    if body is not None:
        referenced = list(walk_body(body))
        for ref in referenced:
            if registry.op(ref.__name__) is None:
                result.add(
                    Severity.ERROR,
                    name,
                    "body_integrity",
                    f"body references Op {ref.__name__!r} that isn't registered.",
                )
        if len(referenced) > BODY_STEPS_SOFT_MAX:
            result.add(
                Severity.WARNING,
                name,
                "body_size",
                f"body references {len(referenced)} Ops (soft limit {BODY_STEPS_SOFT_MAX}).",
            )


def check_all(result: LintResult | None = None) -> LintResult:
    """Run cross-artifact checks over every registered Op."""
    result = result or LintResult()
    for op_cls in registry.ops().values():
        check_op(op_cls, result)
    return result


def check_library(pkg: ModuleType | str) -> LintResult:
    """Import (or reimport) a package recursively and lint what registers."""
    name = pkg if isinstance(pkg, str) else pkg.__name__
    _reimport_recursive(name)
    return check_all()


def _reimport_recursive(name: str) -> None:
    import sys

    pkg = importlib.import_module(name)
    path = getattr(pkg, "__path__", None)
    if path is None:
        if name in sys.modules:
            importlib.reload(sys.modules[name])
        return
    for mod_info in pkgutil.walk_packages(path, prefix=name + "."):
        if mod_info.name in sys.modules:
            importlib.reload(sys.modules[mod_info.name])
        else:
            importlib.import_module(mod_info.name)
    importlib.reload(pkg)
