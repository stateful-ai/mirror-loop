"""Tests for the ``python -m guardrails <package.json>`` CLI."""

from __future__ import annotations

from pathlib import Path

from guardrails.cli import main

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_cli_passes_clean_package(capsys):
    code = main([str(FIXTURES / "clean_package.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("[OK]")


def test_cli_rejects_violating_package(capsys):
    code = main([str(FIXTURES / "violating_package.json")])
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("[REJECTED]")
    assert "NO_REAL_WORLD_PRIVATE_DATA" in out


def test_cli_usage_error_without_arg(capsys):
    code = main([])
    assert code == 2
    assert "usage:" in capsys.readouterr().err
