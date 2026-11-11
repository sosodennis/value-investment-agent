import json
from datetime import UTC, date, datetime

import pytest
from fundamental_service.contracts import (
    IdentityV1,
    IdentityResolutionRequestV1,
    IdentityResolutionV1,
    IdentitySourceEvidenceV1,
)
from fundamental_service.issuer_identity import (
    IdentityResolutionError,
    resolve_issuer_identity,
    validate_original_filing_identity,
)
from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.serialization import sha256_digest
from pydantic import ValidationError


def _original_identity_facts():
    values = {
        "EntityCentralIndexKey": "0000320193",
        "EntityRegistrantName": "Apple Inc.",
        "EntityIncorporationStateCountryCode": "CA",
        "DocumentType": "10-K",
        "DocumentPeriodEndDate": "2024-09-28",
        "TradingSymbol": "AAPL",
        "Security12bTitle": "Common Stock",
    }
    facts = tuple(
        ParsedXbrlFactV1(
            concept=f"dei:{concept}",
            namespace_uri="http://xbrl.sec.gov/dei/2024",
            value=value,
            context_id="original-annual",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier="0000320193",
            period_start=date(2023, 10, 1),
            period_end=date(2024, 9, 28),
        )
        for concept, value in values.items()
    )
    return (
        *facts,
        facts[0].model_copy(
            update={
                "concept": "us-gaap:Revenues",
                "namespace_uri": "http://fasb.org/us-gaap/2024",
                "value": "1",
                "is_numeric": True,
                "unit": "iso4217:USD",
                "consolidation_scope": "consolidated",
            }
        ),
    )


def _check_original(facts=None, **identity_changes):
    identity = IdentityV1(
        **{
            "issuer_id": "0000320193",
            "issuer_name": "Apple Inc.",
            "domicile": "US",
            "reporting_basis": "us-gaap",
            "currency": "USD",
            "security_id": "AAPL",
            "share_class": "Common Stock",
            **identity_changes,
        }
    )
    validate_original_filing_identity(
        identity,
        cik="0000320193",
        ticker="AAPL",
        accepted_at=datetime(2024, 11, 1, tzinfo=UTC),
        facts=facts if facts is not None else _original_identity_facts(),
    )


def test_original_identity_uses_only_original_dei_with_no_current_directory():
    facts = _original_identity_facts()
    _check_original(facts)
    _check_original(tuple(reversed(facts)))
    _check_original((*facts, facts[0]))


def _class_scoped_original():
    securities = {"dei:TradingSymbol", "dei:Security12bTitle"}
    facts = tuple(
        fact.model_copy(
            update={
                "context_id": "common-class",
                "dimensions": (
                    ("us-gaap:StatementClassOfStockAxis", "us-gaap:CommonStockMember"),
                ),
                "consolidation_scope": "segmented",
                "security_scope": "segmented",
            }
        )
        if fact.concept in securities
        else fact
        for fact in _original_identity_facts()
    )
    title = next(f for f in facts if f.concept == "dei:Security12bTitle")
    return (
        *facts,
        title.model_copy(
            update={
                "context_id": "listed-note",
                "dimensions": (
                    ("us-gaap:StatementClassOfStockAxis", "issuer:NotesDue2027Member"),
                ),
                "value": "2.000% Notes due 2027",
            }
        ),
    )


def test_original_identity_selects_ticker_and_title_in_one_class_context():
    facts = _class_scoped_original()
    _check_original(facts)
    _check_original(tuple(reversed(facts)))
    _check_original((*facts, facts[-2]))


