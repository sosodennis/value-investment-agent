from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from .fiscal_source_closure import FiscalArtifactReadSet, FiscalSourceContentReadSet

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .annual_discovery import decode_history, decode_submissions
from .command_artifacts import EvidenceArtifactStore
from .contracts import StrictModel
from .fiscal_source_contracts import FiscalFilingV1
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .sec_capture import (
    RetainedSecSourceAdapter,
    SecFiscalSubmissionsCaptureScopeV1,
    SecResponseReceiptV1,
    SecCaptureStore,
    sec_response_artifact_id,
)
from .sec_source import SecRequestTransportPort, SecSourceError
from .sec_submissions import SecRecentFilingsV1, SecSubmissionsV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError


class FiscalDiscoveryRequestV1(StrictModel):
    protocol: Literal["fundamental.fiscal-discovery-request.v1"] = (
        "fundamental.fiscal-discovery-request.v1"
    )
    cik: str = Field(pattern=r"^[0-9]{10}$")
    valuation_timestamp: AwareDatetime
    declared_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    supported_filing_years: tuple[int, ...] = Field(min_length=1)
    lookback_days: int = Field(default=3650, ge=1, le=3650)
    maximum_history_files: int = Field(default=16, ge=1, le=32)

    @field_validator("valuation_timestamp")
    @classmethod
    def cutoff_is_utc(cls, cutoff: datetime) -> datetime:
        return cutoff.astimezone(UTC)

    @field_validator("supported_filing_years")
    @classmethod
    def canonical_years(cls, years: tuple[int, ...]) -> tuple[int, ...]:
        if any(year < 1900 or year > 2200 for year in years):
            raise ValueError("unsupported fiscal filing year")
        return tuple(sorted(set(years)))

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class FiscalSourceCaptureV1(StrictModel):
    filename: str = Field(pattern=r"^CIK[0-9]{10}(?:-submissions-[0-9]{3})?\.json$")
    receipt: SecResponseReceiptV1 | None
    issue_codes: tuple[str, ...] = ()
    retryable: bool = False

    @field_validator("issue_codes")
    @classmethod
    def canonical_issues(cls, issues: tuple[str, ...]) -> tuple[str, ...]:
        if issues != tuple(sorted(set(issues))):
            raise ValueError("fiscal capture issues must be canonical")
        return issues

    @model_validator(mode="after")
    def capture_outcome(self) -> FiscalSourceCaptureV1:
        if self.receipt is None and not self.issue_codes:
            raise ValueError("a missing fiscal capture requires a reason")
        if self.receipt is not None and (self.issue_codes or self.retryable):
            raise ValueError("retained fiscal capture outcomes derive from the payload")
        return self


class FiscalCandidateV1(StrictModel):
    accession_number: str
    raw_form: str
    record_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_digests: tuple[str, ...]
    filing: FiscalFilingV1 | None
    issue_codes: tuple[str, ...]


class FiscalSelectionV1(StrictModel):
    candidates: tuple[FiscalCandidateV1, ...]
    selected: tuple[FiscalFilingV1, ...]
    issue_codes: tuple[str, ...]


class FiscalDiscoveryEvidenceV1(StrictModel):
    protocol: Literal["fundamental.fiscal-discovery-evidence.v1"] = (
        "fundamental.fiscal-discovery-evidence.v1"
    )
    request: FiscalDiscoveryRequestV1
    sources: tuple[FiscalSourceCaptureV1, ...]
    selection: FiscalSelectionV1

    @property
    def is_retry_attempt(self) -> bool:
        return any(source.retryable for source in self.sources)

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        return (
            f"fiscal-discovery-attempt:{self.digest}"
            if self.is_retry_attempt
            else f"fiscal-discovery:{self.request.digest}"
        )

    @property
    def dependencies(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.request.digest,
                    *(
                        value
                        for source in self.sources
                        if source.receipt is not None
                        for value in (
                            source.receipt.content_hash,
                            sha256_digest(source.receipt),
                        )
                    ),
                }
            )
        )


