import asyncio
import hashlib
import json
import socket
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fundamental_service.app import create_app, create_runtime_app
from fundamental_service.application.service import (
    FundamentalApplication,
    UncertaintyRequestV1,
    normalize_uncertainty_payload,
)
from fundamental_service.contracts import (
    CalculationArtifactV1,
    CalculationEvidenceV1,
    CallerApprovalEnvelopeV1,
    CanonicalFactV1,
    FactsReadRequestV1,
    PeriodType,
    QualityStatus,
    SnapshotResolutionRequestV1,
    SourceProvenanceV1,
    SourceRole,
    UncertaintyV1,
    XbrlContextV1,
)
from fundamental_service.data_releases import (
    REQUIRED_DATA_RELEASE_GATES,
    ActiveDataReleaseV1,
    ActiveDataReleaseWithManifestV1,
    ArtifactRefV1,
    DataReleaseActivationCommandV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseVerificationV1,
    FactRefV1,
    MappingRefV1,
    SnapshotRefV1,
    sign_data_release_verification,
)
from fundamental_service.facts import canonical_fact_digest
from fundamental_service.governance import ModelInventory
from fundamental_service.operations import OperationsConfig
from fundamental_service.policies import (
    PolicyError,
    PolicyRecordV1,
    PolicyRegistry,
    expansion_model_specs,
    expansion_policy_records,
    initial_model_specs,
    initial_policy_records,
)
from fundamental_service.replay import ArtifactStore, replay_calculation
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.testsupport import (
    TEST_SERVICE_TOKEN,
    auth_headers,
    make_internal_envelope,
    make_valuation,
)
from fundamental_service.uncertainty import UncertaintyEvidenceV1


def _bind_initial_policy(valuation):
    policy = initial_policy_records()[0]
    return valuation.model_copy(
        update={
            "policy_id": policy.policy_id,
            "provenance": valuation.provenance.model_copy(
                update={"policy_version": policy.policy_version}
            ),
        }
    ).with_digest()


def _with_uncertainty_digest(payload):
    normalized = normalize_uncertainty_payload(payload)
    normalized["input_digest"] = None
    normalized["caller_approval"] = None
    return UncertaintyRequestV1.model_validate_json(
        json.dumps(normalized)
    ).with_digest()


class _SnapshotRepository:
    def __init__(self):
        valuation = make_valuation()
        self.snapshot = SimpleNamespace(
            snapshot_id="snapshot-1",
            identity=valuation.identity,
            valuation_timestamp=valuation.valuation_context.valuation_timestamp,
            source_records=(SimpleNamespace(content_hash="a" * 64),),
            manifest_digest="b" * 64,
            policy_version="source-policy-v1",
            coverage_status=QualityStatus.VERIFIED,
            issues=(),
        )

    def get(self, snapshot_id: str):
        self.snapshot.snapshot_id = snapshot_id
        return self.snapshot


class _ResolvingSnapshotRepository(_SnapshotRepository):
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def find(self, *, identity, valuation_timestamp):
        if (
            identity.issuer_id == self.snapshot.identity.issuer_id
            and valuation_timestamp >= self.snapshot.valuation_timestamp
        ):
            return (self.snapshot,)
        return ()


class _ReleaseSnapshotRepository(_ResolvingSnapshotRepository):
    def __init__(self, *snapshots):
        self.snapshots = snapshots
        self.snapshot = snapshots[0]

    def find(self, *, identity, valuation_timestamp):
        return tuple(
            snapshot
            for snapshot in self.snapshots
            if identity.issuer_id == snapshot.identity.issuer_id
            and valuation_timestamp >= snapshot.valuation_timestamp
        )


class _FactRepository:
    def get(self, fact_id: str):
        return SimpleNamespace(
            fact_id=fact_id,
            issuer_id="CIK1",
            security_id="COMMON",
            quality=QualityStatus.VERIFIED,
            available_at=datetime(2025, 1, 1, tzinfo=UTC),
            source=SimpleNamespace(content_hash="a" * 64),
        )

    def resolve(self, *, snapshot, valuation_timestamp, required_fields):
        _ = snapshot, valuation_timestamp
        return tuple(
            _canonical_fact(f"fact-{field}", field) for field in required_fields
        )


def _canonical_fact(fact_id: str, normalized_field: str) -> CanonicalFactV1:
    available = datetime(2025, 12, 1, tzinfo=UTC)
    period_start = datetime(2025, 1, 1).date()
    period_end = datetime(2025, 12, 31).date()
    return CanonicalFactV1(
        contract_version="fundamental.v1",
        fact_id=fact_id,
        issuer_id="CIK1",
        security_id="COMMON",
        concept="us-gaap:Revenues",
        normalized_field=normalized_field,
        value=Decimal(100),
        unit="USD",
        scale=0,
        currency="USD",
        period_start=period_start,
        period_end=period_end,
        context=XbrlContextV1(
            concept_qname="us-gaap:Revenues",
            period_type=PeriodType.DURATION,
            start_date=period_start,
            end_date=period_end,
            unit_qname="xbrli:shares",
            measure="iso4217:USD",
            entity_scope="consolidated",
            consolidation_scope="consolidated",
            context_id=fact_id,
        ),
        security_scope="COMMON",
        as_of=datetime(2025, 12, 31, tzinfo=UTC),
        available_at=available,
        filed_at=available,
        captured_at=datetime(2026, 1, 2, tzinfo=UTC),
        accession_number="0000000001-25-000001",
        filing_version="original",
        taxonomy_version="us-gaap-2025",
        source=SourceProvenanceV1(
            source_url="https://www.sec.gov/Archives/edgar/data/1/fixture.htm",
            content_hash="a" * 64,
            source_role=SourceRole.FILING,
            captured_at=datetime(2026, 1, 2, tzinfo=UTC),
            available_at=available,
            filed_at=available,
            accession_number="0000000001-25-000001",
            parser_version="arelle-2.47.4",
            taxonomy_version="us-gaap-2025",
            terms_reference="SEC fair access policy",
        ),
        quality=QualityStatus.VERIFIED,
    )


class _CanonicalFactRepository(_FactRepository):
    def get(self, fact_id: str):
        return _canonical_fact(fact_id, "revenue")


def _release_manifest_for(snapshot, facts):
    fact_refs = tuple(
        FactRefV1(
            fact_id=fact.fact_id,
            fact_digest=sha256_digest(fact.model_dump(mode="json")),
        )
        for fact in facts
    )
    snapshot_ref = SnapshotRefV1(
        snapshot_id=snapshot.snapshot_id,
        manifest_digest=snapshot.manifest_digest,
        facts=fact_refs,
        fact_set_digest=sha256_digest(fact_refs),
    )
    payload = {
        "profile_id": "sec-public-pit-v1",
        "release_id": "release-pinned-tests",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "snapshot_refs": (snapshot_ref,),
        "mapping_refs": (
            MappingRefV1(mapping_id="mapping-v1", mapping_digest="c" * 64),
        ),
        "taxonomy_refs": (
            ArtifactRefV1(
                artifact_id="taxonomy-v1",
                content_hash="d" * 64,
                media_type="application/zip",
                role="taxonomy",
            ),
        ),
        "parser_version": "arelle-release==2.47.4",
        "quality_profile_digest": "e" * 64,
        "required_fields": ("revenue",),
        "artifact_refs": (
            ArtifactRefV1(
                artifact_id="quality-v1",
                content_hash="f" * 64,
                media_type="application/json",
                role="quality-evidence",
            ),
        ),
    }
    return DataReleaseManifestV1(
        **payload,
        manifest_digest=sha256_digest(payload),
    )


def _release_verification_for(
    manifest: DataReleaseManifestV1,
) -> DataReleaseVerificationV1:
    payload = {
        "manifest_digest": manifest.manifest_digest,
        "verification_suite_digest": "1" * 64,
        "source_revision": "2" * 40,
        "verification_run_id": "release-api-run",
        "workflow_identity": "github://value-investment-agent/release-api-test",
        "verifier_id": "release-api-test",
        "passed_gate_ids": tuple(sorted(REQUIRED_DATA_RELEASE_GATES)),
        "evidence_refs": (
            ArtifactRefV1(
                artifact_id="release-api-evidence",
                content_hash="3" * 64,
                media_type="application/json",
                role="verification-evidence",
            ),
        ),
        "mapping_reviews": (),
    }
    return sign_data_release_verification(
        payload,
        Ed25519PrivateKey.from_private_bytes(b"release-api-key".ljust(32, b"0")),
    )


