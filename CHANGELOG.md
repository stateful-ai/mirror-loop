# Changelog
All notable changes to Mirror Loop will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- `ci/commit_guard.py` — build-pipeline gate that rejects diffs with no
  source change (`NO_SOURCE_DIFF`) or that add/modify compiled artifacts
  (`BYTECODE_COMMITTED`). Run with `python -m ci.commit_guard --base main`.
  Closes the PR #2 class of bug (a task "completed" with only `.pyc` files
  under `__pycache__/` and no `.py` source); a regression test pins the
  exact PR #2 file list.
### Changed
### Fixed
