"""LLM が出したインスタンスの JSON の検証（仕様 §5.4）。エラーの一覧を返す。"""

import re
import unicodedata
from collections.abc import Iterator

from semantica_agent.extract import Row
from semantica_agent.ids import ProvisionRef
from semantica_agent.lawref import provision_appears_in
from semantica_agent.vocab import ITEM_VOCAB_FIELDS, LAW_SLUGS

ITEM_KINDS = ("check", "task", "note")
ALIGNMENTS = ("ok", "uncertain")


class InstanceValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("インスタンスの検証に失敗しました:\n" + "\n".join(errors))
        self.errors = errors


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def iter_items(items: list[dict], prefix: str) -> Iterator[tuple[str, dict]]:
    for i, item in enumerate(items or [], start=1):
        where = f"{prefix}.{i}"
        yield where, item
        yield from iter_items(item.get("children") or [], where)


def has_article(cite: dict) -> bool:
    return isinstance(cite.get("article"), int)


def cite_to_ref(cite: dict) -> ProvisionRef:
    return ProvisionRef(
        cite.get("law", ""),
        int(cite.get("article") or 0),
        cite.get("branch"),
        cite.get("paragraph"),
        cite.get("item"),
    )


def ref_text(ref: ProvisionRef) -> str:
    s = f"{ref.law}第{ref.article}条" + (f"の{ref.branch}" if ref.branch else "")
    s += f"第{ref.paragraph}項" if ref.paragraph else ""
    return s + (f"第{ref.item}号" if ref.item else "")


class _Checker:
    def __init__(self, out: dict, rows: list[Row]):
        self.out = out
        self.rows = {r.row_id: r for r in rows}
        self.business_rows = [r for r in rows if r.business == out.get("business")]
        self.errors: list[str] = []
        self.used: set[str] = set()

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def known_rows(self, where: str, ids: list[str]) -> list[Row]:
        found = []
        for rid in ids or []:
            if rid not in self.rows:
                self.err(f"{where}: 存在しない row_id です: {rid}")
            else:
                self.used.add(rid)
                found.append(self.rows[rid])
        return found

    def check_cites(
        self, where: str, cites: list[dict], remark_rows: list[Row], text_rows: list[Row]
    ) -> None:
        # 備考の列と、項目の業務手順の本文の両方を見る（本文で条文を引く手順があるため）
        remarks = (
            "".join(r.remarks for r in remark_rows) + "。" + "".join(r.procedure for r in text_rows)
        )
        for cite in cites or []:
            if not has_article(cite):
                continue  # 条の指定の無い法令は注記にする（instance_gen）
            ref = cite_to_ref(cite)
            if ref.law not in LAW_SLUGS:
                self.err(f"{where}: 未知の法令です（vocab.LAW_SLUGS に足すか確認）: {ref.law}")
            elif not cite.get("normalization_note") and not provision_appears_in(ref, remarks):
                self.err(f"{where}: {ref_text(ref)} が備考（remark_row_ids）に見つかりません")

    def check_item(self, where: str, item: dict) -> None:
        rows = self.known_rows(where, item.get("row_ids"))
        if not rows:
            self.err(f"{where}: row_ids がありません")
        quote = _norm(item.get("quote") or "")
        texts = (_norm("".join(r.procedure for r in rows)), _norm("".join(r.remarks for r in rows)))
        if not quote or not any(quote in t for t in texts):
            self.err(f"{where}: quote が row_ids の行にありません: {item.get('quote')!r}")
        remark_rows = self.known_rows(where, item.get("remark_row_ids") or item.get("row_ids"))
        self.check_cites(where, item.get("cites"), remark_rows, rows)
        if item.get("kind") not in ITEM_KINDS:
            self.err(f"{where}: kind は {ITEM_KINDS} のいずれか: {item.get('kind')!r}")
        if item.get("alignment", "ok") not in ALIGNMENTS:
            self.err(f"{where}: alignment は {ALIGNMENTS} のいずれか: {item.get('alignment')!r}")
        if item.get("speculative") and not item.get("reason"):
            self.err(f"{where}: speculative の項目には reason が要ります")
        for field, (kind, table, _, _) in ITEM_VOCAB_FIELDS.items():
            for name in item.get(field) or []:
                if name not in table:
                    self.err(f"{where}: {field} の「{name}」が語彙の表（{kind}）にありません")

    def check_steps(self) -> None:
        numbers = [s.get("number") for s in self.out.get("steps") or []]
        divisions = sorted(
            {int(m.group(1)) for r in self.business_rows if (m := re.match(r"(\d+)\.", r.division))}
        )
        if sorted(n for n in numbers if isinstance(n, int)) != divisions:
            self.err(f"工程の番号 {numbers} が手順書の区分 {divisions} と一致しません")
        for step in self.out.get("steps") or []:
            where = f"step{step.get('number')}"
            step_rows = self.known_rows(where, step.get("row_ids"))
            self.check_cites(where, step.get("cites"), step_rows, step_rows)
            for w, item in iter_items(step.get("items"), where):
                self.check_item(w, item)
                target = item.get("prerequisite_for")
                if target is not None and target not in numbers:
                    self.err(f"{w}: prerequisite_for の工程 {target} がありません")

    def run(self) -> list[str]:
        if self.out.get("business") not in {r.business for r in self.business_rows}:
            self.err(f"business が行の業務と一致しません: {self.out.get('business')!r}")
        self.check_steps()
        for note in self.out.get("notes") or []:
            self.known_rows("notes", note.get("row_ids"))
        tables = {kind: table for kind, table, _, _ in ITEM_VOCAB_FIELDS.values()}
        for v in self.out.get("new_vocab") or []:
            if v.get("name_ja") in tables.get(v.get("kind"), {}):
                continue
            self.err(
                f"語彙の追加の提案: {v.get('kind')} 「{v.get('name_ja')}」→ {v.get('slug')}"
                "（vocab.py に足してから再実行）"
            )
        unused = [
            r.row_id for r in self.business_rows if r.kind == "table" and r.row_id not in self.used
        ]
        if unused:
            self.err(f"どの項目にも使われていない行があります: {', '.join(unused)}")
        return self.errors


def validate_instance_output(out: dict, rows: list[Row]) -> list[str]:
    return _Checker(out, rows).run()
