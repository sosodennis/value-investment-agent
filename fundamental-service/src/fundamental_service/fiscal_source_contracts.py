from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .arelle_parser import ArelleParseReportV1, fact_semantic_digest
from .contracts import StrictModel
from .original_issuer import (
    ORIGINAL_ISSUER_POLICY,
    OriginalIssuerIdentityV1,
    OriginalOperatingSourceV1,
    canonical_original_report,
)
from .regulatory_validation import require_sec_validation_evidence
from .serialization import sha256_digest
from .snapshots import SnapshotError

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
    "dei:DocumentFiscalYearFocus",
    "dei:DocumentFiscalPeriodFocus",
)


class FiscalFilingV1(StrictModel):
    cik: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    form: Literal["10-Q", "10-K"]
    filing_date: date
    accepted_at: AwareDatetime
    report_period_end: date
    primary_document: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=255)
    is_xbrl: bool
    is_inline_xbrl: bool | None
    is_amendment: bool = False
    amends_accession: str | None = Field(
        default=None, pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$"
    )
    amendment_scope: Literal["valuation_relevant", "unrelated", "unknown"] | None = None

    @model_validator(mode="after")
    def filing_lineage_is_explicit(self) -> FiscalFilingV1:
        if self.primary_document in {".", ".."}:
            raise ValueError("fiscal primary document must be a file")
        if (
            self.report_period_end > self.filing_date
            or self.report_period_end > self.accepted_at.date()
        ):
            raise ValueError("fiscal report period must not follow filing date")
        if self.is_amendment != (self.amends_accession is not None):
            raise ValueError("fiscal amendment requires an explicit predecessor")
        if self.is_amendment and self.amendment_scope is None:
            raise ValueError("fiscal amendment requires an explicit scope")
        if not self.is_amendment and self.amendment_scope is not None:
            raise ValueError("original fiscal filing cannot carry amendment scope")
        return self


class FiscalOriginalSourceV1(StrictModel):
    cik: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    uri: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    form: Literal["10-Q", "10-K"]
    is_amendment: bool = False
    amends_accession: str | None = Field(
        default=None, pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$"
    )
    amendment_scope: Literal["valuation_relevant", "unrelated", "unknown"] | None = None
    available_at: AwareDatetime
    captured_at: AwareDatetime
    http_status: int | None = Field(default=None, ge=100, le=599)

    @model_validator(mode="after")
    def source_lineage_matches(self) -> FiscalOriginalSourceV1:
        if self.is_amendment != (self.amends_accession is not None):
            raise ValueError("fiscal amendment source requires predecessor lineage")
        if self.is_amendment != (self.amendment_scope is not None):
            raise ValueError("fiscal amendment source requires scope")
        return self

    def original_operating_source(self) -> OriginalOperatingSourceV1:
        return OriginalOperatingSourceV1(
            cik=self.cik,
            accession_number=self.accession_number,
            uri=self.uri,
            content_hash=self.content_hash,
            parser_input_hash=self.parser_input_hash,
            form=self.form,
            is_amendment=self.is_amendment,
            available_at=self.available_at,
            captured_at=self.captured_at,
            http_status=self.http_status,
        )


class FiscalClaimAssessmentV1(StrictModel):
    """DEI and source metadata assessment, without admission or valuation authority."""

    report: ArelleParseReportV1
    identity: OriginalIssuerIdentityV1 | None
    metadata_status: Literal["matched", "refused"]
    metadata_issue_codes: tuple[str, ...]
    report_period_end: date | None
    fiscal_year_focus: int | None
    fiscal_period_focus: Literal["Q1", "Q2", "Q3", "FY"] | None
    status: Literal["matched", "refused"]
    issue_codes: tuple[str, ...]
    input_digest: str


