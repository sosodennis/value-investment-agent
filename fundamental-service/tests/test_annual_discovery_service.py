"""Persistent annual discovery survives retries without replacing source evidence."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from threading import Lock
from types import SimpleNamespace
import json

import pytest

from fundamental_service.annual_discovery import AnnualDiscoveryRequestV1
from fundamental_service.annual_discovery_service import AnnualDiscovery
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import (
    SecRequestPolicy,
    SecSourceError,
    _SecResponse,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError

CIK = "0000724910"
RECENT = f"CIK{CIK}.json"
HISTORY = f"CIK{CIK}-submissions-001.json"
SECOND_HISTORY = f"CIK{CIK}-submissions-002.json"
NOW = datetime.now(UTC)
DEADLINE = NOW + timedelta(minutes=10)


def _request(**updates):
    return AnnualDiscoveryRequestV1(
        **{
            "cik": CIK,
            "valuation_timestamp": datetime(2025, 6, 1, tzinfo=UTC),
            "declared_source_revision": "a" * 40,
            "supported_filing_years": (2023, 2024, 2025),
            **updates,
        }
    )


def _rows(*years):
    rows = [
        {
            "accessionNumber": f"0001376474-{str(year)[2:]}-000214",
            "filingDate": f"{year}-05-01",
            "acceptanceDateTime": f"{year}-05-01T16:00:00Z",
            "reportDate": f"{year}-03-31",
            "form": "10-K",
            "primaryDocument": "annual.htm",
            "isXBRL": 1,
            "isInlineXBRL": 1,
        }
        for year in years
    ]
    return {key: [row[key] for row in rows] for key in rows[0]}


def _reference(name=HISTORY):
    return {
        "name": name,
        "filingCount": 2,
        "filingFrom": "2023-01-01",
        "filingTo": "2024-12-31",
    }


class Provider:
    policy = SecRequestPolicy(user_agent="discovery-test test@example.com")

    def __init__(self, **updates):
        self.payloads = {
            RECENT: {
                "cik": CIK,
                "tickers": ["UNTRUSTED-CURRENT-TICKER"],
                "filings": {"recent": _rows(2025), "files": [_reference()]},
            },
            HISTORY: _rows(2023, 2024),
            **updates,
        }
        self.calls = []
        self.failures = {}

    def _request(self, uri, *, deadline_at=None):
        name = uri.rsplit("/", 1)[1]
        self.calls.append(name)
        if name in self.failures:
            raise self.failures[name]
        value = self.payloads[name]
        payload = value if isinstance(value, bytes) else canonical_bytes(value)
        return _SecResponse(
            content=payload,
            http_status=200,
            media_type="application/json",
            available_at=NOW,
            response_headers=(("etag", '"original"'),),
            declared_size=len(payload),
        )


class Locks:
    def __init__(self):
        self.locks = {}
        self.guard = Lock()

    @contextmanager
    def __call__(self, key):
        with self.guard:
            lock = self.locks.setdefault(key, Lock())
        with lock:
            yield


def _service(root, provider, *, artifacts=None, locks=None):
    return AnnualDiscovery(
        provider=provider,
        artifacts=artifacts or ArtifactStore(root / "artifacts"),
        content=FilesystemContentStore(root / "content"),
        capture_lock=locks or Locks(),
        clock=lambda: NOW,
    )


def _inventory(root):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_reopened_discovery_reuses_frozen_originals_without_any_write(tmp_path):
    provider = Provider()
    first, publication = _service(tmp_path, provider).execute(
        _request(), deadline_at=DEADLINE
    )
    assert publication.wrote and not first.selection.issue_codes
    assert [filing.report_period_end.year for filing in first.selection.selected] == [
        2024,
        2025,
    ]
    assert len(first.selection.dispositions) == 3
    before = _inventory(tmp_path)
    provider.failures = {
        name: AssertionError("repeated discovery contacted the provider")
        for name in provider.payloads
    }
    second, repeated = _service(tmp_path, provider).execute(
        _request(), deadline_at=DEADLINE
    )
    assert second == first and repeated.artifact == publication.artifact
    assert not repeated.wrote and _inventory(tmp_path) == before
    assert provider.calls == [RECENT, HISTORY]


def test_concurrent_discovery_has_one_publication_and_one_capture_per_page(tmp_path):
    provider, locks = Provider(), Locks()
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(
                lambda _: _service(tmp_path, provider, locks=locks).execute(
                    _request(), deadline_at=DEADLINE
                ),
                range(3),
            )
        )
    assert len({evidence.digest for evidence, _ in results}) == 1
    assert sum(publication.wrote for _, publication in results) == 1
    assert provider.calls == [RECENT, HISTORY]


def test_retry_retains_failure_and_reuses_successful_capture(tmp_path):
    provider = Provider()
    provider.failures[HISTORY] = SecSourceError(
        "SOURCE_RATE_LIMITED", "provider detail must not be retained", retryable=True
    )
    service = _service(tmp_path, provider)
    attempt, first = service.execute(_request(), deadline_at=DEADLINE)
    assert attempt.retryable and not attempt.selection.selected and first.wrote
    assert "SOURCE_RATE_LIMITED" in attempt.selection.issue_codes
    assert len(attempt.selection.dispositions) == 1
    assert "provider detail" not in canonical_bytes(attempt).decode()
    before = _inventory(tmp_path)
    repeated, publication = _service(tmp_path, provider).execute(
        _request(), deadline_at=DEADLINE
    )
    assert repeated == attempt and not publication.wrote
    assert _inventory(tmp_path) == before
    provider.failures.clear()
    completed, publication = _service(tmp_path, provider).execute(
        _request(), deadline_at=DEADLINE
    )
    assert not completed.retryable and publication.wrote
    assert not completed.selection.issue_codes
    assert provider.calls == [RECENT, HISTORY, HISTORY, HISTORY]
    assert _service(tmp_path, provider).read(attempt.artifact_id) == attempt
    assert _service(tmp_path, provider).read(completed.artifact_id) == completed


@pytest.mark.parametrize(
    "interrupted_prefix", ["annual-discovery-request:", "annual-discovery:"]
)
def test_interruption_resumes_from_durable_captures(tmp_path, interrupted_prefix):
    class InterruptedArtifacts(ArtifactStore):
        def put_with_receipt(self, artifact_id, *args, **kwargs):
            if artifact_id.startswith(interrupted_prefix):
                raise RuntimeError("simulated process interruption")
            return super().put_with_receipt(artifact_id, *args, **kwargs)

    provider = Provider()
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        _service(
            tmp_path,
            provider,
            artifacts=InterruptedArtifacts(tmp_path / "artifacts"),
        ).execute(_request(), deadline_at=DEADLINE)
    evidence, publication = _service(tmp_path, provider).execute(
        _request(), deadline_at=DEADLINE
    )
    assert publication.wrote and not evidence.selection.issue_codes
    assert provider.calls == [RECENT, HISTORY]


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        (RECENT, b"{", "ANNUAL_SUBMISSIONS_INVALID"),
        (RECENT, b"\xff", "ANNUAL_SUBMISSIONS_INVALID"),
        (RECENT, b'{"cik":"724910","cik":"1"}', "ANNUAL_SUBMISSIONS_INVALID"),
        (HISTORY, b"{", "ANNUAL_HISTORY_INVALID"),
        (HISTORY, b'{"form":[],"form":[]}', "ANNUAL_HISTORY_INVALID"),
        (HISTORY, {**_rows(2023, 2024), "reportDate": []}, "ANNUAL_HISTORY_INVALID"),
    ],
)
def test_malformed_sources_retain_original_bytes_and_terminal_refusal(
    tmp_path, name, value, expected
):
    provider = Provider(**{name: value})
    service = _service(tmp_path, provider)
    evidence, _ = service.execute(_request(), deadline_at=DEADLINE)
    assert not evidence.retryable and not evidence.selection.selected
    assert expected in evidence.selection.issue_codes
    captured = next(source for source in evidence.sources if source.filename == name)
    assert captured.receipt is not None
    content = FilesystemContentStore(tmp_path / "content").get(
        captured.receipt.content_hash, media_type=captured.receipt.media_type
    )
    assert content == (value if isinstance(value, bytes) else canonical_bytes(value))
    before, calls = _inventory(tmp_path), list(provider.calls)
    assert service.read(evidence.artifact_id) == evidence
    _, publication = service.execute(_request(), deadline_at=DEADLINE)
    assert not publication.wrote and provider.calls == calls
    assert _inventory(tmp_path) == before


def test_one_history_failure_does_not_discard_other_pages_or_their_rows(tmp_path):
    provider = Provider(**{SECOND_HISTORY: _rows(2022)})
    provider.payloads[RECENT]["filings"]["files"].append(_reference(SECOND_HISTORY))
    provider.failures[HISTORY] = SecSourceError("SOURCE_NOT_FOUND", "unavailable")
    evidence, _ = _service(tmp_path, provider).execute(_request(), deadline_at=DEADLINE)
    assert provider.calls == [RECENT, HISTORY, SECOND_HISTORY]
    assert len(evidence.sources) == 3 and len(evidence.selection.dispositions) == 2
    assert "SOURCE_NOT_FOUND" in evidence.selection.issue_codes
    assert not evidence.selection.selected and not evidence.retryable


def test_invalid_history_references_block_incomplete_catalog(tmp_path):
    provider = Provider()
    provider.payloads[RECENT]["filings"]["files"].append(_reference())
    evidence, _ = _service(tmp_path, provider).execute(_request(), deadline_at=DEADLINE)
    assert "ANNUAL_HISTORY_REFERENCES_INVALID" in evidence.selection.issue_codes
    assert not evidence.selection.selected and len(evidence.selection.dispositions) == 1
    assert provider.calls == [RECENT]


def test_new_policy_request_reuses_catalog_but_rechecks_latest_runtime_support(
    tmp_path,
):
    provider = Provider()
    first, _ = _service(tmp_path, provider).execute(_request(), deadline_at=DEADLINE)
    before = _inventory(tmp_path)
    refused, _ = _service(tmp_path, provider).execute(
        _request(
            declared_source_revision="b" * 40, supported_filing_years=(2023, 2024)
        ),
        deadline_at=DEADLINE,
    )
    assert first.request.digest != refused.request.digest
    assert refused.selection.issue_codes == ("FILING_RUNTIME_INCOMPATIBLE",)
    assert not refused.selection.selected and len(refused.selection.dispositions) == 3
    assert provider.calls == [RECENT, HISTORY]
    after = _inventory(tmp_path)
    assert all(
        after[path] == value for path, value in before.items() if "content/" in path
    )


def test_corrupt_original_refuses_without_downloading_replacement(tmp_path):
    provider = Provider()
    evidence, _ = _service(tmp_path, provider).execute(_request(), deadline_at=DEADLINE)
    receipt = evidence.sources[0].receipt
    store = FilesystemContentStore(tmp_path / "content")
    store._path(receipt.content_hash, receipt.media_type).write_bytes(b"bad")
    with pytest.raises(SnapshotError):
        _service(tmp_path, provider).execute(_request(), deadline_at=DEADLINE)
    assert provider.calls == [RECENT, HISTORY]


def test_deadline_and_future_request_refuse_before_capture(tmp_path):
    provider = Provider()
    with pytest.raises(SecSourceError) as expired:
        _service(tmp_path, provider).execute(_request(), deadline_at=NOW)
    assert expired.value.code == "REQUEST_DEADLINE_EXCEEDED"
    with pytest.raises(SecSourceError) as future:
        _service(tmp_path, provider).execute(
            _request(valuation_timestamp=DEADLINE), deadline_at=DEADLINE
        )
    assert future.value.code == "ANNUAL_VALUATION_TIME_INVALID"
    assert provider.calls == []


def test_installed_command_uses_runtime_limits_and_retrieves_saved_selection(
    tmp_path, monkeypatch, capsys
):
    from fundamental_service import annual_discovery_runner, app

    provider = Provider()
    artifacts = ArtifactStore(tmp_path / "artifacts")

    @asynccontextmanager
    async def lifespan(_):
        yield

    fake_app = SimpleNamespace(
        router=SimpleNamespace(lifespan_context=lifespan),
        state=SimpleNamespace(
            application=SimpleNamespace(
                ready=True,
                content_store=FilesystemContentStore(tmp_path / "content"),
                artifact_store=artifacts,
            ),
            sec_acquisition=SimpleNamespace(
                adapter=provider,
                settings=SimpleNamespace(
                    supported_filing_years=(2023, 2024),
                    supported_filing_forms=("10-K",),
                ),
            ),
            metadata_store=object(),
        ),
    )
    monkeypatch.setattr(app, "app", fake_app)
    monkeypatch.setattr(
        annual_discovery_runner, "PostgresPublicCaptureLock", lambda _: Locks()
    )
    arguments = [
        "--cik",
        "724910",
        "--valuation-timestamp",
        "2025-06-01T00:00:00Z",
        "--source-revision",
        "a" * 40,
    ]
    assert annual_discovery_runner.main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["wrote"]
    assert first["evidence"]["selection"]["issue_codes"] == [
        "FILING_RUNTIME_INCOMPATIBLE"
    ]
    assert first["evidence"]["request"]["supported_filing_years"] == [2023, 2024]
    before = _inventory(tmp_path)
    assert annual_discovery_runner.main(arguments) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated == {**first, "wrote": False}
    assert (
        annual_discovery_runner.main(
            ["--artifact-id", first["artifact"]["artifact_id"]]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == repeated
    assert provider.calls == [RECENT, HISTORY] and _inventory(tmp_path) == before


def test_invalid_command_input_is_rejected_before_service_storage(monkeypatch, capsys):
    from fundamental_service import annual_discovery_runner

    async def forbidden(_):
        raise AssertionError("invalid caller input opened service storage")

    monkeypatch.setattr(annual_discovery_runner, "_run_command", forbidden)
    assert (
        annual_discovery_runner.main(
            [
                "--cik",
                "not-a-cik",
                "--valuation-timestamp",
                "2025-06-01T00:00:00Z",
                "--source-revision",
                "a" * 40,
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().err) == {
        "error_code": "ANNUAL_DISCOVERY_INPUT_INVALID"
    }
