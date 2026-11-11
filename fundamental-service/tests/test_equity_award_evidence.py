from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace

import pytest

from fundamental_service.contracts import (
    DimensionV1,
    QualityStatus,
    ValuationEvidenceReadRequestV1,
)
from fundamental_service.data_releases import (
    ArtifactRefV1,
    DataReleaseManifestV1,
    DataReleaseError,
)
from fundamental_service.equity_award_evidence import (
    EQUITY_DILUTION_ARTIFACT_ROLE,
    EQUITY_QUOTE_SOURCE_ROLE,
    load_release_dilution_evidence,
    verify_dilution_fact_bindings,
)
from fundamental_service.equity_dilution import DilutionError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_preparation import prepare_automatic_valuation
from test_preparation_runner import _fixture, _reviewed_candidate
from test_valuation_preparation import _market_policy
from test_api import _release_manifest_for


def _load(fixture, **changes):
    return load_release_dilution_evidence(
        changes.get("manifest", fixture.manifest),
        snapshot=fixture.snapshot,
        artifacts=changes.get("artifacts", fixture.artifacts),
        released_facts=changes.get("released_facts", fixture.facts.list()),
    )


def _manifest(fixture, references):
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = references
    return DataReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))


def _prepare(fixture, evidence):
    return prepare_automatic_valuation(
        fixture.facts.list(),
        snapshot=fixture.snapshot,
        model_id="fcff_dcf",
        model_version="fcff_dcf-v1",
        policy_id="synthetic-v1",
        policy_version="synthetic-v1",
        data_release_manifest_digest=fixture.manifest.manifest_digest,
        market_policy=_market_policy(),
        equity_dilution_evidence=evidence,
    )


def test_pinned_release_drives_composer_and_preserves_award_quote_provenance(tmp_path):
    fixture = _fixture(tmp_path)
    evidence = _load(fixture)
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=fixture.manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    prepared = fixture.application.prepare_valuation(request)
    assert prepared.status == "prepared"
    assert prepared.equity_dilution.incremental_shares == Decimal(10)
    assert prepared.input.assumptions.capital_bridge.diluted_shares == Decimal(120)
    assert prepared.input.provenance.equity_dilution_evidence_digest == evidence.digest
    assert set(fact.fact_id for fact in evidence.facts) <= set(
        prepared.input.historical_facts
    )
    trace = next(
        item
        for item in prepared.assumptions_evidence
        if item.path == "assumptions.capital_bridge.diluted_shares"
    )
    assert evidence.quote.content_hash in trace.source_refs
    assert trace.policy_version == evidence.policy.policy_version
    assert prepared.quality_status is QualityStatus.PROVISIONAL
    assert "HISTORY_THRESHOLD_UNVALIDATED" in prepared.issue_codes


def test_precomputed_net_count_never_substitutes_for_missing_award_evidence(tmp_path):
    fixture = _fixture(tmp_path)
    legacy = fixture.dilution.facts[0].model_copy(
        update={
            "fact_id": "legacy-precomputed-net",
            "normalized_field": "dilutive_instruments",
            "value": Decimal(999),
        }
    )
    fixture.facts.publish(legacy)
    result = _prepare(fixture, None)
    assert result.status == "abstained"
    assert result.input is None
    assert "DILUTION_EVIDENCE_MISSING" in result.issue_codes
    assert "equity_dilution_evidence" in result.missing_evidence


