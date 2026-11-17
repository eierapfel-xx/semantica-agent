"""Agent SDK の ClaudeSDKClient の代わり。台本どおりにツールを呼び、メッセージを返す。"""

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)


def tool(name, args):
    return ("tool", name, args)


def text(t):
    return ("text", t)


def thinking(t):
    return ("thinking", t)


def fail(msg="boom"):
    return ("raise", msg)


def assistant_error(msg="rate_limit"):
    return ("assistant_error", msg)


class FakeClient:
    def __init__(self, options, tools, scripts):
        self.options, self.tools, self.scripts = options, tools, scripts
        self.prompts: list[str] = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def query(self, prompt):
        self.prompts.append(prompt)

    async def _hooks(self, event, data, tid):
        for m in self.options.hooks.get(event, []):
            for h in m.hooks:
                await h(data, tid, None)

    def _msg(self, blocks, error=None):
        return AssistantMessage(content=blocks, model="claude-sonnet-5-5", error=error)

    async def receive_response(self):
        script = self.scripts[len(self.prompts) - 1]
        for i, step in enumerate(script):
            kind = step[0]
            if kind == "tool":
                _, name, args = step
                full = f"mcp__koseki__{name}"
                yield self._msg([ToolUseBlock(id=f"t{i}", name=full, input=args)])
                await self._hooks("PreToolUse", {"tool_name": full, "tool_input": args}, f"t{i}")
                await self.tools[name].handler(args)
                await self._hooks("PostToolUse", {"tool_name": full, "tool_input": args}, f"t{i}")
            elif kind == "text":
                yield self._msg([TextBlock(text=step[1])])
            elif kind == "thinking":
                yield self._msg([ThinkingBlock(thinking=step[1], signature="s")])
            elif kind == "assistant_error":
                yield self._msg([TextBlock(text="")], error=step[1])
            elif kind == "raise":
                raise RuntimeError(step[1])
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="x",
        )


def fake_factory(*scripts):
    created = []

    def factory(options, tools):
        c = FakeClient(options, tools, list(scripts))
        created.append(c)
        return c

    factory.created = created
    return factory
