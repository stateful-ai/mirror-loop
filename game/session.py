"""The session runner — playing the handcrafted world through the core loop.

This is where the three pieces meet, with **no LLM anywhere on the path**:

* ``loop.core.Mirror`` runs each turn (predict → adapt/re-order → record →
  reflect) — the locked four-stage core loop,
* ``game.world`` decides which pre-authored scene framing to reveal next from the
  player model (branch selection), and
* ``game.templates`` renders the Mirror's escalating system voice and closing
  report from that same model.

A *loop* here is one full turn of the world: the Mirror reveals a (possibly
re-ordered, possibly branch-selected) scene, the player chooses, state updates,
and the Mirror speaks. A session is the whole five-loop spine, which sits inside
the 3–5-loop target; :func:`play_session` enforces that bound explicitly.

Each loop's ``predicted_actions`` / ``actual_action`` is, unchanged, a decision
point the locked acceptance gate scores — so a real playthrough drops straight
into ``python -m acceptance.predictability`` (``docs/CORE_LOOP.md`` §5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

from acceptance.predictability import DecisionPoint, top1_accuracy
from loop.core import Mirror, PlayerState, Scene, StepResult

from .templates import SystemMessage, adapt_message, final_report
from .variants import ADAPTIVE, Variant
from .world import DEFAULT_WORLD, Slot, World, dominant_tendency

# Session length must land in the 3–5-loop target. The default world is a fixed
# five-loop spine; the bound is asserted so any future world that strays out of
# range fails loudly rather than shipping an over-long or trivial session.
MIN_LOOPS = 3
MAX_LOOPS = 5

# A policy decides the player's choice for one loop, given the scene exactly as
# the Mirror offered it (post-adaptation), the state so far, and the loop index.
Policy = Callable[[Scene, PlayerState, int], str]


@dataclass(frozen=True)
class LoopRecord:
    """Everything that happened in one loop, enough to render and to score."""

    loop_index: int
    declared: Scene  # the scene before the Mirror re-ordered it
    offered: Scene  # the scene as the Mirror presented it (post-adapt)
    branch_key: str  # which world branch was revealed ("fixed"/"default"/tendency)
    result: StepResult
    system_message: SystemMessage

    @property
    def reordered(self) -> bool:
        """True if the Mirror re-ordered this scene's choices (visible adaptation)."""
        return [c.id for c in self.offered.choices] != [c.id for c in self.declared.choices]

    @property
    def predicted_hit(self) -> bool:
        return bool(self.result.predicted_actions) and (
            self.result.predicted_actions[0] == self.result.actual_action
        )


@dataclass(frozen=True)
class Session:
    """A completed playthrough: every loop plus the final player model."""

    records: tuple[LoopRecord, ...]
    final_state: PlayerState
    world_name: str
    variant_name: str = ADAPTIVE.name

    @property
    def loop_count(self) -> int:
        return len(self.records)

    def decision_points(self) -> list[DecisionPoint]:
        return [
            DecisionPoint(
                predicted_actions=tuple(r.result.predicted_actions),
                actual_action=r.result.actual_action,
            )
            for r in self.records
        ]

    def session_log(self, session_id: str = "mirror-loop") -> dict:
        """Render in the shape ``acceptance/predictability.py`` scores.

        Includes the ``variant`` arm so A/B logs are self-labelling: the data is
        tagged even though the player-facing transcript stays blind.
        """
        return {
            "session_id": session_id,
            "act": self.world_name,
            "variant": self.variant_name,
            "decision_points": [r.result.decision_point() for r in self.records],
        }

    @property
    def top1_accuracy(self) -> float:
        return top1_accuracy(self.decision_points())


# --- One loop, in two halves ------------------------------------------------
# A loop is offer → choose → record. The offer (read-only) and the record (the
# step) are split so they can be driven two ways from one implementation: the
# one-shot :func:`play_session` calls a policy *between* the halves, and the
# resumable :class:`game.playsession.PlaySession` shows the offer to a UI, takes
# a choice id, then records it — possibly across a save/reload boundary. Sharing
# these two functions is what guarantees both runners step the loop identically.


def offer_scene(
    variant: Variant, mirror: Mirror, state: PlayerState, slot: Slot
) -> tuple[Scene, Scene, str]:
    """The Mirror's offer for one slot: ``(declared, offered, branch_key)``.

    ``declared`` is the framing the world selected for this slot (the across-scene
    adaptation), ``offered`` is that scene as the Mirror presents it (the in-scene
    re-ordering), and ``branch_key`` names the framing revealed. This is the
    read-only half of a loop — what the player is *about* to be offered, before
    any choice is made — so an interactive caller can render it and a resumable
    session can recompute it on demand. It does not touch ``state``.
    """
    declared, branch_key = variant.select_scene(slot, state)
    offered = variant.order_choices(mirror, state, declared)
    return declared, offered, branch_key


