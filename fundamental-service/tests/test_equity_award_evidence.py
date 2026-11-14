from dataclasses import replace
from datetime import timedelta
import json
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace

import pytest

from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
)
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
from fundamental_service.equity_dilution import DilutionError, PerformanceStockAwardV1
from fundamental_service.facts import select_fact_groups
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.operations import ServiceError
from quote_provider_fixtures import (
    SyntheticQuoteProvider,
    publish_synthetic_quote_admission,
)
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
        quote_providers=changes.get("quote_providers", default_quote_providers()),
        source_use_policy=changes.get(
            "source_use_policy", fixture.application.source_use_policy
        ),
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
        model_version="fcff_dcf-v2",
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


@pytest.mark.parametrize("aggregate", (False, True))
def test_signed_option_strike_scope_agrees_in_serving_and_canary(tmp_path, aggregate):
    concept = (
        "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice"
        if aggregate
        else "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsExercisePrice"
    )
    fixture = _fixture(tmp_path, released=False, option_price_concept=concept)
    candidate, canary = _reviewed_candidate(fixture)
    before = {fact.fact_id: sha256_digest(fact) for fact in fixture.facts.list()}
    if aggregate:
        with pytest.raises(DataReleaseError) as error:
            canary.validate(candidate.manifest, candidate.verification)
        assert error.value.code == "DILUTION_AGGREGATE_STRIKE_UNRESOLVED"
    else:
        canary.validate(candidate.manifest, candidate.verification)
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=candidate.manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    prepared = fixture.application.prepare_valuation(request)
    repeated = fixture.application.prepare_valuation(request)
    assert canonical_bytes(prepared) == canonical_bytes(repeated)
    if aggregate:
        assert prepared.status == "abstained"
        assert prepared.quality_status is QualityStatus.ABSTAIN
        assert "DILUTION_AGGREGATE_STRIKE_UNRESOLVED" in prepared.issue_codes
        assert prepared.input is None
    else:
        assert prepared.status == "prepared"
        assert prepared.equity_dilution.incremental_shares == Decimal(2)
        assert prepared.input.assumptions.capital_bridge.diluted_shares == Decimal(112)
    assert {
        fact.fact_id: sha256_digest(fact) for fact in fixture.facts.list()
    } == before
    assert _load(fixture).inventory.instruments[0].exercise_price.concept == concept
    assert fixture.state.active is None


def _with_historical_awards(fixture):
    period = fixture.dilution.inventory.period_end
    prior = period.replace(year=period.year - 1)
    historical = tuple(
        fact.model_copy(
            update={
                "fact_id": fact.fact_id + ":prior",
                "instant": prior,
                "period_end": prior,
                "value": fact.value * 100,
                "context": fact.context.model_copy(update={"instant": prior}),
            }
        )
        for fact in fixture.dilution.facts
    )
    for fact in historical:
        fixture.facts.publish(fact)
    payload = fixture.manifest.model_dump(exclude={"manifest_digest"})
    payload["snapshot_refs"] = _release_manifest_for(
        fixture.snapshot, fixture.facts.list()
    ).snapshot_refs
    fixture.manifest = DataReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    fixture.metadata.get_data_release_manifest = lambda digest: (
        fixture.manifest if digest == fixture.manifest.manifest_digest else None
    )
    return historical


