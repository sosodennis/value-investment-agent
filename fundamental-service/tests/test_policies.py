import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fundamental_service.application.service import _approved_market_policy
from fundamental_service.calibration import (
    CalibrationArtifactV1,
    ConfidenceIntervalV1,
    ContinuousMetricsV1,
    IntervalMetricsV1,
    MetricBundleV1,
)
from fundamental_service.contracts import MarketPolicyInputsV1, QualityStatus
from fundamental_service.governance import (
    ModelEvidenceArtifactV1,
    ModelInventory,
    ModelReleaseEvidenceV1,
    ReleaseArtifactAttestationV1,
    ReleaseGateEvidenceV1,
    ReleaseGateReportV1,
    TrustedReleaseVerifier,
    release_subject_digest,
    sign_release_verification,
)
from fundamental_service.policies import (
    PolicyRecordV1,
    evaluate_eligibility,
    expansion_model_specs,
    initial_model_specs,
    initial_policy_records,
    resolve_policy,
)
from fundamental_service.public_source import PUBLIC_SOURCE_SPECS
from fundamental_service.sec_source import SEC_TERMS
from fundamental_service.serialization import sha256_digest
from fundamental_service.testsupport import make_valuation
from market_policy_fixtures import synthetic_market_inputs


def policy() -> PolicyRecordV1:
    request = make_valuation()
    base = request.assumptions.model_copy(deep=True)
    payload = {
        "contract_version": "fundamental.v1",
        "policy_id": "policy-v1",
        "policy_version": "policy-v1",
        "profile_id": "us-gaap-public-v1",
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v2",
        "assumptions": base,
        "source_refs": ("public-policy",),
        "effective_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "status": "active",
    }
    from fundamental_service.serialization import sha256_digest

    return PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))


def test_only_two_initial_models_and_no_legacy_fallback():
    assert {spec.model_id for spec in initial_model_specs()} == {
        "fcff_dcf",
        "transition_fcff_dcf",
    }


@pytest.mark.parametrize("policy", initial_policy_records(), ids=lambda p: p.model_id)
def test_initial_policies_do_not_invent_approved_market_inputs(policy):
    assert policy.assumptions is None
    assert policy.market_inputs is None
    for year in (2016, 2025, 2026, 2027):
        assert (
            _approved_market_policy(
                policy, valuation_timestamp=datetime(year, 1, 1, tzinfo=timezone.utc)
            )
            is None
        )


def test_market_observed_weight_basis_rejects_policy_weight_evidence():
    payload = synthetic_market_inputs().model_dump(mode="python")
    payload["capital_weight_basis"] = "market_observed"
    with pytest.raises(ValueError, match="market-observed capital weights"):
        MarketPolicyInputsV1(**payload)


def test_expansion_inventory_is_ordered_with_complete_non_placeholder_specs():
    specs = expansion_model_specs()
    assert [spec.model_id for spec in specs] == [
        "bank_excess_return",
        "insurance_statutory_excess_return",
        "reit_nav",
        "regulated_utility",
        "normalized_cyclical",
        "biotech_rnpv",
        "sum_of_parts",
        "ifrs_fcff_dcf",
    ]
    assert all(spec.lifecycle == "exploratory" for spec in specs)
    assert all(spec.release_manifest is None for spec in specs)
    assert all(spec.required_evidence for spec in specs)
    assert all(spec.source_register for spec in specs)
    assert all(spec.lifecycle == "exploratory" for spec in specs)
    assert all(spec.calibration_targets for spec in specs)
    assert all(spec.required_release_gates for spec in specs)
    assert all(spec.capital_bridge_policy for spec in specs)
    assert all(spec.monitoring_policy and spec.rollback_policy for spec in specs)


@pytest.mark.parametrize(
    "model", expansion_model_specs(), ids=lambda model: model.model_id
)
def test_expansion_families_are_explicitly_unsupported_until_release_evidence(model):
    request = (
        make_valuation().model_copy(update={"model_id": model.model_id}).with_digest()
    )
    result = evaluate_eligibility(
        request=request,
        model=model,
        available_fields=set(model.required_fields),
        quality=request.quality,
    )
    assert result.report.status == QualityStatus.UNSUPPORTED
    assert "MODEL_NOT_ACTIVE" in result.report.issue_codes
    assert "MODEL_RELEASE_EVIDENCE_MISSING" in result.report.issue_codes


