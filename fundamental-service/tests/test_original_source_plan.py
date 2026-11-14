"""Saved originals compile into executable plans without new source authority."""

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from fundamental_service.bea_source import BEA_CURRENT_GDP_PROFILE, BEA_CURRENT_GDP_URI
from fundamental_service.damodaran_source import (
    DAMODARAN_CAPITAL_PROFILE,
    DAMODARAN_COUNTRY_CURRENT_PROFILE,
    DAMODARAN_SOURCE,
    DAMODARAN_TERMS,
)
from fundamental_service.free_source_policy import (
    DAMODARAN_USE_URI,
    US_GOVERNMENT_WORKS_URI,
    free_market_source_policy,
)
from fundamental_service.automatic_mapping import automatic_mapping_policy_digest
from fundamental_service.classification_crosswalk import ClassificationCrosswalkPolicyV1
from fundamental_service.issuer_country_crosswalk import CountryCrosswalkPolicyV1
from fundamental_service.issuer_market_policy_plan import (
    IssuerMarketReferencePlanPolicyV1,
)
from fundamental_service.market_source_selection import USD_RISK_FREE_POLICY
from fundamental_service.bea_source import BEA_GDP_TERMS
from fundamental_service.treasury_source import (
    TREASURY_PROFILE,
    TREASURY_SOURCE,
    TREASURY_TERMS,
)
from fundamental_service.arelle_parser import ArelleParserError
from fundamental_service.operations import ServiceError
from fundamental_service.original_source_plan import (
    AutomaticMarketSourceTemplateV1,
    AutomaticMarketSourcesTemplateV1,
    AutomaticPublicSourceRequestTemplateV1,
    AutomaticIssuerMarketPolicyTemplateV1,
    AutomaticWorkingCapitalRecipeTemplateV1,
    AutomaticSourcePlanConfigurationV1,
    OriginalSourcePlan,
    OriginalSourcePlanRequestV1,
)
from fundamental_service.preparation_runner import (
    SourcePreparationEvidenceV1,
    SourcePreparationRunner,
)
from fundamental_service.source_plan_contracts import SOURCE_PREPARATION_PLAN
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import SecSourceError
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.sec_sic_damodaran_crosswalk import (
    SecSicDamodaranIndustryCrosswalk,
)
from fundamental_service.sec_state_country_crosswalk import SecStateCountryCrosswalk
from fundamental_service.snapshots import SnapshotError
from fundamental_service.valuation_requirements import (
    composite_working_capital_requirements_profile,
    source_preparation_requirements_profile,
)
from fundamental_service.working_capital import InclusionScenariosV1
from fundamental_service.working_capital_preparation import (
    WorkingCapitalExclusionRecipeV1,
)
from test_annual_discovery_service import _inventory
from test_automatic_source_preparation import run
from test_original_preparation import case, execute
from test_automatic_market_policy import _market_policy
from test_public_admission import admission_fixture
from test_source_admission import METRIC, _source, _terms


def configuration(
    model_id="fcff_dcf",
    *,
    working_capital_recipe_template=None,
    issuer_market_policy_template=None,
):
    return AutomaticSourcePlanConfigurationV1(
        model_id=model_id,
        release_profile_id="automatic-original-fcff",
        coverage_profile="automatic-fcff-v1",
        evaluator_id="machine-evaluator",
        mapping_version="automatic-source-v1",
        policy_version="source-preparation-v1",
        working_capital_recipe_template=working_capital_recipe_template,
        issuer_market_policy_template=issuer_market_policy_template,
    )


def working_capital_recipe_template():
    return AutomaticWorkingCapitalRecipeTemplateV1(
        exclusions=tuple(
            WorkingCapitalExclusionRecipeV1(
                account_class=role,
                mapped_fact_role=role,
                state="reported",
                rationale=f"Use the source-mapped {role.replace('_', ' ')} amount.",
            )
            for role in sorted(
                (
                    "cash_and_equivalents",
                    "current_interest_bearing_debt",
                    "current_finance_lease_liabilities",
                    "current_operating_lease_liabilities",
                    "short_term_investments",
                )
            )
        ),
        asset_residual=InclusionScenariosV1(
            low=Decimal("0"),
            central=Decimal("0.5"),
            high=Decimal("1"),
            rationale="Expose a deterministic asset residual sensitivity range.",
        ),
        liability_residual=InclusionScenariosV1(
            low=Decimal("0"),
            central=Decimal("0.5"),
            high=Decimal("1"),
            rationale="Expose a deterministic liability residual sensitivity range.",
        ),
        perimeter_rationale="Apply the configured operating perimeter to each retained annual filing.",
    )


