"""The two M1 CI gates, as a runnable Python package.

The Mirror Loop M1 acceptance bar names **two** branch-protected CI checks
(``docs/mirror_loop_m1_synthesis.md``, "Gates (both CI-blocking): byte-identity
replay under seed 42; structural baseline≡adaptive parity";
[`docs/adr/0001-m1-locks.md`](../docs/adr/0001-m1-locks.md)). This package is
the single source of truth for *what* each gate runs, so the workflow YAML and
the dry-run harness drive the same test selection (one place to edit, no
chance of the YAML and the test list drifting apart).

Two thin runners (``ci.byte_identity_replay`` / ``ci.baseline_adaptive_parity``)
each invoke the selection in :mod:`ci.gates` and surface a non-zero exit on
failure — those are the commands the GitHub Actions workflows shell out to,
and the same commands a developer can run locally to reproduce a red gate.

The dry-run (:mod:`ci.dry_run`) deliberately breaks determinism, one class of
break per gate, and verifies that each break flips the corresponding gate red
— the acceptance bar's "flips them red in a dry run" clause.
"""
