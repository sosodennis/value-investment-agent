from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
)
from fundamental_service.dqc_applicability import (
    DqcFilingContextV1,
    dqc_applicability_policy_digest,
)
from fundamental_service.fiscal_source_contracts import (
    FiscalFilingV1,
    FiscalIssuerClaimV1,
    FiscalOriginalSourceV1,
    evaluate_fiscal_issuer,
)
from fundamental_service.serialization import canonical_bytes

CIK = "0000789019"
ACCESSION = "0000950170-24-008814"
PRIMARY_DOCUMENT = "synthetic-filing.htm"
PERIOD_END = date(2024, 6, 30)
DECISION_AT = datetime(2026, 11, 25, tzinfo=UTC)
PARSER_INPUT_HASH = "b" * 64


def _profile() -> ArelleValidationProfileV1:
    return ArelleValidationProfileV1(
        profile_id="synthetic-sec-efm-dqc-v31",
        validation_mode="sec-efm-dqc",
        dqc_applicability_digest=dqc_applicability_policy_digest(),
        edgar_plugin_dir=Path("/synthetic/edgar"),
        xule_plugin_dir=Path("/synthetic/xule"),
        dqc_ruleset_path=Path("/synthetic/dqc.zip"),
        edgar_plugin_sha256="1" * 64,
        xule_plugin_sha256="2" * 64,
        dqc_ruleset_sha256="3" * 64,
    )


def _fact(
    concept: str,
    value: str,
    *,
    numeric: bool = False,
    unit: str | None = None,
    namespace_uri: str = "http://xbrl.sec.gov/dei/2024",
    period_start: date | None = date(2024, 1, 1),
    period_end: date | None = PERIOD_END,
    instant: date | None = None,
    entity_identifier: str = CIK,
    dimensions: tuple[tuple[str, str], ...] = (),
    consolidation_scope: str = "consolidated",
) -> ParsedXbrlFactV1:
    return ParsedXbrlFactV1(
        concept=concept,
        namespace_uri=namespace_uri,
        value=value,
        context_id="synthetic-context",
        unit=unit,
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier=entity_identifier,
        period_start=period_start,
        period_end=period_end,
        instant=instant,
        dimensions=dimensions,
        is_numeric=numeric,
        consolidation_scope=consolidation_scope,
    )


def _case(
    *, form: str = "10-Q", period_end: date | None = None
) -> tuple[ArelleParseReportV1, FiscalFilingV1, FiscalOriginalSourceV1]:
    period_end = period_end or (date(2024, 12, 31) if form == "10-K" else PERIOD_END)
    period_focus = "Q2" if form == "10-Q" else "FY"
    facts = tuple(
        _fact(concept, value, period_end=period_end)
        for concept, value in (
            ("dei:DocumentPeriodEndDate", period_end.isoformat()),
            ("dei:DocumentType", form),
            ("dei:EntityCentralIndexKey", CIK),
            ("dei:EntityRegistrantName", "Synthetic Issuer"),
            ("dei:AmendmentFlag", "false"),
            ("dei:DocumentFiscalYearFocus", str(period_end.year)),
            ("dei:DocumentFiscalPeriodFocus", period_focus),
        )
    )
    monetary = _fact(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "123.45",
        numeric=True,
        unit="iso4217:USD",
        namespace_uri="http://fasb.org/us-gaap/2024",
        period_end=period_end,
    )
    profile = _profile()
    filing_date = (
        date(period_end.year + 1, 2, 15)
        if form == "10-K"
        else date(period_end.year, period_end.month + 1, min(period_end.day, 28))
    )
    accepted_at = datetime.combine(filing_date, datetime.min.time(), UTC)
    captured_at = accepted_at + timedelta(days=1)
    accession = ACCESSION if form == "10-Q" else "0000789019-25-000001"
    uri = (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(CIK)}/{accession.replace('-', '')}/{PRIMARY_DOCUMENT}"
    )
    context = DqcFilingContextV1(
        issuer_id=CIK,
        accession_number=accession,
        filing_date=filing_date,
        policy_digest=profile.dqc_applicability_digest,
    )
    report = ArelleParseReportV1(
        filing_path=uri,
        parser_version=profile.arelle_version,
        taxonomy_version="us-gaap-2024",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        facts=(*facts, monetary),
        validation_engines=("sec-efm", "dqc-us"),
        validation_evidence=(
            "strict-sec-efm-profile-selected",
            "dqc-dqcrt-checks-completed",
            context.evidence_marker(),
        ),
        parsed_at=captured_at,
        offline=True,
        network_attempt_count=0,
        source_content_hash=PARSER_INPUT_HASH,
        taxonomy_cache_hash="c" * 64,
        dqc_filing_context=context,
    )
    filing = FiscalFilingV1(
        cik=CIK,
        accession_number=accession,
        form=form,
        filing_date=filing_date,
        accepted_at=accepted_at,
        report_period_end=period_end,
        primary_document=PRIMARY_DOCUMENT,
        is_xbrl=True,
        is_inline_xbrl=False,
    )
    source = FiscalOriginalSourceV1(
        cik=CIK,
        accession_number=accession,
        uri=uri,
        content_hash="a" * 64,
        parser_input_hash=PARSER_INPUT_HASH,
        form=form,
        available_at=accepted_at,
        captured_at=captured_at,
        http_status=200,
    )
    return report, filing, source


