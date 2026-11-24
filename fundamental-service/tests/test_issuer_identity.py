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
    DEFAULT_ORIGINAL_HISTORY_IDENTITY_POLICY,
    DEFAULT_ORIGINAL_SECURITY_POLICY,
    IdentityResolutionError,
    original_history_identity_key,
    original_identity_evidence_facts,
    resolve_issuer_identity,
    resolve_original_filing_identity,
    validate_original_filing_identity,
)
from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.serialization import sha256_digest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "field,changed",
    [
        ("issuer_name", "Apple, Inc."),
        ("issuer_name", "Other Inc."),
        ("issuer_id", "0000000001"),
        ("domicile", "CA"),
        ("reporting_basis", "ifrs"),
        ("security_id", "OTHER"),
        ("share_class", "Class B common stock"),
        ("currency", "CAD"),
    ],
)
def test_history_name_policy_preserves_every_substantive_identity_difference(
    field, changed
):
    identity = resolve_original_filing_identity(
        cik="0000320193",
        accepted_at=datetime(2024, 11, 1, tzinfo=UTC),
        facts=_original_identity_facts(),
    )
    policy = DEFAULT_ORIGINAL_HISTORY_IDENTITY_POLICY
    different = identity.model_copy(update={field: changed})
    assert original_history_identity_key(
        identity, policy
    ) != original_history_identity_key(different, policy)


def test_history_name_format_policy_is_explicit_and_does_not_change_original():
    identity = resolve_original_filing_identity(
        cik="0000320193",
        accepted_at=datetime(2024, 11, 1, tzinfo=UTC),
        facts=_original_identity_facts(),
    )
    formatted = identity.model_copy(update={"issuer_name": "  APPLE\tINC.  "})
    assert original_history_identity_key(identity, None) == identity
    assert original_history_identity_key(identity, None) != formatted
    policy = DEFAULT_ORIGINAL_HISTORY_IDENTITY_POLICY
    assert original_history_identity_key(
        identity, policy
    ) == original_history_identity_key(formatted, policy)
    assert formatted.issuer_name == "  APPLE\tINC.  "
    assert identity.issuer_name == "Apple Inc."


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


@pytest.mark.parametrize(
    "policy", (None, *(f"original-dei-paired-common-stock-v{i}" for i in range(2, 7)))
)
@pytest.mark.parametrize(
    "change",
    (
        "none",
        "mixed_currency",
        "other_period",
        "other_entity",
        "duplicate",
        "no_symbol",
    ),
)
def test_projected_facts_preserve_identity_and_exact_refusals(policy, change):
    facts = _original_identity_facts()
    monetary = facts[-1]
    changes = {
        "none": (),
        "mixed_currency": (monetary.model_copy(update={"unit": "iso4217:CAD"}),),
        "other_period": (
            monetary.model_copy(
                update={"unit": "iso4217:CAD", "period_end": date(2020, 1, 1)}
            ),
        ),
        "other_entity": (
            monetary.model_copy(
                update={"unit": "iso4217:CAD", "entity_identifier": "999"}
            ),
        ),
        "duplicate": (facts[0], facts[-1]),
        "no_symbol": (
            facts[0].model_copy(
                update={"concept": "dei:NoTradingSymbolFlag", "value": "true"}
            ),
        ),
    }
    facts = (*facts, *changes[change])
    unrelated = monetary.model_copy(
        update={
            "concept": "issuer:Unrelated",
            "namespace_uri": "https://example.com",
            "is_numeric": False,
        }
    )
    facts = (unrelated, *facts, unrelated)
    projected = original_identity_evidence_facts(facts)
    assert projected == facts[1:-1]
    assert all(a is b for a, b in zip(projected, facts[1:-1]))

    def outcome(values):
        try:
            return resolve_original_filing_identity(
                cik="0000320193",
                accepted_at=datetime(2024, 11, 1, tzinfo=UTC),
                facts=values,
                security_selection_policy=policy,
            )
        except IdentityResolutionError as error:
            return error.code, str(error)

    assert outcome(projected) == outcome(facts)