class _DataReleaseMetadata:
    def __init__(self) -> None:
        self.candidates: dict[
            str, tuple[DataReleaseManifestV1, DataReleaseVerificationV1]
        ] = {}
        self.active: dict[str, ActiveDataReleaseWithManifestV1] = {}
        self.activation_history: set[tuple[str, str]] = set()
        self.rejected_candidates: set[str] = set()
        self.commands: list[DataReleaseActivationCommandV1] = []

    def publish_data_release_candidate(
        self,
        manifest: DataReleaseManifestV1,
        verification: DataReleaseVerificationV1,
    ) -> None:
        if manifest.manifest_digest in self.rejected_candidates:
            raise DataReleaseError(
                "DATA_RELEASE_CANDIDATE_UNVERIFIED", "candidate was rejected"
            )
        self.candidates[manifest.manifest_digest] = (manifest, verification)

    def get_active_data_release_with_manifest(
        self, profile_id: str
    ) -> ActiveDataReleaseWithManifestV1 | None:
        return self.active.get(profile_id)

    def get_data_release_manifest(
        self, manifest_digest: str
    ) -> DataReleaseManifestV1 | None:
        candidate = self.candidates.get(manifest_digest)
        return None if candidate is None else candidate[0]

    def compare_and_swap_data_release(
        self, command: DataReleaseActivationCommandV1
    ) -> ActiveDataReleaseV1:
        self.commands.append(command)
        candidate = self.candidates.get(command.manifest_digest)
        if candidate is None or candidate[0].profile_id != command.profile_id:
            raise DataReleaseError(
                "DATA_RELEASE_CANDIDATE_UNVERIFIED", "candidate was not published"
            )
        current = self.active.get(command.profile_id)
        current_revision = 0 if current is None else current.active.revision
        current_digest = None if current is None else current.active.manifest_digest
        if (
            current_revision != command.expected_revision
            or current_digest != command.expected_manifest_digest
        ):
            raise DataReleaseError(
                "DATA_RELEASE_POINTER_CONFLICT",
                "active release changed",
                retryable=True,
            )
        if (
            command.operation == "rollback"
            and (
                command.profile_id,
                command.manifest_digest,
            )
            not in self.activation_history
        ):
            raise DataReleaseError(
                "DATA_RELEASE_ROLLBACK_TARGET_INVALID", "rollback target was not active"
            )
        active = ActiveDataReleaseV1(
            profile_id=command.profile_id,
            manifest_digest=command.manifest_digest,
            revision=current_revision + 1,
            activated_at=datetime.now(UTC),
        )
        resolved = ActiveDataReleaseWithManifestV1(
            active=active,
            manifest=candidate[0],
        )
        self.active[command.profile_id] = resolved
        self.activation_history.add((command.profile_id, command.manifest_digest))
        return active


def _policy_with_assumptions(assumptions) -> PolicyRecordV1:
    payload = {
        "contract_version": "fundamental.v1",
        "policy_id": "fcff-policy-v1",
        "policy_version": "fcff-policy-version-1",
        "profile_id": "us-gaap-public-v1",
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v1",
        "assumptions": assumptions,
        "source_refs": ("public-policy-fixture",),
        "effective_at": datetime(1970, 1, 1, tzinfo=UTC),
        "status": "active",
    }
    return PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))


class _ForeignFactRepository(_FactRepository):
    def get(self, fact_id: str):
        fact = super().get(fact_id)
        fact.issuer_id = "CIK-FOREIGN"
        return fact


def test_readiness_distinguishes_missing_snapshot_dependency():
    client = TestClient(create_app())
    assert client.get("/readyz").json() == {
        "contract_version": "internal.v1",
        "status": "not_ready",
    }


def test_snapshot_resolution_returns_service_owned_snapshot_and_fact_refs():
    valuation = make_valuation()
    snapshot = SimpleNamespace(
        snapshot_id="snapshot-resolved",
        identity=valuation.identity,
        valuation_timestamp=valuation.valuation_context.valuation_timestamp,
        coverage_status=QualityStatus.VERIFIED,
        issues=(),
        parser_version="parser-v1",
        taxonomy_manifest_id="taxonomy-v1",
        policy_version="policy-v1",
        source_records=(),
    )
    client = TestClient(
        create_app(
            _ResolvingSnapshotRepository(snapshot),
            fact_repository=_FactRepository(),
        )
    )
    selector = {
        "contract_version": "fundamental.v1",
        "identity": valuation.identity.model_dump(mode="json"),
        "valuation_timestamp": (
            valuation.valuation_context.valuation_timestamp.isoformat()
        ),
        "source_selection_policy": "pit-v1",
        "coverage_profile": "us-gaap-public-v1",
        "required_fields": ["revenue"],
    }
    response = client.post(
        "/v1/data/snapshots/resolve",
        headers=auth_headers(),
        json=make_internal_envelope(selector),
    )
    assert response.status_code == 200
    assert response.json()["result"]["snapshot_id"] == "snapshot-resolved"
    assert response.json()["result"]["historical_facts"] == ["fact-revenue"]


