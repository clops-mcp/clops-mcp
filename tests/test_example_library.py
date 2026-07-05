"""End-of-Phase-0 integration check: lint the synthetic Op library."""

from clops.linter import check_library


def test_example_library_lints_clean():
    result = check_library("examples.my_company")
    assert result.ok, "\n".join(str(f) for f in result.errors)


def test_example_library_registers_expected_ops():
    check_library("examples.my_company")
    from clops.registry import registry

    # Keys are qualified paths now; bare names resolve via the registry.
    for bare in ("ClassifyIntent", "DraftResponse", "HandleSupport"):
        assert registry.op(bare) is not None


def test_handle_support_is_composition():
    check_library("examples.my_company")
    from clops.registry import registry

    handle = registry.op("HandleSupport")
    assert handle is not None
    assert not handle.is_leaf()