def required_fiscal_history_files(
    source: SecSubmissionsV1, request: FiscalDiscoveryRequestV1
) -> tuple[str, ...]:
    lower_bound = request.valuation_timestamp.date() - timedelta(
        days=request.lookback_days
    )
    names: set[str] = set()
    references = source.filings.files or ()
    if len({item.name for item in references}) != len(references):
        raise ValueError("duplicate SEC submission history reference")
    for item in references:
        if (
            not item.name.startswith(f"CIK{request.cik}-")
            or item.filingFrom > item.filingTo
        ):
            raise ValueError("SEC history reference has foreign or reversed scope")
        if (
            item.filingTo >= lower_bound
            and item.filingFrom <= request.valuation_timestamp.date()
        ):
            names.add(item.name)
    if len(names) > request.maximum_history_files:
        raise ValueError("SEC history exceeds the discovery bound")
    return tuple(sorted(names))


def _flag(value: object) -> bool:
    normalized = str(value).lower()
    if normalized not in {"0", "1", "false", "true"}:
        raise ValueError("invalid SEC XBRL flag")
    return normalized in {"1", "true"}


def _parse_filing_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_acceptance(value: object) -> datetime | None:
    try:
        accepted_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return accepted_at if accepted_at.utcoffset() is not None else None


def _timing_issue(
    filing_date: date | None,
    accepted_at: datetime | None,
    cutoff: datetime,
    lower_bound: date,
) -> str | None:
    if (filing_date is not None and filing_date > cutoff.date()) or (
        accepted_at is not None and accepted_at > cutoff
    ):
        return "FISCAL_AFTER_CUTOFF"
    if filing_date is not None and filing_date < lower_bound:
        return "FISCAL_OUTSIDE_LOOKBACK"
    return None


def _preferred_originals(
    originals: set[tuple[str, str]],
) -> set[tuple[str, str]]:
    return {original for original in originals if original[0] == "10-K"} or originals


