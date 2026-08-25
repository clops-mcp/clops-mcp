"""Tests for the path-aware registry (runtime-scoping-spec §2).

Ops are keyed by a qualified path derived from their module; the same bare name
can live in two namespaces; bare lookups resolve when unique and raise when
ambiguous. Uses lightweight stand-in classes (the registry only reads
``__name__`` / ``__module__`` / ``Namespace``) and fresh ``Registry`` instances,
so these are independent of the global registry and the Op metaclass.
"""

from __future__ import annotations

import pytest

from clops.registry import AmbiguousOpName, Registry, qualified_name


def _op(name: str, module: str, namespace: str | None = None) -> type:
    cls = type(name, (), {})
    cls.__module__ = module
    if namespace is not None:
        cls.Namespace = namespace
    return cls


# ---- qualified_name ---------------------------------------------------


def test_qualified_name_from_module_path():
    op = _op("HandleRefund", "work_ops.support.billing")
    assert qualified_name(op) == "work_ops/support/billing/HandleRefund"


def test_qualified_name_single_segment_module():
    assert qualified_name(_op("Echo", "smoke_01_echo")) == "smoke_01_echo/Echo"


def test_qualified_name_namespace_override_replaces_intra_path():
    # Override sets the intra-library path; the library root (module head) stays.
    op = _op("Authenticate", "work_ops.deeply.nested.module", namespace="security")
    assert qualified_name(op) == "work_ops/security/Authenticate"


def test_qualified_name_override_can_be_multi_segment():
    op = _op("HandleRefund", "work_ops.x", namespace="support/billing")
    assert qualified_name(op) == "work_ops/support/billing/HandleRefund"


# ---- coexistence + resolution -----------------------------------------


def test_same_bare_name_across_libraries_coexists():
    reg = Registry()
    a = _op("Authenticate", "lib_a.security")
    b = _op("Authenticate", "lib_b.auth")
    reg.register_op(a)
    reg.register_op(b)  # the collision the old registry hard-rejected

    # Both are kept under distinct qualified paths.
    assert reg.op("lib_a/security/Authenticate") is a
    assert reg.op("lib_b/auth/Authenticate") is b
    assert sorted(reg.qualified_paths_for("Authenticate")) == [
        "lib_a/security/Authenticate",
        "lib_b/auth/Authenticate",
    ]


def test_ambiguous_bare_name_raises():
    reg = Registry()
    reg.register_op(_op("Authenticate", "lib_a.security"))
    reg.register_op(_op("Authenticate", "lib_b.auth"))
    with pytest.raises(AmbiguousOpName, match="ambiguous"):
        reg.op("Authenticate")


def test_unique_bare_name_resolves():
    reg = Registry()
    a = _op("Echo", "lib_a")
    reg.register_op(a)
    assert reg.op("Echo") is a            # bare
    assert reg.op("lib_a/Echo") is a      # qualified
    assert reg.op("missing") is None
    assert reg.op("lib_a/Missing") is None


def test_reimport_same_path_overwrites_without_duplicating():
    reg = Registry()
    first = _op("X", "lib.mod")
    second = _op("X", "lib.mod")  # a reimport: same path, new class object
    reg.register_op(first)
    reg.register_op(second)
    assert reg.op("lib/mod/X") is second                  # last-write-wins
    assert reg.qualified_paths_for("X") == ["lib/mod/X"]  # multimap not duplicated


# ---- ref: minimal unambiguous reference (bare unless it collides) ------


def test_ref_is_bare_when_unique_qualified_on_collision():
    reg = Registry()
    solo = _op("Solo", "lib_a")
    g1 = _op("Greet", "lib_a")
    g2 = _op("Greet", "lib_b")
    for o in (solo, g1, g2):
        reg.register_op(o)
    assert reg.ref(solo) == "Solo"          # unique -> simple bare name
    assert reg.ref(g1) == "lib_a/Greet"     # collides -> qualified
    assert reg.ref(g2) == "lib_b/Greet"
    # ref round-trips through op()
    assert reg.op(reg.ref(g1)) is g1
    assert reg.op(reg.ref(solo)) is solo


def test_list_processes_only_qualifies_on_collision():
    # Integration: list_processes presents bare names unless a name collides.
    from clops.registry import registry
    from clops.runtime.core import Runtime

    def _entry(name: str, module: str) -> type:
        cls = type(name, (), {"entry": True, "Intent": f"do {name}"})
        cls.__module__ = module
        return cls

    for op in (_entry("Solo", "lib_a"), _entry("Greet", "lib_a"), _entry("Greet", "lib_b")):
        registry.register_op(op)

    names = set(Runtime().list_processes())
    assert "Solo" in names                                   # unique -> bare
    assert {"lib_a/Greet", "lib_b/Greet"} <= names           # collision -> qualified
    assert "Greet" not in names


def test_list_processes_filter_asks_for_a_qualified_path_when_ambiguous():
    """A bare name that two libraries both define can't be filtered on — the
    error says so rather than picking one."""
    from clops.registry import registry
    from clops.runtime.core import Runtime, RuntimeError_

    def _entry(name: str, module: str) -> type:
        cls = type(name, (), {"entry": True, "Intent": f"do {name}"})
        cls.__module__ = module
        return cls

    for op in (_entry("Greet", "lib_a"), _entry("Greet", "lib_b")):
        registry.register_op(op)

    rt = Runtime()
    assert rt.list_processes(processes=["lib_b/Greet"]) == ["lib_b/Greet"]

    with pytest.raises(RuntimeError_) as exc:
        rt.list_processes(processes=["Greet"])
    assert "qualified path" in str(exc.value)
    assert ".." not in str(exc.value)