def test_active_model_requires_governance_evidence():
    payload = initial_model_specs()[0].model_dump()
    payload["release_manifest"] = None
    with pytest.raises(ValueError, match="release manifest"):
        type(initial_model_specs()[0]).model_validate(payload)


def test_inventory_advertises_only_signed_test_fixture_until_family_release(
    tmp_path: Path,
):
    model = expansion_model_specs()[0].model_copy(
        update={"model_id": "test-only-release-governance"}
    )
    private_key = Ed25519PrivateKey.from_private_bytes(b"\x01" * 32)
    verifier_id = "fundamental-release-gate-v1"
    workflow_identity = "github-actions/fundamental-release-gates"
    source_revision = "a" * 40
    suite_digest = "b" * 64
    public_key = private_key.public_key().public_bytes(
        encoding=crypto_serialization.Encoding.Raw,
        format=crypto_serialization.PublicFormat.Raw,
    )
    trust_roots_file = tmp_path / "model-trust-roots.json"
    trust_roots_file.write_text(
        json.dumps(
            {
                "verifiers": {
                    verifier_id: {
                        "workflow_identity": workflow_identity,
                        "public_key_ed25519_base64": base64.b64encode(
                            public_key
                        ).decode("ascii"),
                        "expected_source_revision": source_revision,
                        "expected_verification_suite_sha256": suite_digest,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    inventory = ModelInventory.from_deployment_file((model,), trust_roots_file)
    assert inventory.trust_roots_configured
    assert inventory.advertised(at=datetime(2026, 1, 1, tzinfo=timezone.utc)) == ()
    source_count = len(model.source_register)
    role_names = (
        "positive_golden",
        "negative_golden",
        "challenger_report",
        "quality_gate_report",
        *("calibration_report" for _ in model.calibration_targets),
        "replay_report",
        "verification_attestation",
        "monitoring_plan",
        "release_manifest",
        "rollback_manifest",
    )
    role_ids = {
        role: f"evidence-{source_count + index}"
        for index, role in enumerate(role_names, start=1)
        if role != "calibration_report"
    }
    calibration_artifact_ids = tuple(
        f"evidence-{source_count + 5 + offset}"
        for offset in range(len(model.calibration_targets))
    )
    artifact_payloads: dict[str, bytes] = {
        f"evidence-{index}": f"captured public source bytes {index}".encode()
        for index in range(1, source_count + 1)
    }
    for artifact_id, target in zip(
        calibration_artifact_ids, model.calibration_targets, strict=True
    ):
        calibration = passing_bank_calibration(model.model_id, target)
        artifact_payloads[artifact_id] = calibration.model_dump_json().encode()

    def attestation(
        role: str,
        *,
        assertions: dict[str, bool],
        metrics: dict[str, int | float | str | bool],
    ) -> bytes:
        return (
            ReleaseArtifactAttestationV1(
                model_id=model.model_id,
                model_version=model.model_version,
                role=role,
                assertions=assertions,
                metrics=metrics,
            )
            .model_dump_json()
            .encode()
        )

    artifact_payloads[role_ids["positive_golden"]] = attestation(
        "positive_golden",
        assertions={"all_cases_passed": True},
        metrics={"case_count": 12},
    )
    artifact_payloads[role_ids["negative_golden"]] = attestation(
        "negative_golden",
        assertions={"all_cases_passed": True, "expected_abstentions_verified": True},
        metrics={"case_count": 8, "expected_abstention_count": 8},
    )
    artifact_payloads[role_ids["challenger_report"]] = attestation(
        "challenger_report",
        assertions={"independent_implementation": True, "all_nodes_match": True},
        metrics={"checked_node_count": 30, "mismatch_count": 0},
    )
    artifact_payloads[role_ids["replay_report"]] = attestation(
        "replay_report",
        assertions={"offline_replay_reproduced": True},
        metrics={"cohort_count": 12},
    )
    artifact_payloads[role_ids["monitoring_plan"]] = attestation(
        "monitoring_plan",
        assertions={
            "named_owner": True,
            "alerts_defined": True,
            "expiry_reviewed": True,
        },
        metrics={"review_interval_days": 30, "owner": "fundamental-model-risk"},
    )
    artifact_payloads[role_ids["rollback_manifest"]] = attestation(
        "rollback_manifest",
        assertions={"rollback_target_defined": True, "replay_before_reenable": True},
        metrics={"rollback_target_release": "previous-promoted-release-or-unsupported"},
    )

    def source_evidence(
        index: int, source_id: str, payload: bytes
    ) -> dict[str, object]:
        sec_source_uris = {
            "sec-companyfacts": (
                "https://data.sec.gov/api/xbrl/companyfacts/CIK0000019617.json"
            ),
            "sec-submissions": "https://data.sec.gov/submissions/CIK0000019617.json",
            "sec-filing": "https://www.sec.gov/Archives/edgar/data/19617/"
            "000001961726000099/jpm-20260630.htm",
            "sec-taxonomy": "https://www.sec.gov/Archives/edgar/data/19617/"
            "000001961726000099/jpm-20260630.xsd",
        }
        if source_id in sec_source_uris:
            uri = sec_source_uris[source_id]
            terms = SEC_TERMS
        else:
            source_spec = next(
                spec for spec in PUBLIC_SOURCE_SPECS if spec.source_id == source_id
            )
            uri = source_spec.uri_prefix
            terms = source_spec.terms_reference
        return {
            "artifact_id": f"evidence-{index}",
            "sha256": sha256(payload).hexdigest(),
            "role": "public_source",
            "source_id": source_id,
            "source_uri": uri,
            "terms_reference": terms,
            "available_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "captured_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        }

    role_items = [
        source_evidence(index, source_id, payload)
        for (index, source_id), payload in zip(
            enumerate(model.source_register, start=1),
            list(artifact_payloads.values())[: len(model.source_register)],
            strict=True,
        )
    ]
    artifact_roles: dict[str, str] = {
        artifact_id: role for role, artifact_id in role_ids.items()
    }
    artifact_roles.update(dict.fromkeys(calibration_artifact_ids, "calibration_report"))
    gate_artifact_ids = {
        "public-source-coverage": tuple(
            f"evidence-{index}" for index in range(1, source_count + 1)
        ),
        "point-in-time-accounting": (
            "evidence-1",
            role_ids["positive_golden"],
        ),
        "positive-negative-golden-cohorts": (
            role_ids["positive_golden"],
            role_ids["negative_golden"],
        ),
        "independent-node-challenger": (role_ids["challenger_report"],),
        "calibration-oos": calibration_artifact_ids,
        "replay-reproducibility": (role_ids["replay_report"],),
    }
    gate_report = ReleaseGateReportV1(
        model_id=model.model_id,
        model_version=model.model_version,
        gates={
            gate_id: ReleaseGateEvidenceV1(passed=True, artifact_ids=artifact_ids)
            for gate_id, artifact_ids in gate_artifact_ids.items()
        },
    )
    artifact_payloads[role_ids["quality_gate_report"]] = (
        gate_report.model_dump_json().encode()
    )
    evidence_fields = {
        "contract_version": "fundamental.v1",
        "model_id": model.model_id,
        "model_version": model.model_version,
        "source_ids": model.source_register,
        "calibration_training_end": datetime(2025, 12, 31, tzinfo=timezone.utc),
        "calibration_oos_start": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "calibration_oos_end": datetime(2026, 6, 30, tzinfo=timezone.utc),
        "approved_by": model.independent_validator,
        "approved_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
    }
    role_items.extend(
        {
            "artifact_id": artifact_id,
            "sha256": sha256(artifact_payloads[artifact_id]).hexdigest(),
            "role": role,
            "source_id": None,
        }
        for artifact_id, role in artifact_roles.items()
        if role not in {"verification_attestation", "release_manifest"}
    )
    release_attestation = ReleaseArtifactAttestationV1(
        model_id=model.model_id,
        model_version=model.model_version,
        role="release_manifest",
        assertions={"all_gates_complete": True},
        metrics={},
        artifact_hashes={
            artifact_id: sha256(payload).hexdigest()
            for artifact_id, payload in artifact_payloads.items()
        },
    )
    artifact_payloads[role_ids["release_manifest"]] = (
        release_attestation.model_dump_json().encode()
    )
    role_items.append(
        {
            "artifact_id": role_ids["release_manifest"],
            "sha256": sha256(
                artifact_payloads[role_ids["release_manifest"]]
            ).hexdigest(),
            "role": "release_manifest",
            "source_id": None,
        }
    )
    subject_artifacts = tuple(
        ModelEvidenceArtifactV1.model_validate(item) for item in role_items
    )
    subject_digest = release_subject_digest(
        model,
        source_ids=evidence_fields["source_ids"],
        artifacts=subject_artifacts,
        calibration_training_end=evidence_fields["calibration_training_end"],
        calibration_oos_start=evidence_fields["calibration_oos_start"],
        calibration_oos_end=evidence_fields["calibration_oos_end"],
        approved_by=evidence_fields["approved_by"],
        approved_at=evidence_fields["approved_at"],
        expires_at=evidence_fields["expires_at"],
    )
    verification = sign_release_verification(
        {
            "model_id": model.model_id,
            "model_version": model.model_version,
            "model_sha256": sha256_digest(model),
            "release_subject_digest": subject_digest,
            "source_revision": source_revision,
            "verification_suite_sha256": suite_digest,
            "verification_run_id": "release-run-2026-07-02-001",
            "workflow_identity": workflow_identity,
            "verifier_id": verifier_id,
            "passed_gate_ids": tuple(sorted(model.required_release_gates)),
            "artifact_hashes": {
                item.artifact_id: item.sha256 for item in subject_artifacts
            },
        },
        private_key,
    )
    assert role_ids["release_manifest"] in verification.artifact_hashes
    assert len(verification.artifact_hashes) == len(subject_artifacts)
    artifact_payloads[role_ids["verification_attestation"]] = (
        verification.model_dump_json().encode()
    )
    role_items.append(
        {
            "artifact_id": role_ids["verification_attestation"],
            "sha256": sha256(
                artifact_payloads[role_ids["verification_attestation"]]
            ).hexdigest(),
            "role": "verification_attestation",
            "source_id": None,
        }
    )
    evidence_payload = {**evidence_fields, "artifacts": role_items}
    evidence_payload["artifacts"] = tuple(
        ModelEvidenceArtifactV1.model_validate(item)
        for item in evidence_payload["artifacts"]
    )
    normalized_evidence = ModelReleaseEvidenceV1.model_construct(
        **evidence_payload, evidence_digest="0" * 64
    )
    evidence_payload = normalized_evidence.model_dump(exclude={"evidence_digest"})
    evidence = ModelReleaseEvidenceV1(
        **evidence_payload, evidence_digest=sha256_digest(evidence_payload)
    )
    with pytest.raises(ValueError, match="missing or has a hash mismatch"):
        inventory.promote(model, evidence, artifact_bytes={})
    invalid_bytes = dict(artifact_payloads)
    invalid_bytes[role_ids["positive_golden"]] = b"pass"
    with pytest.raises(ValueError, match="missing or has a hash mismatch"):
        inventory.promote(model, evidence, artifact_bytes=invalid_bytes)

    def rehash_evidence(payloads: dict[str, bytes]) -> ModelReleaseEvidenceV1:
        artifacts = tuple(
            artifact.model_copy(
                update={"sha256": sha256(payloads[artifact.artifact_id]).hexdigest()}
            )
            for artifact in evidence.artifacts
        )
        payload = evidence.model_dump(exclude={"evidence_digest"})
        payload["artifacts"] = artifacts
        normalized = ModelReleaseEvidenceV1.model_construct(
            **payload, evidence_digest="0" * 64
        ).model_dump(exclude={"evidence_digest"})
        return ModelReleaseEvidenceV1(
            **normalized, evidence_digest=sha256_digest(normalized)
        )

    incomplete_manifest_payloads = dict(artifact_payloads)
    release_manifest = ReleaseArtifactAttestationV1.model_validate_json(
        incomplete_manifest_payloads[role_ids["release_manifest"]]
    )
    manifest_hashes = dict(release_manifest.artifact_hashes)
    manifest_hashes.pop(role_ids["rollback_manifest"])
    incomplete_manifest_payloads[role_ids["release_manifest"]] = (
        release_manifest.model_copy(update={"artifact_hashes": manifest_hashes})
        .model_dump_json()
        .encode()
    )
    with pytest.raises(ValueError, match="must bind every evidence artifact hash"):
        inventory.promote(
            model,
            rehash_evidence(incomplete_manifest_payloads),
            artifact_bytes=incomplete_manifest_payloads,
        )

    failed_manifest_payloads = dict(artifact_payloads)
    release_manifest = ReleaseArtifactAttestationV1.model_validate_json(
        failed_manifest_payloads[role_ids["release_manifest"]]
    )
    failed_manifest_payloads[role_ids["release_manifest"]] = (
        release_manifest.model_copy(
            update={"assertions": {"all_gates_complete": False}}
        )
        .model_dump_json()
        .encode()
    )
    failed_evidence = rehash_evidence(failed_manifest_payloads)
    with pytest.raises(ValueError, match="release_manifest does not pass"):
        inventory.promote(
            model, failed_evidence, artifact_bytes=failed_manifest_payloads
        )
    with pytest.raises(ValueError, match="no configured trusted verifier"):
        ModelInventory((model,)).promote(
            model, evidence, artifact_bytes=artifact_payloads
        )
    with pytest.raises(ValueError, match="untrusted workflow identity"):
        ModelInventory(
            (model,),
            trusted_verifiers={
                verifier_id: TrustedReleaseVerifier(
                    workflow_identity="github-actions/untrusted-workflow",
                    public_key=private_key.public_key().public_bytes(
                        encoding=crypto_serialization.Encoding.Raw,
                        format=crypto_serialization.PublicFormat.Raw,
                    ),
                    expected_source_revision=source_revision,
                    expected_verification_suite_sha256=suite_digest,
                )
            },
        ).promote(model, evidence, artifact_bytes=artifact_payloads)
    with pytest.raises(ValueError, match="source revision does not match"):
        ModelInventory(
            (model,),
            trusted_verifiers={
                verifier_id: TrustedReleaseVerifier(
                    workflow_identity=workflow_identity,
                    public_key=private_key.public_key().public_bytes(
                        encoding=crypto_serialization.Encoding.Raw,
                        format=crypto_serialization.PublicFormat.Raw,
                    ),
                    expected_source_revision="c" * 40,
                    expected_verification_suite_sha256=suite_digest,
                )
            },
        ).promote(model, evidence, artifact_bytes=artifact_payloads)
    with pytest.raises(ValueError, match="suite digest does not match"):
        ModelInventory(
            (model,),
            trusted_verifiers={
                verifier_id: TrustedReleaseVerifier(
                    workflow_identity=workflow_identity,
                    public_key=private_key.public_key().public_bytes(
                        encoding=crypto_serialization.Encoding.Raw,
                        format=crypto_serialization.PublicFormat.Raw,
                    ),
                    expected_source_revision=source_revision,
                    expected_verification_suite_sha256="d" * 64,
                )
            },
        ).promote(model, evidence, artifact_bytes=artifact_payloads)
    unsigned_payloads = dict(artifact_payloads)
    forged = verification.model_copy(update={"signature": "0" * 128})
    unsigned_payloads[role_ids["verification_attestation"]] = (
        forged.model_dump_json().encode()
    )
    forged_evidence = rehash_evidence(unsigned_payloads)
    with pytest.raises(ValueError, match="release verification signature is invalid"):
        inventory.promote(model, forged_evidence, artifact_bytes=unsigned_payloads)
    promoted = inventory.promote(model, evidence, artifact_bytes=artifact_payloads)
    assert promoted.lifecycle == "active"
    assert [
        item.model_id
        for item in inventory.advertised(at=datetime(2026, 8, 1, tzinfo=timezone.utc))
    ] == ["test-only-release-governance"]
    assert inventory.advertised(at=datetime(2027, 2, 1, tzinfo=timezone.utc)) == ()


def test_deployment_trust_roots_reject_malformed_public_keys(tmp_path: Path):
    trust_roots_file = tmp_path / "model-trust-roots.json"
    trust_roots_file.write_text(
        json.dumps(
            {
                "verifiers": {
                    "release-gate": {
                        "workflow_identity": "github-actions/fundamental-release-gates",
                        "public_key_ed25519_base64": "not-a-public-key",
                        "expected_source_revision": "a" * 40,
                        "expected_verification_suite_sha256": "b" * 64,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="raw Ed25519 public key"):
        ModelInventory.from_deployment_file(expansion_model_specs(), trust_roots_file)


def passing_bank_calibration(model_id: str, target: str) -> CalibrationArtifactV1:
    interval = ConfidenceIntervalV1(
        confidence=0.95,
        lower=0.75,
        upper=0.95,
        method="wilson",
        seed=17,
        resamples=1000,
    )
    continuous = ContinuousMetricsV1(
        sample_count=30,
        mae=0.1,
        rmse=0.2,
        median_absolute_error=0.1,
        signed_bias=0.0,
        scaled_error=0.1,
        confidence_interval=interval,
    )
    metrics = MetricBundleV1(
        continuous=continuous,
        interval=IntervalMetricsV1(
            sample_count=30,
            coverage=0.9,
            mean_width=1.0,
            interval_score=1.1,
            coverage_confidence_interval=interval,
        ),
    )
    payload = {
        "calibration_id": "bank-calibration-2026",
        "calibration_version": "bank-calibration-v1",
        "status": "active",
        "target": target,
        "target_layer": "forecast",
        "metric": "mae",
        "model_id": model_id,
        "cohort_id": "us-bank-holding-companies-v1",
        "training_window": (
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 12, 31, tzinfo=timezone.utc),
        ),
        "data_snapshot_ids": ("bank-train-oos-snapshot",),
        "feature_contract": "bank-features-v1",
        "label_contract": "bank-next-reported-results-v1",
        "split_manifest_digest": "1" * 64,
        "split_policy_version": "bank-split-v1",
        "purge_days": 30,
        "embargo_days": 14,
        "model_class": "bank-forecast-v1",
        "hyperparameters": {},
        "raw_metrics": metrics,
        "calibrated_metrics": metrics,
        "naive_metrics": metrics,
        "sample_counts": {"train": 60, "validation": 30, "oos": 30},
        "cohort_sample_counts": {"bank": 30},
        "cohort_metrics": {},
        "missingness_counts": {"oos": 0},
        "abstention_count": 0,
        "label_manifest_digest": "2" * 64,
        "exclusion_manifest": (),
        "provider_fallback_rate": 0.0,
        "improvement_confidence_interval": interval,
        "naive_improvement_confidence_interval": interval,
        "confidence_method": "percentile-bootstrap",
        "fallback_policy": "abstain",
        "owner": "fundamental-service",
        "review_status": "approved",
        "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "policy_version": "bank-calibration-gates-v1",
        "quality_issue_codes": (),
        "gate_reasons": (),
        "affects_base_value": False,
    }
    from fundamental_service.serialization import sha256_digest

    provisional = CalibrationArtifactV1.model_construct(
        **payload, artifact_digest="0" * 64
    )
    return CalibrationArtifactV1(
        **payload,
        artifact_digest=sha256_digest(
            provisional.model_dump(exclude={"artifact_digest"})
        ),
    )


def test_policy_resolution_records_caller_precedence_and_digest():
    request = make_valuation()
    resolved, resolution = resolve_policy(request=request, policy=policy())
    assert resolved.input_digest == resolution.input_digest
    assert resolution.precedence["assumptions.terminal_growth"] == "caller"


def test_missing_or_low_quality_inputs_abstain():
    request = make_valuation()
    result = evaluate_eligibility(
        request=request,
        model=initial_model_specs()[0],
        available_fields={"revenue"},
        quality={"status": QualityStatus.PROVISIONAL},
    )
    assert result.report.status == QualityStatus.ABSTAIN
    assert "MISSING_REQUIRED_FACT" in result.report.issue_codes


def test_policy_digest_is_immutable():
    first = policy()
    altered = first.model_copy(update={"policy_version": "policy-v2"})
    with pytest.raises(ValueError):
        PolicyRecordV1.model_validate(altered.model_dump())


def test_zero_caller_terminal_growth_wins():
    request = make_valuation().model_copy(
        update={
            "assumptions": make_valuation().assumptions.model_copy(
                update={"terminal_growth": Decimal("0")}
            )
        }
    )
    resolved, resolution = resolve_policy(request=request, policy=policy())
    assert resolved.assumptions.terminal_growth == Decimal("0")
    assert resolution.precedence["assumptions.terminal_growth"] == "caller"
