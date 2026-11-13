import fcntl
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from threading import Event

import pytest

from fundamental_service.contracts import SourceRole
from fundamental_service.public_acquisition import (
    PostgresPublicCaptureLock,
    PublicSourceAcquisition,
    PublicSourceAcquisitionRequestV1,
)
from fundamental_service.public_source import PublicSourceAdapter
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import (
    CapturedSource,
    FilesystemContentStore,
    SnapshotError,
)
from fundamental_service.source_capture import SourceCaptureRequest
from test_public_source import FakeResponse

AT = datetime(2026, 11, 13, 12, tzinfo=UTC)
URI = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xlsx"
TERMS = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/"


def request(**changes):
    return PublicSourceAcquisitionRequestV1(
        **{
            "source_id": "damodaran-reference",
            "uri": URI,
            "source_profile": "damodaran-country-erp-tax-xlsx-v2",
            "terms_reference": TERMS,
            "valuation_timestamp": AT,
            **changes,
        }
    )


class Provider:
    def __init__(self):
        self.calls = []
        self.error = None
        self.source = CapturedSource(
            source_id="damodaran-reference",
            uri=URI,
            role=SourceRole.REFERENCE,
            content=b"original workbook bytes",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            http_status=200,
            captured_at=AT - timedelta(hours=1),
            available_at=AT - timedelta(hours=1),
        )

    def validate_capture(self, source_id, uri):
        return SourceCaptureRequest(source_id, uri, TERMS)

    def capture(self, source_id, uri):
        self.calls.append((source_id, uri))
        if self.error:
            raise self.error
        return replace(self.source, source_id=source_id, uri=uri)


@contextmanager
def file_lock(root, key):
    root.mkdir(parents=True, exist_ok=True)
    with (root / key).open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def acquisition(root, provider, *, artifacts=None, lock=None):
    return PublicSourceAcquisition(
        provider=provider,
        artifacts=artifacts or ArtifactStore(root / "artifacts"),
        content=FilesystemContentStore(root / "content"),
        capture_lock=lock or (lambda key: file_lock(root / "locks", key)),
    )


