"""The handcrafted world — a small, hand-authored lab the player loops through.

This is the no-LLM stand-in for the design's narrative-designer agent
(``README.md`` "Agent Architecture", ``docs/game_design.md`` §7): instead of
generating scenes live, the Mirror **selects** which pre-authored framing to
reveal next from the player model. That selection is the second way the Mirror
visibly drives content (the first is the locked core-loop re-ordering inside a
scene; see ``loop.core.Mirror.adapt``).

The world is a fixed five-loop spine:

    intake → records → corridor → confrontation → exit

Three of those slots are **branch slots**: the prompt/framing the player reads is
chosen by their dominant tendency so far. Every scene, branch or not, always
offers the same three tendencies (kindness / control / defiance) as real choices,
so:

* the player's agency is never reduced — the Mirror reframes the room, it never
  removes a door (consistent with the locked adaptation only ever re-ordering,
  ``docs/CORE_LOOP.md`` §2), and
* the running tendency tally the Mirror models stays well-defined every turn.

Every path through the world is exactly five loops — inside the 3–5-loop session
target — regardless of how the player plays.
"""

from __future__ import annotations

from dataclasses import dataclass

from loop.core import Choice, PlayerState, Scene

# Fixed priority for breaking dominance ties, so branch selection is fully
# deterministic (no LLM, no randomness): kindness, then control, then defiance.
TENDENCY_PRIORITY = ("kindness", "control", "defiance")


def dominant_tendency(state: PlayerState) -> str | None:
    """The tendency the player leans into most so far, or ``None`` if tied/empty.

    A clear winner returns that tendency; an exact tie at the top (or no history)
    returns ``None`` so the caller falls back to a neutral framing. This is what
    keeps content selection honest: the Mirror only tailors the room once the
    player has actually leaned somewhere.
    """
    counts = state.tendency_counts
    if not counts:
        return None
    ranked = counts.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


@dataclass(frozen=True)
class Slot:
    """One loop's worth of world: either a fixed scene or a branch on tendency."""

    key: str
    fixed: Scene | None = None
    variants: dict[str, Scene] | None = None  # keys: tendencies + "default"

    def pick(self, state: PlayerState) -> tuple[Scene, str]:
        """Return the scene to play this loop and the branch key chosen.

        For a fixed slot the key is ``"fixed"``. For a branch slot it is the
        dominant tendency (when one exists and has a variant) or ``"default"``.
        """
        if self.fixed is not None:
            return self.fixed, "fixed"
        assert self.variants is not None
        dom = dominant_tendency(state)
        if dom is not None and dom in self.variants:
            return self.variants[dom], dom
        return self.variants["default"], "default"


@dataclass(frozen=True)
class World:
    """A fixed-length spine of slots the session runner walks once per loop."""

    name: str
    slots: tuple[Slot, ...]

    @property
    def length(self) -> int:
        return len(self.slots)


# --- Authored content --------------------------------------------------------
# Helper so every scene keeps the same kindness/control/defiance choice spine
# while branch variants only change the prompt the player reads.


def _three(
    scene_id: str,
    prompt: str,
    *,
    kind: tuple[str, str, str],
    control: tuple[str, str, str],
    defy: tuple[str, str, str],
) -> Scene:
    """Build a scene whose three choices are (text, id, evidence) per tendency."""
    k_text, k_id, k_ev = kind
    c_text, c_id, c_ev = control
    d_text, d_id, d_ev = defy
    return Scene(
        id=scene_id,
        prompt=prompt,
        choices=(
            Choice(k_id, k_text, "kindness", k_ev),
            Choice(c_id, c_text, "control", c_ev),
            Choice(d_id, d_text, "defiance", d_ev),
        ),
    )


# Loop 1 — INTAKE (fixed). Establishes the three tendencies on equal footing.
INTAKE = _three(
    "intake",
    "The Mirror Lab's intake room is warm and spotless. A technician fits the "
    "headset to your head; her hands are shaking.",
    kind=("Tell her to take her time — you are in no hurry.",
          "c_reassure", "reassured the technician at intake"),
    control=("Ask exactly what the headset records, and where it goes.",
             "c_measure", "interrogated the headset's purpose at intake"),
    defy=("Keep the headset off until someone explains how to leave.",
          "c_refuse", "refused the headset until told the way out"),
)

# Loop 2 — RECORDS (branch). Same dilemma, framed by the player's first lean.
_RECORDS_KIND = ("Close the file. It isn't yours to read.",
                 "c_close", "left another participant's file closed")
_RECORDS_CONTROL = ("Read it top to bottom and memorise the fields.",
                    "c_read", "read another participant's file in full")
_RECORDS_DEFY = ("Flag the open file as a breach and demand the session halt.",
                 "c_breach", "reported the open file as a breach")


def _records(prompt: str) -> Scene:
    return _three("records", prompt, kind=_RECORDS_KIND, control=_RECORDS_CONTROL, defy=_RECORDS_DEFY)


