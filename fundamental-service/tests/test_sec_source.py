import hashlib
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from email.message import Message
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from fundamental_service.contracts import SourceRole
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_capture import RetainedSecSourceAdapter, SecCaptureScopeV1
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    SecSourceError,
    _open_sec,
)
from fundamental_service.snapshots import FilesystemContentStore


class FakeResponse:
    def __init__(
        self, payload: bytes, *, status: int = 200, location: str | None = None
    ):
        self._payload = payload
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        if location is not None:
            self.headers["Location"] = location

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


def test_company_ticker_directory_capture_is_exact_and_hashable():
    payload = b'{"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}}'
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, request.headers["User-agent"], timeout))
        return FakeResponse(payload)

    source = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=opener,
        sleep=lambda _seconds: None,
    ).capture_company_tickers()

    assert source.source_id == "sec-company-tickers"
    assert source.role is SourceRole.ACQUISITION
    assert source.uri == "https://www.sec.gov/files/company_tickers.json"
    assert (
        hashlib.sha256(source.content).hexdigest()
        == hashlib.sha256(payload).hexdigest()
    )
    assert calls[0][0] == source.uri
    assert calls[0][1] == "value-agent test@example.com"


def test_company_ticker_directory_rejects_noncanonical_uri():
    calls = []
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(user_agent="value-agent test@example.com"),
        opener=lambda *_args, **_kwargs: calls.append(True),
    )

    with pytest.raises(SecSourceError) as error:
        adapter.capture_json(
            source_id="sec-company-tickers",
            uri="https://www.sec.gov/files/company_tickers.json?redirect=example.test",
        )

    assert error.value.code == "SOURCE_URI_NOT_ALLOWED"
    assert calls == []


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


def test_sec_source_rejects_redirect_before_following_off_host_location():
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(
            b"",
            status=302,
            location="https://evil.example/Archives/edgar/data/1/index.json",
        )

    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=opener,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(SecSourceError) as error:
        adapter.capture_json(
            source_id="sec-submissions",
            uri="https://data.sec.gov/submissions/CIK0000000001.json",
        )

    assert error.value.code == "SOURCE_REDIRECT_NOT_ALLOWED"
    assert calls == ["https://data.sec.gov/submissions/CIK0000000001.json"]


def test_default_sec_transport_does_not_follow_redirect_to_another_origin():
    destination_requests = []

    class DestinationHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            destination_requests.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            return

    destination_server = ThreadingHTTPServer(("127.0.0.1", 0), DestinationHandler)
    destination = f"http://127.0.0.1:{destination_server.server_address[1]}/redirected"

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", destination)
            self.end_headers()

        def log_message(self, *_args):
            return

    redirect_server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    servers = (destination_server, redirect_server)
    threads = tuple(
        Thread(target=server.serve_forever, daemon=True) for server in servers
    )
    try:
        for thread in threads:
            thread.start()
        request = Request(
            f"http://127.0.0.1:{redirect_server.server_address[1]}/source"
        )
        with pytest.raises(HTTPError) as error:
            _open_sec(request, timeout=2)

        assert error.value.code == 302
        assert destination_requests == []
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


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


def test_filing_archive_capture_is_accession_bound_and_preserves_provenance():
    adapter = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com", min_interval_seconds=0
        ),
        opener=lambda request, timeout: FakeResponse(b"PK\\x03\\x04archive"),
        sleep=lambda _seconds: None,
    )
    filed_at = datetime(2024, 11, 1, 10, 1, 36, tzinfo=timezone.utc)
    source = adapter.capture_filing_archive(
        cik="0000320193",
        accession_number="0000320193-24-000123",
        filename="0000320193-24-000123-xbrl.zip",
        filed_at=filed_at,
    )
    assert source.source_id == "sec-filing-archive"
    assert source.role is SourceRole.FILING
    assert source.uri.endswith("/0000320193-24-000123-xbrl.zip")
    assert source.content == b"PK\\x03\\x04archive"
    assert source.filed_at == filed_at

    with pytest.raises(ValueError, match="match the SEC accession"):
        adapter.capture_filing_archive(
            cik="0000320193",
            accession_number="0000320193-24-000123",
            filename="other-accession-xbrl.zip",
            filed_at=filed_at,
        )


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


@pytest.mark.parametrize(
    ("failures", "max_attempts", "succeeds"),
    [(1, 3, True), (3, 3, False), (1, 1, False)],
)
def test_truncated_chunked_response_retries_without_retaining_partial_bytes(
    tmp_path, failures, max_attempts, succeeds
):
    payload = b'{"padding":"' + b"x" * (1024 * 1024 + 64) + b'"}'
    attempts = []
    responses = []
    delays = []

    class ChunkedHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            attempts.append(self.path)
            truncated = len(attempts) <= failures
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            declared = len(payload) + 100 if truncated else len(payload)
            self.wfile.write(f"{declared:X}\r\n".encode() + payload)
            if not truncated:
                self.wfile.write(b"\r\n0\r\n\r\n")
            self.close_connection = True

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), ChunkedHandler)
    thread = Thread(target=server.serve_forever, daemon=True)

    def opener(_request, timeout):
        response = _open_sec(
            Request(f"http://127.0.0.1:{server.server_address[1]}/original"),
            timeout=timeout,
        )
        responses.append(response)
        return response

    provider = SecEdgarSourceAdapter(
        SecRequestPolicy(
            user_agent="value-agent test@example.com",
            min_interval_seconds=0,
            max_attempts=max_attempts,
            timeout_seconds=2,
        ),
        opener=opener,
        sleep=delays.append,
    )
    receipts = ArtifactStore(tmp_path / "receipts")
    adapter = RetainedSecSourceAdapter(
        provider,
        scope=SecCaptureScopeV1(
            cik="0001539778",
            accession_number="0001477932-16-007985",
            valuation_timestamp=datetime(2016, 1, 12, tzinfo=timezone.utc),
            source_profile="truncated-transfer-test-v1",
        ),
        receipts=receipts,
        content=FilesystemContentStore(tmp_path / "content"),
        capture_lock=lambda _key: nullcontext(),
    )
    initial = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    try:
        thread.start()
        if succeeds:
            source = adapter.capture_submissions("0001539778")
            assert source.content == payload
            assert len(attempts) == failures + 1
            before = {
                p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in tmp_path.rglob("*")
                if p.is_file()
            }
            assert adapter.capture_submissions("0001539778") == source
            assert len(attempts) == failures + 1
            assert {
                p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in tmp_path.rglob("*")
                if p.is_file()
            } == before
            assert len(receipts._records) == 1
        else:
            with pytest.raises(SecSourceError) as error:
                adapter.capture_submissions("0001539778")
            assert error.value.code == "SOURCE_UNAVAILABLE"
            assert error.value.retryable is True
            assert isinstance(error.value.__cause__, IncompleteRead)
            assert len(attempts) == max_attempts
            assert not receipts._records
            assert {
                p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in tmp_path.rglob("*")
                if p.is_file()
            } == initial
        assert delays == [2**i for i in range(len(attempts) - 1)]
        assert all(response.isclosed() for response in responses)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