def _public_request(source_id, uri, profile, terms_reference):
    return AutomaticPublicSourceRequestTemplateV1(
        source_id=source_id,
        uri_template=uri,
        source_profile=profile,
        terms_reference=terms_reference,
    )


def _terms_request(source_id, uri):
    return _public_request(source_id, uri, f"{source_id}-v1", uri)


def _market_source(kind, metric_id, source, terms):
    return AutomaticMarketSourceTemplateV1(
        kind=kind,
        provider_id=(
            "bea-nipa-current"
            if metric_id == "us.nominal_gdp"
            else "us-treasury"
            if metric_id == "us.treasury_par_yield_10y"
            else "damodaran-public-aggregates"
        ),
        metric_id=metric_id,
        sources=(source,),
        terms=terms,
    )


def issuer_market_policy_template():
    country = SecStateCountryCrosswalk()
    industry = SecSicDamodaranIndustryCrosswalk()
    market = _market_policy(datetime(2026, 11, 13, tzinfo=UTC))
    source_use = free_market_source_policy()
    bea_terms = (
        _terms_request("bea-citation-terms", BEA_GDP_TERMS),
        _terms_request("us-government-works-terms", US_GOVERNMENT_WORKS_URI),
    )
    government_terms = (
        _terms_request("us-government-works-terms", US_GOVERNMENT_WORKS_URI),
    )
    damodaran_terms = (_terms_request("damodaran-use-terms", DAMODARAN_USE_URI),)
    capital_source = _public_request(
        DAMODARAN_SOURCE,
        "https://pages.stern.nyu.edu/~adamodar/pc/datasets/wacc.xls",
        DAMODARAN_CAPITAL_PROFILE,
        DAMODARAN_TERMS,
    )
    sources = (
        _market_source(
            "macro",
            "us.nominal_gdp",
            _public_request(
                "bea-nipa-current",
                BEA_CURRENT_GDP_URI,
                BEA_CURRENT_GDP_PROFILE,
                BEA_GDP_TERMS,
            ),
            bea_terms,
        ),
        _market_source(
            "macro",
            "us.treasury_par_yield_10y",
            _public_request(
                TREASURY_SOURCE,
                "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={valuation_year}",
                TREASURY_PROFILE,
                TREASURY_TERMS,
            ),
            government_terms,
        ),
        _market_source(
            "reference",
            "country.equity_risk_premium",
            _public_request(
                DAMODARAN_SOURCE,
                "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xlsx",
                DAMODARAN_COUNTRY_CURRENT_PROFILE,
                DAMODARAN_TERMS,
            ),
            damodaran_terms,
        ),
        *(
            _market_source("reference", metric, capital_source, damodaran_terms)
            for metric in (
                "industry.equity_beta",
                "industry.pre_tax_cost_of_debt",
                "industry.debt_weight",
                "industry.equity_weight",
            )
        ),
    )
    return AutomaticIssuerMarketPolicyTemplateV1(
        classification_provider_id="sec-submissions-classification-v1",
        country_policy=CountryCrosswalkPolicyV1(
            provider_id=country.provider_id,
            mapping_version=country.mapping_version,
            mapping_digest=country.mapping_digest,
            source_scheme="sec-state-country-v1",
            target_taxonomy=country.target_taxonomy,
        ),
        industry_policy=ClassificationCrosswalkPolicyV1(
            provider_id=industry.provider_id,
            mapping_version=industry.mapping_version,
            mapping_digest=industry.mapping_digest,
            source_scheme="sec-sic-v1",
            target_taxonomy=industry.target_taxonomy,
        ),
        reference_policy=IssuerMarketReferencePlanPolicyV1(),
        market_policy_version=market.policy_version,
        risk_free_policy=USD_RISK_FREE_POLICY,
        terminal_growth_policy_id=market.terminal_growth_plan.policy_id,
        gdp_horizon_years=market.terminal_growth_plan.gdp_horizon_years,
        maximum_gdp_period_age_days=(
            market.terminal_growth_plan.maximum_gdp_period_age_days
        ),
        source_plan_template=AutomaticMarketSourcesTemplateV1(
            source_use_policy_version=source_use.policy_version,
            source_use_policy_digest=source_use.digest,
            market_sources=tuple(
                sorted(
                    sources,
                    key=lambda item: (item.kind, item.provider_id, item.metric_id),
                )
            ),
        ),
    )