def test_projection_overflow_returns_complete_original_tuple():
    fact = _original_identity_facts()[0]
    facts = (fact,) * 4097
    assert original_identity_evidence_facts(facts) is facts


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


def _note_with_no_trading_symbol():
    facts = _class_scoped_original()
    note = facts[-1]
    return (
        *facts,
        note.model_copy(update={"concept": "dei:NoTradingSymbolFlag", "value": "true"}),
    )


def test_explicit_no_symbol_note_does_not_obscure_unique_common_stock():
    facts = _note_with_no_trading_symbol()
    identity = _resolve_original(
        facts, security_selection_policy="original-dei-paired-common-stock-v5"
    )
    assert identity.security_id == "AAPL"
    assert identity.share_class == "Common Stock"
    assert (
        _resolve_original(
            tuple(reversed((*facts, *facts))),
            security_selection_policy="original-dei-paired-common-stock-v5",
        )
        == identity
    )


@pytest.mark.parametrize(
    "namespace",
    (
        "http://xbrl.sec.gov/dei/2020-01-31",
        "http://xbrl.sec.gov/dei/2021",
        "http://xbrl.sec.gov/dei/2022",
        "http://xbrl.sec.gov/dei/2024",
    ),
)
def test_no_symbol_notes_use_the_original_dei_namespace(namespace):
    facts = tuple(
        fact.model_copy(update={"namespace_uri": namespace})
        if fact.concept.startswith("dei:")
        else fact
        for fact in _note_with_no_trading_symbol()
    )
    identity = _resolve_original(
        facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
    )
    assert identity.security_id == "AAPL"
    assert identity.share_class == "Common Stock"


@pytest.mark.parametrize(
    "namespace",
    (
        "http://xbrl.sec.gov/dei/2020-01-31",
        "http://xbrl.sec.gov/dei/2021",
        "http://xbrl.sec.gov/dei/2022",
    ),
)
def test_v5_keeps_historical_no_symbol_note_refusal(namespace):
    facts = tuple(
        fact.model_copy(update={"namespace_uri": namespace})
        if fact.concept.startswith("dei:")
        else fact
        for fact in _note_with_no_trading_symbol()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy="original-dei-paired-common-stock-v5"
        )
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize(
    "namespace",
    (
        "http://xbrl.sec.gov/dei/2020-01-31",
        "http://xbrl.sec.gov/dei/2021",
        "http://xbrl.sec.gov/dei/2022",
        "http://xbrl.sec.gov/dei/2024",
    ),
)
@pytest.mark.parametrize(
    "change",
    (
        {"namespace_uri": "http://xbrl.sec.gov/dei/2023"},
        {"namespace_uri": "https://example.test/dei/2024"},
        {"entity_identifier": "0000320194"},
        {"entity_scheme": "https://example.test/CIK"},
        {"dimensions": (("issuer:OtherAxis", "issuer:OtherMember"),)},
        {"value": "false"},
    ),
)
def test_no_symbol_notes_keep_exact_namespace_issuer_and_class_scope(namespace, change):
    facts = tuple(
        fact.model_copy(update={"namespace_uri": namespace})
        if fact.concept.startswith("dei:")
        else fact
        for fact in _note_with_no_trading_symbol()
    )
    facts = (*facts[:-1], facts[-1].model_copy(update=change))
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize(
    "policy",
    (
        "original-dei-paired-common-stock-v2",
        "original-dei-paired-common-stock-v3",
        "original-dei-paired-common-stock-v4",
    ),
)
def test_old_paired_policies_keep_no_symbol_note_refusal(policy):
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            _note_with_no_trading_symbol(), security_selection_policy=policy
        )
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize(
    "change",
    (
        {"value": "false"},
        {"value": "0"},
        {"value": "1"},
        {"value": " true "},
        {"value": "TRUE"},
        {"value": ""},
        {"entity_identifier": "0000320194"},
        {"entity_scheme": "https://example.test/CIK"},
        {"namespace_uri": "https://example.test/dei/2024"},
        {"namespace_uri": "http://xbrl.sec.gov/dei/2027"},
        {"namespace_uri": "http://xbrl.sec.gov/dei/2025"},
        {"period_end": date(2025, 9, 28)},
        {"period_start": None},
        {"unit": "xbrli:shares"},
        {"is_numeric": True},
        {"instant": date(2024, 9, 28)},
        {"context_id": "orphan-flag"},
        {"dimensions": ()},
    ),
)
def test_invalid_no_symbol_evidence_keeps_automatic_selection_unknown(change):
    facts = _note_with_no_trading_symbol()
    facts = (*facts[:-1], facts[-1].model_copy(update=change))
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize("contradiction", ("missing", "false_duplicate", "symbol"))
def test_no_symbol_note_requires_explicit_uncontradicted_evidence(contradiction):
    facts = _note_with_no_trading_symbol()
    if contradiction == "missing":
        facts = facts[:-1]
    elif contradiction == "false_duplicate":
        facts = (*facts, facts[-1].model_copy(update={"value": "false"}))
    else:
        facts = (
            *facts,
            facts[-1].model_copy(
                update={"concept": "dei:TradingSymbol", "value": "NOTE27"}
            ),
        )
    with pytest.raises(IdentityResolutionError):
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )


