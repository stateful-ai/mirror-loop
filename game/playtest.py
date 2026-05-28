"""Blind A/B playtest — adaptive vs. baseline, scored against the locked metric.

This is the M2 experiment the prototype was built to run: play a population of
sessions through the **adaptive** arm (the real game) and a non-adaptive
**baseline** arm (the same engine with the adaptation seam set to the identity
transform), then judge the result against the *single* locked acceptance metric —
the Beats-Baseline Prediction Test (``acceptance.predictability``,
``docs/THESIS.md``).

It honours the company product principle that the adaptive thesis is validated by

    *a blind A/B with a decision rule (metric, n, effect threshold, kill-criteria)
    pre-registered before the playtest, not judged post-hoc.*

All four of those are fixed **here in code** (the single source of truth) and
mirrored in the pre-registered method doc ``docs/PLAYTEST_METHOD.md``:

* **metric** — the locked gate, applied per session and aggregated to the arm
  mean (:data:`acceptance.predictability.MIN_TOP1_ACCURACY` /
  :data:`~acceptance.predictability.MIN_MARGIN_OVER_BASELINE`). Not redefined
  here: imported, so it cannot drift from the thesis.
* **n** — :data:`N_PER_ARM` sessions per arm (the "≥N" the acceptance bar names).
* **effect threshold** — :data:`EFFECT_THRESHOLD`: the minimum separation in mean
  top-1 between arms before we will attribute predictability to the *adaptation*
  rather than to the shell. The A/B contrast is the primary endpoint — when the
  arms do not separate, the comparison is INCONCLUSIVE, whatever either arm's
  absolute score.
* **kill-criterion** — the adaptation *underperforming* the control by at least
  the effect threshold (adaptive worse than baseline) is a FAIL: the adaptation
  is actively counterproductive.

**Blinding.** The locked metric is applied *label-blind*: each session is scored
purely from its ``(predicted_actions, actual_action)`` log with no view of which
arm produced it (the data is self-labelling for analysis, the scorer is not). The
two arms run through the identical :func:`game.session.play_session` path with no
``if arm == ...`` branching anywhere on the player's path — parity is structural.

**Players, and why the arms coincide.** With no human and no LLM in the loop
(``docs/adr/0002-runtime-platform.md``), the population is a deterministic,
seeded set of :class:`SimulatedPlayer` policies that choose by *behavioural
disposition* — a stand-in for human playtesters, who are deferred to a later
milestone. Such a player's choice expresses a tendency and does **not** depend on
the order or framing the Mirror presents (the conservative null: the adaptation
is assumed to have no behavioural pull). Because the model's prediction is a
*render* that fires in every arm, and the player's choice is presentation-
independent, the two arms produce **byte-identical decision points** — exactly the
structural ``baseline ≡ adaptive`` parity the build gates on
(``docs/mirror_loop_m1_synthesis.md``). The honest consequence, reported plainly
by this harness, is that the locked *prediction* metric cannot, by construction,
separate the arms: the binding adaptive-vs-shell question is a *feel* question
that needs the subjective/human instrument the scope defers. This harness still
runs both arms, scores both, and states what the metric can and cannot conclude.

Everything is deterministic and replayable with no network and no model::

    python -m game.playtest                 # canonical run (n=30, seed=42)
    python -m game.playtest --n 50          # more sessions per arm
    python -m game.playtest --baseline random   # placebo control instead of fixed
    python -m game.playtest --json          # machine-readable result

Exit code: ``0`` PASS, ``1`` FAIL, ``3`` INCONCLUSIVE (``2`` is argparse usage).
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from typing import Sequence

from acceptance.predictability import (
    MIN_DECISION_POINTS,
    MIN_MARGIN_OVER_BASELINE,
    MIN_TOP1_ACCURACY,
    AcceptanceResult,
    evaluate,
)
from loop.core import PlayerState, Scene

from .session import Policy, Session, play_session
from .variants import build_variant
from .world import DEFAULT_WORLD, TENDENCY_PRIORITY, World

# --- The locked method (single source of truth; mirrored in docs/PLAYTEST_METHOD.md).
# The per-session gate thresholds are *imported* above from the locked metric, so
# only the A/B-specific knobs are defined here. Moving any of these is a method
# change and must be reflected in the method doc.

#: Minimum sessions per arm. One session is one player's full five-loop spine, so
#: this is the population size per arm — the "≥N" the acceptance bar requires.
N_PER_ARM = 30

#: The pre-registered effect size: the smallest separation in mean top-1 accuracy
#: between the arms that we will treat as the adaptation doing real work over the
#: shell. Below it (in absolute value) the arms are "not separated".
EFFECT_THRESHOLD = 0.05

#: Canonical seed for the reproducible run (matches the byte-identity gate's
#: "seed 42", ``game/replay.py``).
BASE_SEED = 42

#: The adaptive arm is always the real game; the baseline arm defaults to the
#: canonical ``fixed`` control (the identity seam). ``random`` (the player-
#: independent placebo, the blinding-grade control for *human* players) is
#: selectable via ``--baseline random``.
ADAPTIVE_VARIANT = "adaptive"
DEFAULT_BASELINE_VARIANT = "fixed"
BASELINE_VARIANT_CHOICES = ("fixed", "random")

#: The disposition sweep for the simulated population: from a weak lean (still the
#: norm — a player who leans somewhere most of the time) to a pure persona. The
#: floor sits above chance (~0.33 for three options) on purpose: the repo's own
#: archetype model treats the fully-erratic player as the *escape* exception
#: (``docs/game_design.md`` §12), not the typical playtester.
LEAN_MIN = 0.50
LEAN_MAX = 1.00

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"

#: Exit codes for the CLI (2 is reserved by argparse for usage errors).
_EXIT_CODE = {VERDICT_PASS: 0, VERDICT_FAIL: 1, VERDICT_INCONCLUSIVE: 3}


# --- The player population ----------------------------------------------------


@dataclass(frozen=True)
class SimulatedPlayer:
    """A deterministic, seeded stand-in for one human playtester.

    The player has a ``primary`` tendency they lean toward with probability
    ``lean`` each turn, otherwise choosing uniformly among the other tendencies.
    That choice is made by *tendency*, then resolved to whichever choice in the
    offered scene carries it — so by default it is independent of the order or
    framing the Mirror presents. That independence is the **conservative null**:
    it assumes the adaptation has no behavioural pull, which makes the two arms
    coincide on the locked metric (the only thing that differs between arms is
    presentation, which a null player ignores).

    ``suggestibility`` relaxes that null to model the game's own *predictive-
    nudging* thesis (``docs/game_design.md`` §4.6): on a turn where the player is
    not following their primary, with this probability they instead take whatever
    choice is **surfaced first**. In the adaptive arm the first-surfaced choice is
    the Mirror's prediction, so a suggestible player is nudged toward it and the
    adaptive arm pulls ahead of the (player-independent) baseline — an effect the
    A/B can then detect. It is ``0.0`` for the locked canonical population; values
    above zero are a *what-if* used to prove the harness is not blind to an effect.
    """

    player_id: str
    primary: str
    lean: float
    seed: int
    suggestibility: float = 0.0

    def policy(self) -> Policy:
        """A fresh :data:`~game.session.Policy` with its own seeded RNG.

        A *fresh* RNG per call lets the same player drive both arms from an
        identical draw sequence, so any divergence between arms is attributable to
        presentation alone. With ``suggestibility == 0`` the draws never read the
        scene, so the arms produce identical choices; with it positive the player
        sometimes takes the first-surfaced choice, which differs by arm.
        """
        rng = random.Random(f"{self.seed}:{self.player_id}")
        others = tuple(t for t in TENDENCY_PRIORITY if t != self.primary)

        def id_for(scene: Scene, tendency: str) -> str:
            for choice in scene.choices:
                if choice.tendency == tendency:
                    return choice.id
            # Every authored scene offers all three tendencies, so this is
            # unreachable in the shipped world; fall back deterministically rather
            # than raise, keeping the policy total for any future scene.
            return scene.choices[0].id

        def pick(scene: Scene, state: PlayerState, loop_index: int) -> str:
            if rng.random() < self.lean:
                return id_for(scene, self.primary)
            # Off-primary. A suggestible player is pulled to the first-surfaced
            # choice (the prediction, in the adaptive arm). The ``> 0`` guard
            # short-circuits the extra draw so the null stream is unperturbed.
            if self.suggestibility > 0.0 and rng.random() < self.suggestibility:
                return scene.choices[0].id
            return id_for(scene, rng.choice(others))

        return pick


def build_population(
    n: int = N_PER_ARM, *, base_seed: int = BASE_SEED, suggestibility: float = 0.0
) -> list[SimulatedPlayer]:
    """A deterministic population of ``n`` players spanning the disposition space.

    Players are balanced across the three primary tendencies and swept across
    :data:`LEAN_MIN`–:data:`LEAN_MAX`, so the population is a transparent mix from
    weakly-leaning (less predictable) to fully consistent (highly predictable)
    rather than hand-picked to land on a verdict. The same ``(base_seed, index)``
    always yields the same player.

    ``suggestibility`` is ``0.0`` for the locked canonical population (the
    conservative null); a positive value makes the whole population nudgeable, used
    to demonstrate the harness can detect an adaptation effect when one exists.
    """
    if n < 1:
        raise ValueError(f"population size must be >= 1, got {n}")
    players: list[SimulatedPlayer] = []
    for i in range(n):
        primary = TENDENCY_PRIORITY[i % len(TENDENCY_PRIORITY)]
        frac = i / (n - 1) if n > 1 else 1.0
        lean = LEAN_MIN + frac * (LEAN_MAX - LEAN_MIN)
        players.append(
            SimulatedPlayer(
                player_id=f"p{i:03d}",
                primary=primary,
                lean=lean,
                seed=base_seed,
                suggestibility=suggestibility,
            )
        )
    return players


# --- Running and scoring an arm -----------------------------------------------


def run_arm(
    variant_name: str,
    players: Sequence[SimulatedPlayer],
    *,
    world: World = DEFAULT_WORLD,
    seed: int = BASE_SEED,
) -> list[Session]:
    """Play every player through one arm and return the completed sessions.

    The arm is the single adaptation toggle (``game.variants``); the population is
    played through the ordinary :func:`game.session.play_session` with no special
    casing, so the arms differ only in the seam.
    """
    variant = build_variant(variant_name, seed=seed)
    return [
        play_session(player.policy(), world=world, variant=variant)
        for player in players
    ]


@dataclass(frozen=True)
class ArmResult:
    """One arm's outcome under the locked metric, aggregated over the population."""

    arm: str  # "adaptive" / "baseline"
    variant_name: str  # "adaptive" / "fixed" / "random"
    n_sessions: int
    mean_top1: float
    mean_margin: float
    mean_baseline: float
    pass_rate: float  # fraction of sessions that individually pass the locked gate
    total_decision_points: int
    per_session: tuple[AcceptanceResult, ...]

    @property
    def gate_pass(self) -> bool:
        """Does the arm clear the *locked* gate on its population means?

        Reuses the locked thresholds verbatim — the same floor the thesis fixes,
        applied to the average player rather than a single session.
        """
        return (
            self.mean_top1 >= MIN_TOP1_ACCURACY
            and self.mean_margin >= MIN_MARGIN_OVER_BASELINE
        )

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "variant": self.variant_name,
            "n_sessions": self.n_sessions,
            "mean_top1": self.mean_top1,
            "mean_margin": self.mean_margin,
            "mean_baseline": self.mean_baseline,
            "pass_rate": self.pass_rate,
            "total_decision_points": self.total_decision_points,
            "gate_pass": self.gate_pass,
        }


