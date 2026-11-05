"""Research-only bank excess-return graph and independent challenger.

The production calculator deliberately does not dispatch this model until a
release manifest proves issuer mapping, source, cohort, calibration, and
rollback gates.
"""

from __future__ import annotations

from decimal import Decimal

from .calculator import CalculationRefusal, _artifact_digests, _node
from .contracts import (
    BankAssumptionsV1,
    CalculationArtifactV1,
    CalculationNodeV1,
    CalculationStatus,
    QualityStatus,
    ValuationInputV1,
)


def calculate_bank_excess_return(
    request: ValuationInputV1, *, correlation_id: str = "local"
) -> CalculationArtifactV1:
    """Value bank equity from caller forecasts and explicitly mapped facts."""

    bank = request.assumptions.bank
    if request.model_id != "bank_excess_return" or bank is None:
        raise CalculationRefusal(
            "BANK_ASSUMPTIONS_MISSING", "bank model requires typed bank assumptions"
        )
    if request.quality.status is not QualityStatus.VERIFIED:
        raise CalculationRefusal(
            "QUALITY_NOT_VERIFIED", "calculation requires verified quality"
        )

    fact_refs = bank.fact_references
    retained_share = Decimal("1") - bank.payout_ratio
    book_value = bank.tangible_book_value
    projected_capital = bank.cet1_capital
    projected_rwa = bank.reported_rwa
    present_value = Decimal("0")
    nodes: list[CalculationNodeV1] = [
        _node(
            "bank_current_book_value",
            "reported current book value",
            bank.current_book_value,
            "currency",
            (fact_refs["current_book_value"],),
        ),
        _node(
            "bank_tangible_book_value",
            "reported tangible book value",
            bank.tangible_book_value,
            "currency",
            (fact_refs["tangible_book_value"],),
        ),
        _node(
            "bank_reported_cet1_capital",
            "reported CET1 capital",
            bank.cet1_capital,
            "currency",
            (fact_refs["cet1_capital"],),
        ),
        _node(
            "bank_reported_rwa",
            "reported risk-weighted assets",
            bank.reported_rwa,
            "currency",
            (fact_refs["reported_rwa"],),
        ),
        _node(
            "bank_reported_cet1_ratio",
            "reported CET1 capital / reported risk-weighted assets",
            bank.cet1_ratio,
            "rate",
            ("bank_reported_cet1_capital", "bank_reported_rwa"),
        ),
        _node(
            "bank_diluted_shares",
            "reported diluted shares",
            bank.diluted_shares,
            "shares",
            (fact_refs["diluted_shares"],),
        ),
        _node(
            "bank_owner_supplied_forecast_assumptions",
            "explicit caller-owned forecast and capital policy inputs",
            Decimal(len(bank.forecast_net_income)),
            "periods",
            (),
        ),
    ]

    for period, (net_income, rwa_growth) in enumerate(
        zip(bank.forecast_net_income, bank.forecast_rwa_growth, strict=True), start=1
    ):
        income_node = f"bank_forecast_net_income_{period}"
        growth_node = f"bank_forecast_rwa_growth_{period}"
        nodes.extend(
            (
                _node(
                    income_node,
                    "explicit caller forecast net income",
                    net_income,
                    "currency",
                    (),
                ),
                _node(
                    growth_node,
                    "explicit caller risk-weighted-asset growth",
                    rwa_growth,
                    "rate",
                    (),
                ),
            )
        )
        projected_capital += net_income * retained_share
        projected_rwa *= Decimal("1") + rwa_growth
        capital_ratio = projected_capital / projected_rwa
        if capital_ratio < bank.minimum_cet1_ratio:
            raise CalculationRefusal(
                "BANK_CAPITAL_BUFFER_BREACH",
                "projected CET1 ratio is below the caller's declared floor",
            )
        beginning_book_value = book_value
        ending_book_value = beginning_book_value + net_income * retained_share
        residual_income = net_income - bank.cost_of_equity * beginning_book_value
        discounted_residual_income = residual_income / (
            (Decimal("1") + bank.cost_of_equity) ** period
        )
        nodes.extend(
            (
                _node(
                    f"bank_cet1_capital_{period}",
                    "prior_CET1_capital + forecast_net_income * retained_share",
                    projected_capital,
                    "currency",
                    (
                        "bank_reported_cet1_capital"
                        if period == 1
                        else f"bank_cet1_capital_{period - 1}",
                        income_node,
                    ),
                ),
                _node(
                    f"bank_rwa_{period}",
                    "prior_risk_weighted_assets * (1 + caller_growth)",
                    projected_rwa,
                    "currency",
                    (
                        "bank_reported_rwa"
                        if period == 1
                        else f"bank_rwa_{period - 1}",
                        growth_node,
                    ),
                ),
                _node(
                    f"bank_cet1_ratio_{period}",
                    "projected_CET1_capital / projected_risk_weighted_assets",
                    capital_ratio,
                    "rate",
                    (f"bank_cet1_capital_{period}", f"bank_rwa_{period}"),
                ),
                _node(
                    f"bank_beginning_book_value_{period}",
                    "tangible_book_value"
                    if period == 1
                    else "prior_period_ending_book_value",
                    beginning_book_value,
                    "currency",
                    (
                        "bank_tangible_book_value"
                        if period == 1
                        else f"bank_book_value_{period - 1}",
                    ),
                ),
                _node(
                    f"bank_book_value_{period}",
                    "beginning_book_value + forecast_net_income * retained_share",
                    ending_book_value,
                    "currency",
                    (
                        f"bank_beginning_book_value_{period}",
                        income_node,
                    ),
                ),
                _node(
                    f"bank_residual_income_{period}",
                    "forecast_net_income - cost_of_equity * beginning_book_value",
                    residual_income,
                    "currency",
                    (income_node, f"bank_beginning_book_value_{period}"),
                ),
                _node(
                    f"bank_discounted_residual_income_{period}",
                    "residual_income / (1 + cost_of_equity)^period",
                    discounted_residual_income,
                    "currency",
                    (f"bank_residual_income_{period}",),
                ),
            )
        )
        book_value = ending_book_value

    periods = len(bank.forecast_net_income)
    terminal_income = bank.forecast_net_income[-1] * (
        Decimal("1") + bank.terminal_growth
    )
    terminal_residual_income = terminal_income - bank.cost_of_equity * book_value
    terminal_residual_value = terminal_residual_income / (
        bank.cost_of_equity - bank.terminal_growth
    )
    discounted_terminal_value = terminal_residual_value / (
        (Decimal("1") + bank.cost_of_equity) ** periods
    )
    for node in nodes:
        if node.node_id.startswith("bank_discounted_residual_income_"):
            present_value += node.value or Decimal("0")
    equity_value = bank.tangible_book_value + present_value + discounted_terminal_value
    per_share = equity_value / bank.diluted_shares
    nodes.extend(
        (
            _node(
                "bank_terminal_net_income",
                "last_forecast_net_income * (1 + terminal_growth)",
                terminal_income,
                "currency",
                (f"bank_forecast_net_income_{periods}",),
            ),
            _node(
                "bank_terminal_book_value",
                "ending_book_value_at_forecast_horizon",
                book_value,
                "currency",
                (f"bank_book_value_{periods}",),
            ),
            _node(
                "bank_terminal_residual_income",
                "terminal_net_income - cost_of_equity * terminal_book_value",
                terminal_residual_income,
                "currency",
                ("bank_terminal_net_income", "bank_terminal_book_value"),
            ),
            _node(
                "bank_terminal_value",
                "terminal_residual_income / (cost_of_equity - terminal_growth)",
                terminal_residual_value,
                "currency",
                ("bank_terminal_residual_income",),
            ),
            _node(
                "bank_discounted_terminal_value",
                "terminal_value / (1 + cost_of_equity)^forecast_periods",
                discounted_terminal_value,
                "currency",
                ("bank_terminal_value",),
            ),
            _node(
                "bank_equity_value",
                "tangible_book_value + PV(forecast residual income) + PV(terminal)",
                equity_value,
                "currency",
                ("bank_tangible_book_value",)
                + tuple(
                    node.node_id
                    for node in nodes
                    if node.node_id.startswith("bank_discounted_residual_income_")
                )
                + ("bank_discounted_terminal_value",),
            ),
            _node(
                "bank_per_share_value",
                "equity_value / diluted_shares",
                per_share,
                f"{request.identity.currency}/share",
                ("bank_equity_value", "bank_diluted_shares"),
            ),
        )
    )
    input_digest, result_hash = _artifact_digests(
        request, equity=equity_value, per_share=per_share, nodes=nodes
    )
    return CalculationArtifactV1(
        contract_version="fundamental.v1",
        calculation_version="bank-excess-return-v1",
        calculation_status=CalculationStatus.COMPLETED,
        quality_status=QualityStatus.PROVISIONAL,
        input_digest=input_digest,
        result_hash=result_hash,
        intrinsic_value=equity_value,
        per_share_value=per_share,
        nodes=tuple(nodes),
        assumptions=request.assumptions,
        model_version=request.model_version,
        policy_version=request.policy_id,
        snapshot_id=request.valuation_context.data_snapshot_id,
        evaluated_at=request.valuation_context.valuation_timestamp,
        correlation_id=correlation_id,
    )


