"""Experience-change observables — operationalizing "the adaptation changed the
player's experience" as concrete replay-log values.

The locked Beats-Baseline Prediction Test (``acceptance/predictability.py``,
``docs/THESIS.md``) scores how well the Mirror's forecast matches the player's
choice. By construction it is a *render* present in both arms — the canonical
A/B confirmed it cannot, on its own, separate the adaptive arm from the
baseline (``docs/PLAYTEST_RESULTS.md``). So a falsifiable answer to *"did the
adaptation change the player's experience?"* needs different observables — ones
that are sensitive to what the seam actually does (``docs/ADAPTATION.md``):
*select* a framing per slot and *re-order* a scene's choices.

This module is the written, executable definition: which existing replay-log
fields constitute "the adaptation changed the player's experience," and the
pre-registerable A/B rule that judges that question from them. Nothing here
introduces a new event type or asks the engine to log a new value; every
observable below is read straight from data the in-memory replay log
(:class:`game.session.Session`, :class:`game.session.LoopRecord`) and its
serialized form (:meth:`game.session.Session.session_log`) already carry. That
is the no-later-re-instrumentation contract.

Two tiers of observable, both required:

* **Presentation divergence** (per paired loop) — the seam *did the thing*: the
  adaptive arm showed the player a different framing (``branch_key``) and/or a
  different choice order (``offered_order``) than the baseline arm did, for the
  same player and the same loop slot. Without this, the adaptation made no
  visible difference and the question is moot.
* **Behavioral divergence** (per paired loop) — the player *responded* to the
  different presentation: ``actual_action`` differs between arms at the same
  loop slot. Without this, the adaptation changed the room but not what the
  player did — i.e. it changed presentation but not the experience.

A paired A/B is the unit of measurement: the **same** simulated (or human)
player is run through both arms (``game.playtest.run_playtest`` already does
this — pairing is the whole point of seeding one population through both
seams). Pair-level rates are then averaged across the population to a single
pair of population means, and the pre-registered rule decides.

This module is a definition + a computer — it does not change the existing
locked A/B method, which keeps the founder-locked prediction gate as the
*absolute* bar. The experience-change rule sits alongside it as the answer to a
different (and previously out-of-reach) question, expressed in observables that
the existing replay log already produces.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from game.session import LoopRecord, Session

# --- Pre-registered floors (the single source of truth for the rule) ---------
#
# These are the falsifiable thresholds the experience-change A/B rule judges
# against. They are written here in code, mirrored in
# ``docs/ACCEPTANCE_OBSERVABLES.md``, and are fixed *before* any run that uses
# them so the rule cannot be edited to fit the outcome. The same pre-registration
# discipline the locked A/B method already obeys
# (``docs/PLAYTEST_METHOD.md``) extends to this rule.

#: Minimum mean per-pair fraction of loops on which the adaptation must visibly
#: differ from the baseline (different framing and/or different choice order).
#: Below it the seam is not doing the thing the type promises
#: (``docs/ADAPTATION.md`` §1) — there is no experience to compare.
#:
#: Derivation. The canonical world has a five-loop spine: intake (always neutral
#: in both arms) plus four branch-or-reorder slots. Under the conservative-null
#: population (``game.playtest.build_population`` with the locked lean sweep) the
#: adaptive arm differs from the fixed arm whenever either (a) the Mirror's
#: notice threshold has fired so ``branch_key`` flips off ``"default"``, or
#: (b) the player has any predicted action so ``offered.choices`` is reordered
#: predicted-first. Either firing on even one of the four nudgeable slots gives
#: a per-pair rate of 1/5 = 0.20. The observed null on the canonical population
#: lands at ≈0.71 mean presentation divergence (≈0.49 framing, ≈0.59 order), so
#: 0.20 is the conservative *minimum* the seam must clear to be doing anything
#: at all — set well below the observed distribution, not at it, so the rule
#: fails on a structurally-broken seam rather than on noise.
#:
#: This is the floor the authors are willing to be falsified by: a future
#: change that drives mean presentation divergence below 0.20 falsifies the
#: claim that the adaptation seam is producing a visibly different presentation
#: at all, and the experience-change question becomes unanswerable on that run.
PRESENTATION_DIVERGENCE_FLOOR = 0.20

#: Minimum mean per-pair fraction of loops on which the player's actual choice
#: differed between arms. The conservative-null population pins this at zero by
#: construction (presentation-independent players choose the same in both
#: arms); a nudgeable population pushes it above zero. So this threshold is
#: precisely what separates "the adaptation altered presentation" from "the
#: adaptation altered the player's experience," which is the falsifiable claim.
#: 0.05 = at least one of every twenty paired loops shifts choice; below that
#: the effect is indistinguishable from the conservative-null pin at zero and
#: this rule reports FAIL rather than claim an experience change.
BEHAVIORAL_DIVERGENCE_FLOOR = 0.05

#: Minimum paired observations per player. A pair with fewer paired loops than
#: this is not scorable for this rule; the canonical world produces five paired
#: loops per player, so this matches the locked
#: :data:`acceptance.predictability.MIN_DECISION_POINTS`.
MIN_PAIRED_LOOPS = 5

#: Minimum players (paired sessions) the rule needs to decide. Mirrors the
#: locked A/B method (:data:`game.playtest.N_PER_ARM`); kept here as a separate
#: constant so this rule is judged on its own minimum even if the locked method
#: is amended.
MIN_PAIRED_SESSIONS = 30

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"


# --- Per-loop observable ------------------------------------------------------


@dataclass(frozen=True)
class LoopPresentation:
    """One replay-log loop reduced to the five values this rule reads.

    Every field is a direct read of a value the existing replay log already
    carries — :class:`~game.session.LoopRecord` in memory and
    :meth:`game.session.Session.session_log` on disk — so no new instrumentation
    is required to produce one of these. The list is the *operationalization*:
    these are the bytes that constitute the experience the adaptation either
    did or did not change.

    The five field reads below are pinned by
    :func:`acceptance.tests.test_experience_change.test_loop_presentation_reads_record_fields_directly`,
    which drives a real session through the engine and asserts each
    :class:`LoopPresentation` attribute equals the corresponding live
    :class:`~game.session.LoopRecord` attribute — so if any field is ever
    renamed, removed, or restructured, that test fails first and the
    no-later-re-instrumentation claim is enforced rather than assumed.

    Fields:

    * ``loop_index`` — which slot of the world spine this loop is. Pairs across
      arms by loop_index, not by wall-clock.
    * ``scene_id`` — the id of the framing actually presented this loop
      (``LoopRecord.offered.id``). Different framings ⇒ different rooms read.
    * ``branch_key`` — which authored framing the seam revealed
      (``LoopRecord.branch_key``); ``"fixed"`` / ``"default"`` are the neutral
      cases, a tendency name is a tailored framing.
    * ``offered_order`` — the choice ids in the order the player saw them
      (``LoopRecord.offered.choices``). Different order ⇒ different "which door
      leads."
    * ``actual_action`` — the choice the player took
      (``LoopRecord.result.actual_action``). The behavioural response.
    """

    loop_index: int
    scene_id: str
    branch_key: str
    offered_order: tuple[str, ...]
    actual_action: str

    @classmethod
    def from_record(cls, record: LoopRecord) -> "LoopPresentation":
        return cls(
            loop_index=record.loop_index,
            scene_id=record.offered.id,
            branch_key=record.branch_key,
            offered_order=tuple(c.id for c in record.offered.choices),
            actual_action=record.result.actual_action,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "LoopPresentation":
        """Read one presentation from the serialized log shape this module emits.

        Symmetric with :meth:`to_dict`; lets a JSON-only consumer compute the
        rule without ever reconstructing a live :class:`Session`.
        """
        return cls(
            loop_index=data["loop_index"],
            scene_id=data["scene_id"],
            branch_key=data["branch_key"],
            offered_order=tuple(data["offered_order"]),
            actual_action=data["actual_action"],
        )

    def to_dict(self) -> dict:
        return {
            "loop_index": self.loop_index,
            "scene_id": self.scene_id,
            "branch_key": self.branch_key,
            "offered_order": list(self.offered_order),
            "actual_action": self.actual_action,
        }


def session_presentations(session: Session) -> tuple[LoopPresentation, ...]:
    """Read the per-loop presentation observables out of an in-memory session.

    The whole reduction is one ``from_record`` per :class:`LoopRecord`. There is
    no fan-out and no engine replay: the observables are exactly the fields the
    record already exposes.
    """
    return tuple(LoopPresentation.from_record(r) for r in session.records)


# --- Per-loop divergence predicates -------------------------------------------
#
# Each predicate is one boolean a future analyst would ask of a paired loop.
# They are pure: a paired (adaptive, baseline) :class:`LoopPresentation` in,
# bool out, no side effects, no log access.


def framing_diverged(adaptive: LoopPresentation, baseline: LoopPresentation) -> bool:
    """Did the seam reveal a different framing than the baseline at this loop?

    The branch key is the framing label (``"default"`` / ``"fixed"`` / a
    tendency). Different keys ⇒ the player literally read different prose.
    """
    _assert_paired(adaptive, baseline)
    return adaptive.branch_key != baseline.branch_key


def order_diverged(adaptive: LoopPresentation, baseline: LoopPresentation) -> bool:
    """Did the seam present the choices in a different order than the baseline?

    The same choice set with a different order is the in-scene re-ordering
    surface (``docs/ADAPTATION.md`` §1). Different order ⇒ a different option
    leads, which is what predictive nudging acts through.
    """
    _assert_paired(adaptive, baseline)
    return adaptive.offered_order != baseline.offered_order


def presentation_diverged(
    adaptive: LoopPresentation, baseline: LoopPresentation
) -> bool:
    """Did the adaptation present *anything* differently — framing or order?"""
    return framing_diverged(adaptive, baseline) or order_diverged(adaptive, baseline)


def behavior_diverged(
    adaptive: LoopPresentation, baseline: LoopPresentation
) -> bool:
    """Did the player make a different choice between arms at this loop?

    This is the falsifiable observable for "the adaptation changed the
    *experience*": a presentation-independent player chooses the same in both
    arms by construction, so a paired difference attributable to the seam is
    real evidence that what was presented changed what was done.
    """
    _assert_paired(adaptive, baseline)
    return adaptive.actual_action != baseline.actual_action


def _assert_paired(a: LoopPresentation, b: LoopPresentation) -> None:
    """Pairs are only meaningful at the same loop_index — fail loudly otherwise."""
    if a.loop_index != b.loop_index:
        raise ValueError(
            f"paired loops must share loop_index; got {a.loop_index} vs {b.loop_index}"
        )


# --- Pair-level aggregate -----------------------------------------------------


@dataclass(frozen=True)
class PairObservables:
    """One player's paired (adaptive, baseline) session reduced to the rule's inputs."""

    player_id: str
    n_paired_loops: int
    framing_divergence_rate: float
    order_divergence_rate: float
    presentation_divergence_rate: float
    behavior_divergence_rate: float

    @property
    def scorable(self) -> bool:
        """True if this pair has enough paired loops to score the rule."""
        return self.n_paired_loops >= MIN_PAIRED_LOOPS

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "n_paired_loops": self.n_paired_loops,
            "framing_divergence_rate": self.framing_divergence_rate,
            "order_divergence_rate": self.order_divergence_rate,
            "presentation_divergence_rate": self.presentation_divergence_rate,
            "behavior_divergence_rate": self.behavior_divergence_rate,
        }


def pair_observables(
    adaptive: Sequence[LoopPresentation],
    baseline: Sequence[LoopPresentation],
    *,
    player_id: str,
) -> PairObservables:
    """Aggregate one player's paired loops to the four rates the rule reads.

    The two sequences must have the same length and the same loop indices (the
    paired contract — same player, same world, same input log driving both
    arms); otherwise the inputs are not a paired A/B sample and the function
    refuses to invent an alignment. Empty pairs are returned with zero rates so
    the population aggregate can simply skip them via :attr:`scorable`.
    """
    if len(adaptive) != len(baseline):
        raise ValueError(
            f"paired sessions must have the same number of loops; got "
            f"{len(adaptive)} adaptive vs {len(baseline)} baseline for "
            f"player {player_id!r}"
        )
    n = len(adaptive)
    if n == 0:
        return PairObservables(player_id, 0, 0.0, 0.0, 0.0, 0.0)

    framing = sum(framing_diverged(a, b) for a, b in zip(adaptive, baseline))
    order = sum(order_diverged(a, b) for a, b in zip(adaptive, baseline))
    presentation = sum(
        presentation_diverged(a, b) for a, b in zip(adaptive, baseline)
    )
    behavior = sum(behavior_diverged(a, b) for a, b in zip(adaptive, baseline))
    return PairObservables(
        player_id=player_id,
        n_paired_loops=n,
        framing_divergence_rate=framing / n,
        order_divergence_rate=order / n,
        presentation_divergence_rate=presentation / n,
        behavior_divergence_rate=behavior / n,
    )


# --- Population aggregate + the pre-registered decision rule ------------------


@dataclass(frozen=True)
class ExperienceChangeResult:
    """The population-level outcome under the experience-change rule."""

    verdict: str
    reason: str
    n_pairs: int
    mean_presentation_divergence: float
    mean_behavior_divergence: float
    mean_framing_divergence: float
    mean_order_divergence: float
    presentation_floor: float
    behavior_floor: float
    required_min_pairs: int

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "n_pairs": self.n_pairs,
            "means": {
                "presentation_divergence": self.mean_presentation_divergence,
                "behavior_divergence": self.mean_behavior_divergence,
                "framing_divergence": self.mean_framing_divergence,
                "order_divergence": self.mean_order_divergence,
            },
            "floors": {
                "presentation_divergence": self.presentation_floor,
                "behavior_divergence": self.behavior_floor,
            },
            "required_min_pairs": self.required_min_pairs,
        }

    def render(self) -> str:
        return (
            f"[{self.verdict}] Experience-Change A/B — adaptive vs. baseline\n"
            f"  pairs scored             : {self.n_pairs} "
            f"(need >= {self.required_min_pairs})\n"
            f"  mean presentation diverg.: {self.mean_presentation_divergence:.3f} "
            f"(floor >= {self.presentation_floor:.2f})\n"
            f"  mean behavior divergence : {self.mean_behavior_divergence:.3f} "
            f"(floor >= {self.behavior_floor:.2f})\n"
            f"    (framing {self.mean_framing_divergence:.3f}, "
            f"order {self.mean_order_divergence:.3f})\n"
            f"  reason                   : {self.reason}"
        )


def decide(
    pairs: Sequence[PairObservables],
    *,
    presentation_floor: float = PRESENTATION_DIVERGENCE_FLOOR,
    behavior_floor: float = BEHAVIORAL_DIVERGENCE_FLOOR,
    required_min: int = MIN_PAIRED_SESSIONS,
) -> ExperienceChangeResult:
    """Apply the pre-registered experience-change rule to a paired population.

    Order is fixed in advance:

    1. **INCONCLUSIVE** — fewer than :data:`MIN_PAIRED_SESSIONS` scorable pairs;
       not enough paired observations to judge.
    2. **FAIL — presentation floor** — the seam did not visibly differ from the
       baseline in enough loops (mean presentation-divergence below
       :data:`PRESENTATION_DIVERGENCE_FLOOR`). The adaptation made no visible
       difference, so the experience question is unanswerable on this run.
    3. **FAIL — behavior floor** — the seam did visibly differ, but the
       player's choices did not shift between arms (mean behavior-divergence
       below :data:`BEHAVIORAL_DIVERGENCE_FLOOR`). The adaptation changed the
       presentation but not the experience — exactly the conservative-null
       reading the canonical playtest produced.
    4. **PASS** — both floors are cleared. The seam visibly did the thing and
       the player's actual choices responded to it.
    """
    scorable = [p for p in pairs if p.scorable]
    n = len(scorable)
    means = _means(scorable)

    if n < required_min:
        return ExperienceChangeResult(
            verdict=VERDICT_INCONCLUSIVE,
            reason=(
                f"insufficient paired sessions: {n} scorable "
                f"(need >= {required_min}; a pair is scorable iff it has "
                f">= {MIN_PAIRED_LOOPS} paired loops)"
            ),
            n_pairs=n,
            mean_presentation_divergence=means["presentation"],
            mean_behavior_divergence=means["behavior"],
            mean_framing_divergence=means["framing"],
            mean_order_divergence=means["order"],
            presentation_floor=presentation_floor,
            behavior_floor=behavior_floor,
            required_min_pairs=required_min,
        )

    if means["presentation"] < presentation_floor:
        reason = (
            f"presentation divergence {means['presentation']:.3f} below floor "
            f"{presentation_floor:.2f}: the adaptation made no visible difference "
            f"from the baseline, so the experience question is unanswerable"
        )
        return _result(
            VERDICT_FAIL, reason, n, means, presentation_floor, behavior_floor, required_min
        )

    if means["behavior"] < behavior_floor:
        reason = (
            f"presentation divergence {means['presentation']:.3f} clears floor "
            f"{presentation_floor:.2f} but behavior divergence "
            f"{means['behavior']:.3f} is below floor {behavior_floor:.2f}: the "
            f"adaptation changed the presentation but not the player's choices "
            f"(the conservative-null reading)"
        )
        return _result(
            VERDICT_FAIL, reason, n, means, presentation_floor, behavior_floor, required_min
        )

    reason = (
        f"presentation divergence {means['presentation']:.3f} >= "
        f"{presentation_floor:.2f} and behavior divergence "
        f"{means['behavior']:.3f} >= {behavior_floor:.2f}: the adaptation "
        f"visibly changed content and the player's choices responded"
    )
    return _result(
        VERDICT_PASS, reason, n, means, presentation_floor, behavior_floor, required_min
    )


def _means(pairs: Sequence[PairObservables]) -> dict[str, float]:
    if not pairs:
        return {"presentation": 0.0, "behavior": 0.0, "framing": 0.0, "order": 0.0}
    n = len(pairs)
    return {
        "presentation": sum(p.presentation_divergence_rate for p in pairs) / n,
        "behavior": sum(p.behavior_divergence_rate for p in pairs) / n,
        "framing": sum(p.framing_divergence_rate for p in pairs) / n,
        "order": sum(p.order_divergence_rate for p in pairs) / n,
    }


def _result(
    verdict: str,
    reason: str,
    n: int,
    means: dict[str, float],
    presentation_floor: float,
    behavior_floor: float,
    required_min: int,
) -> ExperienceChangeResult:
    return ExperienceChangeResult(
        verdict=verdict,
        reason=reason,
        n_pairs=n,
        mean_presentation_divergence=means["presentation"],
        mean_behavior_divergence=means["behavior"],
        mean_framing_divergence=means["framing"],
        mean_order_divergence=means["order"],
        presentation_floor=presentation_floor,
        behavior_floor=behavior_floor,
        required_min_pairs=required_min,
    )


# --- End-to-end driver: paired sessions -> verdict ----------------------------


def evaluate_paired_sessions(
    pairs: Sequence[tuple[str, Session, Session]],
) -> ExperienceChangeResult:
    """Run the rule over an iterable of ``(player_id, adaptive, baseline)`` triples.

    Each triple is one player's paired A/B run (same player driving both arms,
    as :func:`game.playtest.run_playtest` already produces). The function
    reduces every triple to a :class:`PairObservables` and applies
    :func:`decide`. Nothing else is read — confirming sufficiency.
    """
    observables = [
        pair_observables(
            session_presentations(adaptive),
            session_presentations(baseline),
            player_id=player_id,
        )
        for player_id, adaptive, baseline in pairs
    ]
    return decide(observables)


# --- JSON I/O: the no-re-instrumentation contract from disk -------------------
#
# The in-memory :class:`Session` already carries every observable above. For the
# serialized log path (the long-term audit artifact), this module emits a
# minimal, additive shape that is a direct projection of the existing log — no
# new event types, no engine replay, just the same five values per loop pulled
# out for analysis.


def session_observables_log(session: Session, *, player_id: str, arm: str) -> dict:
    """Project one session into the experience-change shape, no new events.

    The result is structurally a subset of what the existing
    :meth:`game.session.Session.session_log` and
    :mod:`game.instrumentation` traces already produce — every field is a
    direct read of an attribute the in-memory :class:`LoopRecord` already
    carries. Persisting this is a *projection*, not new instrumentation.
    """
    return {
        "player_id": player_id,
        "arm": arm,
        "variant": session.variant_name,
        "world": session.world_name,
        "loops": [p.to_dict() for p in session_presentations(session)],
    }


def load_pair_log(path: str | Path) -> tuple[str, list[LoopPresentation], list[LoopPresentation]]:
    """Load a paired-sessions log written by :func:`write_pair_log`.

    Returns ``(player_id, adaptive_loops, baseline_loops)`` so a JSON-only
    consumer can apply :func:`pair_observables` without touching the engine.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return (
        data["player_id"],
        [LoopPresentation.from_dict(d) for d in data["adaptive"]["loops"]],
        [LoopPresentation.from_dict(d) for d in data["baseline"]["loops"]],
    )


