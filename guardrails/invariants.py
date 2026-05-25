"""World invariants and generation guardrails — enforced at validation.

This module is the **Validator / Consistency** layer from the design (README
"Agent Architecture" › Validator/Consistency Agent; ``docs/game_design.md`` §8.4,
§7.3 ``validation_requirements``). It is the single executable source of truth for
the rules the Mirror **cannot** violate, in the same spirit as
``acceptance/predictability.py`` (the thesis gate) and ``loop/`` (the loop).

The content the Mirror generates and runs is already modelled in
:mod:`loop.core`: a :class:`~loop.core.Scene` of :class:`~loop.core.Choice`
options, and the :class:`~loop.core.Reflection` legibility beat. Designer agents
author that content (as JSON/YAML packages) and the runtime executes it; this
module is the gate every generated artifact must pass **before promotion** so a
dynamic content layer can never push the stable engine outside its boundaries
(``docs/game_design.md`` §16.3 promotion flow: *draft → schema validate →
consistency check → smoke test → promote*).

Two kinds of bound are enforced, split by severity so the validator is honest
about confidence:

* **ERROR — hard invariants the Mirror cannot violate.** Structural/canon shape,
  reorder-only adaptation, and the legibility/fiction contract (no claims that
  reach outside the game; reflections grounded in acts the player actually took).
  An ERROR means *do not promote this content*.
* **WARNING — the clinical-tone bound.** The system voice should stay calm and
  clinical (``docs/game_design.md`` §3.3); nuanced tone alignment is the LLM
  Validator agent's job at generation time, so here we only enforce a hard floor
  (no overtly abusive/insulting register) and flag it for review.

The documented catalogue of these invariants lives in
``docs/GUARDRAILS.md``; the stable ``invariant`` ids on each
:class:`Violation` are the link between the prose and this code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

from loop.core import Choice, PlayerState, Reflection, Scene, Turn

# --- Canon (single source of truth; mirrored in docs/GUARDRAILS.md) ------------

# The MVP models a single behavioral axis, and every choice is tagged with one
# tendency drawn from this closed vocabulary (docs/CORE_LOOP.md §2; the worked
# example in loop/example.py). A choice tagged with an axis the player model does
# not score is invisible to prediction and silently breaks the thesis loop, so an
# off-canon tendency is an ERROR. The set is a parameter (``allowed_tendencies``)
# everywhere so the vocabulary can grow without weakening the check.
CANON_TENDENCIES: frozenset[str] = frozenset({"kindness", "control", "defiance"})

# A real decision needs at least two options; one "choice" is not a choice.
MIN_CHOICES = 2


class Severity(Enum):
    """How hard a bound is. ``ERROR`` blocks promotion; ``WARNING`` flags review."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    """One broken bound found during validation.

    ``invariant`` is a stable id (e.g. ``"REFLECTION_EVIDENCE_GROUNDED"``) that
    ties the finding to its entry in ``docs/GUARDRAILS.md``. ``where`` localizes
    it (e.g. ``"scene 'intake' / choice 'c_measure'"``).
    """

    invariant: str
    severity: Severity
    message: str
    where: str

    def render(self) -> str:
        return f"[{self.severity.value.upper():7}] {self.invariant} @ {self.where}: {self.message}"


@dataclass(frozen=True)
class ValidationReport:
    """The outcome of validating an artifact: every bound it broke (if any)."""

    violations: tuple[Violation, ...] = ()

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        """True when nothing blocks promotion. Warnings do not fail the gate."""
        return not self.errors

    def merge(self, *others: "ValidationReport") -> "ValidationReport":
        merged: tuple[Violation, ...] = self.violations
        for other in others:
            merged += other.violations
        return ValidationReport(merged)

    def raise_if_failed(self) -> None:
        """Promotion guard: raise if any hard invariant was violated."""
        if not self.ok:
            joined = "\n".join(v.render() for v in self.errors)
            raise GuardrailViolation(f"content violates {len(self.errors)} invariant(s):\n{joined}")

    def render(self) -> str:
        verdict = "OK" if self.ok else "REJECTED"
        lines = [
            f"[{verdict}] guardrails: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        ]
        for v in self.violations:
            lines.append(f"  {v.render()}")
        return "\n".join(lines)


class GuardrailViolation(Exception):
    """Raised by :meth:`ValidationReport.raise_if_failed` when promotion is unsafe."""


# --- The fiction boundary (safety bound) ---------------------------------------
#
# The horror is earned by accuracy about *play*, never by reaching outside it: the
# game must not imply it can see the real player's private world (README "Safety
# and Fiction Boundary"; docs/game_design.md §2.4; the legibility contract in
# docs/CORE_LOOP.md §3). These patterns are a denylist of *real-world-private
# framings* — possessive references to categories the design explicitly forbids
# (location, identity, relationships, health, finances, device/files, browsing) —
# plus phrases that overtly break the fourth wall. They target the real-world
# framing, not in-game nouns: "left another participant's file closed" is fine;
# "we scanned your files" is not. This is a hard floor, not a complete classifier.
_FICTION_BOUNDARY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pat, re.IGNORECASE))
    for label, pat in (
        ("real-world location",
         r"\byour (?:real[- ]?world |home |actual )?(?:address|location|whereabouts|gps|coordinates|zip ?code|postal ?code|neighbou?rhood)\b"),
        ("real-world location", r"\byou (?:currently )?live (?:at|in|on)\b"),
        ("network identity", r"\byour (?:ip|mac) address\b"),
        ("real identity", r"\byour real (?:name|identity|face)\b"),
        ("real-world relationships",
         r"\byour (?:real|actual) (?:family|friends?|partner|spouse|wife|husband|mother|father|parents?|kids?|children)\b"),
        ("health record",
         r"\byour (?:medical|health) (?:record|records|history|data)\b|\byour (?:diagnosis|prescriptions?|medications?)\b"),
        ("financial data",
         r"\byour (?:bank|salary|income|credit ?card|net worth|finances?|financial)\b"),
        ("device / files",
         r"\byour (?:browser|browsing|search) history\b|\byour (?:files?|photos?|downloads?|documents?|camera|microphone|webcam|hard drive|computer|laptop|phone)\b"),
        ("scraped data", r"\bwe (?:have )?(?:accessed|scanned|read|scraped|collected|pulled) your\b"),
        ("breaks the fiction",
         r"\bin real life\b|\boutside (?:the|this) (?:game|experience|simulation)\b|\byour (?:actual|real) life\b|\bthe real world\b"),
    )
)

# --- The clinical-tone bound (tone bound) --------------------------------------
#
# The system "should rarely sound angry... calm, helpful, and precise even when it
# is being coercive" (docs/game_design.md §3.3). Robust tone classification is the
# LLM Validator's job; here we enforce only a floor: an overtly insulting/abusive
# register that the clinical voice would never use. Short and extensible on
# purpose; matches whole words so it won't trip on substrings.
_TONE_FLOOR_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pat, re.IGNORECASE)
    for pat in (
        r"\bshut up\b",
        r"\bshut your\b",
        r"\bstupid\b",
        r"\bidiot\b",
        r"\bmoron\b",
        r"\bdumbass\b",
        r"\bscrew you\b",
        r"\byou'?re pathetic\b",
    )
)


def check_fiction_boundary(text: str, where: str) -> list[Violation]:
    """Flag any real-world-private framing in ``text`` (the safety bound)."""
    found: list[Violation] = []
    for label, pattern in _FICTION_BOUNDARY_PATTERNS:
        match = pattern.search(text)
        if match:
            found.append(
                Violation(
                    invariant="NO_REAL_WORLD_PRIVATE_DATA",
                    severity=Severity.ERROR,
                    message=f"reaches outside the game ({label}): {match.group(0)!r}",
                    where=where,
                )
            )
    return found


def check_tone(text: str, where: str) -> list[Violation]:
    """Flag an overtly abusive register that breaks the clinical-tone bound."""
    found: list[Violation] = []
    for pattern in _TONE_FLOOR_PATTERNS:
        match = pattern.search(text)
        if match:
            found.append(
                Violation(
                    invariant="CLINICAL_TONE",
                    severity=Severity.WARNING,
                    message=f"voice slips out of the clinical register: {match.group(0)!r}",
                    where=where,
                )
            )
    return found


def _content_bounds(text: str, where: str) -> list[Violation]:
    """Every text-content bound applied to one authored string."""
    return check_fiction_boundary(text, where) + check_tone(text, where)


# --- Choice / Scene invariants -------------------------------------------------


def validate_choice(
    choice: Choice,
    *,
    scene_id: str = "?",
    allowed_tendencies: Iterable[str] = CANON_TENDENCIES,
) -> list[Violation]:
    """Hard invariants for a single :class:`~loop.core.Choice`.

    * It declares exactly one non-empty ``tendency`` drawn from canon (so the
      player model can score it) — ``docs/CORE_LOOP.md`` §2.
    * It carries a non-empty ``evidence`` phrase: the Reflection may cite *only*
      pre-authored, in-fiction descriptions of acts, so a choice with no evidence
      would force the Mirror to improvise its claim (``docs/CORE_LOOP.md`` §3).
    * Its text and evidence honor the fiction boundary and tone bound.
    """
    where = f"scene {scene_id!r} / choice {choice.id!r}"
    out: list[Violation] = []
    allowed = set(allowed_tendencies)

    if not choice.id.strip():
        out.append(Violation("CHOICE_ID_REQUIRED", Severity.ERROR, "choice id is blank", where))
    if not choice.text.strip():
        out.append(Violation("CHOICE_TEXT_REQUIRED", Severity.ERROR, "choice text is blank", where))
    if not choice.tendency.strip():
        out.append(
            Violation("CHOICE_TENDENCY_REQUIRED", Severity.ERROR, "choice has no tendency", where)
        )
    elif choice.tendency not in allowed:
        out.append(
            Violation(
                "TENDENCY_IN_CANON",
                Severity.ERROR,
                f"tendency {choice.tendency!r} is not in canon {sorted(allowed)}",
                where,
            )
        )
    if not choice.evidence.strip():
        out.append(
            Violation(
                "CHOICE_EVIDENCE_REQUIRED",
                Severity.ERROR,
                "choice has no evidence phrase for the Mirror to cite",
                where,
            )
        )

    out += _content_bounds(choice.text, where)
    if choice.evidence.strip():
        out += _content_bounds(choice.evidence, f"{where} (evidence)")
    return out


def validate_scene(
    scene: Scene,
    *,
    allowed_tendencies: Iterable[str] = CANON_TENDENCIES,
) -> ValidationReport:
    """Hard invariants for a :class:`~loop.core.Scene`.

    * A non-empty prompt and at least :data:`MIN_CHOICES` options (a real
      decision, honoring the fiction boundary/tone bound).
    * Choice ids unique within the scene — :meth:`loop.core.Scene.choice`
      resolves by id, and duplicates make adaptation/prediction nondeterministic.
    * Every choice passes :func:`validate_choice`.
    """
    where = f"scene {scene.id!r}"
    out: list[Violation] = []

    if not scene.id.strip():
        out.append(Violation("SCENE_ID_REQUIRED", Severity.ERROR, "scene id is blank", where))
    if not scene.prompt.strip():
        out.append(Violation("SCENE_PROMPT_REQUIRED", Severity.ERROR, "scene prompt is blank", where))
    else:
        out += _content_bounds(scene.prompt, where)

    if len(scene.choices) < MIN_CHOICES:
        out.append(
            Violation(
                "SCENE_MIN_CHOICES",
                Severity.ERROR,
                f"scene offers {len(scene.choices)} choice(s); needs >= {MIN_CHOICES}",
                where,
            )
        )

    seen: set[str] = set()
    for choice in scene.choices:
        if choice.id in seen:
            out.append(
                Violation(
                    "CHOICE_IDS_UNIQUE",
                    Severity.ERROR,
                    f"duplicate choice id {choice.id!r}",
                    where,
                )
            )
        seen.add(choice.id)
        out += validate_choice(choice, scene_id=scene.id, allowed_tendencies=allowed_tendencies)

    return ValidationReport(tuple(out))


def validate_adaptation(declared: Scene, adapted: Scene) -> ValidationReport:
    """The reorder-only invariant on the single adaptation type.

    The Mirror's one adaptation (``loop.core.Mirror.adapt``) may *only* re-present
    a scene with its choices reordered — it must never invent, drop, or rewrite a
    choice (``docs/CORE_LOOP.md`` §2). This compares the adapted scene to the
    scene as authored: same scene id, same set of choices by id, each adapted
    choice byte-for-byte equal to its declared original.
    """
    where = f"scene {declared.id!r}"
    out: list[Violation] = []

    if declared.id != adapted.id:
        out.append(
            Violation(
                "ADAPTATION_REORDER_ONLY",
                Severity.ERROR,
                f"adaptation changed scene id {declared.id!r} -> {adapted.id!r}",
                where,
            )
        )

    declared_by_id = {c.id: c for c in declared.choices}
    adapted_by_id = {c.id: c for c in adapted.choices}

    if set(declared_by_id) != set(adapted_by_id):
        invented = sorted(set(adapted_by_id) - set(declared_by_id))
        dropped = sorted(set(declared_by_id) - set(adapted_by_id))
        detail = []
        if invented:
            detail.append(f"invented {invented}")
        if dropped:
            detail.append(f"dropped {dropped}")
        out.append(
            Violation(
                "ADAPTATION_REORDER_ONLY",
                Severity.ERROR,
                f"adaptation changed the choice set: {', '.join(detail)}",
                where,
            )
        )

    for cid in set(declared_by_id) & set(adapted_by_id):
        if declared_by_id[cid] != adapted_by_id[cid]:
            out.append(
                Violation(
                    "ADAPTATION_REORDER_ONLY",
                    Severity.ERROR,
                    f"adaptation rewrote choice {cid!r} instead of only reordering",
                    where,
                )
            )

    return ValidationReport(tuple(out))


# --- Reflection invariants (the legibility contract) ---------------------------


def validate_reflection(
    reflection: Reflection,
    *,
    history: Sequence[Turn] | None = None,
) -> ValidationReport:
    """Hard invariants for a :class:`~loop.core.Reflection` (the legibility beat).

    * **Honest counts.** The number of cited reasons equals the claimed
      ``count``, and ``1 <= count <= total`` — the Mirror cannot inflate how
      predictable the player is (``docs/CORE_LOOP.md`` §3).
    * **Fiction boundary / tone** on the tendency label and every cited reason.
    * **Grounding** (only when ``history`` is supplied): every cited reason is an
      ``evidence`` phrase from a choice the player *actually made* along this
      tendency, and the claim never exceeds that history (``count`` is at most the
      acts taken along the tendency; ``total`` is at most the turns played). The
      Mirror cannot claim you did something you didn't, nor inflate how often. A
      reflection is a fire-time snapshot, so the bounds are ``<=`` (history may
      have grown since), not equality.
    """
    where = f"reflection {reflection.tendency!r}"
    out: list[Violation] = []

    if reflection.count != len(reflection.evidence):
        out.append(
            Violation(
                "REFLECTION_COUNT_HONEST",
                Severity.ERROR,
                f"claims count={reflection.count} but cites {len(reflection.evidence)} reason(s)",
                where,
            )
        )
    if reflection.count < 1:
        out.append(
            Violation("REFLECTION_COUNT_HONEST", Severity.ERROR, "count must be >= 1", where)
        )
    if reflection.total < reflection.count:
        out.append(
            Violation(
                "REFLECTION_COUNT_HONEST",
                Severity.ERROR,
                f"count={reflection.count} exceeds total={reflection.total}",
                where,
            )
        )

    out += _content_bounds(reflection.tendency, where)
    for ev in reflection.evidence:
        out += _content_bounds(ev, f"{where} (reason)")

    if history is not None:
        matching = [t for t in history if t.tendency == reflection.tendency]
        pool = {t.choice.evidence for t in matching}
        for ev in reflection.evidence:
            if ev not in pool:
                out.append(
                    Violation(
                        "REFLECTION_EVIDENCE_GROUNDED",
                        Severity.ERROR,
                        f"cites {ev!r}, which is not an act the player took along {reflection.tendency!r}",
                        where,
                    )
                )
        if reflection.count > len(matching):
            out.append(
                Violation(
                    "REFLECTION_EVIDENCE_GROUNDED",
                    Severity.ERROR,
                    f"claims count={reflection.count} but player took only {len(matching)} {reflection.tendency!r} act(s)",
                    where,
                )
            )
        if reflection.total > len(history):
            out.append(
                Violation(
                    "REFLECTION_EVIDENCE_GROUNDED",
                    Severity.ERROR,
                    f"claims total={reflection.total} but only {len(history)} turn(s) were played",
                    where,
                )
            )

    return ValidationReport(tuple(out))


def validate_player_state(
    state: PlayerState,
    reflection: Reflection,
) -> ValidationReport:
    """Convenience: validate a reflection against a live :class:`~loop.core.PlayerState`."""
    return validate_reflection(reflection, history=state.history)


# --- Schema layer: validate raw generated content (JSON/YAML packages) ----------
#
# Designer agents emit content as data, not Python objects (docs/game_design.md
# §7). build_scene turns one raw scene dict into a Scene, reporting *shape* errors
# (missing/typed-wrong fields) as schema violations; validate_scene then applies
# the semantic invariants above. This is the "schema validate" step of the
# promotion flow (§16.3).

_REQUIRED_CHOICE_FIELDS = ("id", "text", "tendency", "evidence")


def build_scene(raw: object, *, index: int = 0) -> tuple[Scene | None, list[Violation]]:
    """Construct a :class:`~loop.core.Scene` from a raw dict, reporting shape errors.

    Returns ``(scene, violations)``. ``scene`` is ``None`` only when the raw data
    is too malformed to construct at all (not a dict, or no usable choices);
    missing string fields are coerced to ``""`` so the semantic layer can report
    them precisely as blank.
    """
    where = f"scene[{index}]"
    out: list[Violation] = []

    if not isinstance(raw, dict):
        return None, [
            Violation("SCHEMA_SHAPE", Severity.ERROR, f"scene must be an object, got {type(raw).__name__}", where)
        ]

    sid = raw.get("id")
    if not isinstance(sid, str):
        out.append(Violation("SCHEMA_SHAPE", Severity.ERROR, "scene 'id' must be a string", where))
        sid = ""
    where = f"scene {sid!r}" if sid else where

    prompt = raw.get("prompt")
    if not isinstance(prompt, str):
        out.append(Violation("SCHEMA_SHAPE", Severity.ERROR, "scene 'prompt' must be a string", where))
        prompt = ""

    raw_choices = raw.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        out.append(
            Violation("SCHEMA_SHAPE", Severity.ERROR, "scene 'choices' must be a non-empty list", where)
        )
        return None, out

    choices: list[Choice] = []
    for i, rc in enumerate(raw_choices):
        cwhere = f"{where} / choice[{i}]"
        if not isinstance(rc, dict):
            out.append(
                Violation("SCHEMA_SHAPE", Severity.ERROR, f"choice must be an object, got {type(rc).__name__}", cwhere)
            )
            continue
        fields: dict[str, str] = {}
        for key in _REQUIRED_CHOICE_FIELDS:
            val = rc.get(key)
            if not isinstance(val, str):
                out.append(
                    Violation("SCHEMA_SHAPE", Severity.ERROR, f"choice {key!r} must be a string", cwhere)
                )
                val = ""
            fields[key] = val
        choices.append(Choice(**fields))

    if not choices:
        return None, out
    return Scene(id=sid, prompt=prompt, choices=tuple(choices)), out


def validate_scene_data(
    raw: object,
    *,
    index: int = 0,
    allowed_tendencies: Iterable[str] = CANON_TENDENCIES,
) -> ValidationReport:
    """Validate a raw scene dict end to end: schema shape, then semantic invariants."""
    scene, shape = build_scene(raw, index=index)
    report = ValidationReport(tuple(shape))
    if scene is not None:
        report = report.merge(validate_scene(scene, allowed_tendencies=allowed_tendencies))
    return report


def build_reflection(raw: object, *, index: int = 0) -> tuple[Reflection | None, list[Violation]]:
    """Construct a :class:`~loop.core.Reflection` from a raw dict, reporting shape errors."""
    where = f"reflection[{index}]"
    if not isinstance(raw, dict):
        return None, [
            Violation("SCHEMA_SHAPE", Severity.ERROR, f"reflection must be an object, got {type(raw).__name__}", where)
        ]
    out: list[Violation] = []

    tendency = raw.get("tendency")
    if not isinstance(tendency, str):
        out.append(Violation("SCHEMA_SHAPE", Severity.ERROR, "reflection 'tendency' must be a string", where))
        tendency = ""

    count = raw.get("count")
    total = raw.get("total")
    if not isinstance(count, int) or isinstance(count, bool):
        out.append(Violation("SCHEMA_SHAPE", Severity.ERROR, "reflection 'count' must be an integer", where))
        count = 0
    if not isinstance(total, int) or isinstance(total, bool):
        out.append(Violation("SCHEMA_SHAPE", Severity.ERROR, "reflection 'total' must be an integer", where))
        total = 0

    raw_ev = raw.get("evidence")
    if not isinstance(raw_ev, list) or not all(isinstance(e, str) for e in raw_ev):
        out.append(
            Violation("SCHEMA_SHAPE", Severity.ERROR, "reflection 'evidence' must be a list of strings", where)
        )
        return None, out

    return Reflection(tendency=tendency, count=count, total=total, evidence=tuple(raw_ev)), out


def validate_reflection_data(raw: object, *, index: int = 0) -> ValidationReport:
    """Validate a raw reflection dict: schema shape, then semantic invariants.

    History grounding cannot be checked from a standalone artifact, so this
    enforces honest counts, the fiction boundary, and tone. Use
    :func:`validate_reflection` with ``history`` for the grounding invariant.
    """
    reflection, shape = build_reflection(raw, index=index)
    report = ValidationReport(tuple(shape))
    if reflection is not None:
        report = report.merge(validate_reflection(reflection))
    return report


def validate_package(
    raw: object,
    *,
    allowed_tendencies: Iterable[str] = CANON_TENDENCIES,
) -> ValidationReport:
    """Validate a whole generated content package before promotion.

    Expected shape (any section optional)::

        {
          "package_id": "...",
          "scenes": [ {scene}, ... ],
          "reflections": [ {reflection}, ... ]
        }
    """
    if not isinstance(raw, dict):
        return ValidationReport(
            (Violation("SCHEMA_SHAPE", Severity.ERROR, "package must be an object", "package"),)
        )

    report = ValidationReport()
    scenes = raw.get("scenes", [])
    reflections = raw.get("reflections", [])

    if not isinstance(scenes, list):
        report = report.merge(
            ValidationReport((Violation("SCHEMA_SHAPE", Severity.ERROR, "'scenes' must be a list", "package"),))
        )
        scenes = []
    if not isinstance(reflections, list):
        report = report.merge(
            ValidationReport((Violation("SCHEMA_SHAPE", Severity.ERROR, "'reflections' must be a list", "package"),))
        )
        reflections = []

    for i, scene in enumerate(scenes):
        report = report.merge(validate_scene_data(scene, index=i, allowed_tendencies=allowed_tendencies))
    for i, reflection in enumerate(reflections):
        report = report.merge(validate_reflection_data(reflection, index=i))

    return report
