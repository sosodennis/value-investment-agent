"""Public numeric results must not depend on a caller or worker's context."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    Inexact,
    Rounded,
    localcontext,
)

import pytest
from fundamental_service.annual_history import resolve_annual_history
from fundamental_service.calculator import CalculationRefusal, calculate
from fundamental_service.contracts import UncertaintyV1, WaccAssumptionsV1
from fundamental_service.serialization import canonical_bytes
from fundamental_service.testsupport import make_valuation
from fundamental_service.uncertainty import MonteCarloRequestV1, run_uncertainty
from fundamental_service.uncertainty_policy import build_default_uncertainty
from fundamental_service.valuation_preparation import (
    ManualProvenanceV1,
    apply_manual_override,
    derive_historical_metrics,
)
from fundamental_service.valuation_requirements import valuation_requirements_profile
from fundamental_service.verification import (
    compare_artifact,
    independent_calculate,
    invariant_findings,
    mutation_findings,
    property_findings,
)
from test_postgres_metadata import _snapshot
from test_valuation_preparation import (
    VALUATION_TIME,
    _fact,
    _facts,
    _market_policy,
    _prepare,
)


def _state(context):
    return (
        context.prec,
        context.rounding,
        context.Emin,
        context.Emax,
        context.capitals,
        context.clamp,
        dict(context.traps),
        dict(context.flags),
    )


@pytest.fixture(params=("low", "default", "trapping"))
def caller_context(request):
    if request.param == "low":
        context = Context(prec=16, rounding=ROUND_DOWN)
    elif request.param == "trapping":
        context = Context(prec=7, rounding=ROUND_DOWN, Emin=-2, Emax=2, clamp=1)
        context.traps[Inexact] = True
        context.traps[Rounded] = True
    else:
        context = Context(prec=28, rounding=ROUND_HALF_EVEN)
    context.flags[Inexact] = True
    return context


def test_calculation_preserves_released_bytes_and_caller_context(caller_context):
    request = make_valuation().with_digest()
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        expected = calculate(request)
    assert expected.result_hash == (
        "113911627cf76c090aeffe0a4c3731cb915def7391ae768493343906dc7a38a1"
    )
    with localcontext(caller_context) as context:
        before = _state(context)
        actual = calculate(request)
        assert _state(context) == before
    assert canonical_bytes(actual) == canonical_bytes(expected)


def test_fresh_worker_threads_reproduce_the_released_result():
    request = make_valuation().with_digest()
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        expected = canonical_bytes(calculate(request))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(lambda _: canonical_bytes(calculate(request)), range(4))
        )
    assert results == (expected,) * 4


def test_refusal_restores_context_and_error_classification(caller_context):
    request = make_valuation().model_copy(update={"input_digest": "0" * 64})
    with localcontext(caller_context) as context:
        before = _state(context)
        with pytest.raises(CalculationRefusal) as error:
            calculate(request)
        assert error.value.code == "INPUT_DIGEST_MISMATCH"
        assert _state(context) == before


@pytest.mark.parametrize("model_id", ("fcff_dcf", "transition_fcff_dcf"))
def test_preparation_and_override_are_context_independent(caller_context, model_id):
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        facts = _facts()
        if model_id == "transition_fcff_dcf":
            facts = (
                *facts,
                _fact("filed_operating_evidence", 2025, "1").model_copy(
                    update={"value": "filed evidence"}
                ),
            )
        market = _market_policy()
        expected = _prepare(facts, market_policy=market, model_id=model_id)
        assert expected.input is not None
        provenance = ManualProvenanceV1(
            author="test-caller",
            modified_at=datetime(2026, 3, 2, tzinfo=UTC),
            reason="test normalization",
            automatic_preparation_digest=expected.preparation_digest,
        )
        override_arguments = dict(
            path="assumptions.forecast.operating_margin[0]",
            value=Decimal("0.241234567890123456789"),
            provenance=provenance,
        )
        expected_override = apply_manual_override(expected, **override_arguments)
    with localcontext(caller_context) as context:
        before = _state(context)
        actual = _prepare(facts, market_policy=market, model_id=model_id)
        assert canonical_bytes(actual) == canonical_bytes(expected)
        actual_override = apply_manual_override(expected, **override_arguments)
        assert canonical_bytes(actual_override) == canonical_bytes(expected_override)
        assert _state(context) == before


def test_historical_metrics_and_uncertainty_policy_own_their_context(caller_context):
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        preparation = _prepare(_facts(), market_policy=_market_policy())
        assert preparation.input is not None
        history = resolve_annual_history(
            _facts(),
            snapshot=_snapshot("context-metrics", identity=preparation.input.identity),
            valuation_timestamp=VALUATION_TIME,
            profile=valuation_requirements_profile("fcff_dcf"),
        )
        metrics = derive_historical_metrics(history)
        assert len(history.periods) == 5
        assert {metric.metric_id for metric in metrics.metrics} >= {
            "revenue_growth",
            "operating_margin",
            "reinvestment_rate",
        }
        controls = build_default_uncertainty(
            preparation.input, historical_metrics=metrics.metrics
        )
    with localcontext(caller_context) as context:
        before = _state(context)
        assert canonical_bytes(derive_historical_metrics(history)) == canonical_bytes(
            metrics
        )
        assert canonical_bytes(
            build_default_uncertainty(
                preparation.input, historical_metrics=metrics.metrics
            )
        ) == canonical_bytes(controls)
        assert _state(context) == before


def test_monte_carlo_results_and_invalid_draws_ignore_ambient_context(caller_context):
    request = make_valuation().with_digest()
    controls = MonteCarloRequestV1(
        uncertainty=UncertaintyV1(
            mode="monte_carlo",
            samples=24,
            seed=42,
            invalid_draw_policy="skip",
            parameters=(
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": Decimal("0.01"),
                    "upper": Decimal("0.20"),
                },
            ),
        )
    )
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        expected = run_uncertainty(request, monte_carlo=controls)
    assert expected.valid_samples > 0 and expected.invalid_samples > 0
    with localcontext(caller_context) as context:
        before = _state(context)
        actual = run_uncertainty(request, monte_carlo=controls)
        assert canonical_bytes(actual) == canonical_bytes(expected)
        assert _state(context) == before


def test_import_does_not_mutate_the_callers_decimal_context():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from decimal import getcontext, ROUND_DOWN; "
            "context=getcontext(); context.prec=17; context.rounding=ROUND_DOWN; "
            "before=str(context); import fundamental_service.calculator; "
            "assert str(context)==before, (before, str(context))",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_weight_validation_ignores_ambient_rounding_and_traps(caller_context):
    values = make_valuation().assumptions.wacc.model_dump()
    with localcontext(caller_context) as context:
        before = _state(context)
        assert WaccAssumptionsV1.model_validate(values).debt_weight == Decimal("0.2")
        with pytest.raises(ValueError, match="must sum"):
            WaccAssumptionsV1.model_validate(
                {**values, "equity_weight": Decimal("0.8000000000000000000000000001")}
            )
        assert _state(context) == before


def test_challenger_and_error_tolerances_ignore_caller_context(caller_context):
    request = make_valuation().with_digest()
    artifact = calculate(request)
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        expected = independent_calculate(request)
        expected_mutations = mutation_findings(request)
    with localcontext(caller_context) as context:
        before = _state(context)
        actual = independent_calculate(request)
        assert actual == expected
        assert compare_artifact(actual, artifact) == ()
        assert invariant_findings(request, actual) == ()
        assert property_findings(request) == ()
        assert mutation_findings(request) == expected_mutations
        assert _state(context) == before
