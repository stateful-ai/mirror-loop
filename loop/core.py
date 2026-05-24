"""The Mirror Loop core: one turn, one adaptation type, one legibility beat.

This is the load-bearing runtime described in ``docs/CORE_LOOP.md``. It is
deliberately tiny and dependency-free (stdlib only, same as the acceptance gate)
so that the *shape* of the loop is fixed before any LLM/agent machinery is built
on top of it.

The four stages of a turn, named to match the acceptance criterion
(``scene -> choices -> state update -> visible "Mirror noticed..." reason``):

1. **scene / choices** — a :class:`Scene` offers a small set of :class:`Choice`
   options. Each choice carries exactly one ``tendency`` label (the single
   behavioral axis we model) and an ``evidence`` phrase (how the Mirror will
   later describe the act it observed).
2. **state update** — the chosen choice is appended to :class:`PlayerState`,
   which tracks the running tally of tendencies. State is immutable; every
   update returns a new value.
3. **the legibility beat** — once one tendency crosses
   :data:`NOTICE_THRESHOLD`, the :class:`Mirror` emits a :class:`Reflection`:
   the visible ``"Mirror noticed..."`` line, whose *reason* cites only the
   in-game evidence behind it (never anything outside the game).

The Mirror ships with exactly **one adaptation type**: *tendency mirroring*. It
predicts the player's next choice from their running tendency tally
(:meth:`Mirror.predict`) and biases the next scene so the predicted option leads
(:meth:`Mirror.adapt`). That prediction is also what the acceptance gate scores
(``predicted_actions`` vs ``actual_action``), so the loop and the thesis test
speak the same language — see :meth:`StepResult.decision_point`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

# Number of choices along a single tendency before the Mirror "notices" it and
# surfaces the legibility beat. Three consistent choices reads as a pattern, not
# a coincidence. Kept here as the single source of truth for the loop.
NOTICE_THRESHOLD = 3


@dataclass(frozen=True)
class Choice:
    """One option the player can select within a scene.

    ``tendency`` is the single behavioral axis the choice expresses (the only
    thing the prototype models). ``evidence`` is a past-tense phrase the Mirror
    cites when it reflects — phrased as *observed in-game behavior*, never a
    claim about the real player, to honor the fiction boundary.
    """

    id: str
    text: str  # what the player reads and selects
    tendency: str  # the single axis this choice expresses, e.g. "kindness"
    evidence: str  # how the Mirror describes the act it observed


@dataclass(frozen=True)
class Scene:
    """A prompt plus the choices it offers."""

    id: str
    prompt: str
    choices: tuple[Choice, ...]

    def choice(self, choice_id: str) -> Choice:
        for c in self.choices:
            if c.id == choice_id:
                return c
        raise KeyError(f"no choice {choice_id!r} in scene {self.id!r}")


@dataclass(frozen=True)
class Turn:
    """A recorded decision: which choice the player made in which scene."""

    scene_id: str
    choice: Choice

    @property
    def tendency(self) -> str:
        return self.choice.tendency


@dataclass(frozen=True)
class PlayerState:
    """The player model. Immutable; every update returns a new state.

    For the MVP the "model" is just the running history of turns and the set of
    tendencies the Mirror has already announced (so it does not repeat itself).
    Everything else (counts, dominant tendency) is derived on demand.
    """

    history: tuple[Turn, ...] = ()
    announced: frozenset[str] = frozenset()

    @property
    def turn_count(self) -> int:
        return len(self.history)

    @property
    def tendency_counts(self) -> Counter[str]:
        return Counter(t.tendency for t in self.history)

    def record(self, scene: Scene, choice: Choice) -> "PlayerState":
        """Return a new state with this scene/choice appended (stage 2)."""
        return replace(self, history=self.history + (Turn(scene.id, choice),))

    def mark_announced(self, tendency: str) -> "PlayerState":
        return replace(self, announced=self.announced | {tendency})


@dataclass(frozen=True)
class Reflection:
    """The legibility beat — the visible ``"Mirror noticed..."`` line.

    ``evidence`` is the list of in-game acts that earned the notice; it is the
    *reason* the player sees. It is grounded entirely in choices already made.
    """

    tendency: str
    count: int
    total: int
    evidence: tuple[str, ...]

    def render(self) -> str:
        reason = "; ".join(self.evidence)
        return (
            f"Mirror noticed: you chose {self.tendency} in "
            f"{self.count} of {self.total} moments so far.\n"
            f"  reason: {reason}."
        )


@dataclass(frozen=True)
class StepResult:
    """The outcome of one turn: what the Mirror predicted, what the player did,
    the new state, and the legibility beat (if one fired this turn)."""

    scene_id: str
    predicted_actions: tuple[str, ...]  # the Mirror's ranked forecast, made *before* the choice
    actual_action: str
    state: PlayerState
    reflection: Reflection | None

    def decision_point(self) -> dict:
        """Emit this turn in the shape the acceptance gate scores.

        Matches ``acceptance/predictability.py``'s ``DecisionPoint`` so a real
        session log feeds straight into the Beats-Baseline Prediction Test.
        """
        return {
            "scene_id": self.scene_id,
            "predicted_actions": list(self.predicted_actions),
            "actual_action": self.actual_action,
        }


class Mirror:
    """The adaptation engine. Exactly one adaptation type: *tendency mirroring*.

    It tracks the player's choices along one behavioral axis, predicts the next
    choice from that running tally, surfaces a legibility beat once a tendency is
    established, and biases the next scene so the predicted option leads.
    """

    def __init__(self, notice_threshold: int = NOTICE_THRESHOLD) -> None:
        self.notice_threshold = notice_threshold

    def rank(self, state: PlayerState, scene: Scene) -> list[Choice]:
        """Order a scene's choices by how strongly the player leans that way.

        Higher running tendency count first; ties broken by the scene's declared
        order so the result is fully deterministic (and, with no history, equals
        the declared order).
        """
        counts = state.tendency_counts
        declared = {c.id: i for i, c in enumerate(scene.choices)}
        return sorted(
            scene.choices,
            key=lambda c: (-counts.get(c.tendency, 0), declared[c.id]),
        )

    def predict(self, state: PlayerState, scene: Scene) -> tuple[str, ...]:
        """Ranked forecast of the player's next choice (most likely first)."""
        return tuple(c.id for c in self.rank(state, scene))

    def reflect(self, state: PlayerState) -> Reflection | None:
        """Stage 3: the legibility beat, or ``None`` if nothing new to notice.

        Fires the first time a tendency reaches the notice threshold and has not
        been announced yet, so the Mirror notices a pattern exactly once.
        """
        counts = state.tendency_counts
        if not counts:
            return None
        tendency, count = counts.most_common(1)[0]
        if count >= self.notice_threshold and tendency not in state.announced:
            evidence = tuple(
                t.choice.evidence for t in state.history if t.tendency == tendency
            )
            return Reflection(
                tendency=tendency,
                count=count,
                total=state.turn_count,
                evidence=evidence,
            )
        return None

    def adapt(self, state: PlayerState, scene: Scene) -> Scene:
        """The single adaptation: re-present a scene with the predicted choice
        first. A no-op when the declared order already leads with it."""
        return replace(scene, choices=tuple(self.rank(state, scene)))

    def step(self, state: PlayerState, scene: Scene, choice_id: str) -> StepResult:
        """Run one full turn against ``scene`` and return the result.

        Predicts from the *prior* state (so the forecast is honest — it has not
        seen this choice), records the choice, then reflects on the new state.
        """
        choice = scene.choice(choice_id)
        predicted = self.predict(state, scene)
        new_state = state.record(scene, choice)
        reflection = self.reflect(new_state)
        if reflection is not None:
            new_state = new_state.mark_announced(reflection.tendency)
        return StepResult(
            scene_id=scene.id,
            predicted_actions=predicted,
            actual_action=choice_id,
            state=new_state,
            reflection=reflection,
        )
