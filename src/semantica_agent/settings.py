"""環境変数の読み込みと検証。"""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GEN_MODEL = "claude-opus-5-5"
DEFAULT_RUN_ROOT = Path("data/generation")
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    gen_model: str
    log_level: str
    run_root: Path


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    if env.get("ANTHROPIC_API_KEY"):
        raise ConfigError(
            "ANTHROPIC_API_KEY が設定されています。"
            "Pro のログインで動かすため、外してから実行してください。"
        )
    level = env.get("LOG_LEVEL", "INFO").upper()
    if level not in _LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL が不正です: {level}（{', '.join(_LOG_LEVELS)} のいずれか）")
    return Settings(
        gen_model=env.get("ONTOLOGY_GEN_MODEL") or DEFAULT_GEN_MODEL,
        log_level=level,
        run_root=DEFAULT_RUN_ROOT,
    )


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