@pytest.mark.parametrize(
    "title", ("Class B Common Stock", "Preferred Stock", "Unknown security")
)
def test_no_symbol_flag_does_not_classify_another_equity_or_unknown_instrument(title):
    facts = tuple(
        f.model_copy(update={"value": title})
        if f.context_id == "listed-note" and f.concept == "dei:Security12bTitle"
        else f
        for f in _note_with_no_trading_symbol()
    )
    with pytest.raises(IdentityResolutionError):
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )


def test_no_symbol_note_cannot_reuse_the_common_stock_class_dimension():
    facts = tuple(
        f.model_copy(
            update={
                "dimensions": (
                    ("us-gaap:StatementClassOfStockAxis", "us-gaap:CommonStockMember"),
                )
            }
        )
        if f.context_id == "listed-note"
        else f
        for f in _note_with_no_trading_symbol()
    )
    with pytest.raises(IdentityResolutionError):
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
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


@pytest.mark.parametrize(
    "change",
    [
        {"namespace_uri": "http://example.test/dei/2024"},
        {"entity_scheme": "http://example.test/CIK"},
        {"entity_identifier": "0000320194"},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "issuer:USA"),)},
        {"period_end": date(2025, 9, 28)},
        {"period_start": None},
        {"unit": "iso4217:USD"},
        {"is_numeric": True},
    ],
)
def test_reused_ticker_cannot_disambiguate_using_an_invalid_other_security(change):
    facts = _class_scoped_original()
    symbol = next(f for f in facts if f.concept == "dei:TradingSymbol")
    note = facts[-1]
    reused_symbol = symbol.model_copy(
        update={"context_id": note.context_id, "dimensions": note.dimensions}
    )
    actual = tuple(
        fact.model_copy(update=change) if fact.context_id == note.context_id else fact
        for fact in (*facts, reused_symbol)
    )
    with pytest.raises(IdentityResolutionError) as error:
        _check_original(actual)
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


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


def _resolve_original(facts=None, **selectors):
    return resolve_original_filing_identity(
        cik="0000320193",
        accepted_at=datetime(2024, 11, 1, tzinfo=UTC),
        facts=_original_identity_facts() if facts is None else facts,
        **selectors,
    )


