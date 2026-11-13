"""Empty-store automatic mapping uses validated originals and retains refusals."""

from types import SimpleNamespace
from dataclasses import replace

import pytest
from pydantic import ValidationError

from fundamental_service.automatic_mapping import automatic_mapping_policy_digest
from fundamental_service.automatic_mapping_batch import AutomaticMappingBatchDecisionV1
from fundamental_service.automatic_source_mapping import (
    AutomaticSecIngestionRequestV1,
    AutomaticSourceMappingAuthority,
)
from fundamental_service.contracts import SecCapturedSourceEvidenceV1, SourceRole
from fundamental_service.ingestion_mapping import ValidatedOriginalV1
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore
from fundamental_service.valuation_requirements import (
    source_preparation_requirements_profile,
    valuation_requirements_profile,
)
from test_automatic_mapping import EVALUATOR, MACHINE_KEY, REVISION
from test_automatic_mapping_security import security_case
from test_issuer_operating_release import inventory


def source_case(tmp_path):
    single, artifacts, roots = security_case(tmp_path / "source")
    profile = valuation_requirements_profile("fcff_dcf")
    request = AutomaticSecIngestionRequestV1(
        contract_version="fundamental.v1",
        identity=single.security_identity,
        cik=single.original.source.cik,
        ticker=single.security_identity.security_id,
        identity_basis="original-filing-dei-v1",
        valuation_timestamp=single.original.decision_at,
        required_fields=profile.required_fact_fields,
        source_selection_policy="sec-pit-v1",
        coverage_profile="automatic-fcff-v1",
        legal_use_profile="sec-public-us-v1",
        filing={
            "accession_number": single.original.source.accession_number,
            "forms": ("10-K",),
        },
        parser_version="2.47.4",
        validation_profile_id="sec-efm-us-dqc-v31.0.3",
        taxonomy_manifest_id="synthetic-taxonomy",
        taxonomy_version="us-gaap-2015",
        policy_version="source-preparation-v1",
        source_revision=REVISION,
        evaluator_id=EVALUATOR,
        mapping_policy_digest=automatic_mapping_policy_digest(),
        mapping_version="automatic-source-v1",
        model_id="fcff_dcf",
        model_version="fcff_dcf-v2",
        requirements_digest=profile.digest,
    )
    content = FilesystemContentStore(tmp_path / "content")
    sources = []
    integrity = single.integrity
    for name, digest, media_type in (
        ("sec-filing", integrity.raw_content_hash, "application/xml"),
        ("sec-filing-archive", integrity.archive_hash, "application/zip"),
        ("sec-filing-index", integrity.archive_index_hash, "application/json"),
        (
            "taxonomy",
            single.original.report.taxonomy_cache_hash,
            "application/octet-stream",
        ),
    ):
        ref = next(r for r in single.evidence_refs if r.content_hash == digest)
        raw = artifacts.read(ref.artifact_id)
        assert content.put(raw, media_type=media_type) == digest
        if name == "taxonomy":
            continue
        sources.append(
            SecCapturedSourceEvidenceV1(
                source_id=name,
                uri=single.original.source.uri,
                role=SourceRole.FILING
                if name == "sec-filing"
                else SourceRole.ACQUISITION,
                media_type=media_type,
                http_status=200,
                available_at=single.original.source.available_at,
                captured_at=single.original.source.captured_at,
                content_hash=digest,
                received_size=len(raw),
            )
        )
    validated = ValidatedOriginalV1(
        identity=single.security_identity,
        original=single.original,
        integrity=integrity,
        captured_sources=tuple(sources),
        primary_media_type="application/xml",
    )
    mappings = {}
    authority = AutomaticSourceMappingAuthority(
        artifacts=artifacts,
        content=content,
        metadata=SimpleNamespace(
            publish_mapping=lambda m: mappings.setdefault(m.decision_id, m)
        ),
        trust_roots=roots,
        private_key=MACHINE_KEY,
        source_revision=REVISION,
        taxonomy_cache_dir=tmp_path / "not-needed-for-retained-manifest",
        taxonomy_cache_sha256=single.original.report.taxonomy_cache_hash,
    )
    return request, authority, validated, artifacts, mappings


def test_retained_v3_requirements_cannot_authorize_v4_acquisition(tmp_path):
    request, _, _, _, _ = source_case(tmp_path)
    current = valuation_requirements_profile("fcff_dcf")
    previous = current.model_copy(
        update={
            "profile_id": "fcff-valuation-requirements-v3",
            "profile_version": "fcff-valuation-requirements-v3",
            "annual_duration_fields": (
                "revenue",
                "cost_of_revenue",
                "operating_income",
                "income_before_tax",
                "income_tax_expense",
                "net_income",
                "depreciation_and_amortization",
                "capital_expenditure",
                "operating_lease_cost",
                "finance_lease_cost",
                "stock_based_compensation",
                "basic_weighted_average_shares",
                "diluted_weighted_average_shares",
            ),
            "supporting_fact_fields": tuple(
                f
                for f in current.supporting_fact_fields
                if f.startswith("equity_award_")
            ),
        }
    )
    assert previous.digest != current.digest
    payload = request.model_dump(mode="json") | {
        "requirements_digest": previous.digest,
        "required_fields": list(previous.required_fact_fields),
    }
    with pytest.raises(ValidationError, match="exact service model requirements"):
        AutomaticSecIngestionRequestV1.model_validate_json(canonical_bytes(payload))


