"""Unit tests for reframe strategies — config completeness and prompt resolution."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_strategies import (
    STRATEGY_CONFIG,
    CONTENT_TYPE_VARIABLES,
    get_strategy,
    resolve_prompt,
    BASE_REFRAME_PROMPT_TEMPLATE,
)

ALL_TYPES = ["movies", "documentaries", "sports", "podcasts", "promos", "news", "other"]
VALID_CV = {"face", "multi_face", "motion"}


# ---------------------------------------------------------------------------
# Strategy config completeness
# ---------------------------------------------------------------------------


class TestStrategyConfig:
    def test_all_types_have_config(self):
        for t in ALL_TYPES:
            assert t in STRATEGY_CONFIG, f"Missing strategy for {t}"

    def test_all_configs_have_required_keys(self):
        required = {"cv_strategy", "max_velocity", "deadzone", "use_diarization"}
        for t, config in STRATEGY_CONFIG.items():
            missing = required - set(config.keys())
            assert not missing, f"{t} missing keys: {missing}"

    def test_cv_strategy_values_valid(self):
        for t, config in STRATEGY_CONFIG.items():
            assert config["cv_strategy"] in VALID_CV, (
                f"{t} has invalid cv_strategy: {config['cv_strategy']}"
            )

    def test_velocity_positive(self):
        for t, config in STRATEGY_CONFIG.items():
            assert config["max_velocity"] > 0, f"{t} velocity must be positive"
            assert config["deadzone"] >= 0, f"{t} deadzone must be non-negative"
            assert config["deadzone"] < config["max_velocity"], (
                f"{t} deadzone must be less than velocity"
            )

    def test_get_strategy_known_type(self):
        for t in ALL_TYPES:
            s = get_strategy(t)
            assert s["cv_strategy"] in VALID_CV

    def test_get_strategy_unknown_falls_back(self):
        s = get_strategy("nonexistent")
        assert s == STRATEGY_CONFIG["other"]


# ---------------------------------------------------------------------------
# Prompt template variables
# ---------------------------------------------------------------------------


class TestPromptVariables:
    def test_all_types_have_variables(self):
        for t in ALL_TYPES:
            assert t in CONTENT_TYPE_VARIABLES, f"Missing variables for {t}"

    def test_all_variables_have_required_keys(self):
        required = {
            "content_description",
            "focal_strategy",
            "sampling_instructions",
            "audio_instructions",
            "framing_priority",
            "extra_rules",
        }
        for t, v in CONTENT_TYPE_VARIABLES.items():
            missing = required - set(v.keys())
            assert not missing, f"{t} missing variable keys: {missing}"

    def test_no_empty_values(self):
        for t, v in CONTENT_TYPE_VARIABLES.items():
            for key, val in v.items():
                assert val.strip(), f"{t}.{key} is empty"


# ---------------------------------------------------------------------------
# Prompt resolution
# ---------------------------------------------------------------------------


class TestResolvePrompt:
    def test_all_types_resolve(self):
        for t in ALL_TYPES:
            prompt, variables = resolve_prompt(t)
            assert isinstance(prompt, str)
            assert len(prompt) > 100
            assert isinstance(variables, dict)

    def test_unknown_type_uses_other(self):
        prompt, variables = resolve_prompt("unknown")
        other_prompt, other_vars = resolve_prompt("other")
        assert prompt == other_prompt

    def test_prompt_contains_type_description(self):
        prompt, _ = resolve_prompt("sports")
        assert "sports" in prompt.lower() or "athletic" in prompt.lower()

    def test_prompt_has_no_unresolved_placeholders(self):
        for t in ALL_TYPES:
            prompt, _ = resolve_prompt(t)
            assert "{" not in prompt, f"{t} prompt has unresolved placeholder"

    def test_template_has_all_placeholders(self):
        """Base template references all 6 variable keys."""
        for key in [
            "content_description",
            "focal_strategy",
            "sampling_instructions",
            "audio_instructions",
            "framing_priority",
            "extra_rules",
        ]:
            assert f"{{{key}}}" in BASE_REFRAME_PROMPT_TEMPLATE, (
                f"Template missing placeholder: {{{key}}}"
            )