def independent_bank_reference(
    request: ValuationInputV1,
) -> tuple[Decimal, Decimal, dict[str, Decimal]]:
    """Independently entered residual-income equations for challenger checks."""

    bank: BankAssumptionsV1 | None = request.assumptions.bank
    if request.model_id != "bank_excess_return" or bank is None:
        raise ValueError("bank challenger requires typed bank valuation input")
    retained_share = Decimal("1") - bank.payout_ratio
    capital = bank.cet1_capital
    risk_weighted_assets = bank.reported_rwa
    beginning_book_value = bank.tangible_book_value
    present_value = Decimal("0")
    expected: dict[str, Decimal] = {}
    for year, (earnings, rwa_change) in enumerate(
        zip(bank.forecast_net_income, bank.forecast_rwa_growth, strict=True), start=1
    ):
        capital += earnings * retained_share
        risk_weighted_assets *= Decimal("1") + rwa_change
        capital_ratio = capital / risk_weighted_assets
        if capital_ratio < bank.minimum_cet1_ratio:
            raise ValueError("BANK_CAPITAL_BUFFER_BREACH")
        excess_return = earnings - bank.cost_of_equity * beginning_book_value
        discounted_excess = excess_return / (
            (Decimal("1") + bank.cost_of_equity) ** year
        )
        expected[f"bank_cet1_capital_{year}"] = capital
        expected[f"bank_rwa_{year}"] = risk_weighted_assets
        expected[f"bank_cet1_ratio_{year}"] = capital_ratio
        expected[f"bank_beginning_book_value_{year}"] = beginning_book_value
        ending_book_value = beginning_book_value + earnings * retained_share
        expected[f"bank_book_value_{year}"] = ending_book_value
        expected[f"bank_residual_income_{year}"] = excess_return
        expected[f"bank_discounted_residual_income_{year}"] = discounted_excess
        present_value += discounted_excess
        beginning_book_value = ending_book_value

    terminal_income = bank.forecast_net_income[-1] * (
        Decimal("1") + bank.terminal_growth
    )
    terminal_residual = terminal_income - bank.cost_of_equity * beginning_book_value
    terminal_value = terminal_residual / (bank.cost_of_equity - bank.terminal_growth)
    discounted_terminal = terminal_value / (
        (Decimal("1") + bank.cost_of_equity) ** len(bank.forecast_net_income)
    )
    equity = bank.tangible_book_value + present_value + discounted_terminal
    expected.update(
        {
            "bank_terminal_net_income": terminal_income,
            "bank_terminal_book_value": beginning_book_value,
            "bank_terminal_residual_income": terminal_residual,
            "bank_terminal_value": terminal_value,
            "bank_discounted_terminal_value": discounted_terminal,
            "bank_equity_value": equity,
            "bank_per_share_value": equity / bank.diluted_shares,
        }
    )
    return equity, equity / bank.diluted_shares, expected