def write_pair_log(
    path: str | Path,
    *,
    player_id: str,
    adaptive: Session,
    baseline: Session,
) -> None:
    """Serialize one paired A/B session to a JSON log, in the projection shape."""
    payload = {
        "player_id": player_id,
        "adaptive": session_observables_log(adaptive, player_id=player_id, arm="adaptive"),
        "baseline": session_observables_log(baseline, player_id=player_id, arm="baseline"),
    }
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# --- CLI: run the rule end-to-end against the canonical paired population ----
#
# The rule is computable from the engine's existing logs. This entry point
# proves it: one command runs the canonical paired population through both arms
# of :mod:`game.playtest`, reduces every paired session through
# :func:`session_presentations` (no new instrumentation), and prints the
# pre-registered verdict. It also accepts paired logs written by
# :func:`write_pair_log`, so a JSON-only consumer can score without re-running
# the engine. Exit codes mirror :mod:`game.playtest`: ``0`` PASS, ``1`` FAIL,
# ``3`` INCONCLUSIVE (``2`` is argparse usage).


def _run_canonical(n: int, suggestibility: float) -> ExperienceChangeResult:
    # Imported locally so the module's core (definition + pure rule) does not
    # require the playtest harness — JSON-only consumers can skip it entirely.
    from game.playtest import BASE_SEED, build_population, run_arm

    pop = build_population(n, base_seed=BASE_SEED, suggestibility=suggestibility)
    adaptive = run_arm("adaptive", pop, seed=BASE_SEED)
    baseline = run_arm("fixed", pop, seed=BASE_SEED)
    triples = list(zip([p.player_id for p in pop], adaptive, baseline))
    return evaluate_paired_sessions(triples)


