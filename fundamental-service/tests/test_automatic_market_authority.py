"""Deployment settings authorize reusable rules, never supplied classification claims."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest

from fundamental_service.automatic_market_authority import (
    AutomaticMarketAuthorityRuntime,
    AutomaticMarketPolicyAuthorizationV1,
    authorize_compiled_market_policy,
)
from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
from fundamental_service.original_source_plan import (
    AutomaticIssuerMarketPolicyTemplateV1,
    OriginalSourcePlanRequestV1,
    OriginalSourcePlanEvidenceV1,
    OriginalSourcePlan,
    compile_issuer_market_request,
)
from fundamental_service.policies import initial_model_specs
from fundamental_service.public_acquisition import PublicSourceAcquisitionRequestV1
from fundamental_service.public_admission import PublicSourceAdmissionRequestV1
from fundamental_service.source_plan_contracts import SOURCE_PREPARATION_PLAN
from fundamental_service.snapshots import SnapshotError
from fundamental_service.serialization import sha256_digest
from test_automatic_market_policy import _admissions
from test_automatic_source_mapping import source_case
from test_automatic_source_preparation import automatic_plan
from test_issuer_market_preparation import execute, fixture
from test_original_source_plan import configuration
from test_original_preparation import case as original_case
from test_public_acquisition import inventory
from test_release_runner import _candidate


def authority_case(tmp_path):
    f = fixture(tmp_path)
    request = f.request
    terminal = request.market_policy.terminal_growth_plan
    config = configuration(
        issuer_market_policy_template=AutomaticIssuerMarketPolicyTemplateV1(
            classification_provider_id=request.classification_provider_id,
            country_policy=request.country_policy,
            industry_policy=request.industry_policy,
            reference_policy=request.reference_policy,
            market_policy_version=request.market_policy.policy_version,
            risk_free_policy=request.market_policy.risk_free_policy,
            terminal_growth_policy_id=terminal.policy_id,
            gdp_horizon_years=terminal.gdp_horizon_years,
            maximum_gdp_period_age_days=terminal.maximum_gdp_period_age_days,
        )
    )
    compiler = OriginalSourcePlanRequestV1(
        original_preparation=ArtifactRefV1(
            artifact_id="synthetic-original-preparation",
            content_hash="0" * 64,
            media_type="application/json",
            role="sec-original-preparation-v1",
        ),
        configuration=config,
        runtime_source_revision=request.source_revision,
    )
    model = initial_model_specs()[0]
    f.request = compile_issuer_market_request(
        compiler, model=model, classification=request.classification_request
    )
    f.artifacts.put_with_receipt(
        "original-source-plan-request:" + compiler.digest, compiler
    )
    # Source/compiler ports stand in for their independently tested retained replay.
    source_admissions = _admissions(f.snapshot.valuation_timestamp)
    sources = {}
    decisions = {}
    public_requests = []
    for admitted in source_admissions:

        def requests(artifacts):
            result = []
            for artifact in artifacts:
                capture_request = PublicSourceAcquisitionRequestV1(
                    source_id=artifact.source_id,
                    uri=artifact.uri,
                    source_profile=artifact.source_version,
                    terms_reference=artifact.terms_reference,
                    valuation_timestamp=f.snapshot.valuation_timestamp,
                )
                sources[capture_request.digest] = capture_request
                result.append(capture_request.digest)
            return tuple(sorted(result))

        raw_request = admitted.request
        planned = PublicSourceAdmissionRequestV1(
            **raw_request.model_dump(exclude={"source_artifacts", "terms_artifacts"}),
            source_request_digests=requests(raw_request.source_artifacts),
            terms_request_digests=requests(raw_request.terms_artifacts),
        )
        public_requests.append(planned)
        decisions[planned.digest] = SimpleNamespace(
            admission=admitted, issue_codes=(), release_refs=()
        )
    seed = source_case(tmp_path / "plan-seed")[0]
    seed = seed.model_copy(
        update={
            "identity": f.snapshot.identity,
            "cik": f.snapshot.identity.issuer_id,
            "valuation_timestamp": f.snapshot.valuation_timestamp,
            "source_revision": f.request.source_revision,
            "filing": seed.filing.model_copy(
                update={
                    "accession_number": f.request.classification_request.accession_number
                }
            ),
        }
    )
    plan = SOURCE_PREPARATION_PLAN.validate_python(
        {
            **automatic_plan(seed).model_dump(),
            "issuer_market_policy": f.request,
            "public_sources": tuple(sources[key] for key in sorted(sources)),
            "source_admissions": tuple(sorted(public_requests, key=lambda x: x.digest)),
        }
    )
    compiled = OriginalSourcePlanEvidenceV1(
        request=compiler, plan=plan, issue_codes=(), retryable=False
    )
    owners = AutomaticMarketAuthorityRuntime(
        compiler=SimpleNamespace(read=lambda _: compiled),
        current=None,
        acquisitions=SimpleNamespace(
            read=lambda artifact_id: SimpleNamespace(
                request=sources[artifact_id.split(":", 1)[1]]
            )
        ),
        admissions=SimpleNamespace(
            execute=lambda planned, captures: (decisions[planned.digest], None)
        ),
        preparation=f.preparation,
    )
    evidence, _ = execute(f)
    manifest = _candidate()[0]
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload.update(
        artifact_refs=evidence.release_refs,
        snapshot_refs=(
            manifest.snapshot_refs[0].model_copy(
                update={
                    "snapshot_id": f.snapshot.snapshot_id,
                    "manifest_digest": f.snapshot.manifest_digest,
                }
            ),
        ),
    )
    manifest = type(manifest)(**payload, manifest_digest=sha256_digest(payload))
    kwargs = dict(
        authorization=AutomaticMarketPolicyAuthorizationV1(
            source_plan_configuration_digest=config.digest
        ),
        model=model,
        snapshot=f.snapshot,
        admissions=source_admissions,
        artifacts=f.artifacts,
        owners=owners,
        source_plan=plan,
        source_revision=request.source_revision,
    )
    return SimpleNamespace(
        f=f, manifest=manifest, kwargs=kwargs, compiler=compiler, compiled=compiled
    )


def test_configuration_authorizes_reproduced_policy_without_publishing_it(tmp_path):
    case = authority_case(tmp_path)
    before = inventory(tmp_path)
    first = authorize_compiled_market_policy(case.manifest, **case.kwargs)
    assert first.issuer_id == case.f.snapshot.identity.issuer_id
    assert first.market_inputs is not None
    assert first.assumptions is None
    assert first.data_release_manifest_digest == case.manifest.manifest_digest
    assert (
        first.policy_id == case.f.request.market_policy.terminal_growth_plan.policy_id
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeated = tuple(
            pool.map(
                lambda _: authorize_compiled_market_policy(
                    case.manifest, **case.kwargs
                ),
                range(2),
            )
        )
    assert all(item == first for item in repeated)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize(
    "fault,code",
    [
        ("settings", "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH"),
        ("revision", "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH"),
        ("model", "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH"),
        ("snapshot", "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH"),
        ("missing", "AUTOMATIC_MARKET_AUTHORITY_EVIDENCE_INVALID"),
        ("ambiguous", "AUTOMATIC_MARKET_AUTHORITY_EVIDENCE_INVALID"),
        ("hash", "AUTOMATIC_MARKET_AUTHORITY_EVIDENCE_INVALID"),
        ("source", "AUTOMATIC_MARKET_AUTHORITY_REPLAY_MISMATCH"),
        ("admissions", "AUTOMATIC_MARKET_AUTHORITY_REPLAY_MISMATCH"),
        ("selected_original", "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH"),
        ("source_plan", "AUTOMATIC_MARKET_AUTHORITY_CONTEXT_MISMATCH"),
    ],
)
def test_unapproved_context_and_changed_evidence_never_produce_a_policy(
    tmp_path, fault, code
):
    case = authority_case(tmp_path)
    kwargs = dict(case.kwargs)
    manifest = case.manifest
    if fault == "settings":
        kwargs["authorization"] = AutomaticMarketPolicyAuthorizationV1(
            source_plan_configuration_digest="a" * 64
        )
    elif fault == "revision":
        kwargs["source_revision"] = "2" * 40
    elif fault == "model":
        kwargs["model"] = initial_model_specs()[1]
    elif fault == "snapshot":
        kwargs["snapshot"] = case.f.snapshot.model_copy(
            update={"manifest_digest": "a" * 64}
        )
    elif fault == "source":
        source = case.f.snapshot.source_records[0]
        case.f.content._path(source.content_hash, source.media_type).write_bytes(
            b"corrupt SEC original"
        )
    elif fault == "admissions":
        kwargs["admissions"] = ()
    elif fault == "selected_original":
        market = case.f.request
        market = market.model_copy(
            update={
                "classification_request": market.classification_request.model_copy(
                    update={"accession_number": "0000320193-26-000001"}
                )
            }
        ).with_policy_identity(market.automatic_policy_identity)
        kwargs["source_plan"] = kwargs["source_plan"].model_copy(
            update={"issuer_market_policy": market}
        )
    elif fault == "source_plan":
        kwargs["source_plan"] = kwargs["source_plan"].model_copy(
            update={"source_admissions": ()}
        )
    else:
        refs = manifest.artifact_refs
        ref = next(x for x in refs if x.role == "issuer-market-preparation-v1")
        refs = (
            tuple(x for x in refs if x != ref)
            if fault == "missing"
            else (*refs, ref)
            if fault == "ambiguous"
            else tuple(
                x.model_copy(update={"content_hash": "a" * 64}) if x == ref else x
                for x in refs
            )
        )
        manifest = manifest.model_copy(update={"artifact_refs": refs})
    with pytest.raises(DataReleaseError) as error:
        authorize_compiled_market_policy(manifest, **kwargs)
    assert error.value.code == code


def test_forged_compilation_with_missing_original_is_refused_by_actual_reader(
    tmp_path, monkeypatch
):
    case = authority_case(tmp_path / "market")
    upstream = original_case(tmp_path / "upstream", monkeypatch)
    store = case.f.artifacts
    compiler_request = case.compiler
    store.put_with_receipt(
        "source-plan-configuration:" + compiler_request.configuration.digest,
        compiler_request.configuration,
    )
    store.put_with_receipt(
        "source-preparation-plan:" + case.compiled.plan.digest, case.compiled.plan
    )
    store.put_with_receipt(
        case.compiled.artifact_id, case.compiled, case.compiled.dependencies
    )
    owners = replace(
        case.kwargs["owners"],
        compiler=OriginalSourcePlan(
            originals=upstream.service,
            artifacts=store,
            compilation_lock=upstream.locks,
        ),
    )
    with pytest.raises(SnapshotError) as failure:
        authorize_compiled_market_policy(
            case.manifest, **(case.kwargs | {"owners": owners})
        )
    assert failure.value.code == "ARTIFACT_NOT_FOUND"
