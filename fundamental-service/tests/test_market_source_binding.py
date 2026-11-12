from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Context, Decimal, Inexact, localcontext
import hashlib
import json

import pytest

from fundamental_service.application.service import ServiceError
from fundamental_service.application.service import _approved_market_policy
from fundamental_service.contracts import (
    MarketPolicyInputsV1,
    ValuationEvidenceReadRequestV1,
)
from fundamental_service.market_source_selection import (
    DailyMarketRatePolicyV1,
    MarketSourceError,
    select_market_rate,
    verify_observed_market_inputs,
    USD_RISK_FREE_POLICY,
)
from fundamental_service.macro_series import MacroObservationV1, MacroSeriesVintageV1
from fundamental_service.policies import (
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import admit_macro_source
from fundamental_service.source_evidence import SourceArtifactV1
from market_policy_fixtures import synthetic_market_inputs
from test_preparation_runner import _fixture, _reader, _run, _runner
from test_source_admission import CAPTURE, JsonRateProvider, _macro_inputs
from test_source_admission_evidence import _packet


class DatedJsonRateProvider:
    provider_id = JsonRateProvider.provider_id

    def supports(self, series_id):
        return series_id == "us.treasury_par_yield_10y"

    def reproduce_vintage(self, *, series_id, sources):
        source = next(x for x in sources if x.source_id == "synthetic-rate")
        metadata = next(x for x in sources if x.source_id == "synthetic-rate-metadata")
        declaration = json.loads(metadata.content)
        return MacroSeriesVintageV1.build(
            series_id=series_id,
            provider_id=self.provider_id,
            frequency=declaration.get("frequency", "daily"),
            unit=declaration["unit"],
            source_version="synthetic-json-v1",
            available_at=datetime.fromisoformat(declaration["available_at"]),
            captured_at=max(x.captured_at for x in sources),
            artifacts=tuple(
                SourceArtifactV1(
                    source_id=x.source_id,
                    uri=x.uri,
                    source_version=x.source_version,
                    terms_reference=x.terms_reference,
                    captured_at=x.captured_at,
                    content_sha256=hashlib.sha256(x.content).hexdigest(),
                )
                for x in sources
            ),
            observations=tuple(
                MacroObservationV1(
                    series_id=series_id,
                    period_start=date.fromisoformat(row["start"]),
                    period_end=date.fromisoformat(row["end"]),
                    value=Decimal(row["value"]),
                    unit=declaration["unit"],
                    source_sha256=hashlib.sha256(source.content).hexdigest(),
                )
                for row in json.loads(source.content)
            ),
        )


def _dated_inputs(*, at=CAPTURE, observations=None, **metadata):
    inputs = _macro_inputs()
    day = (at - timedelta(days=1)).date().isoformat()
    data = canonical_bytes(
        observations or [{"start": day, "end": day, "value": "4.25"}]
    )
    declaration = canonical_bytes(
        {"unit": "percent", "available_at": at.isoformat(), **metadata}
    )
    inputs.update(
        valuation_at=at,
        sources=tuple(
            replace(
                x,
                captured_at=at,
                content=data if x.source_id == "synthetic-rate" else declaration,
            )
            for x in inputs["sources"]
        ),
    )
    return inputs


def _dated_admission(**kwargs):
    return admit_macro_source(DatedJsonRateProvider(), **_dated_inputs(**kwargs))


def _select(admissions, **kwargs):
    return select_market_rate(
        admissions,
        policy=USD_RISK_FREE_POLICY,
        valuation_at=CAPTURE,
        currency="USD",
        **kwargs,
    )


def _observed_registry(registry):
    policy = registry.policy("fcff_dcf-us-gaap-public-v3")
    payload = policy.model_dump(exclude={"policy_digest"})
    market = payload["market_inputs"]
    market["evidence"][0]["method"] = "observed_source"
    return PolicyRegistry(
        initial_model_specs(),
        (PolicyRecordV1(**payload, policy_digest=sha256_digest(payload)),),
    )


def _admitted_rate():
    inputs = _macro_inputs()
    return admit_macro_source(JsonRateProvider(), **inputs)


def _observed_market_inputs(admission, *, value=Decimal("0.0425")):
    vintage = admission.vintage
    observation = vintage.observations[0]
    original = next(
        item
        for item in vintage.artifacts
        if item.content_sha256 == observation.source_sha256
    )
    payload = synthetic_market_inputs().model_dump(mode="python")
    evidence = next(x for x in payload["evidence"] if x["role"] == "risk_free_rate")
    evidence.update(
        method="observed_source",
        value=value,
        source_id=original.source_id,
        source_uri=original.uri,
        content_hash=original.content_sha256,
        source_version=original.source_version,
        terms_reference=original.terms_reference,
        as_of=datetime.combine(observation.period_end, datetime.min.time(), UTC),
        available_at=vintage.available_at,
        captured_at=vintage.captured_at,
        rationale="Synthetic source reproduced through the provider contract",
    )
    payload["risk_free_rate"] = value
    return MarketPolicyInputsV1.model_validate(payload)


def test_serving_refuses_observed_rate_without_release_source_admission(tmp_path):
    fixture = _fixture(tmp_path)
    application = replace(
        fixture.application,
        policy_registry=_observed_registry(fixture.application.policy_registry),
    )
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=fixture.manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    with pytest.raises(ServiceError) as error:
        application.prepare_valuation(request)
    assert error.value.code == "MARKET_RATE_SOURCE_UNAVAILABLE"


def test_runner_retains_market_source_refusal_and_reuses_the_failure_artifact(tmp_path):
    fixture = _fixture(tmp_path)
    fixture.application = replace(
        fixture.application,
        policy_registry=_observed_registry(fixture.application.policy_registry),
    )
    first = _run(_runner(fixture), fixture.plan)
    inventory = {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    second = _run(_runner(fixture), fixture.plan, correlation="repeat")
    evidence = _reader(fixture, first)
    assert evidence.status == "blocked"
    assert evidence.issue_codes == ("MARKET_RATE_SOURCE_UNAVAILABLE",)
    assert evidence.snapshot_id == fixture.snapshot.snapshot_id
    assert evidence.data_release_manifest_digest == fixture.manifest.manifest_digest
    assert evidence.preparation is None
    assert second.artifact == first.artifact
    assert not second.wrote
    assert inventory == {
        path: (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    "status_code,retryable", [(503, True), (422, True), (403, False)]
)
def test_runner_preserves_transient_and_authorization_errors(
    tmp_path, status_code, retryable
):
    fixture = _fixture(tmp_path)
    application = fixture.application

    class UnavailablePreparation:
        def __getattr__(self, name):
            return getattr(application, name)

        def prepare_valuation(self, request):
            raise ServiceError(
                "TEST_UNAVAILABLE", "test", status_code=status_code, retryable=retryable
            )

    fixture.application = UnavailablePreparation()
    with pytest.raises(ServiceError) as error:
        _run(_runner(fixture), fixture.plan)
    assert error.value.code == "TEST_UNAVAILABLE"


def test_alternative_macro_provider_observation_binds_the_market_policy_value():
    admission = _admitted_rate()
    policy = _observed_market_inputs(admission)
    selection_policy = DailyMarketRatePolicyV1(
        policy_version="test-rate-v1",
        series_id="us.treasury_par_yield_10y",
        currency="USD",
        maximum_age_days=2,
    )
    selected = select_market_rate(
        (admission,),
        policy=selection_policy,
        valuation_at=CAPTURE,
        currency="USD",
    )
    assert selected.value == Decimal("0.0425")
    assert (
        selected.output_digest
        == select_market_rate(
            (admission,),
            policy=selection_policy,
            valuation_at=CAPTURE,
            currency="USD",
        ).output_digest
    )
    traces = verify_observed_market_inputs(
        policy, admissions=(admission,), valuation_at=CAPTURE, currency="USD"
    )
    assert traces["risk_free_rate"].source_ids == ("synthetic-rate",)
    assert (
        admission.vintage.observations[0].source_sha256
        in traces["risk_free_rate"].source_refs
    )


def test_observed_market_input_cannot_change_the_admitted_rate_value():
    admission = _admitted_rate()
    policy = _observed_market_inputs(admission, value=Decimal("0.05"))
    with pytest.raises(MarketSourceError) as error:
        verify_observed_market_inputs(
            policy, admissions=(admission,), valuation_at=CAPTURE, currency="USD"
        )
    assert error.value.code == "MARKET_POLICY_SOURCE_MISMATCH"


@pytest.mark.parametrize(
    "valuation_at,currency,maximum_age_days,code",
    [
        (
            datetime(2026, 11, 10, tzinfo=UTC),
            "USD",
            7,
            "MARKET_RATE_SOURCE_UNAVAILABLE",
        ),
        (CAPTURE, "EUR", 7, "MARKET_RATE_CURRENCY_UNSUPPORTED"),
        (CAPTURE, "USD", 0, "MARKET_RATE_SOURCE_STALE"),
    ],
)
def test_market_rate_selection_refuses_future_wrong_currency_and_stale_sources(
    valuation_at, currency, maximum_age_days, code
):
    with pytest.raises(MarketSourceError) as error:
        select_market_rate(
            (_admitted_rate(),),
            policy=DailyMarketRatePolicyV1(
                policy_version="test-rate-v1",
                series_id="us.treasury_par_yield_10y",
                currency="USD",
                maximum_age_days=maximum_age_days,
            ),
            valuation_at=valuation_at,
            currency=currency,
        )
    assert error.value.code == code


def test_selection_order_duplicate_inputs_concurrency_and_decimal_context_are_deterministic():
    current = _dated_admission()
    old = _dated_admission(at=CAPTURE - timedelta(days=1))
    first = _select((current, old))
    assert first == _select((old, current, current))
    assert first.output_digest == sha256_digest(
        {"input_digest": first.input_digest, "value": first.value, "trace": first.trace}
    )
    with localcontext(Context(prec=3, traps=[Inexact])):
        assert first == _select((current, old))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(x == first for x in pool.map(_select, [(old, current)] * 8))


def test_newer_vintage_and_latest_day_are_selected_without_falling_back_to_matching_policy():
    old = _dated_admission(at=CAPTURE - timedelta(days=1))
    current = _dated_admission(
        observations=[
            {"start": "2026-11-10", "end": "2026-11-10", "value": "4.25"},
            {"start": "2026-11-11", "end": "2026-11-11", "value": "4.38"},
        ]
    )
    assert _select((old, current)).value == Decimal("0.0438")
    with pytest.raises(MarketSourceError) as error:
        verify_observed_market_inputs(
            _observed_market_inputs(old),
            admissions=(old, current),
            valuation_at=CAPTURE,
            currency="USD",
        )
    assert error.value.code == "MARKET_POLICY_SOURCE_MISMATCH"


@pytest.mark.parametrize(
    "change,code",
    [
        ("units", "MARKET_RATE_BASIS_UNSUPPORTED"),
        ("frequency", "MARKET_RATE_BASIS_UNSUPPORTED"),
        ("period", "MARKET_RATE_BASIS_UNSUPPORTED"),
        ("ambiguous_day", "MARKET_RATE_OBSERVATION_AMBIGUOUS"),
        ("ambiguous_vintage", "MARKET_RATE_SOURCE_AMBIGUOUS"),
        ("purpose", "MARKET_RATE_SOURCE_UNAVAILABLE"),
        ("refused", "MARKET_RATE_SOURCE_UNAVAILABLE"),
    ],
)
def test_rate_selection_preserves_ineligible_and_conflicting_evidence(change, code):
    inputs = _dated_inputs()
    provider = DatedJsonRateProvider()
    if change in {"units", "frequency"}:
        inputs = _dated_inputs(
            **({"unit": "fraction"} if change == "units" else {"frequency": "monthly"})
        )
    elif change in {"period", "ambiguous_day"}:
        rows = [{"start": "2026-11-10", "end": "2026-11-11", "value": "4.25"}]
        if change == "ambiguous_day":
            rows.append({"start": "2026-11-11", "end": "2026-11-11", "value": "4.38"})
        inputs = _dated_inputs(observations=rows)
    elif change in {"purpose", "refused"}:
        inputs["intended_use"] = "derived_valuation_display"
        if change == "purpose":
            inputs["policy"] = inputs["policy"].model_copy(
                update={
                    "rules": tuple(
                        rule.model_copy(
                            update={"permitted_uses": ("derived_valuation_display",)}
                        )
                        for rule in inputs["policy"].rules
                    )
                }
            )
    admission = admit_macro_source(provider, **inputs)
    admissions = (admission,)
    if change == "ambiguous_vintage":
        admissions += (
            _dated_admission(
                observations=[
                    {"start": "2026-11-11", "end": "2026-11-11", "value": "4.38"}
                ]
            ),
        )
    before = canonical_bytes(admissions)
    for _ in range(2):
        with pytest.raises(MarketSourceError) as error:
            _select(admissions)
        assert error.value.code == code
    assert canonical_bytes(admissions) == before


@pytest.mark.parametrize(
    "field",
    [
        "value",
        "source_id",
        "source_uri",
        "content_hash",
        "source_version",
        "terms_reference",
        "as_of",
        "available_at",
        "captured_at",
    ],
)
def test_every_declared_source_field_and_value_must_match_the_admitted_selection(field):
    admission = _dated_admission()
    payload = _observed_market_inputs(admission).model_dump(mode="python")
    evidence = payload["evidence"][0]
    if field == "value":
        payload["risk_free_rate"] = evidence[field] = Decimal("0.05")
    elif field in {"as_of", "available_at"}:
        evidence[field] -= timedelta(hours=1)
    elif field == "captured_at":
        evidence[field] += timedelta(hours=1)
    elif field == "content_hash":
        evidence[field] = "0" * 64
    else:
        evidence[field] = "changed-" + evidence[field]
    with pytest.raises(MarketSourceError) as error:
        verify_observed_market_inputs(
            MarketPolicyInputsV1.model_validate(payload),
            admissions=(admission,),
            valuation_at=CAPTURE,
            currency="USD",
        )
    assert error.value.code == "MARKET_POLICY_SOURCE_MISMATCH"


def test_naive_valuation_and_missing_context_have_typed_refusals():
    with pytest.raises(MarketSourceError) as error:
        select_market_rate(
            (),
            policy=USD_RISK_FREE_POLICY,
            valuation_at=datetime(2026, 11, 12),
            currency="USD",
        )
    assert error.value.code == "MARKET_RATE_TIMESTAMP_INVALID"
    from market_policy_fixtures import synthetic_policy_registry

    registry = _observed_registry(synthetic_policy_registry())
    with pytest.raises(MarketSourceError) as error:
        _approved_market_policy(registry.policy("fcff_dcf-us-gaap-public-v3"))
    assert error.value.code == "MARKET_RATE_CONTEXT_MISSING"


def test_unconfigured_observed_roles_cannot_reuse_a_risk_free_admission():
    admission = _dated_admission()
    payload = _observed_market_inputs(admission).model_dump(mode="python")
    next(x for x in payload["evidence"] if x["role"] == "beta")["method"] = (
        "observed_source"
    )
    with pytest.raises(MarketSourceError) as error:
        verify_observed_market_inputs(
            MarketPolicyInputsV1.model_validate(payload),
            admissions=(admission,),
            valuation_at=CAPTURE,
            currency="USD",
        )
    assert error.value.code == "MARKET_OBSERVED_ROLE_UNSUPPORTED"


def _source_bound_application(tmp_path):
    fixture = _fixture(tmp_path)
    inputs = _dated_inputs(at=fixture.snapshot.valuation_timestamp)
    admission = admit_macro_source(DatedJsonRateProvider(), **inputs)
    manifest, sources, _, _ = _packet(fixture.manifest, inputs=inputs, result=admission)
    previous = fixture.artifacts.read

    class CombinedArtifacts:
        def read(self, name):
            return sources.data[name] if name in sources.data else previous(name)

    fixture.metadata.get_data_release_manifest = (
        lambda digest: manifest if digest == manifest.manifest_digest else None
    )
    record = fixture.application.policy_registry.policy("fcff_dcf-us-gaap-public-v3")
    payload = record.model_dump(exclude={"policy_digest"})
    payload["market_inputs"] = _observed_market_inputs(admission)
    policy = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    application = replace(
        fixture.application,
        artifact_store=CombinedArtifacts(),
        policy_registry=PolicyRegistry(initial_model_specs(), (policy,)),
        macro_providers=(DatedJsonRateProvider(),),
        source_use_policy=inputs["policy"],
    )
    request = ValuationEvidenceReadRequestV1(
        contract_version="fundamental.v1",
        snapshot_id=fixture.snapshot.snapshot_id,
        data_release_manifest_digest=manifest.manifest_digest,
        model_id="fcff_dcf",
    )
    return application, request, admission, policy


def test_serving_reproduces_source_and_binds_selected_value_before_formal_composer(
    tmp_path,
):
    application, request, admission, _ = _source_bound_application(tmp_path)
    first = application.prepare_valuation(request)
    repeat = application.prepare_valuation(request)
    assert first.status == "prepared"
    assert first.input.assumptions.wacc.risk_free_rate == Decimal("0.0425")
    assert first.preparation_digest == repeat.preparation_digest
    evidence = next(
        item
        for item in first.assumptions_evidence
        if item.path == "assumptions.wacc.risk_free_rate"
    )
    assert evidence.method == "approved_source"
    assert admission.output_digest in evidence.source_refs
    assert admission.vintage.content_digest in evidence.source_refs


def test_serving_cannot_use_rehashed_policy_to_change_a_source_bound_value(tmp_path):
    application, request, _, record = _source_bound_application(tmp_path)
    payload = record.model_dump(exclude={"policy_digest"})
    payload["market_inputs"]["risk_free_rate"] = Decimal("0.05")
    payload["market_inputs"]["evidence"][0]["value"] = Decimal("0.05")
    altered = PolicyRecordV1(**payload, policy_digest=sha256_digest(payload))
    application = replace(
        application, policy_registry=PolicyRegistry(initial_model_specs(), (altered,))
    )
    for _ in range(2):
        with pytest.raises(ServiceError) as error:
            application.prepare_valuation(request)
        assert error.value.code == "MARKET_POLICY_SOURCE_MISMATCH"
