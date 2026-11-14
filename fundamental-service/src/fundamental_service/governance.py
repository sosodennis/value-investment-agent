"""Immutable model release evidence and fail-closed promotion lifecycle."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .calibration import CalibrationArtifactV1
from .policies import ModelSpecV1
from .public_source_catalog import PUBLIC_SOURCE_SPECS
from .sec_source import SEC_TERMS
from .serialization import canonical_bytes, sha256_digest


class ModelEvidenceArtifactV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: Literal[
        "public_source",
        "positive_golden",
        "negative_golden",
        "challenger_report",
        "quality_gate_report",
        "calibration_report",
        "replay_report",
        "verification_attestation",
        "monitoring_plan",
        "release_manifest",
        "rollback_manifest",
    ]
    source_id: str | None = None
    source_uri: str | None = None
    terms_reference: str | None = None
    available_at: datetime | None = None
    captured_at: datetime | None = None

    @field_validator("available_at", "captured_at")
    @classmethod
    def source_times_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("source evidence timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def source_identity(self) -> ModelEvidenceArtifactV1:
        if (self.role == "public_source") != (self.source_id is not None):
            raise ValueError("only public-source evidence must identify a source_id")
        source_fields = (
            self.source_uri,
            self.terms_reference,
            self.available_at,
            self.captured_at,
        )
        if self.role == "public_source" and any(
            value is None for value in source_fields
        ):
            raise ValueError(
                "public-source evidence requires URI, terms, and timestamps"
            )
        if self.role != "public_source" and any(
            value is not None for value in source_fields
        ):
            raise ValueError("non-source artifacts cannot contain source metadata")
        if (
            self.available_at is not None
            and self.captured_at is not None
            and self.available_at > self.captured_at
        ):
            raise ValueError("source evidence cannot be captured before publication")
        return self


class ModelReleaseEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    source_ids: tuple[str, ...] = Field(min_length=1)
    artifacts: tuple[ModelEvidenceArtifactV1, ...] = Field(min_length=10)
    calibration_training_end: datetime
    calibration_oos_start: datetime
    calibration_oos_end: datetime
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    expires_at: datetime
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "approved_at",
        "expires_at",
        "calibration_training_end",
        "calibration_oos_start",
        "calibration_oos_end",
    )
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("release evidence timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_evidence(self) -> ModelReleaseEvidenceV1:
        if self.expires_at <= self.approved_at:
            raise ValueError("model release evidence must expire after approval")
        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("model release evidence artifact IDs must be unique")
        roles: list[str] = [artifact.role for artifact in self.artifacts]
        required_roles = {
            "positive_golden",
            "negative_golden",
            "challenger_report",
            "quality_gate_report",
            "replay_report",
            "verification_attestation",
            "monitoring_plan",
            "release_manifest",
            "rollback_manifest",
        }
        if not required_roles <= set(roles):
            raise ValueError("model release evidence is missing a required artifact")
        if any(roles.count(role) != 1 for role in required_roles):
            raise ValueError(
                "model release evidence must contain one of each gate artifact"
            )
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("model release source IDs must be unique")
        if not (
            self.calibration_training_end
            < self.calibration_oos_start
            <= self.calibration_oos_end
            < self.approved_at
        ):
            raise ValueError(
                "calibration evidence must be chronologically out of sample"
            )
        evidence_sources = {
            item.source_id for item in self.artifacts if item.role == "public_source"
        }
        if evidence_sources != set(self.source_ids):
            raise ValueError("release evidence must hash every declared public source")
        if self.evidence_digest != sha256_digest(
            self.model_dump(exclude={"evidence_digest"})
        ):
            raise ValueError("evidence_digest does not match release evidence")
        return self

    def artifact(self, role: str) -> ModelEvidenceArtifactV1 | None:
        return next((item for item in self.artifacts if item.role == role), None)


class ReleaseArtifactAttestationV1(BaseModel):
    """Structured, model-bound evidence instead of opaque role-name claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    role: Literal[
        "positive_golden",
        "negative_golden",
        "challenger_report",
        "replay_report",
        "monitoring_plan",
        "release_manifest",
        "rollback_manifest",
    ]
    assertions: dict[str, bool]
    metrics: dict[str, int | float | str | bool]
    artifact_hashes: dict[str, str] = Field(default_factory=dict)


