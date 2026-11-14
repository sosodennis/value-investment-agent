"""Original issuer evidence for operating research, without security authority."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, field_serializer, model_validator

from .arelle_parser import ArelleParseReportV1, fact_semantic_digest
from .contracts import CanonicalFactV1, SourceRole, SourceSnapshotV1, StrictModel
from .serialization import sha256_digest

ORIGINAL_ISSUER_POLICY: Literal["original-issuer-operating-v1"] = (
    "original-issuer-operating-v1"
)
_DEI_NAMESPACE = re.compile(r"http://xbrl\.(?:sec\.gov|us)/dei/\d{4}(?:-\d{2}-\d{2})?")
_GAAP_NAMESPACE = re.compile(
    r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?"
)
_REQUIRED_DEI = (
    "dei:DocumentPeriodEndDate",
    "dei:DocumentType",
    "dei:EntityCentralIndexKey",
    "dei:EntityRegistrantName",
    "dei:AmendmentFlag",
)


class OriginalIssuerIdentityV1(StrictModel):
    scope: Literal["issuer_operating_only"] = "issuer_operating_only"
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    issuer_name: str = Field(min_length=1)
    reporting_basis: Literal["us-gaap"] = "us-gaap"
    currency: Literal["USD"] = "USD"


class OriginalOperatingSourceV1(StrictModel):
    """Retained source metadata; absent HTTP receipts stay absent."""

    cik: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    form: str = Field(min_length=1)
    is_amendment: bool = False
    available_at: datetime
    captured_at: datetime
    http_status: int | None = Field(default=None, ge=100, le=599)

    @property
    def role(self) -> SourceRole:
        return SourceRole.FILING

    @property
    def filed_at(self) -> datetime:
        return self.available_at

    @property
    def filing_version(self) -> str:
        return "original"

    @property
    def amends_accession(self) -> None:
        return None

    @property
    def supersedes_accession(self) -> None:
        return None

    @property
    def amendment_scope(self) -> None:
        return None

    @property
    def terms_reference(self) -> None:
        return None

    @model_validator(mode="after")
    def timestamps_are_aware(self) -> OriginalOperatingSourceV1:
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (self.available_at, self.captured_at)
        ):
            raise ValueError("original source timestamps must include a timezone")
        return self


def _issuer_result(
    source: OriginalOperatingSourceV1,
    decision_at: datetime,
    report: ArelleParseReportV1,
) -> tuple[OriginalIssuerIdentityV1 | None, date | None, tuple[str, ...]]:
    def refused(code: str) -> tuple[None, None, tuple[str, ...]]:
        return None, None, (code,)

    root = (
        f"https://www.sec.gov/Archives/edgar/data/{int(source.cik)}/"
        f"{source.accession_number.replace('-', '')}/"
    )
    document = source.uri.removeprefix(root)
    if (
        not source.uri.startswith(root)
        or not document
        or re.fullmatch(r"[A-Za-z0-9_.-]+", document) is None
        or source.form != "10-K"
        or source.is_amendment
        or source.available_at > decision_at
        or source.available_at > source.captured_at
        or (source.http_status is not None and source.http_status != 200)
        or report.source_content_hash != source.parser_input_hash
        or not report.offline
        or report.network_attempt_count
        or report.validation_profile.digest() != report.validation_profile_digest
    ):
        return refused("ORIGINAL_ISSUER_SOURCE_INVALID")
    values: dict[str, str] = {}
    shapes: set[tuple[date, date]] = set()
    for concept in _REQUIRED_DEI:
        facts = tuple(fact for fact in report.facts if fact.concept == concept)
        if not facts:
            return refused("ORIGINAL_ISSUER_DEI_MISSING")
        for fact in facts:
            if (
                not _DEI_NAMESPACE.fullmatch(fact.namespace_uri or "")
                or fact.entity_scheme != "http://www.sec.gov/CIK"
                or not re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "")
                or int(fact.entity_identifier or "0") != int(source.cik)
                or fact.dimensions
                or fact.consolidation_scope != "consolidated"
                or fact.is_numeric
                or fact.unit is not None
                or fact.instant is not None
                or fact.period_start is None
                or fact.period_end is None
                or not 300 <= (fact.period_end - fact.period_start).days <= 380
            ):
                return refused("ORIGINAL_ISSUER_DEI_SCOPE_INVALID")
            shapes.add((fact.period_start, fact.period_end))
        unique = {" ".join(fact.value.split()) for fact in facts}
        if len(unique) != 1 or not next(iter(unique)):
            return refused("ORIGINAL_ISSUER_DEI_CONFLICT")
        values[concept] = next(iter(unique))
    try:
        report_end = date.fromisoformat(values["dei:DocumentPeriodEndDate"])
    except ValueError:
        return refused("ORIGINAL_ISSUER_PERIOD_INVALID")
    if (
        len(shapes) != 1
        or next(iter(shapes))[1] != report_end
        or report_end > source.available_at.date()
        or values["dei:DocumentType"] != "10-K"
        or values["dei:AmendmentFlag"].lower() not in {"false", "0"}
        or not re.fullmatch(r"[0-9]{1,10}", values["dei:EntityCentralIndexKey"])
        or int(values["dei:EntityCentralIndexKey"]) != int(source.cik)
    ):
        return refused("ORIGINAL_ISSUER_PERIOD_OR_CIK_INVALID")
    monetary = tuple(
        fact
        for fact in report.facts
        if _GAAP_NAMESPACE.fullmatch(fact.namespace_uri or "")
        and fact.concept.startswith("us-gaap:")
        and fact.is_numeric
        and fact.unit is not None
        and re.fullmatch(r"iso4217:[A-Z]{3}", fact.unit)
        and not fact.dimensions
        and fact.consolidation_scope == "consolidated"
        and (fact.period_end == report_end or fact.instant == report_end)
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "")
        and int(fact.entity_identifier or "0") == int(source.cik)
    )
    if {fact.unit for fact in monetary} != {"iso4217:USD"}:
        return refused("ORIGINAL_ISSUER_CURRENCY_UNSUPPORTED")

    # Currency needs an observed amount, not complete financial statements.
    # Empty/unusable observations remain in the report and never become zero.
    def finite(value: str) -> bool:
        try:
            return Decimal(value).is_finite()
        except InvalidOperation:
            return False

    if not any(finite(fact.value) for fact in monetary):
        return refused("ORIGINAL_ISSUER_MONETARY_VALUE_INVALID")
    return (
        OriginalIssuerIdentityV1(
            issuer_id=source.cik, issuer_name=values["dei:EntityRegistrantName"]
        ),
        report_end,
        (),
    )


class OriginalIssuerEvidenceV1(StrictModel):
    """A replayable issuer claim, including original observations and refusals."""

    contract_version: Literal["fundamental.original-issuer-evidence.v1"] = (
        "fundamental.original-issuer-evidence.v1"
    )
    policy_version: Literal["original-issuer-operating-v1"] = ORIGINAL_ISSUER_POLICY
    source: OriginalOperatingSourceV1
    decision_at: datetime
    report: ArelleParseReportV1
    identity: OriginalIssuerIdentityV1 | None
    report_period_end: date | None
    status: Literal["matched", "refused"]
    issue_codes: tuple[str, ...]
    unestablished_claims: tuple[str, ...] = (
        "security_identity",
        "domicile",
        "regulatory_approval",
        "mapping_review",
        "data_release_authority",
    )
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_serializer("report")
    def serialize_report(self, report: ArelleParseReportV1) -> dict[str, JsonValue]:
        return report.model_dump(mode="json")

    @model_validator(mode="after")
    def original_evidence_matches(self) -> OriginalIssuerEvidenceV1:
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("original decision time must include a timezone")
        if (
            self.report.filing_path != self.source.uri
            or self.report.parsed_at != self.source.captured_at
            or self.report.facts != tuple(sorted(self.report.facts, key=sha256_digest))
            or self.report.findings
            != tuple(sorted(self.report.findings, key=sha256_digest))
            or self.report.finding_codes != tuple(sorted(self.report.finding_codes))
            or any(
                value is not None and value != Path(value.name)
                for value in (
                    self.report.validation_profile.edgar_plugin_dir,
                    self.report.validation_profile.xule_plugin_dir,
                    self.report.validation_profile.dqc_ruleset_path,
                    self.report.validation_profile.historical_dqc_dir,
                )
            )
        ):
            raise ValueError("original issuer report must be canonically retained")
        identity, period_end, codes = _issuer_result(
            self.source, self.decision_at, self.report
        )
        if (
            self.identity != identity
            or self.report_period_end != period_end
            or self.issue_codes != codes
            or self.status != ("refused" if codes else "matched")
            or self.unestablished_claims
            != (
                "security_identity",
                "domicile",
                "regulatory_approval",
                "mapping_review",
                "data_release_authority",
            )
        ):
            raise ValueError("issuer claim differs from its exact original evidence")
        if self.input_digest != _issuer_input_digest(
            self.source, self.decision_at, self.report
        ) or self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("issuer evidence digest mismatch")
        return self


def parser_input_matches_registered_original(
    original: OriginalIssuerEvidenceV1, expected_parser_input_hash: str
) -> bool:
    """Match the reviewed filing representation after the integrity boundary.

    The automatic-mapping request separately verifies exact raw bytes against
    SEC integrity evidence before using a registered classification. This
    identity check deliberately uses the retained parser input, so SEC response
    normalization authorized by that policy does not change filing identity.
    """
    return (
        original.status == "matched"
        and original.source.parser_input_hash == expected_parser_input_hash
        and original.report.source_content_hash == expected_parser_input_hash
    )


def _issuer_input_digest(
    source: OriginalOperatingSourceV1,
    decision_at: datetime,
    report: ArelleParseReportV1,
) -> str:
    return sha256_digest(
        {
            "policy_version": ORIGINAL_ISSUER_POLICY,
            "source": source,
            "decision_at": decision_at,
            "parser_replay_digest": report.replay_digest(),
            "parser_fact_digest": fact_semantic_digest(report),
            "report": report.model_dump(mode="json"),
        }
    )


def evaluate_original_issuer(
    report: ArelleParseReportV1,
    *,
    source: OriginalOperatingSourceV1,
    decision_at: datetime,
) -> OriginalIssuerEvidenceV1:
    """Validate issuer scope without approving regulatory or financial evidence."""
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("original decision time must include a timezone")
    profile = report.validation_profile
    profile = profile.model_copy(
        update={
            name: Path(value.name)
            for name in (
                "edgar_plugin_dir",
                "xule_plugin_dir",
                "dqc_ruleset_path",
                "historical_dqc_dir",
            )
            if (value := getattr(profile, name)) is not None
        }
    )
    report = report.model_copy(
        update={
            "filing_path": source.uri,
            "parsed_at": source.captured_at,
            "facts": tuple(sorted(report.facts, key=sha256_digest)),
            "findings": tuple(sorted(report.findings, key=sha256_digest)),
            "finding_codes": tuple(sorted(report.finding_codes)),
            "validation_profile": profile,
        }
    )
    identity, period_end, codes = _issuer_result(source, decision_at, report)
    payload = {
        "source": source,
        "decision_at": decision_at,
        "report": report.model_dump(mode="json"),
        "identity": identity,
        "report_period_end": period_end,
        "status": "refused" if codes else "matched",
        "issue_codes": codes,
        "input_digest": _issuer_input_digest(source, decision_at, report),
    }
    # Include strict contract defaults before calculating the complete digest.
    payload.update(
        {
            "contract_version": "fundamental.original-issuer-evidence.v1",
            "policy_version": ORIGINAL_ISSUER_POLICY,
            "unestablished_claims": (
                "security_identity",
                "domicile",
                "regulatory_approval",
                "mapping_review",
                "data_release_authority",
            ),
        }
    )
    payload["output_digest"] = sha256_digest(payload)
    return OriginalIssuerEvidenceV1.model_validate(payload)


class IssuerOperatingSourceV1(StrictModel):
    """An internal issuer source view; it grants no release or security claim."""

    contract_version: Literal["fundamental.issuer-operating-source.v1"] = (
        "fundamental.issuer-operating-source.v1"
    )
    identity: OriginalIssuerIdentityV1
    valuation_timestamp: datetime
    originals: tuple[OriginalIssuerEvidenceV1, ...] = Field(min_length=1, max_length=6)
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def snapshot_id(self) -> str:
        return f"issuer-operating-{self.manifest_digest}"

    @property
    def source_records(self) -> tuple[OriginalOperatingSourceV1, ...]:
        return tuple(original.source for original in self.originals)

    @model_validator(mode="after")
    def sources_match_issuer(self) -> IssuerOperatingSourceV1:
        if (
            self.valuation_timestamp.tzinfo is None
            or self.valuation_timestamp.utcoffset() is None
        ):
            raise ValueError("issuer operating time must include a timezone")
        accessions = tuple(item.source.accession_number for item in self.originals)
        if accessions != tuple(sorted(set(accessions))):
            raise ValueError("issuer originals must be distinct and ordered")
        if len({item.source.content_hash for item in self.originals}) != len(
            self.originals
        ):
            raise ValueError("issuer originals must have distinct source hashes")
        if any(
            item.status != "matched"
            or item.identity != self.identity
            or item.source.available_at > self.valuation_timestamp
            or item.decision_at > self.valuation_timestamp
            for item in self.originals
        ):
            raise ValueError("issuer source view requires matching available originals")
        if self.manifest_digest != sha256_digest(
            self.model_dump(exclude={"manifest_digest"})
        ):
            raise ValueError("issuer source manifest digest mismatch")
        return self


def compose_issuer_operating_source(
    originals: tuple[OriginalIssuerEvidenceV1, ...], *, valuation_timestamp: datetime
) -> IssuerOperatingSourceV1:
    if not originals or originals[0].identity is None:
        raise ValueError("issuer source view requires matched originals")
    payload = {
        "contract_version": "fundamental.issuer-operating-source.v1",
        "identity": originals[0].identity,
        "valuation_timestamp": valuation_timestamp,
        "originals": tuple(
            sorted(originals, key=lambda item: item.source.accession_number)
        ),
    }
    payload["manifest_digest"] = sha256_digest(payload)
    return IssuerOperatingSourceV1.model_validate(payload)


def fact_matches_operating_identity(
    fact: CanonicalFactV1, snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1
) -> bool:
    if fact.issuer_id != snapshot.identity.issuer_id:
        return False
    if isinstance(snapshot, IssuerOperatingSourceV1):
        return fact.security_id is None and fact.security_scope in {
            None,
            "issuer",
            "consolidated",
            "unspecified",
        }
    return fact.security_id in {None, snapshot.identity.security_id}


def fact_matches_original_source(
    fact: CanonicalFactV1, snapshot: IssuerOperatingSourceV1
) -> bool:
    return any(
        fact.source.content_hash == source.content_hash
        and fact.accession_number == source.accession_number
        and fact.source.accession_number == source.accession_number
        and fact.source.source_url == source.uri
        and fact.source.source_role is SourceRole.FILING
        and fact.source.available_at == source.available_at
        and fact.available_at == source.available_at
        and not fact.is_amendment
        for source in snapshot.source_records
    )
