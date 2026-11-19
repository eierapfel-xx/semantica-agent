from pathlib import Path

import pytest

from semantica_agent.core.settings import DEFAULT_GEN_MODEL, ConfigError, load_settings


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


def test_agent_defaults():
    s = load_settings({})
    assert s.agent_model == "claude-sonnet-5-5"
    assert (s.agent_max_turns, s.web_port, s.sparql_timeout_s) == (20, 8765, 10.0)
    assert s.trace_root == Path("output/traces")


def test_agent_env_overrides():
    s = load_settings({"AGENT_MODEL": "m2", "WEB_PORT": "9000"})
    assert (s.agent_model, s.web_port) == ("m2", 9000)


def test_bad_web_port():
    with pytest.raises(ConfigError, match="WEB_PORT"):
        load_settings({"WEB_PORT": "abc"})


def test_spool_and_trace_roots_default_and_env():
    s = load_settings({})
    assert s.spool_root == Path("output/claude-code") and s.trace_root == Path("output/traces")
    s = load_settings({"KOSEKI_SPOOL_ROOT": "/tmp/a", "KOSEKI_TRACE_ROOT": "/tmp/b"})
    assert s.spool_root == Path("/tmp/a") and s.trace_root == Path("/tmp/b")


def test_default_agent_model_is_sonnet():
    assert load_settings({}).agent_model == "claude-sonnet-5-5"
