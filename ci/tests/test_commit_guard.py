"""Tests for the build-pipeline commit guard (:mod:`ci.commit_guard`).

The cases are organized around the two invariants the guard enforces
(``NO_SOURCE_DIFF`` / ``BYTECODE_COMMITTED``), plus a regression case for
PR #2 ("Lock thesis + single falsifiable acceptance test") which committed
only ``.pyc`` files and is the motivating bug.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ci.commit_guard import (
    CommitGuardReport,
    DiffEntry,
    collect_diff,
    inspect_diff,
    is_compiled_artifact,
    main,
    parse_name_status,
)


# --- is_compiled_artifact ----------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "foo/bar/baz.pyc",
        "foo/bar/baz.pyo",
        "foo/bar/baz.pyd",
        "ci/__pycache__/anything.txt",  # under __pycache__ -> artifact regardless of suffix
        "deep/nested/__pycache__/module.cpython-314.pyc",
        "build/whatever",
        "dist/x.whl",
        "node_modules/foo/index.js",
        "mirror_loop.egg-info/PKG-INFO",
        "some/pkg.egg-info/SOURCES.txt",
        ".mypy_cache/3.14/foo.json",
        ".ruff_cache/0.1.0/foo.bin",
        ".pytest_cache/v/cache/lastfailed",
        "ext/native.so",
        "ext/native.dylib",
        "ext/native.dll",
        "obj/foo.o",
        "lib/foo.a",
        "jvm/Foo.class",
    ],
)
def test_is_compiled_artifact_true(path: str) -> None:
    assert is_compiled_artifact(path)


@pytest.mark.parametrize(
    "path",
    [
        "ci/commit_guard.py",
        "docs/GUARDRAILS.md",
        "pyproject.toml",
        "README.md",
        "fixtures/seed42_answers.json",
        "fixtures/m1_canonical.jsonl",
        "game/scenes/data/act1/act1_01_intake.scene",
        ".gitignore",
        "loop/example.py",
        # ``__pycache__`` only matters as a *path segment*, not as a substring
        # of a filename.
        "tools/clean__pycache__helper.py",
        # ``.egg-info`` only matters as a *directory name* suffix.
        "docs/egg-info-notes.md",
    ],
)
def test_is_compiled_artifact_false(path: str) -> None:
    assert not is_compiled_artifact(path)


# --- parse_name_status -------------------------------------------------------


def test_parse_name_status_handles_adds_mods_deletes_renames() -> None:
    raw = (
        "A\tci/commit_guard.py\n"
        "M\tpyproject.toml\n"
        "D\told/dead_module.py\n"
        "R092\told/path.py\tnew/path.py\n"
        "C075\toriginal.py\tcopied.py\n"
        "\n"  # blank lines tolerated
    )
    entries = parse_name_status(raw)
    assert entries == (
        DiffEntry("A", "ci/commit_guard.py"),
        DiffEntry("M", "pyproject.toml"),
        DiffEntry("D", "old/dead_module.py"),
        # Rename/copy entries keep the *destination* path: that's the file the
        # diff is adding to the tree, which is what the gate cares about.
        DiffEntry("R092", "new/path.py"),
        DiffEntry("C075", "copied.py"),
    )


def test_parse_name_status_rejects_malformed_lines() -> None:
    with pytest.raises(ValueError):
        parse_name_status("garbage-with-no-tabs\n")


def test_parse_name_status_rejects_rename_without_destination() -> None:
    with pytest.raises(ValueError):
        parse_name_status("R100\tonly_source.py\n")


def test_parse_name_status_empty_string_yields_empty_tuple() -> None:
    assert parse_name_status("") == ()
    assert parse_name_status("\n\n") == ()


# --- DiffEntry invariants ----------------------------------------------------


def test_diff_entry_requires_nonempty_status_and_path() -> None:
    with pytest.raises(ValueError):
        DiffEntry("", "foo.py")
    with pytest.raises(ValueError):
        DiffEntry("A", "")


def test_diff_entry_is_addition_or_modification() -> None:
    assert DiffEntry("A", "x.py").is_addition_or_modification
    assert DiffEntry("M", "x.py").is_addition_or_modification
    assert DiffEntry("R092", "x.py").is_addition_or_modification
    assert DiffEntry("C075", "x.py").is_addition_or_modification
    assert DiffEntry("T", "x.py").is_addition_or_modification
    assert not DiffEntry("D", "x.py").is_addition_or_modification


# --- inspect_diff: happy path ------------------------------------------------


def test_clean_source_diff_passes() -> None:
    report = inspect_diff(
        [
            DiffEntry("A", "ci/commit_guard.py"),
            DiffEntry("M", "pyproject.toml"),
            DiffEntry("A", "docs/GUARDRAILS.md"),
        ]
    )
    assert report.ok
    assert report.violations == ()
    assert report.source_paths == (
        "ci/commit_guard.py",
        "pyproject.toml",
        "docs/GUARDRAILS.md",
    )
    assert report.artifact_paths == ()
    assert "OK" in report.render()


def test_docs_only_diff_passes() -> None:
    # A documentation-only PR is a real source change; docs are first-class.
    report = inspect_diff([DiffEntry("M", "docs/THESIS.md")])
    assert report.ok


def test_deletion_only_of_source_passes() -> None:
    # Removing dead code is a legitimate source change.
    report = inspect_diff([DiffEntry("D", "loop/example.py")])
    assert report.ok


def test_cleanup_pr_deleting_pyc_passes() -> None:
    # Deleting accidentally-committed bytecode is the fix shape we want to
    # *allow* — the same PR can land alongside this guard module itself.
    report = inspect_diff(
        [
            DiffEntry("D", "acceptance/__pycache__/__init__.cpython-314.pyc"),
            DiffEntry("M", ".gitignore"),
        ]
    )
    assert report.ok
    assert report.source_paths == (".gitignore",)


# --- inspect_diff: NO_SOURCE_DIFF -------------------------------------------


def test_empty_diff_fails_no_source_diff() -> None:
    report = inspect_diff([])
    assert not report.ok
    assert [v.invariant for v in report.violations] == ["NO_SOURCE_DIFF"]
    assert "empty" in report.violations[0].message
    rendered = report.render()
    assert "REJECTED" in rendered
    assert "NO_SOURCE_DIFF" in rendered


def test_artifacts_only_diff_fails_both_invariants() -> None:
    # Adding only build artifacts trips BOTH invariants independently — the
    # diff has no source files AND adds bytecode. Both reasons are reported so
    # the failure message is fully diagnostic.
    report = inspect_diff(
        [
            DiffEntry("A", "build/output.bin"),
            DiffEntry("A", "mirror/__pycache__/play.cpython-314.pyc"),
        ]
    )
    assert not report.ok
    invariants = [v.invariant for v in report.violations]
    assert invariants == ["NO_SOURCE_DIFF", "BYTECODE_COMMITTED"]
    # NO_SOURCE_DIFF lists every path so the operator can see what *was*
    # touched, not just what was missing.
    no_source = report.violations[0]
    assert no_source.paths == (
        "build/output.bin",
        "mirror/__pycache__/play.cpython-314.pyc",
    )


# --- inspect_diff: BYTECODE_COMMITTED ---------------------------------------


def test_mixed_diff_with_pyc_addition_fails_bytecode_only() -> None:
    # A real source change is present, so NO_SOURCE_DIFF does not fire — but
    # the added .pyc still blocks the merge.
    report = inspect_diff(
        [
            DiffEntry("A", "mirror/state.py"),
            DiffEntry("A", "mirror/__pycache__/state.cpython-314.pyc"),
        ]
    )
    assert not report.ok
    assert [v.invariant for v in report.violations] == ["BYTECODE_COMMITTED"]
    assert report.violations[0].paths == (
        "mirror/__pycache__/state.cpython-314.pyc",
    )


def test_modification_of_existing_pyc_fails() -> None:
    # Even an ``M`` on an artifact path is a violation — it means the artifact
    # was tracked at some point and is being updated, which is the same bug.
    report = inspect_diff(
        [
            DiffEntry("M", "mirror/state.py"),
            DiffEntry("M", "mirror/__pycache__/state.cpython-314.pyc"),
        ]
    )
    assert not report.ok
    assert [v.invariant for v in report.violations] == ["BYTECODE_COMMITTED"]


# --- Regression: PR #2 ------------------------------------------------------


# The exact file list from PR #2 ("Lock thesis + single falsifiable acceptance
# test"). The original PR's ``files`` payload reported four ``.pyc`` files
# under ``__pycache__/``, all with 0 additions / 0 deletions. The guard must
# reject this diff with both invariants firing so the task is *failed*, not
# completed.
PR2_FILES: tuple[DiffEntry, ...] = (
    DiffEntry("A", "acceptance/__pycache__/__init__.cpython-314.pyc"),
    DiffEntry("A", "acceptance/__pycache__/evaluator.cpython-314.pyc"),
    DiffEntry("A", "tests/__pycache__/test_acceptance.cpython-314.pyc"),
    DiffEntry("A", "tests/__pycache__/test_reconciliation.cpython-314.pyc"),
)


def test_regression_pr2_pyc_instead_of_py_is_rejected() -> None:
    report = inspect_diff(PR2_FILES)

    # Both invariants fire: there is no source diff AND bytecode is committed.
    assert not report.ok
    assert [v.invariant for v in report.violations] == [
        "NO_SOURCE_DIFF",
        "BYTECODE_COMMITTED",
    ]
    # The rejection lists every offending path so the operator can act.
    assert report.violations[1].paths == tuple(e.path for e in PR2_FILES)
    # The rendered report carries the REJECTED verdict that the build
    # pipeline uses to fail the task.
    rendered = report.render()
    assert rendered.startswith("[REJECTED] commit guard:")
    assert "NO_SOURCE_DIFF" in rendered
    assert "BYTECODE_COMMITTED" in rendered
    for entry in PR2_FILES:
        assert entry.path in rendered


# --- CLI / git integration --------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    """Run ``git`` in a sandbox repo with deterministic identity and no signing."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
    )
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def sandbox_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with a single seed commit on ``main``."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main", "--quiet")
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed", "--quiet")
    return repo