def _run_from_logs(paths: Sequence[str]) -> ExperienceChangeResult:
    observables = []
    for path in paths:
        player_id, adaptive, baseline = load_pair_log(path)
        observables.append(
            pair_observables(adaptive, baseline, player_id=player_id)
        )
    return decide(observables)


_EXIT_CODE = {
    VERDICT_PASS: 0,
    VERDICT_FAIL: 1,
    VERDICT_INCONCLUSIVE: 3,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m acceptance.experience_change",
        description=(
            "Apply the pre-registered Experience-Change A/B rule "
            "(docs/ACCEPTANCE_OBSERVABLES.md) to a paired population, "
            "from the engine's existing replay log."
        ),
    )
    parser.add_argument(
        "--n",
        type=int,
        default=MIN_PAIRED_SESSIONS,
        help=f"sessions per arm (default: {MIN_PAIRED_SESSIONS})",
    )
    parser.add_argument(
        "--suggestibility",
        type=float,
        default=0.0,
        help=(
            "population suggestibility (0.0 = conservative null; positive = "
            "nudgeable). Default 0.0."
        ),
    )
    parser.add_argument(
        "--from-logs",
        nargs="+",
        metavar="PATH",
        help=(
            "score from pre-saved paired logs (write_pair_log JSON) instead "
            "of re-running the engine"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the result as JSON instead of the rendered text",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.from_logs:
        result = _run_from_logs(args.from_logs)
    else:
        result = _run_canonical(args.n, args.suggestibility)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(result.render())
    return _EXIT_CODE[result.verdict]


__all__ = [
    "BEHAVIORAL_DIVERGENCE_FLOOR",
    "ExperienceChangeResult",
    "LoopPresentation",
    "MIN_PAIRED_LOOPS",
    "MIN_PAIRED_SESSIONS",
    "PRESENTATION_DIVERGENCE_FLOOR",
    "PairObservables",
    "VERDICT_FAIL",
    "VERDICT_INCONCLUSIVE",
    "VERDICT_PASS",
    "behavior_diverged",
    "decide",
    "evaluate_paired_sessions",
    "framing_diverged",
    "load_pair_log",
    "main",
    "order_diverged",
    "pair_observables",
    "presentation_diverged",
    "session_observables_log",
    "session_presentations",
    "write_pair_log",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
