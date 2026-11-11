"""Independent calculation and evidence primitives for the Fundamental release gate.

This module deliberately has no dependency on ``calculator.py``.  It owns the
reference equations, tolerances, invariant checks, and the offline cohort
loader.  The release-gate adapter is the only layer that invokes the production
calculator and compares its result with this reference implementation.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any, Literal

from .contracts import CalculationArtifactV1, QualityStatus, ValuationInputV1
from .numerical_policy import using_valuation_context
from .serialization import canonical_bytes


class VerificationRefusal(ValueError):
    """A reference calculation refused an input for a declared reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IndependentNode:
    node_id: str
    formula: str
    value: Decimal
    unit: str
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class IndependentResult:
    intrinsic_value: Decimal
    per_share_value: Decimal
    nodes: tuple[IndependentNode, ...]

    @property
    def node_map(self) -> dict[str, IndependentNode]:
        return {node.node_id: node for node in self.nodes}


@dataclass(frozen=True)
class NodeTolerance:
    absolute: Decimal
    relative: Decimal


DEFAULT_CURRENCY_TOLERANCE = NodeTolerance(Decimal("1"), Decimal("1e-9"))
PER_SHARE_TOLERANCE = NodeTolerance(Decimal("0.000001"), Decimal("1e-9"))
RATE_TOLERANCE = NodeTolerance(Decimal("1e-12"), Decimal("1e-9"))


@dataclass(frozen=True)
class CohortCase:
    case_id: str
    kind: Literal["positive", "abstain", "degraded"]
    model_id: str
    sector: str
    source_snapshot_id: str
    source_fixture: str
    source_sha256: str
    features: tuple[str, ...]
    expected_refusal_code: str | None
    request_overrides: Mapping[str, Any]


def _node(
    node_id: str,
    formula: str,
    value: Decimal,
    unit: str,
    inputs: tuple[str, ...],
) -> IndependentNode:
    if not value.is_finite():
        raise VerificationRefusal("NON_FINITE_ARITHMETIC", f"{node_id} is not finite")
    return IndependentNode(node_id, formula, value, unit, inputs)


def _quality_status(request: ValuationInputV1) -> QualityStatus:
    value = request.quality.status
    return value if isinstance(value, QualityStatus) else QualityStatus(value)