RECORDS = Slot(
    "records",
    variants={
        "kindness": _records(
            "The Mirror dims the lights to a kinder warmth. A console sits "
            "unlocked on another participant's unfinished file."),
        "control": _records(
            "The Mirror surfaces a metrics overlay you never asked for. A console "
            "sits unlocked on another participant's file, every field exposed."),
        "defiance": _records(
            "A door clicks locked somewhere behind you. A console sits unlocked on "
            "another participant's file."),
        "default": _records(
            "A console sits unlocked, mid-session, on another participant's file."),
    },
)

# Loop 3 — CORRIDOR (branch).
_CORR_KIND = ("Walk them to the waiting room yourself.",
              "c_help", "guided a disoriented participant to safety")
_CORR_CONTROL = ("Catalogue the corridor's exits and cameras instead.",
                 "c_map", "catalogued the corridor's exits and cameras")
_CORR_DEFY = ("Try the one unlocked door, looking for a way out.",
              "c_doors", "tried the corridor doors for a way out")


def _corridor(prompt: str) -> Scene:
    return _three("corridor", prompt, kind=_CORR_KIND, control=_CORR_CONTROL, defy=_CORR_DEFY)


CORRIDOR = Slot(
    "corridor",
    variants={
        "kindness": _corridor(
            "The Mirror plays something soft over the speakers. A disoriented "
            "participant stands in the corridor, unsure which way is out."),
        "control": _corridor(
            "The exit signs reroute as you watch. A disoriented participant stands "
            "in the corridor, unsure which way is out."),
        "defiance": _corridor(
            "Every corridor door reads LOCKED but one. A disoriented participant "
            "stands in the corridor, unsure which way is out."),
        "default": _corridor(
            "A disoriented participant stands in the corridor, unsure which way is out."),
    },
)

# Loop 4 — CONFRONTATION (fixed). Built with an explicit declared order —
# defiance, control, *kindness last* — on purpose (not via ``_three``, which
# always lists kindness first). This is the one scene that declares the kind
# option last, so the core loop's re-ordering is visibly demonstrated for a kind
# player: the Mirror lifts their option from last to first.
CONFRONTATION = Scene(
    id="confrontation",
    prompt=(
        "An incident alarm sounds. The same participant freezes beside a door "
        "marked EXIT — and it is unlocked."
    ),
    choices=(
        Choice("c_walk", "Walk out through the unlocked exit and don't look back.",
               "defiance", "walked out through the unlocked exit"),
        Choice("c_log", "Take the clipboard and log the incident precisely.",
               "control", "logged the incident on the clipboard"),
        Choice("c_wait", "Stay with the participant until staff arrive.",
               "kindness", "stayed with the participant until staff arrived"),
    ),
)

# Loop 5 — EXIT (branch): the reveal. The Mirror offers a conclusion tailored to
# the model it built — the strongest "mirror drives content" beat in the session.
_EXIT_KIND = ("Accept the gentle conclusion the Mirror prepared for you.",
              "c_accept", "accepted the Mirror's prepared conclusion")
_EXIT_CONTROL = ("Demand to read the model the Mirror built of you.",
                 "c_audit", "audited the Mirror's model of you")
_EXIT_DEFY = ("Refuse the script and do the opposite of what it expects.",
              "c_break", "refused the Mirror's prepared script")


def _exit(prompt: str) -> Scene:
    return _three("exit", prompt, kind=_EXIT_KIND, control=_EXIT_CONTROL, defy=_EXIT_DEFY)


EXIT = Slot(
    "exit",
    variants={
        "kindness": _exit(
            "The Mirror lowers its voice. 'You cared, consistently. We have "
            "prepared a gentle conclusion.' A soft-lit door opens."),
        "control": _exit(
            "The Mirror presents a briefing. 'You measured everything. Here is "
            "your file, and the door.'"),
        "defiance": _exit(
            "The Mirror offers a locked door and a dare. 'You pushed at every "
            "edge. Prove you are not predictable.'"),
        "default": _exit(
            "The Mirror offers an exit calibrated to no one in particular."),
    },
)


DEFAULT_WORLD = World(
    name="mirror-lab",
    slots=(
        Slot("intake", fixed=INTAKE),
        RECORDS,
        CORRIDOR,
        Slot("confrontation", fixed=CONFRONTATION),
        EXIT,
    ),
)


# --- The world registry ------------------------------------------------------
# A persisted session stores only its world's *name* (the spine itself is code,
# not data). On reload it resolves the name back to the authored ``World`` here.
# v0 ships exactly one world; :func:`get_world` refuses any other name so a
# session recorded against a spine this build does not have fails loudly rather
# than silently mis-restoring against the wrong world.
WORLDS: dict[str, World] = {DEFAULT_WORLD.name: DEFAULT_WORLD}


def get_world(name: str) -> World:
    """Resolve a registered world by :attr:`World.name`.

    Raises ``ValueError`` for an unknown name (the same fail-loud posture the
    schema-version guards take, ``docs/SCHEMAS.md`` §5).
    """
    try:
        return WORLDS[name]
    except KeyError:
        known = ", ".join(sorted(WORLDS)) or "(none registered)"
        raise ValueError(
            f"unknown world {name!r}; known worlds: {known}"
        ) from None
