from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Literal, Protocol

from pydantic import AwareDatetime, ConfigDict, Field

from .artifact_evidence import read_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .data_releases import AutomaticMappingApprovalV1
from .fiscal_candidate_contracts import (
    ClassifiedSourceForCandidateV1,
    FiscalCandidateClassificationBindingV1,
    FiscalCandidateSourceUseV1,
    FiscalSourceUseScopeV1,
    FiscalStatementCandidateV1,
    VerifiedRawSourceForCandidateV1,
)
from .fiscal_discovery import FiscalDiscovery
from .fiscal_source_closure import FiscalArtifactRead, FiscalSourceClosure
from .fiscal_statement_contracts import (
    FiscalBasisFilingV1,
    FiscalBasisObservationV1,
    FiscalComparativePairV1,
    FiscalDurationPeriodV1,
    FiscalObservationV1,
    FiscalPeriodTargetV1,
    FiscalProjectionInputV1,
    FiscalProjectionResultV1,
    FiscalRevisionBasisProofV1,
    FiscalTtmWindowV1,
    ReportedQuarterV1,
)
from .fiscal_statement_mapping import (
    FiscalMappingApprovalOwner,
    FiscalStatementMappingBatchV1,
    fiscal_display_profile_digest,
    fiscal_mapping_policy_digest,
    fiscal_projection_executable_digest,
    map_fiscal_primary_source,
)
from .fiscal_statement_policy import fiscal_statement_policy
from .fiscal_statement_projection import project_fiscal_statements
from .fiscal_statement_registry import (
    Digest,
    FiscalFourthQuarterBoundaryV1,
    FiscalQuarterReviewV1,
    FiscalReviewedCoverageV1,
    FiscalRowBasisPlanV1,
    fiscal_primary_scopes,
    fiscal_statement_registry,
    selected_fiscal_coverage,
)
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalOriginalValidationRequestV1,
    FiscalValidationCompleteRefusedV1,
    FiscalValidationIncompleteV1,
    FiscalValidationPinV1,
    ResolvedFiscalValidationRequestV1,
)
from .metadata import metadata_operation_budget
from .replay import ArtifactPublicationV1, ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError
from .statement_contracts import StatementScopeV1


class FiscalCandidateClassificationPort(Protocol):
    def require_candidate_source(
        self,
        scope: FiscalSourceUseScopeV1,
        classification_refs: tuple[ArtifactRefV1, ...],
        *,
        deadline_at: datetime,
    ) -> ClassifiedSourceForCandidateV1: ...


class FiscalCoverageBasisEvidenceV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    protocol: Literal["fundamental.fiscal-reconstructed-basis-review.v1"] = (
        "fundamental.fiscal-reconstructed-basis-review.v1"
    )
    coverage: FiscalReviewedCoverageV1
    observations: tuple[FiscalBasisObservationV1, ...]
    filings: tuple[FiscalBasisFilingV1, ...]
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    cutoff_at: AwareDatetime
    source_set_digest: Digest
    mapping_refs: tuple[ArtifactRefV1, ...]


class FiscalProjectionCandidatePublicationV1(StrictModel):
    model_config = ConfigDict(frozen=True)

    candidate: FiscalStatementCandidateV1
    projection: FiscalProjectionResultV1
    candidate_publication: ArtifactPublicationV1
    consumed_metadata: tuple[ArtifactRecordV1, ...]


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_PROJECTION_SOURCE_INVALID", message)


