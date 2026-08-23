import pytest

from clops.registry import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


@pytest.fixture(autouse=True)
def _isolated_project_dir(tmp_path, monkeypatch):
    """Keep run state out of the working repo.

    A FlowServer resolves its project dir from `$CLAUDE_PROJECT_DIR` and now
    writes each run's state file under `<project>/.claude/.clops/state/`.
    Without this, running the suite scatters run files through the checkout.
    """
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