def test_resolve_original_security_without_supplied_identity_or_current_directory():
    facts = _class_scoped_original()
    identity = _resolve_original(facts)
    assert identity == IdentityV1(
        issuer_id="0000320193",
        issuer_name="Apple Inc.",
        security_id="AAPL",
        share_class="Common Stock",
        domicile="US",
        reporting_basis="us-gaap",
        currency="USD",
    )
    assert _resolve_original(tuple(reversed(facts))) == identity
    assert _resolve_original((*facts, *facts)) == identity
    assert (
        _resolve_original(facts, ticker="AAPL", share_class="common stock") == identity
    )


def _two_original_securities(*, reuse_ticker=False):
    facts = _class_scoped_original()
    common = tuple(f for f in facts if f.context_id == "common-class")
    return (
        *facts,
        *(
            fact.model_copy(
                update={
                    "context_id": "second-listed-class",
                    "dimensions": (
                        ("us-gaap:StatementClassOfStockAxis", "issuer:ClassBMember"),
                    ),
                    "value": ("AAPL" if reuse_ticker else "AAPL.B")
                    if fact.concept == "dei:TradingSymbol"
                    else "Class B Common Stock",
                }
            )
            for fact in common
        ),
    )


def test_multiple_original_securities_require_explicit_selection():
    facts = _two_original_securities()
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(facts)
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"
    assert (
        _resolve_original(facts, ticker="AAPL.B").share_class == "Class B Common Stock"
    )
    assert _resolve_original(facts, ticker="AAPL").share_class == "Common Stock"
    with pytest.raises(IdentityResolutionError) as absent:
        _resolve_original(facts, ticker="CURRENT")
    assert absent.value.code == "HISTORICAL_IDENTITY_MISMATCH"


def _common_and_reused_note():
    facts = _class_scoped_original()
    symbol = next(f for f in facts if f.concept == "dei:TradingSymbol")
    note = facts[-1]
    return (
        *facts,
        symbol.model_copy(
            update={"context_id": note.context_id, "dimensions": note.dimensions}
        ),
    )


@pytest.mark.parametrize(
    "title", ["Common Stock", "Common stock, $0.00000625 par value per share"]
)
def test_versioned_common_policy_resolves_a_ticker_reused_by_fixed_coupon_notes(title):
    facts = tuple(
        fact.model_copy(update={"value": title})
        if fact.concept == "dei:Security12bTitle" and fact.context_id == "common-class"
        else fact
        for fact in _common_and_reused_note()
    )
    with pytest.raises(IdentityResolutionError) as old:
        _resolve_original(facts)
    assert old.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"
    identity = _resolve_original(
        facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
    )
    assert identity.security_id == "AAPL" and identity.share_class == title
    assert (
        _resolve_original(
            tuple(reversed((*facts, *facts))),
            security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY,
        )
        == identity
    )
    assert (
        _resolve_original(
            facts,
            share_class="2.000% Notes due 2027",
            security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY,
        ).share_class
        == "2.000% Notes due 2027"
    )