@pytest.mark.parametrize("consumer", ("serving", "canary"))
def test_release_retains_historical_awards_without_counting_them_again(
    tmp_path, consumer
):
    fixture = _fixture(tmp_path, released=False)
    historical = _with_historical_awards(fixture)
    before = {fact.fact_id: sha256_digest(fact) for fact in fixture.facts.list()}
    if consumer == "canary":
        candidate, canary = _reviewed_candidate(fixture)
        report = canary.validate(candidate.manifest, candidate.verification)
        assert len(report.checked_fact_digests) == len(before)
        fixture.manifest = candidate.manifest
    evidence = _load(fixture)
    prepared = fixture.application.prepare_valuation(
        ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=fixture.manifest.manifest_digest,
            model_id="fcff_dcf",
        )
    )
    assert prepared.status == "prepared"
    assert prepared.equity_dilution.incremental_shares == Decimal(10)
    assert prepared.input.assumptions.capital_bridge.diluted_shares == Decimal(120)
    assert set(fact.fact_id for fact in historical) <= set(
        prepared.input.historical_facts
    )
    assert {
        fact.fact_id: sha256_digest(fact) for fact in fixture.facts.list()
    } == before
    assert _load(fixture, released_facts=reversed(fixture.facts.list())) == evidence


@pytest.mark.parametrize("empty", (False, True))
def test_inventory_cannot_ignore_a_newer_released_award_observation(tmp_path, empty):
    fixture = _fixture(tmp_path)
    evidence = fixture.dilution
    period = evidence.inventory.period_end + timedelta(days=1)
    newer = evidence.facts[0].model_copy(
        update={
            "fact_id": "newer-award",
            "instant": period,
            "period_end": period,
            "context": evidence.facts[0].context.model_copy(update={"instant": period}),
        }
    )
    if empty:
        evidence = evidence.model_copy(
            update={
                "inventory": evidence.inventory.model_copy(update={"instruments": ()})
            }
        )
    with pytest.raises(DilutionError) as error:
        verify_dilution_fact_bindings(
            evidence,
            snapshot=fixture.snapshot,
            released_facts=(*fixture.facts.list(), newer),
        )
    assert error.value.code == "DILUTION_INVENTORY_PERIOD_MISMATCH"


def test_inventory_cannot_omit_a_current_award_class(tmp_path):
    fixture = _fixture(tmp_path)
    quantity = fixture.dilution.facts[0]
    extra = quantity.model_copy(update={"fact_id": "another-current-class"})
    with pytest.raises(DilutionError) as error:
        verify_dilution_fact_bindings(
            fixture.dilution,
            snapshot=fixture.snapshot,
            released_facts=(*fixture.facts.list(), extra),
        )
    assert error.value.code == "DILUTION_INVENTORY_INCOMPLETE"


def test_historical_award_with_ambiguous_instant_is_not_silently_excluded(tmp_path):
    fixture = _fixture(tmp_path)
    historical = _with_historical_awards(fixture)
    malformed = historical[0].model_copy(update={"instant": None})
    facts = tuple(
        malformed if fact.fact_id == malformed.fact_id else fact
        for fact in fixture.facts.list()
    )
    with pytest.raises(DilutionError) as error:
        verify_dilution_fact_bindings(
            fixture.dilution, snapshot=fixture.snapshot, released_facts=facts
        )
    assert error.value.code == "DILUTION_FACT_SCOPE_MISMATCH"


def test_reviewed_newer_empty_inventory_preserves_prior_awards(tmp_path):
    fixture = _fixture(tmp_path)
    inventory = fixture.dilution.inventory
    period = inventory.period_end + timedelta(days=1)
    evidence = fixture.dilution.model_copy(
        update={
            "inventory": inventory.model_copy(
                update={
                    "period_end": period,
                    "instruments": (),
                    "coverage_evidence": inventory.coverage_evidence.model_copy(
                        update={
                            "as_of": inventory.coverage_evidence.as_of
                            + timedelta(days=1)
                        }
                    ),
                }
            )
        }
    )
    verify_dilution_fact_bindings(
        evidence, snapshot=fixture.snapshot, released_facts=fixture.facts.list()
    )
    prepared = _prepare(fixture, evidence)
    assert prepared.status == "prepared"
    assert prepared.equity_dilution.incremental_shares == 0
    assert {fact.fact_id for fact in fixture.dilution.facts} <= set(
        prepared.input.historical_facts
    )


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


