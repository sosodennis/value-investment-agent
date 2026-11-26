from __future__ import annotations

import hashlib
from base64 import b64decode
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from functools import partial
from importlib.resources import files
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lxml import etree, html
from pydantic import ConfigDict, Field, model_validator

from .arelle_parser import ParsedXbrlFactV1
from .artifact_evidence import read_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .contracts import QualityStatus, StrictModel
from .data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
    sign_automatic_mapping_approval,
    verify_mapping_review_evidence,
)
from .fiscal_source_closure import FiscalArtifactRead
from .fiscal_statement_contracts import (
    FiscalDurationPeriodV1,
    FiscalObservationV1,
    FiscalReportedPeriodV1,
    FiscalReportingBasisV1,
    FiscalSourceLocatorV1,
    ReportedFiscalYearV1,
    ReportedInstantV1,
    ReportedQuarterV1,
    ReportedYtdV1,
    UnsupportedDurationV1,
)
from .fiscal_statement_registry import (
    Digest,
    FiscalDisclosureScopeV1,
    FiscalPrimaryFactScopeV1,
    FiscalPrimaryScopeV1,
    fiscal_statement_registry,
)
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationCompleteRefusedV1,
    FiscalValidationIncompleteV1,
)
from .ingestion import read_sec_xbrl_archive
from .metadata import metadata_operation_budget
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .statement_contracts import StatementRowId

FISCAL_MAPPING_EVALUATOR_ID = "fiscal-reviewed-primary-mapping-v1"
FISCAL_DISPLAY_PROFILE_ID = "fiscal-historical-statement-display-v1"


class FiscalMappingMissingV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    row_id: StatementRowId
    status: Literal["not_separately_disclosed"] = "not_separately_disclosed"
    primary_table_index: int = Field(ge=0)
    primary_table_sha256: Digest


class FiscalDisclosureEvidenceV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-accounting-disclosure.v1"] = (
        "fundamental.fiscal-accounting-disclosure.v1"
    )
    source_validation_ref: ArtifactRefV1
    primary_member_sha256: Digest
    locator: FiscalDisclosureScopeV1


class FiscalStatementMappingBatchV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-statement-mapping.v1"] = (
        "fundamental.fiscal-statement-mapping.v1"
    )
    source_validation_ref: ArtifactRefV1
    source_binding_digest: Digest
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    validation_kind: Literal["complete_matched", "complete_refused"]
    primary_scope_digest: Digest
    registry_digest: Digest
    policy_digest: Digest
    observations: tuple[FiscalObservationV1, ...] = Field(min_length=1)
    missing: tuple[FiscalMappingMissingV1, ...]
    disclosures: tuple[FiscalDisclosureEvidenceV1, ...]

    @model_validator(mode="after")
    def exact_source_observations(self) -> FiscalStatementMappingBatchV1:
        if len({item.observation_id for item in self.observations}) != len(
            self.observations
        ):
            raise ValueError("mapped observation identities must be unique")
        if any(
            item.source_artifact_id != self.source_validation_ref.artifact_id
            or item.source_binding_digest != self.source_binding_digest
            for item in self.observations
        ):
            raise ValueError("mapped observations differ from their exact source")
        if self.validation_kind == "complete_refused" and any(
            item.quality is not QualityStatus.PROVISIONAL for item in self.observations
        ):
            raise ValueError("refused mapped source must preserve provisional quality")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    @property
    def artifact_id(self) -> str:
        return f"fiscal-statement-mapping-v1:{self.digest}"


def fiscal_mapping_policy_digest() -> str:
    root = files("fundamental_service")
    names = (
        "fiscal_candidate_contracts.py",
        "fiscal_statement_registry.py",
        "fiscal_statement_mapping.py",
        "fiscal_projection_builder.py",
    )
    return sha256_digest(
        {
            "policy": FISCAL_MAPPING_EVALUATOR_ID,
            "registry": fiscal_statement_registry(),
            "sources": {
                name: hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest()
                for name in names
            },
        }
    )


def fiscal_projection_executable_digest() -> str:
    root = files("fundamental_service")
    names = (
        "fiscal_statement_contracts.py",
        "fiscal_statement_policy.py",
        "fiscal_statement_projection.py",
    )
    return sha256_digest(
        {
            name: hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest()
            for name in names
        }
    )