class ReleaseVerificationAttestationV1(BaseModel):
    """Trusted CI statement binding executed gates to exact release inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_subject_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    verification_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_run_id: str = Field(min_length=1)
    workflow_identity: str = Field(min_length=1)
    verifier_id: str = Field(min_length=1)
    passed_gate_ids: tuple[str, ...] = Field(min_length=1)
    artifact_hashes: dict[str, str]
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @field_validator("artifact_hashes")
    @classmethod
    def artifact_digests_are_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in value.values()):
            raise ValueError("verification artifact hashes must be SHA-256 digests")
        return value

    @field_validator("passed_gate_ids")
    @classmethod
    def gate_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("verification gate IDs must be unique")
        return value

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(exclude={"signature"}))


@dataclass(frozen=True)
class TrustedReleaseVerifier:
    workflow_identity: str
    public_key: bytes
    expected_source_revision: str
    expected_verification_suite_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.workflow_identity, str)
            or not self.workflow_identity.strip()
        ):
            raise ValueError("trusted verifier workflow identity is required")
        if not isinstance(self.expected_source_revision, str) or not re.fullmatch(
            r"[0-9a-f]{40}", self.expected_source_revision
        ):
            raise ValueError("trusted verifier source revision must be a commit SHA")
        if not isinstance(
            self.expected_verification_suite_sha256, str
        ) or not re.fullmatch(r"[0-9a-f]{64}", self.expected_verification_suite_sha256):
            raise ValueError("trusted verifier suite digest must be a SHA-256 digest")
        if not isinstance(self.public_key, bytes):
            raise TypeError("trusted verifier public key must be raw bytes")
        Ed25519PublicKey.from_public_bytes(self.public_key)


class DeploymentReleaseVerifierV1(BaseModel):
    """Public deployment pins for one trusted release workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_identity: str = Field(min_length=1)
    public_key_ed25519_base64: str = Field(min_length=1)
    expected_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_verification_suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("public_key_ed25519_base64")
    @classmethod
    def public_key_is_ed25519(cls, value: str) -> str:
        try:
            public_key = base64.b64decode(value, validate=True)
            Ed25519PublicKey.from_public_bytes(public_key)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                "deployment trust root must be a raw Ed25519 public key"
            ) from exc
        return value

    def trusted_verifier(self) -> TrustedReleaseVerifier:
        return TrustedReleaseVerifier(
            workflow_identity=self.workflow_identity,
            public_key=base64.b64decode(self.public_key_ed25519_base64, validate=True),
            expected_source_revision=self.expected_source_revision,
            expected_verification_suite_sha256=self.expected_verification_suite_sha256,
        )


class ModelTrustRootsV1(BaseModel):
    """Deployment-owned public trust roots and exact release pins."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verifiers: dict[str, DeploymentReleaseVerifierV1] = Field(min_length=1)

    @field_validator("verifiers")
    @classmethod
    def verifier_ids_are_valid(
        cls, value: dict[str, DeploymentReleaseVerifierV1]
    ) -> dict[str, DeploymentReleaseVerifierV1]:
        if any(not verifier_id.strip() for verifier_id in value):
            raise ValueError("deployment trust root verifier IDs cannot be empty")
        return value


def sign_release_verification(
    payload: Mapping[str, object], private_key: Ed25519PrivateKey
) -> ReleaseVerificationAttestationV1:
    """Create a signed verification statement in the trusted release workflow."""

    unsigned = ReleaseVerificationAttestationV1.model_validate(
        {**payload, "signature": "0" * 128}
    )
    signature = private_key.sign(unsigned.signing_bytes()).hex()
    return unsigned.model_copy(update={"signature": signature})


def release_subject_digest(
    model: ModelSpecV1,
    *,
    source_ids: tuple[str, ...],
    artifacts: tuple[ModelEvidenceArtifactV1, ...],
    calibration_training_end: datetime,
    calibration_oos_start: datetime,
    calibration_oos_end: datetime,
    approved_by: str,
    approved_at: datetime,
    expires_at: datetime,
) -> str:
    """Digest all release inputs except the verifier statement itself."""

    return sha256_digest(
        {
            "contract_version": "fundamental.v1",
            "model_sha256": sha256_digest(model),
            "source_ids": source_ids,
            "artifacts": tuple(
                sorted(
                    (
                        artifact.model_dump()
                        for artifact in artifacts
                        if artifact.role != "verification_attestation"
                    ),
                    key=lambda item: item["artifact_id"],
                )
            ),
            "calibration_training_end": calibration_training_end,
            "calibration_oos_start": calibration_oos_start,
            "calibration_oos_end": calibration_oos_end,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "expires_at": expires_at,
        }
    )


class ReleaseGateEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: Literal[True]
    artifact_ids: tuple[str, ...] = Field(min_length=1)


class ReleaseGateReportV1(BaseModel):
    """Complete gate report whose references resolve to hashed release inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    gates: dict[str, ReleaseGateEvidenceV1]