def select_fiscal_filings(
    request: FiscalDiscoveryRequestV1,
    sources: Iterable[tuple[str, SecRecentFilingsV1]],
    *,
    target_accession: str | None = None,
) -> FiscalSelectionV1:
    records: dict[tuple[str, str], tuple[dict[str, object], set[str]]] = {}
    for source_digest, rows in sources:
        rows.require_aligned_columns()
        for index, accession in enumerate(rows.accessionNumber):
            record: dict[str, object] = {
                "accessionNumber": accession,
                "filingDate": rows.filingDate[index],
                "acceptanceDateTime": rows.acceptanceDateTime[index],
                "form": rows.form[index],
                "primaryDocument": rows.primaryDocument[index],
                "isXBRL": rows.isXBRL[index],
            }
            for column in ("isInlineXBRL", "reportDate"):
                values = getattr(rows, column)
                if values is not None:
                    record[column] = values[index]
            digest = sha256_digest(record)
            records.setdefault((accession, digest), (record, set()))[1].add(
                source_digest
            )

    lower_bound = request.valuation_timestamp.date() - timedelta(
        days=request.lookback_days
    )
    filing_timing = {}
    by_accession: dict[str, set[str]] = defaultdict(set)
    for key, (record, _) in records.items():
        filing_date = _parse_filing_date(record["filingDate"])
        accepted_at = _parse_acceptance(record["acceptanceDateTime"])
        timing_issue = _timing_issue(
            filing_date, accepted_at, request.valuation_timestamp, lower_bound
        )
        filing_timing[key] = (filing_date, accepted_at, timing_issue)
        if timing_issue is None:
            accession, digest = key
            by_accession[accession].add(digest)
    conflicts = {
        accession for accession, digests in by_accession.items() if len(digests) > 1
    }
    candidates: list[FiscalCandidateV1] = []
    eligible: list[FiscalFilingV1] = []
    global_issues: set[str] = set()
    amendments_by_period: dict[date, list[str]] = defaultdict(list)
    originals_by_period: dict[date, set[tuple[str, str]]] = defaultdict(set)
    in_scope_periods: set[date] = set()

    for (accession, digest), (record, source_digests) in sorted(records.items()):
        raw_form = str(record.get("form", ""))
        issue_codes: set[str] = set()
        filing: FiscalFilingV1 | None = None
        base_form = raw_form.removesuffix("/A")
        is_amendment = raw_form.endswith("/A")
        filing_date, accepted_at, timing_issue = filing_timing[accession, digest]
        if accession in conflicts and timing_issue is None:
            issue_codes.add("FISCAL_ACCESSION_CONFLICT")
        if base_form not in {"10-Q", "10-K"} or raw_form not in {
            "10-Q",
            "10-K",
            "10-Q/A",
            "10-K/A",
        }:
            issue_codes.add("FISCAL_FORM_EXCLUDED")
        elif timing_issue is not None:
            issue_codes.add(timing_issue)
        else:
            try:
                if filing_date is None or accepted_at is None:
                    raise ValueError("SEC filing or acceptance date is unavailable")
                report_period_raw = record.get("reportDate")
                if report_period_raw in {None, ""}:
                    raise ValueError("SEC filing period is missing")
                report_period_end = date.fromisoformat(str(report_period_raw))
                if (
                    report_period_end > filing_date
                    or report_period_end > accepted_at.astimezone(UTC).date()
                ):
                    raise ValueError("SEC report period follows its filing")
                in_scope_periods.add(report_period_end)
                if not is_amendment:
                    originals_by_period[report_period_end].add((base_form, accession))
                if is_amendment:
                    issue_codes.add("FISCAL_AMENDMENT_SCOPE_UNKNOWN")
                    amendments_by_period[report_period_end].append(accession)
                elif accession in conflicts:
                    global_issues.add("FISCAL_ACCESSION_CONFLICT")
                elif filing_date.year not in request.supported_filing_years:
                    issue_codes.add("FISCAL_RUNTIME_INCOMPATIBLE")
                elif not _flag(record["isXBRL"]):
                    issue_codes.add("FISCAL_XBRL_UNAVAILABLE")
                else:
                    filing = FiscalFilingV1(
                        cik=request.cik,
                        accession_number=accession,
                        form="10-K" if raw_form == "10-K" else "10-Q",
                        filing_date=filing_date,
                        accepted_at=accepted_at.astimezone(UTC),
                        report_period_end=report_period_end,
                        primary_document=str(record["primaryDocument"]),
                        is_xbrl=True,
                        is_inline_xbrl=_flag(record["isInlineXBRL"])
                        if "isInlineXBRL" in record
                        else None,
                    )
                    eligible.append(filing)
            except (KeyError, TypeError, ValueError):
                issue_codes.add("FISCAL_METADATA_INVALID")
                if is_amendment:
                    issue_codes.add("FISCAL_AMENDMENT_CATALOG_INCOMPLETE")
                    global_issues.add("FISCAL_AMENDMENT_CATALOG_INCOMPLETE")
                else:
                    global_issues.add("FISCAL_METADATA_INVALID")
        candidates.append(
            FiscalCandidateV1(
                accession_number=accession,
                raw_form=raw_form,
                record_digest=digest,
                source_digests=tuple(sorted(source_digests)),
                filing=filing,
                issue_codes=tuple(sorted(issue_codes)),
            )
        )

    latest_by_period: dict[date, list[FiscalFilingV1]] = defaultdict(list)
    for filing in eligible:
        latest_by_period[filing.report_period_end].append(filing)
    if target_accession is not None:
        matches = [
            filing for filing in eligible if filing.accession_number == target_accession
        ]
        if len(matches) != 1:
            global_issues.add("FISCAL_CANDIDATE_INELIGIBLE")
        else:
            target = matches[0]
            period = target.report_period_end
            if amendments_by_period.get(period):
                global_issues.add("FISCAL_AMENDMENT_SCOPE_UNKNOWN")
            if _preferred_originals(originals_by_period[period]) != {
                (target.form, target_accession)
            }:
                global_issues.add("FISCAL_REPORT_PERIOD_CONFLICT")
        return FiscalSelectionV1(
            candidates=tuple(candidates),
            selected=tuple(matches) if not global_issues else (),
            issue_codes=tuple(sorted(global_issues)),
        )
    target_periods = tuple(sorted(in_scope_periods, reverse=True)[:8])
    selected: list[FiscalFilingV1] = []
    if len(target_periods) < 8:
        global_issues.add("FISCAL_SOURCE_COUNT_INSUFFICIENT")
    for period_end in target_periods:
        period_filings = latest_by_period.get(period_end, [])
        if amendments_by_period.get(period_end):
            global_issues.add("FISCAL_AMENDMENT_SCOPE_UNKNOWN")
            continue
        if not period_filings:
            global_issues.add("FISCAL_LATEST_PERIOD_UNAVAILABLE")
            continue
        preferred = _preferred_originals(originals_by_period[period_end])
        if len(preferred) != 1:
            global_issues.add("FISCAL_REPORT_PERIOD_CONFLICT")
            continue
        chosen = next(
            (
                item
                for item in period_filings
                if (item.form, item.accession_number) in preferred
            ),
            None,
        )
        if chosen is None:
            global_issues.add("FISCAL_LATEST_PERIOD_UNAVAILABLE")
            continue
        selected.append(chosen)
    return FiscalSelectionV1(
        candidates=tuple(candidates),
        selected=tuple(selected) if not global_issues else (),
        issue_codes=tuple(sorted(global_issues)),
    )


