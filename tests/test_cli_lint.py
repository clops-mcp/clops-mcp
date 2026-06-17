"""Tests for `clops lint`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clops.cli.lint import run


def test_lint_clean_library_exits_zero(capsys):
    exit_code = run(SimpleNamespace(library="examples.my_company"))
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[OK]" in captured.out
    assert "No lint findings" in captured.out


def test_lint_clean_smoke_library_exits_zero(capsys):
    """Any of our smoke-test libraries should lint clean."""
    pytest.importorskip("smoke_01_echo", reason="smoke library not installed")
    exit_code = run(SimpleNamespace(library="smoke_01_echo"))
    assert exit_code == 0
    assert "[OK]" in capsys.readouterr().out


def test_lint_unimportable_library_exits_one_with_fatal_prefix(capsys):
    exit_code = run(SimpleNamespace(library="definitely.not.a.real.package.xyz"))
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "[FATAL]" in captured.err
    assert "definitely.not.a.real.package.xyz" in captured.err


def test_lint_library_with_only_warnings_exits_zero(tmp_path, monkeypatch, capsys):
    """Warnings alone do not fail the build."""
    # Build a throwaway Op library with an intentionally long Intent to
    # trigger the intent_size warning.
    import sys, textwrap

    pkg_dir = tmp_path / "temp_warny_lib"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("from temp_warny_lib import ops  # noqa\n")
    (pkg_dir / "ops.py").write_text(textwrap.dedent(f"""\
        from clops import Concept, Op

        class I(Concept):
            description = "in"

        class O(Concept):
            description = "out"

        class WarnOp(Op):
            Input = I
            Output = O
            Intent = {"x" * 2500!r}
            Meta = "Test fixture Op for validating intent_size warning."
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    # Ensure a clean re-import
    for key in [k for k in list(sys.modules) if k.startswith("temp_warny_lib")]:
        del sys.modules[key]

    exit_code = run(SimpleNamespace(library="temp_warny_lib"))
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "WARNING" in captured.out
    assert "intent_size" in captured.out


def test_lint_library_with_errors_exits_one(tmp_path, monkeypatch, capsys):
    """A hard-error finding makes the command exit 1."""
    import sys, textwrap

    pkg_dir = tmp_path / "temp_bad_lib"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("from temp_bad_lib import ops  # noqa\n")
    # Op.Requires contains a plain string instead of a SnippetRole —
    # triggers the `requires_type` linter ERROR without any import-time
    # class-definition error.
    (pkg_dir / "ops.py").write_text(textwrap.dedent("""\
        from clops import Concept, Op

        class I(Concept):
            description = "in"

        class O(Concept):
            description = "out"

        class BadOp(Op):
            Input = I
            Output = O
            Intent = "Bad because Requires is misshaped."
            Meta = "Test fixture Op for validating requires_type error."
            Requires = ["not a SnippetRole"]
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    for key in [k for k in list(sys.modules) if k.startswith("temp_bad_lib")]:
        del sys.modules[key]

    exit_code = run(SimpleNamespace(library="temp_bad_lib"))
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ERROR" in captured.err
    assert "requires_type" in captured.err
