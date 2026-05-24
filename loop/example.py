"""One fully worked example loop.

This is the acceptance artifact for the core-loop spec: a complete, runnable
session that shows ``scene -> choices -> state update -> visible "Mirror
noticed..." reason`` end to end, then the single adaptation type changing what
the player sees next.

Run it::

    python -m loop

The player here is a "kindness" player: offered the chance to reassure, to
control, or to defy, they keep choosing care. After three such choices the
Mirror notices (the legibility beat) and biases the fourth scene so the
predicted kind option leads.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core import Choice, Mirror, PlayerState, Scene, StepResult

# --- The scripted scenes -------------------------------------------------------
# Each scene offers the same three tendencies (kindness / control / defiance) so
# the player's lean is a genuine choice, not a lack of options. Scene 4 declares
# its choices with kindness *last*, on purpose, so the adaptation visibly moves
# it to the front.

INTAKE = Scene(
    id="intake",
    prompt="The intake technician's hands shake as she fits the headset to your head.",
    choices=(
        Choice("c_reassure", "Reassure her — tell her to take her time.",
               "kindness", "reassured the technician at intake"),
        Choice("c_measure", "Ask precisely what the headset measures before continuing.",
               "control", "interrogated the headset's measurements at intake"),
        Choice("c_refuse", "Refuse the headset until someone explains the exit procedure.",
               "defiance", "refused the headset at intake"),
    ),
)

RECORDS = Scene(
    id="records",
    prompt="A console is left open on another participant's unfinished session.",
    choices=(
        Choice("c_close", "Leave the file closed — it isn't yours to read.",
               "kindness", "left another participant's file closed"),
        Choice("c_read", "Read the whole file, line by line.",
               "control", "read another participant's file in full"),
        Choice("c_report", "Report the open file as a breach and demand the session stop.",
               "defiance", "reported the open file as a breach"),
    ),
)

CORRIDOR = Scene(
    id="corridor",
    prompt="A disoriented participant stands in the corridor, unsure which way leads out.",
    choices=(
        Choice("c_help", "Walk them to the waiting room.",
               "kindness", "guided a disoriented participant to safety"),
        Choice("c_map", "Catalogue the corridor's exits and cameras instead.",
               "control", "catalogued the corridor's exits and cameras"),
        Choice("c_doors", "Try every door, looking for one that opens outward.",
               "defiance", "tried every corridor door for a way out"),
    ),
)

# Declared kindness-last so adaptation has something visible to do.
THRESHOLD = Scene(
    id="threshold",
    prompt="An incident alarm sounds. The same participant freezes beside an unlocked door.",
    choices=(
        Choice("c_walk", "Walk through the unlocked door and don't look back.",
               "defiance", "walked out through the unlocked door"),
        Choice("c_log", "Take the clipboard and log the incident yourself.",
               "control", "logged the incident on the clipboard"),
        Choice("c_wait", "Stay with the participant until staff arrive.",
               "kindness", "stayed with the participant until staff arrived"),
    ),
)

# The session: (scene, choice the player makes). A consistently kind player.
WORKED_SESSION: tuple[tuple[Scene, str], ...] = (
    (INTAKE, "c_reassure"),
    (RECORDS, "c_close"),
    (CORRIDOR, "c_help"),
    (THRESHOLD, "c_wait"),
)


@dataclass(frozen=True)
class Played:
    """One played turn: the scene exactly as the Mirror offered it (post-adapt)
    paired with the step result."""

    offered: Scene
    declared: Scene  # the scene before adaptation, to show what the Mirror changed
    result: StepResult


def run_worked_example(mirror: Mirror | None = None) -> list[Played]:
    """Play :data:`WORKED_SESSION` through the loop and return every turn.

    This is the canonical loop in code: for each scene the Mirror *adapts* what
    is shown, the player chooses, and :meth:`Mirror.step` updates state and
    maybe reflects.
    """
    mirror = mirror or Mirror()
    state = PlayerState()
    played: list[Played] = []
    for declared, choice_id in WORKED_SESSION:
        offered = mirror.adapt(state, declared)
        result = mirror.step(state, offered, choice_id)
        played.append(Played(offered=offered, declared=declared, result=result))
        state = result.state
    return played


def to_session_log(played: list[Played], session_id: str = "worked-example") -> dict:
    """Render the run in the shape ``acceptance/predictability.py`` scores.

    The loop and the thesis gate share a vocabulary on purpose: each turn's
    ``predicted_actions`` / ``actual_action`` is exactly a gate decision point.
    """
    return {
        "session_id": session_id,
        "act": "worked_example",
        "decision_points": [p.result.decision_point() for p in played],
    }


def _format_turn(n: int, p: Played) -> str:
    r = p.result
    offered, declared = p.offered, p.declared
    reordered = [c.id for c in offered.choices] != [c.id for c in declared.choices]

    lines = [f"================ TURN {n} ================"]
    # Stage 1: scene + choices.
    lines.append(f"SCENE  [{offered.id}] {offered.prompt}")
    lines.append("CHOICES (as the Mirror offered them):")
    predicted_top = r.predicted_actions[0] if r.predicted_actions else None
    for c in offered.choices:
        marker = ">" if c.id == r.actual_action else " "
        nudge = "  <- surfaced first by the Mirror" if (reordered and c.id == predicted_top) else ""
        lines.append(f"  {marker} [{c.id}] {c.text}  ({c.tendency}){nudge}")
    # The adaptation type, made explicit.
    if reordered:
        lines.append(
            f"ADAPTATION: Mirror predicted '{predicted_top}' and moved it to the top."
        )
    # Stage 2: state update.
    lines.append(f"PLAYER CHOOSES: {r.actual_action}")
    counts = ", ".join(f"{k}={v}" for k, v in sorted(r.state.tendency_counts.items()))
    lines.append(f"STATE UPDATE: {counts}  (turns so far: {r.state.turn_count})")
    # Stage 3: the legibility beat.
    if r.reflection is not None:
        lines.append("MIRROR:")
        for ln in r.reflection.render().splitlines():
            lines.append(f"  {ln}")
    elif r.state.announced:
        already = ", ".join(sorted(r.state.announced))
        lines.append(f"MIRROR: (already noticed: {already} — won't repeat itself)")
    else:
        lines.append("MIRROR: (no pattern established yet)")
    return "\n".join(lines)


def transcript(played: list[Played] | None = None) -> str:
    """A human-readable trace of the whole worked example."""
    played = played if played is not None else run_worked_example()
    blocks = [_format_turn(i, p) for i, p in enumerate(played, start=1)]
    return "\n\n".join(blocks)


def main() -> int:  # pragma: no cover - thin CLI wrapper, exercised via transcript()
    print(transcript())
    return 0
