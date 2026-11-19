from semantica_agent.core.vocab import (
    AUX_PROPERTIES,
    BUSINESS_SLUGS,
    CONDITION_SLUGS,
    DOCUMENT_SLUGS,
    ENUM_INDIVIDUALS,
    LAW_ALIASES,
    LAW_SLUGS,
    ORGANIZATION_SLUGS,
    RECORD_ITEM_SLUGS,
    REQUIRED_CLASSES,
    REQUIRED_PROPERTIES,
    ROLE_SLUGS,
)


def test_required_names_follow_case_rules():
    assert all(n[0].isupper() and n.isascii() for n in REQUIRED_CLASSES)
    assert all(n[0].islower() and n.isascii() for n in REQUIRED_PROPERTIES)


def test_required_classes_cover_spec():
    assert {
        "Business",
        "ProcedureStep",
        "StepItem",
        "Task",
        "ReviewCheck",
        "Condition",
        "DocumentType",
        "RecordItem",
        "PartyRole",
        "Organization",
        "Law",
        "LegalProvision",
        "ProvisionVersion",
        "LegalAmendment",
        "SourceReference",
        "JudgmentRule",
        "DerivedValue",
        "Filing",
        "BirthFiling",
    } <= REQUIRED_CLASSES.keys()


def test_required_properties_cover_case_side():
    assert {
        "filingDate",
        "childBirthDate",
        "statedRelationship",
        "statedFather",
        "certBirthDate",
        "motherRemarriedBeforeBirth",
        "citesProvision",
        "underVersion",
        "outcome",
    } <= REQUIRED_PROPERTIES.keys()


def test_aux_properties_are_included_in_required():
    assert {"partOf", "pdfPage", "rowId", "quote", "periodDays"} <= AUX_PROPERTIES.keys()
    assert AUX_PROPERTIES.keys() <= REQUIRED_PROPERTIES.keys()


def test_enum_individuals():
    assert ENUM_INDIVIDUALS["outcome"] == (
        "Reject",
        "NeedsCorrection",
        "NeedsInquiry",
        "AdditionalProcedure",
        "Info",
    )
    assert ENUM_INDIVIDUALS["reviewStatus"] == ("LlmDraft", "HumanReviewed", "HumanEdited")


def test_business_slugs():
    assert BUSINESS_SLUGS["戸籍届出（出生）"] == "birth"
    assert BUSINESS_SLUGS["戸籍謄本等の交付"] == "certificate"


def test_law_alias_resolves_to_known_law():
    assert LAW_ALIASES["住基法"] == "住民基本台帳法"
    assert all(v in LAW_SLUGS for v in LAW_ALIASES.values())


def test_slugs_are_unique_and_ascii():
    for table in (
        LAW_SLUGS,
        DOCUMENT_SLUGS,
        CONDITION_SLUGS,
        ROLE_SLUGS,
        ORGANIZATION_SLUGS,
        RECORD_ITEM_SLUGS,
        BUSINESS_SLUGS,
    ):
        assert len(set(table.values())) == len(table)
        assert all(s.isascii() and s == s.lower() for s in table.values())
