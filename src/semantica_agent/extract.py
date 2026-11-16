"""手順書の PDF から表を行（PDF 上の 1 行）単位で取り出す。仕様 §5.1。LLM は使わない。"""

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import pdfplumber

from semantica_agent.vocab import BUSINESS_SLUGS

logger = logging.getLogger(__name__)

RowKind = Literal["table", "footnote", "note", "title"]
ROW_KINDS = ("table", "footnote", "note", "title")
LINE_TOLERANCE = 3.0  # 同じ行とみなす top の差（pt）
COLUMN_MARGIN = 4.0  # 見出しの x 座標から列の境界までの余白（pt）
FOOTNOTE_X_MAX = 60.0  # 脚注の番号が置かれる x の上限
PAGE_NUMBER = re.compile(r"^-\s*(\d+)\s*-$")


@dataclass(frozen=True)
class Row:
    row_id: str
    kind: RowKind
    business: str | None
    division: str
    procedure: str
    remarks: str
    pdf_page: int
    printed_page: int | None
    y: float


@dataclass(frozen=True)
class ColumnBounds:
    division_end: float
    procedure_end: float


def group_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda x: (x["top"], x["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda x: x["x0"]) for line in lines]


def assign_columns(words: list[dict], bounds: ColumnBounds) -> tuple[str, str, str]:
    cols: tuple[list[str], list[str], list[str]] = ([], [], [])
    for word in sorted(words, key=lambda x: x["x0"]):
        if word["x0"] < bounds.division_end:
            cols[0].append(word["text"])
        elif word["x0"] < bounds.procedure_end:
            cols[1].append(word["text"])
        else:
            cols[2].append(word["text"])
    return tuple(" ".join(c) for c in cols)  # type: ignore[return-value]


def _line_text(line: list[dict]) -> str:
    return " ".join(w["text"] for w in line)


def _header(lines: list[list[dict]]) -> tuple[int, ColumnBounds] | None:
    for i, line in enumerate(lines):
        texts = {w["text"]: w["x0"] for w in line}
        if {"区分", "業務手順", "備考"} <= texts.keys():
            return i, ColumnBounds(texts["業務手順"] - COLUMN_MARGIN, texts["備考"] - COLUMN_MARGIN)
    return None


def _printed_page(lines: list[list[dict]]) -> tuple[int | None, int | None]:
    for i, line in enumerate(lines):
        m = PAGE_NUMBER.match(_line_text(line).replace(" ", ""))
        if m:
            return i, int(m.group(1))
    return None, None


def _business_of(line: list[dict]) -> str | None:
    text = _line_text(line)
    if not text.startswith("業務名"):
        return None
    name = text.removeprefix("業務名").strip()
    if name not in BUSINESS_SLUGS:
        raise ValueError(f"未知の業務名です（vocab.BUSINESS_SLUGS に足してください）: {name}")
    return BUSINESS_SLUGS[name]


def _page_rows(page, pdf_page: int, business: str | None) -> tuple[list[Row], str | None]:
    lines = group_lines(page.extract_words())
    header = _header(lines)
    pn_index, printed = _printed_page(lines)
    titles = [b for b in (_business_of(line) for line in lines) if b]
    if titles:
        business = titles[0]  # 頁の上部の注記も、その頁で始まる業務に属させる
    rows: list[Row] = []
    for i, line in enumerate(lines):
        if i == pn_index:
            continue
        row_id = f"p{pdf_page}-r{len(rows) + 1}"
        y = float(line[0]["top"])
        found = _business_of(line)
        if found:
            business = found
            rows.append(
                Row(row_id, "title", business, "", _line_text(line), "", pdf_page, printed, y)
            )
            continue
        if header is None or i <= header[0]:
            if header is not None and i == header[0]:
                continue  # 表の見出しの行
            rows.append(
                Row(row_id, "note", business, "", _line_text(line), "", pdf_page, printed, y)
            )
            continue
        first = line[0]
        if first["x0"] < FOOTNOTE_X_MAX and first["text"].isdigit():
            rows.append(
                Row(row_id, "footnote", business, "", _line_text(line), "", pdf_page, printed, y)
            )
            continue
        division, procedure, remarks = assign_columns(line, header[1])
        rows.append(
            Row(row_id, "table", business, division, procedure, remarks, pdf_page, printed, y)
        )
    return rows, business


def extract_rows(pdf_path: Path) -> list[Row]:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"手順書の PDF がありません: {pdf_path}")
    rows: list[Row] = []
    business: str | None = None
    with pdfplumber.open(pdf_path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            page_rows, business = _page_rows(page, index, business)
            rows.extend(page_rows)
            logger.debug("頁 %d: %d 行", index, len(page_rows))
    return rows


def rows_for_business(rows: list[Row], business_slug: str) -> list[Row]:
    return [r for r in rows if r.business == business_slug]


def save_rows(rows: list[Row], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(r) for r in rows]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


_FIELDS = {
    "row_id": str,
    "kind": str,
    "division": str,
    "procedure": str,
    "remarks": str,
    "pdf_page": int,
    "y": (int, float),
}


def _row_from_dict(d: dict) -> Row:
    for key, typ in _FIELDS.items():
        if not isinstance(d.get(key), typ):
            raise ValueError(f"行の {key} が不正です: {d.get('row_id')}: {d.get(key)!r}")
    if d["kind"] not in ROW_KINDS:
        raise ValueError(f"行の kind が不正です: {d['row_id']}: {d['kind']}")
    return Row(
        d["row_id"],
        d["kind"],
        d.get("business"),
        d["division"],
        d["procedure"],
        d["remarks"],
        d["pdf_page"],
        d.get("printed_page"),
        float(d["y"]),
    )


def load_rows(path: Path) -> list[Row]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"rows.json は配列である必要があります: {path}")
    return [_row_from_dict(d) for d in data]


def render_rows(rows: list[Row]) -> str:
    """プロンプトに入れる形（`row_id | 業務 | 区分 | 業務手順 | 備考`）。"""
    return "\n".join(
        f"{r.row_id} | {r.business or '-'} | {r.division} | {r.procedure} | {r.remarks}"
        for r in rows
    )
