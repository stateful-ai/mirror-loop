# CI gates and branch protection

The Mirror Loop M1 acceptance bar names **two** CI checks that must be
required by GitHub branch protection on `main`. They are documented as
"Gates (both CI-blocking)" in
[`mirror_loop_m1_synthesis.md`](./mirror_loop_m1_synthesis.md) and locked in
[ADR-0001](./adr/0001-m1-locks.md). This page is the single normative record
of *what those checks are, what they run, and how to enable them*.

## The two required checks

| Check name | Workflow | What it runs | Why it exists |
|---|---|---|---|
| `byte-identity-replay` | [`.github/workflows/byte-identity-replay.yml`](../.github/workflows/byte-identity-replay.yml) | `python -m ci.byte_identity_replay` — the `game/tests/test_replay.py` suite plus `python -m game.replay --check` against the committed golden fixture. | Identical `(seed, input log)` reproduces byte-identical state across runs and processes; no wall-clock or unsynced randomness on the game path. The byte-identity contract guards against silent behavior drift. |
| `baseline-adaptive-parity` | [`.github/workflows/baseline-adaptive-parity.yml`](../.github/workflows/baseline-adaptive-parity.yml) | `python -m ci.baseline_adaptive_parity` — the `game/tests/test_variants.py` same-shell parity suite plus the `test_playtest.py` assertions that adaptive and the fixed baseline produce identical decision points under the conservative-null population. | The adaptive arm and the baseline arms must run through the *same* engine (one toggle, never a forked code path). Structural parity is what lets the blind A/B mean anything — it pins the only difference between arms to the adaptation seam itself. |

Both check names are also the literal job ids in the workflow YAMLs and the
constants `BYTE_IDENTITY_REPLAY_CHECK` / `BASELINE_ADAPTIVE_PARITY_CHECK` in
[`ci/gates.py`](../ci/gates.py). Renaming a check is a coordinated change
across all three.

The *test selection* each gate runs is declared once, in `ci/gates.py`. The
workflow YAML and the dry-run harness both import that selection, so a CI
job and a local reproduction can never silently disagree.

## Enabling branch protection

GitHub branch protection itself is configured per-repository in the GitHub
UI or via the REST API — it is not part of this repo's source. To enable
the two checks as required on `main`:

### Via the GitHub UI

1. Open **Settings → Branches → Branch protection rules**.
2. Add (or edit) the rule for `main`.
3. Tick **Require status checks to pass before merging** and
   **Require branches to be up to date before merging**.
4. In the status-check search box, add **both** of these by name (the names
   must match the workflow `jobs.<id>` exactly):

   - `byte-identity-replay`
   - `baseline-adaptive-parity`

5. Save the rule.

GitHub only offers a status-check name in the search box once that check has
run at least once on the default branch. If you do not see the names, push
this branch once so the workflows execute and the names are registered, then
return to the settings page.

### Via the REST API

A one-shot equivalent using `gh` (requires a token with the `repo` scope):

```bash
gh api -X PUT \
  "repos/${OWNER}/${REPO}/branches/main/protection/required_status_checks" \
  --raw-field strict=true \
  --raw-field 'contexts[]=byte-identity-replay' \
  --raw-field 'contexts[]=baseline-adaptive-parity'
```

(or, equivalently, include both in the `required_status_checks.contexts`
array of the full branch-protection payload.) After applying, the API
response should list both checks under `contexts`.

## Verifying the gates can flip red (the dry run)

The acceptance bar requires that a deliberate determinism break flip both
gates red. The dry-run harness packaged with the gates does exactly that,
each break targeted at one gate, with strict `try/finally` restoration so
the working tree is left clean:

```bash
python -m ci.dry_run
```

The expected output is:

```
Dry-run: deliberate determinism breaks vs. CI gates
========================================================
[OK ] Break A: Drift the committed byte-identity golden fixture by one byte.
        target: game/fixtures/baseline_seed42.json
        expected-red gate exit:     1  (red)
        expected-green gate exit:   0  (green)
[OK ] Break B: Patch _Adaptive.order_choices to reverse choices after adaptation, …
        target: game/variants.py
        expected-red gate exit:     1  (red)
        expected-green gate exit:   0  (green)

Overall: PASS
```

Each break flips exactly the gate it targets (the other stays green —
evidence the gates are independently wired and not just both reading the
same shared signal). The harness exits non-zero if any break fails to flip
its targeted gate red or accidentally reds the other one; that is treated
as a **CI-system regression**, not a code regression, and means the gate
wiring has drifted and must be fixed.

`python -m ci.dry_run --break A` / `--break B` runs just one break, useful
when iterating on a specific gate.

## Where to edit

- **Which tests a gate runs:** [`ci/gates.py`](../ci/gates.py). Adding a new
  byte-identity invariant means adding a test under `game/tests/test_replay.py`
  (which the gate already selects in full), or extending the parity gate's
  `pytest_nodes` tuple if the new test lives elsewhere.
- **How a gate runs (steps, install, runner):**
  [`.github/workflows/byte-identity-replay.yml`](../.github/workflows/byte-identity-replay.yml) /
  [`.github/workflows/baseline-adaptive-parity.yml`](../.github/workflows/baseline-adaptive-parity.yml).
- **How a deliberate break is shaped and verified:**
  [`ci/dry_run.py`](../ci/dry_run.py).
