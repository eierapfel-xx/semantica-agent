"""エージェントを実際の Claude（Pro のログイン）で動かす。既定では流さない（llm マーカー）。"""

from dataclasses import replace
from pathlib import Path

import pytest

from semantica_agent.agent.sdk import AgentSession
from semantica_agent.agent.tools import Knowledge
from semantica_agent.agent.trace import validate_trace
from semantica_agent.core.settings import load_settings

pytestmark = pytest.mark.llm
ROOT = Path(__file__).resolve().parents[1]

# cases.json の b9-late（11/2 生まれを 11/20 に届出。正解は AdditionalProcedure）を全項目言う。
LATE_CASE = (
    "出生届です。子は2026年11月2日10時30分にA市で生まれました。届出日は2026年11月20日、"
    "届出はA市にされ、本籍もA市、届出人は母でA市に住んでいます。続き柄は嫡出子、届書上の父は現在の夫です。"
    "出生証明書が添付されていて、出生日2026年11月2日、時刻10時30分、場所A市と書かれています。添付書類はこれだけです。"
    "届書には配偶者の有無、生まれたとき、生まれたところ、母の生年月日が記載されています。記載事項はこれだけです。"
    "母の生年月日は1990年1月1日、父母は2020年1月1日に婚姻しています。母に前婚はありません。"
    "入る戸籍も住所も存在します。"
)


async def ask(question: str, tmp_path: Path) -> dict:
    settings = replace(load_settings(), trace_root=tmp_path)
    sess = AgentSession(Knowledge.load(ROOT), settings)
    try:
        events = [e async for e in sess.ask(question)]
    finally:
        await sess.close()
    trace = events[-1]["trace"]
    validate_trace(trace)
    return trace


async def test_late_birth_case(tmp_path):
    trace = await ask(LATE_CASE, tmp_path)
    assert trace["status"] == "ok"
    assert any(e.get("tool") == "judge_birth_case" for e in trace["events"])
    assert trace["judgment"]["decision"] == "additionalProcedure"
    assert trace["flow"]["BIRTH-S2-I11"]["state"] == "finding"


async def test_kisoku_48_question(tmp_path):
    trace = await ask("戸籍法施行規則第48条が関わる工程はどれですか。", tmp_path)
    assert trace["status"] == "ok"
    step7 = {"BIRTH-S7", "MARRIAGE-S8", "DIVORCE-S7", "DEATH-S7"}
    referenced = {k for k, v in trace["flow"].items() if v["state"] == "referenced"}
    assert referenced & step7
