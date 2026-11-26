from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .arelle_parser import ArelleParseReportV1, ArelleValidationProfileV1
from .artifact_evidence import EvidenceArtifactReader
from .contracts import SecIngestionRejectionEvidenceV1
from .data_releases import ArtifactRefV1
from .parser_action_contracts import (
    ParserActionDeliveryV2,
    ParserActionInputV3,
    ParserActionResultV2,
    parser_action_markers,
)
from .parser_action_evidence import read_parser_action_result
from .parser_action_identity import (
    ParserBuildChecks,
    parser_action_input,
    parser_action_resources,
)
from .serialization import canonical_bytes
from .snapshots import ContentAddressedStore, SnapshotError


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_PARSER_ACTION_INVALID", message)


def read_fiscal_rejection(
    identity: str, *, artifacts: EvidenceArtifactReader
) -> SecIngestionRejectionEvidenceV1:
    record = artifacts.get(identity)
    raw = artifacts.read(identity)
    rejection = SecIngestionRejectionEvidenceV1.model_validate_json(raw)
    digest = hashlib.sha256(raw).hexdigest()
    integrity = rejection.integrity_evidence
    accession = integrity.accession_number.replace("-", "")
    if (
        identity != f"sec-ingestion-rejection-{accession}-{digest}"
        or record.artifact_id != identity
        or record.content_hash != digest
        or record.status != "valid"
        or record.retention != "evidence"
        or record.media_type != "application/json"
        or raw != canonical_bytes(rejection)
        or record.dependency_hashes
        != tuple(
            sorted(
                {
                    *(item.content_hash for item in rejection.captured_sources),
                    integrity.normalized_content_hash,
                    integrity.archive_member_hash,
                    integrity.validation_profile_digest,
                    integrity.taxonomy_manifest_hash,
                }
            )
        )
        or artifacts.get(identity) != record
    ):
        raise _invalid("retained ingestion rejection differs")
    return rejection


@dataclass(frozen=True)
class RetainedFiscalAction:
    report: ArelleParseReportV1
    request: ParserActionInputV3
    delivery: ParserActionDeliveryV2
    refs: tuple[ArtifactRefV1, ...]


@dataclass(frozen=True)
class ParserActionRuntimeObservation:
    request: ParserActionInputV3
    profile_json: bytes
    taxonomy_cache_dir: Path
    delivery_revision: str

    def check_current(
        self,
        profile: ArelleValidationProfileV1,
        taxonomy_cache_dir: Path,
        delivery_revision: str,
    ) -> None:
        _check_parser_runtime_current(
            (self,), profile, taxonomy_cache_dir, delivery_revision
        )


def _check_parser_runtime_current(
    observations: tuple[ParserActionRuntimeObservation, ...],
    profile: ArelleValidationProfileV1,
    taxonomy_cache_dir: Path,
    delivery_revision: str,
) -> None:
    if not observations:
        raise _invalid("retained source has no consumed parser runtime")
    profile_json = canonical_bytes(profile.model_dump(mode="json"))
    profile_digest = profile.digest()
    for observation in observations:
        if (
            profile_json != observation.profile_json
            or taxonomy_cache_dir != observation.taxonomy_cache_dir
            or delivery_revision != observation.delivery_revision
            or profile_digest != observation.request.profile_digest
        ):
            raise _invalid("retained parser runtime changed during source admission")
    resources = parser_action_resources(profile, taxonomy_cache_dir)
    build_checks = ParserBuildChecks()
    for observation in observations:
        if (
            resources.logical != observation.request.resources
            or build_checks.current() != observation.request.build
        ):
            raise _invalid("retained parser runtime changed during source admission")


@dataclass
class FiscalParserRuntimeRead:
    observations: list[ParserActionRuntimeObservation] = field(default_factory=list)

    def observe(
        self,
        request: ParserActionInputV3,
        profile: ArelleValidationProfileV1,
        taxonomy_cache_dir: Path,
        delivery_revision: str,
    ) -> None:
        self.observations.append(
            ParserActionRuntimeObservation(
                request.model_copy(deep=True),
                canonical_bytes(profile.model_dump(mode="json")),
                taxonomy_cache_dir,
                delivery_revision,
            )
        )

    def check_current(
        self,
        profile: ArelleValidationProfileV1,
        taxonomy_cache_dir: Path,
        delivery_revision: str,
    ) -> None:
        _check_parser_runtime_current(
            tuple(self.observations), profile, taxonomy_cache_dir, delivery_revision
        )