def _evaluate(
    report: ArelleParseReportV1,
    filing: FiscalFilingV1,
    source: FiscalOriginalSourceV1,
) -> FiscalIssuerClaimV1:
    return evaluate_fiscal_issuer(
        report,
        filing=filing,
        source=source,
        decision_at=DECISION_AT,
        request_digest="1" * 64,
    )


@pytest.mark.parametrize("form", ("10-Q", "10-K"))
def test_synthetic_fiscal_claim_matches_only_typed_dei_and_usd_gaap_witness(
    form: str,
) -> None:
    report, filing, source = _case(form=form)

    claim = _evaluate(report, filing, source)

    assert claim.status == "matched"
    assert claim.identity is not None
    assert claim.identity.issuer_id == CIK
    assert claim.identity.reporting_basis == "us-gaap"
    assert claim.identity.currency == "USD"
    assert claim.report_period_end == filing.report_period_end
    assert claim.fiscal_period_focus == ("Q2" if form == "10-Q" else "FY")
    assert (
        claim.output_digest
        == hashlib.sha256(
            canonical_bytes(claim.model_dump(mode="json", exclude={"output_digest"}))
        ).hexdigest()
    )


def test_accession_prefix_does_not_define_issuer_cik() -> None:
    report, filing, source = _case()

    assert filing.accession_number[:10] != filing.cik
    assert _evaluate(report, filing, source).identity.issuer_id == CIK


