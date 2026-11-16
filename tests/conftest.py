import json
from pathlib import Path

import pytest

from semantica_agent.extract import Row

FIXTURES = Path(__file__).parent / "fixtures"


def _row(n, kind, division, procedure, remarks):
    return Row(f"p2-r{n}", kind, "birth", division, procedure, remarks, 2, 1, float(n * 15))


@pytest.fixture
def birth_rows():
    return [
        _row(1, "title", "", "業務名 戸籍届出（出生）", ""),
        _row(2, "table", "1.受付", "★下記(1)から(2)までの必要書類が全て満たされ、疑義が無い", ""),
        _row(3, "table", "", "場合は審査に移行する。", ""),
        _row(4, "table", "", "(1) 出生届及び出生証明書等の確認", ""),
        _row(
            5,
            "table",
            "",
            "① 記入例と照合して記入漏れがあれば、指摘する。",
            "戸籍法、戸籍法施行規則に定められた記載",
        ),
        _row(6, "table", "", "", "事項について確認する。（戸籍法第29条、第49条）"),
        _row(7, "table", "2.審査", "○届出地に該当しているか。", "戸籍法第25条、第51条"),
        _row(
            8,
            "table",
            "",
            "○届出人は届出義務者又は届出の資格を有する者か。",
            "戸籍法第52条第1項、第2項",
        ),
        _row(9, "table", "", "○必要な添付書類は揃っているか。", "戸籍法第49条第3項"),
        _row(10, "table", "", "（出生証明書が添付されていない場合には、法務局に受理照", ""),
        _row(11, "table", "", "会する。）", ""),
        _row(12, "footnote", "", "1 現に届出の任に当たっている者", ""),
    ]


@pytest.fixture
def sample():
    return json.loads((FIXTURES / "instances_birth_sample.json").read_text(encoding="utf-8"))
