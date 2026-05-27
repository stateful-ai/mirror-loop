"""``python -m ci`` -> run the commit guard against the current branch.

This is a convenience alias for ``python -m ci.commit_guard`` so the build
pipeline can call a single module-name entry point.
"""

from .commit_guard import main

if __name__ == "__main__":
    raise SystemExit(main())
