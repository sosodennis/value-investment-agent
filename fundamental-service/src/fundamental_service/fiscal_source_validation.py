from __future__ import annotations

import re
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from importlib.metadata import version
from io import BytesIO
from typing import TYPE_CHECKING, Literal

from lxml import etree

from .annual_discovery_service import AnnualDiscoveryArtifacts
from .arelle_parser import (
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationProfileV1,
)
from .artifact_evidence import EvidenceArtifactReader
from .command_artifacts import EvidenceArtifactStore
from .data_releases import ArtifactRefV1
from .dqc_applicability import DqcFilingContextV1, dqc_applicability_policy_digest
from .dqc_rulesets import DQC_V18_PROFILE_ID, DQC_V18_RULESETS
from .fiscal_parser_evidence import (
    FiscalParserRuntimeRead,
    RetainedFiscalActions,
    RetainedFiscalValidation,
    read_fiscal_parser_actions,
    read_fiscal_rejection,
    bind_fiscal_retained_inputs,
)
from .fiscal_source_closure import (
    FiscalSourceContentRead,
    FiscalSourceValidationRead,
    FiscalSourceContentReadSet,
)
from .fiscal_source_contracts import FiscalOriginalSourceV1, evaluate_fiscal_issuer
from .fiscal_validation_contracts import (
    FiscalValidationCompleteRefusedV1,
    FiscalValidationIncompleteV1,
    FiscalValidationMatchedV1,
    FiscalValidationOutcomeV1,
    FiscalValidationPinV1,
    FiscalValidationRuntimeV1,
    FiscalRetainedInputBindingV1,
    FiscalOriginalValidationEvidenceV1,
    ResolvedFiscalValidationRequestV1,
)
from .ingestion import read_sec_xbrl_archive
from .operations import ServiceError
from .parser_action_identity import IncompleteParserClosure, ParserBuildChecks
from .regulatory_validation import bind_dqc_filing_context
from .replay import (
    ArtifactPublicationDeadlineExceeded,
    ArtifactPublicationV1,
    ArtifactRecordV1,
)
from .sec_capture import RetainedSecSourceAdapter
from .sec_source import SecSourceError
from .snapshots import CapturedSource, SnapshotError

if TYPE_CHECKING:
    from .source_acquisition import SecAcquisitionUseCase, _OriginalPackage


def resolve_fiscal_validation_profile(
    acquisition: SecAcquisitionUseCase, namespace: str
) -> ArelleValidationProfileV1:
    """Resolve the configured physical profile and full ruleset for a GAAP namespace."""
    profile = acquisition._profile_for_id(
        DQC_V18_PROFILE_ID
        if namespace in DQC_V18_RULESETS
        else "sec-efm-us-dqc-v31.0.3"
    )
    catalog = profile.dqc_ruleset_catalog
    if catalog is None:
        raise SnapshotError(
            "VALIDATION_RESOURCES_UNAVAILABLE",
            "fiscal validation requires a full taxonomy ruleset catalog",
            retryable=True,
        )
    try:
        binding = catalog.select((namespace,))
    except ValueError as error:
        raise SnapshotError("DQC_TAXONOMY_RULESET_UNAVAILABLE", str(error)) from error
    return profile.model_copy(
        update={
            "dqc_ruleset_path": binding.path,
            "dqc_ruleset_sha256": binding.sha256,
        }
    )