class ModelInventory:
    """Immutable model records with evidence-gated active release pointers."""

    def __init__(
        self,
        models: Iterable[ModelSpecV1] = (),
        *,
        trusted_verifiers: Mapping[str, TrustedReleaseVerifier] | None = None,
    ) -> None:
        self._models: dict[tuple[str, str], ModelSpecV1] = {}
        self._evidence: dict[tuple[str, str], ModelReleaseEvidenceV1] = {}
        self._active: dict[str, str] = {}
        self._trusted_verifiers = dict(trusted_verifiers or {})
        if any(
            not isinstance(verifier, TrustedReleaseVerifier)
            for verifier in self._trusted_verifiers.values()
        ):
            raise ValueError("trusted verifier configuration is invalid")
        for model in models:
            self.register(model)

    @classmethod
    def from_deployment_file(
        cls,
        models: Iterable[ModelSpecV1],
        trust_roots_file: Path | None,
    ) -> ModelInventory:
        """Load verifier identities and public keys from deployment config."""

        if trust_roots_file is None:
            return cls(models)
        trust_roots = ModelTrustRootsV1.model_validate_json(
            trust_roots_file.read_bytes()
        )
        return cls(
            models,
            trusted_verifiers={
                verifier_id: verifier.trusted_verifier()
                for verifier_id, verifier in trust_roots.verifiers.items()
            },
        )

    @property
    def trust_roots_configured(self) -> bool:
        return bool(self._trusted_verifiers)

    def register(self, model: ModelSpecV1) -> None:
        if model.lifecycle == "active":
            raise ValueError(
                "active models must enter through evidence-gated promotion"
            )
        key = (model.model_id, model.model_version)
        existing = self._models.get(key)
        if existing is not None and existing != model:
            raise ValueError("model definition is immutable")
        self._models[key] = model

    def promote(
        self,
        model: ModelSpecV1,
        evidence: ModelReleaseEvidenceV1,
        *,
        artifact_bytes: Mapping[str, bytes],
        at: datetime | None = None,
    ) -> ModelSpecV1:
        key = (model.model_id, model.model_version)
        registered = self._models.get(key)
        if registered is None or registered != model:
            raise ValueError("promotion requires the immutable registered model")
        if key != (evidence.model_id, evidence.model_version):
            raise ValueError("release evidence does not match model")
        if set(evidence.source_ids) != set(model.source_register):
            raise ValueError("release evidence must match the complete source register")
        calibration_reports = tuple(
            artifact
            for artifact in evidence.artifacts
            if artifact.role == "calibration_report"
        )
        if model.calibration_required_for_promotion and not calibration_reports:
            raise ValueError(
                "model promotion requires out-of-sample calibration evidence"
            )
        artifacts_by_id = {item.artifact_id: item for item in evidence.artifacts}
        if len(artifacts_by_id) != len(evidence.artifacts):
            raise ValueError("release evidence artifact IDs must be unique")
        for artifact in evidence.artifacts:
            payload = artifact_bytes.get(artifact.artifact_id)
            if payload is None or sha256(payload).hexdigest() != artifact.sha256:
                raise ValueError(
                    f"release artifact {artifact.artifact_id} is missing or has "
                    "a hash mismatch"
                )
            if artifact.role == "public_source":
                spec = next(
                    (
                        item
                        for item in PUBLIC_SOURCE_SPECS
                        if item.source_id == artifact.source_id
                    ),
                    None,
                )
                sec_source = artifact.source_id in {
                    "sec-companyfacts",
                    "sec-submissions",
                    "sec-filing",
                    "sec-filing-archive",
                    "sec-taxonomy",
                }
                if (
                    spec is None and not sec_source
                ) or artifact.source_id not in model.source_register:
                    raise ValueError(
                        "release evidence contains an unregistered public source"
                    )
                observed = urlsplit(artifact.source_uri or "")
                allowed = urlsplit(spec.uri_prefix) if spec is not None else None
                sec_prefixes = {
                    "sec-companyfacts": ("data.sec.gov", "/api/xbrl/companyfacts/"),
                    "sec-submissions": ("data.sec.gov", "/submissions/"),
                    "sec-filing": ("www.sec.gov", "/Archives/edgar/data/"),
                    "sec-filing-archive": (
                        "www.sec.gov",
                        "/Archives/edgar/data/",
                    ),
                    "sec-taxonomy": ("www.sec.gov", "/Archives/edgar/data/"),
                }
                if sec_source:
                    expected_host, expected_path = sec_prefixes[artifact.source_id]
                    host_allowed = observed.hostname == expected_host
                    path_allowed = observed.path.startswith(expected_path)
                    expected_terms = SEC_TERMS
                else:
                    assert spec is not None
                    host_allowed = (
                        allowed is not None and observed.hostname == allowed.hostname
                    )
                    path_allowed = allowed is not None and observed.path.startswith(
                        allowed.path
                    )
                    expected_terms = spec.terms_reference
                if (
                    observed.scheme != "https"
                    or not host_allowed
                    or not path_allowed
                    or observed.port is not None
                    or observed.username is not None
                    or observed.password is not None
                    or bool(observed.fragment)
                    or artifact.terms_reference != expected_terms
                ):
                    raise ValueError(
                        "release evidence source URI or legal terms do not match "
                        "register"
                    )
                assert artifact.available_at is not None
                assert artifact.captured_at is not None
                if artifact.available_at > artifact.captured_at:
                    raise ValueError(
                        "public-source artifact has invalid point-in-time ordering"
                    )
            elif artifact.role == "calibration_report":
                # Parsed and checked against its target and OOS window below.
                continue
            elif artifact.role == "quality_gate_report":
                report = ReleaseGateReportV1.model_validate_json(payload)
                if (report.model_id, report.model_version) != key:
                    raise ValueError("quality gate report does not match model version")
                if set(report.gates) != set(model.required_release_gates):
                    raise ValueError(
                        "quality gate report must cover every required gate"
                    )
                gate_roles = {
                    "public-source-coverage": {"public_source"},
                    "point-in-time-accounting": {"public_source", "positive_golden"},
                    "positive-negative-golden-cohorts": {
                        "positive_golden",
                        "negative_golden",
                    },
                    "independent-node-challenger": {"challenger_report"},
                    "calibration-oos": {"calibration_report"},
                    "replay-reproducibility": {"replay_report"},
                }
                if set(model.required_release_gates) != set(gate_roles):
                    raise ValueError("model declares an unsupported release gate")
                for gate_id, gate_evidence in report.gates.items():
                    if not set(gate_evidence.artifact_ids) <= set(artifacts_by_id):
                        raise ValueError(
                            f"quality gate {gate_id} references missing evidence"
                        )
                for gate_id, required_roles in gate_roles.items():
                    gate = report.gates.get(gate_id)
                    if gate is None:
                        continue
                    cited_roles = {
                        artifacts_by_id[item_id].role for item_id in gate.artifact_ids
                    }
                    if not required_roles <= cited_roles:
                        raise ValueError(
                            f"quality gate {gate_id} lacks required evidence"
                        )
                    if gate_id == "public-source-coverage":
                        cited_sources = {
                            artifacts_by_id[item_id].source_id
                            for item_id in gate.artifact_ids
                            if artifacts_by_id[item_id].role == "public_source"
                        }
                        if cited_sources != set(model.source_register):
                            raise ValueError(
                                "public-source gate must cite the complete source "
                                "register"
                            )
                    if gate_id == "calibration-oos":
                        cited_targets = {
                            CalibrationArtifactV1.model_validate_json(
                                artifact_bytes[item_id]
                            ).target
                            for item_id in gate.artifact_ids
                            if artifacts_by_id[item_id].role == "calibration_report"
                        }
                        if cited_targets != set(model.calibration_targets):
                            raise ValueError(
                                "calibration gate must cite every declared target"
                            )
            elif artifact.role == "verification_attestation":
                continue
            else:
                attestation = ReleaseArtifactAttestationV1.model_validate_json(payload)
                if (attestation.model_id, attestation.model_version) != key:
                    raise ValueError(f"{artifact.role} does not match model version")
                if attestation.role != artifact.role:
                    raise ValueError(f"{artifact.role} has a mismatched evidence role")
                requirements: dict[str, tuple[tuple[str, ...], dict[str, int]]] = {
                    "positive_golden": (("all_cases_passed",), {"case_count": 1}),
                    "negative_golden": (
                        ("all_cases_passed", "expected_abstentions_verified"),
                        {"case_count": 1},
                    ),
                    "challenger_report": (
                        ("independent_implementation", "all_nodes_match"),
                        {"checked_node_count": 1, "mismatch_count": 0},
                    ),
                    "replay_report": (
                        ("offline_replay_reproduced",),
                        {"cohort_count": 1},
                    ),
                    "monitoring_plan": (
                        ("named_owner", "alerts_defined", "expiry_reviewed"),
                        {"review_interval_days": 1},
                    ),
                    "rollback_manifest": (
                        ("rollback_target_defined", "replay_before_reenable"),
                        {},
                    ),
                    "release_manifest": (("all_gates_complete",), {}),
                }
                required_assertions, minimum_metrics = requirements[artifact.role]
                if any(
                    attestation.assertions.get(name) is not True
                    for name in required_assertions
                ):
                    raise ValueError(
                        f"{artifact.role} does not pass its required assertions"
                    )
                for name, minimum in minimum_metrics.items():
                    metric = attestation.metrics.get(name)
                    if (
                        not isinstance(metric, int)
                        or isinstance(metric, bool)
                        or metric < minimum
                    ):
                        raise ValueError(
                            f"{artifact.role} is missing required cohort or node counts"
                        )
                if artifact.role == "negative_golden":
                    abstention_count = attestation.metrics.get(
                        "expected_abstention_count"
                    )
                    if not isinstance(abstention_count, int):
                        raise ValueError(
                            "negative golden evidence requires abstention counts"
                        )
                    if abstention_count <= 0:
                        raise ValueError(
                            "negative golden evidence requires abstention cases"
                        )
                if (
                    artifact.role == "challenger_report"
                    and attestation.metrics.get("mismatch_count") != 0
                ):
                    raise ValueError("independent challenger reported node mismatches")
                owner = attestation.metrics.get("owner")
                if artifact.role == "monitoring_plan" and not (
                    isinstance(owner, str) and owner.strip()
                ):
                    raise ValueError(
                        "monitoring plan must identify its accountable owner"
                    )
                rollback_target = attestation.metrics.get("rollback_target_release")
                if artifact.role == "rollback_manifest" and not (
                    isinstance(rollback_target, str) and rollback_target.strip()
                ):
                    raise ValueError(
                        "rollback manifest must name a prior release or unsupported "
                        "state"
                    )
                if artifact.role == "release_manifest":
                    expected_hashes = {
                        item.artifact_id: item.sha256
                        for item in evidence.artifacts
                        if item.role
                        not in {"release_manifest", "verification_attestation"}
                    }
                    if attestation.artifact_hashes != expected_hashes:
                        raise ValueError(
                            "release manifest must bind every evidence artifact hash"
                        )
        if evidence.approved_by != model.independent_validator:
            raise ValueError(
                "model promotion requires approval by its independent validator"
            )
        if model.calibration_required_for_promotion:
            if not calibration_reports:  # pragma: no cover - guarded above
                raise ValueError(
                    "model promotion requires out-of-sample calibration evidence"
                )
            reported_targets: set[str] = set()
            for report_artifact in calibration_reports:
                calibration = CalibrationArtifactV1.model_validate_json(
                    artifact_bytes.get(report_artifact.artifact_id, b"")
                )
                if (
                    calibration.model_id != model.model_id
                    or calibration.target not in model.calibration_targets
                    or calibration.status != "active"
                    or calibration.review_status != "approved"
                    or calibration.gate_reasons
                    or calibration.sample_counts.get("oos", 0) <= 0
                ):
                    raise ValueError(
                        "calibration report has not passed this model's OOS gates"
                    )
                if calibration.target in reported_targets:
                    raise ValueError("duplicate calibration report for the same target")
                reported_targets.add(calibration.target)
                if not (
                    calibration.training_window[1]
                    <= evidence.calibration_training_end
                    < evidence.calibration_oos_start
                    <= evidence.calibration_oos_end
                    < calibration.created_at
                    <= evidence.approved_at
                ):
                    raise ValueError(
                        "calibration report is not time-separated out of sample"
                    )
                if evidence.expires_at > calibration.expires_at:
                    raise ValueError("model release outlives its calibration evidence")
            if reported_targets != set(model.calibration_targets):
                raise ValueError(
                    "model promotion requires every declared OOS calibration target"
                )
        gate_artifact = evidence.artifact("quality_gate_report")
        release_manifest_artifact = evidence.artifact("release_manifest")
        if gate_artifact is None or release_manifest_artifact is None:
            raise ValueError(
                "model promotion requires gate report and release manifest"
            )
        gate_report = ReleaseGateReportV1.model_validate_json(
            artifact_bytes[gate_artifact.artifact_id]
        )
        release_manifest = ReleaseArtifactAttestationV1.model_validate_json(
            artifact_bytes[release_manifest_artifact.artifact_id]
        )
        expected_manifest_hashes = {
            item.artifact_id: item.sha256
            for item in evidence.artifacts
            if item.role not in {"verification_attestation", "release_manifest"}
        }
        if release_manifest.artifact_hashes != expected_manifest_hashes:
            raise ValueError(
                "release manifest does not bind every release evidence artifact"
            )
        if not gate_report.gates:
            raise ValueError("model promotion requires a complete quality gate report")
        verification_artifact = evidence.artifact("verification_attestation")
        if verification_artifact is None:
            raise ValueError(
                "model promotion requires a trusted verification attestation"
            )
        verification = ReleaseVerificationAttestationV1.model_validate_json(
            artifact_bytes[verification_artifact.artifact_id]
        )
        verifier = self._trusted_verifiers.get(verification.verifier_id)
        if verifier is None:
            raise ValueError("model promotion has no configured trusted verifier")
        if verification.workflow_identity != verifier.workflow_identity:
            raise ValueError(
                "verification attestation has an untrusted workflow identity"
            )
        if verification.source_revision != verifier.expected_source_revision:
            raise ValueError(
                "verification source revision does not match deployment configuration"
            )
        if (
            verification.verification_suite_sha256
            != verifier.expected_verification_suite_sha256
        ):
            raise ValueError(
                "verification suite digest does not match deployment configuration"
            )
        expected_artifact_hashes = {
            item.artifact_id: item.sha256
            for item in evidence.artifacts
            if item.role != "verification_attestation"
        }
        expected_subject_digest = release_subject_digest(
            model,
            source_ids=evidence.source_ids,
            artifacts=evidence.artifacts,
            calibration_training_end=evidence.calibration_training_end,
            calibration_oos_start=evidence.calibration_oos_start,
            calibration_oos_end=evidence.calibration_oos_end,
            approved_by=evidence.approved_by,
            approved_at=evidence.approved_at,
            expires_at=evidence.expires_at,
        )
        if (
            (verification.model_id, verification.model_version)
            != (model.model_id, model.model_version)
            or verification.model_sha256 != sha256_digest(model)
            or verification.release_subject_digest != expected_subject_digest
            or verification.artifact_hashes != expected_artifact_hashes
            or set(verification.passed_gate_ids) != set(model.required_release_gates)
            or set(gate_report.gates) != set(verification.passed_gate_ids)
        ):
            raise ValueError(
                "verification attestation does not bind the model, inputs, and gates"
            )
        try:
            Ed25519PublicKey.from_public_bytes(verifier.public_key).verify(
                bytes.fromhex(verification.signature), verification.signing_bytes()
            )
        except (InvalidSignature, ValueError) as exc:
            raise ValueError("release verification signature is invalid") from exc
        now = at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("promotion time must include a timezone")
        now = now.astimezone(timezone.utc)
        if not evidence.approved_at <= now < evidence.expires_at:
            raise ValueError("model release evidence is not current at promotion time")

        existing = self._evidence.get(key)
        if existing is not None and existing != evidence:
            raise ValueError("model release evidence is immutable by model version")
        manifest_artifact = evidence.artifact("release_manifest")
        if manifest_artifact is None:  # validated by ModelReleaseEvidenceV1
            raise ValueError("model promotion requires a release manifest")
        self._evidence[key] = evidence
        self._active[model.model_id] = model.model_version
        return model.model_copy(
            update={
                "lifecycle": "active",
                "release_manifest": manifest_artifact.artifact_id,
                "approval_date": evidence.approved_at,
                "review_date": evidence.expires_at,
            }
        )

    def rollback(
        self, model_id: str, target_version: str, *, at: datetime | None = None
    ) -> ModelSpecV1:
        key = (model_id, target_version)
        model = self._models.get(key)
        evidence = self._evidence.get(key)
        if model is None or evidence is None:
            raise ValueError("rollback target has no promoted release evidence")
        now = at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("rollback time must include a timezone")
        now = now.astimezone(timezone.utc)
        if not evidence.approved_at <= now < evidence.expires_at:
            raise ValueError("rollback target release evidence has expired")
        release_manifest = evidence.artifact("release_manifest")
        if release_manifest is None:
            raise ValueError("rollback target is missing its release manifest")
        self._active[model_id] = target_version
        return model.model_copy(
            update={
                "lifecycle": "active",
                "release_manifest": release_manifest.artifact_id,
                "approval_date": evidence.approved_at,
                "review_date": evidence.expires_at,
            }
        )

    def retire(self, model_id: str) -> None:
        self._active.pop(model_id, None)

    def evidence(
        self, model_id: str, model_version: str
    ) -> ModelReleaseEvidenceV1 | None:
        return self._evidence.get((model_id, model_version))

    def advertised(self, *, at: datetime | None = None) -> tuple[ModelSpecV1, ...]:
        now = at or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("advertisement time must include a timezone")
        now = now.astimezone(timezone.utc)
        current: list[ModelSpecV1] = []
        for model_id, version in self._active.items():
            key = (model_id, version)
            model = self._models[key]
            evidence = self._evidence.get(key)
            if (
                evidence is None
                or not evidence.approved_at <= now < evidence.expires_at
            ):
                continue
            release_manifest = evidence.artifact("release_manifest")
            if release_manifest is None:
                continue
            current.append(
                model.model_copy(
                    update={
                        "lifecycle": "active",
                        "release_manifest": release_manifest.artifact_id,
                        "approval_date": evidence.approved_at,
                        "review_date": evidence.expires_at,
                    }
                )
            )
        return tuple(
            sorted(current, key=lambda item: (item.model_id, item.model_version))
        )


__all__ = [
    "DeploymentReleaseVerifierV1",
    "ModelEvidenceArtifactV1",
    "ModelInventory",
    "ModelReleaseEvidenceV1",
    "ModelTrustRootsV1",
    "ReleaseVerificationAttestationV1",
    "TrustedReleaseVerifier",
    "release_subject_digest",
    "sign_release_verification",
]
