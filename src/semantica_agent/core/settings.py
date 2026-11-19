"""環境変数の読み込みと検証。"""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GEN_MODEL = "claude-opus-5-5"
DEFAULT_RUN_ROOT = Path("data/generation")
DEFAULT_AGENT_MODEL = "claude-sonnet-5-5"
DEFAULT_WEB_PORT = 8765
DEFAULT_TRACE_ROOT = Path("output/traces")
AGENT_MAX_TURNS = 20
SPARQL_TIMEOUT_S = 10.0
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    gen_model: str
    log_level: str
    run_root: Path
    agent_model: str = DEFAULT_AGENT_MODEL
    agent_max_turns: int = AGENT_MAX_TURNS
    web_port: int = DEFAULT_WEB_PORT
    sparql_timeout_s: float = SPARQL_TIMEOUT_S
    trace_root: Path = DEFAULT_TRACE_ROOT


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    if env.get("ANTHROPIC_API_KEY"):
        raise ConfigError(
            "ANTHROPIC_API_KEY が設定されています。"
            "Pro のログインで動かすため、外してから実行してください。"
        )
    level = env.get("LOG_LEVEL", "INFO").upper()
    if level not in _LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL が不正です: {level}（{', '.join(_LOG_LEVELS)} のいずれか）")
    port = env.get("WEB_PORT") or str(DEFAULT_WEB_PORT)
    if not port.isdigit() or not 0 < int(port) < 65536:
        raise ConfigError(f"WEB_PORT が不正です: {port!r}（1〜65535 の整数）")
    return Settings(
        gen_model=env.get("ONTOLOGY_GEN_MODEL") or DEFAULT_GEN_MODEL,
        log_level=level,
        run_root=DEFAULT_RUN_ROOT,
        agent_model=env.get("AGENT_MODEL") or DEFAULT_AGENT_MODEL,
        web_port=int(port),
    )


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
