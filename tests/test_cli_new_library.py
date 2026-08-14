"""Tests for `clops new-library`."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from clops.cli.new_library import _validate_dotted_path, run


# ---- Validation -----------------------------------------------------


def test_validate_simple_path():
    assert _validate_dotted_path("my_lib") == ["my_lib"]


def test_validate_dotted_path():
    assert _validate_dotted_path("my_company.support_ops") == ["my_company", "support_ops"]


def test_validate_deep_path():
    assert _validate_dotted_path("a.b.c.d") == ["a", "b", "c", "d"]


@pytest.mark.parametrize("bad", [
    "",
    "   ",
    ".foo",
    "foo.",
    "foo..bar",
    "1foo",
    "foo-bar",
    "foo.bar-baz",
    "class",
    "foo.def",
])
def test_validate_rejects_bad_paths(bad):
    with pytest.raises(ValueError):
        _validate_dotted_path(bad)


# ---- Scaffolding happy path ----------------------------------------


def test_scaffold_dotted_path_creates_expected_tree(tmp_path, capsys):
    ns = SimpleNamespace(
        dotted_path="my_company.support_ops",
        target=str(tmp_path),
        force=False,
    )
    exit_code = run(ns)
    assert exit_code == 0

    root = tmp_path / "my_company"
    assert (root / "pyproject.toml").is_file()
    assert (root / "README.md").is_file()
    assert (root / "my_company" / "__init__.py").is_file()
    assert (root / "my_company" / "support_ops" / "__init__.py").is_file()
    assert (root / "my_company" / "support_ops" / "concepts.py").is_file()
    assert (root / "my_company" / "support_ops" / "ops.py").is_file()

    # The leaf __init__ imports concepts + ops, and tries snippets
    leaf_init = (root / "my_company" / "support_ops" / "__init__.py").read_text()
    assert "from my_company.support_ops import concepts, ops" in leaf_init
    assert "from my_company.support_ops import snippets" in leaf_init

    # The namespace __init__ is just a docstring
    ns_init = (root / "my_company" / "__init__.py").read_text()
    assert "Namespace package" in ns_init

    # pyproject declares the right package name and dependencies
    pyproject = (root / "pyproject.toml").read_text()
    assert 'name = "my-company-support-ops"' in pyproject
    assert 'include = ["my_company*"]' in pyproject
    # `clops-mcp`, not `clops` — the latter is an unrelated project on PyPI, so
    # scaffolding it would make every generated library depend on a stranger's
    # package.
    assert 'dependencies = ["clops-mcp"]' in pyproject
    assert 'requires-python = ">=3.11"' in pyproject


def test_scaffold_single_segment_path(tmp_path):
    ns = SimpleNamespace(dotted_path="simple_lib", target=str(tmp_path), force=False)
    assert run(ns) == 0

    root = tmp_path / "simple_lib"
    assert (root / "pyproject.toml").is_file()
    assert (root / "simple_lib" / "__init__.py").is_file()
    assert (root / "simple_lib" / "concepts.py").is_file()
    assert (root / "simple_lib" / "ops.py").is_file()

    leaf_init = (root / "simple_lib" / "__init__.py").read_text()
    assert "from simple_lib import concepts, ops" in leaf_init


def test_scaffold_deep_path_writes_all_intermediate_inits(tmp_path):
    ns = SimpleNamespace(dotted_path="a.b.c.d", target=str(tmp_path), force=False)
    assert run(ns) == 0

    root = tmp_path / "a"
    for p in ["a/__init__.py", "a/b/__init__.py", "a/b/c/__init__.py", "a/b/c/d/__init__.py"]:
        assert (root / p).is_file()


# ---- Conflict handling ----------------------------------------------


def test_scaffold_refuses_to_overwrite_existing_dir(tmp_path, capsys):
    existing = tmp_path / "my_company"
    existing.mkdir()
    (existing / "something.txt").write_text("do not clobber")

    ns = SimpleNamespace(
        dotted_path="my_company.support_ops",
        target=str(tmp_path),
        force=False,
    )
    assert run(ns) == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    # Did NOT clobber the existing file.
    assert (existing / "something.txt").read_text() == "do not clobber"


def test_scaffold_force_overwrites(tmp_path):
    existing = tmp_path / "my_company"
    existing.mkdir()

    ns = SimpleNamespace(
        dotted_path="my_company.support_ops",
        target=str(tmp_path),
        force=True,
    )
    assert run(ns) == 0
    assert (existing / "pyproject.toml").is_file()


# ---- Generated library is actually valid ----------------------------


def test_scaffolded_library_lints_clean(tmp_path, monkeypatch):
    """The scaffold's demo Op should lint with no errors."""
    ns = SimpleNamespace(
        dotted_path="scaffolded_test_lib",
        target=str(tmp_path),
        force=False,
    )
    assert run(ns) == 0

    # Put the scaffolded package on sys.path so it can be imported.
    pkg_root = tmp_path / "scaffolded_test_lib"
    monkeypatch.syspath_prepend(str(pkg_root))
    # Clean any prior import of this test's throwaway name
    for key in [k for k in list(sys.modules) if k.startswith("scaffolded_test_lib")]:
        del sys.modules[key]

    from clops.linter import check_library
    result = check_library("scaffolded_test_lib")
    assert not result.errors, [str(f) for f in result.errors]


# ---- Error paths ----------------------------------------------------


def test_scaffold_invalid_dotted_path_errors(tmp_path, capsys):
    ns = SimpleNamespace(dotted_path="1-bad", target=str(tmp_path), force=False)
    assert run(ns) == 1
    assert "invalid" in capsys.readouterr().err.lower()


def test_scaffold_nonexistent_target_errors(tmp_path, capsys):
    ns = SimpleNamespace(
        dotted_path="my_lib",
        target=str(tmp_path / "does-not-exist"),
        force=False,
    )
    assert run(ns) == 1
    assert "does not exist" in capsys.readouterr().err
