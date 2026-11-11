import hashlib
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_capture import RetainedSecSourceAdapter, SecCaptureScopeV1
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    _SecResponse,
)
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError

AT = datetime(2016, 1, 12, 19, 35, 54, tzinfo=UTC)


class _Provider(SecEdgarSourceAdapter):
    def __init__(self, *, media_type="application/json"):
        super().__init__(SecRequestPolicy(user_agent="replay-test test@example.com"))
        self.calls = []
        self.response = _SecResponse(
            content=b'{"cik":"0001539778"}',
            http_status=200,
            media_type=media_type,
            available_at=datetime(2026, 11, 10, tzinfo=UTC),
            response_headers=(("etag", '"original"'),),
            declared_size=20,
        )

    def _request(self, uri, *, deadline_at=None):
        self.calls.append(uri)
        return self.response


def _scope(**changes):
    return SecCaptureScopeV1(
        **{
            "cik": "0001539778",
            "accession_number": "0001477932-16-007985",
            "valuation_timestamp": AT,
            "source_profile": "sec-original-pit-v1",
            **changes,
        }
    )


@contextmanager
def _uncontended(_key):
    yield


def _adapter(root, provider, *, scope=None, capture_lock=_uncontended):
    return RetainedSecSourceAdapter(
        provider,
        scope=scope or _scope(),
        receipts=ArtifactStore(root / "receipts"),
        content=FilesystemContentStore(root / "content"),
        capture_lock=capture_lock,
    )


@pytest.mark.parametrize("media_type", ["application/json", ""])
def test_restart_after_capture_reuses_exact_original_and_writes_nothing(
    tmp_path: Path, media_type
):
    provider = _Provider(media_type=media_type)
    first = _adapter(tmp_path, provider).capture_submissions("0001539778")
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    second = _adapter(tmp_path, provider).capture_submissions("0001539778")
    after = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert second == first
    assert len(provider.calls) == 1
    assert after == before
    assert len(ArtifactStore(tmp_path / "receipts")._records) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"cik": "0000000001"},
        {"accession_number": "0001477932-17-007985"},
        {"valuation_timestamp": AT + timedelta(seconds=1)},
        {"source_profile": "sec-another-pit-v1"},
    ],
)
def test_each_declared_identity_dimension_separates_original_captures(
    tmp_path, changes
):
    provider = _Provider()
    uri = "https://data.sec.gov/submissions/CIK0001539778.json"
    _adapter(tmp_path, provider)._request(uri)
    _adapter(tmp_path, provider, scope=_scope(**changes))._request(uri)
    assert provider.calls == [uri, uri]
    assert len(ArtifactStore(tmp_path / "receipts")._records) == 2


def test_invalid_retained_bytes_fail_closed_without_redownloading(tmp_path):
    provider = _Provider()
    adapter = _adapter(tmp_path, provider)
    adapter.capture_submissions("0001539778")
    store = ArtifactStore(tmp_path / "receipts")
    record = next(iter(store._records.values()))
    store._artifact_path(record.content_hash, record.media_type).write_bytes(b"corrupt")
    with pytest.raises(SnapshotError) as failure:
        _adapter(tmp_path, provider).capture_submissions("0001539778")
    assert failure.value.code == "ARTIFACT_HASH_MISMATCH"
    assert len(provider.calls) == 1


def test_retained_body_corruption_fails_closed_without_redownloading(tmp_path):
    provider = _Provider()
    _adapter(tmp_path, provider).capture_submissions("0001539778")
    digest = hashlib.sha256(provider.response.content).hexdigest()
    content = FilesystemContentStore(tmp_path / "content")
    content._path(digest, "application/json").write_bytes(b"corrupt")
    with pytest.raises(SnapshotError):
        _adapter(tmp_path, provider).capture_submissions("0001539778")
    assert len(provider.calls) == 1


def test_parallel_captures_are_serialized_before_provider_io(tmp_path):
    entered = Event()
    release = Event()
    held = Lock()
    provider = _Provider()
    original_request = provider._request

    def slow(uri, *, deadline_at=None):
        entered.set()
        assert release.wait(5)
        return original_request(uri, deadline_at=deadline_at)

    provider._request = slow

    @contextmanager
    def capture_lock(_key):
        with held:
            yield

    results = []
    failures = []

    def capture():
        try:
            results.append(
                _adapter(
                    tmp_path, provider, capture_lock=capture_lock
                ).capture_submissions("0001539778")
            )
        except Exception as error:
            failures.append(error)

    first = Thread(target=capture)
    second = Thread(target=capture)
    first.start()
    assert entered.wait(5)
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not failures
    assert len(results) == 2 and results[0] == results[1]
    assert len(provider.calls) == 1


