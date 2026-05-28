"""Mirror Loop M1 orchestration — the sole impure module in :mod:`mirror`.

This is the playable orchestration loop the M1 founder brief specifies
(``docs/mirror_loop_m1_founder_brief.md``): one module that walks the
**Prologue → Act 1 → Recalibration → Act 2 entry** slice end-to-end. Every other
module in :mod:`mirror` (``schema``, ``state``, ``log``, ``intake``) is a pure
transformation; the impurity — reading ``.scene`` files from disk, advancing a
seeded RNG to drive the simulated player, writing JSONL bytes — is concentrated
here so the rest of the package stays trivially testable as data.

What one *beat* is. The slice walks fourteen authored scenes laid out under
``game/scenes/data/act1/``. Each beat does the same five things, in order:

    1. load the scene file (``game.scenes.loader.load_scene``) — the only place
       the package reads bytes off the filesystem during play;
    2. pass it through the **single adaptation seam**, :func:`adapt`, which
       re-orders choices toward the player's confident lean on the Mirror's
       primary axis (``risk_tolerance`` — the locked caution↔aggression axis).
       With ``baseline=True`` the seam is the identity, so a baseline run is
       UX-identical to an adaptive run minus the adaptation layer;
    3. let the seeded policy (:func:`seeded_policy`) pick a choice from the
       offered order. The policy is biased toward the first-offered choice, so
       the Mirror's re-ordering is observable in the run's *content*, not only
       in its prediction labels;
    4. append a :class:`mirror.log.ChoiceObserved` event whose ``signals`` come
       from the tendency → signal mapping in :data:`TENDENCY_SIGNALS`, then a
       :class:`mirror.log.TurnAdvanced` so STATE axes decay at turn boundaries;
    5. for the Recalibration beat, render the scene's prompt as a *function* of
       the live :class:`MirrorState` (:func:`render_recalibration_prompt`) — the
       diegetic moment the lab tells you what it learned about you.

The output is JSONL: one ``event_to_dict`` per line, framed by a ``run_started``
header and a ``run_completed`` footer that records the final reduced state
snapshot. Sorted keys + LF newlines + no trailing whitespace make the byte
stream stable so the M1 byte-identity replay gate can lock onto it.

``--baseline`` is the parity arm: same seed, same intake, same beat ordering,
**identity** adaptation. The brief's DoD requires a baseline run to be
UX-identical minus the adaptation layer; the seam-is-identity rule in
:func:`adapt` is how that property is made structural rather than relying on a
disciplined caller.
"""

from __future__ import annotations

import json
import random
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, TextIO

from game.scenes.loader import load_scene
from loop.core import Scene
from mirror.intake import seed_log
from mirror.log import (
    ChoiceObserved,
    EventLog,
    TurnAdvanced,
    event_to_dict,
)
from mirror.schema import SCHEMA_VERSION, schema_fingerprint
from mirror.state import MirrorState, Signal

#: Repo-relative path to the directory holding the act-1 ``.scene`` files. Held
#: as a module constant so a test or a tool can override it via
#: :func:`scene_path` without monkeypatching.
SCENES_DIR = Path(__file__).resolve().parents[1] / "game" / "scenes" / "data" / "act1"


@dataclass(frozen=True)
class Beat:
    """One scheduled beat in the M1 slice: a phase label + a scene filename.

    The phase label (``"prologue"`` / ``"act1"`` / ``"recalibration"`` /
    ``"act2_entry"``) is what the JSONL footer / a downstream consumer reads to
    partition the run; it is not derivable from the filename alone (Act 1
    explicitly does not include the recalibration scene, even though both live
    in ``act1/``), so the schedule names it explicitly.
    """

    phase: str
    filename: str


