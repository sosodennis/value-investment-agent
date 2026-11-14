"""Freeze original annual filing selection before automatic source preparation."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, timedelta
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from .contracts import StrictModel
from .sec_submissions import SecRecentFilingsV1, SecSubmissionsV1
from .serialization import canonical_bytes, sha256_digest


class AnnualDiscoveryParametersV1(StrictModel):
    protocol: Literal["sec-original-annual-discovery-v1"] = (
        "sec-original-annual-discovery-v1"
    )
    cik: str = Field(pattern=r"^[0-9]{10}$")
    valuation_timestamp: AwareDatetime
    declared_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    original_count: int = Field(default=2, ge=1, le=6)
    lookback_days: int = Field(default=3650, ge=1, le=3650)
    maximum_history_files: int = Field(default=16, ge=1, le=32)


class AnnualDiscoveryRequestV1(AnnualDiscoveryParametersV1):
    supported_filing_years: tuple[int, ...] = Field(min_length=1)
    supported_filing_forms: tuple[Literal["10-K"], ...] = ("10-K",)

    @field_validator("supported_filing_years")
    @classmethod
    def canonical_years(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(year < 1900 or year > 2200 for year in value):
            raise ValueError("unsupported filing year")
        return tuple(sorted(set(value)))

    @field_validator("supported_filing_forms")
    @classmethod
    def original_form_only(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != ("10-K",):
            raise ValueError("annual discovery supports original 10-K only")
        return value

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class AnnualFilingV1(StrictModel):
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    form: Literal["10-K"] = "10-K"
    filing_date: date
    accepted_at: AwareDatetime
    report_period_end: date
    primary_document: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=255)
    is_xbrl: bool
    is_inline_xbrl: bool | None


class AnnualFilingDispositionV1(StrictModel):
    accession_number: str
    record_digest: str
    source_digests: tuple[str, ...]
    filing: AnnualFilingV1 | None
    issue_codes: tuple[str, ...]


class AnnualSelectionV1(StrictModel):
    selected: tuple[AnnualFilingV1, ...]
    dispositions: tuple[AnnualFilingDispositionV1, ...]
    issue_codes: tuple[str, ...]


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate SEC JSON key")
        result[key] = value
    return result


def decode_submissions(payload: bytes, cik: str) -> SecSubmissionsV1:
    source = SecSubmissionsV1.model_validate(
        json.loads(payload, object_pairs_hook=_unique_pairs)
    )
    if str(source.cik).zfill(10) != cik:
        raise ValueError("submissions CIK differs from the requested issuer")
    source.filings.recent.require_aligned_columns()
    return source


def required_history_files(
    source: SecSubmissionsV1, request: AnnualDiscoveryRequestV1
) -> tuple[str, ...]:
    cutoff = request.valuation_timestamp.date() - timedelta(days=request.lookback_days)
    names: set[str] = set()
    references = source.filings.files or ()
    if len({ref.name for ref in references}) != len(references):
        raise ValueError("duplicate SEC submission history reference")
    for ref in references:
        if (
            not ref.name.startswith(f"CIK{request.cik}-")
            or ref.filingFrom > ref.filingTo
        ):
            raise ValueError("invalid issuer or date range in SEC history reference")
        if (
            ref.filingTo >= cutoff
            and ref.filingFrom <= request.valuation_timestamp.date()
        ):
            names.add(ref.name)
    if len(names) > request.maximum_history_files:
        raise ValueError("SEC history exceeds the explicit discovery bound")
    return tuple(sorted(names))


def decode_history(payload: bytes) -> SecRecentFilingsV1:
    rows = SecRecentFilingsV1.model_validate(
        json.loads(payload, object_pairs_hook=_unique_pairs)
    )
    rows.require_aligned_columns()
    return rows


def _flag(value: object) -> bool:
    text = str(value).lower()
    if text not in {"0", "1", "false", "true"}:
        raise ValueError("invalid SEC XBRL flag")
    return text in {"1", "true"}


def select_original_annuals(
    request: AnnualDiscoveryRequestV1,
    sources: Iterable[tuple[str, SecRecentFilingsV1]],
) -> AnnualSelectionV1:
    """Retain every row; never replace an incompatible latest original with an older one."""
    records: dict[tuple[str, str], tuple[dict, set[str]]] = {}
    for source_digest, rows in sources:
        rows.require_aligned_columns()
        for index, accession in enumerate(rows.accessionNumber):
            record = {
                key: values[index]
                for key in (
                    "accessionNumber",
                    "filingDate",
                    "acceptanceDateTime",
                    "form",
                    "primaryDocument",
                    "isXBRL",
                    "isInlineXBRL",
                    "reportDate",
                )
                if (values := getattr(rows, key)) is not None
            }
            key = (accession, sha256_digest(record))
            records.setdefault(key, (record, set()))[1].add(source_digest)
    counts = Counter(accession for accession, _ in records)
    conflicts = {accession for accession, count in counts.items() if count > 1}
    issues: set[str] = set()
    dispositions = []
    candidates = []
    cutoff = request.valuation_timestamp.date() - timedelta(days=request.lookback_days)
    for (accession, digest), (record, source_digests) in sorted(records.items()):
        codes: set[str] = set()
        filing = None
        if record["form"] != "10-K":
            codes.add("ANNUAL_FORM_EXCLUDED")
        else:
            try:
                filing = AnnualFilingV1.model_validate_json(
                    canonical_bytes(
                        {
                            "accession_number": accession,
                            "accepted_at": record["acceptanceDateTime"],
                            "filing_date": record["filingDate"],
                            "report_period_end": record.get("reportDate", ""),
                            "primary_document": record["primaryDocument"],
                            "is_xbrl": _flag(record["isXBRL"]),
                            "is_inline_xbrl": _flag(record["isInlineXBRL"])
                            if "isInlineXBRL" in record
                            else None,
                        }
                    )
                )
                if filing.report_period_end > filing.filing_date:
                    raise ValueError("report period follows the filing date")
                if filing.report_period_end > filing.accepted_at.astimezone(UTC).date():
                    raise ValueError("report period follows the acceptance date")
                # SEC 17 CFR 232.13(a)(2): after-hours submissions may have
                # an official filing date on the next business day.
                if (
                    filing.accepted_at > request.valuation_timestamp
                    or filing.filing_date > request.valuation_timestamp.date()
                ):
                    codes.add("ANNUAL_AFTER_VALUATION")
                elif filing.filing_date < cutoff:
                    codes.add("ANNUAL_OUTSIDE_LOOKBACK")
                elif accession in conflicts:
                    codes.add("ANNUAL_ACCESSION_CONFLICT")
                    issues.update(codes)
                else:
                    candidates.append(filing)
            except ValueError:
                filing = None
                codes.add("ANNUAL_METADATA_INVALID")
                issues.update(codes)
        dispositions.append(
            AnnualFilingDispositionV1(
                accession_number=accession,
                record_digest=digest,
                source_digests=tuple(sorted(source_digests)),
                filing=filing,
                issue_codes=tuple(sorted(codes)),
            )
        )
    candidates.sort(
        key=lambda item: (item.accepted_at, item.accession_number), reverse=True
    )
    selected = candidates[: request.original_count]
    if len(selected) < request.original_count:
        issues.add("ANNUAL_SOURCE_COUNT_INSUFFICIENT")
    if len({item.report_period_end for item in selected}) != len(selected):
        issues.add("ANNUAL_REPORT_PERIOD_CONFLICT")
    if any(
        item.filing_date.year not in request.supported_filing_years for item in selected
    ):
        issues.add("FILING_RUNTIME_INCOMPATIBLE")
    if any(not item.is_xbrl for item in selected):
        issues.add("ANNUAL_XBRL_UNAVAILABLE")
    return AnnualSelectionV1(
        selected=tuple(sorted(selected, key=lambda item: item.accession_number))
        if not issues
        else (),
        dispositions=tuple(dispositions),
        issue_codes=tuple(sorted(issues)),
    )
