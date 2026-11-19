"""テスト用：cases.json の事案を、judge_birth_case の入力（3 状態）に直す。"""

import json
from pathlib import Path

from semantica_agent.review.case_input import CASE_FIELDS, parse_case_input

CASES = json.loads((Path(__file__).parent / "fixtures/birth_cases/cases.json").read_text("utf-8"))
UNKNOWN = object()  # 項目を省く（未確認）
VOCAB_PREFIX = {
    "notifierRole": "ROLE",
    "attachedDocument": "DOCUMENT",
    "recordedItem": "RECORD-ITEM",
}


def _arg(key, value):
    if value is None:
        return {"status": "none", "quote": "q"}
    if isinstance(value, dict):
        return value
    if key in ("attachedDocument", "recordedItem"):
        items = [f"{VOCAB_PREFIX[key]}-{v.upper()}" for v in value]
        return {"status": "given", "items": items, "complete": True, "quote": "q"}
    if key == "notifierRole":
        return {"status": "given", "value": f"ROLE-{value.upper()}", "quote": "q"}
    return {"status": "given", "value": value, "quote": "q"}


def full_args(**changes) -> dict:
    """base に changes を当てる。None は「無いと確認」、UNKNOWN は省く。

    base に無い項目は none にする。
    """
    merged = {f.name: None for f in CASE_FIELDS} | CASES["base"] | changes
    return {k: _arg(k, v) for k, v in merged.items() if v is not UNKNOWN}


def full_case(onto, **changes):
    return parse_case_input(full_args(**changes), onto)


def case_changes(case_id: str) -> dict:
    return next(c["changes"] for c in CASES["cases"] if c["id"] == case_id)
