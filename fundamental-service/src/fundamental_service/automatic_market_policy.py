"""Assemble approved market inputs from retained, point-in-time evidence.

The evaluator composes existing source-neutral selectors and the #352 input
contract. It contains no valuation formula and has no concrete source client.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import MarketPolicyEvidenceV1, MarketPolicyInputsV1, TraceV1
from .industry_capital import adopt_industry_capital, industry_capital_evidence
from .issuer_market_policy_plan import IssuerMarketReferencePlanDecisionV1
from .market_reference_selection import (
    IssuerMarketReferenceSelectionV1,
    MarketReferenceSelectionError,
    select_issuer_market_references,
)
from .market_source_selection import (
    DailyMarketRatePolicyV1,
    MarketSourceError,
    select_market_rate,
)
from .serialization import sha256_digest
from .snapshots import SnapshotError
from .source_admission import SourceAdmissionV1
from .terminal_growth import (
    TerminalGrowthPlanV1,
    TerminalGrowthSelectionV1,
    select_terminal_growth,
    terminal_growth_evidence,
)


class AutomaticMarketPolicyPolicyV1(BaseModel):
    """Versioned assembly policy with injectable rate and reference sources."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    risk_free_policy: DailyMarketRatePolicyV1
    terminal_growth_plan: TerminalGrowthPlanV1

    @model_validator(mode="after")
    def terminal_context_matches(self) -> AutomaticMarketPolicyPolicyV1:
        if self.terminal_growth_plan.currency != self.currency:
            raise ValueError("market policy currency differs from terminal policy")
        if self.terminal_growth_plan.risk_free_policy != self.risk_free_policy:
            raise ValueError("terminal policy must use the approved risk-free policy")
        return self