#: The full M1 slice schedule — the founder brief's Prologue → Act 1 →
#: Recalibration → Act 2 entry — as a tuple so the order is the contract. The
#: filenames are the on-disk scene files under :data:`SCENES_DIR`.
SLICE: tuple[Beat, ...] = (
    # Prologue — the intake/onboarding triad before the first in-fiction scene.
    Beat("prologue", "act1_01_intake.scene"),
    Beat("prologue", "act1_02_questionnaire_genre.scene"),
    Beat("prologue", "act1_03_consent.scene"),
    # Act 1 — the eight in-fiction beats plus the climax.
    Beat("act1", "act1_04_first_scene.scene"),
    Beat("act1", "act1_05_npc_encounter.scene"),
    Beat("act1", "act1_06_optional_lore.scene"),
    Beat("act1", "act1_07_authority_request.scene"),
    Beat("act1", "act1_08_unmarked_door.scene"),
    Beat("act1", "act1_09_npc_distress.scene"),
    Beat("act1", "act1_10_resource_choice.scene"),
    Beat("act1", "act1_11_pattern_callback.scene"),
    Beat("act1", "act1_12_act1_climax.scene"),
    # Recalibration — the one beat whose prompt is rendered from MirrorState.
    Beat("recalibration", "act1_13_recalibration.scene"),
    # Act 2 entry — the slice's terminal beat.
    Beat("act2_entry", "act1_14_act2_entry.scene"),
)


# --- Tendency → Signal mapping ------------------------------------------------
#
# The ``.scene`` files declare each choice's tendency as one of
# ``kindness | control | defiance`` (the v0 vocabulary from
# ``docs/ADAPTATION.md`` §2). The Mirror's domain types (``mirror/schema.py``)
# speak in named axes. This table is the one place the two vocabularies meet:
# it pins which axes a tendency emits evidence on, and at what weight.
#
# The signals are chosen so the **locked M1 Mirror axis is exercised** every
# beat: ``risk_tolerance`` (the caution↔reckless axis the founder brief names)
# moves on every choice, so a session is guaranteed to *produce* a reading on
# it rather than relying on intake alone. ``authority_trust`` moves more softly
# on choices the v0 tendency vocabulary clearly speaks to. Weights stay below
# 1.0 so a single choice cannot saturate the axis.

#: Weight scale for in-fiction (slice) signals. Higher than the intake's 0.5
#: because observed behaviour is stronger evidence than self-report
#: (``mirror/intake.py``'s anti-mush rule).
_BEAT_WEIGHT = 0.7

#: For each tendency, the tuple of :class:`Signal` a beat of that tendency
#: emits. Stable order so the JSONL is byte-stable for a given run.
TENDENCY_SIGNALS: dict[str, tuple[Signal, ...]] = {
    "kindness": (
        Signal.toward("risk_tolerance", -1.0, _BEAT_WEIGHT),
        Signal.toward("authority_trust", 1.0, _BEAT_WEIGHT / 2),
    ),
    "control": (
        # Control reads as "scrutinise rules and procedure" — mild authority
        # scepticism (the *question*, not the refuse), no risk-axis evidence.
        Signal.toward("authority_trust", 0.0, _BEAT_WEIGHT / 2),
    ),
    "defiance": (
        Signal.toward("risk_tolerance", 1.0, _BEAT_WEIGHT),
        Signal.toward("authority_trust", -1.0, _BEAT_WEIGHT / 2),
    ),
}


def signals_for_tendency(tendency: str) -> tuple[Signal, ...]:
    """Return the :class:`Signal` tuple a beat of ``tendency`` emits.

    Raises :class:`KeyError` on an unknown tendency so a stray vocabulary in a
    scene file fails the run loudly instead of silently emitting an inert beat.
    """
    try:
        return TENDENCY_SIGNALS[tendency]
    except KeyError as exc:
        raise KeyError(
            f"unknown choice tendency {tendency!r}; the slice loop only knows "
            f"{sorted(TENDENCY_SIGNALS)!r}"
        ) from exc


