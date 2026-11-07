import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from fundamental_service.app import create_app
from fundamental_service.contracts import IdentityResolutionV1, SourceRole
from fundamental_service.operations import OperationsConfig
from fundamental_service.sec_source import SecSourceError
from fundamental_service.snapshots import CapturedSource, FilesystemContentStore
from fundamental_service.source_acquisition import SecIdentityResolutionUseCase
from fundamental_service.testsupport import (
    TEST_SERVICE_TOKEN,
    auth_headers,
    make_internal_envelope,
)


def _json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode()


def _source_payloads():
    return {
        "sec-company-tickers": _json_bytes(
            {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        ),
        "sec-submissions": _json_bytes(
            {
                "cik": "0000320193",
                "name": "Apple Inc.",
                "tickers": ["AAPL"],
                "stateOfIncorporation": "CA",
                "filings": {"recent": {"form": ["10-K", "10-Q"]}},
            }
        ),
        "sec-companyfacts": _json_bytes(
            {
                "cik": 320193,
                "entityName": "Apple Inc.",
                "facts": {
                    "us-gaap": {
                        "Revenue": {"units": {"USD": [{"val": 1}]}},
                    }
                },
            }
        ),
    }


class _FakeSecAdapter:
    def __init__(self, *, fail_source=None):
        self.payloads = _source_payloads()
        self.fail_source = fail_source
        self.calls = []

    def _capture(self, source_id, uri, *, deadline_at):
        self.calls.append((source_id, deadline_at))
        if source_id == self.fail_source:
            raise SecSourceError(
                "SOURCE_TIMEOUT", "provider response included private detail"
            )
        return CapturedSource(
            source_id=source_id,
            uri=uri,
            role=SourceRole.ACQUISITION,
            content=self.payloads[source_id],
            media_type="application/json; charset=utf-8",
            http_status=200,
            available_at=datetime(2026, 11, 7, tzinfo=UTC),
            captured_at=datetime(2026, 11, 7, tzinfo=UTC),
            received_size=len(self.payloads[source_id]),
        )

    def capture_company_tickers(self, *, deadline_at):
        return self._capture(
            "sec-company-tickers",
            "https://www.sec.gov/files/company_tickers.json",
            deadline_at=deadline_at,
        )

    def capture_submissions(self, cik, *, deadline_at):
        assert str(int(cik)).zfill(10) == "0000320193"
        return self._capture(
            "sec-submissions",
            f"https://data.sec.gov/submissions/CIK{str(int(cik)).zfill(10)}.json",
            deadline_at=deadline_at,
        )

    def capture_company_facts(self, cik, *, deadline_at):
        assert str(int(cik)).zfill(10) == "0000320193"
        return self._capture(
            "sec-companyfacts",
            "https://data.sec.gov/api/xbrl/companyfacts/"
            f"CIK{str(int(cik)).zfill(10)}.json",
            deadline_at=deadline_at,
        )


class _AuditMetadata:
    def __init__(self):
        self.audits = []

    def publish_source_audit(self, **audit):
        self.audits.append(audit)


def _resolver(tmp_path: Path, adapter=None, *, allowed_orgs=("organization-test",)):
    adapter = adapter or _FakeSecAdapter()
    metadata = _AuditMetadata()
    content_store = FilesystemContentStore(tmp_path / "content")
    resolver = SecIdentityResolutionUseCase(
        adapter=adapter,
        metadata=metadata,
        content_store=content_store,
        authorized_organizations=frozenset(allowed_orgs),
    )
    return resolver, adapter, metadata, content_store


def test_signed_identity_resolution_stores_sources_and_returns_bound_metadata(
    tmp_path,
):
    resolver, adapter, _, content_store = _resolver(tmp_path)
    client = TestClient(
        create_app(config=OperationsConfig.testing(), identity_resolution=resolver)
    )
    deadline_at = datetime.now(UTC) + timedelta(seconds=60)
    envelope = make_internal_envelope(
        {"ticker": " aapl "},
        correlation_id="identity-correlation",
        deadline_at=deadline_at,
    )

    response = client.post(
        "/v1/identity/resolve",
        headers=auth_headers(),
        json=envelope,
    )

    assert response.status_code == 200
    result = IdentityResolutionV1.model_validate_json(
        json.dumps(response.json()["result"])
    )
    assert response.json()["correlation_id"] == "identity-correlation"
    assert result.ticker == "AAPL"
    assert result.identity.issuer_id == "0000320193"
    assert {item.source_id for item in result.source_evidence} == {
        "sec-company-tickers",
        "sec-submissions",
        "sec-companyfacts",
    }
    assert [item[0] for item in adapter.calls] == [
        "sec-company-tickers",
        "sec-submissions",
        "sec-companyfacts",
    ]
    assert all(item[1] == deadline_at for item in adapter.calls)
    assert "provider response included private detail" not in response.text
    assert all(
        content_store.get(item.content_hash, media_type="application/json")
        == adapter.payloads[item.source_id]
        for item in result.source_evidence
    )
    assert all(
        source.decode() not in response.text for source in adapter.payloads.values()
    )


def test_invalid_signed_context_is_rejected_before_sec_access(tmp_path):
    resolver, adapter, _, _ = _resolver(tmp_path)
    client = TestClient(
        create_app(config=OperationsConfig.testing(), identity_resolution=resolver)
    )
    envelope = make_internal_envelope({"ticker": "AAPL"})
    envelope["context"]["signature"] = "0" * 64

    response = client.post(
        "/v1/identity/resolve", headers=auth_headers(), json=envelope
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_context_signature_invalid"
    assert adapter.calls == []


def test_identity_resolution_requires_authorized_organization(tmp_path):
    resolver, adapter, metadata, _ = _resolver(
        tmp_path, allowed_orgs=("organization-approved",)
    )
    client = TestClient(
        create_app(config=OperationsConfig.testing(), identity_resolution=resolver)
    )
    envelope = make_internal_envelope(
        {"ticker": "AAPL"}, organization_id="organization-denied"
    )

    response = client.post(
        "/v1/identity/resolve",
        headers=auth_headers(organization_id="organization-denied"),
        json=envelope,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "IDENTITY_RESOLUTION_NOT_AUTHORIZED"
    assert adapter.calls == []
    assert metadata.audits[-1]["outcome"] == "IDENTITY_RESOLUTION_NOT_AUTHORIZED"


def test_identity_resolution_uses_shared_sec_acquisition_rate_limit(tmp_path):
    resolver, adapter, _, _ = _resolver(tmp_path)
    client = TestClient(
        create_app(
            config=OperationsConfig(
                service_token=TEST_SERVICE_TOKEN,
                ingestion_rate_limit_per_minute=1,
            ),
            identity_resolution=resolver,
        )
    )
    headers = auth_headers()
    body = make_internal_envelope({"ticker": "AAPL"})

    first = client.post("/v1/identity/resolve", headers=headers, json=body)
    second = client.post("/v1/identity/resolve", headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "IDENTITY_RESOLUTION_RATE_LIMITED"
    assert len(adapter.calls) == 3


def test_unavailable_sec_source_returns_stable_redacted_error(tmp_path):
    resolver, adapter, metadata, _ = _resolver(
        tmp_path, _FakeSecAdapter(fail_source="sec-company-tickers")
    )
    client = TestClient(
        create_app(config=OperationsConfig.testing(), identity_resolution=resolver)
    )

    response = client.post(
        "/v1/identity/resolve",
        headers=auth_headers(),
        json=make_internal_envelope({"ticker": "AAPL"}),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ISSUER_IDENTITY_SOURCE_UNAVAILABLE"
    assert "provider response included private detail" not in response.text
    assert adapter.calls == [("sec-company-tickers", adapter.calls[0][1])]
    assert metadata.audits[-1]["outcome"] == "SOURCE_TIMEOUT"


def test_identity_route_has_typed_fundamental_v1_openapi_contract(tmp_path):
    resolver, _, _, _ = _resolver(tmp_path)
    client = TestClient(
        create_app(config=OperationsConfig.testing(), identity_resolution=resolver)
    )

    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/v1/identity/resolve"]["post"]
    request_ref = operation["requestBody"]["content"]["application/json"]["schema"][
        "$ref"
    ]

    assert request_ref.endswith("FundamentalIdentityResolutionRequestEnvelopeV1")
    assert "IdentityResolutionRequestV1" in schema["components"]["schemas"]
    assert "IdentityResolutionV1" in schema["components"]["schemas"]