def fiscal_display_profile_digest() -> str:
    return sha256_digest(
        {
            "profile": FISCAL_DISPLAY_PROFILE_ID,
            "scope": "sec-us-gaap-nonfinancial-historical-quarter-ttm",
            "raw_refusal": "requires-source-classification-and-separate-fixed-candidate-decision",
            "valuation_eligibility": "not_evaluated",
            "supported_history_threshold": None,
        }
    )


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_MAPPING_INVALID", message)


def _text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def transcribe_fiscal_amount(node: etree._Element) -> Decimal:
    transform = node.get("format", "").split(":")[-1]
    if transform not in {"", "num-dot-decimal", "numdotdecimal"}:
        raise _invalid("primary amount uses an unreviewed numeric transform")
    lexical = _text(node).replace(",", "").strip()
    try:
        scale = int(node.get("scale", "0"))
        if abs(scale) > 1000 or len(lexical) > 1000:
            raise _invalid("primary amount exceeds numeric transcription limits")
        with localcontext() as context:
            context.prec = 2200
            value = Decimal(lexical).scaleb(scale)
            if node.get("sign") == "-":
                value = -value
        if not value.is_finite() or node.get("sign") not in {None, "+", "-"}:
            raise _invalid("primary amount is not a finite signed decimal")
        return value
    except (InvalidOperation, ValueError) as error:
        raise _invalid("primary amount cannot be transcribed") from error


def _reported_period(
    scope: FiscalPrimaryFactScopeV1,
    targets: tuple[FiscalDurationPeriodV1, ...],
) -> FiscalReportedPeriodV1:
    if scope.instant is not None:
        return ReportedInstantV1(instant=scope.instant)
    start, end = scope.period_start, scope.period_end
    if start is None or end is None:
        raise _invalid("reviewed duration has no complete source context")
    for target in targets:
        if (target.start, target.end) == (start, end):
            return ReportedQuarterV1(
                period=target,
                applicability="quarter_and_ytd"
                if start == target.fiscal_year_start
                else "quarter",
            )
    for target in targets:
        if (target.fiscal_year_start, target.end) == (start, end):
            span = target.model_copy(
                update={"start": start, "inclusive_days": (end - start).days + 1}
            )
            return (
                ReportedFiscalYearV1(period=span)
                if target.fiscal_period == "FY"
                else ReportedYtdV1(period=span)
            )
    for target in targets:
        if target.fiscal_year_start == start and 80 <= (end - start).days + 1 <= 105:
            span = target.model_copy(
                update={
                    "start": start,
                    "end": end,
                    "fiscal_period": "Q1",
                    "inclusive_days": (end - start).days + 1,
                }
            )
            return ReportedQuarterV1(period=span, applicability="quarter_and_ytd")
    return UnsupportedDurationV1(
        start=start, end=end, reason="outside_reviewed_fiscal_periods"
    )


