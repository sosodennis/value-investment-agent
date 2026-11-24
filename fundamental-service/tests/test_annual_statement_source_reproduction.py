import hashlib
import sys
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fundamental_service.annual_discovery import AnnualDiscoveryRequestV1
from fundamental_service.annual_discovery_service import AnnualDiscovery
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_capture import RetainedSecSourceAdapter, SecCaptureScopeV1
from fundamental_service.sec_source import (
    SecRequestPolicy,
    SecSourceError,
    _SecResponse,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import reproduce_annual_statement_sources as command  # noqa: E402

CIK = "0000320193"
ACCESSION = "0000320193-24-000123"
AT = datetime(2026, 11, 24, tzinfo=UTC)
CUTOFF = datetime(2024, 11, 2, tzinfo=UTC)
FILED = datetime(2024, 11, 1, 10, 1, 36, tzinfo=UTC)
SOURCE = "a" * 40
BASE = f"https://www.sec.gov/Archives/edgar/data/320193/{ACCESSION.replace('-', '')}"
URLS = (
    BASE + "/index.json",
    BASE + f"/{ACCESSION}-xbrl.zip",
    BASE + "/aapl-20240928.htm",
    BASE + f"/{ACCESSION}.txt",
)


class Provider:
    policy = SecRequestPolicy(user_agent="Synthetic boundary test test@example.com")

    def __init__(
        self, *, observed_at=AT, changed_source=None, failure=None, newest=False
    ):
        self.observed_at = observed_at
        self.changed_source = changed_source
        self.failure = failure
        self.newest = newest
        self.calls = []

    def _request(self, uri, *, deadline_at=None):
        self.calls.append(uri)
        if self.failure == uri:
            raise SecSourceError(
                "SEC_RATE_LIMITED", "synthetic rate limit", retryable=True
            )
        name = uri.rsplit("/", 1)[-1]
        if uri.startswith("https://data.sec.gov/"):
            accession = "0000320193-24-000124" if self.newest else ACCESSION
            row = {
                "accessionNumber": accession,
                "filingDate": "2024-11-01",
                "acceptanceDateTime": "2024-11-01T10:01:36Z",
                "reportDate": "2024-09-28",
                "form": "10-K",
                "primaryDocument": "aapl-20240928.htm",
                "isXBRL": 1,
                "isInlineXBRL": 1,
            }
            payload = canonical_bytes(
                {
                    "cik": CIK,
                    "filings": {
                        "recent": {key: [value] for key, value in row.items()},
                        "files": [],
                    },
                }
            )
            media = "application/json"
        elif name == "index.json":
            payload, media = b'{"directory":{"item":[]}}', "application/json"
        elif name.endswith(".zip"):
            payload, media = b"synthetic accession archive", "application/zip"
        elif name.endswith(".txt"):
            payload, media = b"synthetic complete submission", "text/plain"
        else:
            payload, media = b"<html>synthetic original</html>", "text/html"
        if uri == self.changed_source:
            payload += b"changed"
        return _SecResponse(
            content=payload,
            http_status=200,
            media_type=media,
            available_at=self.observed_at,
            response_headers=(("date", self.observed_at.isoformat()),),
            declared_size=len(payload),
        )


def _fixture(root):
    provider = Provider()
    artifacts = ArtifactStore(root / "artifacts")
    content = FilesystemContentStore(root / "content")
    discovery = AnnualDiscovery(
        provider=provider,
        artifacts=artifacts,
        content=content,
        capture_lock=lambda key: nullcontext(),
    )
    request = AnnualDiscoveryRequestV1(
        cik=CIK,
        valuation_timestamp=CUTOFF,
        original_count=1,
        declared_source_revision=SOURCE,
        supported_filing_years=(2024,),
    )
    evidence, _ = discovery.execute(
        request, deadline_at=datetime.now(UTC) + timedelta(minutes=1)
    )
    scope = SecCaptureScopeV1(
        cik=CIK,
        accession_number=ACCESSION,
        valuation_timestamp=CUTOFF,
        source_profile="issue494-original-inspection-v1",
    )
    adapter = RetainedSecSourceAdapter(
        provider,
        scope=scope,
        receipts=artifacts,
        content=content,
        capture_lock=lambda key: nullcontext(),
    )
    kwargs = dict(cik=CIK, accession_number=ACCESSION, filed_at=FILED)
    adapter.capture_filing_index(**kwargs)
    adapter.capture_filing_archive(**kwargs)
    adapter.capture_filing(primary_document="aapl-20240928.htm", **kwargs)
    adapter.capture_filing_submission(**kwargs)
    sources = []
    for receipt in adapter.observed_responses:
        artifact_id = command.sec_response_artifact_id(scope, receipt.uri)
        record = artifacts.get(artifact_id)
        media_key = hashlib.sha256(record.media_type.encode()).hexdigest()[:16]
        sources.append(
            {
                **receipt.model_dump(exclude={"scope", "schema_version"}),
                "receipt_refs": [
                    {
                        "artifact_id": artifact_id,
                        "content_hash": record.content_hash,
                        "retained_path": f"artifacts/{record.content_hash}.{media_key}.artifact",
                        "schema_version": receipt.schema_version,
                        "scope": scope,
                    }
                ],
            }
        )
    return command.FrozenCohort.model_validate_json(
        canonical_bytes(
            {
                "protocol": "issue494-annual-statements-cohort-v1",
                "source_baseline": SOURCE,
                "cases": [
                    {
                        "case_id": "synthetic-source-boundary",
                        "issuer_id": CIK,
                        "cutoff_at": CUTOFF,
                        "original_accessions": [ACCESSION],
                        "discovery_artifact_id": evidence.artifact_id,
                        "discovery_evidence_digest": evidence.digest,
                    }
                ],
                "filings": [
                    {
                        **evidence.selection.selected[0].model_dump(),
                        "issuer_id": CIK,
                        "source_records": sources,
                    }
                ],
            }
        )
    )


def _inventory(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def _capture(cohort, root, provider):
    return command.capture_sources(
        cohort,
        cohort_hash=sha256_digest(cohort),
        evidence_dir=root,
        provider=provider,
        source_revision=SOURCE,
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def test_verifies_retained_bytes_and_receipts_without_any_write(tmp_path):
    cohort = _fixture(tmp_path)
    before = _inventory(tmp_path)
    report = command.verify_frozen(
        cohort, cohort_hash=sha256_digest(cohort), evidence_dir=tmp_path
    )
    assert report.exit_code == 0
    assert len(report.sources) == 4
    assert report.cases[0].selected_accessions == (ACCESSION,)
    assert not report.validation_performed and not report.canonical_ingestion_performed
    assert _inventory(tmp_path) == before


def test_verification_does_not_create_missing_evidence(tmp_path):
    cohort = _fixture(tmp_path / "seed")
    missing = tmp_path / "absent"
    with pytest.raises(ValueError, match="existing content"):
        command.verify_frozen(
            cohort, cohort_hash=sha256_digest(cohort), evidence_dir=missing
        )
    assert not missing.exists()


@pytest.mark.parametrize("part", ["source", "receipt"])
def test_corruption_is_a_named_failure(tmp_path, part):
    cohort = _fixture(tmp_path)
    source = cohort.filings[0].source_records[0]
    if part == "source":
        suffix = ".json" if source.media_type == "application/json" else ".bin"
        path = (
            tmp_path
            / "content"
            / source.content_hash[:2]
            / (source.content_hash + suffix)
        )
    else:
        path = tmp_path / source.receipt_refs[0].retained_path
    path.write_bytes(b"corrupt")
    report = command.verify_frozen(
        cohort, cohort_hash=sha256_digest(cohort), evidence_dir=tmp_path
    )
    assert report.exit_code == 2
    assert any(item.issue_codes for item in report.sources)
    assert report.sources[0].issue_codes == (
        "SOURCE_HASH_MISMATCH" if part == "source" else "ARTIFACT_HASH_MISMATCH",
    )


def test_recapture_preserves_new_metadata_and_reuses_same_inputs_after_restart(
    tmp_path,
):
    cohort = _fixture(tmp_path / "frozen")
    root = tmp_path / "new"
    provider = Provider(observed_at=AT + timedelta(days=1))
    first = _capture(cohort, root, provider)
    assert first.exit_code == 2
    assert len(first.sources) == 4
    assert all(
        item.actual.captured_at == AT + timedelta(days=1) for item in first.sources
    )
    assert all(
        "SOURCE_CAPTURE_METADATA_DIFFERENT" in item.issue_codes
        for item in first.sources
    )
    assert all(
        "SOURCE_CONTENT_DIFFERENT" not in item.issue_codes for item in first.sources
    )
    before = _inventory(root)
    provider.calls.clear()
    second = _capture(cohort, root, provider)
    assert first == second and provider.calls == []
    assert _inventory(root) == before


def test_changed_raw_bytes_are_new_inputs(tmp_path):
    cohort = _fixture(tmp_path / "frozen")
    report = _capture(cohort, tmp_path / "new", Provider(changed_source=URLS[2]))
    source = next(item for item in report.sources if item.source_url == URLS[2])
    assert report.exit_code == 2
    assert "SOURCE_CONTENT_DIFFERENT" in source.issue_codes
    assert source.actual.content_hash != source.expected_content_hash


def test_transport_failure_remains_visible_and_retry_only_fetches_missing_source(
    tmp_path,
):
    cohort = _fixture(tmp_path / "frozen")
    provider = Provider(failure=URLS[2])
    first = _capture(cohort, tmp_path / "new", provider)
    assert first.exit_code == 2
    failed = next(item for item in first.sources if item.source_url == URLS[2])
    assert failed.issue_codes == ("SEC_RATE_LIMITED",)
    assert len([item for item in first.sources if item.actual is not None]) == 3
    provider.failure = None
    provider.calls.clear()
    second = _capture(cohort, tmp_path / "new", provider)
    assert second.exit_code == 0 and provider.calls == [URLS[2]]


def test_changed_newest_selection_cannot_capture_older_frozen_original(tmp_path):
    cohort = _fixture(tmp_path / "frozen")
    provider = Provider(newest=True)
    report = _capture(cohort, tmp_path / "new", provider)
    assert report.exit_code == 2
    assert report.cases[0].issue_codes == ("FROZEN_SELECTION_DIFFERENT",)
    assert report.cases[0].selected_accessions == ("0000320193-24-000124",)
    assert report.sources == ()
    assert len(provider.calls) == 1


def test_capture_refuses_existing_frozen_root(tmp_path):
    cohort = _fixture(tmp_path)
    before = _inventory(tmp_path)
    with pytest.raises(ValueError, match="new evidence directory"):
        _capture(cohort, tmp_path, Provider())
    assert _inventory(tmp_path) == before


def test_cli_checks_output_boundary_before_capture(tmp_path, monkeypatch):
    cohort = _fixture(tmp_path / "seed")
    path = tmp_path / "cohort.json"
    path.write_bytes(canonical_bytes(cohort))
    evidence = tmp_path / "new"
    monkeypatch.setenv("TEST_SEC_USER_AGENT", "Synthetic test test@example.com")
    with pytest.raises(SystemExit) as caught:
        command.main(
            [
                "capture",
                "--cohort",
                str(path),
                "--evidence-dir",
                str(evidence),
                "--output",
                str(evidence / "report.json"),
                "--source-revision",
                SOURCE,
                "--user-agent-env",
                "TEST_SEC_USER_AGENT",
            ]
        )
    assert caught.value.code == 2
    assert not evidence.exists()


def test_missing_receipt_is_not_reacquired_during_verify(tmp_path):
    cohort = _fixture(tmp_path)
    source = cohort.filings[0].source_records[0]
    (tmp_path / source.receipt_refs[0].retained_path).unlink()
    before = _inventory(tmp_path)
    report = command.verify_frozen(
        cohort, cohort_hash=sha256_digest(cohort), evidence_dir=tmp_path
    )
    assert report.exit_code == 2
    assert report.sources[0].issue_codes == ("ARTIFACT_BYTES_UNAVAILABLE",)
    assert _inventory(tmp_path) == before


def test_cohort_rejects_cross_issuer_source_scope(tmp_path):
    cohort = _fixture(tmp_path)
    payload = cohort.model_dump(mode="json")
    payload["filings"][0]["issuer_id"] = "0000789019"
    with pytest.raises(ValueError, match="source URLs must belong"):
        command.FrozenCohort.model_validate_json(canonical_bytes(payload))


def test_cohort_rejects_receipt_path_that_escapes_artifacts(tmp_path):
    cohort = _fixture(tmp_path)
    payload = cohort.model_dump(mode="json")
    payload["filings"][0]["source_records"][0]["receipt_refs"][0]["retained_path"] = (
        "../outside"
    )
    changed = command.FrozenCohort.model_validate_json(canonical_bytes(payload))
    report = command.verify_frozen(
        changed, cohort_hash=sha256_digest(changed), evidence_dir=tmp_path
    )
    assert report.sources[0].issue_codes == ("SOURCE_RECEIPT_PATH_INVALID",)


def test_report_output_preserves_previous_evidence(tmp_path):
    cohort = _fixture(tmp_path / "frozen")
    cohort_path = tmp_path / "cohort.json"
    cohort_path.write_bytes(canonical_bytes(cohort))
    output = tmp_path / "report.json"
    output.write_bytes(b"retained earlier report")
    with pytest.raises(SystemExit) as caught:
        command.main(
            [
                "verify",
                "--cohort",
                str(cohort_path),
                "--evidence-dir",
                str(tmp_path / "frozen"),
                "--output",
                str(output),
            ]
        )
    assert caught.value.code == 2
    assert output.read_bytes() == b"retained earlier report"
