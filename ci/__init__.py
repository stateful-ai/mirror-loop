"""Mirror Loop — build-pipeline checks (the commit-time gates).

``ci/`` is the build-pipeline counterpart to the other gates in this repo:

* :mod:`acceptance.predictability` — the thesis gate (does a played session
  beat baseline? — ``docs/THESIS.md``).
* :mod:`guardrails.invariants` — the content gate (does a generated content
  package honor the world invariants? — ``docs/GUARDRAILS.md``).
* :mod:`ci.commit_guard` — the **commit gate**: does the diff a coding task
  is about to merge actually contain source changes, and is it free of
  compiled-artifact noise?

The motivating incident is PR #2 (``Lock thesis + single falsifiable
acceptance test``), where the task's "completed" diff consisted entirely of
four ``.pyc`` files under ``__pycache__/`` (0 additions / 0 deletions) — no
actual Python source. The agent reported success and the PR almost merged. The
commit guard fails that class of diff explicitly so a coding task producing no
source change, or one that smuggles compiled bytecode in, is rejected with a
clear reason instead of marked completed.

Run it against the current branch::

    python -m ci.commit_guard            # compares HEAD against origin/main
    python -m ci.commit_guard --base main
    python -m ci.commit_guard main..HEAD

The public API lives in :mod:`ci.commit_guard` — import directly from there
(``from ci.commit_guard import inspect_diff, DiffEntry``). This package's
``__init__`` deliberately stays import-free so ``python -m ci.commit_guard``
runs without the ``RuntimeWarning`` :mod:`runpy` raises when a submodule has
already been loaded by package initialization.
"""