def test_configuration_rejects_models_without_an_automatic_source_policy():
    with pytest.raises(ValueError):
        configuration("bank_excess_return")


@pytest.mark.parametrize(
    "uri",
    (
        "https://example.com/{issuer_id}",
        "https://example.com/{valuation_date.__class__}",
        "https://example.com/{valuation_year!r}",
        "https://example.com/{valuation_year:>4}",
        "https://example.com/{valuation_date",
        "http://example.com/{valuation_date}",
        "https://secret@example.com/{valuation_date}",
    ),
)
def test_public_source_template_rejects_unsupported_substitutions_and_uris(uri):
    with pytest.raises(ValueError):
        _public_request("configured", uri, "profile-v1", "https://example.com/terms")


def test_public_source_template_uses_same_utc_date_for_equal_instants():
    template = _public_request(
        "configured",
        "https://example.com/{valuation_year}/{valuation_date}",
        "profile-v1",
        "https://example.com/terms",
    )
    utc = datetime(2025, 12, 31, 23, tzinfo=UTC)
    local = utc.astimezone(timezone(timedelta(hours=8)))
    assert template.render(utc) == template.render(local)
    assert template.render(local).uri == "https://example.com/2025/2025-12-31"
    assert template.render(utc).digest == template.render(local).digest


def test_market_template_rejects_duplicate_metrics_and_invalid_reference_roles():
    template = issuer_market_policy_template().source_plan_template
    payload = template.model_dump()
    payload["market_sources"] = (
        *payload["market_sources"],
        payload["market_sources"][0],
    )
    with pytest.raises(ValueError, match="canonical"):
        AutomaticMarketSourcesTemplateV1.model_validate(payload)
    source = next(item for item in template.market_sources if item.kind == "reference")
    with pytest.raises(ValueError):
        AutomaticMarketSourceTemplateV1.model_validate(
            {**source.model_dump(), "metric_id": "unknown.metric"}
        )


def test_market_request_template_without_source_configuration_keeps_retained_digest():
    payload = issuer_market_policy_template().model_dump(
        exclude={"source_plan_template"}
    )
    loaded = AutomaticIssuerMarketPolicyTemplateV1.model_validate(payload)
    assert loaded.source_plan_template is None
    assert canonical_bytes(loaded) == canonical_bytes(payload)


def compiler_case(value, prepared, config=None):
    compiler = OriginalSourcePlan(
        originals=value.service,
        artifacts=value.artifacts,
        compilation_lock=value.locks,
    )
    request = OriginalSourcePlanRequestV1(
        original_preparation=value.service.reference(
            prepared.artifact_id, "sec-original-preparation-v1"
        ),
        configuration=config or configuration(),
        runtime_source_revision=value.annual_request.declared_source_revision,
    )
    return compiler, request


