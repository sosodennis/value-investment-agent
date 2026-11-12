"""Synthetic signatures exercise issuer trust boundaries, never real approval."""

import hashlib
import io
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from fundamental_service.accounting_roles import (
    AccountingRoleRuleSetV1,
    IssuerAccountingRoleRuleSetV1,
)
from fundamental_service.arelle_parser import (
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    fact_semantic_digest,
)
from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseManifestV1,
    FactRefV1,
    IssuerOperatingReleaseManifestV1,
    MappingRefV1,
    SnapshotRefV1,
    sign_data_release_verification,
    sign_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1, canonical_fact_digest
from fundamental_service.issuer_operating_release import (
    IssuerOperatingReleaseBundleV1,
    IssuerOperatingReleaseService,
)
from fundamental_service.issuer_release_evidence import original_rebuilt_facts
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.snapshots import SnapshotError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_requirements import (
    composite_working_capital_requirements_profile,
    operating_forecast_requirements_profile,
)
from fundamental_service.working_capital import (
    CompositeWorkingCapitalInputV1,
    InclusionScenariosV1,
    WorkingCapitalExclusionV1,
    WORKING_CAPITAL_FIELDS,
    canonical_working_capital_inputs,
    working_capital_policy_digest,
)
from decimal import Decimal
from test_valuation_preparation import _fact
from test_original_issuer import original, DECISION
from test_operating_forecast import operating_facts, prepare
from test_release_runner import _candidate
from test_history_composition import _original

VERIFIER = Ed25519PrivateKey.from_private_bytes(b"verifier-key".ljust(32, b"0"))
REVIEWER = Ed25519PrivateKey.from_private_bytes(b"reviewer-key".ljust(32, b"0"))


class Evidence:
    def __init__(self):
        self.values = {}

    def add(self, name, raw, role="test-only"):
        self.values[name] = raw
        return ArtifactRefV1(
            artifact_id=name,
            content_hash=hashlib.sha256(raw).hexdigest(),
            media_type="application/octet-stream",
            role=role,
        )

    def read(self, artifact_id):
        return self.values[artifact_id]


def resign(bundle, **changes):
    payload = bundle.manifest.model_dump(exclude={"manifest_digest"})
    payload.update(changes)
    manifest = IssuerOperatingReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    verification = bundle.verification.model_dump(
        exclude={"verification_digest", "signature"}
    )
    verification["manifest_digest"] = manifest.manifest_digest
    return bundle.model_copy(
        update={
            "manifest": manifest,
            "verification": sign_data_release_verification(verification, VERIFIER),
        }
    )


