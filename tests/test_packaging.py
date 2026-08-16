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


def _version_locations():
    """`scripts/set_version.py`, or a skip if it isn't shipped.

    The sdist prunes `scripts/`, so these tests have to degrade rather than
    error when running from an unpacked sdist.
    """
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    if not (scripts / "set_version.py").exists():  # pragma: no cover
        pytest.skip("scripts/ not present (sdist)")
    sys.path.insert(0, str(scripts))
    try:
        import set_version
    finally:
        sys.path.remove(str(scripts))
    return set_version


def test_every_location_agrees_with_pyproject(project):
    """Seven places carry the version and nothing kept them in step.

    The release now derives the version from the tag and writes it everywhere,
    so drift on `main` is cosmetic rather than fatal — but cosmetic drift is
    what makes someone distrust the rest of a manifest. A plugin reporting
    0.3.0 from a 0.4.1 install is the kind of wrong that costs you the benefit
    of the doubt.

    Driven by `scripts/set_version.py`'s own list so that adding a location
    means editing one file, not two. A test with its own copy of the list is a
    test that stops covering the thing it was written for.
    """
    set_version = _version_locations()
    disagree = {
        label: value
        for label, value in set_version.read_all().items()
        if value is not None and value != project["version"]
    }
    assert not disagree, (
        f"pyproject.toml says {project['version']}; these disagree: {disagree}"
    )


def test_set_version_actually_reaches_every_location():
    """The list is only worth having if writing through it works.

    Exercised against a real write and then restored, because the failure this
    guards against is a pattern that silently stops matching after someone
    rewords the line around it — which a read-only check cannot see.
    """
    set_version = _version_locations()
    originals = {
        loc.full: loc.full.read_text() for loc in set_version.LOCATIONS if loc.full.exists()
    }
    try:
        set_version.write_all("9.9.9")
        written = {v for v in set_version.read_all().values() if v is not None}
        assert written == {"9.9.9"}, f"some location did not take the write: {written}"
    finally:
        for path, text in originals.items():
            path.write_text(text)

    # This test writes to the real source tree, and the release workflow runs
    # the suite *between* setting the version and building. A restore that
    # silently half-worked would ship the wrong version, so prove it rather
    # than trust the finally block.
    for path, text in originals.items():
        assert path.read_text() == text, f"{path} was not restored"


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