def bank_artifact_findings(
    request: ValuationInputV1, artifact: CalculationArtifactV1
) -> tuple[str, ...]:
    """Compare every bank result node with the separate challenger equations."""

    try:
        equity, per_share, expected = independent_bank_reference(request)
    except ValueError as error:
        return (str(error),)
    actual_nodes = {node.node_id: node for node in artifact.nodes}
    if len(actual_nodes) != len(artifact.nodes):
        return ("calculation_nodes:duplicate_id",)
    for node_id, expected_value in expected.items():
        actual = actual_nodes.get(node_id)
        if actual is None or actual.value != expected_value:
            return (f"{node_id}:value",)
    if artifact.intrinsic_value != equity:
        return ("bank_equity_value:reported_value",)
    if artifact.per_share_value != per_share:
        return ("bank_per_share_value:reported_value",)
    if artifact.calculation_version != "bank-excess-return-v1":
        return ("calculation_version:mismatch",)
    if artifact.calculation_status is not CalculationStatus.COMPLETED:
        return ("calculation_status:not_completed",)
    if artifact.quality_status is not QualityStatus.PROVISIONAL:
        return ("quality_status:not_provisional",)
    for node in artifact.nodes:
        if node.value is not None and not node.value.is_finite():
            return (f"{node.node_id}:non_finite",)
        if (
            node.node_id.endswith("_ratio")
            or "_ratio_" in node.node_id
            or "_growth_" in node.node_id
        ):
            if node.unit != "rate":
                return (f"{node.node_id}:unit",)
        elif node.node_id == "bank_diluted_shares":
            if node.unit != "shares":
                return (f"{node.node_id}:unit",)
        elif node.node_id == "bank_per_share_value":
            if node.unit != f"{request.identity.currency}/share":
                return (f"{node.node_id}:unit",)
        elif node.node_id == "bank_owner_supplied_forecast_assumptions":
            if node.unit != "periods":
                return (f"{node.node_id}:unit",)
        elif node.value is not None and node.unit != "currency":
            return (f"{node.node_id}:unit",)
    return ()


__all__ = [
    "bank_artifact_findings",
    "calculate_bank_excess_return",
    "independent_bank_reference",
]