def map_fiscal_primary_source(
    evidence: FiscalOriginalValidationEvidenceV1,
    source_ref: ArtifactRefV1,
    *,
    archive: bytes,
    reviewed: FiscalPrimaryScopeV1,
    target_periods: tuple[FiscalDurationPeriodV1, ...],
    security_id: str | None,
    policy_digest: str,
    check_deadline: Callable[[], float],
) -> FiscalStatementMappingBatchV1:
    check_deadline()
    outcome = evidence.outcome
    if isinstance(outcome, FiscalValidationIncompleteV1):
        raise _invalid("incomplete validation cannot supply fiscal mapping inputs")
    claim, filing = outcome.claim, evidence.request.filing
    binding = sha256_digest(evidence.model_dump(mode="json"))
    if (
        source_ref.artifact_id != evidence.artifact_id
        or source_ref.content_hash != binding
        or source_ref.role != "fiscal-original-validation"
        or claim.metadata_status != "matched"
        or filing.is_amendment
        or reviewed.issuer_id != filing.cik
        or reviewed.accession_number != filing.accession_number
        or reviewed.form != filing.form
        or reviewed.accepted_at != filing.accepted_at
        or reviewed.report_date != filing.report_period_end
        or reviewed.primary_document != filing.primary_document
        or reviewed.fiscal_year_focus != claim.fiscal_year_focus
        or reviewed.fiscal_period_focus != claim.fiscal_period_focus
        or reviewed.archive_sha256 != outcome.integrity.archive_hash
        or hashlib.sha256(archive).hexdigest() != reviewed.archive_sha256
    ):
        raise _invalid("source validation differs from its reviewed primary scope")
    member = read_sec_xbrl_archive(
        archive, primary_document=filing.primary_document, dts_filenames=()
    )[filing.primary_document]
    if (
        hashlib.sha256(member).hexdigest() != reviewed.primary_member_sha256
        or outcome.integrity.archive_member_hash != reviewed.primary_member_sha256
    ):
        raise _invalid("reviewed archive primary member differs")
    try:
        root = etree.fromstring(
            member,
            etree.XMLParser(resolve_entities=False, no_network=True, recover=True),
        )
        if root is None:
            raise _invalid("primary source cannot be decoded")
        nodes = root.xpath(
            '//*[local-name()="nonFraction" or local-name()="nonNumeric" or local-name()="fraction"][@name]'
        )
        tables = root.xpath('//*[local-name()="table"]')
        table_indexes = {table: index for index, table in enumerate(tables)}
        for table_scope in reviewed.tables:
            check_deadline()
            if (
                table_scope.table_index >= len(tables)
                or hashlib.sha256(
                    etree.tostring(tables[table_scope.table_index], method="c14n")
                ).hexdigest()
                != table_scope.table_sha256
            ):
                raise _invalid("reviewed primary statement table differs")
        parsed: dict[tuple[str, str], list[ParsedXbrlFactV1]] = {}
        for fact in claim.report.facts:
            parsed.setdefault((fact.concept, fact.context_id), []).append(fact)
        observations = []
        for fact_scope in reviewed.facts:
            check_deadline()
            if fact_scope.fact_index >= len(nodes):
                raise _invalid("reviewed primary fact is missing")
            node = nodes[fact_scope.fact_index]
            table = next(
                (
                    parent
                    for parent in node.iterancestors()
                    if etree.QName(parent).localname == "table"
                ),
                None,
            )
            row = next(
                (
                    parent
                    for parent in node.iterancestors()
                    if etree.QName(parent).localname == "tr"
                ),
                None,
            )
            if table is None or row is None:
                raise _invalid("primary fact has no reviewed table row")
            rows = table.xpath('.//*[local-name()="tr"]')
            if (
                node.get("id", "") != fact_scope.fact_id
                or node.get("name") != fact_scope.concept
                or node.get("contextRef") != fact_scope.context_id
                or table_indexes[table] != fact_scope.table_index
                or rows.index(row) != fact_scope.row_index
                or fact_scope.table_index
                not in {
                    item.table_index
                    for item in reviewed.tables
                    if item.statement == fact_scope.statement
                }
            ):
                raise _invalid("primary fact row, context or concept differs")
            value = transcribe_fiscal_amount(node)
            matches = [
                fact
                for fact in parsed.get((fact_scope.concept, fact_scope.context_id), ())
                if (
                    fact.namespace_uri == fact_scope.namespace_uri
                    and fact.unit == fact_scope.unit
                    and fact.entity_identifier == filing.cik
                    and fact.entity_scheme == "http://www.sec.gov/CIK"
                    and not fact.dimensions
                    and fact.consolidation_scope == "consolidated"
                    and fact.is_numeric
                    and (fact.period_start, fact.period_end, fact.instant)
                    == (
                        fact_scope.period_start,
                        fact_scope.period_end,
                        fact_scope.instant,
                    )
                    and fact.decimals == node.get("decimals")
                    and fact.scale == int(node.get("scale", "0"))
                    and Decimal(fact.value) == value
                )
            ]
            if not matches or len({sha256_digest(fact) for fact in matches}) != 1:
                raise _invalid(
                    "raw primary disclosure does not match the canonical parser fact"
                )
            fact = matches[0]
            decimals_raw = node.get("decimals")
            decimals: int | Literal["INF"] | None = (
                "INF"
                if decimals_raw == "INF"
                else int(decimals_raw)
                if decimals_raw is not None
                else None
            )
            observations.append(
                FiscalObservationV1(
                    observation_id=fact_scope.observation_id,
                    row_id=fact_scope.row_id,
                    statement=fact_scope.statement,
                    source_artifact_id=source_ref.artifact_id,
                    accession_number=filing.accession_number,
                    form=filing.form,
                    issuer_id=filing.cik,
                    accepted_at=filing.accepted_at,
                    available_at=claim.source.available_at,
                    filing_date=filing.filing_date,
                    report_date=filing.report_period_end,
                    period=_reported_period(fact_scope, target_periods),
                    basis=FiscalReportingBasisV1(
                        issuer_id=filing.cik,
                        security_id=security_id,
                        security_scope="issuer",
                        entity_scope=fact.entity_identifier or "",
                        currency="USD",
                        unit=fact_scope.unit,
                        consolidation_scope="consolidated",
                        dimensions=fact.dimensions,
                        cash_basis=fact_scope.cash_basis,
                    ),
                    source_locator=FiscalSourceLocatorV1(
                        primary_document_sha256=reviewed.primary_member_sha256,
                        context_id=fact_scope.context_id,
                        fact_index=fact_scope.fact_index,
                        table_index=fact_scope.table_index,
                        row_index=fact_scope.row_index,
                    ),
                    concept=fact.concept,
                    namespace_uri=fact_scope.namespace_uri,
                    source_fact_key=sha256_digest(fact),
                    raw_text=_text(node),
                    value=value,
                    scale=fact.scale,
                    sign=node.get("sign"),
                    decimals=decimals,
                    quality=QualityStatus.PROVISIONAL
                    if isinstance(outcome, FiscalValidationCompleteRefusedV1)
                    else QualityStatus.VERIFIED,
                    source_binding_digest=binding,
                    parser_action_digest=sha256_digest(outcome.action_refs),
                    mapping_digest=sha256_digest(
                        {
                            "source": source_ref,
                            "primary_scope": fact_scope,
                            "policy": policy_digest,
                        }
                    ),
                )
            )
        document = html.fromstring(member).getroottree()
        paragraphs = {
            document.getpath(node): node for node in document.iter("p", "div")
        }
        disclosures = []
        for disclosure in reviewed.disclosures:
            check_deadline()
            node = paragraphs.get(disclosure.xpath)
            if (
                node is None
                or hashlib.sha256(_text(node).encode()).hexdigest()
                != disclosure.text_sha256
            ):
                raise _invalid("reviewed accounting disclosure differs")
            disclosures.append(
                FiscalDisclosureEvidenceV1(
                    source_validation_ref=source_ref,
                    primary_member_sha256=reviewed.primary_member_sha256,
                    locator=disclosure,
                )
            )
    except (etree.XMLSyntaxError, IndexError, ValueError, InvalidOperation) as error:
        raise _invalid("reviewed primary statement cannot be reconstructed") from error
    check_deadline()
    return FiscalStatementMappingBatchV1(
        source_validation_ref=source_ref,
        source_binding_digest=binding,
        source_revision=evidence.request.pin.declared_source_revision,
        validation_kind=outcome.kind,
        primary_scope_digest=sha256_digest(reviewed),
        registry_digest=fiscal_statement_registry().digest,
        policy_digest=policy_digest,
        observations=tuple(observations),
        missing=tuple(
            FiscalMappingMissingV1(
                row_id=row_id,
                primary_table_index=table.table_index,
                primary_table_sha256=table.table_sha256,
            )
            for table in reviewed.tables
            for row_id in table.missing_rows
        ),
        disclosures=tuple(disclosures),
    )