@dataclass(frozen=True)
class RetainedFiscalActions:
    normalized: RetainedFiscalAction
    archive: RetainedFiscalAction | None
    runtime_read: FiscalParserRuntimeRead | None = None

    @property
    def refs(self) -> tuple[ArtifactRefV1, ...]:
        refs = {
            ref.artifact_id: ref
            for action in (self.normalized, self.archive)
            if action is not None
            for ref in action.refs
        }
        return tuple(refs[key] for key in sorted(refs))

    def replay(
        self,
        path: Path,
        *,
        representation: Literal["normalized", "archive"],
        delivery_revision: str,
        normalization_inputs: tuple[str, ...],
        profile: ArelleValidationProfileV1,
        taxonomy_version: str,
        taxonomy_cache_dir: Path,
        source_content_hash: str,
        build_checks: ParserBuildChecks,
    ) -> ArelleParseReportV1:
        action = self.normalized if representation == "normalized" else self.archive
        if action is None:
            raise _invalid("retained parser representation is missing")
        expected = parser_action_input(
            path,
            representation=representation,
            delivery_revision=delivery_revision,
            normalization_inputs=normalization_inputs,
            profile=profile,
            taxonomy_version=taxonomy_version,
            taxonomy_cache_dir=taxonomy_cache_dir,
            source_content_hash=source_content_hash,
            build_checks=build_checks,
        )
        resources = dict(expected.resources)
        if (
            action.request != expected
            or action.delivery.delivery_revision != delivery_revision
            or resources.get("edgar") != profile.edgar_plugin_sha256
            or resources.get("xule") != profile.xule_plugin_sha256
            or profile.dqc_ruleset_catalog is None
            or profile.dqc_ruleset_path is None
            or resources.get(f"dqc-primary:{profile.dqc_ruleset_path.name}")
            != profile.dqc_ruleset_sha256
            or any(
                resources.get(
                    f"dqc-catalog:{binding.taxonomy_namespace}:{binding.path.name}"
                )
                != binding.sha256
                for binding in profile.dqc_ruleset_catalog.bindings
            )
        ):
            raise _invalid(
                "retained parser action differs from its staged inputs or resources"
            )
        if self.runtime_read is not None:
            if not isinstance(expected, ParserActionInputV3):
                raise _invalid("source admission requires complete parser runtime")
            self.runtime_read.observe(
                expected, profile, taxonomy_cache_dir, delivery_revision
            )
        return action.report


@dataclass(frozen=True)
class RetainedFiscalValidation:
    artifacts: EvidenceArtifactReader
    content: ContentAddressedStore
    actions: RetainedFiscalActions

    def match_content(self, content: bytes, *, media_type: str) -> str:
        digest = hashlib.sha256(content).hexdigest()
        if self.content.get(digest, media_type=media_type) != content:
            raise _invalid("retained SEC filing input bytes differ")
        return digest

    def match_rejection(
        self, identity: str, rejection: SecIngestionRejectionEvidenceV1
    ) -> None:
        if read_fiscal_rejection(identity, artifacts=self.artifacts) != rejection:
            raise _invalid("retained SEC filing rejection differs")


def read_fiscal_parser_actions(
    evidence: tuple[str, ...],
    *,
    relation: Literal["exact", "normalized"],
    artifacts: EvidenceArtifactReader,
    build_checks: ParserBuildChecks,
    delivery_revision: str,
) -> RetainedFiscalActions:
    try:
        markers = parser_action_markers(evidence)
    except ValueError as error:
        raise _invalid("invalid parser action markers") from error
    expected = {"normalized", "archive"} if relation == "normalized" else {"normalized"}
    if {item[1] for item in markers} != expected:
        raise _invalid("complete parser actions are required")
    current = build_checks.current()
    actions = {}
    for version, representation, key, digest, binding_digest in markers:
        if version != "v2" or binding_digest is None:
            raise _invalid("fiscal validation requires current parser action delivery")
        result_role = "sec-parser-action-result-v2"
        result_id = f"{result_role}:{key}:{digest}"
        report, result, record = read_parser_action_result(
            result_id, artifacts=artifacts
        )
        if (
            record.artifact_id != result_id
            or not isinstance(result, ParserActionResultV2)
            or not isinstance(result.request, ParserActionInputV3)
            or result.request.build != current
            or result.request.digest != key
            or result.request.representation != representation
        ):
            raise _invalid(
                "retained parser result differs from current build or representation"
            )
        delivery_role = "sec-parser-action-delivery-v2"
        delivery_id = f"{delivery_role}:{binding_digest}"
        delivery_record = artifacts.get(delivery_id)
        raw = artifacts.read(delivery_id)
        delivery = ParserActionDeliveryV2.model_validate_json(raw)
        if (
            delivery
            != ParserActionDeliveryV2(
                action_key=key,
                result_artifact_id=result_id,
                report_content_hash=result.report_content_hash,
                delivery_revision=delivery_revision,
                build=current,
            )
            or raw != canonical_bytes(delivery)
            or hashlib.sha256(raw).hexdigest() != binding_digest
            or delivery_record.artifact_id != delivery_id
            or delivery_record.content_hash != binding_digest
            or delivery_record.media_type != "application/json"
            or delivery_record.status != "valid"
            or delivery_record.retention != "evidence"
            or delivery_record.dependency_hashes
            != tuple(sorted({key, result.report_content_hash, digest}))
            or artifacts.get(delivery_id) != delivery_record
        ):
            raise _invalid("retained parser delivery differs")
        body_role = "sec-parser-action-report-v1"
        body_id = f"{body_role}:{result.report_content_hash}"
        body = artifacts.get(body_id)
        if (
            body.artifact_id != body_id
            or body.content_hash != result.report_content_hash
            or body.media_type != "application/json"
            or body.status != "valid"
            or body.retention != "evidence"
            or body.dependency_hashes
        ):
            raise _invalid("retained parser body differs")
        actions[representation] = RetainedFiscalAction(
            report=report.model_copy(
                update={
                    "validation_evidence": (
                        *report.validation_evidence,
                        result.evidence_marker(binding_digest),
                    )
                }
            ),
            request=result.request,
            delivery=delivery,
            refs=tuple(
                ArtifactRefV1(
                    artifact_id=item.artifact_id,
                    role=role,
                    content_hash=item.content_hash,
                    media_type=item.media_type,
                )
                for item, role in (
                    (record, result_role),
                    (body, body_role),
                    (delivery_record, delivery_role),
                )
            ),
        )
    build_checks.verify()
    return RetainedFiscalActions(actions["normalized"], actions.get("archive"))