def fixture(tmp_path, *, composite=False):
    _, verification, _, _, _, _, roots = _candidate()
    report, source = original()
    evidence = Evidence()
    raw = b"synthetic original bytes; not an SEC filing"
    raw_ref = evidence.add("synthetic-original", raw)
    name = source.uri.rsplit("/", 1)[-1]
    archive_name = source.accession_number + "-xbrl.zip"
    archive = io.BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr(ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0)), raw)
    archive_ref = evidence.add("synthetic-archive", archive.getvalue())
    index_ref = evidence.add(
        "synthetic-index",
        canonical_bytes(
            {
                "directory": {
                    "item": [
                        {"name": name, "size": str(len(raw))},
                        {"name": archive_name, "size": str(len(archive.getvalue()))},
                    ]
                }
            }
        ),
    )
    taxonomy_ref = evidence.add("synthetic-taxonomy", b"synthetic taxonomy bytes")
    profile = ArelleValidationProfileV1(
        profile_id="synthetic-release-only",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("edgar"),
        xule_plugin_dir=Path("xule"),
        dqc_ruleset_path=Path("ruleset"),
        edgar_plugin_sha256="0" * 64,
        xule_plugin_sha256="1" * 64,
        dqc_ruleset_sha256="2" * 64,
    )
    requirement = (
        composite_working_capital_requirements_profile("fcff_dcf")
        if composite
        else operating_forecast_requirements_profile("fcff_dcf")
    )
    selected_facts = operating_facts()
    if composite:
        selected_facts = tuple(
            f
            for f in selected_facts
            if f.normalized_field not in WORKING_CAPITAL_FIELDS
        )
        selected_facts += tuple(
            _fact(field, year, value, instant=True)
            for year in range(2021, 2026)
            for field, value in (
                ("current_assets", "100"),
                ("current_liabilities", "40"),
                ("cash_and_equivalents", "10"),
                ("short_term_investments", "5"),
                ("current_interest_bearing_debt", "5"),
                ("current_operating_lease_liabilities", "2"),
                ("current_finance_lease_liabilities", "1"),
            )
        )
    observations = tuple(
        ParsedXbrlFactV1(
            concept=f"us-gaap:{f.normalized_field}",
            namespace_uri="http://fasb.org/us-gaap/2015-01-31",
            value=str(f.value),
            context_id=f.fact_id,
            unit="iso4217:USD",
            decimals="0",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier=source.cik,
            period_start=f.period_start,
            period_end=None if f.instant else f.period_end,
            instant=f.instant,
            is_numeric=True,
            consolidation_scope="consolidated",
            security_scope="unspecified",
        )
        for f in selected_facts
    )
    markers = ("strict-sec-efm-profile-selected", "dqc-dqcrt-checks-completed")
    report = report.model_copy(
        update={
            "facts": (*report.facts, *observations),
            "source_content_hash": raw_ref.content_hash,
            "validation_profile": profile,
            "validation_profile_digest": profile.digest(),
            "validation_engines": ("sec-efm", "dqc-us"),
            "validation_evidence": markers,
            "taxonomy_cache_hash": taxonomy_ref.content_hash,
        }
    )
    source = source.model_copy(
        update={
            "content_hash": raw_ref.content_hash,
            "parser_input_hash": raw_ref.content_hash,
            "http_status": 200,
        }
    )
    claim = evaluate_original_issuer(report, source=source, decision_at=DECISION)
    view = compose_issuer_operating_source((claim,), valuation_timestamp=DECISION)
    mappings = tuple(
        CanonicalMappingV1(
            contract_version="fundamental.v1",
            decision_id="test-mapping-" + role,
            source_concept="us-gaap:" + role,
            normalized_field=role,
            mapping_version="test-issuer-mapping-v1",
            confidence="high",
            status="approved",
            reviewer="mapping-reviewer",
            reviewed_at=DECISION,
        )
        for role in sorted({f.normalized_field for f in selected_facts})
    )
    facts = original_rebuilt_facts(view, {m.decision_id: m for m in mappings})
    integrity = _original(2025).sec_integrity_evidence.model_copy(
        update={
            "accession_number": source.accession_number,
            "primary_document_uri": source.uri,
            "captured_at": source.captured_at,
            "raw_content_hash": source.content_hash,
            "normalized_content_hash": source.parser_input_hash,
            "parser_input_hash": source.parser_input_hash,
            "archive_index_hash": index_ref.content_hash,
            "archive_hash": archive_ref.content_hash,
            "archive_member_hash": source.content_hash,
            "archive_index_uri": source.uri.rsplit("/", 1)[0] + "/index.json",
            "archive_uri": source.uri.rsplit("/", 1)[0] + "/" + archive_name,
            "declared_primary_size": len(raw),
            "raw_received_size": len(raw),
            "archive_size": len(archive.getvalue()),
            "archive_member_name": name,
            "archive_member_size": len(raw),
            "normalized_content_size": len(raw),
            "taxonomy_manifest_hash": taxonomy_ref.content_hash,
            "normalized_fact_count": len(report.facts),
            "archive_fact_count": len(report.facts),
            "normalized_fact_digest": fact_semantic_digest(report),
            "archive_fact_digest": fact_semantic_digest(report),
            "validation_profile_digest": profile.digest(),
            "efm_profile": profile.efm_profile,
        }
    )
    integrity_ref = evidence.add(
        "synthetic-integrity", canonical_bytes(integrity), "sec-issuer-integrity-v1"
    )
    review_ref = evidence.add(
        "synthetic-review-evidence", b"test-only mapping and validation fixture"
    )
    references = tuple(
        FactRefV1(fact_id=f.fact_id, fact_digest=canonical_fact_digest(f))
        for f in facts
    )
    snapshot_ref = SnapshotRefV1(
        snapshot_id=view.snapshot_id,
        manifest_digest=view.manifest_digest,
        facts=references,
        fact_set_digest=sha256_digest(references),
    )
    mapping_refs = tuple(
        MappingRefV1(
            mapping_id=m.decision_id,
            mapping_digest=sha256_digest(m.model_dump(mode="json")),
        )
        for m in mappings
    )
    payload = {
        "protocol": "fundamental.issuer-operating-release.v1",
        "profile_id": "test-only-issuer-profile",
        "release_id": "test-only-release",
        "created_at": DECISION,
        "snapshot_refs": (snapshot_ref,),
        "mapping_refs": mapping_refs,
        "taxonomy_refs": (taxonomy_ref,),
        "parser_version": report.parser_version,
        "quality_profile_digest": "c" * 64,
        "required_fields": requirement.required_fact_fields,
        "artifact_refs": (raw_ref, index_ref, archive_ref, integrity_ref, review_ref),
        "model_id": "fcff_dcf",
        "model_version": "fcff_dcf-v2",
        "policy_id": "test-only-policy",
        "policy_version": "test-only-policy-v1",
        "mapping_version": "test-issuer-mapping-v1",
        "requirements_profile_digest": requirement.digest,
    }
    if composite:
        inputs = []
        for year in range(2021, 2026):
            by_field = {
                f.normalized_field: f
                for f in facts
                if f.instant and f.instant.year == year
            }
            inputs.append(
                CompositeWorkingCapitalInputV1(
                    policy_digest=working_capital_policy_digest(),
                    mapping_version="test-issuer-mapping-v1",
                    issuer_id=view.identity.issuer_id,
                    accession_number=source.accession_number,
                    source_hash=source.content_hash,
                    period_end=by_field["current_assets"].period_end,
                    current_assets_fact_id=by_field["current_assets"].fact_id,
                    current_liabilities_fact_id=by_field["current_liabilities"].fact_id,
                    exclusions=tuple(
                        WorkingCapitalExclusionV1(
                            account_class=field,
                            side=side,
                            state="reported",
                            fact_id=by_field[field].fact_id,
                            mapped_fact_role=field,
                            covered_by_fact_id=by_field[parent].fact_id,
                            covered_classes=(field,),
                            rationale="Synthetic fixture explicitly classifies this reported balance.",
                        )
                        for field, side, parent in (
                            ("cash_and_equivalents", "assets", "current_assets"),
                            ("short_term_investments", "assets", "current_assets"),
                            (
                                "current_interest_bearing_debt",
                                "liabilities",
                                "current_liabilities",
                            ),
                            (
                                "current_operating_lease_liabilities",
                                "liabilities",
                                "current_liabilities",
                            ),
                            (
                                "current_finance_lease_liabilities",
                                "liabilities",
                                "current_liabilities",
                            ),
                        )
                    ),
                    asset_residual=InclusionScenariosV1(
                        low=Decimal("0.4"),
                        central=Decimal("0.6"),
                        high=Decimal("0.8"),
                        rationale="Synthetic asset residual classification assumption.",
                    ),
                    liability_residual=InclusionScenariosV1(
                        low=Decimal("0.4"),
                        central=Decimal("0.5"),
                        high=Decimal("0.6"),
                        rationale="Synthetic liability residual classification assumption.",
                    ),
                    perimeter_rationale="Synthetic totals and exclusions share one original filing perimeter.",
                )
            )
        payload["working_capital_inputs"] = canonical_working_capital_inputs(
            tuple(inputs)
        )
    manifest = IssuerOperatingReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    reviews = tuple(
        sign_mapping_review_evidence(
            {
                "mapping_id": ref.mapping_id,
                "mapping_digest": ref.mapping_digest,
                "author_id": "mapping-builder",
                "reviewer_id": "mapping-reviewer",
                "reviewed_at": DECISION,
                "evidence_refs": (review_ref,),
                "fixture_digest": sha256_digest({"test_only": ref.mapping_id}),
            },
            REVIEWER,
        )
        for ref in mapping_refs
    )
    vp = verification.model_dump(exclude={"verification_digest", "signature"})
    vp.update(
        {
            "manifest_digest": manifest.manifest_digest,
            "mapping_reviews": reviews,
            "evidence_refs": (review_ref,),
        }
    )
    bundle = IssuerOperatingReleaseBundleV1(
        manifest=manifest,
        verification=sign_data_release_verification(vp, VERIFIER),
        sources=(view,),
        facts=facts,
        mappings=mappings,
    )
    store = ArtifactStore(tmp_path / "issuer-releases")
    service = IssuerOperatingReleaseService(
        releases=store, evidence=evidence, trust_roots=roots
    )
    return bundle, service, evidence, roots, store