class AutomaticMarketPolicyDecisionV1(BaseModel):
    """A complete market policy or stable refusal with all selection digests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["automatic-market-policy-v1"] = "automatic-market-policy-v1"
    policy: AutomaticMarketPolicyPolicyV1
    issuer_id: str = Field(min_length=1)
    valuation_at: datetime
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["approved", "refused"]
    issue_codes: tuple[str, ...]
    reference_selection: IssuerMarketReferenceSelectionV1 | None = None
    terminal_selection: TerminalGrowthSelectionV1 | None = None
    reference_selection_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    terminal_selection_digest: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    inputs: MarketPolicyInputsV1 | None = None
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_decision(self) -> AutomaticMarketPolicyDecisionV1:
        if self.valuation_at.tzinfo is None or self.valuation_at.utcoffset() is None:
            raise ValueError("automatic market policy requires a valuation timezone")
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("automatic market policy issues are not canonical")
        if self.status == "approved" and (self.issue_codes or self.inputs is None):
            raise ValueError("approved market policy requires complete inputs")
        if self.status == "approved" and (
            self.reference_selection is None or self.terminal_selection is None
        ):
            raise ValueError("approved market policy requires selection evidence")
        if self.status == "refused" and (
            self.inputs is not None or not self.issue_codes
        ):
            raise ValueError("refused market policy requires issues without inputs")
        if (self.reference_selection is None) != (
            self.reference_selection_digest is None
        ) or (
            self.reference_selection is not None
            and self.reference_selection.output_digest
            != self.reference_selection_digest
        ):
            raise ValueError("market policy reference selection digest is inconsistent")
        if (self.terminal_selection is None) != (
            self.terminal_selection_digest is None
        ) or (
            self.terminal_selection is not None
            and self.terminal_selection.output_digest != self.terminal_selection_digest
        ):
            raise ValueError("market policy terminal selection digest is inconsistent")
        if self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError(
                "automatic market policy output digest differs from content"
            )
        return self


def _evidence(
    *,
    role: str,
    value: Decimal,
    method: Literal["observed_source", "approved_policy"],
    trace: TraceV1,
    rationale: str,
) -> MarketPolicyEvidenceV1:
    if not trace.source_ids or not trace.source_uris or not trace.source_refs:
        raise ValueError("observed policy evidence requires a source trace")
    if trace.as_of is None or trace.available_at is None or trace.captured_at is None:
        raise ValueError("observed policy evidence requires complete timestamps")
    return MarketPolicyEvidenceV1(
        role=role,
        method=method,
        value=value,
        source_id=trace.source_ids[0],
        source_uri=trace.source_uris[0],
        content_hash=trace.source_refs[0],
        source_version=trace.source_versions[0],
        terms_reference=trace.terms_references[0],
        as_of=trace.as_of,
        available_at=trace.available_at,
        captured_at=trace.captured_at,
        rationale=rationale,
    )


def evaluate_automatic_market_policy(
    plan_decision: IssuerMarketReferencePlanDecisionV1,
    *,
    policy: AutomaticMarketPolicyPolicyV1,
    admissions: tuple[SourceAdmissionV1, ...],
    expected: AutomaticMarketPolicyDecisionV1 | None = None,
) -> AutomaticMarketPolicyDecisionV1:
    """Select and assemble all seven #352 market-policy roles deterministically."""

    plan_decision = IssuerMarketReferencePlanDecisionV1.model_validate_json(
        plan_decision.model_dump_json()
    )
    policy = AutomaticMarketPolicyPolicyV1.model_validate_json(policy.model_dump_json())
    ordered_admissions = tuple(
        sorted(
            {item.output_digest: item for item in admissions}.values(),
            key=lambda item: item.output_digest,
        )
    )
    issuer_id = plan_decision.issuer_id
    valuation_at = plan_decision.valuation_at
    if (
        policy.terminal_growth_plan.issuer_id != issuer_id
        or policy.terminal_growth_plan.valuation_at != valuation_at
    ):
        context_issue = "TERMINAL_POLICY_CONTEXT_MISMATCH"
    else:
        context_issue = None
    input_payload = {
        "plan_decision": plan_decision,
        "policy": policy,
        "admissions": ordered_admissions,
    }
    input_digest = sha256_digest(input_payload)
    issues = set(plan_decision.issue_codes)
    if context_issue is not None:
        issues.add(context_issue)
    if plan_decision.status != "planned" or plan_decision.plan is None:
        issues.add("ISSUER_MARKET_REFERENCE_PLAN_REFUSED")
    elif (
        plan_decision.plan.issuer_id != issuer_id
        or plan_decision.plan.valuation_at != valuation_at
    ):
        issues.add("ISSUER_MARKET_REFERENCE_PLAN_CONTEXT_MISMATCH")
    elif policy.terminal_growth_plan.policy_id != plan_decision.plan.policy_id:
        issues.add("TERMINAL_POLICY_CONTEXT_MISMATCH")
    elif policy.currency != "USD":
        issues.add("INDUSTRY_CAPITAL_CURRENCY_UNSUPPORTED")
    required_metrics = {
        "country.equity_risk_premium",
        "industry.equity_beta",
        "industry.pre_tax_cost_of_debt",
        "industry.debt_weight",
        "industry.equity_weight",
    }
    if plan_decision.plan is not None and not required_metrics <= {
        item.metric for item in plan_decision.plan.selections
    }:
        issues.add("ISSUER_MARKET_REFERENCE_PLAN_ROLES_INCOMPLETE")
    reference_selection: IssuerMarketReferenceSelectionV1 | None = None
    terminal_selection: TerminalGrowthSelectionV1 | None = None
    inputs: MarketPolicyInputsV1 | None = None
    if not issues:
        assert plan_decision.plan is not None
        try:
            reference_selection = select_issuer_market_references(
                plan_decision.plan, admissions=ordered_admissions
            )
            if reference_selection.status != "selected":
                issues.update(reference_selection.issue_codes)
                issues.add("ISSUER_MARKET_REFERENCE_SELECTION_REFUSED")
        except MarketReferenceSelectionError as error:
            issues.add(error.code)
        except ValueError:
            issues.add("ISSUER_MARKET_REFERENCE_SELECTION_FAILED")
    if not issues:
        assert reference_selection is not None
        try:
            capital = adopt_industry_capital(reference_selection)
            terminal_selection = select_terminal_growth(
                policy.terminal_growth_plan, admissions=ordered_admissions
            )
            rate = select_market_rate(
                ordered_admissions,
                policy=policy.risk_free_policy,
                valuation_at=valuation_at,
                currency=policy.currency,
            )
            erp = next(
                item
                for item in reference_selection.selections
                if item.policy.metric == "country.equity_risk_premium"
            )
            assert erp.value is not None and erp.trace is not None
            capital_evidence = industry_capital_evidence(capital)
            evidence = (
                _evidence(
                    role="risk_free_rate",
                    value=rate.value,
                    method="observed_source",
                    trace=rate.trace,
                    rationale="Latest eligible risk-free observation under the injected source policy.",
                ),
                _evidence(
                    role="equity_risk_premium",
                    value=erp.value,
                    method="observed_source",
                    trace=erp.trace,
                    rationale="Exact country reference row selected from the issuer/date plan.",
                ),
                *capital_evidence,
                terminal_growth_evidence(terminal_selection),
            )
            inputs = MarketPolicyInputsV1(
                policy_version=policy.policy_version,
                capital_weight_basis="approved_policy",
                risk_free_rate=rate.value,
                beta=capital.values["beta"],
                equity_risk_premium=erp.value,
                pre_tax_cost_of_debt=capital.values["pre_tax_cost_of_debt"],
                debt_weight=capital.values["debt_weight"],
                equity_weight=capital.values["equity_weight"],
                terminal_growth=terminal_selection.value,
                evidence=tuple(sorted(evidence, key=lambda item: item.role)),
            )
        except (MarketSourceError, MarketReferenceSelectionError) as error:
            issues.add(error.code)
        except (ValueError, StopIteration):
            issues.add("ISSUER_MARKET_POLICY_ASSEMBLY_FAILED")

    payload = {
        "protocol": "automatic-market-policy-v1",
        "policy": policy,
        "issuer_id": issuer_id,
        "valuation_at": valuation_at,
        "plan_digest": plan_decision.output_digest,
        "input_digest": input_digest,
        "status": "refused" if issues else "approved",
        "issue_codes": tuple(sorted(issues)),
        "reference_selection": reference_selection,
        "terminal_selection": terminal_selection,
        "reference_selection_digest": (
            reference_selection.output_digest if reference_selection else None
        ),
        "terminal_selection_digest": (
            terminal_selection.output_digest if terminal_selection else None
        ),
        "inputs": inputs,
    }
    result = AutomaticMarketPolicyDecisionV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )
    if expected is not None and result != expected:
        raise SnapshotError(
            "AUTOMATIC_MARKET_POLICY_REPLAY_MISMATCH",
            "automatic market policy differs from retained replay",
        )
    return result
