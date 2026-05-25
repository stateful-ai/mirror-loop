"""Mirror Loop — world invariants and generation guardrails.

The Validator / Consistency layer (README "Agent Architecture";
``docs/game_design.md`` §8.4). It is the single executable source of truth for
the bounds generated content must pass before promotion: the hard invariants the
Mirror cannot violate, plus the fiction/tone safety bounds. The prose catalogue
is ``docs/GUARDRAILS.md``.

Run the validator against a content package::

    python -m guardrails guardrails/fixtures/clean_package.json
"""

from .invariants import (
    CANON_TENDENCIES,
    MIN_CHOICES,
    GuardrailViolation,
    Severity,
    ValidationReport,
    Violation,
    build_reflection,
    build_scene,
    check_fiction_boundary,
    check_tone,
    validate_adaptation,
    validate_choice,
    validate_package,
    validate_player_state,
    validate_reflection,
    validate_reflection_data,
    validate_scene,
    validate_scene_data,
)

__all__ = [
    "CANON_TENDENCIES",
    "MIN_CHOICES",
    "GuardrailViolation",
    "Severity",
    "ValidationReport",
    "Violation",
    "build_reflection",
    "build_scene",
    "check_fiction_boundary",
    "check_tone",
    "validate_adaptation",
    "validate_choice",
    "validate_package",
    "validate_player_state",
    "validate_reflection",
    "validate_reflection_data",
    "validate_scene",
    "validate_scene_data",
]
