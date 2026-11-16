"""Explicit issuer adoption of industry reference assumptions, without valuation."""

from decimal import Decimal

from .contracts import (
    MarketPolicyEvidenceV1,
    MarketPolicyInputsV1,
    StrictModel,
    TraceV1,
)
from .market_reference_selection import (
    IssuerMarketReferenceSelectionV1,
    MarketReferenceSelectionError,
)
from .market_reference import ReferenceMetric
from .numerical_policy import using_valuation_context
from .serialization import sha256_digest

INDUSTRY_CAPITAL_ROLES = (
    "beta",
    "pre_tax_cost_of_debt",
    "debt_weight",
    "equity_weight",
)


class IndustryCapitalAssumptionsV1(StrictModel):
    reference_selection_digest: str
    values: dict[str, Decimal]
    traces: dict[str, TraceV1]
    output_digest: str


@using_valuation_context
def adopt_industry_capital(
    selection: IssuerMarketReferenceSelectionV1,
) -> IndustryCapitalAssumptionsV1:
    """Apply the pinned USD proxy rule, retaining the observed industry basis.

    This does not infer issuer classification, observed issuer beta, contracted
    borrowing cost or market capital weights. Weight normalization removes only
    bounded representation error from an otherwise coherent published pair.
    """
    if selection.plan.industry_capital_policy != "usd-industry-capital-proxy-v1":
        raise MarketReferenceSelectionError(
            "INDUSTRY_CAPITAL_POLICY_MISSING",
            "explicit industry proxy rule is required",
        )
    metrics: dict[str, ReferenceMetric] = {
        "beta": "industry.equity_beta",
        "pre_tax_cost_of_debt": "industry.pre_tax_cost_of_debt",
        "debt_weight": "industry.debt_weight",
        "equity_weight": "industry.equity_weight",
    }
    by_metric = {item.policy.metric: item for item in selection.selections}
    selected = {}
    for role, metric in metrics.items():
        item = by_metric.get(metric)
        if (
            item is None
            or item.status != "selected"
            or item.value is None
            or item.trace is None
            or item.policy.population != "us-companies"
        ):
            raise MarketReferenceSelectionError(
                "INDUSTRY_CAPITAL_SELECTION_REFUSED",
                f"industry proxy requires a selected U.S. industry row for {role}",
            )
        selected[role] = item
    basis = {
        (
            item.policy.subject,
            item.trace.source_refs[:1],
            item.trace.source_ids,
            item.trace.source_uris,
            item.trace.source_versions[:1],
            item.trace.terms_references,
            item.trace.as_of,
            item.trace.available_at,
            item.trace.captured_at,
        )
        for item in selected.values()
        if item.trace is not None
    }
    if len(basis) != 1:
        raise MarketReferenceSelectionError(
            "INDUSTRY_CAPITAL_BASIS_MISMATCH",
            "industry proxy metrics require one coherent original industry basis",
        )
    values = {role: item.value for role, item in selected.items()}
    assert all(value is not None for value in values.values())
    numeric = {role: value for role, value in values.items() if value is not None}
    total = numeric["debt_weight"] + numeric["equity_weight"]
    if abs(total - Decimal(1)) > Decimal("1e-12"):
        raise MarketReferenceSelectionError(
            "INDUSTRY_CAPITAL_WEIGHTS_INCONSISTENT",
            "published industry weights do not form a coherent capital pair",
        )
    numeric["debt_weight"] /= total
    numeric["equity_weight"] = Decimal(1) - numeric["debt_weight"]
    traces = {}
    for role, item in selected.items():
        assert item.trace is not None
        traces[role] = item.trace.model_copy(
            update={
                "expression": "normalize_published_industry_capital_pair"
                if role in {"debt_weight", "equity_weight"}
                else "adopt_published_industry_proxy",
                "inputs": tuple(
                    selected[x].output_digest for x in INDUSTRY_CAPITAL_ROLES
                )
                if role in {"debt_weight", "equity_weight"}
                else (item.output_digest,),
                "source_refs": tuple(
                    sorted(
                        {
                            *item.trace.source_refs,
                            *(x.output_digest for x in selected.values()),
                            selection.output_digest,
                            sha256_digest(selection.plan),
                        }
                    )
                ),
                "description": "Explicit USD industry capital proxy policy; "
                "not observed issuer beta, contracted borrowing cost or issuer "
                "market weights. Published weights normalize within 1e-12 tolerance.",
            }
        )
    payload = {
        "reference_selection_digest": selection.output_digest,
        "values": numeric,
        "traces": traces,
    }
    return IndustryCapitalAssumptionsV1(
        reference_selection_digest=selection.output_digest,
        values=numeric,
        traces=traces,
        output_digest=sha256_digest(payload),
    )


def industry_capital_evidence(
    assumptions: IndustryCapitalAssumptionsV1,
) -> tuple[MarketPolicyEvidenceV1, ...]:
    """Represent policy assumptions separately from observed industry cells."""
    evidence = []
    for role in INDUSTRY_CAPITAL_ROLES:
        trace = assumptions.traces[role]
        assert trace.as_of is not None
        assert trace.available_at is not None
        assert trace.captured_at is not None
        evidence.append(
            MarketPolicyEvidenceV1(
                role=role,
                method="approved_policy",
                value=assumptions.values[role],
                source_id="industry-capital:usd-industry-capital-proxy-v1",
                source_uri="urn:fundamental:industry-capital:"
                + assumptions.reference_selection_digest,
                content_hash=assumptions.output_digest,
                source_version="usd-industry-capital-proxy-v1",
                terms_reference="deployment-authorized-industry-capital-policy",
                as_of=trace.as_of,
                available_at=trace.available_at,
                captured_at=trace.captured_at,
                rationale=trace.description
                or "Explicit industry capital proxy assumption",
            )
        )
    return tuple(evidence)


def requires_industry_capital_plan(inputs: MarketPolicyInputsV1 | None) -> bool:
    return inputs is not None and any(
        item.source_id.startswith("industry-capital:")
        or item.source_uri.startswith("urn:fundamental:industry-capital:")
        for item in inputs.evidence
    )


def verify_industry_capital_policy(
    inputs: MarketPolicyInputsV1,
    selection: IssuerMarketReferenceSelectionV1 | None,
) -> dict[str, TraceV1]:
    """Serving and independent canary reproduce the same authorized assumptions."""
    if selection is None or selection.plan.industry_capital_policy is None:
        if requires_industry_capital_plan(inputs):
            raise MarketReferenceSelectionError(
                "INDUSTRY_CAPITAL_PLAN_MISSING",
                "industry capital policy requires its plan",
            )
        return {}
    assumptions = adopt_industry_capital(selection)
    actual = {item.role: item for item in inputs.evidence}
    if inputs.capital_weight_basis != "approved_policy" or any(
        actual[item.role] != item or getattr(inputs, item.role) != item.value
        for item in industry_capital_evidence(assumptions)
    ):
        raise MarketReferenceSelectionError(
            "INDUSTRY_CAPITAL_POLICY_SOURCE_MISMATCH",
            "industry capital policy differs from reproduced proxy assumptions",
        )
    return assumptions.traces
