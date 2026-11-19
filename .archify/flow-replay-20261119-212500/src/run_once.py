import asyncio
from pathlib import Path

from semantica_agent.agent.sdk import AgentSession
from semantica_agent.agent.tools import Knowledge
from semantica_agent.core.settings import configure_logging, load_settings

Q = (
    "2026年10月20日生まれの子の出生届です。父が11月10日にB市の窓口に出しに来ました。"
    "父母の婚姻は6月1日で、届書の続き柄は嫡出子、父欄は今の夫です。"
    "本籍はA市、住所はB市で、どちらも確認済みです。母は1995年4月3日生まれ。"
    "B市の病院で生まれ、出生証明書は付いています。添付はそれだけです。"
    "母に前の婚姻はありません。受理できますか？"
)


async def main():
    s = load_settings()
    configure_logging(s)
    k = Knowledge.load(Path("."))
    sess = AgentSession(k, s, session_id="flow-replay")
    try:
        async for e in sess.ask(Q):
            if e["type"] == "turn_end":
                print("TRACE", e["trace_path"])
            else:
                print(e["type"], e.get("tool", ""))
    finally:
        await sess.close()


asyncio.run(main())