def inventory(root):
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in root.rglob("*")
        if p.is_file()
    }


def test_signed_publication_restart_and_forecast_repeat_use_shared_composer(tmp_path):
    bundle, service, evidence, roots, store = fixture(tmp_path)
    first = service.publish(bundle)
    before = inventory(store.root)
    assert first.wrote is True
    second = service.publish(bundle)
    assert second.wrote is False and inventory(store.root) == before
    result = service.prepare(
        artifact_id=bundle.artifact_id,
        expected_manifest_digest=bundle.manifest.manifest_digest,
        snapshot_id=bundle.sources[0].snapshot_id,
    )
    restarted = IssuerOperatingReleaseService(
        releases=ArtifactStore(store.root), evidence=evidence, trust_roots=roots
    )
    repeat = restarted.prepare(
        artifact_id=bundle.artifact_id,
        expected_manifest_digest=bundle.manifest.manifest_digest,
        snapshot_id=bundle.sources[0].snapshot_id,
    )
    assert canonical_bytes(result) == canonical_bytes(repeat)
    baseline = prepare(operating_facts())
    assert result.forecast.status == "prepared"
    assert result.forecast.forecast == baseline.forecast
    assert [n.value for n in result.forecast.nodes] == [n.value for n in baseline.nodes]
    assert result.forecast.quality_status is QualityStatus.PROVISIONAL
    assert result.forecast.supported_history_threshold is None
    assert inventory(store.root) == before
    with pytest.raises(ValidationError):
        DataReleaseManifestV1.model_validate_json(canonical_bytes(bundle.manifest))