@pytest.mark.parametrize(
    ("model_id", "model_version"),
    [("fcff_dcf", "fcff_dcf-v2"), ("transition_fcff_dcf", "transition_fcff_dcf-v2")],
)
def test_saved_original_supplies_identity_and_installed_model_pins(
    tmp_path, monkeypatch, model_id, model_version
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(value, prepared, configuration(model_id))
    calls = value.state.provider_calls, value.state.parser_calls
    result, publication = compiler.execute(request)
    assert publication.wrote and not result.issue_codes
    plan = result.plan
    assert SOURCE_PREPARATION_PLAN.validate_json(canonical_bytes(plan)) == plan
    ingestion = plan.ingestions[0]
    validated = value.service.read_validation(
        prepared.filings[0].validation.artifact_id
    )
    assert ingestion.identity == prepared.filings[0].identity == value.expected_identity
    assert ingestion.ticker == value.expected_identity.security_id
    assert (
        ingestion.filing.accession_number == validated.request.filing.accession_number
    )
    assert ingestion.valuation_timestamp == validated.request.valuation_timestamp
    assert ingestion.model_id == model_id and ingestion.model_version == model_version
    assert ingestion.mapping_policy_digest == automatic_mapping_policy_digest()
    assert ingestion.requirements_digest == plan.requirements_profile.digest
    assert ingestion.required_fields == plan.requirements_profile.required_fact_fields
    assert (
        ingestion.fiscal_period_selector.count
        == plan.requirements_profile.history_window_years
    )
    assert (
        ingestion.taxonomy_manifest_id == prepared.request.runtime.taxonomy_manifest_id
    )
    assert plan.source_revision == request.runtime_source_revision
    assert plan.source_revision == value.annual_request.declared_source_revision
    assert plan.requirements_profile.supported_history_threshold is None
    assert value.artifacts.read(result.plan_ref.artifact_id) == canonical_bytes(plan)
    assert (
        value.metadata.snapshots
        == value.metadata.mappings
        == value.metadata.acquisitions
        == {}
    )
    assert calls == (value.state.provider_calls, value.state.parser_calls)


@pytest.mark.parametrize("with_market", (False, True))
def test_repeat_reopened_and_concurrent_compilers_publish_once_without_io(
    tmp_path, monkeypatch, with_market
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(
        value,
        prepared,
        configuration(
            issuer_market_policy_template=(
                issuer_market_policy_template() if with_market else None
            )
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("compilation must not contact provider/parser")

    monkeypatch.setattr(value.acquisition.adapter, "_request", forbidden)
    monkeypatch.setattr(value.acquisition.ingestion, "validate_filing", forbidden)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: compiler.execute(request), range(3)))
    assert sum(publication.wrote for _, publication in results) == 1
    assert len({result.digest for result, _ in results}) == 1
    expected = results[0][0]
    before = _inventory(tmp_path)
    reopened = OriginalSourcePlan(
        originals=value.service,
        artifacts=ArtifactStore(value.artifacts.root),
        compilation_lock=value.locks,
    )
    assert reopened.read(expected.artifact_id) == expected
    again, publication = reopened.execute(request)
    assert again == expected and not publication.wrote
    assert _inventory(tmp_path) == before


def test_recipe_template_expands_saved_original_and_pins_composite_requirements(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    template = working_capital_recipe_template()
    compiler, request = compiler_case(
        value,
        prepared,
        configuration(working_capital_recipe_template=template),
    )

    result, publication = compiler.execute(request)

    assert publication.wrote and not result.issue_codes
    assert result.plan is not None
    recipe = result.plan.valuation_working_capital_recipe
    assert recipe is not None
    assert recipe.model_version == "fcff_dcf-v2"
    assert recipe.mapping_version == request.configuration.mapping_version
    assert recipe.requirements_profile_digest == (
        composite_working_capital_requirements_profile(
            request.configuration.model_id, operating_only=False
        ).digest
    )
    expected_filings = tuple(
        sorted(
            [
                (
                    value.service.read_validation(
                        item.validation.artifact_id
                    ).request.filing.accession_number,
                    value.service.read_validation(
                        item.validation.artifact_id
                    ).request.filing.report_period_end,
                )
                for item in prepared.filings
            ],
            key=lambda item: item[1],
        )
    )
    assert (
        tuple((item.accession_number, item.period_end) for item in recipe.periods)
        == expected_filings
    )
    assert all(
        request.requirements_digest == result.plan.requirements_profile.digest
        for request in result.plan.ingestions
    )
    assert result.plan.requirements_profile == source_preparation_requirements_profile(
        request.configuration.model_id, composite_inputs=True
    )
    assert not compiler.execute(request)[1].wrote


def test_issuer_market_template_derives_identity_accession_and_date_from_saved_original(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    template = issuer_market_policy_template()
    compiler, request = compiler_case(
        value,
        prepared,
        configuration(issuer_market_policy_template=template),
    )

    result, publication = compiler.execute(request)

    assert publication.wrote and not result.issue_codes
    assert result.plan is not None
    market_request = result.plan.issuer_market_policy
    assert market_request is not None
    identity = prepared.filings[0].identity
    original = value.service.read_validation(
        prepared.filings[0].validation.artifact_id
    ).request
    assert market_request.source_revision == request.runtime_source_revision
    assert market_request.classification_request.issuer_id == identity.issuer_id
    assert market_request.classification_request.accession_number == (
        original.filing.accession_number
    )
    assert market_request.classification_request.report_period_end == (
        original.filing.report_period_end
    )
    assert market_request.classification_request.valuation_at == (
        original.valuation_timestamp
    )
    assert market_request.country_policy == template.country_policy
    assert market_request.industry_policy == template.industry_policy
    assert market_request.reference_policy == template.reference_policy
    assert market_request.market_policy.currency == identity.currency
    assert market_request.market_policy.policy_version == template.market_policy_version
    assert market_request.market_policy.terminal_growth_plan.policy_id == (
        template.terminal_growth_policy_id
    )
    assert market_request.market_policy.terminal_growth_plan.issuer_id == (
        identity.issuer_id
    )
    assert market_request.market_policy.terminal_growth_plan.valuation_at == (
        original.valuation_timestamp
    )
    assert len(result.plan.public_sources) == 7
    assert len(result.plan.source_admissions) == 7
    assert result.plan.source_admissions == tuple(
        sorted(result.plan.source_admissions, key=lambda item: item.digest)
    )
    treasury = next(
        item for item in result.plan.public_sources if item.source_id == TREASURY_SOURCE
    )
    assert "field_tdr_date_value=2026" in treasury.uri
    assert all(
        item.valuation_timestamp == original.valuation_timestamp
        for item in result.plan.public_sources
    )
    capital_admissions = tuple(
        item
        for item in result.plan.source_admissions
        if item.metric_id.startswith("industry.")
    )
    assert len({item.source_request_digests for item in capital_admissions}) == 1
    assert all(
        item.policy_digest == template.source_plan_template.source_use_policy_digest
        and item.policy_version
        == template.source_plan_template.source_use_policy_version
        and item.valuation_at == original.valuation_timestamp
        for item in result.plan.source_admissions
    )
    assert not compiler.execute(request)[1].wrote


@pytest.mark.parametrize(
    "failure,expected_codes",
    (
        (None, ()),
        ("missing", ("SOURCE_ADMISSION_CAPTURE_FAILED", "SOURCE_HTTP_NOT_FOUND")),
        ("terms", ("SOURCE_USE_TERMS_CHANGED",)),
        ("future", ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)),
    ),
)
def test_compiled_requests_execute_existing_source_owners_and_repeat_without_writes(
    tmp_path, monkeypatch, failure, expected_codes
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    original = value.service.read_validation(prepared.filings[0].validation.artifact_id)
    at = original.request.valuation_timestamp
    public = admission_fixture(tmp_path / "public", at=at)
    source, terms = _source(), _terms()
    template = AutomaticIssuerMarketPolicyTemplateV1.model_validate(
        {
            **issuer_market_policy_template().model_dump(),
            "source_plan_template": AutomaticMarketSourcesTemplateV1(
                source_use_policy_version=public.policy.policy_version,
                source_use_policy_digest=public.policy.digest,
                market_sources=(
                    AutomaticMarketSourceTemplateV1(
                        kind="reference",
                        provider_id="damodaran-public-aggregates",
                        metric_id=METRIC,
                        sources=(
                            _public_request(
                                source.source_id,
                                source.uri,
                                source.source_version,
                                source.terms_reference,
                            ),
                        ),
                        terms=(
                            _public_request(
                                terms.source_id,
                                terms.uri,
                                terms.source_version,
                                terms.terms_reference,
                            ),
                        ),
                    ),
                ),
            ),
        }
    )
    if failure == "missing":
        public.capture.errors[source.uri] = SnapshotError(
            "SOURCE_HTTP_NOT_FOUND", "selected source is missing"
        )
    elif failure == "terms":
        public.capture.sources[terms.uri] = replace(
            public.capture.sources[terms.uri], content=b"changed terms"
        )
    elif failure == "future":
        public.capture.sources[source.uri] = replace(
            public.capture.sources[source.uri],
            captured_at=at + timedelta(seconds=1),
            available_at=at + timedelta(seconds=1),
        )
    compiler, request = compiler_case(
        value, prepared, configuration(issuer_market_policy_template=template)
    )
    compiled, _ = compiler.execute(request)
    assert compiled.plan is not None
    plan = compiled.plan
    captures = tuple(
        public.acquisition.read(public.acquisition.execute(item).artifact.artifact_id)
        for item in plan.public_sources
    )
    decision, receipt = public.service.execute(plan.source_admissions[0], captures)
    assert receipt.wrote and decision.issue_codes == expected_codes
    if failure is None:
        assert decision.admission.status == "admitted"
    else:
        assert decision.admission is None or decision.admission.status == "refused"
    assert set(plan.source_admissions[0].source_request_digests) == {
        item.request.digest for item in captures if item.request.uri == source.uri
    }
    before = _inventory(tmp_path)
    calls = len(public.capture.calls)
    compiled_again, compiled_receipt = compiler.execute(request)
    assert not compiled_receipt.wrote and compiled_again.digest == compiled.digest
    repeated_captures = tuple(
        public.acquisition.read(public.acquisition.execute(item).artifact.artifact_id)
        for item in plan.public_sources
    )
    repeated, repeated_receipt = public.service.execute(
        plan.source_admissions[0], repeated_captures
    )
    assert not repeated_receipt.wrote and repeated == decision
    assert sha256_digest(repeated) == sha256_digest(decision)
    assert len(public.capture.calls) == calls and _inventory(tmp_path) == before


@pytest.mark.parametrize("stage", ["configuration", "plan", "evidence"])
def test_interrupted_publication_resumes_without_rewriting_completed_artifacts(
    tmp_path, monkeypatch, stage
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(value, prepared)
    delegate = value.artifacts.put_with_receipt
    prefix = {
        "configuration": "source-plan-configuration:",
        "plan": "source-preparation-plan:",
        "evidence": "original-source-plan:",
    }[stage]
    interrupted = False

    def put(artifact_id, *args, **kwargs):
        nonlocal interrupted
        if artifact_id.startswith(prefix) and not interrupted:
            interrupted = True
            raise OSError("simulated interruption")
        return delegate(artifact_id, *args, **kwargs)

    monkeypatch.setattr(value.artifacts, "put_with_receipt", put)
    with pytest.raises(OSError):
        compiler.execute(request)
    before = _inventory(tmp_path)
    calls = value.state.provider_calls, value.state.parser_calls
    result, publication = compiler.execute(request)
    assert publication.wrote and result.plan
    after = _inventory(tmp_path)
    for path, (payload, mtime) in before.items():
        if path.endswith(".artifact-records.jsonl"):
            assert after[path][0].startswith(payload)
        else:
            assert after[path] == (payload, mtime)
    assert calls == (value.state.provider_calls, value.state.parser_calls)
    assert not compiler.execute(request)[1].wrote


def test_missing_original_blocks_instead_of_using_only_successful_original(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch, multiple_originals=True)
    delegate = value.acquisition.adapter._request

    def capture(uri, *, deadline_at=None):
        if "/000000000126999999/" in uri:
            raise SecSourceError("SEC_HTTP_NOT_FOUND", "missing selected original")
        return delegate(uri, deadline_at=deadline_at)

    monkeypatch.setattr(value.acquisition.adapter, "_request", capture)
    prepared, _ = execute(value)
    assert len(prepared.filings) == 2
    compiler, request = compiler_case(value, prepared)
    result, _ = compiler.execute(request)
    assert result.plan is result.plan_ref is None
    assert "SEC_HTTP_NOT_FOUND" in result.issue_codes
    assert "ORIGINAL_SOURCE_PLAN_IDENTITY_MISSING" in result.issue_codes
    assert "ORIGINAL_HISTORY_IDENTITY_CONFLICT" not in result.issue_codes
    assert value.service.read(request.original_preparation.artifact_id) == prepared
    assert value.metadata.snapshots == value.metadata.mappings == {}
    before = _inventory(tmp_path)
    assert not compiler.execute(request)[1].wrote
    assert _inventory(tmp_path) == before


def test_retryable_original_attempt_does_not_reserve_a_successful_plan_identity(
    tmp_path, monkeypatch
):
    from fundamental_service import ingestion

    value = case(tmp_path, monkeypatch)
    delegate = ingestion.parse_filing_offline
    exhausted = True

    def parse(*args, **kwargs):
        nonlocal exhausted
        if exhausted:
            exhausted = False
            raise ArelleParserError("PARSER_RESOURCE_EXHAUSTED", "temporary failure")
        return delegate(*args, **kwargs)

    monkeypatch.setattr(ingestion, "parse_filing_offline", parse)
    attempt, _ = execute(value)
    compiler, request = compiler_case(value, attempt)
    refused, publication = compiler.execute(request)
    assert publication.wrote and refused.retryable and refused.plan is None
    assert refused.artifact_id.startswith("original-source-plan-attempt:")
    assert "PARSER_RESOURCE_EXHAUSTED" in refused.issue_codes
    before = _inventory(tmp_path)
    assert not compiler.execute(request)[1].wrote
    assert _inventory(tmp_path) == before

    prepared, _ = execute(value)
    compiler, successful_request = compiler_case(value, prepared)
    success, publication = compiler.execute(successful_request)
    assert publication.wrote and success.plan and not success.retryable
    assert successful_request.digest != request.digest
    assert compiler.read(refused.artifact_id) == refused
    assert not compiler.execute(successful_request)[1].wrote


def test_identity_refusal_is_retained_and_new_configuration_has_new_identity(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value, value.request.model_copy(update={"ticker": "OTHER"}))
    compiler, request = compiler_case(value, prepared)
    result, _ = compiler.execute(request)
    assert result.plan is None and "HISTORICAL_IDENTITY_MISMATCH" in result.issue_codes
    changed = request.model_copy(
        update={
            "configuration": request.configuration.model_copy(
                update={"mapping_version": "next-version"}
            )
        }
    )
    again, publication = compiler.execute(changed)
    assert publication.wrote and again.artifact_id != result.artifact_id
    assert again.issue_codes == result.issue_codes


@pytest.mark.parametrize(
    "target", ["evidence", "request", "configuration", "plan", "original"]
)
def test_corrupt_dependency_refuses_without_repair_io(tmp_path, monkeypatch, target):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    compiler, request = compiler_case(value, prepared)
    result, _ = compiler.execute(request)
    artifact_id = {
        "evidence": result.artifact_id,
        "request": f"original-source-plan-request:{request.digest}",
        "configuration": f"source-plan-configuration:{request.configuration.digest}",
        "plan": result.plan_ref.artifact_id,
        "original": prepared.artifact_id,
    }[target]
    delegate = value.artifacts.read
    monkeypatch.setattr(
        value.artifacts,
        "read",
        lambda key: b"{}" if key == artifact_id else delegate(key),
    )
    calls = value.state.provider_calls, value.state.parser_calls
    with pytest.raises(SnapshotError):
        compiler.execute(request)
    assert calls == (value.state.provider_calls, value.state.parser_calls)


def test_compiled_plan_runs_existing_automatic_preparation_and_retains_missing_roles(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    # Match the fixture's configured trust identity; compilation itself grants none.
    source = value.acquisition.automatic_mapping_authority
    config = configuration().model_copy(
        update={
            "evaluator_id": next(iter(source.trust_roots.automatic_mapping_evaluators))
        }
    )
    compiler, request = compiler_case(value, prepared, config)
    result, _ = compiler.execute(request)

    def missing(_):
        raise ServiceError(
            "SNAPSHOT_NOT_FOUND", "empty store", status_code=404, retryable=False
        )

    def forbidden(*args, **kwargs):
        pytest.fail("incomplete real inputs must not release, compose or calculate")

    runner = SourcePreparationRunner(
        application=SimpleNamespace(
            resolve_snapshot=missing,
            artifact_store=value.artifacts,
            snapshot=value.metadata.snapshots.__getitem__,
            prepare_valuation=forbidden,
            calculate_valuation=forbidden,
        ),
        metadata=value.metadata,
        acquisition=value.acquisition,
        artifacts=value.artifacts,
        canary=SimpleNamespace(validate=forbidden),
    )
    publication = run(runner, result.plan)
    evidence = SourcePreparationEvidenceV1.model_validate_json(
        value.artifacts.read(publication.artifact.artifact_id)
    )
    assert evidence.status == "blocked"
    assert evidence.source_outcomes[0].mapping_evidence_ref
    assert evidence.source_plan_ref == result.plan_ref
    assert value.metadata.mappings
    before = _inventory(tmp_path)
    assert not run(runner, result.plan).wrote
    assert _inventory(tmp_path) == before


def test_cli_compiles_and_retrieves_saved_plan_and_checks_configuration_before_storage(
    tmp_path, monkeypatch, capsys
):
    from fundamental_service import annual_discovery_runner, app

    value = case(tmp_path, monkeypatch)

    @asynccontextmanager
    async def lifespan(_):
        yield

    monkeypatch.setattr(
        app,
        "app",
        SimpleNamespace(
            router=SimpleNamespace(lifespan_context=lifespan),
            state=SimpleNamespace(
                application=SimpleNamespace(
                    ready=True,
                    content_store=value.acquisition.content_store,
                    artifact_store=value.artifacts,
                ),
                sec_acquisition=value.acquisition,
                metadata_store=value.metadata,
            ),
        ),
    )
    monkeypatch.setattr(
        annual_discovery_runner, "PostgresPublicCaptureLock", lambda _: value.locks
    )
    config = configuration()
    config_path = tmp_path / "configuration.json"
    config_path.write_bytes(canonical_bytes(config))
    args = [
        "--cik",
        value.annual_request.cik,
        "--valuation-timestamp",
        value.annual_request.valuation_timestamp.isoformat(),
        "--source-revision",
        value.annual_request.declared_source_revision,
        "--original-count",
        "1",
        "--prepare-originals",
        "--source-plan-configuration",
        str(config_path),
        "--configuration-digest",
        config.digest,
    ]
    assert annual_discovery_runner.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["wrote"] and first["plan_ref"]
    assert (
        first["evidence"]["plan"]["ingestions"][0]["identity"]["security_id"]
        == value.expected_identity.security_id
    )
    before = _inventory(tmp_path)
    assert annual_discovery_runner.main(args) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated == {
        **first,
        "wrote": False,
        "lineage": {
            stage: {**value, "wrote": False}
            for stage, value in first["lineage"].items()
        },
    }
    assert (
        annual_discovery_runner.main(
            ["--artifact-id", first["artifact"]["artifact_id"]]
        )
        == 0
    )
    retrieved = json.loads(capsys.readouterr().out)
    assert all(
        retrieved[field] == repeated[field]
        for field in ("input_digest", "output_digest", "evidence", "plan_ref")
    )
    assert retrieved["wrote"] is False
    assert _inventory(tmp_path) == before

    source_preparation_id = first["evidence"]["request"]["original_preparation"][
        "artifact_id"
    ]
    installed_revision = "e" * 40
    monkeypatch.setattr(
        value.acquisition.adapter,
        "_request",
        lambda *args, **kwargs: pytest.fail("saved plan compilation used SEC I/O"),
    )
    saved_plan_args = [
        "--artifact-id",
        source_preparation_id,
        "--source-revision",
        installed_revision,
        "--source-plan-configuration",
        str(config_path),
        "--configuration-digest",
        config.digest,
    ]
    assert annual_discovery_runner.main(saved_plan_args) == 0
    compiled_saved = json.loads(capsys.readouterr().out)
    assert compiled_saved["wrote"] and compiled_saved["plan_ref"]
    assert compiled_saved["evidence"]["plan"]["source_revision"] == installed_revision
    after_first_saved_compile = _inventory(tmp_path)
    assert annual_discovery_runner.main(saved_plan_args) == 0
    repeated_saved = json.loads(capsys.readouterr().out)
    assert repeated_saved == {
        **compiled_saved,
        "wrote": False,
        "lineage": {
            stage: {**value, "wrote": False}
            for stage, value in compiled_saved["lineage"].items()
        },
    }
    assert _inventory(tmp_path) == after_first_saved_compile

    def forbidden(_):
        pytest.fail("invalid configuration opened service storage")

    monkeypatch.setattr(annual_discovery_runner, "_run_command", forbidden)
    assert annual_discovery_runner.main(args[:-1] + ["0" * 64]) == 2
    assert "ANNUAL_DISCOVERY_INPUT_INVALID" in capsys.readouterr().err