def record_loop(
    mirror: Mirror,
    state: PlayerState,
    declared: Scene,
    offered: Scene,
    branch_key: str,
    choice_id: str,
    *,
    loop_index: int,
    is_finale: bool,
) -> LoopRecord:
    """Step a chosen choice against an already-offered scene and record it.

    The write half of a loop: given the offer (:func:`offer_scene`) and the
    player's ``choice_id``, step the locked core loop, build the Mirror's
    escalating voice line, and return the :class:`LoopRecord`. The new
    accumulated state is ``record.result.state`` — the caller folds it forward.
    Shared verbatim by :func:`play_session` and
    :class:`game.playsession.PlaySession`.
    """
    model_locked_before = bool(state.announced)
    result = mirror.step(state, offered, choice_id)
    counts = result.state.tendency_counts
    dominant, dominant_count = counts.most_common(1)[0]
    predicted_hit = bool(result.predicted_actions) and result.predicted_actions[0] == choice_id
    message = adapt_message(
        dominant=dominant,
        dominant_count=dominant_count,
        total=result.state.turn_count,
        just_noticed=result.reflection is not None,
        model_locked=bool(result.state.announced) or model_locked_before,
        predicted_hit=predicted_hit,
        is_finale=is_finale,
    )
    return LoopRecord(
        loop_index=loop_index,
        declared=declared,
        offered=offered,
        branch_key=branch_key,
        result=result,
        system_message=message,
    )


def play_session(
    policy: Policy,
    *,
    world: World = DEFAULT_WORLD,
    mirror: Mirror | None = None,
    variant: Variant = ADAPTIVE,
    on_loop: Callable[[LoopRecord], None] | None = None,
) -> Session:
    """Play ``world`` once under ``policy`` and return the completed session.

    Drives the locked core loop for each slot: the ``variant`` selects the scene
    framing and orders its choices (the single adaptation seam — see
    :mod:`game.variants`), the policy chooses, the Mirror steps and speaks. The
    default :data:`~game.variants.ADAPTIVE` arm is the real game; the baseline
    arms set that seam to the identity or a player-independent placebo for A/B
    feel-testing, and are driven through this same path with no special-casing.

    ``on_loop`` (if given) is called with each completed :class:`LoopRecord` as it
    happens, so an interactive player sees the Mirror's reaction live between
    choices. Raises ``ValueError`` if the world produced a session outside the
    3–5-loop target.
    """
    mirror = mirror or Mirror()
    state = PlayerState()
    records: list[LoopRecord] = []

    # Walk the spine slot by slot. The session length is exactly the spine length
    # (the bound below asserts it lands in 3–5) — there is no early exit: the seam
    # is total, returning a real Scene for every slot regardless of variant or
    # player state (pinned in test_variants/test_world), so nothing here can be
    # None or short-circuit the loop.
    for i, slot in enumerate(world.slots):
        declared, offered, branch_key = offer_scene(variant, mirror, state, slot)
        choice_id = policy(offered, state, i)
        record = record_loop(
            mirror,
            state,
            declared,
            offered,
            branch_key,
            choice_id,
            loop_index=i,
            is_finale=(i == world.length - 1),
        )
        records.append(record)
        if on_loop is not None:
            on_loop(record)
        state = record.result.state

    if not (MIN_LOOPS <= len(records) <= MAX_LOOPS):
        raise ValueError(
            f"session produced {len(records)} loops; the target is "
            f"{MIN_LOOPS}-{MAX_LOOPS} loops per session"
        )

    return Session(
        records=tuple(records),
        final_state=state,
        world_name=world.name,
        variant_name=variant.name,
    )


# --- Policies ----------------------------------------------------------------
# Pre-scripted "personas" so the whole game runs deterministically with no human
# and no LLM — used by the demo CLI and the tests. The stdin policy is the one a
# real player drives.


def persona_policy(target: str) -> Policy:
    """Always take the choice expressing ``target`` (a consistent player)."""

    def pick(scene: Scene, state: PlayerState, loop_index: int) -> str:
        for choice in scene.choices:
            if choice.tendency == target:
                return choice.id
        return scene.choices[0].id

    return pick