@pytest.mark.parametrize("value", ("0000000001", "issuer-cik", ""))
def test_dei_cik_value_must_match_filing_cik(value: str) -> None:
    report, filing, source = _case()
    report = report.model_copy(
        update={
            "facts": tuple(
                fact.model_copy(update={"value": value})
                if fact.concept == "dei:EntityCentralIndexKey"
                else fact
                for fact in report.facts
            )
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.identity is None
    assert "FISCAL_DEI_CIK_MISMATCH" in claim.issue_codes


def test_missing_dei_cik_is_refused() -> None:
    report, filing, source = _case()
    report = report.model_copy(
        update={
            "facts": tuple(
                fact
                for fact in report.facts
                if fact.concept != "dei:EntityCentralIndexKey"
            )
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert {"FISCAL_DEI_MISSING", "FISCAL_DEI_CIK_MISMATCH"}.issubset(claim.issue_codes)


@pytest.mark.parametrize(
    "concept, value, expected_code",
    (
        ("dei:DocumentPeriodEndDate", "2024-06-29", "FISCAL_DEI_PERIOD_END_MISMATCH"),
        ("dei:DocumentFiscalYearFocus", "not-a-year", "FISCAL_DEI_YEAR_FOCUS_INVALID"),
        ("dei:DocumentFiscalPeriodFocus", "FY", "FISCAL_DEI_PERIOD_FOCUS_INVALID"),
    ),
)
def test_dei_period_and_fiscal_focus_must_match_filing(
    concept: str, value: str, expected_code: str
) -> None:
    report, filing, source = _case()
    report = report.model_copy(
        update={
            "facts": tuple(
                fact.model_copy(update={"value": value})
                if fact.concept == concept
                else fact
                for fact in report.facts
            )
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.metadata_status == "refused"
    assert expected_code in claim.metadata_issue_codes


@pytest.mark.parametrize(
    "change",
    (
        {"unit": "iso4217:USD"},
        {"dimensions": (("us-gaap:ProductAxis", "us-gaap:ProductMember"),)},
        {"consolidation_scope": "segmented"},
        {"entity_identifier": "0000000001"},
    ),
)
def test_nonconsolidated_or_dimensional_dei_cannot_establish_identity(
    change: dict[str, object],
) -> None:
    report, filing, source = _case()
    report = report.model_copy(
        update={
            "facts": tuple(
                fact.model_copy(update=change)
                if fact.concept == "dei:EntityRegistrantName"
                else fact
                for fact in report.facts
            )
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.identity is None
    assert "FISCAL_DEI_CONTEXT_MISMATCH" in claim.metadata_issue_codes


@pytest.mark.parametrize(
    "change, expected_code",
    (
        ("missing", "FISCAL_US_GAAP_MONETARY_MISSING"),
        ("ifrs", "FISCAL_US_GAAP_MONETARY_MISSING"),
        ("eur", "FISCAL_US_GAAP_CURRENCY_UNSUPPORTED"),
        ("nonfinite", "FISCAL_US_GAAP_MONETARY_VALUE_INVALID"),
    ),
)
def test_identity_defaults_require_an_exact_usd_gaap_finite_observation(
    change: str, expected_code: str
) -> None:
    report, filing, source = _case()
    monetary = report.facts[-1]
    if change == "missing":
        facts = report.facts[:-1]
    else:
        update = {
            "value": "NaN" if change == "nonfinite" else monetary.value,
            "unit": "iso4217:EUR" if change == "eur" else monetary.unit,
            "namespace_uri": "http://ifrs.org/ifrs/2024"
            if change == "ifrs"
            else monetary.namespace_uri,
        }
        facts = (*report.facts[:-1], monetary.model_copy(update=update))
    report = report.model_copy(update={"facts": facts})

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.identity is None
    assert expected_code in claim.issue_codes


def test_multiple_consolidated_currency_units_do_not_establish_usd() -> None:
    report, filing, source = _case()
    eur = report.facts[-1].model_copy(update={"unit": "iso4217:EUR", "value": "1"})
    report = report.model_copy(update={"facts": (*report.facts, eur)})

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert "FISCAL_US_GAAP_CURRENCY_UNSUPPORTED" in claim.issue_codes


@pytest.mark.parametrize(
    "change, expected_code",
    (
        ({"offline": False}, "FISCAL_OFFLINE_REQUIRED"),
        ({"validation_profile_digest": "d" * 64}, "FISCAL_ORIGINAL_SOURCE_MISMATCH"),
    ),
)
def test_report_execution_and_profile_identity_are_required(
    change: dict[str, object], expected_code: str
) -> None:
    report, filing, source = _case()
    report = report.model_copy(update=change)

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert expected_code in claim.issue_codes


def test_source_identity_mismatch_is_retained_as_refusal() -> None:
    report, filing, source = _case()
    source = source.model_copy(update={"form": "10-K"})

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.metadata_status == "refused"
    assert "FISCAL_ORIGINAL_SOURCE_MISMATCH" in claim.metadata_issue_codes


def test_missing_validation_completion_is_refused() -> None:
    report, filing, source = _case()
    report = report.model_copy(
        update={"validation_evidence": (report.dqc_filing_context.evidence_marker(),)}
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.metadata_status == "matched"
    assert claim.identity is not None
    assert "VALIDATION_EVIDENCE_MISSING" in claim.issue_codes


def test_non_xbrl_filing_is_refused_even_with_matching_dei() -> None:
    report, filing, source = _case()
    filing = filing.model_copy(update={"is_xbrl": False})

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.metadata_status == "refused"
    assert "FISCAL_XBRL_REQUIRED" in claim.issue_codes


def test_active_dqc_finding_remains_a_refusal() -> None:
    report, filing, source = _case()
    report = report.model_copy(
        update={
            "findings": (
                ArelleFindingV1(
                    code="DQC.US.0015.5970",
                    severity="error",
                    message="synthetic active DQC finding",
                ),
            )
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert claim.metadata_status == "matched"
    assert claim.metadata_issue_codes == ()
    assert claim.identity is not None
    assert claim.identity.issuer_id == CIK
    assert "FISCAL_STRICT_VALIDATION_BLOCKED" in claim.issue_codes


def test_amendment_lineage_must_match_and_unverified_amendment_is_refused() -> None:
    report, filing, source = _case()
    predecessor = "0000789019-24-000001"
    filing = filing.model_copy(
        update={
            "is_amendment": True,
            "amends_accession": predecessor,
            "amendment_scope": "valuation_relevant",
        }
    )
    source = source.model_copy(
        update={
            "is_amendment": True,
            "amends_accession": predecessor,
            "amendment_scope": "valuation_relevant",
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert "FISCAL_AMENDMENT_LINEAGE_UNVERIFIED" in claim.issue_codes


def test_amendment_source_predecessor_mismatch_is_refused() -> None:
    report, filing, source = _case()
    filing = filing.model_copy(
        update={
            "is_amendment": True,
            "amends_accession": "0000789019-24-000001",
            "amendment_scope": "valuation_relevant",
        }
    )
    source = source.model_copy(
        update={
            "is_amendment": True,
            "amends_accession": "0000789019-24-000002",
            "amendment_scope": "valuation_relevant",
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.status == "refused"
    assert "FISCAL_ORIGINAL_SOURCE_MISMATCH" in claim.issue_codes


def test_fiscal_timestamps_require_timezone() -> None:
    _, filing, source = _case()

    with pytest.raises(ValidationError):
        FiscalFilingV1.model_validate(
            {**filing.model_dump(), "accepted_at": datetime(2024, 7, 31)}
        )
    with pytest.raises(ValidationError):
        FiscalOriginalSourceV1.model_validate(
            {**source.model_dump(), "captured_at": datetime(2024, 8, 1)}
        )


def test_claim_digest_tampering_is_rejected() -> None:
    report, filing, source = _case()
    claim = _evaluate(report, filing, source)
    tampered = claim.model_copy(update={"output_digest": "f" * 64})

    with pytest.raises(ValidationError, match="digest mismatch"):
        FiscalIssuerClaimV1.model_validate(tampered.model_dump(mode="python"))


def test_parser_hash_mismatch_is_a_strict_input_error() -> None:
    report, filing, source = _case()
    source = source.model_copy(update={"parser_input_hash": "e" * 64})

    with pytest.raises(ValueError, match="parser input hash"):
        _evaluate(report, filing, source)


def test_inverted_dei_duration_cannot_establish_fiscal_identity() -> None:
    report, filing, source = _case()
    report = report.model_copy(
        update={
            "facts": tuple(
                fact.model_copy(
                    update={
                        "period_start": filing.report_period_end + timedelta(days=1)
                    }
                )
                if fact.concept.startswith("dei:")
                else fact
                for fact in report.facts
            )
        }
    )

    claim = _evaluate(report, filing, source)

    assert claim.metadata_status == "refused"
    assert claim.status == "refused"
    assert claim.identity is None
    assert "FISCAL_DEI_CONTEXT_MISMATCH" in claim.metadata_issue_codes


@pytest.mark.parametrize("primary_document", (".", ".."))
def test_fiscal_filing_rejects_directory_segments_as_primary_document(
    primary_document: str,
) -> None:
    _, filing, _ = _case()

    with pytest.raises(ValidationError, match="primary document must be a file"):
        FiscalFilingV1.model_validate(
            {**filing.model_dump(), "primary_document": primary_document}
        )
