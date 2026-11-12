"""Explicit synthetic market inputs; these never establish source admission."""

from datetime import UTC, datetime
from decimal import Decimal

from fundamental_service.contracts import MarketPolicyEvidenceV1, MarketPolicyInputsV1
from fundamental_service.policies import (
    PolicyRecordV1,
    PolicyRegistry,
    initial_model_specs,
    initial_policy_records,
)
from fundamental_service.serialization import sha256_digest


def synthetic_market_inputs() -> MarketPolicyInputsV1:
    values = {
        "risk_free_rate": Decimal("0.046"),
        "beta": Decimal("1.1"),
        "equity_risk_premium": Decimal("0.05"),
        "pre_tax_cost_of_debt": Decimal("0.05"),
        "debt_weight": Decimal("0.2"),
        "equity_weight": Decimal("0.8"),
        "terminal_growth": Decimal("0.02"),
    }
    return MarketPolicyInputsV1(
        policy_version="synthetic-market-policy-v1",
        **values,
        evidence=tuple(
            MarketPolicyEvidenceV1(
                role=role,
                method="approved_policy",
                value=value,
                source_id="synthetic-market-policy",
                source_uri=f"urn:test:market:{role}",
                content_hash=sha256_digest({"synthetic": role, "value": value}),
                source_version="synthetic-market-policy-v1",
                terms_reference="urn:test:synthetic-only",
                as_of=datetime(2025, 1, 3, tzinfo=UTC),
                available_at=datetime(2025, 1, 3, tzinfo=UTC),
                captured_at=datetime(2026, 11, 3, tzinfo=UTC),
                rationale="Synthetic normative-policy fixture; no observed source is claimed",
            )
            for role, value in values.items()
        ),
    )


def synthetic_policy_registry() -> PolicyRegistry:
    policies = []
    for policy in initial_policy_records():
        payload = policy.model_dump(exclude={"policy_digest"})
        payload["market_inputs"] = synthetic_market_inputs()
        policies.append(PolicyRecordV1(**payload, policy_digest=sha256_digest(payload)))
    return PolicyRegistry(initial_model_specs(), policies)