class FiscalMappingVerifier:
    def __init__(
        self,
        *,
        artifacts: EvidenceArtifactStore,
        trust_roots: Callable[[], DataReleaseTrustRootsV1],
        evaluator_id: str = FISCAL_MAPPING_EVALUATOR_ID,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.artifacts, self.trust_roots = artifacts, trust_roots
        self.evaluator_id, self.clock = evaluator_id, clock

    @staticmethod
    def _expired() -> SnapshotError:
        return SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED",
            "fiscal mapping deadline expired",
            retryable=True,
        )

    def _budget(self, deadline_at: datetime) -> float:
        now = self.clock()
        if (
            deadline_at.utcoffset() is None
            or now.utcoffset() is None
            or deadline_at <= now
        ):
            raise self._expired()
        return (deadline_at - now).total_seconds()

    def _authority(self, policy_digest: str) -> DataReleaseTrustRootsV1:
        roots = self.trust_roots()
        evaluator = roots.automatic_mapping_evaluators.get(self.evaluator_id)
        if (
            evaluator is None
            or evaluator.policy_digest != policy_digest
            or policy_digest != fiscal_mapping_policy_digest()
        ):
            raise DataReleaseError(
                "FISCAL_MAPPING_AUTHORITY_UNTRUSTED",
                "fiscal mapping evaluator or installed policy is not trusted",
            )
        return roots

    def verify(
        self,
        batch: FiscalStatementMappingBatchV1,
        reference: ArtifactRefV1,
        *,
        deadline_at: datetime,
    ) -> AutomaticMappingApprovalV1:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            budget = partial(self._budget, deadline_at)
            reader = FiscalArtifactRead(self.artifacts, budget)
            approval = AutomaticMappingApprovalV1.model_validate_json(
                read_retained_artifact(reader, reference)
            )
            expected_input = sha256_digest(
                {
                    "source": batch.source_validation_ref,
                    "scope": batch.primary_scope_digest,
                    "policy": batch.policy_digest,
                }
            )
            expected_ref = ArtifactRefV1(
                role="fiscal-statement-mapping-v1",
                artifact_id=batch.artifact_id,
                content_hash=batch.digest,
                media_type="application/json",
            )
            if (
                reference.role != "fiscal-mapping-approval"
                or reference.artifact_id
                != "fiscal-mapping-approval-v1:" + sha256_digest(approval)
                or (
                    approval.mapping_id,
                    approval.mapping_digest,
                    approval.output_digest,
                    approval.source_revision,
                    approval.policy_digest,
                    approval.input_digest,
                    approval.evidence_refs,
                )
                != (
                    batch.artifact_id,
                    batch.digest,
                    batch.digest,
                    batch.source_revision,
                    batch.policy_digest,
                    expected_input,
                    (expected_ref, batch.source_validation_ref),
                )
            ):
                raise _invalid(
                    "fiscal mapping approval differs from reconstructed mapping"
                )
            verify_mapping_review_evidence(
                approval, self._authority(batch.policy_digest)
            )
            reader.check_current()
            verify_mapping_review_evidence(
                approval, self._authority(batch.policy_digest)
            )
            budget()
            return approval