@pytest.mark.parametrize(
    "title",
    ["Class B Common Stock", "Preferred Stock", "Unknown security", "Notes", ""],
)
def test_common_policy_keeps_other_or_unknown_classes_ambiguous(title):
    facts = tuple(
        fact.model_copy(update={"value": title})
        if fact.concept == "dei:Security12bTitle" and fact.context_id == "listed-note"
        else fact
        for fact in _common_and_reused_note()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert error.value.code in {
        "HISTORICAL_SECURITY_SELECTION_REQUIRED",
        "HISTORICAL_IDENTITY_MISSING",
    }


@pytest.mark.parametrize("reuse_ticker", [False, True])
def test_common_policy_does_not_choose_between_common_share_classes(reuse_ticker):
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            _two_original_securities(reuse_ticker=reuse_ticker),
            security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY,
        )
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize(
    "change",
    [
        {"namespace_uri": "http://example.test/dei/2024"},
        {"entity_identifier": "0000320194"},
        {"period_end": date(2023, 9, 28)},
        {"period_start": None},
        {"unit": "iso4217:USD"},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "issuer:USA"),)},
    ],
)
def test_common_policy_still_validates_the_unselected_note_context(change):
    facts = tuple(
        fact.model_copy(update=change) if fact.context_id == "listed-note" else fact
        for fact in _common_and_reused_note()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


def test_v1_common_policy_requires_the_standard_common_member_and_complete_pairs():
    facts = _common_and_reused_note()
    changed = tuple(
        fact.model_copy(
            update={
                "dimensions": (
                    ("us-gaap:StatementClassOfStockAxis", "issuer:CommonStockMember"),
                )
            }
        )
        if fact.context_id == "common-class"
        else fact
        for fact in facts
    )
    incomplete = (
        *facts,
        facts[-2].model_copy(update={"context_id": "unpaired-listed-note"}),
    )
    for observed in (changed, incomplete):
        with pytest.raises(IdentityResolutionError) as error:
            _resolve_original(
                observed,
                security_selection_policy="original-dei-single-common-stock-v1",
            )
        assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


def _common_and_distinct_note():
    return tuple(
        fact.model_copy(update={"value": "AAPL28"})
        if fact.context_id == "listed-note" and fact.concept == "dei:TradingSymbol"
        else fact
        for fact in _common_and_reused_note()
    )


@pytest.mark.parametrize(
    "title", ["Preferred Stock", "Unclassified security", "2.000% Notes due 2027"]
)
def test_paired_common_policy_refuses_single_non_common_without_explicit_selector(
    title,
):
    facts = tuple(
        f.model_copy(update={"value": title})
        if f.concept == "dei:Security12bTitle"
        else f
        for f in _original_identity_facts()
    )
    with pytest.raises(IdentityResolutionError) as caught:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert caught.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"
    for policy in (None, "original-dei-single-common-stock-v1"):
        assert (
            _resolve_original(facts, security_selection_policy=policy).share_class
            == title
        )
    assert (
        _resolve_original(
            facts,
            ticker="AAPL",
            security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY,
        ).share_class
        == title
    )


@pytest.mark.parametrize(
    "title",
    [
        "Common Stock",
        "Common Stock, par value $0.10 per share",
        "Common Stock, $0.0001 par value per share",
    ],
)
def test_paired_common_policy_uses_printed_title_for_custom_members_and_distinct_tickers(
    title,
):
    facts = tuple(
        fact.model_copy(
            update={
                "dimensions": (
                    (
                        "us-gaap:StatementClassOfStockAxis",
                        "issuer:UniquePrintedStockMember",
                    ),
                ),
                **({"value": title} if fact.concept == "dei:Security12bTitle" else {}),
            }
        )
        if fact.context_id == "common-class"
        else fact
        for fact in _common_and_distinct_note()
    )
    identity = _resolve_original(
        facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
    )
    assert identity.security_id == "AAPL" and identity.share_class == title
    assert (
        _resolve_original(
            tuple(reversed((*facts, *facts))),
            security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY,
        )
        == identity
    )
    for legacy in (None, "original-dei-single-common-stock-v1"):
        with pytest.raises(IdentityResolutionError) as caught:
            _resolve_original(facts, security_selection_policy=legacy)
        assert caught.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"
    assert (
        _resolve_original(
            facts,
            ticker="AAPL28",
            security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY,
        ).share_class
        == "2.000% Notes due 2027"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "unpaired_title",
        "unpaired_symbol",
        "conflicting_symbol",
        "conflicting_title",
        "unknown",
        "preferred",
        "second_common",
    ],
)
def test_paired_common_policy_requires_complete_unambiguous_security_pairs(fault):
    facts = _common_and_distinct_note()
    note_symbol = next(
        f
        for f in facts
        if f.context_id == "listed-note" and f.concept == "dei:TradingSymbol"
    )
    note_title = next(
        f
        for f in facts
        if f.context_id == "listed-note" and f.concept == "dei:Security12bTitle"
    )
    if fault == "unpaired_title":
        facts = tuple(f for f in facts if f != note_title)
    elif fault == "unpaired_symbol":
        facts = tuple(f for f in facts if f != note_symbol)
    elif fault == "conflicting_symbol":
        facts = (*facts, note_symbol.model_copy(update={"value": "OTHER"}))
    elif fault == "conflicting_title":
        facts = (
            *facts,
            note_title.model_copy(update={"value": "3.000% Notes due 2027"}),
        )
    else:
        title = {
            "unknown": "Unclassified security",
            "preferred": "Preferred Stock",
            "second_common": "Common Stock",
        }[fault]
        facts = tuple(
            f.model_copy(update={"value": title}) if f == note_title else f
            for f in facts
        )
    with pytest.raises(IdentityResolutionError) as caught:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert caught.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize(
    "change",
    [
        {"namespace_uri": "http://example.test/dei/2024"},
        {"entity_identifier": "0000320194"},
        {"period_end": date(2023, 9, 28)},
        {"unit": "iso4217:USD"},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "issuer:USA"),)},
        {"value": "invalid symbol"},
    ],
)
def test_paired_common_policy_validates_unselected_distinct_ticker_context(change):
    facts = tuple(
        f.model_copy(update=change)
        if f.context_id == "listed-note" and f.concept == "dei:TradingSymbol"
        else f
        for f in _common_and_distinct_note()
    )
    with pytest.raises(IdentityResolutionError) as caught:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert caught.value.code in {
        "HISTORICAL_SECURITY_SELECTION_REQUIRED",
        "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
    }