def _commit(repo: Path, files: dict[str, str | None], message: str) -> None:
    """Apply a {path: contents-or-None-for-delete} change and commit it."""
    for path, contents in files.items():
        target = repo / path
        if contents is None:
            if target.exists():
                target.unlink()
            _git(repo, "rm", "--quiet", path)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
            _git(repo, "add", path)
    _git(repo, "commit", "-m", message, "--quiet")


def test_collect_diff_reads_git_name_status(sandbox_repo: Path) -> None:
    _git(sandbox_repo, "checkout", "-b", "feature", "--quiet")
    _commit(
        sandbox_repo,
        {
            "src/new.py": "x = 1\n",
            "docs/note.md": "hello\n",
        },
        "real source",
    )

    diff = collect_diff("main", cwd=str(sandbox_repo))
    assert sorted(e.path for e in diff) == ["docs/note.md", "src/new.py"]
    assert all(e.is_addition_or_modification for e in diff)


def test_cli_passes_clean_branch(sandbox_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git(sandbox_repo, "checkout", "-b", "feature", "--quiet")
    _commit(sandbox_repo, {"src/feature.py": "def f():\n    return 1\n"}, "add feature")

    cwd = Path.cwd()
    os.chdir(sandbox_repo)
    try:
        exit_code = main(["--base", "main"])
    finally:
        os.chdir(cwd)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.startswith("[OK] commit guard:")
    assert "src/feature.py" in out


def test_cli_rejects_pyc_only_branch(
    sandbox_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # End-to-end regression for the PR #2 shape: a branch whose only commit
    # adds bytecode under __pycache__/. The CLI must exit 1 with a REJECTED
    # report that the build pipeline can surface as a task failure.
    _git(sandbox_repo, "checkout", "-b", "feature", "--quiet")
    # Bypass .gitignore (mirrors how PR #2 slipped through: there was no
    # .gitignore yet, so an agent could stage __pycache__/*.pyc directly).
    _commit(
        sandbox_repo,
        {
            "pkg/__pycache__/mod.cpython-314.pyc": "<<bytecode>>",
            "pkg/tests/__pycache__/test_mod.cpython-314.pyc": "<<bytecode>>",
        },
        "fake completion",
    )

    cwd = Path.cwd()
    os.chdir(sandbox_repo)
    try:
        exit_code = main(["--base", "main"])
    finally:
        os.chdir(cwd)

    out = capsys.readouterr().out
    assert exit_code == 1
    assert out.startswith("[REJECTED] commit guard:")
    assert "NO_SOURCE_DIFF" in out
    assert "BYTECODE_COMMITTED" in out


def test_cli_accepts_explicit_refspec(
    sandbox_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(sandbox_repo, "checkout", "-b", "feature", "--quiet")
    _commit(sandbox_repo, {"src/x.py": "y = 2\n"}, "src change")

    cwd = Path.cwd()
    os.chdir(sandbox_repo)
    try:
        exit_code = main(["main..HEAD"])
    finally:
        os.chdir(cwd)

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "src/x.py" in out


def test_cli_rejects_passing_both_refspec_and_base(
    sandbox_repo: Path,
) -> None:
    cwd = Path.cwd()
    os.chdir(sandbox_repo)
    try:
        with pytest.raises(SystemExit) as excinfo:
            main(["main..HEAD", "--base", "main"])
    finally:
        os.chdir(cwd)
    # argparse exits 2 on usage error.
    assert excinfo.value.code == 2


def test_cli_returns_2_when_base_cannot_be_resolved(
    sandbox_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Sandbox repo has ``main`` but no ``origin/main``; passing an unknown
    # base must fail with exit code 2 (usage / environment), not 1 (rejected).
    cwd = Path.cwd()
    os.chdir(sandbox_repo)
    try:
        exit_code = main(["--base", "definitely-not-a-ref"])
    finally:
        os.chdir(cwd)

    err = capsys.readouterr().err
    assert exit_code == 2
    assert "commit-guard" in err


# --- Report shape ------------------------------------------------------------


def test_report_render_lists_source_paths_when_ok() -> None:
    report: CommitGuardReport = inspect_diff(
        [DiffEntry("A", "ci/commit_guard.py"), DiffEntry("M", "pyproject.toml")]
    )
    rendered = report.render()
    assert "[OK] commit guard: 2 changed file(s), 0 violation(s)" in rendered
    assert "source changes:" in rendered
    assert "ci/commit_guard.py" in rendered
    assert "pyproject.toml" in rendered
