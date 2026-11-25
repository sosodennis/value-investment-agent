from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .artifact_evidence import read_retained_artifact
from .data_releases import ArtifactRefV1
from .fiscal_candidate_contracts import FiscalSourceUseScopeV1
from .fiscal_discovery import FiscalDiscovery
from .fiscal_focus_witness import (
    FiscalDiagnosticFocusWitnessOwner,
    SignedFiscalDiagnosticFocusWitnessV1,
)
from .fiscal_source_closure import FiscalArtifactRead, FiscalSourceClosure
from .fiscal_statement_mapping import (
    fiscal_display_profile_digest,
    fiscal_mapping_policy_digest,
    map_fiscal_primary_source,
)
from .fiscal_statement_registry import (
    fiscal_primary_scopes,
    fiscal_statement_registry,
    selected_fiscal_coverage,
)
from .fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationCompleteRefusedV1,
)
from .snapshots import ContentAddressedStore, SnapshotError
from .serialization import canonical_bytes, sha256_digest


@dataclass(frozen=True)
class FiscalClassificationSource:
    scope: FiscalSourceUseScopeV1
    evidence: FiscalOriginalValidationEvidenceV1
    witness: SignedFiscalDiagnosticFocusWitnessV1
    archive: bytes


class FiscalClassificationSourcePort(Protocol):
    def resolve(
        self,
        source_ref: ArtifactRefV1,
        witness_ref: ArtifactRefV1,
        security_id: str | None,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSource: ...


class FiscalClassificationSourceResolver:
    def __init__(
        self,
        *,
        sources: FiscalSourceClosure,
        discovery: FiscalDiscovery,
        witnesses: FiscalDiagnosticFocusWitnessOwner,
        content: ContentAddressedStore,
    ) -> None:
        self.sources = sources
        self.discovery = discovery
        self.witnesses = witnesses
        self.content = content

    def resolve(
        self,
        source_ref: ArtifactRefV1,
        witness_ref: ArtifactRefV1,
        security_id: str | None,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSource:
        def invalid(message: str) -> SnapshotError:
            return SnapshotError("FISCAL_CLASSIFICATION_INVALID", message)

        check_deadline()
        raw = read_retained_artifact(reader, source_ref)
        source = self.sources.read_with_metadata(
            source_ref.artifact_id, deadline_at=deadline_at
        )
        for identity, record in source.records:
            reader.expect(identity, record)
        evidence = source.evidence
        outcome = evidence.outcome
        if (
            source_ref.role != "fiscal-original-validation"
            or source_ref.media_type != "application/json"
            or raw != canonical_bytes(evidence.model_dump(mode="json"))
            or source_ref.artifact_id != evidence.artifact_id
            or not isinstance(outcome, FiscalValidationCompleteRefusedV1)
        ):
            raise invalid("classification requires exact complete raw-refused source")
        discovery_ref = evidence.request.selection.discovery_ref
        read_retained_artifact(reader, discovery_ref)
        discovery = self.discovery.read(
            discovery_ref.artifact_id, deadline_at=deadline_at
        )
        coverage = selected_fiscal_coverage(discovery)
        filing = evidence.request.filing
        if (
            filing.accession_number not in coverage.source_accessions
            or discovery.request.valuation_timestamp
            != evidence.request.valuation_timestamp
            or discovery.request.cik != filing.cik
        ):
            raise invalid("source is outside the reviewed discovery period set")
        if security_id is not None and security_id not in {
            fact.value.strip()
            for fact in outcome.claim.report.facts
            if fact.concept == "dei:TradingSymbol"
            and fact.entity_identifier == filing.cik
            and fact.entity_scheme == "http://www.sec.gov/CIK"
            and fact.namespace_uri is not None
            and fact.namespace_uri.startswith(
                ("http://xbrl.sec.gov/dei/", "http://xbrl.us/dei/")
            )
        }:
            raise invalid("security identifier is not disclosed for the source issuer")
        witness_raw = read_retained_artifact(reader, witness_ref)
        witness = self.witnesses.read(witness_ref.artifact_id, deadline_at=deadline_at)
        body = witness.witness
        if (
            witness_ref.role != "fiscal-diagnostic-focus-witness-v1"
            or witness_ref.media_type != "application/json"
            or canonical_bytes(witness) != witness_raw
            or witness.artifact_id != witness_ref.artifact_id
            or body.source_validation_ref != source_ref
            or body.runtime != outcome.runtime
            or body.cutoff != evidence.request.valuation_timestamp
            or body.filing != filing
            or body.raw_report_digest
            != sha256_digest(outcome.claim.report.model_dump(mode="json"))
            or tuple(
                sorted(
                    (
                        ref
                        for action in body.actions
                        for ref in (
                            action.result_ref,
                            action.report_ref,
                            action.delivery_ref,
                        )
                    ),
                    key=lambda ref: ref.artifact_id,
                )
            )
            != outcome.action_refs
        ):
            raise invalid("current witness differs from the exact source execution")
        for action in body.actions:
            for ref in (action.result_ref, action.report_ref, action.delivery_ref):
                read_retained_artifact(reader, ref)
        receipt = next(
            (
                item
                for item in outcome.responses
                if item.uri == outcome.integrity.archive_uri
            ),
            None,
        )
        if receipt is None:
            raise invalid("source archive receipt is missing")
        archive = self.content.get(receipt.content_hash, media_type=receipt.media_type)
        check_deadline()
        reviewed = next(
            (
                item
                for item in fiscal_primary_scopes(fiscal_statement_registry())
                if item.accession_number == filing.accession_number
            ),
            None,
        )
        if reviewed is None:
            raise invalid("source has no reviewed primary mapping")
        policy = fiscal_mapping_policy_digest()
        batch = map_fiscal_primary_source(
            evidence,
            source_ref,
            archive=archive,
            reviewed=reviewed,
            target_periods=tuple(item.period for item in coverage.quarters),
            security_id=security_id,
            policy_digest=policy,
            check_deadline=check_deadline,
        )
        scope = FiscalSourceUseScopeV1(
            source_validation_ref=source_ref,
            validation_kind="complete_refused",
            source_binding_digest=batch.source_binding_digest,
            issuer_id=filing.cik,
            accession_number=filing.accession_number,
            cutoff_at=discovery.request.valuation_timestamp,
            runtime=outcome.runtime,
            raw_report_digest=sha256_digest(
                outcome.claim.report.model_dump(mode="json")
            ),
            parser_action_refs=outcome.action_refs,
            witness_ref=witness_ref,
            display_profile_digest=fiscal_display_profile_digest(),
            mapping_policy_digest=policy,
            permitted_inputs=batch.observations,
        )
        check_deadline()
        return FiscalClassificationSource(scope, evidence, witness, archive)