@pytest.mark.parametrize("consumer", ["serving", "canary"])
def test_signed_quote_cannot_change_price_over_unchanged_source_bytes(
    tmp_path, consumer
):
    fixture = _fixture(tmp_path, released=False)
    evidence = fixture.dilution.model_copy(
        update={
            "quote": fixture.dilution.quote.model_copy(update={"price": Decimal(20)})
        }
    )
    fixture.artifacts.put_with_receipt(f"equity-dilution:{evidence.digest}", evidence)
    manifest = _manifest(
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
    fixture.manifest = manifest
    if consumer == "canary":
        candidate, canary = _reviewed_candidate(fixture)
        with pytest.raises(DataReleaseError) as error:
            canary.validate(candidate.manifest, candidate.verification)
        assert fixture.state.active is None
        assert fixture.state.publications == 0
    else:
        with pytest.raises(DilutionError) as error:
            _load(fixture)
    assert error.value.code == "DILUTION_QUOTE_SOURCE_VALUE_MISMATCH"


def _with_alternative_quote(fixture, *, quote=None, raw=None):
    raw = (
        raw if raw is not None else canonical_bytes({"price": "10", "currency": "USD"})
    )
    source_hash = sha256(raw).hexdigest()
    quote = (
        quote
        if quote is not None
        else fixture.dilution.quote.model_copy(
            update={
                "source_id": "synthetic-quote-vendor",
                "source_version": "synthetic-v1",
                "source_uri": "https://example.test/quotes/synthetic",
                "terms_reference": "synthetic-test-only",
                "content_hash": source_hash,
            }
        )
    )
    evidence = fixture.dilution.model_copy(update={"quote": quote})
    artifact_id = f"equity-dilution:{evidence.digest}"
    fixture.artifacts.put_with_receipt(artifact_id, evidence)
    fixture.artifacts.put_bytes_with_receipt(
        "alternative-quote", raw, media_type="application/json"
    )
    references = []
    for reference in fixture.manifest.artifact_refs:
        if reference.role == EQUITY_DILUTION_ARTIFACT_ROLE:
            reference = reference.model_copy(
                update={"artifact_id": artifact_id, "content_hash": evidence.digest}
            )
        elif reference.role == EQUITY_QUOTE_SOURCE_ROLE:
            reference = reference.model_copy(
                update={"artifact_id": "alternative-quote", "content_hash": source_hash}
            )
        references.append(reference)
    fixture.manifest = _manifest(fixture, tuple(references))
    fixture.dilution = evidence
    policy, refs = publish_synthetic_quote_admission(
        quote,
        raw,
        valuation_at=fixture.snapshot.valuation_timestamp,
        artifacts=fixture.artifacts,
    )
    fixture.manifest = _manifest(
        fixture,
        tuple(
            ref
            for ref in fixture.manifest.artifact_refs
            if ref.role
            not in {"equity-quote-source-admission-v1", "equity-quote-source-terms-v1"}
        )
        + refs,
    )
    fixture.application = replace(fixture.application, source_use_policy=policy)
    fixture.metadata.get_data_release_manifest = lambda digest: (
        fixture.manifest if digest == fixture.manifest.manifest_digest else None
    )


@pytest.mark.parametrize("consumer", ("serving", "canary"))
def test_serving_and_canary_use_configured_quote_provider_with_same_composer(
    tmp_path, consumer: str
):
    fixture = _fixture(tmp_path)
    _with_alternative_quote(fixture)
    if consumer == "canary":
        candidate, unconfigured = _reviewed_candidate(fixture)
        with pytest.raises(DataReleaseError) as error:
            unconfigured.validate(candidate.manifest, candidate.verification)
        candidate, configured = _reviewed_candidate(
            fixture, quote_providers=(SyntheticQuoteProvider(),)
        )
        report = configured.validate(candidate.manifest, candidate.verification)
        assert report.candidate_manifest_digest == candidate.manifest.manifest_digest
    else:
        request = ValuationEvidenceReadRequestV1(
            contract_version="fundamental.v1",
            snapshot_id=fixture.snapshot.snapshot_id,
            data_release_manifest_digest=fixture.manifest.manifest_digest,
            model_id="fcff_dcf",
        )
        with pytest.raises(ServiceError) as error:
            fixture.application.prepare_valuation(request)
        configured = replace(
            fixture.application, quote_providers=(SyntheticQuoteProvider(),)
        )
        prepared = configured.prepare_valuation(request)
        assert prepared.status == "prepared"
        assert prepared.equity_dilution.incremental_shares == Decimal(10)
        assert prepared.input.assumptions.capital_bridge.diluted_shares == Decimal(120)
        assert prepared.quality_status is QualityStatus.PROVISIONAL
    assert error.value.code == "DILUTION_QUOTE_SOURCE_PROFILE_UNSUPPORTED"


def test_quote_security_must_match_the_snapshot_identity(tmp_path):
    fixture = _fixture(tmp_path)
    evidence = fixture.dilution.model_copy(
        update={
            "quote": fixture.dilution.quote.model_copy(
                update={"security_id": "OTHER-CLASS"}
            )
        }
    )
    artifact_id = f"equity-dilution:{evidence.digest}"
    fixture.artifacts.put_with_receipt(artifact_id, evidence)
    fixture.manifest = _manifest(
        fixture,
        tuple(
            ref.model_copy(
                update={"artifact_id": artifact_id, "content_hash": evidence.digest}
            )
            if ref.role == EQUITY_DILUTION_ARTIFACT_ROLE
            else ref
            for ref in fixture.manifest.artifact_refs
        ),
    )

    with pytest.raises(DilutionError) as error:
        _load(fixture)

    assert error.value.code == "DILUTION_SNAPSHOT_MISMATCH"


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

    from fundamental_service.quote_sources import select_nasdaq_historical_close
    from test_preparation_runner import quote_source_bytes

    fixture = _fixture(tmp_path, released=False)
    from zoneinfo import ZoneInfo

    stale_date = fixture.snapshot.valuation_timestamp.astimezone(
        ZoneInfo("America/New_York")
    ).date() - timedelta(days=10)
    payload = json.loads(quote_source_bytes(fixture.snapshot))
    payload["data"]["tradesTable"]["rows"][0]["date"] = stale_date.strftime("%m/%d/%Y")
    source_bytes = canonical_bytes(payload)
    source_uri = (
        f"https://api.nasdaq.com/api/quote/{fixture.snapshot.identity.security_id}/historical"
        f"?assetclass=stocks&fromdate={stale_date.isoformat()}"
        f"&todate={(stale_date + timedelta(days=1)).isoformat()}&limit=10"
    )
    stale_quote = select_nasdaq_historical_close(
        source_bytes,
        issuer_id=fixture.snapshot.identity.issuer_id,
        security_id=fixture.snapshot.identity.security_id,
        source_uri=source_uri,
        observation_date=stale_date,
        captured_at=fixture.snapshot.valuation_timestamp,
    )
    evidence = fixture.dilution.model_copy(
        update={
            "quote": stale_quote,
        }
    )
    fixture.artifacts.put_with_receipt(f"equity-dilution:{evidence.digest}", evidence)
    quote_artifact_id = f"quote-source:{stale_quote.content_hash}"
    fixture.artifacts.put_bytes_with_receipt(
        quote_artifact_id, source_bytes, media_type="application/json"
    )
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
            else ref.model_copy(
                update={
                    "artifact_id": quote_artifact_id,
                    "content_hash": stale_quote.content_hash,
                }
            )
            if ref.role == EQUITY_QUOTE_SOURCE_ROLE
            else ref
            for ref in fixture.manifest.artifact_refs
        ),
    )
    policy, refs = publish_synthetic_quote_admission(
        stale_quote,
        source_bytes,
        valuation_at=fixture.snapshot.valuation_timestamp,
        artifacts=fixture.artifacts,
    )
    fixture.manifest = _manifest(
        fixture,
        tuple(
            ref
            for ref in fixture.manifest.artifact_refs
            if ref.role
            not in {"equity-quote-source-admission-v1", "equity-quote-source-terms-v1"}
        )
        + refs,
    )
    fixture.application = replace(fixture.application, source_use_policy=policy)
    candidate, canary = _reviewed_candidate(fixture)
    with pytest.raises(DataReleaseError) as error:
        canary.validate(candidate.manifest, candidate.verification)
    assert error.value.code == "DILUTION_QUOTE_STALE"
    assert fixture.state.active is None
    assert fixture.state.publications == 0