# --- The single adaptation seam ----------------------------------------------
#
# Every adaptation in the slice flows through this one function, so toggling
# ``baseline`` flips the *only* arm that differs between adaptive and baseline
# runs. That structural single-seam is what the M1 baseline-parity gate locks
# onto: there is no second place in the slice where adaptation can sneak in,
# so the two arms are guaranteed identical apart from the choice ordering.

#: Confidence floor below which the Mirror does not yet trust its axis read
#: enough to surface a prediction. Matches the ``known()`` default in
#: ``mirror/state.py`` so the seam respects the same anti-mush bar.
_ADAPT_CONFIDENCE_FLOOR = 0.5

#: Absolute axis-value threshold under which the adaptation treats the player
#: as "not yet leaning either way" and falls back to the declared order — same
#: spirit as ``game.world.dominant_tendency``'s exact-tie rule.
_ADAPT_LEAN_THRESHOLD = 0.05


def predict_target_tendency(state: MirrorState) -> str | None:
    """The tendency the Mirror would surface first, or ``None`` for no lean.

    Reads the player's confident risk_tolerance value: negative → ``kindness``
    (cautious), positive → ``defiance`` (reckless). Returns ``None`` when the
    axis has not yet earned enough evidence (``confidence <
    _ADAPT_CONFIDENCE_FLOOR``) or is too close to neutral to call.

    Confined to ``risk_tolerance`` on purpose: the M1 founder brief locks the
    Mirror axis to *caution ↔ aggression*, and the brief's parity gate is
    cleaner when the seam reads exactly one axis.
    """
    reading = state.readings.get("risk_tolerance")
    if reading is None or reading.confidence < _ADAPT_CONFIDENCE_FLOOR:
        return None
    value = float(reading.value)
    if abs(value) < _ADAPT_LEAN_THRESHOLD:
        return None
    return "defiance" if value > 0 else "kindness"


def adapt(scene: Scene, state: MirrorState, *, baseline: bool) -> Scene:
    """The single adaptation seam: re-order ``scene`` choices toward the lean.

    With ``baseline=True`` returns ``scene`` unchanged — the **identity** layer
    the brief's parity gate requires. With ``baseline=False``, sorts choices so
    the one whose ``tendency`` matches :func:`predict_target_tendency` leads;
    ties (no lean, or the predicted tendency absent) preserve the declared
    order.

    Re-order-only: the seam never invents, drops, or rewrites a choice
    (``docs/ADAPTATION.md`` §1). The output ``Scene`` has the same id, prompt,
    and choice set — just possibly in a new order.
    """
    if baseline:
        return scene
    target = predict_target_tendency(state)
    if target is None:
        return scene
    declared_order = {c.id: i for i, c in enumerate(scene.choices)}
    reordered = tuple(
        sorted(
            scene.choices,
            key=lambda c: (0 if c.tendency == target else 1, declared_order[c.id]),
        )
    )
    if reordered == scene.choices:
        return scene
    return replace(scene, choices=reordered)


# --- Recalibration: rendered from MirrorState --------------------------------


def recalibration_summary(state: MirrorState) -> str:
    """One-line diegetic summary of the player model at the Recalibration beat.

    Pure function of ``state``. The renderer reads the two named M1 axes
    (``risk_tolerance``, ``authority_trust``) and, for each one the Mirror has
    a confident-enough read on, names the pole the player has leaned toward
    plus the rounded value. Returns the bare "no clear lean" line when neither
    axis has earned a confident read, so the slice can still finish coherently
    on a player who only made middle-ground choices.
    """
    parts: list[str] = []
    rt = state.readings.get("risk_tolerance")
    if rt is not None and rt.confidence >= 0.3:
        value = float(rt.value)
        if value >= _ADAPT_LEAN_THRESHOLD:
            parts.append(f"reckless ({value:+.2f})")
        elif value <= -_ADAPT_LEAN_THRESHOLD:
            parts.append(f"cautious ({value:+.2f})")
    at = state.readings.get("authority_trust")
    if at is not None and at.confidence >= 0.3:
        value = float(at.value)
        if value >= _ADAPT_LEAN_THRESHOLD:
            parts.append(f"deferential ({value:+.2f})")
        elif value <= -_ADAPT_LEAN_THRESHOLD:
            parts.append(f"defiant ({value:+.2f})")
    if not parts:
        return "MIRROR // RECALIBRATION: no clear lean yet — calibrating from neutral."
    return "MIRROR // RECALIBRATION: you have leaned " + ", ".join(parts) + "."


