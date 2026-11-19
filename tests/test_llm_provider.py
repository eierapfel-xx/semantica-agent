import json

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from semantica.semantic_extract.registry import provider_registry
from semantica.utils.exceptions import ProcessingError

from semantica_agent.build.llm_provider import (
    PROVIDER_NAME,
    ClaudeAgentSDKProvider,
    extract_json,
    register_provider,
)


class FakeQuery:
    def __init__(self, replies, model="m-actual", stop_reason=None):
        self.replies = list(replies)
        self.model = model
        self.stop_reason = stop_reason
        self.prompts = []
        self.options = []

    def __call__(self, *, prompt, options):
        self.prompts.append(prompt)
        self.options.append(options)
        text = self.replies.pop(0)

        async def gen():
            yield AssistantMessage(
                content=[TextBlock(text=text)], model=self.model, stop_reason=self.stop_reason
            )

        return gen()


def test_generate_returns_text_and_model(tmp_path):
    q = FakeQuery(["OK"])
    p = ClaudeAgentSDKProvider(model="m", run_dir=tmp_path, query_fn=q)
    assert p.generate("hi") == "OK"
    assert p.last_model == "m-actual"
    assert (tmp_path / "001-prompt.md").read_text(encoding="utf-8") == "hi"
    assert (tmp_path / "001-response.txt").read_text(encoding="utf-8") == "OK"
    meta = json.loads((tmp_path / "001-meta.json").read_text(encoding="utf-8"))
    assert meta["model"] == "m-actual"


def test_options_disable_tools(tmp_path):
    q = FakeQuery(["OK"])
    ClaudeAgentSDKProvider(model="m", run_dir=tmp_path, query_fn=q).generate("hi")
    opt = q.options[0]
    assert opt.allowed_tools == [] and opt.tools == [] and opt.max_turns == 1
    assert opt.model == "m"


def test_generate_structured_strips_fence(tmp_path):
    q = FakeQuery(['前置き\n```json\n{"a": 1}\n```'])
    p = ClaudeAgentSDKProvider(run_dir=tmp_path, query_fn=q)
    assert p.generate_structured("x") == {"a": 1}


def test_generate_structured_retries_once(tmp_path):
    q = FakeQuery(['{"a": ', '{"a": 2}'])
    p = ClaudeAgentSDKProvider(run_dir=tmp_path, query_fn=q)
    assert p.generate_structured("x") == {"a": 2}
    assert "JSON" in q.prompts[1]
    assert (tmp_path / "002-prompt.md").exists()


def test_generate_structured_fails_after_retry(tmp_path):
    p = ClaudeAgentSDKProvider(run_dir=tmp_path, query_fn=FakeQuery(["no", "still no"]))
    with pytest.raises(ProcessingError, match="JSON"):
        p.generate_structured("x")


def test_truncated_by_max_tokens_is_retried(tmp_path):
    q = FakeQuery(['{"a": 1}', '{"a": 1}'], stop_reason="max_tokens")
    p = ClaudeAgentSDKProvider(run_dir=tmp_path, query_fn=q)
    with pytest.raises(ProcessingError, match="max_tokens"):
        p.generate_structured("x")
    assert len(q.prompts) == 2


def test_extract_json_does_not_repair_truncation():
    with pytest.raises(ValueError):
        extract_json('[{"a": 1}, {"b": ')


def test_extract_json_finds_value_after_prose():
    assert extract_json("結果は次のとおり: [1, 2]。以上") == [1, 2]


def test_registered_provider_is_used_by_semantica():
    register_provider()
    register_provider()
    assert provider_registry.get(PROVIDER_NAME) is ClaudeAgentSDKProvider


@pytest.mark.llm
def test_real_call_returns_json(tmp_path):
    p = ClaudeAgentSDKProvider(run_dir=tmp_path)
    assert p.generate_structured('{"ok": true} とだけ JSON で返して') == {"ok": True}