def test_snapshot_resolution_returns_immutable_snapshot_timestamp():
    valuation = make_valuation()
    snapshot = SimpleNamespace(
        snapshot_id="snapshot-immutable-time",
        identity=valuation.identity,
        valuation_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        coverage_status=QualityStatus.VERIFIED,
        issues=(),
        parser_version="parser-v1",
        taxonomy_manifest_id="taxonomy-v1",
        policy_version="policy-v1",
        source_records=(),
    )
    client = TestClient(
        create_app(
            _ResolvingSnapshotRepository(snapshot),
            fact_repository=_FactRepository(),
        )
    )
    request = SnapshotResolutionRequestV1(
        contract_version="fundamental.v1",
        identity=valuation.identity,
        valuation_timestamp=datetime(2026, 11, 7, tzinfo=UTC),
        source_selection_policy="pit-v1",
        coverage_profile="us-gaap-public-v1",
        required_fields=("revenue",),
    )

    response = client.post(
        "/v1/data/snapshots/resolve",
        headers=auth_headers(),
        json=make_internal_envelope(request.model_dump(mode="json")),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["snapshot_id"] == snapshot.snapshot_id
    assert result["historical_facts"] == ["fact-revenue"]
    assert result["valuation_timestamp"] == "2026-11-07T00:00:00Z"
    assert result["snapshot_timestamp"] == "2026-01-01T00:00:00Z"


def test_facts_read_is_snapshot_scoped_point_in_time_and_documented():
    app = create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    client = TestClient(app)
    request = {
        "contract_version": "fundamental.v1",
        "snapshot_id": "snapshot-1",
        "required_fields": ["revenue"],
    }
    response = client.request(
        "GET",
        "/v1/data/facts",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["snapshot_id"] == "snapshot-1"
    assert result["snapshot_manifest_digest"] == "b" * 64
    assert result["facts"][0]["fact_id"] == "fact-revenue"
    assert result["facts"][0]["source"]["content_hash"] == "a" * 64

    openapi = app.openapi()
    facts_operation = openapi["paths"]["/v1/data/facts"]["get"]
    assert "requestBody" in facts_operation
    facts_envelope = openapi["components"]["schemas"][
        "FundamentalFactsRequestEnvelopeV1"
    ]
    assert facts_envelope["properties"]["input"]["$ref"].endswith("/FactsReadRequestV1")
    assert "FactsReadResponseV1" in str(facts_operation["responses"]["200"])


def test_policy_read_returns_exact_version_and_unknown_policy_is_not_found():
    client = TestClient(create_app())
    response = client.request(
        "GET",
        "/v1/policies/fcff_dcf-us-gaap-public-v1",
        headers=auth_headers(),
        json=make_internal_envelope({}),
    )
    assert response.status_code == 200
    assert response.json()["result"]["policy_id"] == "fcff_dcf-us-gaap-public-v1"
    assert response.json()["result"]["policy_version"] == "fcff_dcf-v1-quality-v1"
    operation = client.app.openapi()["paths"]["/v1/policies/{policy_id}"]["get"]
    assert "requestBody" in operation
    assert "PolicyRecordV1" in str(operation["responses"]["200"])

    missing = client.request(
        "GET",
        "/v1/policies/missing-policy",
        headers=auth_headers(),
        json=make_internal_envelope({}),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "POLICY_NOT_FOUND"


def test_policy_calculation_merges_overrides_and_uses_the_explicit_calculator(
    monkeypatch: pytest.MonkeyPatch,
):
    def reject_provider_io(*args, **kwargs):
        _ = args, kwargs
        raise AssertionError("Fundamental calculation must not perform provider I/O")

    monkeypatch.setattr(urllib.request, "urlopen", reject_provider_io)
    monkeypatch.setattr(socket, "create_connection", reject_provider_io)
    monkeypatch.setattr(asyncio.BaseEventLoop, "create_connection", reject_provider_io)
    monkeypatch.setattr(asyncio.BaseEventLoop, "sock_connect", reject_provider_io)

    base = make_valuation()
    policy = _policy_with_assumptions(base.assumptions)
    registry = PolicyRegistry(models=initial_model_specs(), policies=(policy,))
    client = TestClient(
        create_app(
            _SnapshotRepository(),
            fact_repository=_FactRepository(),
            policy_registry=registry,
        )
    )
    partial = base.model_dump(mode="json")
    partial["assumptions"] = {"terminal_growth": "0"}
    partial["policy_id"] = policy.policy_id

    policy_result = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(partial),
    )
    assert policy_result.status_code == 200, policy_result.text
    policy_body = policy_result.json()["result"]
    assert policy_body["assumptions"]["terminal_growth"] == "0"
    assert not {"operation_id", "session_id", "job_id"}.intersection(policy_body)
    assert (
        policy_body["policy_resolution"]["precedence"]["assumptions.terminal_growth"]
        == "caller"
    )
    assert (
        policy_body["policy_resolution"]["precedence"][
            "assumptions.wacc.risk_free_rate"
        ]
        == "policy"
    )
    assert (
        policy_body["input_digest"] == policy_body["policy_resolution"]["input_digest"]
    )

    repeated = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(partial),
    )
    assert repeated.status_code == 200
    assert repeated.json()["result"]["result_hash"] == policy_body["result_hash"]
    assert (
        repeated.json()["result"]["artifact_references"]
        == policy_body["artifact_references"]
    )

    resolved_assumptions = base.assumptions.model_copy(
        update={"terminal_growth": Decimal(0)}
    )
    explicit = base.model_copy(
        update={
            "assumptions": resolved_assumptions,
            "policy_id": policy.policy_id,
            "provenance": base.provenance.model_copy(
                update={"policy_version": policy.policy_version}
            ),
        }
    ).with_digest()
    explicit_result = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(explicit.model_dump(mode="json")),
    )
    assert explicit_result.status_code == 200, explicit_result.text
    explicit_body = explicit_result.json()["result"]
    assert explicit_body["input_digest"] == policy_body["input_digest"]
    assert explicit_body["result_hash"] == policy_body["result_hash"]
    assert explicit_body["per_share_value"] == policy_body["per_share_value"]
    assert [(node["node_id"], node["value"]) for node in explicit_body["nodes"]] == [
        (node["node_id"], node["value"]) for node in policy_body["nodes"]
    ]

    paths = client.app.openapi()["paths"]
    assert "requestBody" in paths["/v1/valuation/calculate"]["post"]
    assert "requestBody" in paths["/v1/valuation/calculate-with-policy"]["post"]
    calculate_envelope = client.app.openapi()["components"]["schemas"][
        "FundamentalCalculationRequestEnvelopeV1"
    ]
    assert calculate_envelope["properties"]["input"]["$ref"].endswith(
        "/ValuationInputV1"
    )
    assert "UncertaintyReportV1" in str(
        paths["/v1/valuation/calculate"]["post"]["responses"]["200"]
    )
    assert "UncertaintyReportV1" in str(
        paths["/v1/valuation/calculate-with-policy"]["post"]["responses"]["200"]
    )
    policy_envelope = client.app.openapi()["components"]["schemas"][
        "FundamentalPolicyCalculationRequestEnvelopeV1"
    ]
    assert policy_envelope["properties"]["input"]["$ref"].endswith(
        "/PolicyValuationInputV1"
    )


def test_policy_calculation_missing_release_and_unresolved_assumptions_are_stable():
    base = make_valuation()
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    request = base.model_dump(mode="json")
    request["assumptions"] = {"terminal_growth": "0.02"}
    request["policy_id"] = "missing-policy"

    missing = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "POLICY_NOT_FOUND"

    unsupported = base.model_dump(mode="json")
    unsupported["assumptions"] = {"terminal_growth": "0.02"}
    unsupported["policy_id"] = "fcff_dcf-us-gaap-public-v1"
    incomplete = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(unsupported),
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "POLICY_ASSUMPTIONS_INCOMPLETE"

    malformed = base.model_dump(mode="json")
    malformed.pop("policy_id")
    invalid = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(malformed),
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_request"


def test_calculate_requires_a_pinned_policy_while_validation_marks_active_selection():
    app = create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    client = TestClient(app)
    request = make_valuation().model_dump(mode="json")

    validation = client.post(
        "/v1/valuation/validate",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )
    assert validation.status_code == 200
    assert (
        validation.json()["result"]["policy_resolution"]["selection_mode"]
        == "exploratory_active"
    )
    assert validation.json()["result"]["quality_status"] == "provisional"
    assert "POLICY_NOT_PINNED_EXPLORATORY" in validation.json()["result"]["issue_codes"]

    calculation = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )
    assert calculation.status_code == 422
    assert calculation.json()["error"]["code"] == "POLICY_ID_REQUIRED"


def test_policy_calculation_executes_uncertainty_and_preserves_full_input_binding():
    base = make_valuation()
    policy = _policy_with_assumptions(base.assumptions)
    registry = PolicyRegistry(models=initial_model_specs(), policies=(policy,))
    client = TestClient(
        create_app(
            _SnapshotRepository(),
            fact_repository=_FactRepository(),
            policy_registry=registry,
        )
    )
    request = base.model_dump(mode="json")
    request.update(
        {
            "policy_id": policy.policy_id,
            "assumptions": {"terminal_growth": "0.02"},
            "uncertainty": {
                "mode": "monte_carlo",
                "samples": 5,
                "seed": 7,
                "invalid_draw_policy": "skip",
                "parameters": [
                    {
                        "path": "assumptions.terminal_growth",
                        "distribution": "uniform",
                        "lower": "0.01",
                        "upper": "0.03",
                    }
                ],
            },
        }
    )
    response = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["requested_samples"] == 5
    assert result["valid_samples"] == 5
    assert result["input_digest"] != result["base"]["policy_resolution"]["input_digest"]
    assert result["input_digest"] != result["base"]["input_digest"]
    calculation_reference = next(
        item
        for item in result["base"]["artifact_references"]
        if item["artifact_type"] == "calculation_evidence"
    )
    calculation_content = client.app.state.application.artifact_content(
        calculation_reference["artifact_id"]
    )[1]
    calculation_evidence = CalculationEvidenceV1.model_validate_json(
        calculation_content
    )
    assert calculation_evidence.request.uncertainty.mode == "none"
    assert calculation_evidence.request.input_digest == result["base"]["input_digest"]
    assert (
        replay_calculation(
            calculation_evidence.request,
            calculation_evidence.calculation,
        ).status
        == "match"
    )
    uncertainty_reference = next(
        item
        for item in result["artifact_references"]
        if item["artifact_type"] == "uncertainty_evidence"
    )
    uncertainty_content = client.app.state.application.artifact_content(
        uncertainty_reference["artifact_id"]
    )[1]
    uncertainty_evidence = UncertaintyEvidenceV1.model_validate_json(
        uncertainty_content
    )
    assert uncertainty_evidence.report.input_digest == result["input_digest"]
    assert (
        uncertainty_evidence.report.base.input_digest == result["base"]["input_digest"]
    )
    assert "caller_approval" not in uncertainty_evidence.request

    explicit_uncertainty = UncertaintyV1.model_validate_json(
        json.dumps(request["uncertainty"])
    )
    explicit = base.model_copy(
        update={
            "policy_id": policy.policy_id,
            "provenance": base.provenance.model_copy(
                update={"policy_version": policy.policy_version}
            ),
            "assumptions": policy.assumptions,
            "uncertainty": explicit_uncertainty,
        }
    ).with_digest()
    explicit_response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(explicit.model_dump(mode="json")),
    )
    assert explicit_response.status_code == 200, explicit_response.text
    explicit_result = explicit_response.json()["result"]
    assert explicit_result["input_digest"] == result["input_digest"]
    assert explicit_result["base"]["input_digest"] == result["base"]["input_digest"]
    assert explicit_result["base"]["result_hash"] == result["base"]["result_hash"]


