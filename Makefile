# Mirror Loop — minimal task runner.
# Thin wrappers around the commands in CONTRIBUTING.md so newcomers
# can `make test` without memorising paths.

.PHONY: help test test-fast lint

help:
	@echo "Targets:"
	@echo "  test       Run the full pytest suite (matches CI / CONTRIBUTING)."
	@echo "  test-fast  Skip the acceptance gate; run the per-package suites."
	@echo "  lint       No linter is configured yet; this target is a no-op."
	@echo "  help       Show this message."

test:
	pytest

# Acceptance lives in acceptance/tests/ and is the slowest leg; skip it
# for a quick inner-loop signal. Mirrors the testpaths block in pyproject.toml
# minus the acceptance entry.
test-fast:
	pytest mirror/tests loop/tests game/tests guardrails/tests \
	       runtime/tests llmbench/tests latency/tests telemetry/tests \
	       tests

lint:
	@echo "No linter is configured for this repo yet — skipping."