@pytest.mark.parametrize("rebuild_from_parser", [False, True])
def test_signed_release_retains_two_distinct_award_classes_without_scalar_collapse(
    tmp_path,
    rebuild_from_parser,
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
        if rebuild_from_parser:
            observations = [
                _rebuild_award_observation(fixture, fact) for fact in observations
            ]
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


def _rebuild_award_observation(fixture, observation):
    """Synthetic parser output uses the same scope shape as real Arelle output."""
    source = max(fixture.snapshot.source_records, key=lambda item: item.available_at)
    profile = ArelleValidationProfileV1(profile_id="synthetic-parser-shape-only")
    report = ArelleParseReportV1(
        filing_path="/synthetic/filing.htm",
        parser_version=source.parser_version.removeprefix("arelle-release=="),
        taxonomy_version="synthetic-us-gaap-2025",
        validation_profile=profile,
        validation_profile_digest=profile.digest(),
        parsed_at=source.captured_at,
        source_content_hash=source.parser_input_hash or source.content_hash,
        facts=(
            ParsedXbrlFactV1(
                concept=observation.concept,
                value=str(observation.value),
                unit=observation.unit,
                context_id=observation.context.context_id,
                instant=observation.instant,
                entity_identifier=observation.issuer_id,
                dimensions=tuple(
                    (item.name, item.member) for item in observation.context.dimensions
                ),
                is_numeric=True,
                consolidation_scope="segmented",
                security_scope="segmented",
            ),
        ),
    )
    candidates = parsed_facts_to_candidates(
        report,
        source=source,
        issuer_id=observation.issuer_id,
        security_id=observation.security_id,
        normalized_field=observation.normalized_field,
        mapping=fixture.mappings[observation.mapping_decision_id],
    )
    selections = select_fact_groups(candidates, fixture.snapshot.valuation_timestamp)
    assert len(selections) == 1 and selections[0].fact is not None
    fact = selections[0].fact
    assert fact.security_scope == "segmented"
    assert fact.context.dimensions == observation.context.dimensions
    return fact


@pytest.mark.parametrize("conditional", [False, True])
def test_coverage_and_performance_conditions_cannot_cite_unknown_originals(
    tmp_path, conditional
):
    fixture = _fixture(tmp_path)
    evidence = fixture.dilution
    inventory = evidence.inventory
    unknown = inventory.coverage_evidence.model_copy(
        update={"source_refs": ("f" * 64,)}
    )
    if conditional:
        original = inventory.instruments[0]
        award = PerformanceStockAwardV1(
            instrument_id=original.instrument_id,
            quantity=original.quantity,
            unrecognized_compensation=original.unrecognized_compensation,
            conditions_satisfied=True,
            condition_evidence=unknown,
        )
        inventory = inventory.model_copy(update={"instruments": (award,)})
    else:
        inventory = inventory.model_copy(update={"coverage_evidence": unknown})
    evidence = evidence.model_copy(update={"inventory": inventory})
    with pytest.raises(DilutionError) as error:
        verify_dilution_fact_bindings(
            evidence, snapshot=fixture.snapshot, released_facts=fixture.facts.list()
        )
    assert error.value.code == "DILUTION_REVIEW_SOURCE_MISMATCH"