@pytest.mark.parametrize(
    "change",
    [
        {"context_id": "different-context"},
        {"period_start": date(2024, 1, 1)},
        {"dimensions": ()},
    ],
)
def test_original_identity_cannot_pair_a_title_from_another_class_context(change):
    facts = tuple(
        fact.model_copy(update=change)
        if fact.concept == "dei:Security12bTitle" and fact.value == "Common Stock"
        else fact
        for fact in _class_scoped_original()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(facts)
    assert error.value.code == "HISTORICAL_IDENTITY_MISSING"


def test_original_identity_rejects_the_same_ticker_in_multiple_class_contexts():
    facts = _class_scoped_original()
    symbol = next(f for f in facts if f.concept == "dei:TradingSymbol")
    with pytest.raises(IdentityResolutionError) as error:
        _check_original((*facts, symbol.model_copy(update={"context_id": "class-b"})))
    assert error.value.code == "HISTORICAL_IDENTITY_CONFLICT"


def test_original_identity_pairs_reused_ticker_with_its_exact_security_title():
    facts = _class_scoped_original()
    symbol = next(f for f in facts if f.concept == "dei:TradingSymbol")
    note = facts[-1]
    reused_symbol = symbol.model_copy(
        update={"context_id": note.context_id, "dimensions": note.dimensions}
    )
    actual = (*facts, reused_symbol)
    _check_original(actual)
    _check_original(tuple(reversed(actual)))
    _check_original((*actual, reused_symbol))


def test_original_identity_rejects_multiple_complete_contexts_with_the_same_title():
    facts = _class_scoped_original()
    common = tuple(f for f in facts if f.context_id == "common-class")
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(
            (
                *facts,
                *(f.model_copy(update={"context_id": "second-common"}) for f in common),
            )
        )
    assert error.value.code == "HISTORICAL_IDENTITY_CONFLICT"


def test_original_identity_rejects_conflicting_titles_for_a_reused_ticker():
    facts = _class_scoped_original()
    symbol = next(f for f in facts if f.concept == "dei:TradingSymbol")
    note = facts[-1]
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(
            (
                *facts,
                symbol.model_copy(
                    update={
                        "context_id": note.context_id,
                        "dimensions": note.dimensions,
                    }
                ),
                note.model_copy(update={"value": "A conflicting title"}),
            )
        )
    assert error.value.code == "HISTORICAL_IDENTITY_CONFLICT"


@pytest.mark.parametrize(
    "change",
    [
        {"namespace_uri": "http://example.test/dei/2024"},
        {"entity_identifier": "0000320194"},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "issuer:USA"),)},
        {
            "dimensions": (
                ("us-gaap:StatementClassOfStockAxis", "us-gaap:CommonStockMember"),
                ("us-gaap:StatementBusinessSegmentsAxis", "issuer:USA"),
            )
        },
    ],
)
def test_original_class_identity_keeps_namespace_entity_and_dimension_guards(change):
    facts = tuple(
        fact.model_copy(update=change) if fact.context_id == "common-class" else fact
        for fact in _class_scoped_original()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(facts)
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer_id": "0000320194"},
        {"issuer_name": "A renamed current company"},
        {"security_id": "NEW"},
        {"share_class": "Inferred common class"},
    ],
)
def test_original_identity_rejects_unproved_issuer_or_security(changes):
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(**changes)
    assert error.value.code == "HISTORICAL_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    "changes",
    [
        {"namespace_uri": "http://example.test/dei/2024"},
        {"namespace_uri": None},
        {"entity_scheme": "http://example.test/CIK"},
        {"entity_identifier": "0000320194"},
        {"dimensions": (("dei:SecurityAxis", "issuer:ClassA"),)},
        {"period_end": date(2025, 9, 28)},
        {"period_start": None},
        {"unit": "iso4217:USD"},
    ],
)
def test_original_identity_rejects_unproved_namespace_context_and_period(changes):
    facts = _original_identity_facts()
    facts = (facts[0].model_copy(update=changes), *facts[1:])
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(facts)
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