def test_reused_original_ticker_requires_title_and_keeps_ambiguous_context_refusal():
    facts = _two_original_securities(reuse_ticker=True)
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(facts, ticker="AAPL")
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"
    assert (
        _resolve_original(facts, share_class="Common Stock").share_class
        == "Common Stock"
    )
    assert (
        _resolve_original(facts, share_class="Class B Common Stock").share_class
        == "Class B Common Stock"
    )
    assert (
        _resolve_original(
            facts,
            share_class="Class B Common Stock",
            security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY,
        ).share_class
        == "Class B Common Stock"
    )
    common = tuple(f for f in facts if f.context_id == "common-class")
    with pytest.raises(IdentityResolutionError) as conflict:
        _resolve_original(
            (
                *facts,
                *(
                    f.model_copy(update={"context_id": "duplicate-class"})
                    for f in common
                ),
            ),
            share_class="Common Stock",
        )
    assert conflict.value.code == "HISTORICAL_IDENTITY_CONFLICT"


@pytest.mark.parametrize(
    "selector",
    [{"ticker": "aapl"}, {"ticker": ""}, {"share_class": ""}, {"share_class": "   "}],
)
def test_original_resolution_rejects_invalid_selectors(selector):
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(**selector)
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


@pytest.mark.parametrize(
    "concept",
    [
        "EntityRegistrantName",
        "TradingSymbol",
        "Security12bTitle",
        "EntityCentralIndexKey",
    ],
)
def test_original_resolution_preserves_missing_identity_roles(concept):
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            tuple(
                f for f in _original_identity_facts() if f.concept != f"dei:{concept}"
            )
        )
    assert error.value.code == "HISTORICAL_IDENTITY_MISSING"


