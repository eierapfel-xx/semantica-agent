"""整合性シェイプと出生届の判定ルールの LLM 下書き（仕様 §4.5・§4.7・§5.6）。"""

import logging
import re
from dataclasses import dataclass
from string import Template

from pyshacl import validate
from rdflib import RDF, RDFS, Graph
from rdflib.namespace import SH
from semantica.semantic_extract.providers import create_provider

from semantica_agent.ids import rule_iri, short_id
from semantica_agent.llm_provider import PROVIDER_NAME
from semantica_agent.namespaces import KD, KOS
from semantica_agent.schema_gen import prompt_path
from semantica_agent.vocab import ENUM_INDIVIDUALS

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:turtle|ttl)?\s*(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class RuleSpec:
    id: str
    slug: str
    check: str
    rule: str
    outcome: str
    version: str | None  # 版が決まっていれば説明。None なら underVersion は任意


RULE_TABLE: tuple[RuleSpec, ...] = (
    RuleSpec(
        "B1",
        "filing-place",
        "届出地に該当しているか",
        "届出地が、本籍地・届出人の所在地・出生地のいずれか",
        "Reject",
        "手順書時点＝現行（戸籍法25・51条）",
    ),
    RuleSpec(
        "B2",
        "notifier",
        "届出人は届出義務者又は届出の資格を有する者か",
        "届出人の資格が、嫡出かどうかに応じた義務者・資格者に入る",
        "Reject",
        "手順書時点＝現行（戸籍法52条）",
    ),
    RuleSpec(
        "B3",
        "birth-certificate",
        "必要な添付書類は揃っているか",
        "出生証明書が無い → 法務局へ受理照会",
        "NeedsInquiry",
        "手順書時点＝現行（戸籍法49条3項）",
    ),
    RuleSpec(
        "B4a",
        "legitimacy-manual",
        "続き柄・嫡出子か（手順書の基準）",
        "婚姻後200日以上・前婚解消後300日以内で嫡出推定。婚姻後200日未満の出生は推定されない嫡出子として嫡出子の届出を認める。届書の続き柄・父と比べる",
        "NeedsCorrection",
        "民法772条の手順書時点の版（2024-03-31 以前の出生）",
    ),
    RuleSpec(
        "B4b",
        "legitimacy-current",
        "続き柄・嫡出子か（現行の基準）",
        "婚姻中の出生は夫の子と推定。前婚解消後300日以内でも、出生までに母が再婚していれば再婚後の夫の子と推定。届書の続き柄・父と比べる",
        "NeedsCorrection",
        "民法772条の 2024-04-01 の版（2024-04-01 以後の出生）",
    ),
    RuleSpec(
        "B4c",
        "legitimacy-diff",
        "手順書と現行で結論が違う",
        "2024-04-01 以後の出生で、手順書の基準と現行の基準の結論が違えば知らせる",
        "Info",
        None,
    ),
    RuleSpec(
        "B5",
        "birth-record-match",
        "生まれたとき・ところが出生証明書と一致しているか",
        "届書と出生証明書の出生日・時刻・場所が違う",
        "NeedsCorrection",
        None,
    ),
    RuleSpec(
        "B6",
        "school-age",
        "学齢に達した子の出生届",
        "childAgeAtFiling が学齢（満6歳）以上 → 法務局へ受理照会",
        "NeedsInquiry",
        "手順書時点",
    ),
    RuleSpec(
        "B7",
        "mother-age",
        "母の生年月日（50歳以上）",
        "motherAgeAtBirth が 50 以上 → 照会の対象になりうる",
        "NeedsInquiry",
        "手順書時点",
    ),
    RuleSpec(
        "B8",
        "family-register",
        "入る戸籍は存在するか",
        "familyRegisterExists が false",
        "Reject",
        None,
    ),
    RuleSpec(
        "B9",
        "filing-period",
        "届出期間内の届出か",
        "daysLate が 1 以上 → 遅延理由書を求め、簡易裁判所に通知",
        "AdditionalProcedure",
        None,
    ),
    RuleSpec(
        "B10", "address", "住所は存在する場所か", "addressExists が false", "NeedsCorrection", None
    ),
    RuleSpec(
        "B11",
        "record-items",
        "記入漏れ（受付(1)①）",
        "必要な記載事項（kos:requiresRecordItem）が recordedItem に無ければ列挙",
        "NeedsCorrection",
        None,
    ),
    RuleSpec(
        "B12",
        "non-honseki",
        "非本籍地での届出（受付(2)、工程5）",
        "届出地が本籍地でない → 公用請求と本籍地への送付",
        "AdditionalProcedure",
        None,
    ),
)


def extract_turtle(text: str) -> str:
    m = _FENCE.search(text)
    return (m.group(1) if m else text).strip()


def _local(iri) -> str:
    return str(iri).split("#")[-1]


def _items_summary(instances: Graph, business: str = "birth") -> str:
    lines = []
    prefix = str(KD[f"{business}/step/"])
    for cls in (KOS.ReviewCheck, KOS.Task, KOS.StepItem):
        for item in sorted(instances.subjects(RDF.type, cls)):
            if not str(item).startswith(prefix):
                continue
            cites = ", ".join(
                sorted(short_id(p) for p in instances.objects(item, KOS.citesProvision))
            )
            label = instances.value(item, RDFS.label) or ""
            kind = _local(cls)
            lines.append(
                f"- {short_id(item)}（{item.n3()}）[{kind}] {label} 根拠: {cites or 'なし'}"
            )
    return "\n".join(lines) or "（なし）"


def _versions_summary(laws: Graph) -> str:
    lines = []
    for v in sorted(laws.subjects(RDF.type, KOS.ProvisionVersion)):
        status = laws.value(v, KOS.versionStatus)
        attrs = [
            f"{p}={laws.value(v, KOS[p])}"
            for p in ("validFrom", "validUntil")
            if laws.value(v, KOS[p])
        ]
        kind = _local(status) if status else ""
        lines.append(f"- {short_id(v)}（{v.n3()}）{kind} {' '.join(attrs)}")
    return "\n".join(lines) or "（なし）"


def _rules_table() -> str:
    return "\n".join(
        f"- {r.id}：IRI {rule_iri('birth', r.slug).n3()}／審査項目「{r.check}」／ルール：{r.rule}"
        f"／判定 kos:{r.outcome}／版：{r.version or '指定なし'}"
        for r in RULE_TABLE
    )


def build_rules_prompt(instances: Graph, laws: Graph, schema_text: str) -> str:
    return Template(prompt_path("rules").read_text(encoding="utf-8")).substitute(
        schema=schema_text,
        checks=_items_summary(instances),
        versions=_versions_summary(laws),
        rules=_rules_table(),
    )


def build_integrity_prompt(schema_text: str) -> str:
    return Template(prompt_path("integrity").read_text(encoding="utf-8")).substitute(
        schema=schema_text
    )


def _ask_turtle(prompt: str, provider: str, **kw) -> tuple[str, str | None]:
    llm = create_provider(provider, **kw)
    ttl = extract_turtle(llm.generate(prompt))
    return ttl, getattr(llm, "last_model", None)


def generate_integrity_shapes(schema_text: str, provider: str = PROVIDER_NAME, **kw):
    return _ask_turtle(build_integrity_prompt(schema_text), provider, **kw)


def generate_rules(
    instances: Graph, laws: Graph, schema_text: str, provider: str = PROVIDER_NAME, **kw
):
    return _ask_turtle(build_rules_prompt(instances, laws, schema_text), provider, **kw)


def _check_rules(g: Graph) -> list[str]:
    errors = []
    outcomes = {KOS[o] for o in ENUM_INDIVIDUALS["outcome"]}
    for r in RULE_TABLE:
        node = rule_iri("birth", r.slug)
        if (node, RDF.type, KOS.JudgmentRule) not in g:
            errors.append(f"{r.id}: ルール {node.n3()} がありません")
            continue
        if g.value(node, KOS.implementsCheck) is None:
            errors.append(f"{r.id}: kos:implementsCheck がありません")
        if g.value(node, KOS.outcome) not in outcomes:
            errors.append(f"{r.id}: kos:outcome が不正です")
        if r.version and g.value(node, KOS.underVersion) is None:
            errors.append(f"{r.id}: kos:underVersion がありません")
        shape = g.value(node, KOS.shape)
        if shape is None or not (
            {(shape, RDF.type, SH.NodeShape), (shape, RDF.type, SH.PropertyShape)} & set(g)
        ):
            errors.append(f"{r.id}: kos:shape の先にシェイプがありません")
    return errors


def check_shapes_text(ttl: str, *, require_rules: bool) -> list[str]:
    try:
        g = Graph().parse(data=ttl, format="turtle")
    except Exception as e:
        return [f"Turtle として読めません: {e}"]
    try:
        validate(Graph(), shacl_graph=g, meta_shacl=True, advanced=True)
    except Exception as e:
        return [f"SHACL のシェイプとして不正です: {e}"]
    return _check_rules(g) if require_rules else []