def inventory(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_reopened_repeat_reuses_original_without_download_or_any_file_write(tmp_path):
    provider = Provider()
    first = acquisition(tmp_path, provider).execute(request())
    original = inventory(tmp_path)
    reopened = acquisition(tmp_path, provider)
    second = reopened.execute(request())
    outcome = reopened.read(second.artifact.artifact_id)
    assert first.wrote and not second.wrote
    assert first.artifact == second.artifact
    assert reopened.retained_source(outcome).content == provider.source.content
    assert outcome.status == "captured" and not outcome.issue_codes
    assert inventory(tmp_path) == original
    assert provider.calls == [("damodaran-reference", URI)]


def test_real_public_adapter_rechecks_whitelist_before_cached_or_new_io(tmp_path):
    calls = []
    provider = PublicSourceAdapter(
        user_agent="source-test test@example.com",
        min_interval_seconds=0,
        opener=lambda *_a, **_kw: calls.append(True)
        or FakeResponse(b"workbook", "application/octet-stream"),
    )
    use_case = acquisition(tmp_path, provider)
    first = use_case.execute(request())
    before = inventory(tmp_path)
    assert not use_case.execute(request()).wrote
    assert inventory(tmp_path) == before
    for change, code in [
        (
            {"uri": URI.replace("pages.stern.nyu.edu", "example.com")},
            "SOURCE_URI_NOT_ALLOWED",
        ),
        (
            {"uri": "https://pages.stern.nyu.edu/~adamodar/pc/blog/erp.html"},
            "SOURCE_QUERY_INVALID",
        ),
        ({"terms_reference": "invented"}, "SOURCE_REGISTRATION_MISMATCH"),
    ]:
        with pytest.raises(SnapshotError) as failure:
            use_case.execute(request(**change))
        assert failure.value.code == code
    assert calls == [True]
    assert use_case.read(first.artifact.artifact_id).source is not None


@pytest.mark.parametrize(
    "change",
    [
        {"source_id": "alternative-reference"},
        {"uri": URI.replace("ctryprem.xlsx", "wacc.xls")},
        {"source_profile": "country-profile-next"},
        {"valuation_timestamp": AT + timedelta(days=1)},
    ],
)
def test_mutable_url_reuse_is_limited_to_exact_declared_scope(tmp_path, change):
    provider = Provider()
    first = acquisition(tmp_path, provider).execute(request())
    second = acquisition(tmp_path, provider).execute(request(**change))
    assert first.wrote and second.wrote
    assert first.artifact.artifact_id != second.artifact.artifact_id
    assert len(provider.calls) == 2


def test_equal_instants_have_same_identity(tmp_path):
    provider = Provider()
    first = acquisition(tmp_path, provider).execute(request())
    shifted = request(valuation_timestamp=AT.astimezone(timezone(timedelta(hours=8))))
    second = acquisition(tmp_path, provider).execute(shifted)
    assert request().digest == shifted.digest
    assert first.artifact == second.artifact and not second.wrote
    assert len(provider.calls) == 1


def test_late_capture_is_retained_but_cannot_establish_historical_availability(
    tmp_path,
):
    provider = Provider()
    use_case = acquisition(tmp_path, provider)
    first = use_case.execute(request(valuation_timestamp=AT - timedelta(days=3650)))
    outcome = use_case.read(first.artifact.artifact_id)
    assert outcome.status == "captured"
    assert outcome.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
    assert outcome.available_at == provider.source.available_at
    assert outcome.source.captured_at == provider.source.captured_at
    assert use_case.retained_source(outcome).content == provider.source.content


@pytest.mark.parametrize("location", ["receipt", "source"])
def test_corruption_fails_without_download_or_repair(tmp_path, location):
    provider = Provider()
    use_case = acquisition(tmp_path, provider)
    publication = use_case.execute(request())
    outcome = use_case.read(publication.artifact.artifact_id)
    if location == "receipt":
        store = ArtifactStore(tmp_path / "artifacts")
        p = store._artifact_path(publication.artifact.content_hash, "application/json")
    else:
        p = FilesystemContentStore(tmp_path / "content")._path(
            outcome.source.content_sha256, outcome.media_type
        )
    p.write_bytes(b"corruption")
    before = inventory(tmp_path)
    with pytest.raises(SnapshotError):
        acquisition(tmp_path, provider).execute(request())
    assert len(provider.calls) == 1
    assert inventory(tmp_path) == before


def test_stable_provider_failure_is_retained_and_reused_after_reopen(tmp_path):
    provider = Provider()
    provider.error = SnapshotError("SOURCE_PAYLOAD_INVALID", "fixture")
    first = acquisition(tmp_path, provider).execute(request())
    before = inventory(tmp_path)
    second = acquisition(tmp_path, provider).execute(request())
    outcome = acquisition(tmp_path, provider).read(first.artifact.artifact_id)
    assert first.artifact == second.artifact and not second.wrote
    assert outcome.status == "failed"
    assert outcome.issue_codes == ("SOURCE_PAYLOAD_INVALID",)
    assert outcome.source is None and not outcome.retryable
    assert inventory(tmp_path) == before and len(provider.calls) == 1


def test_transient_attempt_is_retained_without_freezing_successful_retry(tmp_path):
    provider = Provider()
    provider.error = SnapshotError("SOURCE_RATE_LIMITED", "fixture", retryable=True)
    use_case = acquisition(tmp_path, provider)
    failed = use_case.execute(request())
    assert use_case.read(failed.artifact.artifact_id).retryable
    provider.error = None
    successful = use_case.execute(request())
    assert successful.wrote
    assert use_case.read(successful.artifact.artifact_id).status == "captured"
    assert use_case.read(failed.artifact.artifact_id).issue_codes == (
        "SOURCE_RATE_LIMITED",
    )
    assert not use_case.execute(request()).wrote
    assert len(provider.calls) == 2


def test_concurrent_captures_publish_one_receipt_and_download_once(tmp_path):
    provider = Provider()
    entered, release = Event(), Event()
    capture = provider.capture

    def delayed(source_id, uri):
        entered.set()
        assert release.wait(5)
        return capture(source_id, uri)

    provider.capture = delayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(acquisition(tmp_path, provider).execute, request())
        assert entered.wait(5)
        second = pool.submit(acquisition(tmp_path, provider).execute, request())
        release.set()
        results = [first.result(5), second.result(5)]
    assert sorted(p.wrote for p in results) == [False, True]
    assert results[0].artifact == results[1].artifact
    assert len(provider.calls) == 1


def test_interruption_after_receipt_commit_resumes_without_another_download(tmp_path):
    class InterruptedStore(ArtifactStore):
        def put_with_receipt(self, *args, **kwargs):
            super().put_with_receipt(*args, **kwargs)
            raise RuntimeError("caller interrupted after durable publication")

    provider = Provider()
    with pytest.raises(RuntimeError, match="interrupted"):
        acquisition(
            tmp_path, provider, artifacts=InterruptedStore(tmp_path / "artifacts")
        ).execute(request())
    before = inventory(tmp_path)
    repeated = acquisition(tmp_path, provider).execute(request())
    assert not repeated.wrote and len(provider.calls) == 1
    assert inventory(tmp_path) == before


def test_content_and_receipt_identity_are_bound_even_if_registry_hash_is_valid(
    tmp_path,
):
    provider = Provider()
    use_case = acquisition(tmp_path, provider)
    result = use_case.execute(request())
    outcome = use_case.read(result.artifact.artifact_id)
    other = outcome.model_copy(
        update={"request": request(source_profile="different-profile")}
    )
    store = ArtifactStore(tmp_path / "tampered")
    store.put_with_receipt(
        result.artifact.artifact_id,
        other,
        (request().digest, outcome.source.content_sha256),
    )
    with pytest.raises(SnapshotError):
        acquisition(tmp_path, provider, artifacts=store).execute(request())
    assert len(provider.calls) == 1


def test_busy_postgres_lease_refuses_before_provider_or_store_io(tmp_path):
    class Busy:
        def try_acquire_ingestion_lock(self, key):
            return None

    provider = Provider()
    with pytest.raises(SnapshotError) as failure:
        acquisition(tmp_path, provider, lock=PostgresPublicCaptureLock(Busy())).execute(
            request()
        )
    assert failure.value.code == "PUBLIC_CAPTURE_IN_PROGRESS"
    assert failure.value.retryable and not provider.calls


def test_released_postgres_lease_even_if_capture_raises(tmp_path):
    released = []

    class Lease:
        def try_acquire_ingestion_lock(self, key):
            return key

        def release_ingestion_lock(self, lease):
            released.append(lease)

    provider = Provider()
    provider.capture = lambda *_args: (_ for _ in ()).throw(RuntimeError("interrupt"))
    with pytest.raises(RuntimeError, match="interrupt"):
        acquisition(
            tmp_path, provider, lock=PostgresPublicCaptureLock(Lease())
        ).execute(request())
    assert released == [request().digest]


def test_profile_label_never_grants_source_or_policy_approval(tmp_path):
    provider = Provider()
    case = acquisition(tmp_path, provider)
    result = case.execute(request(source_profile="unreviewed-profile"))
    outcome = case.read(result.artifact.artifact_id)
    assert outcome.source.source_version == "unreviewed-profile"
    assert b"approved" not in canonical_bytes(outcome)


def test_postgres_parallel_lease_prevents_duplicate_io_then_reuses(
    tmp_path, recovery_databases
):
    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        PostgresMetadataStore,
    )

    source_database, _ = recovery_databases
    store = PostgresMetadataStore(source_database, auto_migrate=True)
    store.start()
    provider = Provider()
    entered, release = Event(), Event()
    capture = provider.capture

    def delayed(source_id, uri):
        entered.set()
        assert release.wait(5)
        return capture(source_id, uri)

    provider.capture = delayed
    content = PostgresContentStore(tmp_path / "pg-content", store)
    use_case = PublicSourceAcquisition(
        provider=provider,
        artifacts=PostgresArtifactStore(store, content),
        content=content,
        capture_lock=PostgresPublicCaptureLock(store),
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(use_case.execute, request())
            try:
                assert entered.wait(5)
                with pytest.raises(SnapshotError) as busy:
                    use_case.execute(request())
                assert busy.value.code == "PUBLIC_CAPTURE_IN_PROGRESS"
                assert busy.value.retryable
            finally:
                release.set()
            first = future.result(5)
        before = inventory(tmp_path)
        repeated = use_case.execute(request())
        assert repeated.artifact == first.artifact and not repeated.wrote
        assert inventory(tmp_path) == before and len(provider.calls) == 1
    finally:
        store.close()