def test_empty_store_publishes_approved_mappings_and_every_abstention(tmp_path):
    request, authority, validated, artifacts, mappings = source_case(tmp_path)
    assert not mappings
    result = authority.resolver_for(request).resolve(validated)
    batch = AutomaticMappingBatchDecisionV1.model_validate_json(
        artifacts.read(result.evidence_ref)
    )
    assert result.mappings and all(
        mappings[m.decision_id] == m for m in result.mappings
    )
    assert len(batch.roles) == len(
        set(batch.requirements.required_fact_fields)
        | set(batch.requirements.supporting_fact_fields)
    )
    assert any(
        m.normalized_field == "stock_based_compensation" for m in result.mappings
    )
    assert any(
        i.field == "non_operating_assets"
        and i.code == "MAPPING_AUTOMATIC_RULE_UNSUPPORTED"
        for i in result.issues
    )
    assert "non_operating_assets" in result.missing_fields
    assert batch.policy_digest == request.mapping_policy_digest
    assert batch.source_revision == request.source_revision
    before = inventory(artifacts.root)
    again = authority.resolver_for(request).resolve(validated)
    assert sha256_digest(again) == sha256_digest(result)
    assert before == inventory(artifacts.root)


def test_automatic_source_retains_composite_totals_and_optional_exclusion_refusals(
    tmp_path,
):
    request, authority, validated, artifacts, _ = source_case(tmp_path)
    profile = source_preparation_requirements_profile("fcff_dcf", composite_inputs=True)
    request = type(request)(
        **(
            request.model_dump()
            | {
                "required_fields": profile.required_fact_fields,
                "requirements_digest": profile.digest,
            }
        )
    )
    first = authority.resolver_for(request).resolve(validated)
    batch = AutomaticMappingBatchDecisionV1.model_validate_json(
        artifacts.read(first.evidence_ref)
    )
    assert batch.requirements == profile
    roles = {role.normalized_field: role for role in batch.roles}
    assert {
        "current_assets",
        "current_liabilities",
        "short_term_investments",
        "cash_and_short_term_investments",
    } <= roles.keys()
    assert "contract_assets" not in roles
    assert roles["short_term_investments"].status == "abstain"
    assert roles["short_term_investments"].approval is None
    assert profile.supported_history_threshold is None
    before = inventory(artifacts.root)
    assert authority.resolver_for(request).resolve(validated) == first
    assert inventory(artifacts.root) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"model_version": "unknown"},
        {"requirements_digest": "b" * 64},
        {"identity_basis": "current-sec-ticker-v1"},
        {"mappings": ()},
        {"required_fields": ("revenue",)},
        {"filing": {"forms": ("10-K",)}},
    ],
)
def test_automatic_contract_rejects_unpinned_or_manual_inputs(tmp_path, changes):
    request, _, _, _, _ = source_case(tmp_path)
    with pytest.raises(ValidationError):
        AutomaticSecIngestionRequestV1.model_validate(
            {**request.model_dump(), **changes}
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_revision": "b" * 40},
        {"mapping_policy_digest": "b" * 64},
        {"evaluator_id": "untrusted"},
    ],
)
def test_mismatched_authority_or_runtime_refuses_without_writes(tmp_path, changes):
    request, authority, validated, artifacts, mappings = source_case(tmp_path)
    before = inventory(artifacts.root)
    with pytest.raises(DataReleaseError):
        authority.resolver_for(request.model_copy(update=changes))
    assert before == inventory(artifacts.root) and not mappings


def test_wrong_machine_key_refuses_without_writes(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    request, authority, _, artifacts, mappings = source_case(tmp_path)
    before = inventory(artifacts.root)
    with pytest.raises(DataReleaseError) as error:
        replace(
            authority, private_key=Ed25519PrivateKey.from_private_bytes(b"x" * 32)
        ).resolver_for(request)
    assert error.value.code == "MAPPING_AUTOMATIC_AUTHORITY_MISMATCH"
    assert before == inventory(artifacts.root) and not mappings


def test_validated_source_or_taxonomy_mismatch_refuses_before_publication(tmp_path):
    request, authority, validated, artifacts, mappings = source_case(tmp_path)
    before = inventory(artifacts.root)
    wrong = replace(authority, taxonomy_cache_sha256="b" * 64)
    with pytest.raises(DataReleaseError) as error:
        wrong.resolver_for(request).resolve(validated)
    assert error.value.code == "MAPPING_AUTOMATIC_SOURCE_MISMATCH"
    assert before == inventory(artifacts.root) and not mappings


def test_retry_after_mapping_publication_interruption_reuses_immutable_evidence(
    tmp_path,
):
    from fundamental_service.snapshots import SnapshotError

    request, authority, validated, artifacts, mappings = source_case(tmp_path)
    interrupted = replace(
        authority,
        metadata=SimpleNamespace(
            publish_mapping=lambda mapping: (_ for _ in ()).throw(
                SnapshotError(
                    "SIMULATED_INTERRUPTION", "before mapping metadata publication"
                )
            )
        ),
    )
    with pytest.raises(SnapshotError, match="before mapping metadata publication"):
        interrupted.resolver_for(request).resolve(validated)
    retained = inventory(artifacts.root)
    result = authority.resolver_for(request).resolve(validated)
    assert result.mappings and mappings
    assert retained == inventory(artifacts.root)
