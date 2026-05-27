"""Smoke tests for repo-root governance docs.

These pin down that the policy files newcomers and security researchers expect
to find at the top of the repository actually exist and aren't empty stubs.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_security_md_exists_and_mentions_security_and_report():
    path = REPO_ROOT / "SECURITY.md"
    assert path.is_file(), f"expected {path} to exist at the repo root"

    text = path.read_text(encoding="utf-8").lower()
    assert "security" in text, "SECURITY.md should mention 'security'"
    assert "report" in text, "SECURITY.md should explain how to report an issue"