def test_signed_composite_release_rechecks_bound_policy_and_serves_provisional_forecast(
    tmp_path,
):
    bundle, service, evidence, roots, store = fixture(tmp_path, composite=True)
    first = service.publish(bundle)
    before = inventory(store.root)
    assert first.wrote is True
    assert service.publish(bundle).wrote is False
    result = service.prepare(
        artifact_id=bundle.artifact_id,
        expected_manifest_digest=bundle.manifest.manifest_digest,
        snapshot_id=bundle.sources[0].snapshot_id,
    )
    restarted = IssuerOperatingReleaseService(
        releases=ArtifactStore(store.root), evidence=evidence, trust_roots=roots
    )
    repeat = restarted.prepare(
        artifact_id=bundle.artifact_id,
        expected_manifest_digest=bundle.manifest.manifest_digest,
        snapshot_id=bundle.sources[0].snapshot_id,
    )
    assert result.forecast.status == "prepared"
    assert result.forecast.quality_status is QualityStatus.PROVISIONAL
    assert result.forecast.supported_history_threshold is None
    assert result.forecast.historical_metrics.working_capital_assessments
    assert (
        result.forecast.historical_metrics.working_capital_inputs
        == bundle.manifest.working_capital_inputs
    )
    assert canonical_bytes(result) == canonical_bytes(repeat)
    assert inventory(store.root) == before

    altered = bundle.manifest.working_capital_inputs[0].model_copy(
        update={"policy_digest": "0" * 64}
    )
    with pytest.raises(DataReleaseError) as error:
        service.publish(
            resign(
                bundle,
                working_capital_inputs=(
                    altered,
                    *bundle.manifest.working_capital_inputs[1:],
                ),
            )
        )
    assert error.value.code == "DATA_RELEASE_WORKING_CAPITAL_POLICY_MISMATCH"
    assert inventory(store.root) == before


