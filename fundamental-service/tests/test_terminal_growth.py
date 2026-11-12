from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, Inexact, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.market_source_selection import (
    MarketSourceError,
    USD_RISK_FREE_POLICY,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.source_admission import SourceUsePolicyV1, admit_macro_source
from fundamental_service.terminal_growth import (
    TerminalGrowthPlanV1,
    select_terminal_growth,
    terminal_growth_evidence,
)
from test_market_source_binding import DatedJsonRateProvider, _dated_inputs

AT = datetime(2026, 3, 1, tzinfo=UTC)


class AnnualAndDailyProvider(DatedJsonRateProvider):
    """A second GDP publisher uses the same source/selection contracts."""

    def supports(self, series_id):
        return series_id in {"us.nominal_gdp", "us.treasury_par_yield_10y"}


def _inputs(at=AT, *, increment="100", missing=None, gdp_at=None):
    rate = _dated_inputs(at=at)
    gdp = _dated_inputs(
        at=gdp_at or at,
        unit="USD millions",
        frequency="annual",
        observations=[
            {
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "value": str(Decimal(1000) + (year - 2015) * Decimal(increment)),
            }
            for year in range(2015, 2026)
            if year != missing
        ],
    )
    gdp["series_id"] = "us.nominal_gdp"
    gdp["valuation_at"] = at
    policy = SourceUsePolicyV1(
        policy_version="synthetic-two-macro-series-v1",
        rules=tuple(
            sorted(
                (
                    rule.model_copy(
                        update={
                            "rule_id": metric + ":" + rule.rule_id,
                            "metric_id": metric,
                            "population": metric,
                        }
                    )
                    for metric in ("us.nominal_gdp", "us.treasury_par_yield_10y")
                    for rule in rate["policy"].rules
                ),
                key=lambda rule: rule.rule_id,
            )
        ),
    )
    return {**rate, "policy": policy}, {**gdp, "policy": policy}


def _admissions(**kwargs):
    return tuple(
        admit_macro_source(AnnualAndDailyProvider(), **inputs)
        for inputs in _inputs(**kwargs)
    )


def _plan(**updates):
    return TerminalGrowthPlanV1(
        **{
            "issuer_id": "0000909724",
            "policy_id": "fcff_dcf-us-gaap-public-v3",
            "valuation_at": AT,
            "gdp_horizon_years": 10,
            "maximum_gdp_period_age_days": 500,
            "risk_free_policy": USD_RISK_FREE_POLICY,
            **updates,
        }
    )


@pytest.mark.parametrize("increment,binding", [("100", "rate"), ("5", "gdp")])
def test_source_neutral_terminal_assumption_uses_the_binding_ceiling(
    increment, binding
):
    admissions = _admissions(increment=increment)
    result = select_terminal_growth(_plan(), admissions=admissions)
    assert result.value == (
        Decimal("0.0425") if binding == "rate" else result.gdp_ceiling.nominal_gdp_cagr
    )
    assert result.value <= result.gdp_ceiling.nominal_gdp_cagr
    assert result.trace.inputs == (
        result.gdp_ceiling.content_digest,
        result.risk_free_selection_digest,
        sha256_digest(result.plan),
    )
    assert sha256_digest(result.plan) in result.trace.source_refs
    assert result.gdp_ceiling.content_digest in result.trace.source_refs
    assert result.input_digest in result.trace.source_refs
    evidence = terminal_growth_evidence(result)
    assert evidence.method == "approved_policy"
    assert evidence.value == result.value
    assert evidence.content_hash == result.output_digest
    assert "not observed issuer growth" in evidence.rationale
    assert select_terminal_growth(_plan(), admissions=admissions) == result
    assert (
        select_terminal_growth(
            _plan(), admissions=(*reversed(admissions), admissions[0])
        )
        == result
    )


@pytest.mark.parametrize(
    "case,code",
    [
        ("missing", "TERMINAL_GDP_SOURCE_UNAVAILABLE"),
        ("future", "TERMINAL_GDP_SOURCE_UNAVAILABLE"),
        ("gap", "TERMINAL_GDP_HORIZON_UNAVAILABLE"),
        ("stale", "TERMINAL_GDP_PERIOD_STALE"),
        ("rate", "MARKET_RATE_SOURCE_UNAVAILABLE"),
        ("conflict", "TERMINAL_GDP_SOURCE_UNAVAILABLE"),
    ],
)
def test_unusable_sources_fail_with_stable_reasons_and_preserve_inputs(case, code):
    admissions = _admissions(
        missing=2020 if case == "gap" else None,
        gdp_at=AT + timedelta(days=1) if case == "future" else None,
    )
    plan = _plan(maximum_gdp_period_age_days=1) if case == "stale" else _plan()
    if case == "missing":
        admissions = admissions[:1]
    elif case == "rate":
        admissions = admissions[1:]
    elif case == "conflict":
        admissions = (*admissions, _admissions(increment="101")[1])
    before = canonical_bytes(admissions)
    for ordered in (admissions, tuple(reversed(admissions))):
        with pytest.raises(MarketSourceError) as error:
            select_terminal_growth(plan, admissions=ordered)
        assert error.value.code == code
    assert canonical_bytes(admissions) == before


def test_latest_incomplete_gdp_never_falls_back_to_a_complete_old_vintage():
    older = _admissions(at=AT - timedelta(days=1))[1]
    latest = _admissions(missing=2020)[1]
    rate = _admissions()[0]
    with pytest.raises(MarketSourceError) as error:
        select_terminal_growth(_plan(), admissions=(older, latest, rate))
    assert error.value.code == "TERMINAL_GDP_HORIZON_UNAVAILABLE"


def test_terminal_selection_ignores_ambient_decimal_context_and_concurrency():
    admissions = _admissions(increment="5")
    expected = select_terminal_growth(_plan(), admissions=admissions)
    with localcontext(Context(prec=6, traps=[Inexact])):
        assert select_terminal_growth(_plan(), admissions=admissions) == expected
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(
            executor.map(
                lambda _: select_terminal_growth(_plan(), admissions=admissions),
                range(2),
            )
        ) == [expected, expected]


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "EUR"},
        {"valuation_at": AT.replace(tzinfo=None)},
        {"gdp_horizon_years": 0},
        {"maximum_gdp_period_age_days": -1},
        {
            "risk_free_policy": USD_RISK_FREE_POLICY.model_copy(
                update={"series_id": "us.sofr_overnight"}
            )
        },
    ],
)
def test_unsupported_currency_time_horizon_and_benchmark_cannot_claim_the_rule(changes):
    with pytest.raises(ValidationError):
        _plan(**changes)
