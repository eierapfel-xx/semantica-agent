"""事案データの派生値（日数・年齢）の計算。仕様 §4.6。"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import jpholiday
from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, XSD

from semantica_agent.ids import ProvisionRef, article_iri, derived_iri, short_id
from semantica_agent.namespaces import KOS, bind_prefixes

logger = logging.getLogger(__name__)

PERIOD_SLUG = "birth-filing-period"
NEW_YEAR_CLOSED = ((12, 29), (12, 30), (12, 31), (1, 1), (1, 2), (1, 3))


class DeriveError(ValueError):
    pass


@dataclass(frozen=True)
class PeriodRule:
    days: int
    count_first_day: bool
    extend_on_holiday: bool


@dataclass(frozen=True)
class DerivedDef:
    slug: str
    output: str
    inputs: tuple[str, ...]
    label_ja: str
    basis: tuple[ProvisionRef, ...]


DERIVED_VALUES: tuple[DerivedDef, ...] = (
    DerivedDef(
        "days-from-marriage-to-birth",
        "daysFromMarriageToBirth",
        ("parentsMarriageDate", "childBirthDate"),
        "婚姻の成立から出生までの日数",
        (ProvisionRef("民法", 772),),
    ),
    DerivedDef(
        "days-from-prev-marriage-end-to-birth",
        "daysFromPrevMarriageEndToBirth",
        ("motherPrevMarriageEndDate", "childBirthDate"),
        "前婚の解消から出生までの日数",
        (ProvisionRef("民法", 772),),
    ),
    DerivedDef(
        "filing-deadline",
        "filingDeadline",
        ("childBirthDate",),
        "出生届の届出期間の末日",
        (ProvisionRef("戸籍法", 49), ProvisionRef("戸籍法", 43)),
    ),
    DerivedDef(
        "days-late",
        "daysLate",
        ("filingDate", "filingDeadline"),
        "届出期間を過ぎた日数（期間内なら 0）",
        (ProvisionRef("戸籍法", 49),),
    ),
    DerivedDef(
        "mother-age-at-birth",
        "motherAgeAtBirth",
        ("motherBirthDate", "childBirthDate"),
        "出生時の母の年齢",
        (),
    ),
    DerivedDef(
        "child-age-at-filing",
        "childAgeAtFiling",
        ("childBirthDate", "filingDate"),
        "届出時の子の年齢",
        (),
    ),
)


def is_closed_day(d: date) -> bool:
    if not jpholiday.year_holidays(d.year):
        raise DeriveError(f"{d.year} 年の祝日のデータがありません")
    return d.weekday() >= 5 or jpholiday.is_holiday(d) or (d.month, d.day) in NEW_YEAR_CLOSED


def filing_deadline(event: date, rule: PeriodRule) -> date:
    end = event + timedelta(days=rule.days - 1 if rule.count_first_day else rule.days)
    while rule.extend_on_holiday and is_closed_day(end):
        end += timedelta(days=1)
    return end


def days_between(a: date, b: date) -> int:
    return (b - a).days


def age_on(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def read_period_rule(ontology: Graph, slug: str = PERIOD_SLUG) -> PeriodRule:
    node = derived_iri(slug)
    values = [
        ontology.value(node, KOS[p]) for p in ("periodDays", "countFirstDay", "extendOnHoliday")
    ]
    if any(v is None for v in values):
        raise DeriveError(f"届出期間の定義（{slug}）がオントロジーにありません")
    days, first, extend = (v.toPython() for v in values)
    return PeriodRule(int(days), bool(first), bool(extend))


def derived_definitions_graph() -> Graph:
    g = bind_prefixes(Graph())
    for d in DERIVED_VALUES:
        n = derived_iri(d.slug)
        g.add((n, RDF.type, KOS.DerivedValue))
        g.add((n, DCTERMS.identifier, Literal(short_id(n))))
        g.add((n, RDFS.label, Literal(d.label_ja, lang="ja")))
        g.add((n, KOS.reviewStatus, KOS.HumanReviewed))
        g.add((n, KOS.sourceKind, KOS.Speculation))
        g.add(
            (n, RDFS.comment, Literal("推測：計算の定義はコードで決めた（仕様 §4.6）", lang="ja"))
        )
        for i in d.inputs:
            g.add((n, KOS.derivedFromProperty, KOS[i]))
        for ref in d.basis:
            g.add((n, KOS.citesProvision, article_iri(ref)))
    return g


def _compute(d: DerivedDef, vals: list, rule: PeriodRule):
    calc: dict[str, Callable] = {
        "daysFromMarriageToBirth": lambda a, b: days_between(a, b),
        "daysFromPrevMarriageEndToBirth": lambda a, b: days_between(a, b),
        "filingDeadline": lambda a: filing_deadline(a, rule),
        "daysLate": lambda f, dl: max(0, days_between(dl, f)),
        "motherAgeAtBirth": lambda a, b: age_on(a, b),
        "childAgeAtFiling": lambda a, b: age_on(a, b),
    }
    return calc[d.output](*vals)


def derive(case: Graph, case_iri: URIRef, ontology: Graph) -> Graph:
    rule = read_period_rule(ontology)
    g = bind_prefixes(Graph())
    for t in case:
        g.add(t)
    for d in DERIVED_VALUES:  # 定義の順に計算する（filingDeadline → daysLate）
        vals = [g.value(case_iri, KOS[i]) for i in d.inputs]
        if any(v is None for v in vals):
            continue
        value = _compute(d, [v.toPython() for v in vals], rule)
        lit = Literal(value, datatype=XSD.date) if isinstance(value, date) else Literal(value)
        g.add((case_iri, KOS[d.output], lit))
        node = URIRef(f"{case_iri}/derived/{d.slug}")
        g.add((node, RDF.type, PROV.Entity))
        g.add((node, PROV.value, lit))
        g.add((node, PROV.wasGeneratedBy, derived_iri(d.slug)))
        for i in d.inputs:
            g.add((node, PROV.wasDerivedFrom, KOS[i]))
        logger.debug("派生値 %s = %s", d.output, value)
    return g