@pytest.mark.parametrize("mutation", ("source_hash", "unbound"))
def test_signed_composite_release_rejects_unbound_or_mismatched_inputs(
    tmp_path, mutation
):
    bundle, service, _, _, store = fixture(tmp_path, composite=True)
    policy_input = bundle.manifest.working_capital_inputs[0]
    if mutation == "source_hash":
        altered = policy_input.model_copy(update={"source_hash": "0" * 64})
        code = "DATA_RELEASE_WORKING_CAPITAL_INVALID"
    else:
        altered = CompositeWorkingCapitalInputV1.model_validate(
            policy_input.model_dump()
            | {
                "current_assets_fact_id": "undeclared-assets",
                "exclusions": tuple(
                    item.model_dump() | {"covered_by_fact_id": "undeclared-assets"}
                    if item.side == "assets"
                    else item.model_dump()
                    for item in policy_input.exclusions
                ),
            }
        )
        code = "DATA_RELEASE_WORKING_CAPITAL_UNBOUND"
    before = inventory(store.root)
    with pytest.raises(DataReleaseError) as error:
        service.publish(
            resign(
                bundle,
                working_capital_inputs=canonical_working_capital_inputs(
                    (altered, *bundle.manifest.working_capital_inputs[1:])
                ),
            )
        )
    assert error.value.code == code
    assert inventory(store.root) == before


@pytest.mark.parametrize(
    "mutation,code",
    (
        ("untrusted", "DATA_RELEASE_VERIFIER_UNTRUSTED"),
        ("signature", "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID"),
        ("review_missing", "DATA_RELEASE_MAPPING_REVIEW_MISMATCH"),
        ("review_signature", "DATA_RELEASE_MAPPING_REVIEW_SIGNATURE_INVALID"),
        ("wrong_profile", "DATA_RELEASE_OPERATING_PROFILE_MISMATCH"),
        ("missing_integrity", "DATA_RELEASE_ORIGINAL_INTEGRITY_UNAVAILABLE"),
        ("wrong_mapping_version", "DATA_RELEASE_MAPPING_VERSION_MISMATCH"),
        ("artifact_bytes", "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"),
    ),
)
def test_untrusted_or_incomplete_release_cannot_publish(tmp_path, mutation, code):
    bundle, service, evidence, roots, store = fixture(tmp_path)
    if mutation == "untrusted":
        roots = roots.model_copy(
            update={
                "verifiers": {"other-verifier": next(iter(roots.verifiers.values()))}
            }
        )
        service = IssuerOperatingReleaseService(
            releases=store, evidence=evidence, trust_roots=roots
        )
    elif mutation == "signature":
        bundle = bundle.model_copy(
            update={
                "verification": bundle.verification.model_copy(
                    update={"signature": "0" * 128}
                )
            }
        )
    elif mutation in {"review_missing", "review_signature"}:
        vp = bundle.verification.model_dump(
            exclude={"verification_digest", "signature"}
        )
        vp["mapping_reviews"] = (
            ()
            if mutation == "review_missing"
            else (
                bundle.verification.mapping_reviews[0].model_copy(
                    update={"signature": "0" * 128}
                ),
                *bundle.verification.mapping_reviews[1:],
            )
        )
        bundle = bundle.model_copy(
            update={"verification": sign_data_release_verification(vp, VERIFIER)}
        )
    elif mutation == "wrong_profile":
        bundle = resign(bundle, requirements_profile_digest="0" * 64)
    elif mutation == "missing_integrity":
        bundle = resign(
            bundle,
            artifact_refs=tuple(
                ref
                for ref in bundle.manifest.artifact_refs
                if ref.role != "sec-issuer-integrity-v1"
            ),
        )
    elif mutation == "wrong_mapping_version":
        bundle = resign(bundle, mapping_version="other")
    else:
        evidence.values["synthetic-original"] = b"changed bytes"
    before = inventory(store.root)
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == code
    assert inventory(store.root) == before


def test_changed_financial_amount_cannot_be_released_even_when_review_is_signed(
    tmp_path,
):
    bundle, service, _, _, _ = fixture(tmp_path)
    fact = bundle.facts[0].model_copy(update={"value": bundle.facts[0].value + 1})
    facts = tuple(fact if f.fact_id == fact.fact_id else f for f in bundle.facts)
    refs = tuple(
        FactRefV1(fact_id=f.fact_id, fact_digest=canonical_fact_digest(f))
        for f in facts
    )
    reference = bundle.manifest.snapshot_refs[0].model_copy(
        update={"facts": refs, "fact_set_digest": sha256_digest(refs)}
    )
    bundle = resign(
        bundle.model_copy(update={"facts": facts}), snapshot_refs=(reference,)
    )
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == "DATA_RELEASE_ORIGINAL_FACT_MISMATCH"


