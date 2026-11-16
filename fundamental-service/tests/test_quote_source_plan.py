"""Original identity compiles dated quote requests without granting source rights."""

from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from fundamental_service.contracts import IdentityV1
from fundamental_service.original_source_plan import AutomaticQuoteSourceTemplateV1
from fundamental_service.quote_source_plan import AutomaticDailyQuoteRequestTemplateV1
from fundamental_service.serialization import canonical_bytes
from fundamental_service.twelve_quote_source import (
    TWELVE_CLOSE_PROFILE,
    TWELVE_CLOSE_SOURCE,
    TWELVE_TERMS,
)
from test_original_preparation import case, execute
from test_original_source_plan import (
    _terms_request,
    compiler_case,
    configuration,
    issuer_market_policy_template,
)


def quote_template():
    return AutomaticDailyQuoteRequestTemplateV1(
        source_id=TWELVE_CLOSE_SOURCE,
        uri_template=(
            "https://api.twelvedata.com/time_series?symbol={security_id}"
            "&interval=1day&country=US&type=Common%20Stock&format=JSON"
            "&date={observation_date}&adjust=none&dp=11&mic_code=XNAS"
        ),
        source_profile=TWELVE_CLOSE_PROFILE,
        terms_reference=TWELVE_TERMS,
    )


@pytest.fixture
def identity():
    return IdentityV1(
        issuer_id="synthetic-issuer",
        issuer_name="Synthetic quote compiler fixture",
        domicile="US",
        reporting_basis="us-gaap",
        security_id="EXAMPLE",
        share_class="common",
        currency="USD",
    )


@pytest.mark.parametrize(
    "timestamp,observation,as_of",
    (
        ("2026-11-14T10:49:46+00:00", "2026-11-13", "2026-11-13T05:00:00+00:00"),
        ("2026-11-16T10:00:00+00:00", "2026-11-13", "2026-11-13T05:00:00+00:00"),
        ("2026-11-14T02:00:00+00:00", "2026-11-12", "2026-11-12T05:00:00+00:00"),
        ("2026-03-10T04:00:00+00:00", "2026-03-09", "2026-03-09T04:00:00+00:00"),
        ("2026-01-01T05:00:00+00:00", "2025-12-31", "2025-12-31T05:00:00+00:00"),
    ),
)
def test_previous_complete_new_york_weekday_is_fixed_and_zoned(
    identity, timestamp, observation, as_of
):
    template = quote_template()
    valuation_at = datetime.fromisoformat(timestamp)
    request, selection = template.render(identity=identity, valuation_at=valuation_at)
    assert parse_qs(urlsplit(request.uri).query)["date"] == [observation]
    assert selection.as_of.isoformat() == as_of
    assert selection.as_of < valuation_at
    assert selection.issuer_id == identity.issuer_id
    assert selection.security_id == identity.security_id
    local = valuation_at.astimezone(timezone(timedelta(hours=8)))
    assert canonical_bytes((request, selection)) == canonical_bytes(
        template.render(identity=identity, valuation_at=local)
    )


@pytest.mark.parametrize(
    "uri",
    (
        "http://example.com/{security_id}/{observation_date}",
        "https://user:secret@example.com/{security_id}/{observation_date}",
        "https://example.com/{security_id}/{observation_date}#fragment",
        "https://example.com/{security_id}",
        "https://example.com/{security_id}/{unknown}",
        "https://example.com/{security_id!r}/{observation_date}",
        "https://example.com/{security_id:>10}/{observation_date}",
        "https://example.com/{security_id}/{observation_date",
    ),
)
def test_quote_template_rejects_unsafe_or_undated_requests(uri):
    with pytest.raises(ValueError):
        AutomaticDailyQuoteRequestTemplateV1.model_validate(
            {**quote_template().model_dump(), "uri_template": uri}
        )


def test_template_refuses_naive_time_and_non_usd_and_encodes_security(identity):
    template = quote_template()
    with pytest.raises(ValueError, match="zoned"):
        template.render(identity=identity, valuation_at=datetime(2026, 11, 14))
    with pytest.raises(ValueError, match="USD"):
        template.render(
            identity=identity.model_copy(update={"currency": "HKD"}),
            valuation_at=datetime(2026, 11, 14, tzinfo=UTC),
        )
    security = "EXAMPLE&date=2099-01-01"
    request, _ = template.render(
        identity=identity.model_copy(update={"security_id": security}),
        valuation_at=datetime(2026, 11, 14, tzinfo=UTC),
    )
    assert parse_qs(urlsplit(request.uri).query)["symbol"] == [security]
    assert parse_qs(urlsplit(request.uri).query)["date"] != ["2099-01-01"]


@pytest.mark.parametrize("mode", ("quote_only", "shared_terms", "conflicting_terms"))
def test_saved_original_compiles_quote_identity_and_deduplicates_shared_terms(
    tmp_path, monkeypatch, mode
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    market = issuer_market_policy_template() if mode != "quote_only" else None
    terms = (
        market.source_plan_template.market_sources[0].terms[0]
        if market is not None
        else _terms_request("twelve-data-terms", TWELVE_TERMS)
    )
    if mode == "conflicting_terms":
        terms = terms.model_copy(update={"source_profile": "conflicting-profile"})
    quote = AutomaticQuoteSourceTemplateV1(
        request=quote_template(),
        terms=(terms,),
        source_use_policy_version="synthetic-unapproved-policy-v1",
        source_use_policy_digest="a" * 64,
    )
    config = configuration(issuer_market_policy_template=market).model_copy(
        update={"quote_source_template": quote}
    )
    compiler, request = compiler_case(value, prepared, config)
    calls = value.state.provider_calls, value.state.parser_calls
    if mode == "conflicting_terms":
        with pytest.raises(ValueError, match="conflicting profile"):
            compiler.execute(request)
        assert calls == (value.state.provider_calls, value.state.parser_calls)
        return
    result, publication = compiler.execute(request)
    plan = result.plan
    assert plan is not None and publication.wrote and not result.issue_codes
    admission = next(item for item in plan.source_admissions if item.kind == "quote")
    assert admission.quote_selection.issuer_id == value.expected_identity.issuer_id
    assert admission.quote_selection.security_id == value.expected_identity.security_id
    assert admission.policy_digest == quote.source_use_policy_digest
    assert admission.policy_version == quote.source_use_policy_version
    sources = [
        item
        for item in plan.public_sources
        if item.digest in admission.source_request_digests
    ]
    assert len(sources) == 1
    assert parse_qs(urlsplit(sources[0].uri).query)["symbol"] == [
        value.expected_identity.security_id
    ]
    assert (
        len([item for item in plan.public_sources if item.uri == terms.uri_template])
        == 1
    )
    assert result == compiler.execute(request)[0]
    assert not compiler.execute(request)[1].wrote
    assert calls == (value.state.provider_calls, value.state.parser_calls)


def test_absent_quote_template_keeps_existing_configuration_bytes():
    config = configuration()
    assert config.quote_source_template is None
    assert "quote_source_template" not in config.model_dump()