def score_arm(arm: str, variant_name: str, sessions: Sequence[Session]) -> ArmResult:
    """Score an arm's sessions against the locked metric, one session at a time.

    The unit of analysis is the session, exactly as ``docs/THESIS.md`` defines the
    metric ("run against one complete playtested session"). The per-session
    results are then averaged — the per-player baseline stays per-player, so the
    margin keeps its honest meaning rather than being diluted by pooling players.
    """
    results = tuple(evaluate(s.decision_points()) for s in sessions)
    n = len(results)
    if n == 0:
        return ArmResult(arm, variant_name, 0, 0.0, 0.0, 0.0, 0.0, 0, ())
    mean_top1 = sum(r.top1_accuracy for r in results) / n
    mean_margin = sum(r.margin for r in results) / n
    mean_baseline = sum(r.baseline_accuracy for r in results) / n
    pass_rate = sum(r.passed for r in results) / n
    total_points = sum(r.n for r in results)
    return ArmResult(
        arm=arm,
        variant_name=variant_name,
        n_sessions=n,
        mean_top1=mean_top1,
        mean_margin=mean_margin,
        mean_baseline=mean_baseline,
        pass_rate=pass_rate,
        total_decision_points=total_points,
        per_session=results,
    )


# --- The pre-registered decision rule -----------------------------------------