@using_valuation_context
def independent_calculate(request: ValuationInputV1) -> IndependentResult:
    """Recompute the production graph with independently entered equations.

    The implementation intentionally uses only the public request contract and
    does not import or call any production calculation function.
    """

    if _quality_status(request) is not QualityStatus.VERIFIED:
        raise VerificationRefusal(
            "QUALITY_NOT_VERIFIED", "reference calculation requires verified quality"
        )
    if request.uncertainty.mode != "none":
        raise VerificationRefusal(
            "UNCERTAINTY_NOT_IMPLEMENTED",
            "reference cohort only evaluates deterministic requests",
        )
    if request.model_id not in {"fcff_dcf", "transition_fcff_dcf"}:
        raise VerificationRefusal(
            "MODEL_UNSUPPORTED", "model is outside the V1 profile"
        )
    if request.model_id == "transition_fcff_dcf" and (
        "filed_operating_evidence" not in request.historical_facts
    ):
        raise VerificationRefusal(
            "TRANSITION_EVIDENCE_MISSING",
            "guarded transition DCF requires filed operating evidence",
        )

    assumptions = request.assumptions
    wacc = assumptions.wacc
    growth = assumptions.terminal_growth
    forecast = assumptions.forecast
    bridge = assumptions.capital_bridge
    if wacc is None or growth is None or forecast is None or bridge is None:
        raise VerificationRefusal(
            "ASSUMPTIONS_INCOMPLETE", "complete FCFF assumptions are required"
        )
    if wacc.debt_weight + wacc.equity_weight != Decimal("1"):
        raise VerificationRefusal(
            "WACC_WEIGHTS_INVALID", "capital weights do not sum to one"
        )

    with localcontext() as context:
        context.prec = 50
        cost_equity = wacc.risk_free_rate + wacc.beta * wacc.equity_risk_premium
        after_tax_debt = wacc.pre_tax_cost_of_debt * (Decimal("1") - wacc.tax_rate)
        weighted_wacc = (
            wacc.equity_weight * cost_equity + wacc.debt_weight * after_tax_debt
        )
        if (
            not weighted_wacc.is_finite()
            or weighted_wacc <= growth
            or weighted_wacc <= 0
        ):
            raise VerificationRefusal(
                "DISCOUNT_RATE_INVALID", "WACC must exceed terminal growth and zero"
            )
        if forecast.base_revenue is None or forecast.base_revenue <= 0:
            raise VerificationRefusal(
                "BASE_REVENUE_MISSING", "a positive base revenue fact is required"
            )
        if not (
            len(forecast.revenue_growth)
            == len(forecast.operating_margin)
            == len(forecast.reinvestment_rate)
            and forecast.revenue_growth
        ):
            raise VerificationRefusal(
                "FORECAST_INVALID", "forecast arrays must be non-empty and equal length"
            )

        nodes: list[IndependentNode] = [
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
                weighted_wacc,
                "rate",
                ("cost_of_equity", "after_tax_debt"),
            ),
            _node(
                "base_revenue",
                "historical revenue fact",
                forecast.base_revenue,
                "currency",
                tuple(request.historical_facts),
            ),
        ]
        revenue = forecast.base_revenue
        present_value = Decimal("0")
        last_fcff = Decimal("0")
        for period, (revenue_growth, margin, reinvestment) in enumerate(
            zip(
                forecast.revenue_growth,
                forecast.operating_margin,
                forecast.reinvestment_rate,
            ),
            start=1,
        ):
            revenue = revenue * (Decimal("1") + revenue_growth)
            fcff = (
                revenue
                * margin
                * (Decimal("1") - wacc.tax_rate)
                * (Decimal("1") - reinvestment)
            )
            discounted = fcff / ((Decimal("1") + weighted_wacc) ** period)
            present_value += discounted
            last_fcff = fcff
            nodes.extend(
                (
                    _node(
                        f"revenue_{period}",
                        "prior_revenue * (1 + growth)",
                        revenue,
                        "currency",
                        (f"revenue_{period - 1}" if period > 1 else "base_revenue",),
                    ),
                    _node(
                        f"fcff_{period}",
                        "revenue * margin * (1 - tax_rate) * (1 - reinvestment_rate)",
                        fcff,
                        "currency",
                        (f"revenue_{period}",),
                    ),
                    _node(
                        f"discounted_fcff_{period}",
                        "fcff / (1 + wacc)^period",
                        discounted,
                        "currency",
                        (f"fcff_{period}", "wacc"),
                    ),
                )
            )

        terminal_value = last_fcff * (Decimal("1") + growth) / (weighted_wacc - growth)
        terminal_pv = terminal_value / (
            (Decimal("1") + weighted_wacc) ** len(forecast.revenue_growth)
        )
        nodes.extend(
            (
                _node(
                    "discounted_terminal_value",
                    "terminal_value / (1 + wacc)^forecast_periods",
                    terminal_pv,
                    "currency",
                    ("terminal_value", "wacc"),
                ),
                _node(
                    "terminal_value",
                    "last_fcff * (1 + terminal_growth) / (wacc - terminal_growth)",
                    terminal_value,
                    "currency",
                    (f"fcff_{len(forecast.revenue_growth)}", "wacc"),
                ),
            )
        )
        enterprise = present_value + terminal_pv
        equity = (
            enterprise
            + bridge.cash
            - bridge.debt
            - bridge.preferred_stock
            - bridge.lease_liabilities
            - bridge.non_controlling_interest
        )
        per_share = equity / bridge.diluted_shares
        nodes.extend(
            (
                _node(
                    "enterprise_value",
                    "sum(discounted_fcff) + discounted_terminal_value",
                    enterprise,
                    "currency",
                    tuple(
                        [
                            f"discounted_fcff_{period}"
                            for period in range(1, len(forecast.revenue_growth) + 1)
                        ]
                        + ["discounted_terminal_value"]
                    ),
                ),
                _node(
                    "equity_value",
                    "enterprise_value + cash - debt - preferred - leases - NCI",
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
        return IndependentResult(equity, per_share, tuple(nodes))


def _tolerance(node: IndependentNode) -> NodeTolerance:
    return (
        PER_SHARE_TOLERANCE
        if node.unit == "currency/share"
        else (RATE_TOLERANCE if node.unit == "rate" else DEFAULT_CURRENCY_TOLERANCE)
    )


def _within(actual: Decimal, expected: Decimal, tolerance: NodeTolerance) -> bool:
    if not actual.is_finite() or not expected.is_finite():
        return False
    difference = abs(actual - expected)
    scale = max(abs(actual), abs(expected), Decimal("1"))
    return difference <= max(tolerance.absolute, tolerance.relative * scale)


@using_valuation_context
def compare_artifact(
    reference: IndependentResult, artifact: CalculationArtifactV1
) -> tuple[str, ...]:
    """Return first-node-oriented differential findings for a production artifact."""

    findings: list[str] = []
    actual_nodes = {node.node_id: node for node in artifact.nodes}
    if len(actual_nodes) != len(artifact.nodes):
        return ("calculation_nodes:duplicate_id",)
    for expected in reference.nodes:
        actual = actual_nodes.get(expected.node_id)
        if actual is None:
            findings.append(f"{expected.node_id}:missing")
            break
        if (actual.formula, actual.unit, actual.inputs) != (
            expected.formula,
            expected.unit,
            expected.inputs,
        ):
            findings.append(f"{expected.node_id}:structure")
            break
        if actual.value is None or not _within(
            actual.value, expected.value, _tolerance(expected)
        ):
            findings.append(f"{expected.node_id}:value")
            break
    if not findings:
        if artifact.intrinsic_value is None or not _within(
            artifact.intrinsic_value,
            reference.intrinsic_value,
            DEFAULT_CURRENCY_TOLERANCE,
        ):
            findings.append("equity_value:reported_value")
        elif artifact.per_share_value is None or not _within(
            artifact.per_share_value,
            reference.per_share_value,
            PER_SHARE_TOLERANCE,
        ):
            findings.append("per_share_value:reported_value")
    if not findings:
        expected_ids = {node.node_id for node in reference.nodes}
        extra = sorted(set(actual_nodes) - expected_ids)
        if extra:
            findings.append(f"{extra[0]}:unexpected_node")
    return tuple(findings)


@using_valuation_context
def invariant_findings(
    request: ValuationInputV1, result: IndependentResult
) -> tuple[str, ...]:
    """Check dimensions and conservation identities independently of node output."""

    findings: list[str] = []
    expected_units = {
        "cost_of_equity": "rate",
        "after_tax_debt": "rate",
        "wacc": "rate",
        "per_share_value": "currency/share",
    }
    for node in result.nodes:
        if not node.value.is_finite():
            findings.append(f"{node.node_id}:non_finite")
        if expected_units.get(node.node_id, "currency") != node.unit:
            findings.append(f"{node.node_id}:dimension")
    values = result.node_map
    discounted = sum(
        values[node_id].value
        for node_id in values
        if node_id.startswith("discounted_fcff_")
    )
    if (
        values["enterprise_value"].value
        != discounted + values["discounted_terminal_value"].value
    ):
        findings.append("enterprise_value:conservation")
    bridge = request.assumptions.capital_bridge
    if bridge is None:
        raise VerificationRefusal(
            "ASSUMPTIONS_INCOMPLETE", "capital bridge is required"
        )
    expected_equity = (
        values["enterprise_value"].value
        + bridge.cash
        - bridge.debt
        - bridge.preferred_stock
        - bridge.lease_liabilities
        - bridge.non_controlling_interest
    )
    if values["equity_value"].value != expected_equity:
        findings.append("equity_value:conservation")
    if (
        values["per_share_value"].value
        != values["equity_value"].value / bridge.diluted_shares
    ):
        findings.append("per_share_value:conservation")
    return tuple(findings)


@using_valuation_context
def property_findings(request: ValuationInputV1) -> tuple[str, ...]:
    """Run deterministic monotonicity and metamorphic checks over the reference."""

    baseline = independent_calculate(request)
    assumptions = request.assumptions
    bridge = assumptions.capital_bridge
    wacc = assumptions.wacc
    if bridge is None or wacc is None:
        raise VerificationRefusal(
            "ASSUMPTIONS_INCOMPLETE", "FCFF assumptions are required"
        )
    checks: list[str] = []

    higher_cash = request.model_copy(
        update={
            "assumptions": assumptions.model_copy(
                update={
                    "capital_bridge": bridge.model_copy(
                        update={"cash": bridge.cash + Decimal("1")}
                    )
                }
            )
        }
    )
    if independent_calculate(higher_cash).intrinsic_value <= baseline.intrinsic_value:
        checks.append("cash_monotonicity")

    higher_debt = request.model_copy(
        update={
            "assumptions": assumptions.model_copy(
                update={
                    "capital_bridge": bridge.model_copy(
                        update={"debt": bridge.debt + Decimal("1")}
                    )
                }
            )
        }
    )
    if independent_calculate(higher_debt).intrinsic_value >= baseline.intrinsic_value:
        checks.append("debt_monotonicity")

    doubled_shares = request.model_copy(
        update={
            "assumptions": assumptions.model_copy(
                update={
                    "capital_bridge": bridge.model_copy(
                        update={"diluted_shares": bridge.diluted_shares * Decimal("2")}
                    )
                }
            )
        }
    )
    transformed = independent_calculate(doubled_shares)
    if not _within(
        transformed.per_share_value,
        baseline.per_share_value / Decimal("2"),
        PER_SHARE_TOLERANCE,
    ):
        checks.append("share_scale_metamorphic")

    higher_wacc = request.model_copy(
        update={
            "assumptions": assumptions.model_copy(
                update={
                    "wacc": wacc.model_copy(
                        update={
                            "risk_free_rate": wacc.risk_free_rate + Decimal("0.005")
                        }
                    )
                }
            )
        }
    )
    if independent_calculate(higher_wacc).intrinsic_value >= baseline.intrinsic_value:
        checks.append("discount_rate_monotonicity")
    return tuple(checks)


@using_valuation_context
def mutation_findings(request: ValuationInputV1) -> tuple[str, ...]:
    """Ensure a one-unit mutation of critical outputs is caught by tolerances."""

    reference = independent_calculate(request)
    mutated = reference.node_map["enterprise_value"].value * Decimal("1.0001")
    if _within(
        mutated,
        reference.node_map["enterprise_value"].value,
        DEFAULT_CURRENCY_TOLERANCE,
    ):
        return ("enterprise_value:mutation_not_detected",)
    mutated_share = reference.per_share_value * Decimal("1.0001")
    if _within(mutated_share, reference.per_share_value, PER_SHARE_TOLERANCE):
        return ("per_share_value:mutation_not_detected",)
    return ()


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_cohort_manifest(path: Path) -> tuple[dict[str, Any], tuple[CohortCase, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "fundamental-verification-cohort-v1":
        raise ValueError("unsupported verification cohort schema")
    cases: list[CohortCase] = []
    for raw in payload.get("cases", []):
        cases.append(
            CohortCase(
                case_id=raw["case_id"],
                kind=raw["kind"],
                model_id=raw["model_id"],
                sector=raw["sector"],
                source_snapshot_id=raw["source_snapshot_id"],
                source_fixture=raw["source_fixture"],
                source_sha256=raw["source_sha256"],
                features=tuple(raw.get("features", ())),
                expected_refusal_code=raw.get("expected_refusal_code"),
                request_overrides=raw.get("request_overrides", {}),
            )
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("cohort case IDs must be unique")
    return payload, tuple(cases)


def request_for_case(manifest: Mapping[str, Any], case: CohortCase) -> ValuationInputV1:
    payload = _deep_merge(manifest["base_request"], case.request_overrides)
    payload["input_digest"] = None
    # JSON validation preserves the strict contract while applying its canonical
    # wire conversions for Decimal, datetime, tuple, and enum fields.
    request = ValuationInputV1.model_validate_json(json.dumps(payload))
    if request.model_id != case.model_id:
        raise ValueError(f"{case.case_id}: model_id does not match case metadata")
    if request.valuation_context.data_snapshot_id != case.source_snapshot_id:
        raise ValueError(f"{case.case_id}: source snapshot does not match request")
    return request.with_digest()


def verify_public_snapshot_bytes(
    cohort_path: Path, cases: tuple[CohortCase, ...]
) -> tuple[dict[str, Any], ...]:
    """Verify every case points to immutable local bytes with the declared hash."""

    capture_manifest_path = (
        cohort_path.parent / "../sec-edgar/capture_manifest.json"
    ).resolve()
    capture_payload = json.loads(capture_manifest_path.read_text(encoding="utf-8"))
    captured_by_path = {
        str(record["path"]): record for record in capture_payload.get("sources", ())
    }
    records: list[dict[str, Any]] = []
    for case in cases:
        path = (cohort_path.parent / case.source_fixture).resolve()
        if not path.is_file():
            raise ValueError(f"{case.case_id}: source fixture is unavailable: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != case.source_sha256:
            raise ValueError(f"{case.case_id}: source fixture hash mismatch")
        captured = captured_by_path.get(path.name)
        if captured is None or captured.get("sha256") != digest:
            raise ValueError(
                f"{case.case_id}: source is not in the SEC capture manifest"
            )
        records.append(
            {
                "snapshot_id": case.source_snapshot_id,
                "path": case.source_fixture,
                "sha256": digest,
                "available_at": captured["available_at"],
                "filed_at": captured.get("filed_at"),
                "accession_number": captured.get("accession_number"),
            }
        )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        unique[(record["snapshot_id"], record["sha256"])] = record
    return tuple(unique.values())


def report_digest(report: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(report)).hexdigest()


def make_report(
    *,
    cohort_id: str,
    source_records: tuple[dict[str, Any], ...],
    cases: tuple[dict[str, Any], ...],
    findings: tuple[str, ...],
    counts: Mapping[str, int],
    coverage_features: tuple[str, ...] = (),
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "fundamental-verification-report-v1",
        "cohort_id": cohort_id,
        "offline": True,
        "source_records": source_records,
        "counts": dict(counts),
        "cases": cases,
        "findings": findings,
        "feature_coverage": coverage_features,
        "release_decision": "pass" if not findings else "block",
        "coverage_boundaries": [
            "engineering cohort is not calibration evidence",
            "public SEC fixtures are replay evidence, not intrinsic-value truth",
        ],
        "challenger_tolerances": {
            "currency_absolute": "1",
            "currency_relative": "1e-9",
            "per_share_absolute": "0.000001",
            "per_share_relative": "1e-9",
        },
    }
    report["report_digest"] = report_digest(report)
    return report


__all__ = [
    "CohortCase",
    "DEFAULT_CURRENCY_TOLERANCE",
    "IndependentNode",
    "IndependentResult",
    "PER_SHARE_TOLERANCE",
    "VerificationRefusal",
    "compare_artifact",
    "independent_calculate",
    "invariant_findings",
    "load_cohort_manifest",
    "make_report",
    "mutation_findings",
    "property_findings",
    "request_for_case",
    "verify_public_snapshot_bytes",
]