def test_issuer_release_cannot_authorize_equity_dilution(tmp_path):
    from fundamental_service.equity_award_evidence import EQUITY_DILUTION_ARTIFACT_ROLE

    bundle, service, evidence, _, _ = fixture(tmp_path)
    reference = evidence.add("synthetic-equity", b"{}", EQUITY_DILUTION_ARTIFACT_ROLE)
    bundle = resign(bundle, artifact_refs=(*bundle.manifest.artifact_refs, reference))
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == "DATA_RELEASE_SOURCE_SCOPE_MISMATCH"


def test_explicit_issuer_rule_protocol_has_no_security_claim(tmp_path):
    from test_accounting_roles import _fixture

    snapshot, report, mapping = _fixture()
    payload = mapping.accounting_rules.model_dump()
    payload.update({"protocol": "sec-accounting-role-issuer-v1", "security_id": None})
    rules = IssuerAccountingRoleRuleSetV1.model_validate(payload)
    assert rules.security_id is None
    with pytest.raises(ValidationError):
        AccountingRoleRuleSetV1.model_validate(payload)
    with pytest.raises(ValidationError):
        IssuerAccountingRoleRuleSetV1.model_validate({**payload, "security_id": "FAKE"})


def rebind_original(bundle, *, report_changes=None, source_changes=None):
    old = bundle.sources[0]
    original = old.originals[0]
    claim = evaluate_original_issuer(
        original.report.model_copy(update=report_changes or {}),
        source=original.source.model_copy(update=source_changes or {}),
        decision_at=original.decision_at,
    )
    view = compose_issuer_operating_source(
        (claim,), valuation_timestamp=old.valuation_timestamp
    )
    ref = bundle.manifest.snapshot_refs[0].model_copy(
        update={
            "snapshot_id": view.snapshot_id,
            "manifest_digest": view.manifest_digest,
        }
    )
    return resign(bundle.model_copy(update={"sources": (view,)}), snapshot_refs=(ref,))


@pytest.mark.parametrize(
    "change,code",
    (
        ("missing_http", "DATA_RELEASE_SOURCE_RECEIPT_UNAVAILABLE"),
        ("missing_engines", "VALIDATION_EVIDENCE_MISSING"),
        ("missing_completion", "VALIDATION_EVIDENCE_MISSING"),
        ("blocked_original", "DATA_RELEASE_REGULATORY_BLOCKED"),
        ("missing_bytes", "DATA_RELEASE_ORIGINAL_BYTES_UNAVAILABLE"),
        ("wrong_integrity", "DATA_RELEASE_ORIGINAL_INTEGRITY_MISMATCH"),
    ),
)
def test_signed_release_cannot_replace_original_source_or_regulatory_evidence(
    tmp_path, change, code
):
    from fundamental_service.arelle_parser import ArelleFindingV1

    bundle, service, evidence, _, _ = fixture(tmp_path)
    if change == "missing_http":
        bundle = rebind_original(bundle, source_changes={"http_status": None})
    elif change == "missing_engines":
        bundle = rebind_original(bundle, report_changes={"validation_engines": ()})
    elif change == "missing_completion":
        bundle = rebind_original(bundle, report_changes={"validation_evidence": ()})
    elif change == "blocked_original":
        bundle = rebind_original(
            bundle,
            report_changes={
                "findings": (
                    ArelleFindingV1(
                        code="DQC.US.TEST",
                        severity="error",
                        message="retained blocking observation",
                    ),
                )
            },
        )
    elif change == "missing_bytes":
        bundle = resign(
            bundle,
            artifact_refs=tuple(
                ref
                for ref in bundle.manifest.artifact_refs
                if ref.artifact_id != "synthetic-archive"
            ),
        )
    else:
        import json

        integrity = json.loads(evidence.values["synthetic-integrity"])
        integrity["validation_profile_digest"] = "a" * 64
        ref = evidence.add(
            "synthetic-integrity", canonical_bytes(integrity), "sec-issuer-integrity-v1"
        )
        bundle = resign(
            bundle,
            artifact_refs=tuple(
                ref if old.artifact_id == ref.artifact_id else old
                for old in bundle.manifest.artifact_refs
            ),
        )
    with pytest.raises(DataReleaseError) as error:
        service.publish(bundle)
    assert error.value.code == code