def render_recalibration_prompt(scene: Scene, state: MirrorState) -> Scene:
    """Return the Recalibration scene with its prompt rendered from ``state``.

    Prepends :func:`recalibration_summary` to the authored prompt; the choices
    and ids are unchanged. Pure — produces a fresh :class:`Scene`, leaving the
    file-loaded one untouched, so a second call with the same ``state`` yields
    the same scene.
    """
    summary = recalibration_summary(state)
    return replace(scene, prompt=f"{summary}\n\n{scene.prompt}")


# --- Policy: how the simulated player picks a choice -------------------------

#: Policy callable shape: given the *offered* scene (post-adapt), the current
#: state, and a beat index, return one of the scene's choice ids.
Policy = Callable[[Scene, MirrorState, int], str]

#: Position weights for the seeded simulated player. Biased toward the first
#: offered choice so a re-ordering by :func:`adapt` is observable in the run's
#: trajectory, not only in the prediction labels. Three entries cover every
#: shipped scene (every Act-1 scene offers exactly three choices); shorter
#: scenes truncate. Tuned so a first-offered choice wins about 60% of the time.
_POSITION_WEIGHTS: tuple[int, ...] = (60, 30, 10)


def seeded_policy(seed: int) -> Policy:
    """A deterministic, position-biased policy seeded by ``seed``.

    Drives a simulated player whose pick is a function of (seed, beat index,
    offered order). Two calls with the same seed and the same offered orders
    return the same choices, so a run is fully reproducible — required by the
    M1 byte-identity replay gate.

    Bias toward the first-offered choice makes the in-scene adaptation seam
    *visible* in the trajectory: when :func:`adapt` moves the predicted choice
    to position 0, the policy is more likely to pick it. Without that bias the
    adaptation would only affect prediction labels, not the run's content —
    failing the founder brief's "UX-identical minus adaptation" gate, which is
    only meaningful if adaptation actually shapes what the player sees take
    effect.
    """
    rng = random.Random(seed)

    def pick(scene: Scene, _state: MirrorState, _beat_index: int) -> str:
        n = len(scene.choices)
        weights = list(_POSITION_WEIGHTS[:n])
        # Pad if a scene ever ships with more than three choices, so the policy
        # is total over the format. The format does not constrain choice count.
        while len(weights) < n:
            weights.append(weights[-1])
        index = rng.choices(range(n), weights=weights, k=1)[0]
        return scene.choices[index].id

    return pick


# --- The orchestration -------------------------------------------------------


@dataclass(frozen=True)
class BeatRecord:
    """One beat as it played out — enough to render and to write JSONL.

    Frozen and self-describing: a list of these is sufficient to reconstruct
    the slice run, but the JSONL serializer in :func:`write_jsonl` reads from
    a richer source (a full :class:`EventLog`) so a downstream consumer can
    feed the *log* into the reducer without going through this dataclass.
    """

    beat_index: int
    phase: str
    scene_id: str
    declared_order: tuple[str, ...]
    offered_order: tuple[str, ...]
    actual_choice: str
    tendency: str
    reordered: bool


@dataclass(frozen=True)
class SliceRun:
    """The completed slice: an :class:`EventLog`, beat records, final state.

    Returned by :func:`play_slice` so callers (the CLI, tests) can both write
    JSONL (the byte-stable surface) *and* introspect the run structurally
    (e.g. "did Recalibration prepend a MirrorState-derived line?") without
    re-parsing JSONL.
    """

    seed: int
    baseline: bool
    log: EventLog
    beats: tuple[BeatRecord, ...]
    final_state: MirrorState
    recalibration_summary: str