def test_different_quote_evidence_changes_approval_digest_even_with_equal_shares(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    evidence = _load(fixture)
    first = _prepare(fixture, evidence)
    changed = evidence.model_copy(
        update={"quote": evidence.quote.model_copy(update={"price": Decimal(20)})}
    )
    second = _prepare(fixture, changed)
    assert (
        first.input.assumptions.capital_bridge
        == second.input.assumptions.capital_bridge
    )
    assert first.input.input_digest != second.input.input_digest
    assert first.preparation_digest != second.preparation_digest


def test_legacy_release_without_award_artifact_cannot_prepare_per_share_value(tmp_path):
    fixture = _fixture(tmp_path)
    manifest = _manifest(
        fixture,
        tuple(
            ref
            for ref in fixture.manifest.artifact_refs
            if ref.role != EQUITY_DILUTION_ARTIFACT_ROLE
        ),
    )
    assert _load(fixture, manifest=manifest) is None
    application = replace(
        fixture.application,
        metadata_store=SimpleNamespace(
            get_data_release_manifest=lambda digest: manifest,
            get_mapping=fixture.mappings.__getitem__,
        ),
    )
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    result = application.prepare_valuation(request)
    assert result.status == "abstained"
    assert "DILUTION_EVIDENCE_MISSING" in result.issue_codes


@pytest.mark.parametrize(
    "alteration", ["value", "quality", "missing", "role", "snapshot"]
)
def test_inventory_must_match_released_reviewed_facts(tmp_path, alteration):
    fixture = _fixture(tmp_path)
    evidence = fixture.dilution
    facts = fixture.facts.list()
    target = evidence.facts[0]
    if alteration == "missing":
        facts = tuple(fact for fact in facts if fact.fact_id != target.fact_id)
    elif alteration == "snapshot":
        evidence = evidence.model_copy(update={"snapshot_manifest_digest": "f" * 64})
    else:
        changes = {
            "value": {"value": Decimal(999)},
            "quality": {"quality": QualityStatus.PROVISIONAL},
            "role": {"normalized_field": "dilutive_instruments"},
        }[alteration]
        award = evidence.inventory.instruments[0].model_copy(
            update={"quantity": target.model_copy(update=changes)}
        )
        evidence = evidence.model_copy(
            update={
                "inventory": evidence.inventory.model_copy(
                    update={"instruments": (award,)}
                )
            }
        )
    with pytest.raises(DilutionError):
        verify_dilution_fact_bindings(
            evidence, snapshot=fixture.snapshot, released_facts=facts
        )


@pytest.mark.parametrize(
    "alteration,code",
    [
        ("hash", "DILUTION_ARTIFACT_MISMATCH"),
        ("noncanonical", "DILUTION_ARTIFACT_NONCANONICAL"),
        ("duplicate", "DILUTION_ARTIFACT_AMBIGUOUS"),
        ("missing_quote", "DILUTION_QUOTE_SOURCE_UNAVAILABLE"),
        ("changed_quote", "DILUTION_QUOTE_SOURCE_MISMATCH"),
    ],
)
def test_artifact_and_quote_source_failures_are_retained(tmp_path, alteration, code):
    fixture = _fixture(tmp_path)
    references = list(fixture.manifest.artifact_refs)
    reader = fixture.artifacts
    target = next(
        ref for ref in references if ref.role == EQUITY_DILUTION_ARTIFACT_ROLE
    )
    quote = next(ref for ref in references if ref.role == EQUITY_QUOTE_SOURCE_ROLE)
    if alteration in {"hash", "noncanonical"}:
        raw = canonical_bytes(fixture.dilution) + b"\n"
        reader = SimpleNamespace(
            read=lambda artifact_id: raw
            if artifact_id == target.artifact_id
            else fixture.artifacts.read(artifact_id)
        )
        if alteration == "noncanonical":
            references[references.index(target)] = target.model_copy(
                update={"content_hash": sha256(raw).hexdigest()}
            )
    elif alteration == "duplicate":
        references.append(
            ArtifactRefV1(
                artifact_id="duplicate",
                content_hash=target.content_hash,
                media_type="application/json",
                role=target.role,
            )
        )
        reader = SimpleNamespace(
            read=lambda artifact_id: canonical_bytes(fixture.dilution)
            if artifact_id == "duplicate"
            else fixture.artifacts.read(artifact_id)
        )
    elif alteration == "missing_quote":
        references.remove(quote)
    else:
        reader = SimpleNamespace(
            read=lambda artifact_id: b"changed"
            if artifact_id == quote.artifact_id
            else fixture.artifacts.read(artifact_id)
        )
    with pytest.raises(DilutionError) as error:
        _load(fixture, manifest=_manifest(fixture, tuple(references)), artifacts=reader)
    assert error.value.code == code


def test_signed_candidate_with_stale_quote_refuses_before_activation(tmp_path):
    from datetime import timedelta

    fixture = _fixture(tmp_path, released=False)
    evidence = fixture.dilution.model_copy(
        update={
            "quote": fixture.dilution.quote.model_copy(
                update={
                    "as_of": fixture.snapshot.valuation_timestamp - timedelta(days=10),
                }
            ),
        }
    )
    fixture.artifacts.put_with_receipt(f"equity-dilution:{evidence.digest}", evidence)
    fixture.manifest = _manifest(
        fixture,
        tuple(
            ref.model_copy(
                update={
                    "artifact_id": f"equity-dilution:{evidence.digest}",
                    "content_hash": evidence.digest,
                }
            )
            if ref.role == EQUITY_DILUTION_ARTIFACT_ROLE
            else ref
            for ref in fixture.manifest.artifact_refs
        ),
    )
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as error:
        canary.validate(candidate.manifest, candidate.verification)
    assert error.value.code == "DILUTION_QUOTE_STALE"
    assert fixture.state.active is None
    assert fixture.state.publications == 0


def test_signed_release_retains_two_distinct_award_classes_without_scalar_collapse(
    tmp_path,
):
    fixture = _fixture(tmp_path, released=False)
    original = fixture.dilution.inventory.instruments[0]
    awards = []
    for suffix in ("class-a", "class-b"):
        observations = []
        for fact in (original.quantity, original.unrecognized_compensation):
            observations.append(
                fact.model_copy(
                    update={
                        "fact_id": fact.fact_id + ":" + suffix,
                        "context": fact.context.model_copy(
                            update={
                                "context_id": fact.context.context_id + ":" + suffix,
                                "dimensions": (
                                    DimensionV1(
                                        name="us-gaap:AwardTypeAxis",
                                        member=f"synthetic:{suffix}",
                                    ),
                                ),
                                "consolidation_scope": "segmented",
                            }
                        ),
                    }
                )
            )
        awards.append(
            original.model_copy(
                update={
                    "instrument_id": suffix,
                    "quantity": observations[0],
                    "unrecognized_compensation": observations[1],
                }
            )
        )
    inventory = type(fixture.dilution.inventory).model_validate(
        {**fixture.dilution.inventory.model_dump(), "instruments": tuple(awards)}
    )
    evidence = fixture.dilution.model_copy(update={"inventory": inventory})
    facts = (
        tuple(
            fact
            for fact in fixture.facts.list()
            if not fact.normalized_field.startswith("equity_award_")
        )
        + evidence.facts
    )
    for fact in evidence.facts:
        fixture.facts.publish(fact)
    fixture.artifacts.put_with_receipt(f"equity-dilution:{evidence.digest}", evidence)
    refs = tuple(
        ref.model_copy(
            update={
                "artifact_id": f"equity-dilution:{evidence.digest}",
                "content_hash": evidence.digest,
            }
        )
        if ref.role == EQUITY_DILUTION_ARTIFACT_ROLE
        else ref
        for ref in fixture.manifest.artifact_refs
    )
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        snapshot_refs=_release_manifest_for(fixture.snapshot, facts).snapshot_refs,
        artifact_refs=refs,
    )
    fixture.manifest = DataReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    candidate, canary = _reviewed_candidate(fixture)
    report = canary.validate(candidate.manifest, candidate.verification)
    assert len(report.checked_fact_digests) == len(facts)
    prepared = fixture.application.prepare_valuation(
        ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=candidate.manifest.manifest_digest,
            model_id="fcff_dcf",
        )
    )
    assert len(prepared.equity_dilution.instruments) == 2
    assert prepared.equity_dilution.incremental_shares == Decimal(20)
    assert prepared.input.assumptions.capital_bridge.diluted_shares == Decimal(130)
    assert fixture.state.active is None