def test_serving_rechecks_current_deployment_trust_and_evidence(tmp_path):
    bundle, service, evidence, roots, store = fixture(tmp_path)
    service.publish(bundle)
    kwargs = {
        "artifact_id": bundle.artifact_id,
        "expected_manifest_digest": bundle.manifest.manifest_digest,
        "snapshot_id": bundle.sources[0].snapshot_id,
    }
    with pytest.raises(DataReleaseError) as error:
        service.prepare(**{**kwargs, "expected_manifest_digest": "0" * 64})
    assert error.value.code == "DATA_RELEASE_PIN_MISMATCH"
    with pytest.raises(DataReleaseError) as error:
        service.prepare(**{**kwargs, "snapshot_id": "outside-release"})
    assert error.value.code == "DATA_RELEASE_SNAPSHOT_NOT_IN_RELEASE"
    changed = roots.model_copy(
        update={"verifiers": {"other-verifier": next(iter(roots.verifiers.values()))}}
    )
    untrusted = IssuerOperatingReleaseService(
        releases=ArtifactStore(store.root), evidence=evidence, trust_roots=changed
    )
    with pytest.raises(DataReleaseError) as error:
        untrusted.prepare(**kwargs)
    assert error.value.code == "DATA_RELEASE_VERIFIER_UNTRUSTED"
    evidence.values["synthetic-original"] = b"changed after publication"
    with pytest.raises(DataReleaseError) as error:
        service.prepare(**kwargs)
    assert error.value.code == "DATA_RELEASE_ARTIFACT_HASH_MISMATCH"


def test_generic_release_manifest_cannot_release_issuer_source(tmp_path):
    from fundamental_service.release_runner import DataReleaseCanaryRunner
    from fundamental_service.issuer_operating_release import _SourceReader, _FactReader

    bundle, _, evidence, roots, _ = fixture(tmp_path)
    payload = bundle.manifest.model_dump(
        exclude={
            "manifest_digest",
            "protocol",
            "model_id",
            "model_version",
            "policy_id",
            "policy_version",
            "mapping_version",
            "requirements_profile_digest",
        }
    )
    manifest = DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))
    vp = bundle.verification.model_dump(exclude={"verification_digest", "signature"})
    vp["manifest_digest"] = manifest.manifest_digest
    reader = _FactReader(bundle)
    runner = DataReleaseCanaryRunner(
        snapshot_repository=_SourceReader(bundle),
        fact_repository=reader,
        mapping_reader=reader,
        artifact_reader=evidence,
        trust_roots=roots,
    )
    with pytest.raises(DataReleaseError) as error:
        runner.validate(manifest, sign_data_release_verification(vp, VERIFIER))
    assert error.value.code == "DATA_RELEASE_SOURCE_SCOPE_MISMATCH"


def test_issuer_mapping_fact_ids_do_not_depend_on_capture_time(tmp_path):
    from datetime import timedelta
    from fundamental_service.sec_rebuild import parsed_facts_to_candidates

    bundle, _, _, _, _ = fixture(tmp_path)
    original = bundle.sources[0].originals[0]
    mapping = bundle.mappings[0]
    first = parsed_facts_to_candidates(
        original.report,
        source=original.source,
        issuer_id=original.source.cik,
        normalized_field=mapping.normalized_field,
        mapping=mapping,
    )
    repeated = parsed_facts_to_candidates(
        original.report,
        source=original.source.model_copy(
            update={"captured_at": original.source.captured_at + timedelta(days=1)}
        ),
        issuer_id=original.source.cik,
        normalized_field=mapping.normalized_field,
        mapping=mapping,
    )
    assert first and [f.candidate_id for f in first] == [
        f.candidate_id for f in repeated
    ]
    with pytest.raises(SnapshotError, match="security"):
        parsed_facts_to_candidates(
            original.report,
            source=original.source,
            issuer_id=original.source.cik,
            security_id="FAKE",
            normalized_field=mapping.normalized_field,
            mapping=mapping,
        )
