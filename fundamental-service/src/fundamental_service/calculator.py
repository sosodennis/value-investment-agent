"""Pure Decimal valuation graphs for the initial Fundamental profiles."""

from __future__ import annotations

from decimal import Decimal

from .contracts import (
    CalculationArtifactV1,
    CalculationNodeV1,
    CalculationStatus,
    QualityStatus,
    TraceV1,
    ValuationInputV1,
)
from .numerical_policy import using_valuation_context
from .operating_projection import (
    OperatingProjectionError,
    project_operating_nodes,
    resolve_operating_model,
)
from .serialization import sha256_digest


class CalculationRefusal(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _artifact_digests(
    request: ValuationInputV1,
    *,
    equity: Decimal,
    per_share: Decimal,
    nodes: list[CalculationNodeV1],
) -> tuple[str, str]:
    expected_input_digest = sha256_digest(
        request.model_dump(exclude={"input_digest", "caller_approval"})
    )
    if (
        request.input_digest is not None
        and request.input_digest != expected_input_digest
    ):
        raise CalculationRefusal(
            "INPUT_DIGEST_MISMATCH", "input_digest does not match the complete request"
        )
    result_hash = sha256_digest(
        {
            "input_digest": expected_input_digest,
            "intrinsic_value": equity,
            "per_share_value": per_share,
            "nodes": nodes,
            "model_version": request.model_version,
        }
    )
    return expected_input_digest, result_hash


def _node(
    node_id: str, formula: str, value: Decimal, unit: str, inputs: tuple[str, ...]
) -> CalculationNodeV1:
    return CalculationNodeV1(
        node_id=node_id,
        formula=formula,
        inputs=inputs,
        value=value,
        unit=unit,
        trace=TraceV1(expression=formula, inputs=inputs),
    )


def calculation_result_hash(artifact: CalculationArtifactV1) -> str:
    return sha256_digest(
        artifact.model_dump(
            mode="python",
            exclude={
                "result_hash",
                "artifact_references",
                "evaluated_at",
                "correlation_id",
                # Caller-vs-policy precedence describes how the same resolved
                # inputs were supplied; it is not part of calculation identity.
                "policy_resolution",
            },
        )
    )


def with_calculation_result_hash(
    artifact: CalculationArtifactV1,
) -> CalculationArtifactV1:
    return artifact.model_copy(
        update={"result_hash": calculation_result_hash(artifact)}
    )


@using_valuation_context
def calculate(
    request: ValuationInputV1,
    *,
    correlation_id: str = "local",
    allow_provisional: bool = False,
) -> CalculationArtifactV1:
    if (
        request.caller_approval is not None
        and request.caller_approval.decision != "approved"
    ):
        raise CalculationRefusal(
            "CALLER_APPROVAL_REJECTED",
            "caller rejected this exact valuation input",
        )
    try:
        resolve_operating_model(request.model_id, request.model_version)
    except OperatingProjectionError as error:
        raise CalculationRefusal(error.code, str(error)) from error
    quality_status = request.quality.status
    if quality_status is not QualityStatus.VERIFIED and not (
        allow_provisional and quality_status is QualityStatus.PROVISIONAL
    ):
        raise CalculationRefusal(
            "QUALITY_NOT_VERIFIED", "calculation requires verified quality"
        )
    if request.uncertainty.mode != "none":
        raise CalculationRefusal(
            "UNCERTAINTY_NOT_IMPLEMENTED",
            "explicit uncertainty controls must be executed by service orchestration",
        )
    wacc = request.assumptions.wacc
    growth = request.assumptions.terminal_growth
    forecast = request.assumptions.forecast
    bridge = request.assumptions.capital_bridge
    if wacc is None or growth is None or forecast is None or bridge is None:
        raise CalculationRefusal(
            "ASSUMPTIONS_INCOMPLETE", "complete FCFF assumptions are required"
        )
    if wacc.debt_weight + wacc.equity_weight != Decimal("1"):
        raise CalculationRefusal(
            "WACC_WEIGHTS_INVALID", "capital weights must sum to one"
        )
    cost_equity = wacc.risk_free_rate + wacc.beta * wacc.equity_risk_premium
    after_tax_debt = wacc.pre_tax_cost_of_debt * (Decimal("1") - wacc.tax_rate)
    wacc_value = wacc.equity_weight * cost_equity + wacc.debt_weight * after_tax_debt
    if wacc_value <= growth or wacc_value <= 0:
        raise CalculationRefusal(
            "DISCOUNT_RATE_INVALID", "WACC must exceed terminal growth and zero"
        )
    try:
        operating_nodes = project_operating_nodes(
            forecast,
            tax_rate=wacc.tax_rate,
            historical_fact_ids=tuple(request.historical_facts),
        )
    except OperatingProjectionError as error:
        raise CalculationRefusal(error.code, str(error)) from error
    nodes = [
        _node(
            "cost_of_equity",
            "risk_free_rate + beta * equity_risk_premium",
            cost_equity,
            "rate",
            ("wacc",),
        ),
        _node(
            "after_tax_debt",
            "pre_tax_cost_of_debt * (1 - tax_rate)",
            after_tax_debt,
            "rate",
            ("wacc",),
        ),
        _node(
            "wacc",
            "equity_weight * cost_of_equity + debt_weight * after_tax_debt",
            wacc_value,
            "rate",
            ("cost_of_equity", "after_tax_debt"),
        ),
    ]
    nodes.append(operating_nodes[0])
    present_value = Decimal("0")
    last_fcff = Decimal("0")
    for index in range(1, len(forecast.revenue_growth) + 1):
        revenue_node, fcff_node = operating_nodes[2 * index - 1 : 2 * index + 1]
        fcff = fcff_node.value
        assert fcff is not None
        discounted = fcff / ((Decimal("1") + wacc_value) ** index)
        present_value += discounted
        last_fcff = fcff
        nodes.extend(
            (
                revenue_node,
                fcff_node,
                _node(
                    f"discounted_fcff_{index}",
                    "fcff / (1 + wacc)^period",
                    discounted,
                    "currency",
                    (f"fcff_{index}", "wacc"),
                ),
            )
        )
    terminal_value = last_fcff * (Decimal("1") + growth) / (wacc_value - growth)
    terminal_pv = terminal_value / (
        (Decimal("1") + wacc_value) ** len(forecast.revenue_growth)
    )
    nodes.append(
        _node(
            "discounted_terminal_value",
            "terminal_value / (1 + wacc)^forecast_periods",
            terminal_pv,
            "currency",
            ("terminal_value", "wacc"),
        )
    )
    enterprise = present_value + terminal_pv
    equity = (
        enterprise
        + bridge.cash
        + bridge.non_operating_assets
        - bridge.debt
        - bridge.preferred_stock
        - bridge.lease_liabilities
        - bridge.non_controlling_interest
    )
    per_share = equity / bridge.diluted_shares
    nodes.extend(
        (
            _node(
                "terminal_value",
                "last_fcff * (1 + terminal_growth) / (wacc - terminal_growth)",
                terminal_value,
                "currency",
                (f"fcff_{len(forecast.revenue_growth)}", "wacc"),
            ),
            _node(
                "enterprise_value",
                "sum(discounted_fcff) + discounted_terminal_value",
                enterprise,
                "currency",
                tuple(
                    [
                        f"discounted_fcff_{index}"
                        for index in range(1, len(forecast.revenue_growth) + 1)
                    ]
                    + ["discounted_terminal_value"]
                ),
            ),
            _node(
                "equity_value",
                "enterprise_value + cash + non_operating_assets - debt - preferred - leases - NCI",
                equity,
                "currency",
                ("enterprise_value",),
            ),
            _node(
                "per_share_value",
                "equity_value / diluted_shares",
                per_share,
                "currency/share",
                ("equity_value",),
            ),
        )
    )
    expected_input_digest = sha256_digest(
        request.model_dump(exclude={"input_digest", "caller_approval"})
    )
    if (
        request.input_digest is not None
        and request.input_digest != expected_input_digest
    ):
        raise CalculationRefusal(
            "INPUT_DIGEST_MISMATCH", "input_digest does not match the complete request"
        )
    input_digest = expected_input_digest
    result = CalculationArtifactV1(
        contract_version="fundamental.v1",
        calculation_version="calculator-v2",
        calculation_status=CalculationStatus.COMPLETED,
        quality_status=quality_status,
        input_digest=input_digest,
        intrinsic_value=equity,
        per_share_value=per_share,
        nodes=tuple(nodes),
        assumptions=request.assumptions,
        policy_id=request.policy_id,
        model_version=request.model_version,
        policy_version=request.provenance.policy_version,
        snapshot_id=request.valuation_context.data_snapshot_id,
        valuation_timestamp=request.valuation_context.valuation_timestamp,
        evaluated_at=request.valuation_context.valuation_timestamp,
        correlation_id=correlation_id,
        result_hash="0" * 64,
    )
    return with_calculation_result_hash(result)


def validate(request: ValuationInputV1) -> ValuationInputV1:
    return request if request.input_digest is not None else request.with_digest()