@pytest.mark.parametrize(
    "change",
    [
        {"namespace_uri": "http://example.test/dei/2024"},
        {"entity_scheme": "http://example.test/CIK"},
        {"entity_identifier": "0000320194"},
        {"period_end": date(2025, 9, 28)},
        {"period_start": None},
        {"unit": "iso4217:USD"},
        {"is_numeric": True},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "issuer:USA"),)},
    ],
)
def test_original_resolution_cannot_bypass_ingestion_identity_scope(change):
    facts = tuple(
        f.model_copy(update=change) if f.concept == "dei:Security12bTitle" else f
        for f in _original_identity_facts()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(facts)
    assert error.value.code in {
        "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
        "HISTORICAL_IDENTITY_MISSING",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "iso4217:EUR"},
        {"namespace_uri": "http://example.test/us-gaap/2024"},
        {"entity_identifier": "0000320194"},
        {"consolidation_scope": "unknown"},
        {"period_end": date(2023, 9, 28)},
    ],
)
def test_original_resolution_requires_source_proof_of_usd_gaap_scope(change):
    facts = _original_identity_facts()
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original((*facts[:-1], facts[-1].model_copy(update=change)))
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


def test_original_resolution_rejects_conflicting_issuer_name_or_security_title():
    facts = _original_identity_facts()
    for concept in ("dei:EntityRegistrantName", "dei:Security12bTitle"):
        original = next(f for f in facts if f.concept == concept)
        with pytest.raises(IdentityResolutionError) as error:
            _resolve_original(
                (*facts, original.model_copy(update={"value": "Different name"}))
            )
        assert error.value.code in {
            "HISTORICAL_IDENTITY_CONFLICT",
            "HISTORICAL_SECURITY_SELECTION_REQUIRED",
        }
    with pytest.raises(IdentityResolutionError) as mismatch:
        _resolve_original(share_class="Unproved preferred stock")
    assert mismatch.value.code == "HISTORICAL_IDENTITY_MISMATCH"


@pytest.mark.parametrize("cik", ["", "320193", "0000320194", "００００３２０１９３"])
def test_original_resolution_requires_the_requested_original_cik(cik):
    with pytest.raises(IdentityResolutionError) as error:
        resolve_original_filing_identity(
            cik=cik,
            accepted_at=datetime(2024, 11, 1, tzinfo=UTC),
            facts=_original_identity_facts(),
        )
    assert error.value.code in {
        "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
        "HISTORICAL_IDENTITY_MISMATCH",
    }


