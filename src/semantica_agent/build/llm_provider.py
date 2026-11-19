"""Claude Agent SDK（Pro のログイン）を包んだ semantica のプロバイダー。仕様 §5.2。"""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import anyio
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query
from semantica.semantic_extract.providers import BaseProvider
from semantica.semantic_extract.registry import provider_registry
from semantica.utils.exceptions import ProcessingError

logger = logging.getLogger(__name__)

PROVIDER_NAME = "claude_agent_sdk"
SYSTEM_PROMPT = (
    "あなたはオントロジー生成の補助をする。指示された形式だけを出力し、前置きや説明を付けない。"
)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict | list:
    """コードフェンスを外し、最初の完全な JSON 値を返す。切れた JSON は補わない。"""
    candidates = [m.group(1) for m in _FENCE.finditer(text)] or [text]
    decoder = json.JSONDecoder()
    for cand in candidates:
        # 最初の括弧から始まる値だけを見る（内側の部分を拾うと欠落を黙って通すため）
        starts = [i for i in (cand.find("{"), cand.find("[")) if i >= 0]
        if not starts:
            continue
        try:
            value, _ = decoder.raw_decode(cand[min(starts) :])
            return value
        except json.JSONDecodeError:
            continue
    raise ValueError(f"JSON を取り出せません。先頭: {text[:100]!r}")


class ClaudeAgentSDKProvider(BaseProvider):
    def __init__(self, model=None, run_dir: Path | None = None, query_fn=None, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.run_dir = run_dir
        self.query_fn = query_fn or query
        self.last_model: str | None = None
        self.last_stop_reason: str | None = None
        self._calls = 0

    def _options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            model=self.model, system_prompt=SYSTEM_PROMPT, allowed_tools=[], tools=[], max_turns=1
        )

    async def _ask(self, prompt: str) -> str:
        texts: list[str] = []
        async for msg in self.query_fn(prompt=prompt, options=self._options()):
            if isinstance(msg, AssistantMessage):
                if msg.error:
                    raise ProcessingError(f"Agent SDK がエラーを返しました: {msg.error}")
                self.last_model = msg.model
                self.last_stop_reason = msg.stop_reason
                texts += [b.text for b in msg.content if isinstance(b, TextBlock)]
        return "".join(texts)

    def _save(self, prompt: str, text: str, started: datetime) -> None:
        if self.run_dir is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        n = f"{self._calls:03d}"
        (self.run_dir / f"{n}-prompt.md").write_text(prompt, encoding="utf-8")
        (self.run_dir / f"{n}-response.txt").write_text(text, encoding="utf-8")
        meta = {
            "model": self.last_model,
            "requested_model": self.model,
            "stop_reason": self.last_stop_reason,
            "started": started.isoformat(),
            "ended": datetime.now(UTC).isoformat(),
        }
        (self.run_dir / f"{n}-meta.json").write_text(json.dumps(meta, ensure_ascii=False))

    def generate(self, prompt: str, **kwargs) -> str:
        self._calls += 1
        started = datetime.now(UTC)
        logger.info("LLM を呼びます（%d 回目、%d 文字）", self._calls, len(prompt))
        text = anyio.run(self._ask, prompt)
        self._save(prompt, text, started)
        logger.debug(
            "応答: model=%s stop=%s 文字数=%d", self.last_model, self.last_stop_reason, len(text)
        )
        return text

    def _parse(self, text: str) -> dict | list:
        if self.last_stop_reason == "max_tokens":
            raise ValueError("応答が max_tokens で切れています")
        return extract_json(text)

    def generate_structured(self, prompt: str, **kwargs) -> dict | list:
        text = self.generate(prompt)
        try:
            return self._parse(text)
        except ValueError as first:
            logger.warning("JSON を取り出せないため 1 回だけ再要求します: %s", first)
            retry = (
                f"{prompt}\n\n前回の応答から JSON を取り出せませんでした（{first}）。"
                "JSON だけを、省略せずに最後まで出力してください。"
            )
            text = self.generate(retry)
            try:
                return self._parse(text)
            except ValueError as second:
                raise ProcessingError(f"再要求しても JSON を取り出せません: {second}") from second


def register_provider() -> None:
    provider_registry.register(PROVIDER_NAME, ClaudeAgentSDKProvider)
