import json
from datetime import datetime, timezone
from email.message import Message

import pytest

from fundamental_service.contracts import SourceRole
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    SecSourceError,
)


class FakeResponse:
    status = 200

    def __init__(self, payload: bytes):
        self._payload = payload
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_companyfacts_capture_is_public_and_hashable():
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, request.headers["User-agent"], timeout))
        return FakeResponse(json.dumps({"entityName": "Example"}).encode())

    source = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=opener,
        sleep=lambda _seconds: None,
    ).capture_company_facts(
        "0000320193", captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert source.source_id == "sec-companyfacts"
    assert source.uri.endswith("CIK0000320193.json")
    assert calls[0][1] == "value-agent test@example.com"


def test_rate_limit_retries_then_returns_stable_error():
    attempts = 0

    def opener(_request, timeout):
        assert timeout == 30.0
        nonlocal attempts
        attempts += 1
        raise OSError("offline")

    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com",
            max_attempts=2,
            min_interval_seconds=0,
        ),
        opener=opener,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(SecSourceError, match="failed after retries") as error:
        adapter.capture_company_facts("1")
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert attempts == 2


def test_invalid_user_agent_and_cik_fail_before_network():
    with pytest.raises(ValueError):
        SecRequestPolicy(user_agent="anonymous")
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(user_agent="value-agent test@example.com"),
        opener=lambda *_args, **_kwargs: None,
    )
    with pytest.raises(ValueError):
        adapter.capture_company_facts("not-a-cik")


def test_sec_source_rejects_uri_that_does_not_match_registered_endpoint():
    calls = []
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(user_agent="value-agent test@example.com"),
        opener=lambda *_args, **_kwargs: calls.append(True),
    )
    with pytest.raises(SecSourceError) as error:
        adapter.capture_json(
            source_id="sec-companyfacts",
            uri="https://example.test/companyfacts.json",
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
    assert calls == []


def test_filing_resource_capture_preserves_dts_role_and_metadata():
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=lambda *_args, **_kwargs: FakeResponse(
            b"<schema/>",
        ),
        sleep=lambda _seconds: None,
    )
    filed_at = datetime(2024, 11, 1, 10, 1, 36, tzinfo=timezone.utc)
    source = adapter.capture_filing_resource(
        cik="0000320193",
        accession_number="0000320193-24-000123",
        filename="aapl-20240928.xsd",
        filed_at=filed_at,
        taxonomy_manifest_id="manifest-v1",
    )
    assert source.source_id == "sec-taxonomy"
    assert source.role is SourceRole.TAXONOMY
    assert source.uri.endswith("/aapl-20240928.xsd")
    assert source.filed_at == filed_at
    assert source.taxonomy_manifest_id == "manifest-v1"


def test_sec_policy_rejects_non_sec_base_url_and_archive_host():
    with pytest.raises(ValueError, match="base_url"):
        SecRequestPolicy(
            user_agent="value-agent test@example.com",
            base_url="https://example.test",
        )
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(user_agent="value-agent test@example.com"),
        opener=lambda *_args, **_kwargs: pytest.fail("network must not be attempted"),
    )
    with pytest.raises(SecSourceError) as error:
        adapter.capture_json(
            source_id="sec-submissions",
            uri="https://evil.example/Archives/edgar/data/1/index.json",
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"


def test_sec_source_rejects_custom_port():
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(user_agent="value-agent test@example.com"),
        opener=lambda *_args, **_kwargs: pytest.fail("network must not be attempted"),
    )
    with pytest.raises(SecSourceError) as error:
        adapter.capture_json(
            source_id="sec-companyfacts",
            uri="https://data.sec.gov:443/api/xbrl/companyfacts/CIK0000000001.json",
        )
    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
