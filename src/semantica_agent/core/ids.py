"""IRI と短い ID（仕様 §7.1・§7.2）。IRI はコードだけが決める。"""

import re
from dataclasses import dataclass

from rdflib import URIRef

from semantica_agent.core.namespaces import KD
from semantica_agent.core.vocab import LAW_SLUGS

VOCAB_KINDS = ("record-item", "document", "condition", "role", "organization")
_DATE_LABEL = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ProvisionRef:
    law: str
    article: int
    branch: int | None = None
    paragraph: int | None = None
    item: int | None = None


def _law_slug(law: str) -> str:
    try:
        return LAW_SLUGS[law]
    except KeyError:
        raise KeyError(f"未知の法令です（vocab.LAW_SLUGS に足してください）: {law}") from None


def business_iri(slug: str) -> URIRef:
    return KD[slug]


def step_iri(business: str, step: int) -> URIRef:
    return KD[f"{business}/step/{step}"]


def item_iri(business: str, step: int, position: tuple[int, ...]) -> URIRef:
    return KD[f"{business}/step/{step}/item/{'.'.join(str(p) for p in position)}"]


def law_iri(law: str) -> URIRef:
    return KD[f"law/{_law_slug(law)}"]


def article_iri(ref: ProvisionRef) -> URIRef:
    art = str(ref.article) if ref.branch is None else f"{ref.article}-{ref.branch}"
    return KD[f"law/{_law_slug(ref.law)}/art/{art}"]


def provision_iri(ref: ProvisionRef) -> URIRef:
    path = str(article_iri(ref))
    if ref.paragraph is not None:
        path += f"/para/{ref.paragraph}"
    if ref.item is not None:
        path += f"/item/{ref.item}"
    return URIRef(path)


def version_iri(provision: URIRef, label: str) -> URIRef:
    if label != "manual" and not _DATE_LABEL.match(label):
        raise ValueError(f"版のラベルは manual か YYYY-MM-DD: {label}")
    return URIRef(f"{provision}/version/{label}")


def amendment_iri(era: str, year: int, number: int) -> URIRef:
    return KD[f"amendment/{era}{year}-{number}"]


def manual_source_iri(row_id: str) -> URIRef:
    return KD[f"source/manual/{row_id}"]


def egov_source_iri(slug: str) -> URIRef:
    return KD[f"source/egov/{slug}"]


def rule_iri(business: str, slug: str) -> URIRef:
    return KD[f"rule/{business}/{slug}"]


def derived_iri(slug: str) -> URIRef:
    return KD[f"derived/{slug}"]


def vocab_iri(kind: str, slug: str) -> URIRef:
    if kind not in VOCAB_KINDS:
        raise ValueError(f"語彙の種類が不明です: {kind}")
    return KD[f"{kind}/{slug}"]


def activity_iri(run_id: str) -> URIRef:
    return KD[f"activity/{run_id}"]


# ── 短い ID ────────────────────────────────────────────────────────────


def _law_short(parts: list[str]) -> str:
    out = ["LAW", parts[0].upper()]
    rest = parts[1:]
    tags = {"para": "P", "item": "I", "version": "V"}
    if rest[:1] == ["art"]:
        out.append(rest[1])
        rest = rest[2:]
    for key, val in zip(rest[::2], rest[1::2], strict=True):
        out.append(tags[key] + val.replace("-", "").upper())
    return "-".join(o.upper() for o in out)


def short_id(iri: URIRef) -> str:
    path = str(iri).removeprefix(str(KD))
    if path == str(iri):
        raise ValueError(f"kd: の IRI ではありません: {iri}")
    p = path.split("/")
    head = p[0]
    if head == "law":
        return _law_short(p[1:])
    if head == "source" and len(p) == 3:
        return "SRC-" + p[2].upper() if p[1] == "manual" else "SRC-EGOV-" + p[2].upper()
    if head in ("amendment", "derived", "activity", *VOCAB_KINDS) and len(p) == 2:
        return f"{head}-{p[1]}".upper()
    if head == "rule" and len(p) == 3:
        return f"RULE-{p[1]}-{p[2]}".upper()
    if len(p) == 1 and "-" not in head:
        return head.upper()
    if len(p) == 3 and p[1] == "step":
        return f"{head.upper()}-S{p[2]}"
    if len(p) == 5 and p[1] == "step" and p[3] == "item":
        return f"{head.upper()}-S{p[2]}-I{p[4]}"
    raise ValueError(f"短い ID を作れない IRI です: {iri}")


def _law_from_short(tokens: list[str]) -> URIRef:
    i = 0
    while i < len(tokens) and tokens[i].isalpha():
        i += 1
    path = "law/" + "-".join(tokens[:i]).lower()
    rest = tokens[i:]
    if rest and rest[0].isdigit():
        art = rest[0]
        rest = rest[1:]
        if rest and rest[0].isdigit():
            art += "-" + rest[0]
            rest = rest[1:]
        path += f"/art/{art}"
    names = {"P": "para", "I": "item", "V": "version"}
    for tok in rest:
        val = tok[1:].lower()
        if tok[0] == "V" and len(val) == 8 and val.isdigit():
            val = f"{val[:4]}-{val[4:6]}-{val[6:]}"
        path += f"/{names[tok[0]]}/{val}"
    return KD[path]


def iri_from_short_id(sid: str) -> URIRef:
    tokens = sid.split("-")
    head = tokens[0]
    low = sid.lower()
    if head == "LAW":
        return _law_from_short(tokens[1:])
    if head == "SRC":
        if tokens[1] == "EGOV":
            return egov_source_iri("-".join(tokens[2:]).lower())
        return manual_source_iri("-".join(tokens[1:]).lower())
    if head == "RULE":
        return rule_iri(tokens[1].lower(), "-".join(tokens[2:]).lower())
    for kind in ("record-item", "amendment", "derived", "activity", *VOCAB_KINDS):
        if low.startswith(kind + "-"):
            rest = sid[len(kind) + 1 :]
            if kind == "amendment":
                return KD[f"amendment/{rest}"]
            return KD[f"{kind}/{rest.lower()}"]
    m = re.fullmatch(r"([A-Z]+)(?:-S(\d+))?(?:-I([\d.]+))?", sid)
    if not m:
        raise ValueError(f"短い ID を解釈できません: {sid}")
    biz, step, pos = m.group(1).lower(), m.group(2), m.group(3)
    if step is None:
        return business_iri(biz)
    if pos is None:
        return step_iri(biz, int(step))
    return item_iri(biz, int(step), tuple(int(x) for x in pos.split(".")))