class FiscalIssuerClaimV1(StrictModel):
    """Replayable fiscal source metadata claim, separate from annual evidence."""

    protocol: Literal["fundamental.fiscal-issuer-claim.v1"] = (
        "fundamental.fiscal-issuer-claim.v1"
    )
    policy_version: Literal["fiscal-issuer-dei-v1"] = "fiscal-issuer-dei-v1"
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    filing: FiscalFilingV1
    source: FiscalOriginalSourceV1
    decision_at: AwareDatetime
    report: ArelleParseReportV1
    identity: OriginalIssuerIdentityV1 | None
    metadata_status: Literal["matched", "refused"]
    metadata_issue_codes: tuple[str, ...]
    report_period_end: date | None
    fiscal_year_focus: int | None
    fiscal_period_focus: Literal["Q1", "Q2", "Q3", "FY"] | None
    status: Literal["matched", "refused"]
    issue_codes: tuple[str, ...]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def claim_matches_exact_report(self) -> FiscalIssuerClaimV1:
        expected = evaluate_fiscal_claim(
            self.report,
            filing=self.filing,
            source=self.source,
            decision_at=self.decision_at,
            request_digest=self.request_digest,
        )
        for name in (
            "report",
            "identity",
            "metadata_status",
            "metadata_issue_codes",
            "report_period_end",
            "fiscal_year_focus",
            "fiscal_period_focus",
            "status",
            "issue_codes",
            "input_digest",
        ):
            if getattr(self, name) != getattr(expected, name):
                raise ValueError(
                    "fiscal issuer claim differs from its retained evidence"
                )
        if self.output_digest != sha256_digest(
            self.model_dump(mode="json", exclude={"output_digest"})
        ):
            raise ValueError("fiscal issuer claim digest mismatch")
        return self


def evaluate_fiscal_issuer(
    report: ArelleParseReportV1,
    *,
    filing: FiscalFilingV1,
    source: FiscalOriginalSourceV1,
    decision_at: AwareDatetime,
    request_digest: str,
) -> FiscalIssuerClaimV1:
    """Bind DEI and strict parser evidence to one selected fiscal original.

    This boundary reports typed source identity and parser evidence only. It
    does not admit a source, authorize mapping or release, or calculate value.
    """
    expected = evaluate_fiscal_claim(
        report,
        filing=filing,
        source=source,
        decision_at=decision_at,
        request_digest=request_digest,
    )
    payload = {
        "protocol": "fundamental.fiscal-issuer-claim.v1",
        "policy_version": "fiscal-issuer-dei-v1",
        "request_digest": request_digest,
        "filing": filing,
        "source": source,
        "decision_at": decision_at,
        "report": expected.report,
        "identity": expected.identity,
        "metadata_status": expected.metadata_status,
        "metadata_issue_codes": expected.metadata_issue_codes,
        "report_period_end": expected.report_period_end,
        "fiscal_year_focus": expected.fiscal_year_focus,
        "fiscal_period_focus": expected.fiscal_period_focus,
        "status": expected.status,
        "issue_codes": expected.issue_codes,
        "input_digest": expected.input_digest,
    }
    draft = FiscalIssuerClaimV1.model_construct(
        _fields_set=None, **payload, output_digest="0" * 64
    )
    payload["output_digest"] = sha256_digest(
        draft.model_dump(mode="json", exclude={"output_digest"})
    )
    return FiscalIssuerClaimV1.model_validate(payload)


