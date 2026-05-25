"""Templated adaptations — the Mirror's visible voice, with no LLM.

The locked core loop (``loop.core``) ships exactly one *mechanical* adaptation:
tendency-mirroring re-ordering of a scene's choices (``docs/CORE_LOOP.md`` §2).
This module is the *content* layer that sits on top of it: the system messages
the Mirror speaks each loop and the closing report it renders. The full design
imagines these lines being authored live by a narrative-designer LLM agent
(``README.md`` "Agent Architecture"); here they are **handcrafted templates that
the player model fills in deterministically** — the no-LLM stand-in for that
agent.

Every line the Mirror says is therefore:

* **templated** — a fixed authored string with ``{slots}`` the player model fills,
* **driven by observed in-game behaviour only** — the dominant tendency, its
  count, whether a pattern was confirmed, whether the last prediction hit — never
  anything outside the game (the fiction boundary, ``docs/CORE_LOOP.md`` §3), and
* **escalating** — the four stages mirror the design's "Creepy Personalization"
  ladder (``docs/game_design.md`` §11.1): Calibration → Observation → Prediction
  → Confrontation.
"""

from __future__ import annotations

from dataclasses import dataclass

# Per-tendency flavour the Mirror quotes once it has a read on the player. These
# are lifted in spirit from docs/game_design.md §11.2 ("You prefer kindness when
# it costs nothing…") — pre-authored, in-fiction observations of *play*, never of
# the real person.
TENDENCY_FLAVOR: dict[str, str] = {
    "kindness": "You prefer kindness when it costs nothing. We are testing when that changes.",
    "control": "You catalogue what you cannot command. Certainty is the comfort you reach for.",
    "defiance": "You reach for the exit before you have read the room. Resistance, noted.",
}

# The escalation ladder (docs/game_design.md §11.1). Stage is selected by how
# much the Mirror has learned, not by the loop number, so a player who stays
# unreadable never escalates past Observation.
STAGE_TITLES: dict[int, str] = {
    1: "CALIBRATION",
    2: "OBSERVATION",
    3: "PREDICTION",
    4: "CONFRONTATION",
}


@dataclass(frozen=True)
class SystemMessage:
    """One templated line in the Mirror's diegetic system voice."""

    stage: int
    body: str

    @property
    def title(self) -> str:
        return STAGE_TITLES[self.stage]

    def render(self) -> str:
        return f"MIRROR // {self.title}: {self.body}"


def _flavor(tendency: str) -> str:
    return TENDENCY_FLAVOR.get(tendency, "Your pattern is still forming.")


def adapt_message(
    *,
    dominant: str,
    dominant_count: int,
    total: int,
    just_noticed: bool,
    model_locked: bool,
    predicted_hit: bool,
    is_finale: bool,
) -> SystemMessage:
    """Render the Mirror's line for one loop from the (post-choice) player model.

    Stage selection — the escalation contract:

    * **1 CALIBRATION** — the Mirror has nothing to say yet (the first moment).
    * **2 OBSERVATION** — a lean exists but no pattern is confirmed; it merely
      reports the tally (``docs/game_design.md`` §11.1 stage 2).
    * **3 PREDICTION** — a pattern has been confirmed (the reflection beat fired).
      The Mirror now claims foresight, and — crucially — if the player's last
      choice *broke* the prediction it says so, which is the escape mechanic's
      first visible appearance (``docs/game_design.md`` §12).
    * **4 CONFRONTATION** — the finale, once the model is locked: the Mirror
      shows its confidence back to the player (``docs/game_design.md`` §11.1
      stage 6) and reframes the exit as engagement.
    """
    percent = round(100 * dominant_count / total) if total else 0
    flavor = _flavor(dominant)

    if is_finale and model_locked:
        body = (
            f"Predictability index: {percent}%. {flavor} "
            "You are not trapped. You are engaged beyond your anticipated threshold."
        )
        return SystemMessage(stage=4, body=body)

    if just_noticed:
        body = f"Pattern confirmed: {dominant}. {flavor}"
        return SystemMessage(stage=3, body=body)

    if model_locked:
        if predicted_hit:
            body = f"As predicted: {dominant} again. {flavor}"
        else:
            body = (
                f"Unanticipated. Recalibrating around your {dominant} drift — "
                "randomness is a known strategy. Yours is not random yet."
            )
        return SystemMessage(stage=3, body=body)

    if total >= 2:
        body = f"Observation logged: you chose {dominant} in {dominant_count} of {total} moments."
        return SystemMessage(stage=2, body=body)

    return SystemMessage(
        stage=1,
        body="Your experience has been calibrated to your stated preferences. Proceed when ready.",
    )


# --- Closing report ----------------------------------------------------------
# A diegetic render of the same number the locked acceptance gate scores: how
# often the Mirror's top prediction matched the player. Low accuracy reads, in
# fiction, as the player slipping the model (docs/game_design.md §11.1 stage 6,
# §12) — the thesis (docs/THESIS.md §1) made visible at the table.


def _band(accuracy: float) -> tuple[str, str]:
    """(model-confidence, agency-drift) bands from top-1 accuracy."""
    if accuracy >= 0.60:
        return "HIGH", "LOW"
    if accuracy >= 0.40:
        return "MODERATE", "ELEVATED"
    return "LOW", "HIGH"


def final_report(*, hits: int, total: int, accuracy: float, dominant: str) -> str:
    """The Mirror's closing diegetic readout of how predictable the player was."""
    percent = round(100 * accuracy)
    confidence, drift = _band(accuracy)
    escape = "improbable" if accuracy >= 0.60 else "plausible" if accuracy >= 0.40 else "open"
    verdict = (
        f"The Mirror anticipated {hits} of {total} of your choices. {_flavor(dominant)}"
        if accuracy >= 0.40
        else (
            f"The Mirror anticipated only {hits} of {total} of your choices. "
            "You were harder to predict than you were sold as being."
        )
    )
    return (
        "==================  MIRROR // FINAL READOUT  ==================\n"
        f"  PREDICTABILITY INDEX : {percent}%\n"
        f"  MODEL CONFIDENCE     : {confidence}\n"
        f"  AGENCY DRIFT         : {drift}\n"
        f"  ESCAPE               : {escape}\n"
        f"  {verdict}"
    )