class FiscalDiscoveryStore(EvidenceArtifactStore, SecCaptureStore, Protocol):
    pass


@dataclass(frozen=True)
class _CapturedPage:
    source: FiscalSourceCaptureV1
    record: ArtifactRecordV1 | None = None
    payload: bytes | None = None


@dataclass(frozen=True)
class _VerifiedDiscovery:
    evidence: FiscalDiscoveryEvidenceV1
    records: tuple[tuple[str, ArtifactRecordV1 | None], ...]
    target: FiscalSelectionV1 | None
    input_footprint: tuple[object, ...]
    artifact_readset: FiscalArtifactReadSet
    content_readsets: tuple[FiscalSourceContentReadSet, ...]


class FiscalDiscovery:
    def __init__(
        self,
        *,
        provider: SecRequestTransportPort,
        artifacts: FiscalDiscoveryStore,
        content: ContentAddressedStore,
        capture_lock: Callable[[str], AbstractContextManager[None]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        operation: Callable[
            [datetime], AbstractContextManager[None]
        ] = lambda _: nullcontext(),
    ) -> None:
        self._provider = provider
        self._artifacts = artifacts
        self._content = content
        self._capture_lock = capture_lock
        self._clock = clock
        self._operation = operation

    @staticmethod
    def _uri(filename: str) -> str:
        return f"https://data.sec.gov/submissions/{filename}"

    def _before_deadline(self, deadline_at: datetime) -> datetime:
        now = self._clock()
        if (
            deadline_at.utcoffset() is None
            or now.utcoffset() is None
            or deadline_at <= now
        ):
            raise SecSourceError(
                "REQUEST_DEADLINE_EXCEEDED",
                "fiscal discovery deadline expired",
                retryable=True,
            )
        return now

    def _adapter(
        self, request: FiscalDiscoveryRequestV1, check_deadline: Callable[[], datetime]
    ) -> RetainedSecSourceAdapter:
        return RetainedSecSourceAdapter(
            self._provider,
            scope=SecFiscalSubmissionsCaptureScopeV1(
                cik=request.cik, valuation_timestamp=request.valuation_timestamp
            ),
            receipts=self._artifacts,
            content=self._content,
            capture_lock=self._capture_lock,
            check_deadline=check_deadline,
        )

    def _capture(
        self,
        adapter: RetainedSecSourceAdapter,
        filename: str,
        *,
        deadline_at: datetime,
    ) -> _CapturedPage:
        codes: tuple[str, ...] = ()
        retryable = False
        try:
            if "-submissions-" in filename:
                adapter.capture_submission_history(
                    cik=adapter.scope.cik,
                    filename=filename,
                    deadline_at=deadline_at,
                )
            else:
                adapter.capture_submissions(adapter.scope.cik, deadline_at=deadline_at)
        except SecSourceError as error:
            if error.code == "REQUEST_DEADLINE_EXCEEDED":
                raise
            codes = (error.code,)
            retryable = error.retryable
        retained = adapter.read_retained_response_with_record(self._uri(filename))
        if retained is not None:
            receipt, record, response = retained
            return _CapturedPage(
                FiscalSourceCaptureV1(filename=filename, receipt=receipt),
                record,
                response.content,
            )
        return _CapturedPage(
            FiscalSourceCaptureV1(
                filename=filename, receipt=None, issue_codes=codes, retryable=retryable
            )
        )

    def _history_names(
        self, request: FiscalDiscoveryRequestV1, payload: bytes | None
    ) -> tuple[str, ...]:
        if payload is None:
            return ()
        try:
            submissions = decode_submissions(payload, request.cik)
            return required_fiscal_history_files(submissions, request)
        except ValueError:
            return ()

    def _assess(
        self,
        request: FiscalDiscoveryRequestV1,
        pages: tuple[_CapturedPage, ...],
        *,
        target_accession: str | None = None,
    ) -> FiscalSelectionV1:
        sources = tuple(page.source for page in pages)
        if not sources or sources[0].filename != f"CIK{request.cik}.json":
            raise ValueError("fiscal discovery must start with issuer submissions")
        expected_history = self._history_names(request, pages[0].payload)
        if tuple(item.filename for item in sources[1:]) != expected_history:
            raise ValueError("fiscal discovery omitted or reordered a history shard")
        issues = {code for item in sources for code in item.issue_codes}
        decoded_sources: list[tuple[str, SecRecentFilingsV1]] = []
        earliest_dates: list[date] = []
        for index, page in enumerate(pages):
            receipt = page.source.receipt
            raw = page.payload
            if receipt is None or raw is None:
                continue
            try:
                if index == 0:
                    submissions = decode_submissions(raw, request.cik)
                    rows = submissions.filings.recent
                else:
                    rows = decode_history(raw)
                earliest_dates.extend(
                    day
                    for value in rows.filingDate
                    if (day := _parse_filing_date(value)) is not None
                )
            except (ValueError, TypeError):
                issues.add(
                    "FISCAL_SUBMISSIONS_INVALID"
                    if index == 0
                    else "FISCAL_HISTORY_INVALID"
                )
                continue
            decoded_sources.append((receipt.content_hash, rows))
            if index == 0:
                try:
                    required_fiscal_history_files(submissions, request)
                except ValueError:
                    issues.add("FISCAL_HISTORY_REFERENCES_INVALID")
        lower_bound = request.valuation_timestamp.date() - timedelta(
            days=request.lookback_days
        )
        if not earliest_dates or min(earliest_dates) > lower_bound:
            issues.add("FISCAL_HISTORY_COVERAGE_INCOMPLETE")
        selection = (
            select_fiscal_filings(request, decoded_sources)
            if target_accession is None
            else select_fiscal_filings(
                request, decoded_sources, target_accession=target_accession
            )
        )
        issues.update(selection.issue_codes)
        return FiscalSelectionV1(
            candidates=selection.candidates,
            selected=() if issues else selection.selected,
            issue_codes=tuple(sorted(issues)),
        )

    def _current_record(
        self, artifact_id: str, check_deadline: Callable[[], datetime]
    ) -> ArtifactRecordV1 | None:
        check_deadline()
        try:
            record = self._artifacts.get(artifact_id)
        except SnapshotError as error:
            if error.code != "ARTIFACT_NOT_FOUND":
                raise
            record = None
        check_deadline()
        return record

    def _assert_current(
        self,
        records: dict[str, ArtifactRecordV1 | None],
        check_deadline: Callable[[], datetime],
    ) -> None:
        for artifact_id, expected in records.items():
            if self._current_record(artifact_id, check_deadline) != expected:
                raise SnapshotError(
                    "FISCAL_DISCOVERY_INVALID", "fiscal discovery metadata changed"
                )
        check_deadline()

    def read(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> FiscalDiscoveryEvidenceV1:
        with self._operation(deadline_at):
            check_deadline = partial(self._before_deadline, deadline_at)
            record = self._current_record(artifact_id, check_deadline)
            if record is None:
                raise SnapshotError(
                    "ARTIFACT_NOT_FOUND", "fiscal discovery is unavailable"
                )
            return self._read(artifact_id, record, check_deadline).evidence

    def read_with_inputs(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> _VerifiedDiscovery:
        with self._operation(deadline_at):
            check = partial(self._before_deadline, deadline_at)
            record = self._current_record(artifact_id, check)
            if record is None:
                raise SnapshotError(
                    "ARTIFACT_NOT_FOUND", "fiscal discovery is unavailable"
                )
            return self._read(artifact_id, record, check)

    def read_current_inputs(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> _VerifiedDiscovery:
        from .fiscal_source_closure import (
            _FiscalSourceArtifactRead,
            FiscalSourceContentRead,
        )

        with self._operation(deadline_at):
            check = partial(self._before_deadline, deadline_at)
            reader = _FiscalSourceArtifactRead(self._artifacts, check, artifact_id)
            content = FiscalSourceContentRead(self._content, check)
            raw = reader.read(artifact_id)
            evidence = FiscalDiscoveryEvidenceV1.model_validate_json(raw)
            record = reader.get(artifact_id)
            if (
                evidence.artifact_id != artifact_id
                or canonical_bytes(evidence) != raw
                or record.media_type != "application/json"
                or record.dependency_hashes != evidence.dependencies
            ):
                raise SnapshotError(
                    "FISCAL_DISCOVERY_INVALID", "current discovery identity differs"
                )
            reader._discovery_edges(evidence)
            request_id = f"fiscal-discovery-request:{evidence.request.digest}"
            request_record = reader.get(request_id)
            if (
                request_record.content_hash != evidence.request.digest
                or request_record.media_type != "application/json"
                or request_record.dependency_hashes
                or reader.read(request_id) != canonical_bytes(evidence.request)
            ):
                raise SnapshotError(
                    "FISCAL_DISCOVERY_INVALID", "current discovery request differs"
                )
            adapter = RetainedSecSourceAdapter(
                self._provider,
                scope=SecFiscalSubmissionsCaptureScopeV1(
                    cik=evidence.request.cik,
                    valuation_timestamp=evidence.request.valuation_timestamp,
                ),
                receipts=self._artifacts,
                content=content,
                capture_lock=self._capture_lock,
                check_deadline=check,
                replay_reader=reader,
            )
            for source in evidence.sources:
                uri = self._uri(source.filename)
                if source.receipt is None:
                    if not evidence.is_retry_attempt:
                        identity = sec_response_artifact_id(adapter.scope, uri)
                        missing = reader.current(identity)
                        reader.expect(identity, missing)
                        if missing is not None:
                            raise SnapshotError(
                                "FISCAL_DISCOVERY_INVALID",
                                "current discovery omitted a retained receipt",
                            )
                    continue
                retained = adapter.read_retained_response_with_record(uri)
                if retained is None or retained[0] != source.receipt:
                    raise SnapshotError(
                        "FISCAL_DISCOVERY_INVALID",
                        "current discovery source receipt differs",
                    )
                reader.expect(retained[1].artifact_id, retained[1])
            reader._complete_source_graph("fiscal-discovery")
            reader._enroll_content_readset(content.readset)
            reader.check_bodies()
            content.check_current()
            check()
            return _VerifiedDiscovery(
                evidence,
                reader.records,
                None,
                (reader.input_footprint, content.input_footprint),
                reader.readset,
                (content.readset,),
            )

    def read_current_with_metadata(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> tuple[
        FiscalDiscoveryEvidenceV1, tuple[tuple[str, ArtifactRecordV1 | None], ...]
    ]:
        current = self.read_current_inputs(artifact_id, deadline_at=deadline_at)
        return current.evidence, current.records

    def read_current(
        self, artifact_id: str, *, deadline_at: datetime
    ) -> FiscalDiscoveryEvidenceV1:
        return self.read_current_inputs(artifact_id, deadline_at=deadline_at).evidence

    def read_for_validation(
        self, artifact_id: str, accession_number: str, *, deadline_at: datetime
    ) -> tuple[
        FiscalDiscoveryRequestV1,
        FiscalFilingV1,
        tuple[tuple[str, ArtifactRecordV1 | None], ...],
    ]:
        verified = self._read_validation_inputs(
            artifact_id, accession_number, deadline_at=deadline_at
        )
        assert verified.target is not None
        return verified.evidence.request, verified.target.selected[0], verified.records

    def _read_validation_inputs(
        self, artifact_id: str, accession_number: str, *, deadline_at: datetime
    ) -> _VerifiedDiscovery:
        with self._operation(deadline_at):
            check_deadline = partial(self._before_deadline, deadline_at)
            record = self._current_record(artifact_id, check_deadline)
            if record is None:
                raise SnapshotError(
                    "ARTIFACT_NOT_FOUND", "fiscal discovery is unavailable"
                )
            verified = self._read(
                artifact_id, record, check_deadline, target_accession=accession_number
            )
        if (
            verified.evidence.is_retry_attempt
            or verified.target is None
            or not verified.target.selected
        ):
            raise SnapshotError(
                "FISCAL_CANDIDATE_INELIGIBLE",
                "retained fiscal discovery could not select this accession",
            )
        return verified

    def _read(
        self,
        artifact_id: str,
        record: ArtifactRecordV1,
        check_deadline: Callable[[], datetime],
        *,
        target_accession: str | None = None,
    ) -> _VerifiedDiscovery:
        from .fiscal_source_closure import (
            _FiscalSourceArtifactRead,
            FiscalSourceContentRead,
        )

        reader = _FiscalSourceArtifactRead(self._artifacts, check_deadline, artifact_id)
        content = FiscalSourceContentRead(self._content, check_deadline)
        reader.expect(artifact_id, record)
        try:
            check_deadline()
            raw = reader.read(artifact_id)
            check_deadline()
            evidence = FiscalDiscoveryEvidenceV1.model_validate_json(raw)
            if (
                record.artifact_id != artifact_id
                or record.status != "valid"
                or record.retention != "evidence"
                or record.media_type != "application/json"
                or raw != canonical_bytes(evidence)
                or hashlib.sha256(raw).hexdigest() != record.content_hash
                or record.dependency_hashes != evidence.dependencies
                or evidence.artifact_id != artifact_id
            ):
                raise ValueError("fiscal discovery artifact identity differs")
            reader._discovery_edges(evidence)
            request_id = f"fiscal-discovery-request:{evidence.request.digest}"
            request_record = self._current_record(request_id, check_deadline)
            if (
                request_record is None
                or request_record.artifact_id != request_id
                or request_record.status != "valid"
                or request_record.retention != "evidence"
                or request_record.media_type != "application/json"
                or request_record.content_hash != evidence.request.digest
                or request_record.dependency_hashes
            ):
                raise ValueError("fiscal discovery request evidence changed")
            reader.expect(request_id, request_record)
            request_bytes = reader.read(request_id)
            check_deadline()
            if request_bytes != canonical_bytes(evidence.request):
                raise ValueError("fiscal discovery request bytes changed")
            adapter = RetainedSecSourceAdapter(
                self._provider,
                scope=SecFiscalSubmissionsCaptureScopeV1(
                    cik=evidence.request.cik,
                    valuation_timestamp=evidence.request.valuation_timestamp,
                ),
                receipts=self._artifacts,
                content=content,
                capture_lock=self._capture_lock,
                check_deadline=check_deadline,
                replay_reader=reader,
            )
            records: dict[str, ArtifactRecordV1 | None] = {
                artifact_id: record,
                request_id: request_record,
            }
            pages: list[_CapturedPage] = []
            for source in evidence.sources:
                uri = self._uri(source.filename)
                if source.receipt is None:
                    if not evidence.is_retry_attempt:
                        key = sec_response_artifact_id(adapter.scope, uri)
                        if self._current_record(key, check_deadline) is not None:
                            raise ValueError(
                                "fiscal discovery omitted a retained receipt"
                            )
                        records[key] = None
                        reader.expect(key, None)
                    pages.append(_CapturedPage(source))
                    continue
                retained = adapter.read_retained_response_with_record(uri)
                if retained is None or retained[0] != source.receipt:
                    raise ValueError(
                        "fiscal capture receipt differs from retained source"
                    )
                _, receipt_record, response = retained
                records[receipt_record.artifact_id] = receipt_record
                pages.append(_CapturedPage(source, receipt_record, response.content))
            check_deadline()
            if evidence.selection != self._assess(evidence.request, tuple(pages)):
                raise ValueError(
                    "fiscal source selection differs from retained submissions"
                )
            target = (
                self._assess(
                    evidence.request, tuple(pages), target_accession=target_accession
                )
                if target_accession is not None
                else None
            )
            self._assert_current(records, check_deadline)
        except SecSourceError:
            raise
        except (ValueError, SnapshotError) as error:
            raise SnapshotError(
                "FISCAL_DISCOVERY_INVALID",
                "retained fiscal discovery failed verification",
            ) from error
        reader._complete_source_graph("fiscal-discovery")
        reader._enroll_content_readset(content.readset)
        return _VerifiedDiscovery(
            evidence,
            tuple(records.items()),
            target,
            (reader.input_footprint, content.input_footprint),
            reader.readset,
            (content.readset,),
        )

    def _completed(
        self,
        request: FiscalDiscoveryRequestV1,
        check_deadline: Callable[[], datetime],
    ) -> tuple[FiscalDiscoveryEvidenceV1, ArtifactPublicationV1] | None:
        artifact_id = f"fiscal-discovery:{request.digest}"
        record = self._current_record(artifact_id, check_deadline)
        if record is None:
            return None
        previous = self._read(artifact_id, record, check_deadline).evidence
        if previous.request != request:
            raise SnapshotError("FISCAL_DISCOVERY_INVALID", "request digest collision")
        check_deadline()
        return previous, ArtifactPublicationV1(artifact=record, wrote=False)

    def execute(
        self,
        request: FiscalDiscoveryRequestV1,
        *,
        deadline_at: datetime,
    ) -> tuple[FiscalDiscoveryEvidenceV1, ArtifactPublicationV1]:
        with self._operation(deadline_at):
            return self._execute(request, deadline_at)

    def _execute(
        self, request: FiscalDiscoveryRequestV1, deadline_at: datetime
    ) -> tuple[FiscalDiscoveryEvidenceV1, ArtifactPublicationV1]:
        check_deadline = partial(self._before_deadline, deadline_at)
        check_deadline()
        request = FiscalDiscoveryRequestV1.model_validate_json(canonical_bytes(request))
        if completed := self._completed(request, check_deadline):
            return completed
        with self._capture_lock(sha256_digest(("fiscal-discovery", request.digest))):
            check_deadline()
            result = self._completed(request, check_deadline) or self._publish(
                request, deadline_at, check_deadline
            )
        check_deadline()
        return result

    def _publish(
        self,
        request: FiscalDiscoveryRequestV1,
        deadline_at: datetime,
        check_deadline: Callable[[], datetime],
    ) -> tuple[FiscalDiscoveryEvidenceV1, ArtifactPublicationV1]:
        if request.valuation_timestamp > check_deadline():
            raise SecSourceError(
                "FISCAL_CUTOFF_IN_FUTURE",
                "fiscal discovery cannot use a future valuation cutoff",
            )
        adapter = self._adapter(request, check_deadline)
        recent = self._capture(
            adapter, f"CIK{request.cik}.json", deadline_at=deadline_at
        )
        pages = (
            recent,
            *(
                self._capture(adapter, name, deadline_at=deadline_at)
                for name in self._history_names(request, recent.payload)
            ),
        )
        check_deadline()
        evidence = FiscalDiscoveryEvidenceV1(
            request=request,
            sources=tuple(page.source for page in pages),
            selection=self._assess(request, pages),
        )
        records: dict[str, ArtifactRecordV1 | None] = {}
        for page in pages:
            if page.record is not None:
                records[page.record.artifact_id] = page.record
            elif not evidence.is_retry_attempt:
                key = sec_response_artifact_id(
                    adapter.scope, self._uri(page.source.filename)
                )
                records[key] = None
        self._assert_current(records, check_deadline)
        request_id = f"fiscal-discovery-request:{request.digest}"
        records[request_id] = self._artifacts.put_with_receipt(
            request_id, request
        ).artifact
        check_deadline()
        publication = self._artifacts.put_with_receipt(
            evidence.artifact_id, evidence, evidence.dependencies
        )
        records[evidence.artifact_id] = publication.artifact
        self._assert_current(records, check_deadline)
        return evidence, publication