def evaluate_fiscal_claim(
    report: ArelleParseReportV1,
    *,
    filing: FiscalFilingV1,
    source: FiscalOriginalSourceV1,
    decision_at: AwareDatetime,
    request_digest: str,
) -> FiscalClaimAssessmentV1:
    if len(request_digest) != 64 or any(
        c not in "0123456789abcdef" for c in request_digest
    ):
        raise ValueError("fiscal validation request digest is invalid")
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("fiscal decision time must include a timezone")

    if report.source_content_hash != source.parser_input_hash:
        raise ValueError("fiscal parser input hash differs from retained source")
    canonical_report = canonical_original_report(
        report,
        source=source.original_operating_source(),
        policy_version=ORIGINAL_ISSUER_POLICY,
    )
    codes: set[str] = set()
    metadata_codes: set[str] = set()

    def add_metadata_issue(code: str) -> None:
        codes.add(code)
        metadata_codes.add(code)

    identity = None
    report_period_end = None
    fiscal_year_focus = None
    fiscal_period_focus: Literal["Q1", "Q2", "Q3", "FY"] | None = None

    root = (
        f"https://www.sec.gov/Archives/edgar/data/{int(source.cik)}/"
        f"{filing.accession_number.replace('-', '')}/"
    )
    document = source.uri.removeprefix(root)
    if (
        source.cik != filing.cik
        or source.accession_number != filing.accession_number
        or source.form != filing.form
        or source.is_amendment != filing.is_amendment
        or source.amends_accession != filing.amends_accession
        or source.amendment_scope != filing.amendment_scope
        or source.available_at != filing.accepted_at
        or source.available_at > decision_at
        or source.available_at > source.captured_at
        or source.http_status != 200
        or not source.uri.startswith(root)
        or document != filing.primary_document
        or canonical_report.taxonomy_cache_hash is None
        or canonical_report.validation_profile.digest()
        != canonical_report.validation_profile_digest
    ):
        add_metadata_issue("FISCAL_ORIGINAL_SOURCE_MISMATCH")
    if not canonical_report.offline:
        codes.add("FISCAL_OFFLINE_REQUIRED")
    if not filing.is_xbrl:
        add_metadata_issue("FISCAL_XBRL_REQUIRED")
    dqc_context = canonical_report.dqc_filing_context
    if (
        dqc_context is None
        or dqc_context.issuer_id != filing.cik
        or dqc_context.accession_number != filing.accession_number
        or dqc_context.filing_date != filing.filing_date
        or dqc_context.dqc_version != canonical_report.validation_profile.dqc_version
    ):
        add_metadata_issue("FISCAL_DQC_CONTEXT_MISMATCH")

    try:
        require_sec_validation_evidence(canonical_report)
    except (SnapshotError, ValueError) as error:
        codes.add(getattr(error, "code", "FISCAL_STRICT_VALIDATION_MISSING"))
    if canonical_report.blocking_finding_codes():
        codes.add("FISCAL_STRICT_VALIDATION_BLOCKED")

    values: dict[str, str] = {}
    shapes: set[tuple[date, date]] = set()
    for concept in _REQUIRED_DEI:
        facts = tuple(
            fact for fact in canonical_report.facts if fact.concept == concept
        )
        if not facts:
            add_metadata_issue("FISCAL_DEI_MISSING")
            continue
        for fact in facts:
            if (
                not _DEI_NAMESPACE.fullmatch(fact.namespace_uri or "")
                or fact.entity_scheme != "http://www.sec.gov/CIK"
                or not re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "")
                or int(fact.entity_identifier or "0") != int(filing.cik)
                or fact.dimensions
                or fact.consolidation_scope != "consolidated"
                or fact.is_numeric
                or fact.unit is not None
                or fact.instant is not None
                or fact.period_start is None
                or fact.period_start > filing.report_period_end
                or fact.period_end != filing.report_period_end
            ):
                add_metadata_issue("FISCAL_DEI_CONTEXT_MISMATCH")
                continue
            shapes.add((fact.period_start, fact.period_end))
        unique = {" ".join(fact.value.split()) for fact in facts}
        if len(unique) != 1 or not next(iter(unique)):
            add_metadata_issue("FISCAL_DEI_CONFLICT")
        else:
            values[concept] = next(iter(unique))

    if len(shapes) != 1 or next(iter(shapes))[1] != filing.report_period_end:
        add_metadata_issue("FISCAL_DEI_PERIOD_CONTEXT_MISMATCH")
    else:
        try:
            report_period_end = date.fromisoformat(
                values.get("dei:DocumentPeriodEndDate", "")
            )
        except ValueError:
            add_metadata_issue("FISCAL_DEI_PERIOD_END_INVALID")
    if report_period_end != filing.report_period_end:
        add_metadata_issue("FISCAL_DEI_PERIOD_END_MISMATCH")
    if values.get("dei:DocumentType") != filing.form:
        add_metadata_issue("FISCAL_DEI_FORM_MISMATCH")
    dei_cik = values.get("dei:EntityCentralIndexKey", "").strip()
    if not re.fullmatch(r"[0-9]{1,10}", dei_cik or "") or int(dei_cik or "0") != int(
        filing.cik
    ):
        add_metadata_issue("FISCAL_DEI_CIK_MISMATCH")
    if values.get("dei:AmendmentFlag", "").lower() not in {"false", "0"}:
        add_metadata_issue("FISCAL_DEI_AMENDMENT_MISMATCH")
    if filing.is_amendment:
        add_metadata_issue("FISCAL_AMENDMENT_LINEAGE_UNVERIFIED")

    try:
        year_focus = int(values.get("dei:DocumentFiscalYearFocus", ""))
    except ValueError:
        year_focus = 0
    if not 1900 <= year_focus <= 2200:
        add_metadata_issue("FISCAL_DEI_YEAR_FOCUS_INVALID")
    else:
        fiscal_year_focus = year_focus
    period_focus = values.get("dei:DocumentFiscalPeriodFocus")
    allowed_focus = {"Q1", "Q2", "Q3"} if filing.form == "10-Q" else {"FY"}
    if period_focus not in allowed_focus:
        add_metadata_issue("FISCAL_DEI_PERIOD_FOCUS_INVALID")
    elif period_focus == "Q1":
        fiscal_period_focus = "Q1"
    elif period_focus == "Q2":
        fiscal_period_focus = "Q2"
    elif period_focus == "Q3":
        fiscal_period_focus = "Q3"
    elif period_focus == "FY":
        fiscal_period_focus = "FY"

    monetary = tuple(
        fact
        for fact in canonical_report.facts
        if _GAAP_NAMESPACE.fullmatch(fact.namespace_uri or "")
        and fact.concept.startswith("us-gaap:")
        and fact.is_numeric
        and fact.unit is not None
        and re.fullmatch(r"iso4217:[A-Z]{3}", fact.unit)
        and not fact.dimensions
        and fact.consolidation_scope == "consolidated"
        and (
            fact.period_end == filing.report_period_end
            or fact.instant == filing.report_period_end
        )
        and fact.entity_scheme == "http://www.sec.gov/CIK"
        and re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "")
        and int(fact.entity_identifier or "0") == int(filing.cik)
    )
    if not monetary:
        add_metadata_issue("FISCAL_US_GAAP_MONETARY_MISSING")
    elif {fact.unit for fact in monetary} != {"iso4217:USD"}:
        add_metadata_issue("FISCAL_US_GAAP_CURRENCY_UNSUPPORTED")
    else:
        try:
            finite = any(Decimal(fact.value).is_finite() for fact in monetary)
        except InvalidOperation:
            finite = False
        if not finite:
            add_metadata_issue("FISCAL_US_GAAP_MONETARY_VALUE_INVALID")

    if not metadata_codes:
        identity = OriginalIssuerIdentityV1(
            issuer_id=filing.cik,
            issuer_name=values["dei:EntityRegistrantName"],
        )
    return FiscalClaimAssessmentV1(
        report=canonical_report,
        identity=identity,
        metadata_status="refused" if metadata_codes else "matched",
        metadata_issue_codes=tuple(sorted(metadata_codes)),
        report_period_end=report_period_end,
        fiscal_year_focus=fiscal_year_focus,
        fiscal_period_focus=fiscal_period_focus,
        status="refused" if codes else "matched",
        issue_codes=tuple(sorted(codes)),
        input_digest=sha256_digest(
            {
                "policy_version": "fiscal-issuer-dei-v1",
                "request_digest": request_digest,
                "filing": filing,
                "source": source,
                "decision_at": decision_at,
                "parser_replay_digest": canonical_report.replay_digest(),
                "parser_fact_digest": fact_semantic_digest(canonical_report),
                "report": canonical_report.model_dump(mode="json"),
            }
        ),
    )