def fiscal_validation_budget(deadline_at: datetime) -> float:
    if deadline_at.utcoffset() is None:
        remaining = 0.0
    else:
        remaining = (deadline_at - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise SecSourceError(
            "REQUEST_DEADLINE_EXCEEDED",
            "fiscal SEC validation deadline expired",
            retryable=True,
        )
    return remaining


@dataclass(frozen=True)
class _FiscalEvidencePublications:
    store: EvidenceArtifactStore
    budget: Callable[[], float]

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        self.budget()
        record = self.store.get(artifact_id)
        self.budget()
        return record

    def require_current_records(
        self,
        expected: tuple[tuple[str, ArtifactRecordV1 | None], ...],
        *,
        check_deadline: Callable[[], object],
    ) -> None:
        self.budget()
        self.store.require_current_records(expected, check_deadline=check_deadline)
        self.budget()

    def read(self, artifact_id: str) -> bytes:
        self.budget()
        raw = self.store.read(artifact_id)
        self.budget()
        return raw

    def read_bounded(self, artifact_id: str, *, maximum_bytes: int) -> bytes:
        self.budget()
        raw = self.store.read_bounded(artifact_id, maximum_bytes=maximum_bytes)
        self.budget()
        return raw

    def put_with_receipt(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
        publication_budget: Callable[[], float] | None = None,
    ) -> ArtifactPublicationV1:
        return self.store.put_with_receipt(
            artifact_id,
            value,
            dependency_hashes,
            media_type=media_type,
            retention=retention,
            publication_budget=publication_budget or self.budget,
        )

    def put_bytes_with_receipt(
        self,
        artifact_id: str,
        payload: bytes,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/octet-stream",
        retention: Literal["evidence", "operational_cache"] = "evidence",
        publication_budget: Callable[[], float] | None = None,
    ) -> ArtifactPublicationV1:
        return self.store.put_bytes_with_receipt(
            artifact_id,
            payload,
            dependency_hashes,
            media_type=media_type,
            retention=retention,
            publication_budget=publication_budget or self.budget,
        )


class SecFiscalSourceValidation:
    def __init__(
        self,
        acquisition: SecAcquisitionUseCase,
        *,
        pin: FiscalValidationPinV1,
        store: AnnualDiscoveryArtifacts,
    ) -> None:
        self.acquisition = acquisition
        self.pin = pin
        self.store = store

    def _profile(
        self, package: _OriginalPackage, archive_source: CapturedSource
    ) -> tuple[str, ArelleValidationProfileV1]:
        members = read_sec_xbrl_archive(
            archive_source.content,
            primary_document=package.xbrl_entrypoint,
            dts_filenames=package.dts_filenames,
            inline_documents=package.inline_documents,
        )
        namespaces: set[str] = set()
        gaap = re.compile(r"http://fasb\.org/us-gaap/20[0-9]{2}(?:-01-31)?")
        documents = package.inline_documents or (package.xbrl_entrypoint,)
        for filename in (*package.dts_filenames[:1], *documents):
            try:
                document = etree.parse(
                    BytesIO(members[filename]),
                    etree.XMLParser(
                        resolve_entities=False, no_network=True, huge_tree=True
                    ),
                )
            except etree.XMLSyntaxError as error:
                raise SnapshotError(
                    "FISCAL_TAXONOMY_NAMESPACE_INVALID", "fiscal XBRL could not be read"
                ) from error
            for element in document.iter():
                namespaces.update(
                    uri for uri in element.nsmap.values() if gaap.fullmatch(uri)
                )
                if element.tag == "{http://www.w3.org/2001/XMLSchema}import":
                    namespace = element.get("namespace", "")
                    if gaap.fullmatch(namespace):
                        namespaces.add(namespace)
        if len(namespaces) != 1:
            raise SnapshotError(
                "FISCAL_TAXONOMY_NAMESPACE_INVALID",
                "fiscal package has no unique US GAAP namespace",
            )
        namespace = next(iter(namespaces))
        return namespace, resolve_fiscal_validation_profile(self.acquisition, namespace)

    @staticmethod
    def _rejected_report(
        actions: RetainedFiscalActions, context: DqcFilingContextV1
    ) -> tuple[ArelleParseReportV1, tuple[str, ...]]:
        report = bind_dqc_filing_context(actions.normalized.report, context)
        archive = report
        if actions.archive is not None:
            archive = bind_dqc_filing_context(actions.archive.report, context)
            marker = next(
                value
                for value in archive.validation_evidence
                if value.startswith("sec-parser-action-v2:archive:")
            )
            report = report.model_copy(
                update={"validation_evidence": (*report.validation_evidence, marker)}
            )
        return report, tuple(sorted({report.replay_digest(), archive.replay_digest()}))

    def _collect(
        self,
        request: ResolvedFiscalValidationRequestV1,
        *,
        deadline_at: datetime,
        artifacts: EvidenceArtifactReader,
        retained: FiscalValidationMatchedV1
        | FiscalValidationCompleteRefusedV1
        | None = None,
        content_read: FiscalSourceContentRead | None = None,
        runtime_read: FiscalParserRuntimeRead | None = None,
    ) -> FiscalValidationMatchedV1 | FiscalValidationCompleteRefusedV1:
        check = partial(fiscal_validation_budget, deadline_at)
        check()
        publications = _FiscalEvidencePublications(self.store, check)
        owner = self.acquisition
        filing = request.filing
        if (
            request.pin != self.pin
            or self.pin.taxonomy_manifest_id != owner.settings.taxonomy_manifest_id
            or self.pin.taxonomy_cache_sha256 != owner.settings.taxonomy_cache_sha256
            or version("arelle-release") != "2.47.4"
        ):
            raise SnapshotError(
                "FISCAL_RUNTIME_PIN_MISMATCH", "fiscal runtime pins differ"
            )
        if (
            filing.accepted_at > request.valuation_timestamp
            or filing.filing_date > request.valuation_timestamp.date()
            or request.valuation_timestamp > datetime.now(UTC)
            or filing.filing_date.year not in owner.settings.supported_filing_years
            or filing.form not in owner.settings.supported_filing_forms
            or not filing.is_xbrl
            or filing.is_amendment
        ):
            raise SnapshotError(
                "FISCAL_FILING_NOT_ELIGIBLE",
                "fiscal original is unavailable at the cutoff or unsupported",
            )

        build_checks = ParserBuildChecks()
        build = build_checks.current()
        if owner.ingestion.parser_actions is None and retained is None:
            raise SnapshotError(
                "FISCAL_PARSER_ACTION_UNAVAILABLE",
                "fiscal validation requires persistent parser actions",
                retryable=True,
            )
        adapter = RetainedSecSourceAdapter(
            owner.adapter,
            scope=request.scope,
            receipts=self.store,
            content=content_read if content_read is not None else owner.content_store,
            capture_lock=owner._capture_lock,
            check_deadline=check,
            replay_reader=artifacts if retained is not None else None,
            publish_receipt=publications.put_with_receipt,
        )
        package = owner._capture_fiscal_package(
            adapter=adapter, filing=filing, deadline_at=deadline_at
        )
        primary_source = adapter.capture_filing(
            cik=filing.cik,
            accession_number=filing.accession_number,
            primary_document=package.xbrl_entrypoint,
            filed_at=filing.accepted_at,
            accepted_at=filing.accepted_at,
            form=filing.form,
            deadline_at=deadline_at,
        )
        captured_at = primary_source.captured_at
        if captured_at is None:
            raise SnapshotError(
                "SEC_CAPTURE_IDENTITY_MISMATCH", "missing capture timestamp"
            )
        archive = adapter.capture_filing_archive(
            cik=filing.cik,
            accession_number=filing.accession_number,
            filename=package.archive_filename,
            filed_at=filing.accepted_at,
            accepted_at=filing.accepted_at,
            form=filing.form,
            deadline_at=deadline_at,
        )
        check()
        namespace, profile = self._profile(package, archive)
        runtime = FiscalValidationRuntimeV1(
            pin=self.pin,
            taxonomy_version=f"us-gaap-{namespace.rsplit('/', 1)[1][:4]}",
            dqc_namespace=namespace,
            validation_profile_id=profile.profile_id,
            validation_profile_digest=profile.digest(),
            delivery_revision=self.pin.declared_source_revision,
            parser_build=build,
        )
        check()
        actions = None
        if retained is not None:
            if retained.runtime != runtime:
                raise SnapshotError(
                    "FISCAL_RUNTIME_PIN_MISMATCH", "retained fiscal runtime differs"
                )
            actions = read_fiscal_parser_actions(
                retained.integrity.validation_evidence,
                relation=retained.integrity.integrity_relation,
                artifacts=artifacts,
                build_checks=build_checks,
                delivery_revision=runtime.delivery_revision,
            )
            if actions.refs != retained.action_refs:
                raise SnapshotError(
                    "FISCAL_VALIDATION_INVALID", "retained parser action edges differ"
                )
            if runtime_read is not None:
                actions = RetainedFiscalActions(
                    actions.normalized, actions.archive, runtime_read
                )
        rejection_ref = None
        try:
            validated = owner.ingestion.validate_filing(
                build_checks=build_checks,
                parser_delivery_revision=runtime.delivery_revision,
                source_adapter=adapter,
                cik=filing.cik,
                accession_number=filing.accession_number,
                primary_document=package.xbrl_entrypoint,
                filing_archive_filename=package.archive_filename,
                filed_at=filing.accepted_at,
                filing_date=filing.filing_date,
                accepted_at=filing.accepted_at,
                captured_at=captured_at,
                taxonomy_manifest_id=runtime.pin.taxonomy_manifest_id,
                taxonomy_version=runtime.taxonomy_version,
                taxonomy_cache_dir=owner.settings.taxonomy_cache_dir,
                reference_sources=(package.index_source,),
                submission_source=package.submission_source,
                dts_filenames=package.dts_filenames,
                inline_documents=package.inline_documents,
                profile=profile,
                form=filing.form,
                deadline_at=deadline_at,
                retained_fiscal=(
                    RetainedFiscalValidation(
                        artifacts,
                        content_read
                        if content_read is not None
                        else owner.content_store,
                        actions,
                    )
                    if actions is not None
                    else None
                ),
                fiscal_publications=publications if retained is None else None,
            )
        except SnapshotError as error:
            if error.code != "PARSER_VALIDATION_BLOCKED" or error.evidence_ref is None:
                raise
            rejection = read_fiscal_rejection(error.evidence_ref, artifacts=artifacts)
            integrity = rejection.integrity_evidence
            actions = actions or read_fiscal_parser_actions(
                integrity.validation_evidence,
                relation=integrity.integrity_relation,
                artifacts=artifacts,
                build_checks=build_checks,
                delivery_revision=runtime.delivery_revision,
            )
            context = DqcFilingContextV1(
                issuer_id=filing.cik,
                accession_number=filing.accession_number,
                filing_date=filing.filing_date,
                dqc_version="v18" if profile.dqc_version == "v18" else "v31.0.3",
                policy_digest=dqc_applicability_policy_digest(profile.dqc_version),
            )
            report, digests = self._rejected_report(actions, context)
            if digests != rejection.parser_replay_digests:
                raise SnapshotError(
                    "FISCAL_VALIDATION_INVALID", "ingestion rejection report differs"
                )
            record = artifacts.get(error.evidence_ref)
            rejection_ref = ArtifactRefV1(
                artifact_id=record.artifact_id,
                content_hash=record.content_hash,
                media_type=record.media_type,
                role="sec-ingestion-rejection",
            )
        else:
            report, integrity = validated.parser_report, validated.integrity_evidence
            actions = actions or read_fiscal_parser_actions(
                integrity.validation_evidence,
                relation=integrity.integrity_relation,
                artifacts=artifacts,
                build_checks=build_checks,
                delivery_revision=runtime.delivery_revision,
            )

        responses = adapter.observed_responses
        primary = next(
            (
                receipt
                for receipt in responses
                if receipt.uri == integrity.primary_document_uri
            ),
            None,
        )
        if (
            primary is None
            or report.taxonomy_cache_hash != self.pin.taxonomy_cache_sha256
        ):
            raise SnapshotError(
                "FISCAL_VALIDATION_INVALID",
                "fiscal source or taxonomy evidence differs",
            )
        claim = evaluate_fiscal_issuer(
            report,
            filing=filing,
            source=FiscalOriginalSourceV1(
                cik=filing.cik,
                accession_number=filing.accession_number,
                uri=primary.uri,
                content_hash=primary.content_hash,
                parser_input_hash=integrity.parser_input_hash,
                form=filing.form,
                available_at=filing.accepted_at,
                captured_at=primary.captured_at,
                http_status=primary.http_status,
            ),
            decision_at=request.valuation_timestamp,
            request_digest=request.digest,
        )
        build_checks.verify()
        check()
        if claim.status == "refused":
            return FiscalValidationCompleteRefusedV1(
                runtime=runtime,
                claim=claim,
                integrity=integrity,
                responses=responses,
                action_refs=actions.refs,
                issue_codes=claim.issue_codes,
                rejection_ref=rejection_ref,
            )
        return FiscalValidationMatchedV1(
            runtime=runtime,
            claim=claim,
            integrity=integrity,
            responses=responses,
            action_refs=actions.refs,
        )

    def validate(
        self, request: ResolvedFiscalValidationRequestV1, *, deadline_at: datetime
    ) -> FiscalValidationOutcomeV1:
        try:
            return self._collect(
                request,
                deadline_at=deadline_at,
                artifacts=_FiscalEvidencePublications(
                    self.store, partial(fiscal_validation_budget, deadline_at)
                ),
            )
        except ArtifactPublicationDeadlineExceeded as error:
            raise SecSourceError(error.code, error.message, retryable=True) from error
        except (IncompleteParserClosure, OSError) as error:
            raise SnapshotError(
                "FISCAL_PARSER_BUILD_UNAVAILABLE",
                "current parser build could not be verified",
            ) from error
        except (
            SecSourceError,
            SnapshotError,
            ServiceError,
            ArelleParserError,
        ) as error:
            fiscal_validation_budget(deadline_at)
            retryable = (
                error.code
                in {"PARSER_CONCURRENCY_EXHAUSTED", "PARSER_RESOURCE_EXHAUSTED"}
                if isinstance(error, ArelleParserError)
                else error.retryable
            )
            return FiscalValidationIncompleteV1(
                issue_codes=(error.code,), retryable=retryable
            )

    def verify(
        self,
        request: ResolvedFiscalValidationRequestV1,
        outcome: FiscalValidationOutcomeV1,
        *,
        artifacts: EvidenceArtifactReader,
        deadline_at: datetime,
    ) -> None:
        fiscal_validation_budget(deadline_at)
        if isinstance(outcome, FiscalValidationIncompleteV1):
            return
        try:
            replayed = self._collect(
                request, deadline_at=deadline_at, artifacts=artifacts, retained=outcome
            )
        except (IncompleteParserClosure, OSError) as error:
            raise SnapshotError(
                "FISCAL_PARSER_BUILD_UNAVAILABLE",
                "current parser build could not be verified",
            ) from error
        if replayed != outcome:
            raise SnapshotError(
                "FISCAL_VALIDATION_INVALID",
                "retained fiscal validation differs from source replay",
            )

    def observe(
        self,
        request: ResolvedFiscalValidationRequestV1,
        outcome: FiscalValidationOutcomeV1,
        *,
        artifacts: EvidenceArtifactReader,
        deadline_at: datetime,
    ) -> FiscalSourceValidationRead:
        if isinstance(outcome, FiscalValidationIncompleteV1):
            raise SnapshotError(
                "FISCAL_VALIDATION_INVALID",
                "source admission requires a complete replay",
            )
        content = FiscalSourceContentRead(
            self.acquisition.content_store,
            partial(fiscal_validation_budget, deadline_at),
        )
        runtime = FiscalParserRuntimeRead()
        observation = _FiscalValidationRead(
            self,
            request.model_copy(deep=True),
            outcome.runtime.model_copy(deep=True),
            content,
            runtime,
            deadline_at,
            outcome,
            artifacts,
        )
        try:
            replayed = self._collect(
                request,
                deadline_at=deadline_at,
                artifacts=artifacts,
                retained=outcome,
                content_read=content,
                runtime_read=runtime,
            )
        except (IncompleteParserClosure, OSError) as error:
            raise SnapshotError(
                "FISCAL_PARSER_BUILD_UNAVAILABLE",
                "current parser build could not be verified",
            ) from error
        if replayed != outcome:
            raise SnapshotError(
                "FISCAL_VALIDATION_INVALID",
                "retained fiscal validation differs from source replay",
            )
        observation.check_current()
        return observation

    def observe_current(
        self,
        request: ResolvedFiscalValidationRequestV1,
        outcome: FiscalValidationOutcomeV1,
        binding: FiscalRetainedInputBindingV1,
        *,
        artifacts: EvidenceArtifactReader,
        deadline_at: datetime,
    ) -> FiscalSourceValidationRead:
        if isinstance(outcome, FiscalValidationIncompleteV1):
            raise SnapshotError(
                "FISCAL_VALIDATION_INVALID",
                "current source requires complete validation",
            )
        owner, filing = self.acquisition, request.filing
        if (
            filing.accepted_at > request.valuation_timestamp
            or filing.filing_date > request.valuation_timestamp.date()
            or filing.filing_date.year not in owner.settings.supported_filing_years
            or filing.form not in owner.settings.supported_filing_forms
            or not filing.is_xbrl
            or filing.is_amendment
        ):
            raise SnapshotError(
                "FISCAL_FILING_NOT_ELIGIBLE",
                "current filing is unsupported or unavailable at cutoff",
            )
        content = FiscalSourceContentRead(
            owner.content_store, partial(fiscal_validation_budget, deadline_at)
        )
        runtime = FiscalParserRuntimeRead()
        profile = resolve_fiscal_validation_profile(
            owner, outcome.runtime.dqc_namespace
        )
        actions = read_fiscal_parser_actions(
            outcome.integrity.validation_evidence,
            relation=outcome.integrity.integrity_relation,
            artifacts=artifacts,
            build_checks=ParserBuildChecks(),
            delivery_revision=outcome.runtime.delivery_revision,
        )
        if actions.refs != outcome.action_refs:
            raise SnapshotError(
                "FISCAL_VALIDATION_INVALID", "current parser action edges differ"
            )
        for action in (actions.normalized, actions.archive):
            if action is not None:
                runtime.observe(
                    action.request,
                    profile,
                    owner.settings.taxonomy_cache_dir,
                    outcome.runtime.delivery_revision,
                )
        self._observe_current_content(
            request,
            outcome,
            actions,
            content,
            artifacts=artifacts,
            deadline_at=deadline_at,
        )
        if (
            isinstance(outcome, FiscalValidationCompleteRefusedV1)
            and outcome.rejection_ref is not None
        ):
            read_fiscal_rejection(
                outcome.rejection_ref.artifact_id, artifacts=artifacts
            )
        expected = bind_fiscal_retained_inputs(
            FiscalOriginalValidationEvidenceV1(request=request, outcome=outcome),
            binding.source_validation_ref,
            actions,
            content,
            actual_requests=tuple(
                item.request
                for item in (actions.normalized, actions.archive)
                if item is not None
            ),
        )
        if binding != expected:
            raise SnapshotError(
                "FISCAL_VALIDATION_INVALID",
                "retained input origins differ from the exact current source closure",
            )
        observation = _FiscalValidationRead(
            self,
            request,
            outcome.runtime,
            content,
            runtime,
            deadline_at,
            outcome,
            artifacts,
        )
        observation.check_current()
        return observation

    def _observe_current_content(
        self,
        request: ResolvedFiscalValidationRequestV1,
        outcome: FiscalValidationMatchedV1 | FiscalValidationCompleteRefusedV1,
        actions: RetainedFiscalActions,
        content: FiscalSourceContentRead,
        *,
        artifacts: EvidenceArtifactReader,
        deadline_at: datetime,
    ) -> None:
        for receipt in outcome.responses:
            content.get(receipt.content_hash, media_type=receipt.media_type)
        primary = next(
            item
            for item in outcome.responses
            if item.uri == outcome.integrity.primary_document_uri
        )
        for digest in {
            outcome.integrity.normalized_content_hash,
            outcome.integrity.archive_member_hash,
        }:
            content.get(digest, media_type=primary.media_type)
        if outcome.integrity.inline_documents:
            content.get(
                outcome.integrity.parser_input_hash, media_type="application/json"
            )
        owner, filing = self.acquisition, request.filing
        adapter = RetainedSecSourceAdapter(
            owner.adapter,
            scope=request.scope,
            receipts=self.store,
            content=content,
            capture_lock=owner._capture_lock,
            check_deadline=partial(fiscal_validation_budget, deadline_at),
            replay_reader=artifacts,
        )
        package = owner._capture_fiscal_package(
            adapter=adapter, filing=filing, deadline_at=deadline_at
        )
        archive = adapter.capture_filing_archive(
            cik=filing.cik,
            accession_number=filing.accession_number,
            filename=package.archive_filename,
            filed_at=filing.accepted_at,
            accepted_at=filing.accepted_at,
            form=filing.form,
            deadline_at=deadline_at,
        )
        members = read_sec_xbrl_archive(
            archive.content,
            primary_document=package.xbrl_entrypoint,
            dts_filenames=package.dts_filenames,
            inline_documents=package.inline_documents,
        )
        retained = RetainedFiscalValidation(artifacts, content, actions)
        for filename in package.dts_filenames:
            retained.match_content(members[filename], media_type="application/xml")


class _FiscalValidationRead:
    def __init__(
        self,
        owner: SecFiscalSourceValidation,
        request: ResolvedFiscalValidationRequestV1,
        runtime: FiscalValidationRuntimeV1,
        content: FiscalSourceContentRead,
        parser: FiscalParserRuntimeRead,
        deadline_at: datetime,
        outcome: FiscalValidationMatchedV1 | FiscalValidationCompleteRefusedV1,
        artifacts: EvidenceArtifactReader,
    ) -> None:
        self._owner = owner
        self._request = request
        self._runtime = runtime
        self._content = content
        self._parser = parser
        self._deadline_at = deadline_at
        self._outcome = outcome
        self._artifacts = artifacts
        self._acquisition = owner.acquisition
        self._settings = deepcopy(owner.acquisition.settings)
        self._store = owner.store
        self._content_store = owner.acquisition.content_store
        self._adapter = owner.acquisition.adapter
        self._ingestion = owner.acquisition.ingestion

    def retained_input_binding(
        self, reference: ArtifactRefV1
    ) -> FiscalRetainedInputBindingV1:
        self.check_current()
        actions = read_fiscal_parser_actions(
            self._outcome.integrity.validation_evidence,
            relation=self._outcome.integrity.integrity_relation,
            artifacts=self._artifacts,
            build_checks=ParserBuildChecks(),
            delivery_revision=self._runtime.delivery_revision,
        )
        return bind_fiscal_retained_inputs(
            FiscalOriginalValidationEvidenceV1(
                request=self._request, outcome=self._outcome
            ),
            reference,
            actions,
            self._content,
            actual_requests=tuple(
                item.request
                for item in sorted(
                    self._parser.observations,
                    key=lambda item: item.request.representation,
                )
            ),
        )

    @property
    def input_footprint(self) -> tuple[object, ...]:
        return (
            self._content.input_footprint,
            self._parser.resources,
            tuple(
                (
                    item.request,
                    item.profile_json.hex(),
                    str(item.taxonomy_cache_dir),
                    item.delivery_revision,
                )
                for item in sorted(
                    self._parser.observations,
                    key=lambda item: item.request.representation,
                )
            ),
        )

    @property
    def content_readsets(self) -> tuple[FiscalSourceContentReadSet, ...]:
        return (self._content.readset,)

    def check_current(self) -> None:
        fiscal_validation_budget(self._deadline_at)
        owner = self._owner
        if (
            owner.acquisition is not self._acquisition
            or owner.acquisition.settings != self._settings
            or owner.store is not self._store
            or owner.acquisition.content_store is not self._content_store
            or owner.acquisition.adapter is not self._adapter
            or owner.acquisition.ingestion is not self._ingestion
            or owner.pin != self._request.pin
            or version("arelle-release") != "2.47.4"
            or self._request.valuation_timestamp > datetime.now(UTC)
        ):
            raise SnapshotError(
                "FISCAL_RUNTIME_PIN_MISMATCH", "fiscal source configuration changed"
            )
        try:
            profile = resolve_fiscal_validation_profile(
                owner.acquisition, self._runtime.dqc_namespace
            )
            current = self._runtime.model_copy(
                update={
                    "pin": owner.pin,
                    "validation_profile_id": profile.profile_id,
                    "validation_profile_digest": profile.digest(),
                    "delivery_revision": owner.pin.declared_source_revision,
                    "parser_build": ParserBuildChecks().current(),
                }
            )
            if current != self._runtime:
                raise SnapshotError(
                    "FISCAL_RUNTIME_PIN_MISMATCH", "retained fiscal runtime changed"
                )
            self._parser.check_current(
                profile,
                owner.acquisition.settings.taxonomy_cache_dir,
                current.delivery_revision,
            )
            self._content.check_current()
        except (IncompleteParserClosure, OSError) as error:
            raise SnapshotError(
                "FISCAL_PARSER_BUILD_UNAVAILABLE",
                "current parser build could not be verified",
            ) from error
        fiscal_validation_budget(self._deadline_at)
