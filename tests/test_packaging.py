"""Tests for what the installed distribution actually exposes.

These assert against `pyproject.toml` rather than against an installed
distribution, so they pass in a source checkout with no build step. The release
workflow covers the other half — it installs the built wheel into a clean venv
and imports from it — but that only runs on a tag, which is far too late to
learn that an entry point vanished.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the project targets 3.11+
    tomllib = pytest.importorskip("tomli")

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def project() -> dict:
    if not PYPROJECT.exists():  # pragma: no cover - sdist keeps it, but be safe
        pytest.skip("pyproject.toml not present")
    return tomllib.loads(PYPROJECT.read_text())["project"]


def test_distribution_is_named_clops_mcp(project):
    """`clops` on PyPI is an unrelated project. Publishing under it, or telling
    anyone to install it, points them at somebody else's code."""
    assert project["name"] == "clops-mcp"


@pytest.mark.parametrize(
    "script",
    ["clops", "clops-server", "clops-hook", "clops-mcp"],
)
def test_console_script_is_declared(project, script):
    assert script in project["scripts"]


def test_uvx_shorthand_works_because_a_script_matches_the_distribution_name():
    """`uvx <name>` installs package <name> and runs an executable ALSO called
    <name>. Without a `clops-mcp` script, `uvx clops-mcp` fails outright — uv
    lists the other scripts and tells you to use `uvx --from` instead. And the
    obvious next guess, `uvx clops`, installs the unrelated PyPI project.

    Asserted separately from the parametrized case above because the reason is
    not "we happen to ship four scripts" — it is that this one name has to equal
    the distribution name.
    """
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    assert project["name"] in project["scripts"]


def test_clops_mcp_and_clops_server_are_the_same_entry_point(project):
    """The alias exists for `uvx`; it must not drift into a second server."""
    assert project["scripts"]["clops-mcp"] == project["scripts"]["clops-server"]


def test_server_help_reports_the_name_it_was_invoked_as(capsys):
    """argparse must not hardcode `prog`. The same entry point is installed
    under two names, so a hardcoded one prints usage for a command the reader
    did not type."""
    from clops.runtime.mcp_server import build_server_from_argv

    original = sys.argv[0]
    sys.argv[0] = "/somewhere/bin/clops-mcp"
    try:
        with pytest.raises(SystemExit):
            build_server_from_argv(["--help"])
        out = capsys.readouterr().out
    finally:
        sys.argv[0] = original

    assert "clops-mcp" in out
    assert "usage: clops-server" not in out
