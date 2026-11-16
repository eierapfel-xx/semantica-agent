import os

import pytest
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query


@pytest.mark.llm
async def test_agent_sdk_answers_with_pro_login():
    # API キーがあるとログインより優先され従量課金になるので、Pro のログインで動くことを確かめる。
    assert not os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY を外して実行する"
    options = ClaudeAgentOptions(max_turns=1, allowed_tools=[])
    texts = []
    async for message in query(prompt="「OK」とだけ答えて。", options=options):
        if isinstance(message, AssistantMessage):
            texts += [b.text for b in message.content if isinstance(b, TextBlock)]
    assert "OK" in "".join(texts)
