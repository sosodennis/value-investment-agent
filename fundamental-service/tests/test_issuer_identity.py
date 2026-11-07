import json
from datetime import UTC, datetime

import pytest
from fundamental_service.contracts import (
    IdentityResolutionRequestV1,
    IdentityResolutionV1,
    IdentitySourceEvidenceV1,
)
from fundamental_service.issuer_identity import (
    IdentityResolutionError,
    resolve_issuer_identity,
)
from fundamental_service.serialization import sha256_digest
from pydantic import ValidationError


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
            lambda value: value["facts"]["us-gaap"]["Revenue"]["units"].update(
                {"EUR": [{"val": 1}]}
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
