"""Real prompts, built from the shipped world — the harness's corpus.

The acceptance bar is *cost/latency on **real** prompts*, not synthetic filler. So
this module constructs the prompts an LLM would actually receive at the two places
the design imagines putting one, and it builds them out of the **real game
content** — the authored scenes, choices, and evidence phrases in
``game.world.DEFAULT_WORLD`` — paired with **real player-model reads** taken by
walking representative personas through that world with the shipped branch-selection
logic (``game.world.Slot.pick``). Nothing here is lorem ipsum: every prompt embeds
prose and choices that ship today.

Two insertion points, chosen to bracket the two latency regimes the go/no-go turns
on (``README.md`` "Agent Architecture"; "Development Principles" #3-4):

* **NPC reply** (:attr:`InsertionPoint.NPC_REPLY`) — generate the Mirror's
  free-form in-character line reacting to the player's latest choice. This is **on
  the critical path**: the player waits for it every loop. Short output.
* **Branch candidate** (:attr:`InsertionPoint.BRANCH_CANDIDATE`) — author the next
  scene's tailored framing ahead of the player (the generative analogue of v0's
  templated ``BRANCH_SELECTION`` adaptation). This is **off the critical path**: it
  can be precomputed and cached before the player arrives. Larger, structured
  output.

The prompts also carry the design's safety contract in their instructions —
reflect only in-game behavior, never remove a door, never rewrite the engine
(``docs/ADAPTATION.md`` §4; ``docs/GUARDRAILS.md``) — because a realistic prompt is
one that already constrains the model the way the loop would have to.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator

from game.world import DEFAULT_WORLD, Slot, World, dominant_tendency
from loop.core import Choice, PlayerState, Scene


class InsertionPoint(Enum):
    """Where in the content supply chain an LLM call would sit."""

    NPC_REPLY = "npc_reply"
    BRANCH_CANDIDATE = "branch_candidate"


@dataclass(frozen=True)
class InsertionPointSpec:
    """The fixed properties of one insertion point the harness reasons about.

    ``expected_output_tokens`` is the task's output budget (the call's generation
    length is set by the *task*, not the model, so cost/latency compare like for
    like across candidates). ``on_critical_path`` is the single fact the go/no-go
    decision hinges on: an on-path call adds directly to the latency the player
    feels; an off-path call can be precomputed and cached.
    """

    point: InsertionPoint
    label: str
    on_critical_path: bool
    expected_output_tokens: int
    rationale: str


#: Output budgets are grounded in the shipped content: an NPC line is one short
#: in-character sentence (the design's "short context packets / fast NPC replies"),
#: and a branch candidate is a scene package the size of the authored ones in
#: ``game.world`` — a 2-3 sentence prompt plus three (text, evidence) choices.
INSERTION_POINTS: dict[InsertionPoint, InsertionPointSpec] = {
    InsertionPoint.NPC_REPLY: InsertionPointSpec(
        point=InsertionPoint.NPC_REPLY,
        label="NPC reply",
        on_critical_path=True,
        expected_output_tokens=64,
        rationale="Mirror's in-character reaction to the latest choice; player waits on it each loop.",
    ),
    InsertionPoint.BRANCH_CANDIDATE: InsertionPointSpec(
        point=InsertionPoint.BRANCH_CANDIDATE,
        label="Branch candidate",
        on_critical_path=False,
        expected_output_tokens=256,
        rationale="Author the next scene's tailored framing ahead of the player; precomputable and cacheable.",
    ),
}


@dataclass(frozen=True)
class Prompt:
    """One real prompt: a system + user pair tagged with its insertion point.

    ``id`` is a stable, human-readable key (insertion point, persona, slot, loop)
    used both to label samples and to seed the simulated client deterministically,
    so the same corpus produces the same measurements every run.
    """

    id: str
    insertion_point: InsertionPoint
    system: str
    user: str
    expected_output_tokens: int

    @property
    def text(self) -> str:
        """The full prompt text the token estimator counts (system + user)."""
        return f"{self.system}\n\n{self.user}"


# --- Representative personas --------------------------------------------------
# One consistent player per tendency: the choice id of that tendency at each slot
# of DEFAULT_WORLD, in spine order. Walking these produces authentic player-model
# reads (a leaning tally, a dominant tendency) and exercises every branch framing.
# The ids match game.world / game.replay.CANONICAL_INPUT_LOG (the "kind" persona).

PERSONAS: dict[str, tuple[str, ...]] = {
    "kind": ("c_reassure", "c_close", "c_help", "c_wait", "c_accept"),
    "control": ("c_measure", "c_read", "c_map", "c_log", "c_audit"),
    "defiance": ("c_refuse", "c_breach", "c_doors", "c_walk", "c_break"),
}


@dataclass(frozen=True)
class _Step:
    """One loop of a walked persona: the read taken, the scene shown, the choice."""

    persona: str
    loop_index: int
    slot: Slot
    state_before: PlayerState
    scene: Scene  # the framing Slot.pick selected for state_before
    choice: Choice


def _walk(persona: str, log: tuple[str, ...], world: World) -> Iterator[_Step]:
    """Replay a persona through ``world`` with the shipped branch-selection logic.

    Yields one :class:`_Step` per slot, using ``game.world.Slot.pick`` (the real
    across-scene selection) so the framing and the player-model read at each loop
    are exactly what the engine would have produced — making the prompts genuinely
    "real", not reconstructions of a parallel rule.
    """
    state = PlayerState()
    for loop_index, (slot, choice_id) in enumerate(zip(world.slots, log)):
        scene, _branch_key = slot.pick(state)
        choice = scene.choice(choice_id)
        yield _Step(persona, loop_index, slot, state, scene, choice)
        state = state.record(scene, choice)


def _tally(state: PlayerState) -> str:
    """A compact, stable rendering of the player-model tally for a prompt."""
    counts = state.tendency_counts
    if not counts:
        return "no choices yet"
    return ", ".join(f"{tendency}×{count}" for tendency, count in sorted(counts.items()))


# --- The two prompt builders --------------------------------------------------

_NPC_SYSTEM = (
    "You are the Mirror, the lab's adaptive narrator in a text game. In ONE short "
    "in-character line (40 words or fewer), react to the participant's latest "
    "choice. Stay in the lab's calm, clinical voice. Reflect ONLY behavior observed "
    "inside the game; never reference anything from outside it. Do not invent, add, "
    "or remove options, and do not change the rules of the scene."
)

_BRANCH_SYSTEM = (
    "You are the Mirror Lab's narrative-designer agent. Output one JSON content "
    "package for the next scene: a `prompt` of 2-3 sentences and exactly three "
    "`choices`, one each tagged kindness, control, and defiance, each with `text` "
    "and a past-tense `evidence` phrase. Reframe the room toward the participant's "
    "dominant tendency, but preserve the authored choice spine: same three "
    "tendencies, never remove a door. Ground everything in in-game behavior only, "
    "and never alter the engine or its rules."
)


def _npc_prompt(step: _Step) -> Prompt:
    user = (
        f"Scene: {step.scene.prompt}\n"
        f'The participant chose: "{step.choice.text}"\n'
        f"That reads as {step.choice.tendency} ({step.choice.evidence}).\n"
        f"Behavior so far: {_tally(step.state_before)}.\n"
        "Write the Mirror's reply."
    )
    spec = INSERTION_POINTS[InsertionPoint.NPC_REPLY]
    return Prompt(
        id=f"npc_reply:{step.persona}:{step.slot.key}:{step.loop_index}",
        insertion_point=InsertionPoint.NPC_REPLY,
        system=_NPC_SYSTEM,
        user=user,
        expected_output_tokens=spec.expected_output_tokens,
    )


def _branch_prompt(step: _Step) -> Prompt:
    assert step.slot.variants is not None  # only built for branch slots
    spine = step.slot.variants["default"].choices
    dom = dominant_tendency(step.state_before) or "none yet"
    spine_lines = "\n".join(
        f'  - {c.tendency}: "{c.text}"' for c in spine
    )
    user = (
        f"Slot: {step.slot.key}\n"
        f"Dominant tendency: {dom}\n"
        f"Behavior so far: {_tally(step.state_before)}\n"
        f"Neutral framing for reference: {step.slot.variants['default'].prompt}\n"
        "Authored choice spine to preserve (tendency: text):\n"
        f"{spine_lines}\n"
        "Produce the tailored content package as JSON."
    )
    spec = INSERTION_POINTS[InsertionPoint.BRANCH_CANDIDATE]
    return Prompt(
        id=f"branch_candidate:{step.persona}:{step.slot.key}:{step.loop_index}",
        insertion_point=InsertionPoint.BRANCH_CANDIDATE,
        system=_BRANCH_SYSTEM,
        user=user,
        expected_output_tokens=spec.expected_output_tokens,
    )


def build_corpus(
    world: World = DEFAULT_WORLD,
    personas: dict[str, tuple[str, ...]] | None = None,
) -> dict[InsertionPoint, tuple[Prompt, ...]]:
    """Build the real-prompt corpus for every insertion point.

    Walks each persona through ``world`` and emits, per loop, an NPC-reply prompt
    (every loop is on the critical path) and — only at **branch** slots — a
    branch-candidate prompt (the off-path authoring task). Returns the prompts
    grouped by insertion point so the harness can measure each independently.
    """
    personas = personas or PERSONAS
    npc: list[Prompt] = []
    branch: list[Prompt] = []
    for persona, log in personas.items():
        if len(log) != world.length:
            raise ValueError(
                f"persona {persona!r} has {len(log)} choices but world "
                f"{world.name!r} has {world.length} slots"
            )
        for step in _walk(persona, log, world):
            npc.append(_npc_prompt(step))
            if step.slot.variants is not None:
                branch.append(_branch_prompt(step))
    return {
        InsertionPoint.NPC_REPLY: tuple(npc),
        InsertionPoint.BRANCH_CANDIDATE: tuple(branch),
    }


__all__ = [
    "INSERTION_POINTS",
    "PERSONAS",
    "InsertionPoint",
    "InsertionPointSpec",
    "Prompt",
    "build_corpus",
]
