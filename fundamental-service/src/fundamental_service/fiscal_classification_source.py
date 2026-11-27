from __future__ import annotations

import hashlib

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from copy import deepcopy

from .artifact_evidence import read_retained_artifact
from .data_releases import ArtifactRefV1
from .fiscal_candidate_contracts import FiscalSourceUseScopeV1
from .fiscal_discovery import FiscalDiscovery
from .fiscal_focus_witness import (
    FiscalDiagnosticFocusWitnessOwner,
    FiscalFocusWitnessRead,
    SignedFiscalDiagnosticFocusWitnessV1,
)
from .fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalSourceContentReadSet,
    FiscalSourceClosure,
    FiscalSourceContentRead,
    FiscalSourceRead,
)
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
    FiscalRetainedInputBindingV1,
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
    def _observe_current(
        self,
        scope: FiscalSourceUseScopeV1,
        binding: FiscalRetainedInputBindingV1,
        security_id: str | None,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSourceReadPort: ...

    def observe(
        self,
        source_ref: ArtifactRefV1,
        witness_ref: ArtifactRefV1,
        security_id: str | None,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSourceReadPort: ...

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


class FiscalClassificationSourceReadPort(Protocol):
    @property
    def content_readsets(self) -> tuple[FiscalSourceContentReadSet, ...]: ...

    @property
    def input_footprint(self) -> tuple[object, ...]: ...

    @property
    def witness_input_footprint(self) -> tuple[object, ...]: ...

    @property
    def source(self) -> FiscalClassificationSource: ...

    def check_current(self) -> None: ...


@dataclass(frozen=True)
class _ClassificationSourceRead:
    owner: FiscalClassificationSourceResolver
    sources: FiscalSourceClosure
    discovery: FiscalDiscovery
    witnesses: FiscalDiagnosticFocusWitnessOwner
    content_store: ContentAddressedStore
    source_read: FiscalSourceRead
    witness_read: FiscalFocusWitnessRead
    content: FiscalSourceContentRead
    reader: FiscalArtifactRead
    _source: FiscalClassificationSource
    registry_digest: str
    check_deadline: Callable[[], float]
    mapping_inputs: tuple[object, ...]

    @property
    def source(self) -> FiscalClassificationSource:
        return deepcopy(self._source)

    @property
    def content_readsets(self) -> tuple[FiscalSourceContentReadSet, ...]:
        return (
            self.content.readset,
            *self.source_read.content_readsets,
            *self.witness_read.content_readsets,
        )

    @property
    def input_footprint(self) -> tuple[object, ...]:
        return (
            self.reader.input_footprint,
            self.content.input_footprint,
            self._source.scope,
            self.source_read.input_footprint,
            self.mapping_inputs,
        )

    @property
    def witness_input_footprint(self) -> tuple[object, ...]:
        return self.witness_read.input_footprint

    def check_current(self) -> None:
        self.check_deadline()
        if (
            self.owner.sources is not self.sources
            or self.owner.discovery is not self.discovery
            or self.owner.witnesses is not self.witnesses
            or self.owner.content is not self.content_store
            or fiscal_mapping_policy_digest()
            != self._source.scope.mapping_policy_digest
            or fiscal_display_profile_digest()
            != self._source.scope.display_profile_digest
            or sha256_digest(fiscal_statement_registry()) != self.registry_digest
        ):
            raise SnapshotError(
                "FISCAL_CLASSIFICATION_INVALID", "source resolver configuration changed"
            )
        self.source_read.check_current()
        self.witness_read.check_current()
        self.content.check_current()
        self.reader.check_bodies()
        self.check_deadline()


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
        return self.observe(
            source_ref,
            witness_ref,
            security_id,
            reader=reader,
            check_deadline=check_deadline,
            deadline_at=deadline_at,
        ).source

    def observe(
        self,
        source_ref: ArtifactRefV1,
        witness_ref: ArtifactRefV1,
        security_id: str | None,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSourceReadPort:
        def invalid(message: str) -> SnapshotError:
            return SnapshotError("FISCAL_CLASSIFICATION_INVALID", message)

        check_deadline()
        reader = reader.for_consumer()
        raw = read_retained_artifact(reader, source_ref)
        sources, discovery_owner, witnesses, content_store = (
            self.sources,
            self.discovery,
            self.witnesses,
            self.content,
        )
        source = sources.observe(source_ref.artifact_id, deadline_at=deadline_at)
        reader.enroll(source.artifact_readset)
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
        discovery = discovery_owner.read(
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
        witness_read = witnesses.observe(
            witness_ref.artifact_id, deadline_at=deadline_at
        )
        reader.enroll(witness_read.artifact_readset)
        witness = witness_read.witness
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
        content = FiscalSourceContentRead(content_store, check_deadline)
        archive = content.get(receipt.content_hash, media_type=receipt.media_type)
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
        consumed_mapping_inputs: list[tuple[object, ...]] = []
        batch = map_fiscal_primary_source(
            evidence,
            source_ref,
            archive=archive,
            reviewed=reviewed,
            target_periods=tuple(item.period for item in coverage.quarters),
            security_id=security_id,
            policy_digest=policy,
            check_deadline=check_deadline,
            consume_inputs=consumed_mapping_inputs.append,
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
        return _ClassificationSourceRead(
            self,
            sources,
            discovery_owner,
            witnesses,
            content_store,
            source,
            witness_read,
            content,
            reader,
            FiscalClassificationSource(scope, evidence, witness, archive),
            sha256_digest(fiscal_statement_registry()),
            check_deadline,
            consumed_mapping_inputs[0],
        )

    def _observe_current(
        self,
        scope: FiscalSourceUseScopeV1,
        binding: FiscalRetainedInputBindingV1,
        security_id: str | None,
        *,
        reader: FiscalArtifactRead,
        check_deadline: Callable[[], float],
        deadline_at: datetime,
    ) -> FiscalClassificationSourceReadPort:
        source_ref, witness_ref = scope.source_validation_ref, scope.witness_ref
        if witness_ref is None:
            raise SnapshotError(
                "FISCAL_CLASSIFICATION_INVALID",
                "current classified source requires its witness",
            )

        def invalid(message: str) -> SnapshotError:
            return SnapshotError("FISCAL_CLASSIFICATION_INVALID", message)

        check_deadline()
        reader = reader.for_consumer()
        raw = read_retained_artifact(reader, source_ref)
        sources, discovery_owner, witnesses, content_store = (
            self.sources,
            self.discovery,
            self.witnesses,
            self.content,
        )
        source = sources._observe_current(
            source_ref.artifact_id, binding, deadline_at=deadline_at
        )
        reader.enroll(source.artifact_readset)
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
        discovery = discovery_owner.read_current(
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
        witness_read = witnesses._observe_current(
            witness_ref.artifact_id, binding, deadline_at=deadline_at
        )
        reader.enroll(witness_read.artifact_readset)
        witness = witness_read.witness
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
        content = FiscalSourceContentRead(content_store, check_deadline)
        archive = content.get(receipt.content_hash, media_type=receipt.media_type)
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
        if (
            scope.source_validation_ref != source_ref
            or scope.runtime != outcome.runtime
            or scope.issuer_id != filing.cik
            or scope.accession_number != filing.accession_number
            or scope.cutoff_at != discovery.request.valuation_timestamp
            or scope.raw_report_digest
            != sha256_digest(outcome.claim.report.model_dump(mode="json"))
            or scope.parser_action_refs != outcome.action_refs
            or scope.mapping_policy_digest != policy
            or scope.display_profile_digest != fiscal_display_profile_digest()
        ):
            raise invalid(
                "current resolver differs from the prepared exact source scope"
            )
        check_deadline()
        return _ClassificationSourceRead(
            self,
            sources,
            discovery_owner,
            witnesses,
            content_store,
            source,
            witness_read,
            content,
            reader,
            FiscalClassificationSource(scope, evidence, witness, archive),
            sha256_digest(fiscal_statement_registry()),
            check_deadline,
            (
                source_ref,
                sha256_digest(evidence.model_dump(mode="json")),
                hashlib.sha256(archive).hexdigest(),
                len(archive),
                reviewed,
                tuple(item.period for item in coverage.quarters),
                security_id,
                policy,
            ),
        )
