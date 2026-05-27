# Local setup

Recommended toolchain — opinionated but lightweight.

## Python
Whatever pyproject.toml pins. Use `pyenv` if you juggle versions.

## Editor
Anything that respects .editorconfig (most editors do by default).
VS Code, Helix, NeoVim, Sublime all fine.

## Optional helpers
- `ripgrep` (rg) — way faster than grep when navigating.
- `jq` — useful for inspecting any JSON the project emits.
- `gh` — GitHub CLI; needed if you want to use scripts/open_prs.py
  from the company-os repo.

None of these are required; the project runs with stdlib + dev deps.