@pytest.mark.parametrize(
    "title",
    (
        "Common Stock, par value $1",
        "Common Stock, $0.10 par value",
        "Common Stock, par value $0.001",
    ),
)
@pytest.mark.parametrize(
    "policy",
    ("original-dei-paired-common-stock-v3", "original-dei-paired-common-stock-v4"),
)
def test_paired_v3_accepts_printed_dollar_par_without_per_share(title, policy):
    facts = tuple(
        f.model_copy(update={"value": title})
        if f.context_id == "common-class" and f.concept == "dei:Security12bTitle"
        else f
        for f in _common_and_distinct_note()
    )
    identity = _resolve_original(facts, security_selection_policy=policy)
    assert identity.security_id == "AAPL" and identity.share_class == title
    assert (
        _resolve_original(
            tuple(reversed((*facts, *facts))),
            security_selection_policy=policy,
        )
        == identity
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy="original-dei-paired-common-stock-v2"
        )
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize(
    "title",
    (
        "Class A Common Stock, par value $1",
        "Preferred Stock, par value $1",
        "Common Stock, par value $1 convertible",
        "Common Stock, par value $-1",
        "Common Stock, par value EUR1",
        "Common Stock, par value $1 per unit",
    ),
)
def test_paired_v3_does_not_relax_class_economic_or_currency_scope(title):
    facts = tuple(
        f.model_copy(update={"value": title})
        if f.context_id == "common-class" and f.concept == "dei:Security12bTitle"
        else f
        for f in _common_and_distinct_note()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize("symbol", ("BOND 27", "OTHER 33", "X" * 25))
@pytest.mark.parametrize(
    "policy",
    ("original-dei-paired-common-stock-v3", "original-dei-paired-common-stock-v4"),
)
def test_v3_retains_unselected_note_source_symbol_without_stock_ticker_conversion(
    symbol,
    policy,
):
    facts = tuple(
        f.model_copy(update={"value": symbol})
        if f.context_id == "listed-note" and f.concept == "dei:TradingSymbol"
        else f
        for f in _common_and_distinct_note()
    )
    identity = _resolve_original(facts, security_selection_policy=policy)
    assert identity.security_id == "AAPL" and identity.share_class == "Common Stock"
    with pytest.raises(IdentityResolutionError):
        _resolve_original(
            facts, security_selection_policy="original-dei-paired-common-stock-v2"
        )


@pytest.mark.parametrize(
    "context,symbol",
    (
        ("common-class", "STOCK 1"),
        ("common-class", "X" * 16),
        ("listed-note", "bad symbol"),
        ("listed-note", "X" * 26),
        ("listed-note", "NOTE/27"),
        ("listed-note", "NOTE_27"),
    ),
)
def test_v3_preserves_selected_ticker_and_unselected_symbol_boundaries(context, symbol):
    facts = tuple(
        f.model_copy(update={"value": symbol})
        if f.context_id == context and f.concept == "dei:TradingSymbol"
        else f
        for f in _common_and_distinct_note()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(
            facts, security_selection_policy=DEFAULT_ORIGINAL_SECURITY_POLICY
        )
    assert error.value.code == "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED"


@pytest.mark.parametrize(
    "title", ("Common stock, no par value", "COMMON STOCK, NO PAR VALUE")
)
@pytest.mark.parametrize("representation", ("single", "distinct_note", "reused_note"))
@pytest.mark.parametrize(
    "policy",
    (
        "original-dei-paired-common-stock-v4",
        "original-dei-paired-common-stock-v5",
        "original-dei-paired-common-stock-v6",
    ),
)
def test_paired_v4_selects_explicit_no_par_common_stock(title, representation, policy):
    source = {
        "single": _original_identity_facts,
        "distinct_note": _common_and_distinct_note,
        "reused_note": _common_and_reused_note,
    }[representation]()
    facts = tuple(
        f.model_copy(update={"value": title})
        if f.concept == "dei:Security12bTitle" and "Notes" not in f.value
        else f
        for f in source
    )
    assert DEFAULT_ORIGINAL_SECURITY_POLICY == "original-dei-paired-common-stock-v6"
    identity = _resolve_original(facts, security_selection_policy=policy)
    assert identity.security_id == "AAPL" and identity.share_class == title
    assert (
        _resolve_original(
            tuple(reversed((*facts, *facts))),
            security_selection_policy=policy,
        )
        == identity
    )
    for policy in (
        "original-dei-paired-common-stock-v2",
        "original-dei-paired-common-stock-v3",
    ):
        with pytest.raises(IdentityResolutionError) as error:
            _resolve_original(facts, security_selection_policy=policy)
        assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"


@pytest.mark.parametrize(
    "title",
    (
        "Class A Common stock, no par value",
        "Preferred stock, no par value",
        "Common stock, no par value convertible",
        "Common stock, no par value per unit",
        "Common stock, no par value $1",
        "Common stock, par value",
        "Common stock, no stated value",
        "Common stock, no par value\nCommon stock",
    ),
)
@pytest.mark.parametrize(
    "policy",
    (
        "original-dei-paired-common-stock-v4",
        "original-dei-paired-common-stock-v5",
        "original-dei-paired-common-stock-v6",
    ),
)
def test_paired_v4_requires_the_complete_supported_printed_title(title, policy):
    facts = tuple(
        f.model_copy(update={"value": title})
        if f.concept == "dei:Security12bTitle"
        else f
        for f in _original_identity_facts()
    )
    with pytest.raises(IdentityResolutionError) as error:
        _resolve_original(facts, security_selection_policy=policy)
    assert error.value.code == "HISTORICAL_SECURITY_SELECTION_REQUIRED"