def test_original_identity_retains_missing_security_and_conflicting_originals():
    facts = _original_identity_facts()
    with pytest.raises(IdentityResolutionError) as missing:
        _check_original(tuple(f for f in facts if f.concept != "dei:TradingSymbol"))
    assert missing.value.code == "HISTORICAL_IDENTITY_MISSING"
    assert "dei:TradingSymbol" in str(missing.value)
    with pytest.raises(IdentityResolutionError) as conflict:
        _check_original((*facts, facts[0].model_copy(update={"value": "0000320194"})))
    assert conflict.value.code == "HISTORICAL_IDENTITY_CONFLICT"


@pytest.mark.parametrize(
    "changes",
    [
        {
            "dimensions": (
                ("gaap:StatementBusinessSegmentsAxis", "issuer:USDSubsidiary"),
            )
        },
        {"period_end": date(2023, 9, 28)},
        {"consolidation_scope": "unknown"},
        {"unit": "iso4217:USD/shares"},
    ],
)
def test_usd_in_other_scopes_or_periods_does_not_prove_reporting_currency(changes):
    facts = _original_identity_facts()
    with pytest.raises(IdentityResolutionError) as error:
        _check_original((*facts[:-1], facts[-1].model_copy(update=changes)))
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


def test_original_reporting_currency_rejects_conflicting_consolidated_currencies():
    facts = _original_identity_facts()
    with pytest.raises(IdentityResolutionError) as error:
        _check_original((*facts, facts[-1].model_copy(update={"unit": "iso4217:EUR"})))
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


@pytest.mark.parametrize("missing", ["usd", "gaap", "domicile", "amendment"])
def test_original_identity_requires_supported_original_reporting_scope(missing):
    facts = tuple(
        f.model_copy(update={"unit": "iso4217:EUR"})
        if missing == "usd" and f.is_numeric
        else f.model_copy(update={"namespace_uri": "http://example.test/us-gaap"})
        if missing == "gaap" and f.is_numeric
        else f.model_copy(update={"value": "UK"})
        if missing == "domicile" and f.concept.endswith("IncorporationStateCountryCode")
        else f.model_copy(update={"value": "10-K/A"})
        if missing == "amendment" and f.concept == "dei:DocumentType"
        else f
        for f in _original_identity_facts()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(facts)
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


def valid_sources():
    ticker_directory = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
    }
    submissions = {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "stateOfIncorporation": "CA",
        "filings": {"recent": {"form": ["10-K", "10-Q"]}},
    }
    companyfacts = {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenue": {"units": {"USD": [{"val": 1}]}},
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [{"val": 1}]}
                },
            }
        },
    }
    return ticker_directory, submissions, companyfacts


def resolve(*, ticker="aapl", sources=None):
    ticker_directory, submissions, companyfacts = sources or valid_sources()
    return resolve_issuer_identity(
        IdentityResolutionRequestV1(ticker=ticker),
        ticker_directory=ticker_directory,
        submissions=submissions,
        companyfacts=companyfacts,
    )


def test_known_issuer_resolves_with_selected_ticker_as_opaque_series_key():
    identity = resolve()

    assert identity.issuer_id == "0000320193"
    assert identity.issuer_name == "Apple Inc."
    assert identity.domicile == "US"
    assert identity.reporting_basis == "us-gaap"
    assert identity.currency == "USD"
    assert identity.security_id == "AAPL"
    assert identity.share_class == "AAPL"


def test_known_issuer_allows_unrelated_foreign_currency_facts_with_usd_reporting():
    ticker_directory, submissions, companyfacts = valid_sources()
    companyfacts["facts"]["us-gaap"]["DebtInstrumentFaceAmount"] = {
        "units": {"EUR": [{"val": 550_000_000}]}
    }

    identity = resolve(sources=(ticker_directory, submissions, companyfacts))

    assert identity.currency == "USD"


def test_selected_ticker_is_normalized_and_rejected_if_not_supported():
    assert IdentityResolutionRequestV1(ticker=" brk-b ").ticker == "BRK-B"
    with pytest.raises(ValidationError):
        IdentityResolutionRequestV1(ticker="AAPL/CLASS")