def decide(
    adaptive: ArmResult, baseline: ArmResult, *, required_min: int = N_PER_ARM
) -> tuple[str, str]:
    """Apply the locked decision rule. Returns ``(verdict, reason)``.

    ``required_min`` is the locked floor on sessions per arm (the "≥N" of the
    acceptance bar, :data:`N_PER_ARM`); running fewer is INCONCLUSIVE by rule,
    regardless of how many were actually collected.

    The **A/B contrast is the primary endpoint** — this is a comparison of two
    arms, so the verdict is about whether they differ, with the absolute locked
    gate used as the bar the *winning* arm must still clear. Order is fixed in
    advance:

    1. **INCONCLUSIVE** — not enough data to judge (either arm under
       :data:`N_PER_ARM` sessions, or under :data:`MIN_DECISION_POINTS` scored
       points).
    2. **FAIL (kill-criterion)** — the adaptation *underperforms* the control by
       at least the effect threshold (adaptive worse than baseline): the
       adaptation is actively counterproductive and the thesis is killed.
    3. The arms **separate** in the adaptation's favour (Δ top-1 ≥ effect
       threshold):
       * **PASS** if the adaptive arm also clears the locked gate — the adaptation
         adds real, attributable predictive signal *and* meets the thesis bar.
       * **INCONCLUSIVE** otherwise — the effect is there but the adaptive arm is
         still below the locked floor; the bar is not yet met.
    4. The arms **do not separate** (|Δ top-1| < effect threshold) →
       **INCONCLUSIVE**: on the locked prediction metric the adaptation is
       indistinguishable from the baseline shell, so the comparison cannot
       attribute the experience to the adaptation — whatever the (shared) absolute
       score. (Note: prediction is a *render* present in both arms, so for
       presentation-independent players the arms coincide by construction; the
       adaptive-vs-shell 'feel' question then needs the deferred human instrument.)
    """
    if adaptive.n_sessions < required_min or baseline.n_sessions < required_min:
        return (
            VERDICT_INCONCLUSIVE,
            f"insufficient sessions per arm: adaptive={adaptive.n_sessions}, "
            f"baseline={baseline.n_sessions} (need >= {required_min} each)",
        )
    if (
        adaptive.total_decision_points < MIN_DECISION_POINTS
        or baseline.total_decision_points < MIN_DECISION_POINTS
    ):
        return (
            VERDICT_INCONCLUSIVE,
            "too few scored decision points to apply the locked gate",
        )

    delta = adaptive.mean_top1 - baseline.mean_top1
    if delta <= -EFFECT_THRESHOLD:
        return (
            VERDICT_FAIL,
            f"adaptive underperforms baseline by {delta:+.3f} mean top-1 "
            f"(>= {EFFECT_THRESHOLD} worse): the adaptation is counterproductive",
        )
    if delta >= EFFECT_THRESHOLD:
        if adaptive.gate_pass:
            return (
                VERDICT_PASS,
                f"adaptive beats baseline by {delta:+.3f} mean top-1 "
                f"(>= {EFFECT_THRESHOLD}) and clears the locked gate: the "
                f"adaptation adds real, attributable predictive signal",
            )
        return (
            VERDICT_INCONCLUSIVE,
            f"adaptive separates from baseline by {delta:+.3f} mean top-1 but is "
            f"below the locked floor (mean top-1 {adaptive.mean_top1:.3f} < "
            f"{MIN_TOP1_ACCURACY:.2f}); the effect is real but the thesis bar is "
            f"not yet met",
        )
    gate = "PASS" if adaptive.gate_pass else "FAIL"
    return (
        VERDICT_INCONCLUSIVE,
        f"arms do not separate (Δ top-1 {delta:+.3f}, |Δ| < {EFFECT_THRESHOLD}): "
        f"on the locked prediction metric the adaptation is indistinguishable from "
        f"the baseline shell (adaptive-arm gate {gate}, mean top-1 "
        f"{adaptive.mean_top1:.3f} vs floor {MIN_TOP1_ACCURACY:.2f}). The "
        f"prediction is a render present in both arms, so this metric cannot "
        f"attribute the experience to the adaptation; the adaptive-vs-shell "
        f"question needs the deferred human/subjective instrument",
    )