class FiscalMappingApprovalOwner(FiscalMappingVerifier):
    def __init__(
        self,
        *,
        artifacts: EvidenceArtifactStore,
        trust_roots: Callable[[], DataReleaseTrustRootsV1],
        private_key: Callable[[], Ed25519PrivateKey],
        evaluator_id: str = FISCAL_MAPPING_EVALUATOR_ID,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(
            artifacts=artifacts,
            trust_roots=trust_roots,
            evaluator_id=evaluator_id,
            clock=clock,
        )
        self.private_key = private_key

    def approve(
        self,
        batch: FiscalStatementMappingBatchV1,
        reference: ArtifactRefV1,
        *,
        deadline_at: datetime,
    ) -> ArtifactRefV1:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            budget = partial(self._budget, deadline_at)
            budget()
            roots = self._authority(batch.policy_digest)
            reader = FiscalArtifactRead(self.artifacts, budget)
            if read_retained_artifact(reader, reference) != canonical_bytes(batch):
                raise _invalid("retained fiscal mapping differs")
            if self.private_key is None:
                raise SnapshotError(
                    "FISCAL_MAPPING_AUTHORITY_UNCONFIGURED",
                    "fiscal mapping publication requires a signing capability",
                )
            key = self.private_key()
            if key.public_key().public_bytes_raw() != b64decode(
                roots.automatic_mapping_evaluators[
                    self.evaluator_id
                ].public_key_ed25519_base64,
                validate=True,
            ):
                raise _invalid(
                    "fiscal mapping signer differs from deployment authority"
                )
            approval = sign_automatic_mapping_approval(
                {
                    "mapping_id": batch.artifact_id,
                    "mapping_digest": batch.digest,
                    "evaluator_id": self.evaluator_id,
                    "policy_digest": batch.policy_digest,
                    "source_revision": batch.source_revision,
                    "input_digest": sha256_digest(
                        {
                            "source": batch.source_validation_ref,
                            "scope": batch.primary_scope_digest,
                            "policy": batch.policy_digest,
                        }
                    ),
                    "output_digest": batch.digest,
                    "evidence_refs": (reference, batch.source_validation_ref),
                },
                key,
            )
            verify_mapping_review_evidence(
                approval, self._authority(batch.policy_digest)
            )
            publication = self.artifacts.put_with_receipt(
                "fiscal-mapping-approval-v1:" + sha256_digest(approval),
                approval,
                (batch.digest, batch.source_validation_ref.content_hash),
                publication_budget=budget,
            )
            reader.expect(publication.artifact.artifact_id, publication.artifact)
            reader.get(publication.artifact.artifact_id)
            reader.check_current()
            verify_mapping_review_evidence(
                approval, self._authority(batch.policy_digest)
            )
            budget()
            return ArtifactRefV1(
                role="fiscal-mapping-approval",
                artifact_id=publication.artifact.artifact_id,
                content_hash=publication.artifact.content_hash,
                media_type="application/json",
            )
