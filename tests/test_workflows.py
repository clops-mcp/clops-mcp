"""The repo requires every GitHub Action to be pinned to a full-length SHA.

That policy is enforced by GitHub at run time, which means a violation shows up
as a failed *release* — the worst moment to find out. This catches it at
`pytest` time instead.

Why the policy is worth guarding rather than trusting people to remember: a
moving tag like `@v7` can be repointed at a different commit by whoever owns
the action, and the release job holds `id-token: write` against PyPI. A
compromised action there could publish as us. A SHA cannot be repointed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# `uses: owner/repo@ref` — also matches `./local` and `docker://`, which the
# check below lets through, because neither is a mutable upstream reference.
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)", re.M)
SHA = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files() -> list[Path]:
    if not WORKFLOWS.is_dir():  # pragma: no cover - sdist prunes .github
        pytest.skip(".github/workflows not present (sdist)")
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not files:  # pragma: no cover
        pytest.skip("no workflows to check")
    return files


def test_every_action_is_pinned_to_a_full_length_sha():
    unpinned = []
    for path in _workflow_files():
        for ref in USES.findall(path.read_text()):
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            _, _, rev = ref.partition("@")
            if not SHA.match(rev):
                unpinned.append(f"{path.name}: {ref}")

    assert not unpinned, (
        "these action references are not pinned to a 40-character commit SHA, "
        "and GitHub will reject the workflow at run time: " + "; ".join(unpinned)
    )


def test_each_pin_records_the_tag_it_came_from():
    """A bare SHA is unreviewable — nobody can tell v7.0.1 from a random commit.

    The trailing `# v7.0.1` is a note to a human, not something git checks, so
    the only thing keeping it there is this test.
    """
    missing = []
    for path in _workflow_files():
        for line in path.read_text().splitlines():
            match = USES.match(line)
            if not match:
                continue
            ref = match.group(1)
            if ref.startswith("./") or ref.startswith("docker://"):
                continue
            if "#" not in line.split("uses:", 1)[1]:
                missing.append(f"{path.name}: {ref}")

    assert not missing, (
        "pin these to a readable version with a trailing comment, "
        "e.g. `uses: actions/checkout@<sha> # v7.0.1`: " + "; ".join(missing)
    )
