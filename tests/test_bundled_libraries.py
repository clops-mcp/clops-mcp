"""Guardrail: every Op library shipped under clops/example_library imports and lints.

Op shape is enforced by the metaclass at class-definition time, so a library
whose Ops are missing `Meta` — or whose modules import each other by the wrong
path — fails at *import*, not at call time. Nothing else in the suite imports
the bundled libraries (the CLI lint tests use their own fixtures), and
`clops.example_library.code_review` shipped broken twice because of it: first importing
its siblings by bare name (`from code_review import ...`), then with no `Meta`
on any of its eleven Ops.

Discovery is dynamic, so a new library added under clops/example_library is covered the
moment it lands.
"""

import importlib
import pkgutil

import pytest

import clops.example_library
from clops.linter import check_library
from clops.registry import registry


STDLIB_LIBRARIES = sorted(
    m.name for m in pkgutil.iter_modules(clops.example_library.__path__) if m.ispkg
)


def test_bundled_libraries_are_discovered():
    """Guard the guard: empty discovery would make everything below vacuous."""
    assert STDLIB_LIBRARIES, "no packages found under clops/example_library"
    assert "code_review" in STDLIB_LIBRARIES


@pytest.mark.parametrize("library", STDLIB_LIBRARIES)
def test_bundled_library_imports(library):
    # A module that raises never lands in sys.modules, so this re-executes —
    # and re-fails — even if an earlier test already imported the library.
    importlib.import_module(f"clops.example_library.{library}")


@pytest.mark.parametrize("library", STDLIB_LIBRARIES)
def test_bundled_library_registers_ops_and_lints(library):
    # check_library reimports recursively, so the metaclass runs again against
    # the registry this test just cleared: an Op that fails validation raises
    # here, and one that never registers shows up as an empty registry.
    result = check_library(f"clops.example_library.{library}")
    assert result.ok, "\n".join(str(f) for f in result.errors)
    assert registry.ops(), f"clops.example_library.{library} registered no Ops"
