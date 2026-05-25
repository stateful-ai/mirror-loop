"""The harness is a measurement instrument, not a loop dependency.

The task is explicit: *measure ... before loop integration*, and *not wired into
the loop*. That is a property, not a promise, so it is pinned here: no production
package — the engine, the game, the world, the runtime, the guardrails, the
acceptance gate — may import :mod:`llmbench`. The dependency only ever runs the
other way (``llmbench`` imports the real world to build prompts), so a future
change that quietly threads the LLM harness into the loop fails this test instead
of shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every package that is part of the running game / engine. None may depend on the
#: measurement harness.
PRODUCTION_PACKAGES = ("loop", "game", "mirror", "runtime", "guardrails", "acceptance")

#: Any import of the harness, in either ``import``/``from`` form.
_IMPORTS_LLMBENCH = re.compile(r"^\s*(?:from|import)\s+llmbench\b", re.MULTILINE)


def _production_sources():
    for package in PRODUCTION_PACKAGES:
        for path in (REPO_ROOT / package).rglob("*.py"):
            # The other packages' own tests are still shipped code paths, but the
            # rule we care about is the runtime: skip nothing, scan it all.
            yield path


def test_no_production_package_imports_the_harness():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _production_sources()
        if _IMPORTS_LLMBENCH.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "llmbench must not be wired into the loop, but it is imported by: "
        + ", ".join(sorted(offenders))
    )


def test_the_scan_can_actually_detect_an_import():
    # Guard the guard: the regex must match the very thing it forbids, so a real
    # offender could never slip through a broken pattern.
    assert _IMPORTS_LLMBENCH.search("from llmbench.harness import measure")
    assert _IMPORTS_LLMBENCH.search("import llmbench")
    assert not _IMPORTS_LLMBENCH.search("import llmbench_something_else_unrelated\n# ok")


def test_production_packages_exist_on_disk():
    # If a package is renamed/removed the scan would silently cover nothing;
    # assert each target is real so the guarantee cannot rot into a no-op.
    for package in PRODUCTION_PACKAGES:
        assert (REPO_ROOT / package).is_dir(), f"missing package {package!r}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