def erratic_policy() -> Policy:
    """Cycle through tendencies — a deliberately unpredictable player.

    This is the escape archetype (``docs/game_design.md`` §12): the model never
    locks, the closing report reads low predictability, high agency drift.
    """
    order = ("kindness", "control", "defiance")

    def pick(scene: Scene, state: PlayerState, loop_index: int) -> str:
        target = order[loop_index % len(order)]
        for choice in scene.choices:
            if choice.tendency == target:
                return choice.id
        return scene.choices[0].id

    return pick


def scripted_policy(choice_ids: Iterable[str]) -> Policy:
    """Replay an exact sequence of choice ids (one per loop)."""
    iterator: Iterator[str] = iter(choice_ids)

    def pick(scene: Scene, state: PlayerState, loop_index: int) -> str:
        return next(iterator)

    return pick


PERSONAS: dict[str, Callable[[], Policy]] = {
    "kind": lambda: persona_policy("kindness"),
    "controlling": lambda: persona_policy("control"),
    "defiant": lambda: persona_policy("defiance"),
    "erratic": erratic_policy,
}


def stdin_policy(
    prompt: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> Policy:
    """Interactive policy: show the offered scene and read the player's choice.

    Choices are shown in the order the Mirror offered them (predicted-first once a
    pattern forms), so the player sees the adaptation as they play.
    """

    def pick(scene: Scene, state: PlayerState, loop_index: int) -> str:
        out(f"\n--- LOOP {loop_index + 1} ---")
        out(scene.prompt)
        for n, choice in enumerate(scene.choices, start=1):
            out(f"  {n}. {choice.text}")
        while True:
            raw = prompt("Choose [1-{n}]: ".format(n=len(scene.choices))).strip()
            if raw.isdigit() and 1 <= int(raw) <= len(scene.choices):
                return scene.choices[int(raw) - 1].id
            out("  (enter the number of a listed choice)")

    return pick


# --- Rendering ---------------------------------------------------------------


def _format_loop(record: LoopRecord) -> str:
    result = record.result
    offered = record.offered
    predicted_top = result.predicted_actions[0] if result.predicted_actions else None

    lines = [f"================ LOOP {record.loop_index + 1} ================"]
    branch_note = "" if record.branch_key in ("fixed", "default") else f"  (Mirror revealed the '{record.branch_key}' framing)"
    lines.append(f"SCENE  [{offered.id}]{branch_note}")
    lines.append(f"  {offered.prompt}")
    lines.append("CHOICES (as the Mirror offered them):")
    for choice in offered.choices:
        marker = ">" if choice.id == result.actual_action else " "
        nudge = "  <- surfaced first by the Mirror" if (record.reordered and choice.id == predicted_top) else ""
        lines.append(f"  {marker} [{choice.id}] {choice.text}  ({choice.tendency}){nudge}")
    if record.reordered:
        lines.append(f"ADAPTATION: Mirror predicted '{predicted_top}' and moved it to the top.")

    counts = ", ".join(f"{k}={v}" for k, v in sorted(result.state.tendency_counts.items()))
    lines.append(f"PLAYER CHOOSES: {result.actual_action}")
    lines.append(f"STATE UPDATE: {counts}  (loops so far: {result.state.turn_count})")

    if result.reflection is not None:
        lines.append("REFLECTION:")
        for ln in result.reflection.render().splitlines():
            lines.append(f"  {ln}")
    lines.append(record.system_message.render())
    return "\n".join(lines)


def report_block(session: Session) -> str:
    """The Mirror's closing diegetic readout for a completed session."""
    points = session.decision_points()
    hits = sum(p.top1_correct for p in points)
    dominant = dominant_tendency(session.final_state) or "kindness"
    return final_report(
        hits=hits,
        total=len(points),
        accuracy=session.top1_accuracy,
        dominant=dominant,
    )


def transcript(session: Session) -> str:
    """A human-readable trace of a whole session, ending with the readout."""
    blocks = [_format_loop(r) for r in session.records]
    return "\n\n".join(blocks) + "\n\n" + report_block(session)


def live_feedback(out: Callable[[str], None] = print) -> Callable[[LoopRecord], None]:
    """An ``on_loop`` hook that prints the Mirror's reaction after each choice,
    for interactive play (where the scene/choices were already shown by
    :func:`stdin_policy` before the player chose)."""

    def show(record: LoopRecord) -> None:
        if record.reordered:
            top = record.result.predicted_actions[0]
            out(f"  (the Mirror had moved '{top}' to the top — it expected that choice)")
        if record.result.reflection is not None:
            for ln in record.result.reflection.render().splitlines():
                out(f"  {ln}")
        out(record.system_message.render())

    return show