def play_slice(
    *,
    seed: int = 0,
    baseline: bool = False,
    intake_answers: Mapping[str, str] | None = None,
    scenes_dir: Path | None = None,
    policy: Policy | None = None,
) -> SliceRun:
    """Run the M1 slice end-to-end and return the recorded :class:`SliceRun`.

    Walks :data:`SLICE` beat by beat: load → adapt → policy pick → emit
    ``ChoiceObserved`` + ``TurnAdvanced`` → fold into ``state``. The
    Recalibration beat has its prompt re-rendered from the live
    :class:`MirrorState` via :func:`render_recalibration_prompt`; that re-render
    runs *before* the seam, so the seam still re-orders the choices on the
    Recalibration scene under the same rule as every other beat.

    ``intake_answers`` (optional) seed the run from the questionnaire so the
    Mirror starts with a soft prior instead of blank — the same path
    :mod:`mirror.intake` already implements. Without it the run starts blank
    and the adaptation simply does not fire until enough beats have moved an
    axis past the confidence floor.

    All file I/O happens here (and in :func:`load_scene`, which this calls):
    no other :mod:`mirror` module touches the filesystem during play.
    """
    scenes_dir = scenes_dir if scenes_dir is not None else SCENES_DIR
    policy = policy if policy is not None else seeded_policy(seed)

    # Start the log from the intake events if any, so the slice log carries the
    # full causal chain — the questionnaire is just the first chapter of the
    # same append-only log (``mirror/intake.py``'s contract).
    if intake_answers:
        log = seed_log(intake_answers)
    else:
        log = EventLog()
    state = log.reduce()

    beats: list[BeatRecord] = []
    captured_recalibration_summary: str | None = None
    for beat_index, beat in enumerate(SLICE):
        loaded = load_scene(scenes_dir / beat.filename)
        if beat.phase == "recalibration":
            # Capture the lab's summary *as it was shown to the player* — i.e.
            # from the state before this beat's own choice contributed
            # evidence. Stashing the summary here keeps it a pure function of
            # the prior log without later having to reduce a prefix slice.
            captured_recalibration_summary = recalibration_summary(state)
            loaded = render_recalibration_prompt(loaded, state)
        offered = adapt(loaded, state, baseline=baseline)
        choice_id = policy(offered, state, beat_index)
        chosen = offered.choice(choice_id)
        signals = signals_for_tendency(chosen.tendency)

        choice_event = ChoiceObserved(
            choice_id=choice_id,
            signals=signals,
            scene_id=loaded.id,
            act_id=beat.phase,
        )
        log = log.append(choice_event, TurnAdvanced())
        state = log.reduce()

        beats.append(
            BeatRecord(
                beat_index=beat_index,
                phase=beat.phase,
                scene_id=loaded.id,
                declared_order=tuple(c.id for c in loaded.choices),
                offered_order=tuple(c.id for c in offered.choices),
                actual_choice=choice_id,
                tendency=chosen.tendency,
                reordered=tuple(c.id for c in offered.choices)
                != tuple(c.id for c in loaded.choices),
            )
        )

    # The slice always includes a Recalibration beat (SLICE pins it), so the
    # captured summary cannot be None on a successful run; fall back defensively
    # to the final state in case a caller ever ships a SLICE without one.
    final_summary = (
        captured_recalibration_summary
        if captured_recalibration_summary is not None
        else recalibration_summary(state)
    )
    return SliceRun(
        seed=seed,
        baseline=baseline,
        log=log,
        beats=tuple(beats),
        final_state=state,
        recalibration_summary=final_summary,
    )


# --- JSONL emit (the impure boundary) ----------------------------------------