@dataclass(frozen=True)
class ABResult:
    """The full playtest outcome: both arms, the contrast, and the verdict."""

    adaptive: ArmResult
    baseline: ArmResult
    verdict: str
    reason: str
    n_per_arm: int
    base_seed: int
    effect_threshold: float

    @property
    def delta_top1(self) -> float:
        return self.adaptive.mean_top1 - self.baseline.mean_top1

    @property
    def delta_margin(self) -> float:
        return self.adaptive.mean_margin - self.baseline.mean_margin

    @property
    def arms_separated(self) -> bool:
        return abs(self.delta_top1) >= self.effect_threshold

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "method": {
                "metric": "Beats-Baseline Prediction Test (docs/THESIS.md)",
                "n_per_arm": self.n_per_arm,
                "base_seed": self.base_seed,
                "effect_threshold": self.effect_threshold,
                "min_top1_accuracy": MIN_TOP1_ACCURACY,
                "min_margin_over_baseline": MIN_MARGIN_OVER_BASELINE,
            },
            "adaptive": self.adaptive.to_dict(),
            "baseline": self.baseline.to_dict(),
            "contrast": {
                "delta_top1": self.delta_top1,
                "delta_margin": self.delta_margin,
                "arms_separated": self.arms_separated,
            },
        }

    def render(self) -> str:
        """The written verdict with evidence — the acceptance deliverable."""
        header = (
            f"  {'arm':<22}{'n':>3}  {'top-1':>7}  {'margin':>8}  "
            f"{'baseline':>9}  {'pass-rate':>10}  gate"
        )
        lines = [
            f"[{self.verdict}] Blind A/B Playtest — adaptive vs. baseline",
            "  method     : Beats-Baseline Prediction Test (docs/THESIS.md), "
            "pre-registered in docs/PLAYTEST_METHOD.md",
            f"  n per arm  : {self.n_per_arm} sessions   seed: {self.base_seed}   "
            f"effect threshold (Δ top-1): {self.effect_threshold:.2f}",
            f"  gate (locked): mean top-1 >= {MIN_TOP1_ACCURACY:.2f} AND "
            f"mean margin >= {MIN_MARGIN_OVER_BASELINE:.2f}   "
            f"(pass-rate = fraction of sessions individually passing the gate)",
            "",
            header,
            "  " + "-" * (len(header) - 2),
            self._arm_row(self.adaptive),
            self._arm_row(self.baseline),
            "",
            f"  A/B contrast : Δ mean top-1 = {self.delta_top1:+.3f}   "
            f"Δ mean margin = {self.delta_margin:+.3f}   "
            f"arms separated: {'yes' if self.arms_separated else 'no'}",
            f"  reason       : {self.reason}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _arm_row(a: ArmResult) -> str:
        label = f"{a.arm} ({a.variant_name})"
        return (
            f"  {label:<22}{a.n_sessions:>3}  {a.mean_top1:>7.3f}  "
            f"{a.mean_margin:>+8.3f}  {a.mean_baseline:>9.3f}  "
            f"{a.pass_rate:>10.3f}  {'PASS' if a.gate_pass else 'FAIL'}"
        )


def run_playtest(
    *,
    n_per_arm: int = N_PER_ARM,
    base_seed: int = BASE_SEED,
    baseline_variant: str = DEFAULT_BASELINE_VARIANT,
    world: World = DEFAULT_WORLD,
) -> ABResult:
    """Run the whole blind A/B: build the population, play both arms, decide.

    The same population (same players, same seeds) drives both arms — a paired
    design — so any difference is the adaptation, not the sample.
    """
    if baseline_variant not in BASELINE_VARIANT_CHOICES:
        raise ValueError(
            f"baseline must be one of {BASELINE_VARIANT_CHOICES}, got "
            f"{baseline_variant!r}"
        )
    players = build_population(n_per_arm, base_seed=base_seed)

    adaptive_sessions = run_arm(ADAPTIVE_VARIANT, players, world=world, seed=base_seed)
    baseline_sessions = run_arm(baseline_variant, players, world=world, seed=base_seed)

    adaptive = score_arm("adaptive", ADAPTIVE_VARIANT, adaptive_sessions)
    baseline = score_arm("baseline", baseline_variant, baseline_sessions)

    # The decision rule always enforces the *locked* minimum (N_PER_ARM), so a
    # run with fewer sessions than the floor is INCONCLUSIVE by rule even though
    # ``n_per_arm`` sessions were collected.
    verdict, reason = decide(adaptive, baseline, required_min=N_PER_ARM)
    return ABResult(
        adaptive=adaptive,
        baseline=baseline,
        verdict=verdict,
        reason=reason,
        n_per_arm=n_per_arm,
        base_seed=base_seed,
        effect_threshold=EFFECT_THRESHOLD,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m game.playtest", description=__doc__)
    parser.add_argument(
        "--n", type=int, default=N_PER_ARM, help=f"sessions per arm (default {N_PER_ARM})"
    )
    parser.add_argument(
        "--seed", type=int, default=BASE_SEED, help=f"population seed (default {BASE_SEED})"
    )
    parser.add_argument(
        "--baseline",
        choices=BASELINE_VARIANT_CHOICES,
        default=DEFAULT_BASELINE_VARIANT,
        help="the baseline arm: 'fixed' (canonical identity control) or 'random' "
        "(player-independent placebo). Default: fixed.",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the result as JSON instead of a report"
    )
    args = parser.parse_args(argv)

    result = run_playtest(
        n_per_arm=args.n, base_seed=args.seed, baseline_variant=args.baseline
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.render())
    return _EXIT_CODE[result.verdict]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
