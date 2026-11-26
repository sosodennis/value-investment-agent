from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

import fundamental_service.fiscal_discovery as discovery_module
from fundamental_service.fiscal_discovery import (
    FiscalDiscovery,
    FiscalDiscoveryRequestV1,
    required_fiscal_history_files,
    select_fiscal_filings,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_capture import (
    SecFiscalSubmissionsCaptureScopeV1,
    SecSubmissionsCaptureScopeV1,
    sec_response_artifact_id,
)
from fundamental_service.sec_source import (
    SecRequestPolicy,
    SecSourceError,
    _SecResponse,
)
from fundamental_service.sec_submissions import SecRecentFilingsV1
from fundamental_service.sec_submissions import (
    SecSubmissionHistoryReferenceV1,
    SecSubmissionsV1,
    SecFilingsV1,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError

CIK = "0000789019"
CUTOFF = datetime(2024, 2, 20, tzinfo=UTC)
RECENT = f"CIK{CIK}.json"
HISTORY = f"CIK{CIK}-submissions-001.json"


def request(**updates: object) -> FiscalDiscoveryRequestV1:
    return FiscalDiscoveryRequestV1(
        **{
            "cik": CIK,
            "valuation_timestamp": CUTOFF,
            "declared_source_revision": "a" * 40,
            "supported_filing_years": (2021, 2022, 2023, 2024),
            "lookback_days": 3650,
            **updates,
        }
    )


def row(period_end: date, **updates: object) -> dict[str, object]:
    filing_date = period_end + timedelta(days=45)
    accession_year = filing_date.year
    serial = period_end.month * 100 + period_end.day
    return {
        "accessionNumber": f"0000950170-{accession_year % 100:02d}-{serial:06d}",
        "filingDate": filing_date.isoformat(),
        "acceptanceDateTime": f"{filing_date.isoformat()}T16:00:00Z",
        "reportDate": period_end.isoformat(),
        "form": "10-Q",
        "primaryDocument": "quarter.htm",
        "isXBRL": 1,
        "isInlineXBRL": 1,
        **updates,
    }


def rows(*values: dict[str, object]) -> SecRecentFilingsV1:
    return SecRecentFilingsV1(
        **{key: [value[key] for value in values] for key in values[0]}
    )


def eight_periods() -> tuple[dict[str, object], ...]:
    periods = (
        date(2021, 12, 31),
        date(2022, 3, 31),
        date(2022, 6, 30),
        date(2022, 9, 30),
        date(2022, 12, 31),
        date(2023, 3, 31),
        date(2023, 6, 30),
        date(2023, 9, 30),
    )
    return tuple(
        row(period, form="10-K" if period.month == 12 else "10-Q") for period in periods
    )


def select(*values: dict[str, object], at: datetime = CUTOFF):
    return select_fiscal_filings(
        request(valuation_timestamp=at),
        [(sha256_digest(values), rows(*values))],
    )


def test_selects_eight_actual_fiscal_ends_without_using_accession_prefix_as_cik():
    result = select(*eight_periods())

    assert result.issue_codes == ()
    assert len(result.selected) == 8
    assert [item.report_period_end for item in result.selected] == sorted(
        (date.fromisoformat(str(value["reportDate"])) for value in eight_periods()),
        reverse=True,
    )
    assert all(item.cik == CIK for item in result.selected)
    assert all(item.accession_number[:10] != item.cik for item in result.selected)


def test_newest_unsupported_filing_does_not_fall_back_to_old_periods():
    values = list(eight_periods())
    values[-1] = dict(
        values[-1], filingDate="2024-02-01", acceptanceDateTime="2024-02-01T16:00:00Z"
    )
    result = select_fiscal_filings(
        request(
            supported_filing_years=(2022, 2023),
            valuation_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        [(sha256_digest(values), rows(*values))],
    )

    assert result.selected == ()
    assert "FISCAL_LATEST_PERIOD_UNAVAILABLE" in result.issue_codes
    latest = next(
        item
        for item in result.candidates
        if item.accession_number == values[-1]["accessionNumber"]
    )
    assert "FISCAL_RUNTIME_INCOMPATIBLE" in latest.issue_codes


def test_catalog_and_validation_refuse_old_original_when_current_period_conflicts():
    originals = eight_periods()
    older = str(originals[-1]["accessionNumber"])
    unsupported = row(
        date(2023, 9, 30),
        accessionNumber="0000950170-24-999991",
        filingDate="2024-02-01",
        acceptanceDateTime="2024-02-01T16:00:00Z",
        isXBRL=0,
    )
    values = (*originals, unsupported)
    page = [(sha256_digest(values), rows(*values))]
    catalog = select_fiscal_filings(request(), page)
    target = select_fiscal_filings(request(), page, target_accession=older)

    assert catalog.selected == target.selected == ()
    assert (
        catalog.issue_codes == target.issue_codes == ("FISCAL_REPORT_PERIOD_CONFLICT",)
    )
    assert catalog.candidates == target.candidates
    assert catalog.candidates[-1].issue_codes == ("FISCAL_XBRL_UNAVAILABLE",)


def test_unresolved_amendment_for_selected_period_refuses_without_fallback():
    original = eight_periods()
    amendment = row(
        date(2023, 9, 30),
        accessionNumber="0000950170-24-000001",
        filingDate="2024-01-02",
        acceptanceDateTime="2024-01-02T16:00:00Z",
        form="10-Q/A",
    )
    result = select(*original, amendment, at=datetime(2024, 3, 1, tzinfo=UTC))

    assert result.selected == ()
    assert "FISCAL_AMENDMENT_SCOPE_UNKNOWN" in result.issue_codes
    assert any(
        item.accession_number == amendment["accessionNumber"]
        and item.filing is None
        and item.issue_codes == ("FISCAL_AMENDMENT_SCOPE_UNKNOWN",)
        for item in result.candidates
    )


def test_post_cutoff_amendment_cannot_change_historical_selection():
    future_amendment = row(
        date(2023, 9, 30),
        accessionNumber="0000950170-24-000002",
        filingDate="2024-04-02",
        acceptanceDateTime="2024-04-02T16:00:00Z",
        form="10-K/A",
    )
    result = select(*eight_periods(), future_amendment)

    assert result.issue_codes == ()
    assert len(result.selected) == 8
    amended = next(
        item
        for item in result.candidates
        if item.accession_number == future_amendment["accessionNumber"]
    )
    assert amended.issue_codes == ("FISCAL_AFTER_CUTOFF",)


def test_malformed_in_cutoff_amendment_blocks_catalog_instead_of_selecting_old_original():
    malformed = row(
        date(2023, 9, 30),
        accessionNumber="0000950170-24-000003",
        filingDate="2024-01-02",
        acceptanceDateTime="2024-01-02T16:00:00Z",
        reportDate="unknown",
        form="10-K/A",
    )
    result = select(*eight_periods(), malformed, at=datetime(2024, 3, 1, tzinfo=UTC))

    assert result.selected == ()
    assert "FISCAL_AMENDMENT_CATALOG_INCOMPLETE" in result.issue_codes
    assert "FISCAL_AMENDMENT_SCOPE_UNKNOWN" not in result.issue_codes


def test_conflicting_duplicate_accessions_refuse_and_keep_both_candidate_records():
    values = list(eight_periods())
    conflict = dict(values[-1], primaryDocument="different.htm")
    result = select(*values, conflict)

    assert result.selected == ()
    assert "FISCAL_ACCESSION_CONFLICT" in result.issue_codes
    conflicts = [
        item
        for item in result.candidates
        if item.accession_number == values[-1]["accessionNumber"]
    ]
    assert len(conflicts) == 2
    assert all("FISCAL_ACCESSION_CONFLICT" in item.issue_codes for item in conflicts)


def test_acceptance_timestamp_controls_cutoff_within_filing_date():
    values = list(eight_periods())
    values[-2] = dict(
        values[-2], acceptanceDateTime="2024-02-20T00:00:01Z", filingDate="2024-02-19"
    )
    result = select(*values)

    assert result.selected == ()
    latest = next(
        item
        for item in result.candidates
        if item.accession_number == values[-2]["accessionNumber"]
    )
    assert latest.issue_codes == ("FISCAL_AFTER_CUTOFF",)


def test_equivalent_offset_cutoff_keeps_the_available_newest_filing():
    newest = row(
        date(2023, 12, 31),
        filingDate="2024-03-01",
        acceptanceDateTime="2024-03-01T06:00:00Z",
    )
    utc_cutoff = datetime(2024, 3, 1, 7, 30, tzinfo=UTC)
    offset_cutoff = utc_cutoff.astimezone(timezone(timedelta(hours=-8)))
    filings = (*eight_periods(), newest)
    utc_selection = select(*filings, at=utc_cutoff)
    offset_selection = select(*filings, at=offset_cutoff)

    assert offset_selection.selected[0].accession_number == newest["accessionNumber"]
    assert offset_selection == utc_selection
    assert (
        request(valuation_timestamp=offset_cutoff).digest
        == request(valuation_timestamp=utc_cutoff).digest
    )


def test_history_references_are_issuer_scoped_and_bounded():
    request_value = request()
    source = SecSubmissionsV1(
        cik=CIK,
        filings=SecFilingsV1(
            recent=rows(*eight_periods()),
            files=[
                SecSubmissionHistoryReferenceV1(
                    name=f"CIK{CIK}-submissions-001.json",
                    filingCount=1,
                    filingFrom=date(2022, 1, 1),
                    filingTo=date(2023, 12, 31),
                ),
            ],
        ),
    )

    assert required_fiscal_history_files(source, request_value) == (
        f"CIK{CIK}-submissions-001.json",
    )
    foreign = SecSubmissionHistoryReferenceV1(
        name="CIK0000320193-submissions-001.json",
        filingCount=1,
        filingFrom=date(2022, 1, 1),
        filingTo=date(2023, 12, 31),
    )
    source = source.model_copy(
        update={"filings": source.filings.model_copy(update={"files": [foreign]})}
    )
    with pytest.raises(ValueError, match="foreign or reversed scope"):
        required_fiscal_history_files(source, request_value)


@pytest.mark.parametrize(
    "malformed_dates",
    [
        {
            "filingDate": "2024-04-02",
            "acceptanceDateTime": None,
        },
        {
            "filingDate": "invalid",
            "acceptanceDateTime": "2024-04-02T16:00:00Z",
        },
    ],
)
def test_one_proven_future_date_excludes_malformed_amendment(malformed_dates):
    amendment = row(
        date(2023, 9, 30),
        accessionNumber="0000950170-24-000004",
        reportDate="invalid",
        form="10-K/A",
        **malformed_dates,
    )
    result = select(*eight_periods(), amendment)

    assert result.selected == select(*eight_periods()).selected
    assert result.issue_codes == ()
    candidate = next(
        item
        for item in result.candidates
        if item.accession_number == amendment["accessionNumber"]
    )
    assert candidate.issue_codes == ("FISCAL_AFTER_CUTOFF",)


def test_in_cutoff_filing_with_unknown_acceptance_cannot_be_replaced():
    amendment = row(
        date(2023, 9, 30),
        accessionNumber="0000950170-24-000005",
        form="10-Q/A",
        acceptanceDateTime=None,
    )
    result = select(*eight_periods(), amendment)

    assert result.selected == ()
    assert result.issue_codes == ("FISCAL_AMENDMENT_CATALOG_INCOMPLETE",)


def uri(filename):
    return f"https://data.sec.gov/submissions/{filename}"


class SyntheticSecTransport:
    policy = SecRequestPolicy(
        user_agent="fiscal-discovery-test test@example.com", max_attempts=1
    )

    def __init__(self, at):
        periods = eight_periods()
        old = row(date(2013, 12, 31), form="8-K")
        self.pages = {
            uri(RECENT): canonical_bytes(
                {
                    "cik": int(CIK),
                    "filings": {
                        "recent": rows(*periods[3:]).model_dump(),
                        "files": [
                            {
                                "name": HISTORY,
                                "filingCount": 5,
                                "filingFrom": old["filingDate"],
                                "filingTo": periods[3]["filingDate"],
                            }
                        ],
                    },
                }
            ),
            uri(HISTORY): canonical_bytes(rows(old, *periods[:4])),
        }
        self.at = at
        self.calls = []
        self.fail_history = False

    def _request(self, uri, *, deadline_at=None):
        self.calls.append((uri, deadline_at))
        if uri.endswith(HISTORY) and self.fail_history:
            raise SecSourceError("SOURCE_UNAVAILABLE", "temporary", retryable=True)
        payload = self.pages[uri]
        assert len(payload) <= self.policy.response_limit(uri)
        return _SecResponse(
            content=payload,
            http_status=200,
            media_type="application/json",
            available_at=self.at,
            response_headers=(("etag", '"synthetic"'),),
            declared_size=len(payload),
        )


@contextmanager
def uncontended_lock(_key):
    yield


class DiscoveryHarness:
    def __init__(self, root):
        self.root = root
        self.now = datetime.now(UTC)
        self.deadline = self.now + timedelta(minutes=5)
        self.provider = SyntheticSecTransport(self.now)
        self.artifacts = ArtifactStore(root / "artifacts")
        self.content = FilesystemContentStore(root / "content")
        self.request = request()

    def discovery(self, *, capture_lock=uncontended_lock):
        return FiscalDiscovery(
            provider=self.provider,
            artifacts=self.artifacts,
            content=self.content,
            capture_lock=capture_lock,
            clock=lambda: self.now,
        )

    def publish(self):
        return self.discovery().execute(self.request, deadline_at=self.deadline)

    def read(self, artifact_id):
        return self.discovery().read(artifact_id, deadline_at=self.deadline)

    def ids(self, evidence):
        request_id = f"fiscal-discovery-request:{self.request.digest}"
        receipt = evidence.sources[-1].receipt
        assert receipt is not None
        return {
            "discovery": evidence.artifact_id,
            "request": request_id,
            "receipt": sec_response_artifact_id(receipt.scope, receipt.uri),
        }

    def inventory(self):
        return {
            path.relative_to(self.root): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def replace_record(self, record):
        with (self.artifacts.root / ".artifact-records.jsonl").open("ab") as log:
            log.write(canonical_bytes(record) + b"\n")

    def replace_value(self, artifact_id, value, *, dependency_hashes=None):
        record = self.artifacts.get(artifact_id)
        payload = canonical_bytes(value)
        content_hash = hashlib.sha256(payload).hexdigest()
        self.artifacts._artifact_path(content_hash, record.media_type).write_bytes(
            payload
        )
        self.replace_record(
            record.model_copy(
                update={
                    "content_hash": content_hash,
                    "dependency_hashes": (
                        record.dependency_hashes
                        if dependency_hashes is None
                        else dependency_hashes
                    ),
                }
            )
        )


@pytest.fixture
def harness(tmp_path):
    return DiscoveryHarness(tmp_path)


def test_retained_fiscal_discovery_replays_original_pages_without_writing(harness):
    evidence, publication = harness.publish()
    scope = SecFiscalSubmissionsCaptureScopeV1(cik=CIK, valuation_timestamp=CUTOFF)
    annual_scope = SecSubmissionsCaptureScopeV1(cik=CIK, valuation_timestamp=CUTOFF)
    assert publication.wrote
    assert (
        publication.artifact.artifact_id == f"fiscal-discovery:{harness.request.digest}"
    )
    assert publication.artifact.status == "valid"
    assert publication.artifact.retention == "evidence"
    assert evidence.selection.issue_codes == ()
    assert [str(item.report_period_end) for item in evidence.selection.selected] == [
        str(value["reportDate"]) for value in reversed(eight_periods())
    ]
    dependencies = {harness.request.digest}
    page_hashes = []
    assert [capture.filename for capture in evidence.sources] == [RECENT, HISTORY]
    for capture in evidence.sources:
        receipt = capture.receipt
        assert receipt is not None and type(receipt.scope) is type(scope)
        assert receipt.scope == scope
        source_uri = uri(capture.filename)
        assert receipt.uri == source_uri
        raw = harness.provider.pages[source_uri]
        source_hash = hashlib.sha256(raw).hexdigest()
        page_hashes.append(source_hash)
        assert receipt.content_hash == source_hash
        assert harness.content.get(source_hash, media_type="application/json") == raw
        receipt_id = sec_response_artifact_id(scope, source_uri)
        assert harness.artifacts.read(receipt_id) == canonical_bytes(receipt)
        assert harness.artifacts.get(receipt_id).dependency_hashes == (source_hash,)
        dependencies.update((source_hash, sha256_digest(receipt)))
        with pytest.raises(SnapshotError) as missing:
            harness.artifacts.get(sec_response_artifact_id(annual_scope, source_uri))
        assert missing.value.code == "ARTIFACT_NOT_FOUND"
    overlap = next(
        candidate
        for candidate in evidence.selection.candidates
        if candidate.accession_number == eight_periods()[3]["accessionNumber"]
    )
    assert overlap.source_digests == tuple(sorted(page_hashes))
    assert publication.artifact.dependency_hashes == tuple(sorted(dependencies))
    assert harness.artifacts.read(evidence.artifact_id) == canonical_bytes(evidence)
    assert harness.artifacts.read(harness.ids(evidence)["request"]) == canonical_bytes(
        harness.request
    )
    before = harness.inventory()
    harness.artifacts = ArtifactStore(harness.artifacts.root)
    harness.content = FilesystemContentStore(harness.content.root)
    assert harness.read(evidence.artifact_id) == evidence
    replayed, replay = harness.publish()
    assert replayed == evidence
    assert not replay.wrote and replay.artifact == publication.artifact
    assert harness.provider.calls == [
        (uri(RECENT), harness.deadline),
        (uri(HISTORY), harness.deadline),
    ]
    assert harness.inventory() == before


def test_retry_reuses_successful_page_and_preserves_failed_attempt(harness):
    harness.provider.fail_history = True
    attempt, failed = harness.publish()
    assert failed.wrote and attempt.is_retry_attempt and not attempt.selection.selected
    assert failed.artifact.artifact_id == f"fiscal-discovery-attempt:{attempt.digest}"
    assert attempt.sources[0].receipt is not None
    assert attempt.sources[1].receipt is None
    assert attempt.sources[1].issue_codes == ("SOURCE_UNAVAILABLE",)
    assert harness.read(attempt.artifact_id) == attempt
    attempt_bytes = harness.artifacts.read(attempt.artifact_id)
    repeated, duplicate = harness.publish()
    assert repeated == attempt and not duplicate.wrote

    harness.provider.fail_history = False
    complete, publication = harness.publish()
    assert publication.wrote and len(complete.selection.selected) == 8
    assert complete.sources[0] == attempt.sources[0]
    assert harness.artifacts.read(attempt.artifact_id) == attempt_bytes
    assert harness.read(attempt.artifact_id) == attempt
    assert harness.read(complete.artifact_id) == complete
    assert [called for called, _ in harness.provider.calls] == [
        uri(RECENT),
        uri(HISTORY),
        uri(HISTORY),
        uri(HISTORY),
    ]


@pytest.mark.parametrize("target", ["discovery", "request", "receipt", "source"])
def test_owner_read_rejects_corrupted_retained_bytes(harness, target):
    evidence, _ = harness.publish()
    assert len(evidence.selection.selected) == 8
    if target == "source":
        receipt = evidence.sources[-1].receipt
        assert receipt is not None
        harness.content._path(receipt.content_hash, receipt.media_type).write_bytes(
            b"corrupt"
        )
    else:
        record = harness.artifacts.get(harness.ids(evidence)[target])
        harness.artifacts._artifact_path(
            record.content_hash, record.media_type
        ).write_bytes(b"corrupt")
    with pytest.raises(SnapshotError) as failure:
        harness.read(evidence.artifact_id)
    assert failure.value.code == "FISCAL_DISCOVERY_INVALID"
    assert len(harness.provider.calls) == 2


@pytest.mark.parametrize("target", ["discovery", "request", "receipt"])
@pytest.mark.parametrize("change", ["dependencies", "revocation"])
def test_owner_read_rejects_changed_metadata(harness, target, change):
    evidence, _ = harness.publish()
    artifact_id = harness.ids(evidence)[target]
    if change == "revocation":
        harness.artifacts.invalidate(artifact_id)
    else:
        record = harness.artifacts.get(artifact_id)
        harness.replace_record(
            record.model_copy(update={"dependency_hashes": ("a" * 64,)})
        )
    with pytest.raises(SnapshotError) as failure:
        harness.read(evidence.artifact_id)
    assert failure.value.code == "FISCAL_DISCOVERY_INVALID"
    assert len(harness.provider.calls) == 2


@pytest.mark.parametrize(
    "change", ["candidate", "selection", "history_omitted", "receipt_omitted", "scope"]
)
def test_owner_rederives_fiscal_evidence_despite_recomputed_artifact_hash(
    harness, change
):
    evidence, _ = harness.publish()
    assert len(evidence.selection.selected) == 8
    recent, history = evidence.sources
    if change == "history_omitted":
        altered = evidence.model_copy(update={"sources": (recent,)})
    elif change == "receipt_omitted":
        assert recent.receipt is not None
        recent_only = select_fiscal_filings(
            harness.request,
            [(recent.receipt.content_hash, rows(*eight_periods()[3:]))],
        )
        altered = evidence.model_copy(
            update={
                "sources": (
                    recent,
                    history.model_copy(
                        update={"receipt": None, "issue_codes": ("SOURCE_UNAVAILABLE",)}
                    ),
                ),
                "selection": recent_only.model_copy(
                    update={
                        "issue_codes": (
                            "FISCAL_HISTORY_COVERAGE_INCOMPLETE",
                            "FISCAL_SOURCE_COUNT_INSUFFICIENT",
                            "SOURCE_UNAVAILABLE",
                        )
                    }
                ),
            }
        )
    elif change == "scope":
        assert history.receipt is not None
        old = history.receipt
        annual_scope = SecSubmissionsCaptureScopeV1(cik=CIK, valuation_timestamp=CUTOFF)
        receipt = old.model_copy(update={"scope": annual_scope})
        harness.replace_value(sec_response_artifact_id(old.scope, old.uri), receipt)
        altered = evidence.model_copy(
            update={
                "sources": (recent, history.model_copy(update={"receipt": receipt}))
            }
        )
    else:
        selection = evidence.selection
        if change == "candidate":
            candidate, *rest = selection.candidates
            changed = candidate.model_copy(update={"source_digests": ("a" * 64,)})
            selection = selection.model_copy(update={"candidates": (changed, *rest)})
        else:
            selection = selection.model_copy(
                update={"selected": selection.selected[::-1]}
            )
        altered = evidence.model_copy(update={"selection": selection})
    harness.replace_value(
        evidence.artifact_id, altered, dependency_hashes=altered.dependencies
    )
    with pytest.raises(SnapshotError) as failure:
        harness.read(evidence.artifact_id)
    assert failure.value.code == "FISCAL_DISCOVERY_INVALID"
    assert len(harness.provider.calls) == 2


@pytest.mark.parametrize("target", ["discovery", "request", "receipt"])
def test_owner_read_rejects_revocation_during_selection(harness, monkeypatch, target):
    evidence, _ = harness.publish()
    artifact_id = harness.ids(evidence)[target]
    select_original = discovery_module.select_fiscal_filings

    def revoke_after_selection(*args, **kwargs):
        result = select_original(*args, **kwargs)
        harness.artifacts.invalidate(artifact_id)
        return result

    monkeypatch.setattr(
        discovery_module, "select_fiscal_filings", revoke_after_selection
    )
    with pytest.raises(SnapshotError) as failure:
        harness.read(evidence.artifact_id)
    assert failure.value.code == "FISCAL_DISCOVERY_INVALID"
    assert len(harness.provider.calls) == 2


@pytest.mark.parametrize("target", ["discovery", "request", "receipt"])
def test_owner_read_rejects_metadata_revoked_after_its_bytes_are_read(
    harness, monkeypatch, target
):
    evidence, _ = harness.publish()
    target_id = harness.ids(evidence)[target]
    read_original = harness.artifacts.read

    def read_then_revoke(artifact_id):
        payload = read_original(artifact_id)
        if artifact_id == target_id:
            harness.artifacts.invalidate(artifact_id)
        return payload

    monkeypatch.setattr(harness.artifacts, "read", read_then_revoke)
    with pytest.raises(SnapshotError) as failure:
        harness.read(evidence.artifact_id)
    assert failure.value.code == "FISCAL_DISCOVERY_INVALID"


def test_retained_read_has_no_lookahead_from_malformed_future_amendment(harness):
    recent_uri = uri(RECENT)
    recent = json.loads(harness.provider.pages[recent_uri])
    amendment = row(
        date(2023, 9, 30),
        accessionNumber="0000950170-24-000006",
        filingDate="invalid",
        acceptanceDateTime="2024-04-02T16:00:00Z",
        reportDate="invalid",
        form="10-Q/A",
    )
    for field, value in amendment.items():
        recent["filings"]["recent"][field].append(value)
    harness.provider.pages[recent_uri] = canonical_bytes(recent)

    evidence, _ = harness.publish()
    assert len(evidence.selection.selected) == 8
    assert evidence.selection.issue_codes == ()
    assert harness.read(evidence.artifact_id) == evidence


@pytest.mark.parametrize("operation", ["read", "cached_execute"])
@pytest.mark.parametrize("when", ["before", "during"])
def test_retained_deadline_never_returns_success(harness, monkeypatch, operation, when):
    evidence, _ = harness.publish()
    if when == "before":
        harness.now = harness.deadline
    else:
        select_original = discovery_module.select_fiscal_filings

        def expire_after_selection(*args, **kwargs):
            result = select_original(*args, **kwargs)
            harness.now = harness.deadline
            return result

        monkeypatch.setattr(
            discovery_module, "select_fiscal_filings", expire_after_selection
        )
    with pytest.raises(SecSourceError) as failure:
        if operation == "read":
            harness.read(evidence.artifact_id)
        else:
            harness.publish()
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert failure.value.retryable
    assert len(harness.provider.calls) == 2


@pytest.mark.parametrize("lock_number", [1, 2])
def test_deadline_expiry_while_acquiring_lock_does_not_call_sec(harness, lock_number):
    entered = 0

    @contextmanager
    def expired_lock(_key):
        nonlocal entered
        entered += 1
        if entered == lock_number:
            harness.now = harness.deadline
        yield

    with pytest.raises(SecSourceError) as failure:
        harness.discovery(capture_lock=expired_lock).execute(
            harness.request, deadline_at=harness.deadline
        )
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert harness.provider.calls == []


def test_retained_read_stops_before_reading_more_bytes_after_deadline(
    harness, monkeypatch
):
    evidence, _ = harness.publish()
    history_receipt_id = harness.ids(evidence)["receipt"]
    read_original = harness.artifacts.read
    get_original = harness.content.get
    source_reads = []

    def read_receipt_then_expire(artifact_id):
        payload = read_original(artifact_id)
        if artifact_id == history_receipt_id:
            harness.now = harness.deadline
        return payload

    def read_source(content_hash, *, media_type):
        source_reads.append(content_hash)
        return get_original(content_hash, media_type=media_type)

    monkeypatch.setattr(harness.artifacts, "read", read_receipt_then_expire)
    monkeypatch.setattr(harness.content, "get", read_source)
    with pytest.raises(SecSourceError) as failure:
        harness.read(evidence.artifact_id)
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    recent_receipt = evidence.sources[0].receipt
    assert recent_receipt is not None
    assert source_reads == [recent_receipt.content_hash]