def test_response_capture_timestamp_is_metadata_and_not_identity(tmp_path):
    provider = _Provider()
    adapter = _adapter(tmp_path, provider)
    first = adapter.capture_submissions("0001539778")
    provider.response = replace(
        provider.response,
        available_at=provider.response.available_at + timedelta(days=1),
    )
    second = _adapter(tmp_path, provider).capture_submissions("0001539778")
    assert second == first
    assert len(provider.calls) == 1
    assert sha256_digest(_scope()) == sha256_digest(
        _scope(valuation_timestamp=AT.astimezone(timezone(timedelta(hours=8))))
    )


def test_acquisition_retries_after_parser_failure_reuse_all_original_responses(
    tmp_path,
):
    import json
    from types import SimpleNamespace

    from fundamental_service.source_acquisition import SecAcquisitionUseCase
    from test_source_acquisition import (
        _runtime_settings,
        _sec_request,
        _validation_profile,
    )

    request = _sec_request()
    accession = request.filing.accession_number
    primary = "msft-20240630.htm"
    files = (primary, "msft-20240630.xsd", f"{accession}-xbrl.zip")
    submissions = {
        "cik": int(request.cik),
        "tickers": [request.ticker],
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2024-07-30"],
                "acceptanceDateTime": ["2024-07-30T12:00:00Z"],
                "form": ["10-K"],
                "primaryDocument": [primary],
                "isXBRL": [1],
                "isInlineXBRL": [1],
            }
        },
    }

    class Provider(_Provider):
        def _request(self, uri, *, deadline_at=None):
            self.calls.append(uri)
            payload = (
                json.dumps(submissions).encode()
                if "/submissions/" in uri
                else json.dumps(
                    {
                        "directory": {
                            "item": [{"name": name, "size": 20} for name in files]
                        }
                    }
                ).encode()
                if uri.endswith("index.json")
                else b"original-filing-fixture"
            )
            return replace(self.response, content=payload, declared_size=len(payload))

    class Metadata:
        def try_acquire_ingestion_lock(self, _key):
            return object()

        def release_ingestion_lock(self, _lease):
            pass

        def get_mapping(self, _mapping_id):
            return SimpleNamespace(
                mapping_version=request.mappings[0].mapping_version,
                normalized_field=request.mappings[0].normalized_field,
            )

    capture_times = []

    def blocked_parser(**kwargs):
        adapter = kwargs["source_adapter"]
        adapter.capture_filing(
            cik=request.cik,
            accession_number=accession,
            primary_document=primary,
            filed_at=kwargs["filed_at"],
        )
        adapter.capture_filing_archive(
            cik=request.cik,
            accession_number=accession,
            filename=f"{accession}-xbrl.zip",
            filed_at=kwargs["filed_at"],
        )
        capture_times.append(kwargs["captured_at"])
        raise SnapshotError("PARSER_VALIDATION_BLOCKED", "original blocking finding")

    provider = Provider()
    settings = _runtime_settings()
    settings.taxonomy_cache_dir = tmp_path / "taxonomy"
    for _ in range(2):
        use_case = SecAcquisitionUseCase(
            adapter=provider,
            ingestion=SimpleNamespace(prepare_filing=blocked_parser),
            metadata=Metadata(),
            content_store=FilesystemContentStore(tmp_path / "content"),
            settings=settings,
            authorized_organizations=frozenset({"org"}),
            capture_store=ArtifactStore(tmp_path / "receipts"),
        )
        with pytest.raises(SnapshotError) as failure:
            use_case._acquire_and_publish(
                request,
                acquisition_key="a" * 64,
                key_payload={},
                caller_principal="caller",
                organization_id="org",
                correlation_id="correlation",
                deadline_at=datetime.now(UTC) + timedelta(minutes=1),
                validation_profile=_validation_profile(),
            )
        assert failure.value.code == "PARSER_VALIDATION_BLOCKED"
    assert len(provider.calls) == 4
    assert len(set(provider.calls)) == 4
    assert capture_times[0] == capture_times[1] == provider.response.available_at
    assert len(ArtifactStore(tmp_path / "receipts")._records) == 4