def test_rejected_caller_approval_never_executes_calculation():
    valuation = _bind_initial_policy(make_valuation())
    payload = valuation.model_dump(mode="json")
    payload["caller_approval"] = {
        "input_digest": valuation.input_digest,
        "decision": "rejected",
        "caller_id": "test-agent",
        "decided_at": datetime.now(UTC).isoformat(),
    }
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CALLER_APPROVAL_REJECTED"


def test_policy_calculation_rejects_unsupported_model_family():
    bank_model = next(
        model
        for model in expansion_model_specs()
        if model.model_id == "bank_excess_return"
    )
    bank_policy = next(
        policy
        for policy in expansion_policy_records()
        if policy.model_id == bank_model.model_id
    )
    request = make_valuation().model_dump(mode="json")
    request.update(
        {
            "model_id": bank_model.model_id,
            "model_version": bank_model.model_version,
            "policy_id": bank_policy.policy_id,
            "assumptions": {},
        }
    )
    client = TestClient(create_app())

    response = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "POLICY_MODEL_UNSUPPORTED"


def test_policy_calculation_maps_repository_outage_to_retryable_unavailable():
    class UnavailablePolicyRepository:
        def get(self, policy_id: str):
            _ = policy_id
            raise RuntimeError("database unavailable")

    registry = PolicyRegistry(
        models=initial_model_specs(), repository=UnavailablePolicyRepository()
    )
    client = TestClient(
        create_app(
            _SnapshotRepository(),
            fact_repository=_FactRepository(),
            policy_registry=registry,
        )
    )
    request = make_valuation().model_dump(mode="json")
    request["policy_id"] = "fcff-policy-v1"

    response = client.post(
        "/v1/valuation/calculate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(request),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True


def test_policy_lookup_preserves_ambiguous_release_error():
    class AmbiguousPolicyRepository:
        def get(self, policy_id: str):
            _ = policy_id
            raise PolicyError("POLICY_AMBIGUOUS", "policy ID has multiple releases")

    registry = PolicyRegistry(
        models=initial_model_specs(), repository=AmbiguousPolicyRepository()
    )
    client = TestClient(create_app(policy_registry=registry))

    response = client.request(
        "GET",
        "/v1/policies/fcff-policy-v1",
        headers=auth_headers(),
        json=make_internal_envelope({}),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "POLICY_AMBIGUOUS"


def test_policy_lookup_without_registry_is_retryable_unavailable():
    client = TestClient(create_app(require_metadata=True))

    response = client.request(
        "GET",
        "/v1/policies/fcff-policy-v1",
        headers=auth_headers(),
        json=make_internal_envelope({}),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "POLICY_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True


def test_new_internal_routes_reject_missing_or_invalid_signed_context():
    client = TestClient(create_app())
    missing_context = client.get(
        "/v1/policies/fcff_dcf-us-gaap-public-v1",
        headers=auth_headers(),
    )
    assert missing_context.status_code == 400
    assert missing_context.json()["error"]["code"] == "invalid_request"

    invalid_context = make_internal_envelope({})
    invalid_context["context"]["signature"] = "0" * 64
    response = client.request(
        "GET",
        "/v1/policies/fcff_dcf-us-gaap-public-v1",
        headers=auth_headers(),
        json=invalid_context,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_context_signature_invalid"


def test_sec_ingestion_route_requires_a_valid_signed_context():
    client = TestClient(create_app())
    missing_context = client.post(
        "/v1/data/ingestions",
        headers=auth_headers(),
        json={"input": {}},
    )
    assert missing_context.status_code == 400
    assert missing_context.json()["error"]["code"] == "invalid_request"

    invalid_context = make_internal_envelope({})
    invalid_context["context"]["signature"] = "0" * 64
    rejected = client.post(
        "/v1/data/ingestions",
        headers=auth_headers(),
        json=invalid_context,
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "internal_context_signature_invalid"


def test_uncertainty_endpoint_runs_the_shared_calculator():
    payload = _bind_initial_policy(make_valuation()).model_dump(mode="json")
    payload["scenarios"] = [
        {"name": "base", "assumptions": {}},
        {"name": "downside", "assumptions": {"assumptions.terminal_growth": "0.01"}},
        {"name": "upside", "assumptions": {"assumptions.terminal_growth": "0.03"}},
    ]
    payload["sensitivity"] = [
        {"path": "assumptions.terminal_growth", "values": ["0.01", "0.03"]}
    ]
    payload["monte_carlo"] = {
        "uncertainty": {
            "mode": "monte_carlo",
            "samples": 10,
            "seed": 7,
            "invalid_draw_policy": "skip",
            "parameters": [
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": "0.01",
                    "upper": "0.03",
                }
            ],
        }
    }
    payload = _with_uncertainty_digest(payload).model_dump(mode="json")
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "internal.v1"
    assert body["schema_version"] == "fundamental.v1"
    assert body["result"]["valid_samples"] == 10
    assert body["result"]["scenario_results"]


def test_uncertainty_approval_digest_covers_sampling_and_scenario_controls():
    valuation = _bind_initial_policy(make_valuation())
    payload = valuation.model_dump(mode="json")
    payload.update(
        {
            "scenarios": [
                {"name": "base", "assumptions": {}},
                {
                    "name": "downside",
                    "assumptions": {"assumptions.terminal_growth": "0.01"},
                },
                {
                    "name": "upside",
                    "assumptions": {"assumptions.terminal_growth": "0.03"},
                },
            ],
            "sensitivity": [],
            "monte_carlo": {
                "uncertainty": {
                    "mode": "monte_carlo",
                    "samples": 10,
                    "seed": 7,
                    "invalid_draw_policy": "skip",
                    "parameters": [
                        {
                            "path": "assumptions.terminal_growth",
                            "distribution": "uniform",
                            "lower": "0.01",
                            "upper": "0.03",
                        }
                    ],
                },
                "sampler_version": "python-random-v1",
            },
        }
    )
    payload["uncertainty"] = {
        "mode": "monte_carlo",
        "samples": 10,
        "seed": 7,
        "invalid_draw_policy": "skip",
        "parameters": [
            {
                "path": "assumptions.terminal_growth",
                "distribution": "uniform",
                "lower": "0.01",
                "upper": "0.03",
            }
        ],
    }
    request = _with_uncertainty_digest(payload)
    changed = request.model_dump(mode="json")
    changed["monte_carlo"]["uncertainty"]["seed"] = 8
    with pytest.raises(ValidationError):
        UncertaintyRequestV1.model_validate_json(json.dumps(changed))

    payload = request.model_dump(mode="json")
    payload["caller_approval"] = {
        "input_digest": request.input_digest,
        "decision": "approved",
        "caller_id": "test-agent",
        "decided_at": datetime.now(UTC).isoformat(),
    }
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["base"]["input_digest"] != request.input_digest
    assert result["input_digest"] == request.input_digest
    assert result["valid_samples"] == 10


def test_calculate_executes_explicit_monte_carlo_controls_with_optional_approval():
    valuation = (
        make_valuation()
        .model_copy(
            update={
                "uncertainty": UncertaintyV1(
                    mode="monte_carlo",
                    samples=5,
                    seed=7,
                    invalid_draw_policy="skip",
                    parameters=(
                        {
                            "path": "assumptions.terminal_growth",
                            "distribution": "uniform",
                            "lower": Decimal("0.01"),
                            "upper": Decimal("0.03"),
                        },
                    ),
                ),
            }
        )
        .with_digest()
    )
    valuation = _bind_initial_policy(valuation)
    payload = valuation.model_dump(mode="json")
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["requested_samples"] == 5
    assert result["valid_samples"] == 5
    assert result["input_digest"] == valuation.input_digest
    assert result["base"]["input_digest"] != valuation.input_digest
    assert (
        result["base"]["policy_resolution"]["input_digest"]
        == result["base"]["input_digest"]
    )

    approved = valuation.model_copy(
        update={
            "caller_approval": CallerApprovalEnvelopeV1(
                input_digest=valuation.input_digest,
                decision="approved",
                caller_id="test-agent",
                decided_at=datetime.now(UTC),
            )
        }
    )
    approved_response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(approved.model_dump(mode="json")),
    )
    assert approved_response.status_code == 200, approved_response.text
    assert (
        approved_response.json()["result"]["base"]["result_hash"]
        == result["base"]["result_hash"]
    )


def test_calculate_rejects_scenario_mode_without_executable_controls():
    request = _bind_initial_policy(
        make_valuation()
        .model_copy(update={"uncertainty": UncertaintyV1(mode="scenarios")})
        .with_digest()
    )
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(request.model_dump(mode="json")),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNCERTAINTY_INVALID"


def test_calculate_returns_version_bound_replayable_evidence():
    app = create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    client = TestClient(app)
    validation = app.state.application.validate_valuation(make_valuation())
    request = validation.input.model_copy(
        update={
            "caller_approval": CallerApprovalEnvelopeV1(
                input_digest=validation.input_digest,
                decision="approved",
                caller_id="test-agent",
                decided_at=datetime.now(UTC),
            )
        }
    )
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(request.model_dump(mode="json")),
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["policy_id"] == validation.policy_resolution.policy_id
    assert result["policy_version"] == validation.policy_resolution.policy_version
    assert result["trace"]["snapshot_manifest_digest"] == "b" * 64
    assert (
        result["trace"]["policy_digest"] == validation.policy_resolution.policy_digest
    )
    references = result["artifact_references"]
    assert len(references) == 1
    reference = references[0]
    record, content = app.state.application.artifact_content(reference["artifact_id"])
    assert record.content_hash == reference["content_hash"]
    assert hashlib.sha256(content).hexdigest() == reference["content_hash"]
    evidence = CalculationEvidenceV1.model_validate_json(content)
    assert evidence.calculation.result_hash == result["result_hash"]
    assert (
        evidence.calculation.trace.policy_digest
        == validation.policy_resolution.policy_digest
    )
    assert evidence.request.caller_approval is None
    assert json.loads(content)["request"]["caller_approval"] is None


def test_uncertainty_accepts_the_validated_request_and_same_caller_approval():
    valuation = (
        make_valuation()
        .model_copy(
            update={
                "uncertainty": UncertaintyV1(
                    mode="monte_carlo",
                    samples=5,
                    seed=7,
                    invalid_draw_policy="skip",
                    parameters=(
                        {
                            "path": "assumptions.terminal_growth",
                            "distribution": "uniform",
                            "lower": Decimal("0.01"),
                            "upper": Decimal("0.03"),
                        },
                    ),
                ),
            }
        )
        .with_digest()
    )
    valuation = _bind_initial_policy(valuation)
    payload = valuation.model_dump(mode="json")
    payload["monte_carlo"] = {
        "uncertainty": payload["uncertainty"],
        "sampler_version": "python-random-v1",
    }
    request = _with_uncertainty_digest(payload)
    payload = request.model_dump(mode="json")
    payload["caller_approval"] = {
        "input_digest": request.input_digest,
        "decision": "approved",
        "caller_id": "test-agent",
        "decided_at": datetime.now(UTC).isoformat(),
    }
    response = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    ).post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200
    assert response.json()["result"]["base"]["snapshot_id"] == "snapshot-1"


def test_liveness_is_public_and_readiness_requires_all_runtime_dependencies(
    tmp_path: Path,
):
    client = TestClient(
        create_app(
            _SnapshotRepository(),
            ArtifactStore(tmp_path / "artifacts"),
            FilesystemContentStore(tmp_path / "content"),
            fact_repository=_FactRepository(),
            config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
        )
    )
    assert client.get("/livez").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"contract_version": "internal.v1", "status": "ready"}


def test_production_readiness_requires_deployment_model_trust_roots(tmp_path: Path):
    common = {
        "snapshot_repository": _SnapshotRepository(),
        "artifact_store": ArtifactStore(tmp_path / "artifacts"),
        "content_store": FilesystemContentStore(tmp_path / "content"),
        "fact_repository": _FactRepository(),
        "config": OperationsConfig(service_token=TEST_SERVICE_TOKEN),
        "metadata_store": SimpleNamespace(ready=True),
        "require_metadata": True,
    }
    missing_roots = create_app(**common, model_inventory=ModelInventory())
    assert missing_roots.state.application.ready is False

    trust_roots_file = (
        Path(__file__).parent / "fixtures" / "development" / "model-trust-roots.json"
    )
    inventory = ModelInventory.from_deployment_file(
        expansion_model_specs(), trust_roots_file
    )
    configured_roots = create_app(**common, model_inventory=inventory)
    assert configured_roots.state.application.ready is True


def test_runtime_injects_deployment_data_release_trust_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from fundamental_service import app as fundamental_app
    from fundamental_service.data_releases import DataReleaseTrustRootsV1

    trust_roots_file = tmp_path / "data-release-trust-roots.json"
    trust_roots_file.write_text(
        json.dumps(
            {
                "verifiers": {
                    "release-ci": {
                        "workflow_identity": "github://example/release.yml",
                        "public_key_ed25519_base64": "W2SJycf9Dc9QVF58FkiG70BJHsBsfxsSMEF5foEXU14=",
                        "verification_suite_digest": "a" * 64,
                    }
                },
                "mapping_reviewers": {
                    "reviewer-1": "tfkAlTGPPwRM2OQLWEJT2Gd3vmK/ByITNOX9IZnPp/c="
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv(
        "FUNDAMENTAL_SERVICE_DATABASE_URL",
        "postgresql+asyncpg://fundamental:fundamental@localhost/fundamental",
    )
    monkeypatch.setenv(
        "FUNDAMENTAL_DATA_RELEASE_TRUST_ROOTS_FILE", str(trust_roots_file)
    )

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        fundamental_app,
        "PostgresMetadataStore",
        lambda *_, **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setattr(
        fundamental_app.ModelInventory,
        "from_deployment_file",
        lambda *_args: object(),
    )
    for name in (
        "PostgresSnapshotRepository",
        "PostgresCanonicalFactRepository",
        "PostgresContentStore",
        "PostgresArtifactStore",
        "MetadataModelRepository",
        "MetadataPolicyRepository",
        "PolicyRegistry",
    ):
        monkeypatch.setattr(fundamental_app, name, lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        fundamental_app, "build_runtime_sec_acquisition", lambda **_kwargs: object()
    )
    monkeypatch.setattr(fundamental_app, "create_app", lambda **kwargs: kwargs)

    composed = create_runtime_app()

    roots = DataReleaseTrustRootsV1.from_file(trust_roots_file)
    assert captured["data_release_trust_roots"] == roots
    assert composed["metadata_store"] is not None


def test_snapshot_resolution_pins_only_active_release_facts():
    snapshot = _SnapshotRepository().snapshot
    snapshot.parser_version = "arelle-release==2.47.4"
    snapshot.taxonomy_manifest_id = "taxonomy-v1"
    fact = _canonical_fact("fact-revenue", "revenue")
    fact_ref = {
        "fact_id": fact.fact_id,
        "fact_digest": sha256_digest(fact.model_dump(mode="json")),
    }
    snapshot_ref = {
        "snapshot_id": snapshot.snapshot_id,
        "manifest_digest": snapshot.manifest_digest,
        "facts": (fact_ref,),
        "fact_set_digest": sha256_digest((fact_ref,)),
    }
    manifest_payload = {
        "profile_id": "sec-public-pit-v1",
        "release_id": "release-1",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "snapshot_refs": (snapshot_ref,),
        "mapping_refs": (
            MappingRefV1(mapping_id="mapping-1", mapping_digest="c" * 64),
        ),
        "taxonomy_refs": (
            ArtifactRefV1(
                artifact_id="taxonomy-1",
                content_hash="d" * 64,
                media_type="application/zip",
                role="taxonomy",
            ),
        ),
        "parser_version": "arelle-release==2.47.4",
        "quality_profile_digest": "e" * 64,
        "required_fields": ("revenue",),
        "artifact_refs": (
            ArtifactRefV1(
                artifact_id="quality-1",
                content_hash="f" * 64,
                media_type="application/json",
                role="quality-evidence",
            ),
        ),
    }
    manifest = DataReleaseManifestV1(
        **manifest_payload,
        manifest_digest=sha256_digest(manifest_payload),
    )
    active_release = ActiveDataReleaseWithManifestV1(
        active=ActiveDataReleaseV1(
            profile_id=manifest.profile_id,
            manifest_digest=manifest.manifest_digest,
            revision=3,
            activated_at=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        manifest=manifest,
    )
    decoy = SimpleNamespace(
        **{
            **snapshot.__dict__,
            "snapshot_id": "snapshot-outside-release",
            "manifest_digest": "9" * 64,
        }
    )
    active_release_state = {"value": active_release}
    metadata = SimpleNamespace(
        get_active_data_release_with_manifest=lambda profile_id: (
            active_release_state["value"] if profile_id == manifest.profile_id else None
        )
    )
    app = create_app(
        _ReleaseSnapshotRepository(decoy, snapshot),
        fact_repository=_FactRepository(),
        metadata_store=metadata,
        config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
    )
    request = SnapshotResolutionRequestV1(
        contract_version="fundamental.v1",
        release_profile_id=manifest.profile_id,
        identity=snapshot.identity,
        valuation_timestamp=snapshot.valuation_timestamp,
        source_selection_policy="pit-v1",
        coverage_profile="us-gaap-public-v1",
        required_fields=("revenue",),
    )

    response = TestClient(app).post(
        "/v1/data/snapshots/resolve",
        headers=auth_headers(),
        json=make_internal_envelope(request.model_dump(mode="json")),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["snapshot_id"] == snapshot.snapshot_id
    assert result["historical_facts"] == [fact.fact_id]
    assert result["data_release_manifest_digest"] == manifest.manifest_digest

    undeclared_fact = FactRefV1(fact_id="fact-outside-release", fact_digest="0" * 64)
    bad_snapshot_ref = SnapshotRefV1(
        snapshot_id=snapshot.snapshot_id,
        manifest_digest=snapshot.manifest_digest,
        facts=(undeclared_fact,),
        fact_set_digest=sha256_digest((undeclared_fact,)),
    )
    bad_manifest_payload = manifest.model_dump(
        mode="python", exclude={"manifest_digest"}
    )
    bad_manifest_payload["snapshot_refs"] = (bad_snapshot_ref,)
    bad_manifest = DataReleaseManifestV1(
        **bad_manifest_payload,
        manifest_digest=sha256_digest(bad_manifest_payload),
    )
    active_release_state["value"] = ActiveDataReleaseWithManifestV1(
        active=ActiveDataReleaseV1(
            profile_id=bad_manifest.profile_id,
            manifest_digest=bad_manifest.manifest_digest,
            revision=4,
            activated_at=datetime(2026, 1, 3, tzinfo=UTC),
        ),
        manifest=bad_manifest,
    )
    mismatch = TestClient(app).post(
        "/v1/data/snapshots/resolve",
        headers=auth_headers(),
        json=make_internal_envelope(request.model_dump(mode="json")),
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "DATA_RELEASE_FACT_MISMATCH"


def test_release_fact_verification_ignores_point_in_time_selection_annotations():
    snapshot = _SnapshotRepository().snapshot
    fact = _canonical_fact("fact-revenue", "revenue")
    manifest = _release_manifest_for(snapshot, (fact,))
    selected = fact.model_copy(
        update={
            "rejected_candidates": ("fact-older",),
            "point_in_time_policy": "pit-v1",
            "selection_reason": "latest_available_after_fact_key_point_in_time_selection",
        }
    )

    FundamentalApplication._verify_release_snapshot_and_facts(
        manifest,
        snapshot,
        (selected,),
        required_fields=("revenue",),
    )

    assert (
        canonical_fact_digest(selected)
        == manifest.snapshot_refs[0].facts[0].fact_digest
    )


def test_facts_calculation_evidence_and_replay_keep_the_pinned_release(
    tmp_path: Path,
):
    snapshot = _SnapshotRepository().snapshot
    fact = _canonical_fact("fact-revenue", "revenue")
    manifest = _release_manifest_for(snapshot, (fact,))
    metadata = SimpleNamespace(
        get_data_release_manifest=lambda digest: (
            manifest if digest == manifest.manifest_digest else None
        )
    )
    app = create_app(
        snapshot_repository=_SnapshotRepository(),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        content_store=FilesystemContentStore(tmp_path / "content"),
        fact_repository=_CanonicalFactRepository(),
        metadata_store=metadata,
        config=OperationsConfig(service_token=TEST_SERVICE_TOKEN),
    )
    read_facts = app.state.application.read_facts(
        FactsReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=snapshot.snapshot_id,
            data_release_manifest_digest=manifest.manifest_digest,
            required_fields=("revenue",),
        )
    )
    assert read_facts.data_release_manifest_digest == manifest.manifest_digest
    assert tuple(item.fact_id for item in read_facts.facts) == (fact.fact_id,)

    valuation = make_valuation()
    valuation = valuation.model_copy(
        update={
            "historical_facts": (fact.fact_id,),
            "valuation_context": valuation.valuation_context.model_copy(
                update={"data_release_manifest_digest": manifest.manifest_digest}
            ),
            "provenance": valuation.provenance.model_copy(
                update={"fact_ids": (fact.fact_id,)}
            ),
            "input_digest": None,
        }
    ).with_digest()
    request = _bind_initial_policy(valuation)
    response = TestClient(app).post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(request.model_dump(mode="json")),
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["trace"]["data_release_manifest_digest"] == manifest.manifest_digest
    reference = result["artifact_references"][0]
    record, content = app.state.application.artifact_content(reference["artifact_id"])
    assert manifest.manifest_digest in record.dependency_hashes
    evidence = CalculationEvidenceV1.model_validate_json(content)
    assert (
        evidence.request.valuation_context.data_release_manifest_digest
        == manifest.manifest_digest
    )

    replay = replay_calculation(
        request,
        CalculationArtifactV1.model_validate_json(json.dumps(result)),
    )
    assert replay.status == "match"
    assert replay.dependency_versions["data_release"] == manifest.manifest_digest


def test_snapshot_resolution_cache_isolated_by_active_release_dependencies():
    first_snapshot = _SnapshotRepository().snapshot
    first_snapshot.snapshot_id = "snapshot-cache-one"
    first_snapshot.manifest_digest = "a" * 64
    first_snapshot.parser_version = "arelle-release==2.47.4"
    first_snapshot.taxonomy_manifest_id = "taxonomy-v1"
    second_snapshot = _SnapshotRepository().snapshot
    second_snapshot.snapshot_id = "snapshot-cache-two"
    second_snapshot.manifest_digest = "b" * 64
    second_snapshot.parser_version = "arelle-release==2.47.4"
    second_snapshot.taxonomy_manifest_id = "taxonomy-v1"
    first_fact = _canonical_fact("fact-cache-one", "revenue")
    second_fact = _canonical_fact("fact-cache-two", "revenue")
    facts_by_snapshot = {
        first_snapshot.snapshot_id: (first_fact,),
        second_snapshot.snapshot_id: (second_fact,),
    }
    manifest_one = _release_manifest_for(first_snapshot, (first_fact,))
    manifest_two = _release_manifest_for(second_snapshot, (second_fact,))
    active_state = {
        "value": ActiveDataReleaseWithManifestV1(
            active=ActiveDataReleaseV1(
                profile_id=manifest_one.profile_id,
                manifest_digest=manifest_one.manifest_digest,
                revision=1,
                activated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            manifest=manifest_one,
        )
    }
    metadata = SimpleNamespace(
        get_active_data_release_with_manifest=lambda profile_id: (
            active_state["value"] if profile_id == manifest_one.profile_id else None
        )
    )
    fact_repository = SimpleNamespace(
        resolve=lambda *, snapshot, valuation_timestamp, required_fields: (
            facts_by_snapshot[snapshot.snapshot_id]
        )
    )
    app = create_app(
        _ReleaseSnapshotRepository(first_snapshot, second_snapshot),
        fact_repository=fact_repository,
        metadata_store=metadata,
    )
    request = SnapshotResolutionRequestV1(
        contract_version="fundamental.v1",
        identity=first_snapshot.identity,
        valuation_timestamp=first_snapshot.valuation_timestamp,
        source_selection_policy="pit-v1",
        coverage_profile="us-gaap-public-v1",
        required_fields=("revenue",),
        release_profile_id=manifest_one.profile_id,
    )

    first = app.state.application.resolve_snapshot(request)
    repeated = app.state.application.resolve_snapshot(request)
    assert first.snapshot_id == first_snapshot.snapshot_id
    assert repeated == first
    assert "fundamental_service_cache_hit_total 1" in (
        app.state.metrics.render_prometheus()
    )

    active_state["value"] = ActiveDataReleaseWithManifestV1(
        active=ActiveDataReleaseV1(
            profile_id=manifest_two.profile_id,
            manifest_digest=manifest_two.manifest_digest,
            revision=2,
            activated_at=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        manifest=manifest_two,
    )
    after_activation = app.state.application.resolve_snapshot(request)
    assert after_activation.snapshot_id == second_snapshot.snapshot_id
    assert after_activation.data_release_manifest_digest == manifest_two.manifest_digest
    assert "fundamental_service_cache_miss_total 2" in (
        app.state.metrics.render_prometheus()
    )


def test_production_fact_reads_require_a_pinned_release_digest():
    snapshot = _SnapshotRepository().snapshot
    manifest = _release_manifest_for(
        snapshot, (_canonical_fact("fact-revenue", "revenue"),)
    )
    metadata = SimpleNamespace(
        get_data_release_manifest=lambda digest: (
            manifest if digest == manifest.manifest_digest else None
        )
    )
    app = create_app(
        snapshot_repository=_SnapshotRepository(),
        fact_repository=_CanonicalFactRepository(),
        metadata_store=metadata,
        require_metadata=True,
    )

    response = TestClient(app).request(
        "GET",
        "/v1/data/facts",
        headers=auth_headers(),
        json=make_internal_envelope(
            {
                "contract_version": "fundamental.v1",
                "snapshot_id": snapshot.snapshot_id,
                "required_fields": ["revenue"],
            }
        ),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATA_RELEASE_MANIFEST_REQUIRED"


def test_data_release_operations_are_signed_authorized_and_compare_and_swap():
    metadata = _DataReleaseMetadata()
    client = TestClient(
        create_app(
            config=OperationsConfig(
                service_token=TEST_SERVICE_TOKEN,
                rate_limit_per_minute=10_000,
                release_publish_authorized_organizations=frozenset({"publisher"}),
                release_activation_authorized_organizations=frozenset({"operator"}),
            ),
            metadata_store=metadata,
            require_metadata=True,
        )
    )
    fact = _canonical_fact("fact-revenue", "revenue")
    first_snapshot = _SnapshotRepository().snapshot
    second_snapshot = _SnapshotRepository().snapshot
    second_snapshot.snapshot_id = "snapshot-release-two"
    second_snapshot.manifest_digest = "9" * 64
    rejected_snapshot = _SnapshotRepository().snapshot
    rejected_snapshot.snapshot_id = "snapshot-rejected"
    rejected_snapshot.manifest_digest = "8" * 64
    first = _release_manifest_for(first_snapshot, (fact,))
    second = _release_manifest_for(second_snapshot, (fact,))
    rejected = _release_manifest_for(rejected_snapshot, (fact,))

    denied = client.post(
        "/v1/data/releases/candidates",
        headers=auth_headers(organization_id="operator"),
        json=make_internal_envelope(
            {
                "manifest": first.model_dump(mode="json"),
                "verification": _release_verification_for(first).model_dump(
                    mode="json"
                ),
            },
            organization_id="operator",
        ),
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "DATA_RELEASE_FORBIDDEN"
    assert metadata.candidates == {}

    published = client.post(
        "/v1/data/releases/candidates",
        headers=auth_headers(organization_id="publisher"),
        json=make_internal_envelope(
            {
                "manifest": first.model_dump(mode="json"),
                "verification": _release_verification_for(first).model_dump(
                    mode="json"
                ),
            },
            organization_id="publisher",
        ),
    )
    assert published.status_code == 200, published.text
    assert published.json()["result"]["manifest_digest"] == first.manifest_digest

    activation = {
        "manifest_digest": first.manifest_digest,
        "expected_revision": 0,
        "expected_manifest_digest": None,
        "operation": "activate",
        "command_id": "activation-one",
        "reason": "Initial release acceptance",
    }
    activated = client.post(
        f"/v1/data/releases/{first.profile_id}/activate",
        headers=auth_headers(organization_id="operator"),
        json=make_internal_envelope(activation, organization_id="operator"),
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["result"]["active"]["revision"] == 1
    assert metadata.commands[-1].actor_id == "subject-test"
    assert metadata.commands[-1].organization_id == "operator"
    assert metadata.commands[-1].correlation_id == "correlation-test"

    active_read = client.request(
        "GET",
        f"/v1/data/releases/{first.profile_id}",
        headers=auth_headers(organization_id="operator"),
        json=make_internal_envelope({}, organization_id="operator"),
    )
    assert active_read.status_code == 200
    assert active_read.json()["result"]["manifest"]["manifest_digest"] == (
        first.manifest_digest
    )

    metadata.rejected_candidates.add(rejected.manifest_digest)
    rejected_response = client.post(
        "/v1/data/releases/candidates",
        headers=auth_headers(organization_id="publisher"),
        json=make_internal_envelope(
            {
                "manifest": rejected.model_dump(mode="json"),
                "verification": _release_verification_for(rejected).model_dump(
                    mode="json"
                ),
            },
            organization_id="publisher",
        ),
    )
    assert rejected_response.status_code == 422
    unchanged = metadata.get_active_data_release_with_manifest(first.profile_id)
    assert unchanged is not None
    assert unchanged.active.revision == 1
    assert unchanged.active.manifest_digest == first.manifest_digest

    second_publish = client.post(
        "/v1/data/releases/candidates",
        headers=auth_headers(organization_id="publisher"),
        json=make_internal_envelope(
            {
                "manifest": second.model_dump(mode="json"),
                "verification": _release_verification_for(second).model_dump(
                    mode="json"
                ),
            },
            organization_id="publisher",
        ),
    )
    assert second_publish.status_code == 200, second_publish.text

    stale_activation = {
        **activation,
        "manifest_digest": second.manifest_digest,
        "command_id": "activation-stale",
    }
    stale = client.post(
        f"/v1/data/releases/{first.profile_id}/activate",
        headers=auth_headers(organization_id="operator"),
        json=make_internal_envelope(stale_activation, organization_id="operator"),
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "DATA_RELEASE_POINTER_CONFLICT"

    second_activation = {
        **stale_activation,
        "expected_revision": 1,
        "expected_manifest_digest": first.manifest_digest,
        "command_id": "activation-two",
    }
    activated_second = client.post(
        f"/v1/data/releases/{first.profile_id}/activate",
        headers=auth_headers(organization_id="operator"),
        json=make_internal_envelope(second_activation, organization_id="operator"),
    )
    assert activated_second.status_code == 200, activated_second.text
    assert activated_second.json()["result"]["active"]["manifest_digest"] == (
        second.manifest_digest
    )

    rollback = {
        **second_activation,
        "manifest_digest": first.manifest_digest,
        "expected_revision": 2,
        "expected_manifest_digest": second.manifest_digest,
        "operation": "rollback",
        "command_id": "rollback-one",
        "reason": "Restore prior verified release",
    }
    rolled_back = client.post(
        f"/v1/data/releases/{first.profile_id}/rollback",
        headers=auth_headers(organization_id="operator"),
        json=make_internal_envelope(rollback, organization_id="operator"),
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["result"]["active"]["revision"] == 3
    assert rolled_back.json()["result"]["active"]["manifest_digest"] == (
        first.manifest_digest
    )

    schema = client.app.openapi()
    assert "FundamentalDataReleaseCandidateRequestEnvelopeV1" in str(schema)
    assert "FundamentalDataReleaseLookupRequestEnvelopeV1" in str(schema)
    assert "FundamentalDataReleaseActivationRequestEnvelopeV1" in str(schema)
    metrics = client.get("/metrics").text
    assert "fundamental_service_data_release_candidate_publish_total 2" in metrics
    assert "fundamental_service_data_release_activation_total 2" in metrics
    assert "fundamental_service_data_release_rollback_total 1" in metrics


def test_internal_endpoints_require_signed_context_and_redact_credentials():
    client = TestClient(
        create_app(config=OperationsConfig(service_token="super-secret-token"))
    )
    response = client.request(
        "GET",
        "/v1/data/snapshots/snapshot-1",
        json={"context": {}, "input": {}},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "internal_auth_missing"
    assert "super-secret-token" not in response.text
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]


def test_expired_deadline_and_calculation_budget_are_stable_errors():
    value = make_valuation().model_dump(mode="json")
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    expired = client.post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(
            _with_uncertainty_digest(
                {
                    **_bind_initial_policy(make_valuation()).model_dump(mode="json"),
                    "scenarios": [],
                    "sensitivity": [],
                    "monte_carlo": None,
                }
            ).model_dump(mode="json"),
            deadline_at=datetime(2020, 1, 1, tzinfo=UTC),
            issued_at=datetime(2019, 1, 1, tzinfo=UTC),
        ),
    )
    assert expired.status_code == 408
    assert expired.json()["error"]["code"] == "REQUEST_DEADLINE_EXCEEDED"

    limited = TestClient(
        create_app(
            _SnapshotRepository(),
            fact_repository=_FactRepository(),
            config=OperationsConfig(
                service_token=TEST_SERVICE_TOKEN, max_calculation_samples=2
            ),
        )
    )
    value = _bind_initial_policy(make_valuation()).model_dump(mode="json")
    value["monte_carlo"] = {
        "uncertainty": {
            "mode": "monte_carlo",
            "samples": 3,
            "seed": 7,
            "invalid_draw_policy": "skip",
            "parameters": [
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": "0.01",
                    "upper": "0.03",
                }
            ],
        }
    }
    value = _with_uncertainty_digest(value).model_dump(mode="json")
    budget = limited.post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(value),
    )
    assert budget.status_code == 422
    assert budget.json()["error"]["code"] == "CALCULATION_BUDGET_EXCEEDED"


def test_calculation_dependency_outage_is_unavailable_without_local_fallback():
    client = TestClient(create_app())
    valuation = _bind_initial_policy(make_valuation())
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=make_internal_envelope(valuation.model_dump(mode="json")),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "source_unavailable"


def test_validation_rejects_fact_outside_selected_snapshot():
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_ForeignFactRepository())
    )
    response = client.post(
        "/v1/valuation/validate",
        headers=auth_headers(),
        json=make_internal_envelope(make_valuation().model_dump(mode="json")),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FACT_PROVENANCE_MISMATCH"


@pytest.mark.parametrize(
    ("lifecycle", "release_manifest", "expected_issue"),
    (
        ("retired", None, "MODEL_NOT_ACTIVE"),
        ("active", None, "MODEL_RELEASE_EVIDENCE_MISSING"),
    ),
)
def test_unreleased_model_is_unsupported_before_snapshot_reads(
    lifecycle: str, release_manifest: str | None, expected_issue: str
):
    # Exercise the request gate against registry state that bypassed model validation.
    model = initial_model_specs()[0].model_copy(
        update={"lifecycle": lifecycle, "release_manifest": release_manifest}
    )
    registry = PolicyRegistry(models=(model,), policies=(initial_policy_records()[0],))

    class SnapshotRepository:
        def get(self, snapshot_id: str):
            raise AssertionError(f"unreleased model read snapshot {snapshot_id}")

    class FactRepository:
        def get(self, fact_id: str):
            raise AssertionError(f"unreleased model read fact {fact_id}")

    client = TestClient(
        create_app(
            SnapshotRepository(),
            fact_repository=FactRepository(),
            policy_registry=registry,
        )
    )
    payload = make_valuation().model_dump(mode="json")
    envelope = make_internal_envelope(payload)

    validation = client.post(
        "/v1/valuation/validate", headers=auth_headers(), json=envelope
    )
    assert validation.status_code == 200
    validation_result = validation.json()["result"]
    assert validation_result["quality_status"] == "unsupported"
    assert expected_issue in validation_result["issue_codes"]

    calculation = client.post(
        "/v1/valuation/calculate", headers=auth_headers(), json=envelope
    )
    assert calculation.status_code == 422
    assert calculation.json()["error"]["code"] == "MODEL_UNSUPPORTED"

    uncertainty_payload = {
        **payload,
        "scenarios": [],
        "sensitivity": [],
        "monte_carlo": {
            "uncertainty": {
                "mode": "monte_carlo",
                "samples": 10,
                "seed": 17,
                "invalid_draw_policy": "skip",
                "parameters": [
                    {
                        "path": "assumptions.terminal_growth",
                        "distribution": "uniform",
                        "lower": "0.01",
                        "upper": "0.03",
                    }
                ],
            },
            "sampler_version": "python-random-v1",
        },
    }
    uncertainty = client.post(
        "/v1/valuation/uncertainty",
        headers=auth_headers(),
        json=make_internal_envelope(uncertainty_payload),
    )
    assert uncertainty.status_code == 422
    assert uncertainty.json()["error"]["code"] == "MODEL_UNSUPPORTED"


def test_valid_bearer_without_signed_context_is_rejected():
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    response = client.post(
        "/v1/valuation/calculate",
        headers={"Authorization": f"Bearer {TEST_SERVICE_TOKEN}"},
        json={"input": make_valuation().model_dump(mode="json")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_signed_context_claims_are_bound_to_audience_and_organization():
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    payload = make_valuation().model_dump(mode="json")
    wrong_audience = make_internal_envelope(payload, audience="search-service")
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=wrong_audience,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_context_claims_invalid"

    mismatched_org = make_internal_envelope(payload)
    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(organization_id="organization-attacker"),
        json=mismatched_org,
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_context_organization_mismatch"


def test_signed_context_rejects_invalid_signature():
    client = TestClient(
        create_app(_SnapshotRepository(), fact_repository=_FactRepository())
    )
    envelope = make_internal_envelope(make_valuation().model_dump(mode="json"))
    envelope["context"]["signature"] = "0" * 64

    response = client.post(
        "/v1/valuation/calculate",
        headers=auth_headers(),
        json=envelope,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "internal_context_signature_invalid"


def test_artifact_survives_store_restart_and_cache_reset(tmp_path: Path):
    first = ArtifactStore(tmp_path / "artifacts")
    record = first.put("release-1", {"result": "immutable"})
    first.reset_operational_cache()
    second = ArtifactStore(tmp_path / "artifacts")
    assert second.get(record.artifact_id) == record
    assert second.read(record.artifact_id) == b'{"result":"immutable"}'


def test_metrics_declare_operational_quality_and_dependency_signals():
    body = TestClient(create_app()).get("/metrics").text
    for metric in (
        "source_health_failures_total",
        "snapshot_freshness_failures_total",
        "cache_hit_total",
        "cache_miss_total",
        "cache_stale_total",
        "calculation_latency_ms_total",
        "calculation_budget_failures_total",
        "quality_status_total",
        "abstention_total",
        "provenance_replay_failures_total",
        "provider_degradation_total",
    ):
        assert f"fundamental_service_{metric}" in body
