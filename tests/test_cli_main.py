"""Tests for the clops CLI subcommand dispatcher."""

from __future__ import annotations

import pytest

from clops.cli.main import build_parser


def test_parser_requires_subcommand():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_init_subcommand_resolves_to_init_handler():
    from clops.cli import init
    parser = build_parser()
    ns = parser.parse_args(["init", "--library", "pkg.x"])
    assert ns.command == "init"
    assert ns.library == ["pkg.x"]
    assert ns.project_dir == "."
    assert ns.no_skill is False
    assert ns.handler is init.run


def test_lint_subcommand_resolves_to_lint_handler():
    from clops.cli import lint
    parser = build_parser()
    ns = parser.parse_args(["lint", "my_company.ops"])
    assert ns.command == "lint"
    assert ns.library == "my_company.ops"
    assert ns.handler is lint.run


def test_init_preserves_all_flags():
    parser = build_parser()
    ns = parser.parse_args([
        "init",
        "--library", "pkg.x",
        "--project-dir", "/tmp/foo",
        "--no-skill",
    ])
    assert ns.library == ["pkg.x"]
    assert ns.project_dir == "/tmp/foo"
    assert ns.no_skill is True


def test_unknown_subcommand_exits_with_usage_error():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["not-a-real-command"])
