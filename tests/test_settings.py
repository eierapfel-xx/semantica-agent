from pathlib import Path

import pytest

from semantica_agent.settings import DEFAULT_GEN_MODEL, ConfigError, load_settings


def test_defaults():
    s = load_settings({})
    assert s.gen_model == DEFAULT_GEN_MODEL
    assert s.log_level == "INFO"
    assert s.run_root == Path("data/generation")


def test_env_overrides():
    s = load_settings({"ONTOLOGY_GEN_MODEL": "m", "LOG_LEVEL": "debug"})
    assert (s.gen_model, s.log_level) == ("m", "DEBUG")


def test_load_settings_rejects_api_key():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_settings({"ANTHROPIC_API_KEY": "x"})


def test_load_settings_rejects_bad_log_level():
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        load_settings({"LOG_LEVEL": "LOUD"})
