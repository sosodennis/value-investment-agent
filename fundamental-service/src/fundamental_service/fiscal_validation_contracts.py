from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .arelle_parser import fact_semantic_digest
from .contracts import SecIntegrityEvidenceV1, StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_source_contracts import FiscalFilingV1, FiscalIssuerClaimV1
from .parser_action_contracts import ParserBuildIdentityV1, parser_action_markers
from .parser_computation import execution_validation_evidence
from .regulatory_validation import require_sec_validation_evidence
from .sec_capture import SecCaptureScopeV1, SecResponseReceiptV1
from .serialization import sha256_digest

FISCAL_TAXONOMY_CACHE_SHA256: Final = (
    "af63b0b36d5cad6f2788e90fc323b56955ce581fd84e41330bac4ba765f3a6f0"
)
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Accession = Annotated[str, Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")]
RefusalCodes = Annotated[tuple[str, ...], Field(min_length=1)]


class _FiscalValidationModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class FiscalRetainedContentV1(_FiscalValidationModel):
    digest: Digest
    media_type: str = Field(min_length=1)
    byte_length: int = Field(ge=0)


class FiscalCapturedInputV1(_FiscalValidationModel):
    kind: Literal["captured"] = "captured"
    receipt_ref: ArtifactRefV1
    content: FiscalRetainedContentV1


class FiscalArchiveInputV1(_FiscalValidationModel):
    kind: Literal["archive_member"] = "archive_member"
    archive_receipt_ref: ArtifactRefV1
    member_name: str = Field(min_length=1)
    member_content: FiscalRetainedContentV1


class FiscalNormalizedInputV1(_FiscalValidationModel):
    kind: Literal["normalized"] = "normalized"
    integrity_role: Literal["normalized_content", "parser_input"]
    content: FiscalRetainedContentV1


FiscalRetainedInputOriginV1 = Annotated[
    FiscalCapturedInputV1 | FiscalArchiveInputV1 | FiscalNormalizedInputV1,
    Field(discriminator="kind"),
]


class FiscalStagedInputV1(_FiscalValidationModel):
    relative_name: str = Field(min_length=1)
    origin: FiscalRetainedInputOriginV1


class FiscalParserInputBindingV1(_FiscalValidationModel):
    representation: Literal["normalized", "archive"]
    action_result_ref: ArtifactRefV1
    files: tuple[FiscalStagedInputV1, ...] = Field(min_length=1, max_length=4096)


class FiscalRetainedInputBindingV1(_FiscalValidationModel):
    protocol: Literal["fundamental.fiscal-retained-input-binding.v1"] = (
        "fundamental.fiscal-retained-input-binding.v1"
    )
    source_validation_ref: ArtifactRefV1
    source_contract_digest: Digest
    inputs: tuple[FiscalParserInputBindingV1, ...] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def exact_representations(self) -> FiscalRetainedInputBindingV1:
        representations = tuple(item.representation for item in self.inputs)
        if (
            len(set(representations)) != len(representations)
            or self.source_validation_ref.role != "fiscal-original-validation"
            or any(
                item.action_result_ref.role != "sec-parser-action-result-v2"
                or len({file.relative_name for file in item.files}) != len(item.files)
                for item in self.inputs
            )
        ):
            raise ValueError("retained input binding roles or representations differ")
        return self


class FiscalValidationPinV1(_FiscalValidationModel):
    declared_source_revision: Revision
    taxonomy_manifest_id: str = Field(min_length=1)
    taxonomy_cache_sha256: Literal[
        "af63b0b36d5cad6f2788e90fc323b56955ce581fd84e41330bac4ba765f3a6f0"
    ] = FISCAL_TAXONOMY_CACHE_SHA256


class FiscalValidationRuntimeV1(_FiscalValidationModel):
    pin: FiscalValidationPinV1
    taxonomy_version: str = Field(pattern=r"^us-gaap-[0-9]{4}$")
    dqc_namespace: str = Field(
        pattern=r"^http://fasb\.org/us-gaap/20[0-9]{2}(?:-01-31)?$"
    )
    validation_profile_id: str = Field(min_length=1)
    validation_profile_digest: Digest
    parser_version: Literal["2.47.4"] = "2.47.4"
    delivery_revision: Revision
    parser_build: ParserBuildIdentityV1

    @model_validator(mode="after")
    def check_pins(self) -> FiscalValidationRuntimeV1:
        if (
            self.taxonomy_version
            != f"us-gaap-{self.dqc_namespace.rsplit('/', 1)[1][:4]}"
            or self.delivery_revision != self.pin.declared_source_revision
        ):
            raise ValueError("fiscal parser delivery differs from its runtime pins")
        return self


class FiscalOriginalValidationRequestV1(_FiscalValidationModel):
    protocol: Literal["fundamental.fiscal-original-validation-request.v1"] = (
        "fundamental.fiscal-original-validation-request.v1"
    )
    discovery_ref: ArtifactRefV1
    accession_number: Accession


class ResolvedFiscalValidationRequestV1(_FiscalValidationModel):
    selection: FiscalOriginalValidationRequestV1
    filing: FiscalFilingV1
    valuation_timestamp: AwareDatetime
    pin: FiscalValidationPinV1

    @property
    def scope(self) -> SecCaptureScopeV1:
        return SecCaptureScopeV1(
            cik=self.filing.cik,
            accession_number=self.filing.accession_number,
            valuation_timestamp=self.valuation_timestamp,
            source_profile="fiscal-source-validation-v1",
        )

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        return f"fiscal-original-validation-request:{self.digest}"

    @property
    def completed_artifact_id(self) -> str:
        return f"fiscal-original-validation:{self.digest}"


class FiscalValidationIncompleteV1(_FiscalValidationModel):
    kind: Literal["incomplete_refused"] = "incomplete_refused"
    issue_codes: RefusalCodes
    retryable: bool = Field(default=False, exclude_if=lambda value: not value)


class _FiscalValidationCompleteV1(_FiscalValidationModel):
    runtime: FiscalValidationRuntimeV1
    claim: FiscalIssuerClaimV1
    integrity: SecIntegrityEvidenceV1
    responses: tuple[SecResponseReceiptV1, ...] = Field(min_length=1)
    action_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_complete_evidence(self) -> _FiscalValidationCompleteV1:
        report = self.claim.report
        require_sec_validation_evidence(report)
        markers = parser_action_markers(execution_validation_evidence(report))
        representations = {representation for _, representation, *_ in markers}
        expected_representations = (
            {"normalized", "archive"}
            if self.integrity.integrity_relation == "normalized"
            else {"normalized"}
        )
        if representations != expected_representations:
            raise ValueError(
                "complete fiscal validation requires exact parser representations"
            )
        action_roles = {ref.artifact_id: ref.role for ref in self.action_refs}
        if (
            tuple(action_roles) != tuple(sorted(action_roles))
            or len(action_roles) != len(self.action_refs)
            or "sec-parser-action-report-v1" not in action_roles.values()
            or any(
                version != "v2"
                or action_roles.get(
                    f"sec-parser-action-result-{version}:{key}:{digest}"
                )
                != "sec-parser-action-result-v2"
                or action_roles.get(f"sec-parser-action-delivery-v2:{binding}")
                != "sec-parser-action-delivery-v2"
                for version, _, key, digest, binding in markers
            )
        ):
            raise ValueError(
                "complete fiscal validation requires retained parser actions"
            )
        return self


class FiscalValidationMatchedV1(_FiscalValidationCompleteV1):
    kind: Literal["complete_matched"] = "complete_matched"

    @model_validator(mode="after")
    def check_quality(self) -> FiscalValidationMatchedV1:
        if self.claim.status != "matched" or self.integrity.quality_decision != "pass":
            raise ValueError(
                "matched fiscal validation requires a passing issuer claim"
            )
        return self


class FiscalValidationCompleteRefusedV1(_FiscalValidationCompleteV1):
    kind: Literal["complete_refused"] = "complete_refused"
    issue_codes: RefusalCodes
    rejection_ref: ArtifactRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def check_refusal(self) -> FiscalValidationCompleteRefusedV1:
        if self.claim.status != "refused" or self.issue_codes != self.claim.issue_codes:
            raise ValueError("fiscal refusal requires the exact refused issuer claim")
        if self.rejection_ref is not None and (
            self.integrity.quality_decision != "block"
            or self.rejection_ref.role != "sec-ingestion-rejection"
            or self.rejection_ref.media_type != "application/json"
        ):
            raise ValueError("fiscal rejection reference has the wrong role or type")
        return self


FiscalValidationOutcomeV1 = Annotated[
    FiscalValidationIncompleteV1
    | FiscalValidationMatchedV1
    | FiscalValidationCompleteRefusedV1,
    Field(discriminator="kind"),
]


class FiscalOriginalValidationEvidenceV1(_FiscalValidationModel):
    protocol: Literal["fundamental.fiscal-original-validation-evidence.v1"] = (
        "fundamental.fiscal-original-validation-evidence.v1"
    )
    request: ResolvedFiscalValidationRequestV1
    outcome: FiscalValidationOutcomeV1

    @model_validator(mode="after")
    def check_scope(self) -> FiscalOriginalValidationEvidenceV1:
        request, outcome = self.request, self.outcome
        if isinstance(outcome, FiscalValidationIncompleteV1):
            return self
        runtime, claim, integrity = outcome.runtime, outcome.claim, outcome.integrity
        report, source = claim.report, claim.source
        responses = {receipt.uri: receipt for receipt in outcome.responses}
        primary = responses.get(source.uri)
        archive = responses.get(integrity.archive_uri)
        index = responses.get(integrity.archive_index_uri)
        filing = request.filing
        primary_uri = (
            f"https://www.sec.gov/Archives/edgar/data/{int(filing.cik)}/"
            f"{filing.accession_number.replace('-', '')}/{filing.primary_document}"
        )
        if (
            runtime.pin != request.pin
            or claim.request_digest != request.digest
            or claim.filing != request.filing
            or claim.decision_at != request.valuation_timestamp
            or runtime.taxonomy_version != report.taxonomy_version
            or runtime.pin.taxonomy_cache_sha256 != report.taxonomy_cache_hash
            or runtime.validation_profile_id != report.validation_profile.profile_id
            or runtime.validation_profile_digest != report.validation_profile_digest
            or runtime.parser_version != report.parser_version
            or not report.offline
            or integrity.taxonomy_manifest_hash != runtime.pin.taxonomy_cache_sha256
            or integrity.validation_profile_digest != runtime.validation_profile_digest
            or integrity.arelle_version != runtime.parser_version
            or integrity.accession_number != request.filing.accession_number
            or integrity.primary_document_uri != source.uri
            or integrity.raw_content_hash != source.content_hash
            or integrity.parser_input_hash != source.parser_input_hash
            or integrity.captured_at != source.captured_at
            or integrity.dqc_filing_context != report.dqc_filing_context
            or integrity.validation_engines != report.validation_engines
            or integrity.validation_evidence != execution_validation_evidence(report)
            or integrity.normalized_fact_count != len(report.facts)
            or integrity.normalized_fact_digest != fact_semantic_digest(report)
            or integrity.quality_decision
            != ("block" if report.blocking_finding_codes() else "pass")
            or report.dqc_filing_context is None
            or report.dqc_filing_context.issuer_id != request.filing.cik
            or report.dqc_filing_context.accession_number
            != request.filing.accession_number
            or report.dqc_filing_context.filing_date != request.filing.filing_date
            or source.cik != request.filing.cik
            or source.accession_number != request.filing.accession_number
            or source.form != request.filing.form
            or source.uri != primary_uri
            or source.available_at != request.filing.accepted_at
            or source.available_at > request.valuation_timestamp
            or primary is None
            or primary.content_hash != source.content_hash
            or primary.captured_at != source.captured_at
            or primary.http_status != source.http_status
            or primary.received_size != integrity.raw_received_size
            or archive is None
            or archive.content_hash != integrity.archive_hash
            or archive.received_size != integrity.archive_size
            or index is None
            or index.content_hash != integrity.archive_index_hash
            or tuple(responses) != tuple(sorted(responses))
            or len(responses) != len(outcome.responses)
            or any(receipt.scope != request.scope for receipt in outcome.responses)
        ):
            raise ValueError(
                "fiscal validation evidence differs from its retained request"
            )
        return self

    @property
    def artifact_id(self) -> str:
        if (
            isinstance(self.outcome, FiscalValidationIncompleteV1)
            and self.outcome.retryable
        ):
            digest = sha256_digest(self.model_dump(mode="json"))
            return f"fiscal-original-validation-attempt:{digest}"
        return self.request.completed_artifact_id

    @property
    def dependencies(self) -> tuple[str, ...]:
        values = {
            self.request.digest,
            self.request.selection.discovery_ref.content_hash,
        }
        if not isinstance(self.outcome, FiscalValidationIncompleteV1):
            values.update(sha256_digest(receipt) for receipt in self.outcome.responses)
            values.update(receipt.content_hash for receipt in self.outcome.responses)
            values.update(ref.content_hash for ref in self.outcome.action_refs)
            values.update(self.outcome.integrity.parser_content_hashes)
            if (
                isinstance(self.outcome, FiscalValidationCompleteRefusedV1)
                and self.outcome.rejection_ref is not None
            ):
                values.add(self.outcome.rejection_ref.content_hash)
        return tuple(sorted(values))


class ValidatedFiscalOriginalV1(_FiscalValidationModel):
    evidence_ref: ArtifactRefV1
    outcome: FiscalValidationMatchedV1
