"""出生届の事案の入力（ツールの引数）を解釈する。仕様 §5.1。

項目は given（値がある）・none（無いと確認した）・unknown（未確認）の 3 つの状態をとる。
none と unknown はどちらも三つ組を作らない。区別は判定の後処理（assess.py）で使う。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Literal

from rdflib import RDF, RDFS, Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import XSD

from semantica_agent.ids import iri_from_short_id, short_id
from semantica_agent.namespaces import KD, KOS, bind_prefixes

Kind = Literal["date", "time", "string", "bool", "iri", "iri_list"]
Status = Literal["given", "none", "unknown"]
STATUSES = ("given", "none", "unknown")
RELATIONSHIPS = ("嫡出子", "嫡出でない子")
STATED_FATHERS = ("現在の夫", "前の夫", "記載なし")
_SPACE = re.compile(r"\s+")


class CaseInputError(ValueError):
    pass


@dataclass(frozen=True)
class CaseField:
    name: str
    kind: Kind
    label_ja: str
    vocab: str | None = None
    choices: tuple[str, ...] = ()


CASE_FIELDS: tuple[CaseField, ...] = (
    CaseField("childBirthDate", "date", "子の出生日"),
    CaseField("childBirthTime", "time", "子の出生時刻"),
    CaseField("filingDate", "date", "届出日"),
    CaseField("filingMunicipality", "string", "届出を受けた市区町村"),
    CaseField("honsekiMunicipality", "string", "子が入る戸籍の本籍地"),
    CaseField("birthPlaceMunicipality", "string", "出生地"),
    CaseField("notifierMunicipality", "string", "届出人の所在地"),
    CaseField("notifierRole", "iri", "届出人の資格", vocab="role"),
    CaseField("attachedDocument", "iri_list", "添付された書類", vocab="document"),
    CaseField("recordedItem", "iri_list", "届書に記載のある事項", vocab="record-item"),
    CaseField("statedRelationship", "string", "届書の続き柄", choices=RELATIONSHIPS),
    CaseField("statedFather", "string", "届書上の父", choices=STATED_FATHERS),
    CaseField("certBirthDate", "date", "出生証明書の出生日"),
    CaseField("certBirthTime", "time", "出生証明書の出生時刻"),
    CaseField("certBirthPlace", "string", "出生証明書の出生地"),
    CaseField("motherBirthDate", "date", "母の生年月日"),
    CaseField("parentsMarriageDate", "date", "出生時の母の婚姻の日"),
    CaseField("motherPrevMarriageEndDate", "date", "母の前婚の解消日"),
    CaseField("motherRemarriedBeforeBirth", "bool", "前婚の解消後、出生までに再婚したか"),
    CaseField("familyRegisterExists", "bool", "入る戸籍が存在するか"),
    CaseField("addressExists", "bool", "住所が存在するか"),
)
FIELDS_BY_NAME = {f.name: f for f in CASE_FIELDS}


@dataclass(frozen=True)
class FieldValue:
    name: str
    status: Status
    value: object = None
    quote: str | None = None
    inferred: bool = False
    note: str | None = None


@dataclass(frozen=True)
class CaseInput:
    fields: tuple[FieldValue, ...]
    complete_lists: frozenset[str]

    @property
    def unknown_fields(self) -> frozenset[str]:
        return frozenset(f.name for f in self.fields if f.status == "unknown")

    def get(self, name: str) -> FieldValue:
        return next(f for f in self.fields if f.name == name)


def vocab_values(ontology: Graph, vocab: str) -> tuple[str, ...]:
    """列挙の種類（role 等）の個体の短い ID。"""
    prefix = f"{KD}{vocab}/"
    iris = {s for s in ontology.subjects(RDFS.label, None) if str(s).startswith(prefix)}
    return tuple(sorted(short_id(s) for s in iris))


def _value_schema(f: CaseField, ontology: Graph) -> dict:
    if f.kind in ("iri", "iri_list"):
        return {"type": "string", "enum": list(vocab_values(ontology, f.vocab))}
    if f.choices:
        return {"type": "string", "enum": list(f.choices)}
    return {
        "date": {"type": "string", "format": "date"},
        "time": {"type": "string", "description": "HH:MM"},
        "string": {"type": "string"},
        "bool": {"type": "boolean"},
    }[f.kind]


def input_schema(ontology: Graph) -> dict:
    """judge_birth_case の入力の JSON スキーマ。省いた項目は未確認（unknown）。"""
    props = {}
    for f in CASE_FIELDS:
        common = {
            "status": {"type": "string", "enum": list(STATUSES)},
            "quote": {"type": "string", "description": "根拠になった職員の発言の一部"},
            "inferred": {"type": "boolean"},
            "note": {"type": "string"},
        }
        if f.kind == "iri_list":
            common["items"] = {"type": "array", "items": _value_schema(f, ontology)}
            common["complete"] = {"type": "boolean", "description": "これで全部と確認したか"}
        else:
            common["value"] = _value_schema(f, ontology)
        props[f.name] = {
            "type": "object",
            "description": f.label_ja,
            "properties": common,
            "required": ["status"],
        }
    return {"type": "object", "properties": props, "additionalProperties": False}


def _convert(f: CaseField, raw: object, ontology: Graph) -> object:
    try:
        if f.kind == "date":
            return date.fromisoformat(str(raw))
        if f.kind == "time":
            return time.fromisoformat(str(raw))
        if f.kind == "bool":
            if not isinstance(raw, bool):
                raise ValueError("true か false")
            return raw
        if f.kind == "iri":
            return _enum(f, raw, ontology)
        if f.choices and raw not in f.choices:
            raise ValueError(f"{'・'.join(f.choices)} のいずれか")
        if not isinstance(raw, str) or not raw:
            raise ValueError("空でない文字列")
        return raw
    except ValueError as e:
        raise CaseInputError(f"{f.name} の値が不正です: {raw!r}（{e}）") from e


def _enum(f: CaseField, raw: object, ontology: Graph) -> str:
    allowed = vocab_values(ontology, f.vocab)
    if raw not in allowed:
        raise CaseInputError(f"{f.name} の値 {raw!r} は列挙にありません（{', '.join(allowed)}）")
    return str(raw)


def _parse_field(f: CaseField, arg: dict, ontology: Graph) -> tuple[FieldValue, bool]:
    if not isinstance(arg, dict) or arg.get("status") not in STATUSES:
        raise CaseInputError(f"{f.name} の status は {', '.join(STATUSES)} のいずれかです")
    status = arg["status"]
    if status == "unknown":
        return FieldValue(f.name, "unknown"), False
    quote = arg.get("quote")
    if not isinstance(quote, str) or not _squash(quote):
        raise CaseInputError(f"{f.name} には quote（職員の発言の引用）が要ります")
    if status == "none":
        # 一覧の項目の none は「一つも無い」と確認したこと（空の一覧で全部）
        return FieldValue(f.name, "none", quote=quote), f.kind == "iri_list"
    meta = {"quote": quote, "inferred": bool(arg.get("inferred")), "note": arg.get("note")}
    if f.kind == "iri_list":
        items = tuple(_enum(f, v, ontology) for v in arg.get("items") or [])
        complete = bool(arg.get("complete"))
        if not items and not complete:
            return FieldValue(f.name, "unknown"), False
        return FieldValue(f.name, "given", items, **meta), complete
    if "value" not in arg or arg["value"] is None:
        raise CaseInputError(f"{f.name} は given なので value が要ります")
    return FieldValue(f.name, "given", _convert(f, arg["value"], ontology), **meta), False


def parse_case_input(args: dict, ontology: Graph) -> CaseInput:
    unknown_names = sorted(set(args) - set(FIELDS_BY_NAME))
    if unknown_names:
        raise CaseInputError(f"知らない項目があります: {', '.join(unknown_names)}")
    fields, complete = [], set()
    for f in CASE_FIELDS:
        if f.name not in args:
            fields.append(FieldValue(f.name, "unknown"))
            continue
        fv, is_complete = _parse_field(f, args[f.name], ontology)
        fields.append(fv)
        if is_complete:
            complete.add(f.name)
    return CaseInput(tuple(fields), frozenset(complete))


def _squash(text: str) -> str:
    return _SPACE.sub("", text)


def check_quotes(case: CaseInput, utterances: Sequence[str]) -> list[str]:
    """引用が職員の発言のどれにも含まれない項目名（空白を除いて照合）。"""
    said = [_squash(u) for u in utterances]
    return [
        f.name
        for f in case.fields
        if f.status != "unknown" and not any(_squash(f.quote or "") in s for s in said)
    ]


def _literal(f: CaseField, value: object) -> RDFLiteral:
    if f.kind == "date":
        return RDFLiteral(value, datatype=XSD.date)
    if f.kind == "time":
        return RDFLiteral(value, datatype=XSD.time)
    return RDFLiteral(value)


def case_graph(case: CaseInput, case_iri: URIRef) -> Graph:
    g = bind_prefixes(Graph())
    g.add((case_iri, RDF.type, KOS.BirthFiling))
    for fv in case.fields:
        if fv.status != "given":
            continue
        f = FIELDS_BY_NAME[fv.name]
        if f.kind == "iri":
            g.add((case_iri, KOS[f.name], iri_from_short_id(fv.value)))
        elif f.kind == "iri_list":
            for sid in fv.value:
                g.add((case_iri, KOS[f.name], iri_from_short_id(sid)))
        else:
            g.add((case_iri, KOS[f.name], _literal(f, fv.value)))
    return g


def case_record(case: CaseInput, case_iri: URIRef) -> dict:
    """トレースに残す事案：Turtle と、項目ごとの状態・値・引用・推測。"""
    fields = [
        {
            "name": fv.name,
            "label": FIELDS_BY_NAME[fv.name].label_ja,
            "status": fv.status,
            "value": list(fv.value)
            if isinstance(fv.value, tuple)
            else (None if fv.value is None else str(fv.value)),
            "quote": fv.quote,
            "inferred": fv.inferred,
            "note": fv.note,
            "complete": fv.name in case.complete_lists,
        }
        for fv in case.fields
    ]
    turtle = case_graph(case, case_iri).serialize(format="turtle")
    return {"iri": str(case_iri), "turtle": turtle, "fields": fields}