class FiscalProjectionBuilder:
    def __init__(
        self,
        *,
        discovery: FiscalDiscovery,
        sources: FiscalSourceClosure,
        artifacts: EvidenceArtifactStore,
        content: ContentAddressedStore,
        pin: FiscalValidationPinV1,
        mapping_approvals: FiscalMappingApprovalOwner | None,
        preparer_execution_ref: ArtifactRefV1,
        classifications: FiscalCandidateClassificationPort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.discovery, self.sources, self.artifacts, self.content = (
            discovery,
            sources,
            artifacts,
            content,
        )
        self.pin, self.mapping_approvals = pin, mapping_approvals
        self.preparer_execution_ref, self.classifications, self.clock = (
            preparer_execution_ref,
            classifications,
            clock,
        )

    @staticmethod
    def _expired() -> SnapshotError:
        return SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED",
            "fiscal projection preparation deadline expired",
            retryable=True,
        )

    def _budget(self, deadline_at: datetime) -> float:
        now = self.clock()
        if (
            now.utcoffset() is None
            or deadline_at.utcoffset() is None
            or deadline_at <= now
        ):
            raise self._expired()
        return (deadline_at - now).total_seconds()

    def _retain(
        self,
        value: object,
        role: str,
        dependencies: tuple[str, ...],
        reader: FiscalArtifactRead,
        *,
        publish: bool,
        deadline_at: datetime,
    ) -> ArtifactRefV1:
        digest = sha256_digest(value)
        identity = role + ":" + digest
        dependencies = tuple(sorted(set(dependencies)))
        if publish:
            publication = self.artifacts.put_with_receipt(
                identity,
                value,
                dependencies,
                publication_budget=partial(self._budget, deadline_at),
            )
            reader.expect(identity, publication.artifact)
        record = reader.get(identity)
        if (
            record.content_hash != digest
            or record.dependency_hashes != dependencies
            or reader.read(identity) != canonical_bytes(value)
        ):
            raise _invalid("retained fiscal preparation evidence differs")
        return ArtifactRefV1(
            role=role,
            artifact_id=identity,
            content_hash=digest,
            media_type="application/json",
        )

    @staticmethod
    def _period(
        quarter: FiscalQuarterReviewV1,
        evidence: dict[str, FiscalOriginalValidationEvidenceV1],
        mapped: dict[str, FiscalStatementMappingBatchV1],
    ) -> FiscalDurationPeriodV1:
        source = evidence[quarter.accession_number]
        if isinstance(source.outcome, FiscalValidationIncompleteV1):
            raise _invalid("fiscal target source is incomplete")
        claim = source.outcome.claim
        expected = quarter.period
        if (
            claim.report_period_end != expected.end
            or claim.fiscal_year_focus != expected.fiscal_year
            or claim.fiscal_period_focus != expected.fiscal_period
        ):
            raise _invalid("fiscal target differs from original DEI identity")
        cash_fact_keys = {
            item.source_fact_key
            for item in mapped[quarter.accession_number].observations
            if item.row_id
            in {"operating_cash_flow", "investing_cash_flow", "financing_cash_flow"}
        }
        current_cash_starts = {
            fact.period_start
            for fact in claim.report.facts
            if sha256_digest(fact) in cash_fact_keys
            and fact.period_end == expected.end
            and fact.period_start is not None
        }
        if (
            not current_cash_starts
            or min(current_cash_starts) != expected.fiscal_year_start
        ):
            raise _invalid(
                "fiscal-year start differs from the disclosed primary cash-flow YTD context"
            )
        source_period = quarter.period_source
        if isinstance(source_period, FiscalFourthQuarterBoundaryV1):
            prior = evidence[source_period.preceding_accession_number]
            if isinstance(prior.outcome, FiscalValidationIncompleteV1):
                raise _invalid("preceding fiscal boundary source is incomplete")
            if (
                prior.outcome.claim.report_period_end
                != source_period.preceding_quarter_end
                or prior.outcome.claim.fiscal_year_focus != expected.fiscal_year
                or prior.outcome.claim.fiscal_period_focus != "Q3"
                or expected.start
                != source_period.preceding_quarter_end + timedelta(days=1)
                or not any(
                    fact.context_id == source_period.annual_context_id
                    and fact.period_start == expected.fiscal_year_start
                    and fact.period_end == expected.end
                    for fact in claim.report.facts
                )
            ):
                raise _invalid(
                    "fourth-quarter boundary does not follow the disclosed nine-month period"
                )
        else:
            matching = [
                item
                for item in mapped[quarter.accession_number].observations
                if item.source_locator.fact_index == source_period.fact_index
                and item.source_locator.context_id == source_period.context_id
                and item.row_id == "revenue"
            ]
            if (
                len(matching) != 1
                or not isinstance(matching[0].period, ReportedQuarterV1)
                or matching[0].period.period != expected
            ):
                raise _invalid(
                    "quarter target does not match its reported duration context"
                )
            if not any(
                fact.period_start == expected.fiscal_year_start
                and fact.period_end == expected.end
                for fact in claim.report.facts
            ):
                raise _invalid("fiscal-year start has no disclosed YTD context")
        return expected

    def _basis(
        self,
        plan: FiscalRowBasisPlanV1,
        period: FiscalDurationPeriodV1,
        observations: dict[str, FiscalObservationV1],
        filings: dict[str, FiscalBasisFilingV1],
        cutoff_at: datetime,
        component_periods: tuple[FiscalPeriodTargetV1, ...],
        reference: ArtifactRefV1,
    ) -> FiscalRevisionBasisProofV1 | None:
        if not plan.observation_ids:
            return None
        if any(identity not in observations for identity in plan.observation_ids):
            raise _invalid("reviewed basis requires a missing original observation")
        selected = tuple(observations[identity] for identity in plan.observation_ids)
        for left_id, right_id in plan.comparative_pairs:
            left, right = observations[left_id], observations[right_id]
            if (
                left.row_id != right.row_id
                or left.value != right.value
                or not left.basis.same_accounting_scope(right.basis)
                or left.period != right.period
            ):
                raise _invalid(
                    "reviewed original and comparative disclosure no longer reproduce"
                )
        bindings = tuple(
            FiscalBasisObservationV1(
                observation_id=item.observation_id,
                observation_digest=item.observation_digest,
            )
            for item in selected
        )
        pairs = tuple(
            FiscalComparativePairV1(original_id=left, comparative_id=right)
            for left, right in plan.comparative_pairs
        )
        source_filings = tuple(
            filings[accession]
            for accession in sorted({item.accession_number for item in selected})
        )
        if any(item.accepted_at > cutoff_at for item in source_filings):
            raise _invalid("reviewed revision basis was not public at cutoff")
        return FiscalRevisionBasisProofV1(
            row_id=plan.row_id,
            period=period,
            observations=bindings,
            filings=source_filings,
            comparative_pairs=pairs,
            component_period_digests=tuple(
                sha256_digest(item) for item in component_periods
            ),
            source_revision=self.pin.declared_source_revision,
            cutoff_at=cutoff_at,
            public_available_at=max(item.accepted_at for item in source_filings),
            review_evidence_ref=reference,
        )

    def prepare(
        self,
        discovery_ref: ArtifactRefV1,
        *,
        security_id: str | None,
        classification_bindings: tuple[
            FiscalCandidateClassificationBindingV1, ...
        ] = (),
        deadline_at: datetime,
    ) -> FiscalProjectionCandidatePublicationV1:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            return self._build(
                discovery_ref,
                security_id=security_id,
                classification_bindings=classification_bindings,
                deadline_at=deadline_at,
                publish=True,
            )

    def _build(
        self,
        discovery_ref: ArtifactRefV1,
        *,
        security_id: str | None,
        classification_bindings: tuple[FiscalCandidateClassificationBindingV1, ...],
        deadline_at: datetime,
        publish: bool,
        retained_mapping_refs: tuple[ArtifactRefV1, ...] = (),
        preparer_execution_ref: ArtifactRefV1 | None = None,
    ) -> FiscalProjectionCandidatePublicationV1:
        budget = partial(self._budget, deadline_at)
        budget()
        if self.mapping_approvals is None:
            raise SnapshotError(
                "FISCAL_MAPPING_AUTHORITY_UNCONFIGURED",
                "fiscal projection preparation requires a configured mapping authority",
            )
        reader = FiscalArtifactRead(self.artifacts, budget)
        discovery = self.discovery.read(
            discovery_ref.artifact_id, deadline_at=deadline_at
        )
        if (
            read_retained_artifact(reader, discovery_ref) != canonical_bytes(discovery)
            or discovery.request.declared_source_revision
            != self.pin.declared_source_revision
        ):
            raise _invalid(
                "projection discovery differs from the configured source revision"
            )
        coverage = selected_fiscal_coverage(discovery)
        preparer = preparer_execution_ref or self.preparer_execution_ref
        read_retained_artifact(reader, preparer)
        scopes = {
            item.accession_number: item
            for item in fiscal_primary_scopes(fiscal_statement_registry())
        }
        candidates = {
            item.filing.accession_number: item.filing
            for item in discovery.selection.candidates
            if item.filing is not None and not item.issue_codes
        }
        target_periods = tuple(item.period for item in coverage.quarters)
        policy_digest = fiscal_mapping_policy_digest()
        evidence_by_accession: dict[str, FiscalOriginalValidationEvidenceV1] = {}
        mapped: dict[str, FiscalStatementMappingBatchV1] = {}
        classifications: dict[str, FiscalCandidateClassificationBindingV1] = {}
        for binding in classification_bindings:
            source_id = binding.source_validation_ref.artifact_id
            if source_id in classifications:
                raise _invalid(
                    "candidate source has multiple supplied witness bindings"
                )
            classifications[source_id] = binding
        source_uses: list[FiscalCandidateSourceUseV1] = []
        mapping_refs: list[ArtifactRefV1] = []
        filings: dict[str, FiscalBasisFilingV1] = {}
        for accession in coverage.source_accessions:
            budget()
            filing = candidates.get(accession)
            if filing is None:
                raise _invalid("reviewed source is not an eligible discovery candidate")
            resolved = ResolvedFiscalValidationRequestV1(
                selection=FiscalOriginalValidationRequestV1(
                    discovery_ref=discovery_ref, accession_number=accession
                ),
                filing=filing,
                valuation_timestamp=discovery.request.valuation_timestamp,
                pin=self.pin,
            )
            source_read = self.sources.read_with_metadata(
                resolved.completed_artifact_id, deadline_at=deadline_at
            )
            for identity, record in source_read.records:
                reader.expect(identity, record)
            evidence = source_read.evidence
            if evidence.request != resolved or isinstance(
                evidence.outcome, FiscalValidationIncompleteV1
            ):
                raise _invalid("source closure differs from requested fiscal candidate")
            if security_id is not None and security_id not in {
                fact.value.strip()
                for fact in evidence.outcome.claim.report.facts
                if fact.concept == "dei:TradingSymbol"
                and fact.entity_identifier == filing.cik
                and fact.entity_scheme == "http://www.sec.gov/CIK"
                and fact.namespace_uri is not None
                and fact.namespace_uri.startswith(
                    ("http://xbrl.sec.gov/dei/", "http://xbrl.us/dei/")
                )
            }:
                raise _invalid(
                    "security identifier is not disclosed for the source issuer"
                )
            source_ref = ArtifactRefV1(
                role="fiscal-original-validation",
                artifact_id=evidence.artifact_id,
                content_hash=sha256_digest(evidence.model_dump(mode="json")),
                media_type="application/json",
            )
            source_record = reader.get(source_ref.artifact_id)
            if (
                source_record.content_hash != source_ref.content_hash
                or source_record.media_type != source_ref.media_type
                or source_record.dependency_hashes != evidence.dependencies
            ):
                raise _invalid("source validation metadata differs from its closure")
            archive_receipt = next(
                (
                    item
                    for item in evidence.outcome.responses
                    if item.uri == evidence.outcome.integrity.archive_uri
                ),
                None,
            )
            if archive_receipt is None:
                raise _invalid("fiscal original archive receipt is missing")
            archive = self.content.get(
                archive_receipt.content_hash, media_type=archive_receipt.media_type
            )
            budget()
            batch = map_fiscal_primary_source(
                evidence,
                source_ref,
                archive=archive,
                reviewed=scopes[accession],
                target_periods=target_periods,
                security_id=security_id,
                policy_digest=policy_digest,
                check_deadline=budget,
            )
            if isinstance(evidence.outcome, FiscalValidationCompleteRefusedV1):
                if self.classifications is None:
                    raise SnapshotError(
                        "FISCAL_CLASSIFICATION_UNCONFIGURED",
                        "raw-refused candidate source requires an independent classification owner",
                    )
                if source_ref.artifact_id not in classifications:
                    raise SnapshotError(
                        "FISCAL_WITNESS_REQUIRED",
                        "raw-refused candidate source requires its exact retained witness",
                    )
                if (
                    classifications[source_ref.artifact_id].source_validation_ref
                    != source_ref
                ):
                    raise _invalid(
                        "classification reference differs from the exact source"
                    )
            classification = classifications.get(source_ref.artifact_id)
            if classification is not None and not isinstance(
                evidence.outcome, FiscalValidationCompleteRefusedV1
            ):
                raise _invalid(
                    "raw-pass source cannot consume a refusal classification"
                )
            use_scope = FiscalSourceUseScopeV1(
                source_validation_ref=source_ref,
                validation_kind=evidence.outcome.kind,
                source_binding_digest=batch.source_binding_digest,
                issuer_id=filing.cik,
                accession_number=accession,
                cutoff_at=discovery.request.valuation_timestamp,
                runtime=evidence.outcome.runtime,
                raw_report_digest=sha256_digest(
                    evidence.outcome.claim.report.model_dump(mode="json")
                ),
                parser_action_refs=evidence.outcome.action_refs,
                witness_ref=classification.witness_ref
                if classification is not None
                else None,
                display_profile_digest=fiscal_display_profile_digest(),
                mapping_policy_digest=policy_digest,
                permitted_inputs=batch.observations,
            )
            if isinstance(evidence.outcome, FiscalValidationCompleteRefusedV1):
                if self.classifications is None:
                    raise _invalid("candidate classification owner became unavailable")
                if classification is None:
                    raise _invalid("candidate source has no classification binding")
                read_retained_artifact(reader, classification.witness_ref)
                for reference in classification.classification_refs:
                    read_retained_artifact(reader, reference)
                admitted = self.classifications.require_candidate_source(
                    use_scope,
                    classification.classification_refs,
                    deadline_at=deadline_at,
                )
                if admitted.scope != use_scope:
                    raise _invalid(
                        "classification does not authorize the exact requested source use"
                    )
                source_uses.append(admitted)
            else:
                source_uses.append(VerifiedRawSourceForCandidateV1(scope=use_scope))
            batch_ref = self._retain(
                batch,
                "fiscal-statement-mapping-v1",
                (source_ref.content_hash, batch.primary_scope_digest, policy_digest),
                reader,
                publish=publish,
                deadline_at=deadline_at,
            )
            if publish:
                approval_ref = self.mapping_approvals.approve(
                    batch, batch_ref, deadline_at=deadline_at
                )
            else:
                possible = [
                    ref
                    for ref in retained_mapping_refs
                    if ref.role == "fiscal-mapping-approval"
                ]
                possible_ref = next(
                    (
                        ref
                        for ref in possible
                        if AutomaticMappingApprovalV1.model_validate_json(
                            reader.read(ref.artifact_id)
                        ).mapping_id
                        == batch.artifact_id
                    ),
                    None,
                )
                if possible_ref is None:
                    raise _invalid(
                        "candidate lacks its exact retained mapping approval"
                    )
                approval_ref = possible_ref
            self.mapping_approvals.verify(batch, approval_ref, deadline_at=deadline_at)
            read_retained_artifact(reader, approval_ref)
            mapping_refs.extend((batch_ref, approval_ref))
            disclosure_refs = tuple(
                self._retain(
                    item,
                    "fiscal-accounting-disclosure-v1",
                    (source_ref.content_hash, item.primary_member_sha256),
                    reader,
                    publish=publish,
                    deadline_at=deadline_at,
                )
                for item in batch.disclosures
            )
            filings[accession] = FiscalBasisFilingV1(
                accession_number=accession,
                primary_document_sha256=scopes[accession].primary_member_sha256,
                accepted_at=filing.accepted_at,
                disclosure_refs=disclosure_refs,
            )
            evidence_by_accession[accession], mapped[accession] = evidence, batch
        if set(classifications) != {
            item.scope.source_validation_ref.artifact_id
            for item in source_uses
            if isinstance(item, ClassifiedSourceForCandidateV1)
        }:
            raise _invalid(
                "classification bindings differ from the exact refused source set"
            )
        source_set_digest = sha256_digest(tuple(source_uses))
        targets = tuple(
            FiscalPeriodTargetV1(
                period_id="fiscal-quarter-v1:"
                + sha256_digest(
                    (
                        coverage.issuer_id,
                        security_id,
                        item.period,
                        discovery.request.valuation_timestamp,
                        source_set_digest,
                        policy_digest,
                    )
                ),
                period=self._period(item, evidence_by_accession, mapped),
                cutoff_at=discovery.request.valuation_timestamp,
                source_binding_digest=source_set_digest,
            )
            for item in coverage.quarters
        )
        by_end = {
            item.period.end: item
            for item in targets
            if isinstance(item.period, FiscalDurationPeriodV1)
        }
        windows = tuple(
            FiscalTtmWindowV1(
                window_id="fiscal-ttm-v1:"
                + sha256_digest(tuple(by_end[end] for end in item.quarter_ends)),
                quarters=tuple(by_end[end] for end in item.quarter_ends),
                source_binding_digest=source_set_digest,
            )
            for item in coverage.ttm_windows
        )
        observations = tuple(
            item for batch in mapped.values() for item in batch.observations
        )
        by_id = {item.observation_id: item for item in observations}
        cohort_review = FiscalCoverageBasisEvidenceV1(
            coverage=coverage,
            observations=tuple(
                FiscalBasisObservationV1(
                    observation_id=item.observation_id,
                    observation_digest=item.observation_digest,
                )
                for item in observations
            ),
            filings=tuple(filings[key] for key in sorted(filings)),
            source_revision=self.pin.declared_source_revision,
            cutoff_at=discovery.request.valuation_timestamp,
            source_set_digest=source_set_digest,
            mapping_refs=tuple(mapping_refs),
        )
        review_ref = self._retain(
            cohort_review,
            "fiscal-basis-review-v1",
            tuple(ref.content_hash for ref in mapping_refs)
            + tuple(
                ref.content_hash
                for filing in filings.values()
                for ref in filing.disclosure_refs
            ),
            reader,
            publish=publish,
            deadline_at=deadline_at,
        )
        proofs = []
        for quarter in coverage.quarters:
            for plan in quarter.rows:
                budget()
                proof = self._basis(
                    plan,
                    quarter.period,
                    by_id,
                    filings,
                    discovery.request.valuation_timestamp,
                    (),
                    review_ref,
                )
                if proof is not None:
                    proofs.append(proof)
        for review, window in zip(coverage.ttm_windows, windows, strict=True):
            first, last = window.quarters[0].period, window.quarters[-1].period
            if not isinstance(first, FiscalDurationPeriodV1) or not isinstance(
                last, FiscalDurationPeriodV1
            ):
                raise _invalid("reviewed TTM components are not duration quarters")
            period = first.model_copy(
                update={
                    "end": last.end,
                    "fiscal_year": last.fiscal_year,
                    "fiscal_period": "TTM",
                    "inclusive_days": (last.end - first.start).days + 1,
                }
            )
            for plan in review.rows:
                budget()
                proof = self._basis(
                    plan,
                    period,
                    by_id,
                    filings,
                    discovery.request.valuation_timestamp,
                    window.quarters,
                    review_ref,
                )
                if proof is not None:
                    proofs.append(proof)
        scope = StatementScopeV1(
            issuer_id=coverage.issuer_id,
            security_id=security_id,
            security_scope="issuer",
            entity_scope=coverage.issuer_id,
            currency="USD",
            unit="iso4217:USD",
        )
        projection = project_fiscal_statements(
            FiscalProjectionInputV1(
                observations=observations,
                scope=scope,
                quarter_targets=targets,
                ttm_windows=windows,
                cutoff_at=discovery.request.valuation_timestamp,
                source_binding_digest=source_set_digest,
                basis_proofs=tuple(proofs),
                source_revision=self.pin.declared_source_revision,
                executable_digest=fiscal_projection_executable_digest(),
            )
        )
        budget()
        projection_ref = self._retain(
            projection,
            "fiscal-statement-projection-v1",
            tuple(ref.content_hash for ref in mapping_refs)
            + tuple(item.review_evidence_ref.content_hash for item in proofs),
            reader,
            publish=publish,
            deadline_at=deadline_at,
        )
        candidate = FiscalStatementCandidateV1(
            scope=scope,
            cutoff_at=discovery.request.valuation_timestamp,
            source_uses=tuple(source_uses),
            mapping_refs=tuple(mapping_refs),
            projection_ref=projection_ref,
            period_set_digest=sha256_digest((targets, windows)),
            row_lineage_digest=sha256_digest(
                tuple(
                    (item.node_id, item.input_edges, item.verification_edges)
                    for item in projection.nodes
                )
            ),
            source_set_digest=source_set_digest,
            projection_policy_digest=fiscal_statement_policy().digest,
            executable_digest=fiscal_projection_executable_digest(),
            preparer_execution_ref=preparer,
        )
        candidate_dependencies = tuple(
            sorted(
                {projection_ref.content_hash, source_set_digest, preparer.content_hash}
            )
        )
        if publish:
            candidate_publication = self.artifacts.put_with_receipt(
                candidate.artifact_id,
                candidate,
                candidate_dependencies,
                publication_budget=budget,
            )
            reader.expect(candidate.artifact_id, candidate_publication.artifact)
        else:
            self._retain(
                candidate,
                "fiscal-statement-candidate-v1",
                candidate_dependencies,
                reader,
                publish=False,
                deadline_at=deadline_at,
            )
            candidate_publication = ArtifactPublicationV1(
                artifact=reader.get(candidate.artifact_id), wrote=False
            )
        if reader.read(candidate.artifact_id) != canonical_bytes(candidate):
            raise _invalid("retained candidate differs from reconstructed inputs")
        for source in source_uses:
            if isinstance(source, ClassifiedSourceForCandidateV1):
                if (
                    self.classifications is None
                    or self.classifications.require_candidate_source(
                        source.scope,
                        source.classification_refs,
                        deadline_at=deadline_at,
                    )
                    != source
                ):
                    raise _invalid("candidate classification changed before completion")
        for batch, approval in zip(mapped.values(), mapping_refs[1::2], strict=True):
            self.mapping_approvals.verify(batch, approval, deadline_at=deadline_at)
        reader.check_current()
        budget()
        return FiscalProjectionCandidatePublicationV1(
            candidate=candidate,
            projection=projection,
            candidate_publication=candidate_publication,
            consumed_metadata=tuple(
                record for _, record in reader.records if record is not None
            ),
        )

    def verify_candidate(
        self,
        reference: ArtifactRefV1,
        *,
        deadline_at: datetime,
    ) -> FiscalProjectionCandidatePublicationV1:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            budget = partial(self._budget, deadline_at)
            reader = FiscalArtifactRead(self.artifacts, budget)
            candidate = FiscalStatementCandidateV1.model_validate_json(
                read_retained_artifact(reader, reference)
            )
            if (
                reference.role != "fiscal-statement-candidate-v1"
                or reference.artifact_id != candidate.artifact_id
            ):
                raise _invalid("candidate reference has the wrong identity")
            first = self.sources.read_with_metadata(
                candidate.source_uses[0].scope.source_validation_ref.artifact_id,
                deadline_at=deadline_at,
            )
            for identity, record in first.records:
                reader.expect(identity, record)
            bindings = tuple(
                FiscalCandidateClassificationBindingV1(
                    source_validation_ref=item.scope.source_validation_ref,
                    witness_ref=item.scope.witness_ref,
                    classification_refs=item.classification_refs,
                )
                for item in candidate.source_uses
                if isinstance(item, ClassifiedSourceForCandidateV1)
                and item.scope.witness_ref is not None
            )
            result = self._build(
                first.evidence.request.selection.discovery_ref,
                security_id=candidate.scope.security_id,
                classification_bindings=bindings,
                deadline_at=deadline_at,
                publish=False,
                retained_mapping_refs=candidate.mapping_refs,
                preparer_execution_ref=candidate.preparer_execution_ref,
            )
            if result.candidate != candidate:
                raise _invalid(
                    "candidate does not reproduce from current source closure"
                )
            reader.check_current()
            budget()
            return result
