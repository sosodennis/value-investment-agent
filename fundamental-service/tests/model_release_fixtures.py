from datetime import UTC, datetime
from hashlib import sha256

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service.governance import (
    ModelEvidenceArtifactV1,
    ModelInventory,
    ModelReleaseEvidenceV1,
    ReleaseArtifactAttestationV1,
    ReleaseGateReportV1,
    TrustedReleaseVerifier,
    release_subject_digest,
    sign_release_verification,
)
from fundamental_service.policies import ModelSpecV1
from fundamental_service.public_source_catalog import PUBLIC_SOURCE_SPECS
from fundamental_service.sec_source import SEC_TERMS
from fundamental_service.serialization import sha256_digest

APPROVED = datetime(2026, 11, 23, tzinfo=UTC)
EXPIRES = datetime(2026, 12, 23, tzinfo=UTC)


def signed_raw_release(
    model: ModelSpecV1,
) -> tuple[ModelInventory, ModelReleaseEvidenceV1, dict[str, bytes]]:
    private = Ed25519PrivateKey.from_private_bytes(b"\x02" * 32)
    inventory = ModelInventory(
        (model,),
        trusted_verifiers={
            "test": TrustedReleaseVerifier(
                public_key=private.public_key().public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw
                ),
                workflow_identity="test-workflow",
                expected_source_revision="a" * 40,
                expected_verification_suite_sha256="b" * 64,
            )
        },
    )
    payloads: dict[str, bytes] = {}
    artifacts: list[ModelEvidenceArtifactV1] = []

    def add(artifact_id: str, role: str, payload: bytes, **metadata: object) -> None:
        payloads[artifact_id] = payload
        artifacts.append(
            ModelEvidenceArtifactV1.model_validate(
                {
                    "artifact_id": artifact_id,
                    "role": role,
                    "sha256": sha256(payload).hexdigest(),
                    **metadata,
                }
            )
        )

    for source in model.source_register:
        public = next(
            (spec for spec in PUBLIC_SOURCE_SPECS if spec.source_id == source), None
        )
        uris = {
            "sec-submissions": "https://data.sec.gov/submissions/CIK1.json",
            "sec-companyfacts": "https://data.sec.gov/api/xbrl/companyfacts/CIK1.json",
            "sec-filing": "https://www.sec.gov/Archives/edgar/data/1/example.htm",
        }
        add(
            source,
            "public_source",
            b"synthetic source fixture",
            source_id=source,
            source_uri=public.uri_prefix if public else uris[source],
            terms_reference=public.terms_reference if public else SEC_TERMS,
            available_at=APPROVED,
            captured_at=APPROVED,
        )
    evidence = {
        "positive_golden": ({"all_cases_passed": True}, {"case_count": 10}),
        "negative_golden": (
            {"all_cases_passed": True, "expected_abstentions_verified": True},
            {"case_count": 10, "expected_abstention_count": 10},
        ),
        "challenger_report": (
            {"independent_implementation": True, "all_nodes_match": True},
            {"checked_node_count": 40, "mismatch_count": 0},
        ),
        "replay_report": ({"offline_replay_reproduced": True}, {"cohort_count": 20}),
        "monitoring_plan": (
            {"named_owner": True, "alerts_defined": True, "expiry_reviewed": True},
            {"review_interval_days": 30, "owner": "test-owner"},
        ),
        "rollback_manifest": (
            {"rollback_target_defined": True, "replay_before_reenable": True},
            {"rollback_target_release": "unsupported"},
        ),
    }
    for role, (assertions, metrics) in evidence.items():
        add(
            role,
            role,
            ReleaseArtifactAttestationV1.model_validate(
                {
                    "model_id": model.model_id,
                    "model_version": model.model_version,
                    "role": role,
                    "assertions": assertions,
                    "metrics": metrics,
                }
            )
            .model_dump_json()
            .encode(),
        )
    gates = {
        "public-source-coverage": model.source_register,
        "point-in-time-accounting": (model.source_register[0], "positive_golden"),
        "positive-negative-golden-cohorts": ("positive_golden", "negative_golden"),
        "independent-node-challenger": ("challenger_report",),
        "replay-reproducibility": ("replay_report",),
    }
    add(
        "quality_gate_report",
        "quality_gate_report",
        ReleaseGateReportV1.model_validate(
            {
                "model_id": model.model_id,
                "model_version": model.model_version,
                "gates": {
                    gate: {"passed": True, "artifact_ids": ids}
                    for gate, ids in gates.items()
                },
            }
        )
        .model_dump_json()
        .encode(),
    )
    add(
        "release_manifest",
        "release_manifest",
        ReleaseArtifactAttestationV1(
            model_id=model.model_id,
            model_version=model.model_version,
            role="release_manifest",
            assertions={"all_gates_complete": True},
            metrics={},
            artifact_hashes={item.artifact_id: item.sha256 for item in artifacts},
        )
        .model_dump_json()
        .encode(),
    )
    fields = dict(
        source_ids=model.source_register,
        calibration_training_end=None,
        calibration_oos_start=None,
        calibration_oos_end=None,
        approved_by=model.independent_validator,
        approved_at=APPROVED,
        expires_at=EXPIRES,
    )
    signature = sign_release_verification(
        {
            "model_id": model.model_id,
            "model_version": model.model_version,
            "model_sha256": sha256_digest(model),
            "release_subject_digest": release_subject_digest(
                model, artifacts=tuple(artifacts), **fields
            ),
            "source_revision": "a" * 40,
            "verification_suite_sha256": "b" * 64,
            "verification_run_id": "synthetic-test-run",
            "workflow_identity": "test-workflow",
            "verifier_id": "test",
            "passed_gate_ids": model.required_release_gates,
            "artifact_hashes": {item.artifact_id: item.sha256 for item in artifacts},
        },
        private,
    )
    add(
        "verification_attestation",
        "verification_attestation",
        signature.model_dump_json().encode(),
    )
    unsigned = ModelReleaseEvidenceV1.model_construct(
        model_id=model.model_id,
        model_version=model.model_version,
        artifacts=tuple(artifacts),
        evidence_digest="0" * 64,
        **fields,
    ).model_dump(exclude={"evidence_digest"})
    release = ModelReleaseEvidenceV1(
        **unsigned, evidence_digest=sha256_digest(unsigned)
    )
    return inventory, release, payloads