def _jsonl_line(payload: dict) -> str:
    """One JSONL line: sorted keys, no whitespace, LF terminator. Pure."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def jsonl_lines(run: SliceRun) -> Iterator[str]:
    """Yield the JSONL representation of ``run`` one line at a time. Pure.

    Layout:

    * ``run_started`` header — seed, baseline arm, schema version + fingerprint,
      plus the scheduled beat phases so a malformed mid-run truncation is
      detectable;
    * one ``event_to_dict`` payload per recorded event, augmented with
      ``beat_index`` / ``phase`` / ``offered_order`` for ``ChoiceObserved``
      lines so a consumer does not have to re-walk the slice to know which
      beat an event belongs to;
    * ``run_completed`` footer — the final reduced state and the
      Recalibration summary, so a JSONL consumer can verify the byte stream
      ends with the same state that re-reducing the events would produce.

    The serializer is pure (no I/O); :func:`write_jsonl` is the thin impure
    wrapper that drains the iterator into a stream.
    """
    yield _jsonl_line(
        {
            "event_type": "run_started",
            "seed": run.seed,
            "baseline": run.baseline,
            "schema_version": SCHEMA_VERSION,
            "fingerprint": schema_fingerprint(),
            "beats": [{"phase": b.phase, "scene_id": b.scene_id} for b in run.beats],
        }
    )

    beats_by_scene = {b.scene_id: b for b in run.beats}
    seen_scene_ids: set[str] = set()
    for event in run.log.events:
        payload = event_to_dict(event)
        if isinstance(event, ChoiceObserved) and event.scene_id is not None:
            beat = beats_by_scene.get(event.scene_id)
            if beat is not None and event.scene_id not in seen_scene_ids:
                payload["beat_index"] = beat.beat_index
                payload["phase"] = beat.phase
                payload["offered_order"] = list(beat.offered_order)
                payload["declared_order"] = list(beat.declared_order)
                payload["reordered"] = beat.reordered
                seen_scene_ids.add(event.scene_id)
        yield _jsonl_line(payload)

    yield _jsonl_line(
        {
            "event_type": "run_completed",
            "final_state": run.final_state.snapshot(),
            "recalibration_summary": run.recalibration_summary,
        }
    )


def write_jsonl(run: SliceRun, stream: TextIO) -> None:
    """Write the JSONL representation of ``run`` to ``stream``. Impure boundary.

    The single point where the slice touches a writable byte stream: every
    other function in this module is pure. Bytes are exactly what
    :func:`jsonl_lines` yields — sorted keys, LF newlines, no trailing
    whitespace — so the M1 byte-identity gate can compare streams directly.
    """
    for line in jsonl_lines(run):
        stream.write(line)


# --- Convenience wrapper used by ``python -m mirror play`` -------------------


def render_jsonl(run: SliceRun) -> str:
    """Return the JSONL representation of ``run`` as one string. Pure."""
    return "".join(jsonl_lines(run))


def play(
    *,
    seed: int = 0,
    baseline: bool = False,
    intake_answers: Mapping[str, str] | None = None,
    out: TextIO | None = None,
) -> SliceRun:
    """Run the slice and write its JSONL to ``out`` (default: ``sys.stdout``).

    The thin wrapper :mod:`mirror.__main__` calls when ``python -m mirror play
    --seed N`` is invoked without ``--answers``. Returns the
    :class:`SliceRun` so an in-process caller (like the CLI tests) can also
    introspect the run structurally.
    """
    run = play_slice(seed=seed, baseline=baseline, intake_answers=intake_answers)
    write_jsonl(run, out if out is not None else sys.stdout)
    return run


__all__ = [
    "SCENES_DIR",
    "Beat",
    "SLICE",
    "TENDENCY_SIGNALS",
    "signals_for_tendency",
    "predict_target_tendency",
    "adapt",
    "recalibration_summary",
    "render_recalibration_prompt",
    "Policy",
    "seeded_policy",
    "BeatRecord",
    "SliceRun",
    "play_slice",
    "jsonl_lines",
    "render_jsonl",
    "write_jsonl",
    "play",
]