def test_unknown_ticker_is_explicitly_unresolved():
    with pytest.raises(IdentityResolutionError) as error:
        resolve(ticker="MSFT")

    assert error.value.code == "ISSUER_IDENTITY_UNRESOLVED"
    assert error.value.status_code == 404


def test_duplicate_ticker_mapping_is_explicitly_ambiguous():
    ticker_directory, submissions, companyfacts = valid_sources()
    ticker_directory["1"] = {
        "cik_str": 320194,
        "ticker": "AAPL",
        "title": "Another issuer",
    }

    with pytest.raises(IdentityResolutionError) as error:
        resolve(sources=(ticker_directory, submissions, companyfacts))

    assert error.value.code == "ISSUER_IDENTITY_AMBIGUOUS"
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    ("source_index", "field", "value"),
    [
        (1, "cik", "0000000001"),
        (1, "tickers", ["MSFT"]),
        (2, "cik", "0000000001"),
        (2, "entityName", "Different Corp"),
    ],
)
def test_mismatched_issuer_evidence_fails_closed(source_index, field, value):
    sources = list(valid_sources())
    sources[source_index] = dict(sources[source_index])
    sources[source_index][field] = value

    with pytest.raises(IdentityResolutionError) as error:
        resolve(sources=tuple(sources))

    assert error.value.code == "ISSUER_IDENTITY_MISMATCH"
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    ("source_index", "mutate"),
    [
        (1, lambda value: value.update(stateOfIncorporation="UK")),
        (1, lambda value: value["filings"]["recent"].update(form=["20-F"])),
        (2, lambda value: value["facts"].update({"us-gaap": {}})),
        (
            2,
            lambda value: value["facts"]["us-gaap"]["Revenue"].update(
                {"units": {"EUR": [{"val": 1}]}}
            ),
        ),
    ],
)
def test_unsupported_domicile_basis_or_currency_fails_closed(source_index, mutate):
    sources = list(valid_sources())
    sources[source_index] = dict(sources[source_index])
    if source_index == 1:
        sources[source_index]["filings"] = {
            "recent": dict(sources[source_index]["filings"]["recent"])
        }
    else:
        sources[source_index]["facts"] = {
            namespace: dict(facts)
            for namespace, facts in sources[source_index]["facts"].items()
        }
        sources[source_index]["facts"]["us-gaap"]["Revenue"] = {
            "units": dict(sources[source_index]["facts"]["us-gaap"]["Revenue"]["units"])
        }
    mutate(sources[source_index])

    with pytest.raises(IdentityResolutionError) as error:
        resolve(sources=tuple(sources))

    assert error.value.code == "ISSUER_IDENTITY_UNSUPPORTED"
    assert error.value.status_code == 422


def test_resolution_digest_binds_identity_and_all_source_evidence():
    now = datetime(2026, 11, 7, tzinfo=UTC)
    sources = tuple(
        IdentitySourceEvidenceV1(
            source_id=source_id,
            source_uri=f"https://www.sec.gov/{source_id}",
            content_hash="a" * 64,
            captured_at=now,
            available_at=now,
            media_type="application/json",
            byte_count=1,
        )
        for source_id in (
            "sec-company-tickers",
            "sec-submissions",
            "sec-companyfacts",
        )
    )
    payload = {
        "ticker": "AAPL",
        "identity": resolve(),
        "mapping_version": "sec-issuer-identity-v1",
        "source_evidence": sources,
    }
    result = IdentityResolutionV1(
        **payload,
        resolution_digest=sha256_digest(
            {
                **payload,
                "identity": payload["identity"].model_dump(mode="json"),
                "source_evidence": [
                    source.model_dump(mode="json") for source in sources
                ],
            }
        ),
    )

    changed_payload = result.model_dump(mode="json")
    changed_payload["source_evidence"][0]["content_hash"] = "b" * 64
    with pytest.raises(ValidationError, match="resolution_digest"):
        IdentityResolutionV1.model_validate_json(json.dumps(changed_payload))
