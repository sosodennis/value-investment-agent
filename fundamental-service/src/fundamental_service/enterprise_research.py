"""Conditional enterprise research using the formal composer and DCF subgraph."""

from decimal import Decimal, DecimalException
from typing import Literal

from pydantic import Field, field_validator

from .contracts import (
    CalculationNodeV1,
    CanonicalFactV1,
    QualityStatus,
    SourceSnapshotV1,
    StrictModel,
    WaccAssumptionsV1,
)
from .enterprise_projection import project_enterprise_nodes
from .numerical_policy import VALUATION_NUMERICAL_POLICY, using_valuation_context
from .operating_forecast import OperatingForecastV2, prepare_operating_forecast
from .operating_projection import OperatingProjectionError, resolve_operating_model
from .original_issuer import IssuerOperatingSourceV1
from .serialization import canonical_bytes, sha256_digest
from .valuation_preparation import ApprovedMarketPolicyInputsV1
from .working_capital import (
    CompositeWorkingCapitalInputV1,
    canonical_working_capital_inputs,
)


class EnterpriseDiscountScenarioV1(StrictModel):
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    market_policy: ApprovedMarketPolicyInputsV1
    rationale: str = Field(min_length=40)
    evidence_digests: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_digests")
    @classmethod
    def canonical_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in values
        ):
            raise ValueError("scenario evidence requires content digests")
        return tuple(sorted(set(values)))


class EnterpriseResearchRequestV1(StrictModel):
    protocol: Literal["conditional-enterprise-research-v1"] = (
        "conditional-enterprise-research-v1"
    )
    facts: tuple[CanonicalFactV1, ...]
    snapshot: SourceSnapshotV1 | IssuerOperatingSourceV1
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    data_release_manifest_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    history_window_years: Literal[3, 4, 5] | None = None
    working_capital_inputs: tuple[CompositeWorkingCapitalInputV1, ...] = ()
    scenarios: tuple[EnterpriseDiscountScenarioV1, ...] = Field(
        min_length=1, max_length=100
    )

    @field_validator("facts")
    @classmethod
    def canonical_facts(
        cls, values: tuple[CanonicalFactV1, ...]
    ) -> tuple[CanonicalFactV1, ...]:
        return tuple(
            sorted(values, key=lambda fact: (fact.fact_id, sha256_digest(fact)))
        )

    @field_validator("working_capital_inputs")
    @classmethod
    def canonical_working_capital(
        cls, values: tuple[CompositeWorkingCapitalInputV1, ...]
    ) -> tuple[CompositeWorkingCapitalInputV1, ...]:
        return canonical_working_capital_inputs(values)

    @field_validator("scenarios")
    @classmethod
    def canonical_scenarios(
        cls, values: tuple[EnterpriseDiscountScenarioV1, ...]
    ) -> tuple[EnterpriseDiscountScenarioV1, ...]:
        if len({value.scenario_id for value in values}) != len(values):
            raise ValueError("scenario identities must be unique")
        return tuple(sorted(values, key=lambda value: value.scenario_id))


class EnterpriseScenarioResultV1(StrictModel):
    scenario: EnterpriseDiscountScenarioV1
    status: Literal["provisional_conditional_enterprise_value", "abstained"]
    enterprise_value: Decimal | None
    nodes: tuple[CalculationNodeV1, ...]
    issue_codes: tuple[str, ...]


class EnterpriseResearchReportV1(StrictModel):
    protocol: Literal["conditional-enterprise-research-report-v1"] = (
        "conditional-enterprise-research-report-v1"
    )
    scope: Literal["conditional_enterprise_value_only"] = (
        "conditional_enterprise_value_only"
    )
    numerical_policy: str = VALUATION_NUMERICAL_POLICY
    input_digest: str
    model_spec_digest: str
    operating_forecast: OperatingForecastV2
    results: tuple[EnterpriseScenarioResultV1, ...]
    supported_history_threshold: None = None
    unestablished_claims: tuple[str, ...] = (
        "market_policy_authority",
        "mapping_or_release_authentication",
        "model_suitability",
        "capital_claim_completeness",
        "complete_award_inventory",
        "quote_entitlement",
        "common_equity_value",
        "per_share_value",
        "caller_approval",
        "validated_history_threshold",
    )

    @property
    def output_digest(self) -> str:
        return sha256_digest(self)


@using_valuation_context
def research_enterprise_value(
    request: EnterpriseResearchRequestV1,
) -> EnterpriseResearchReportV1:
    """Recompose operating evidence; scenarios never authorize a full valuation."""
    request = EnterpriseResearchRequestV1.model_validate_json(canonical_bytes(request))
    model = resolve_operating_model(request.model_id, request.model_version)
    operating = prepare_operating_forecast(
        request.facts,
        snapshot=request.snapshot,
        model_id=request.model_id,
        model_version=request.model_version,
        policy_id=request.policy_id,
        policy_version=request.policy_version,
        mapping_version=request.mapping_version,
        data_release_manifest_digest=request.data_release_manifest_digest,
        history_window_years=request.history_window_years,
        working_capital_inputs=request.working_capital_inputs,
    )
    results = []
    for scenario in request.scenarios:
        codes = {*operating.issue_codes, "ENTERPRISE_SCENARIO_ASSUMPTIONS_UNREVIEWED"}
        nodes: tuple[CalculationNodeV1, ...] = ()
        enterprise = None
        if (
            operating.quality_status is QualityStatus.ABSTAIN
            or operating.forecast is None
            or operating.tax_rate is None
        ):
            codes.add("ENTERPRISE_OPERATING_INPUTS_UNAVAILABLE")
        else:
            policy = scenario.market_policy
            traces = tuple(policy.evidence.values())
            if any(
                trace.as_of is None or trace.available_at is None for trace in traces
            ):
                codes.add("ENTERPRISE_SCENARIO_EVIDENCE_UNDATED")
            elif any(
                value is not None and value > request.snapshot.valuation_timestamp
                for trace in traces
                for value in (trace.as_of, trace.available_at)
            ):
                codes.add("ENTERPRISE_SCENARIO_EVIDENCE_FUTURE")
            else:
                try:
                    wacc = WaccAssumptionsV1.model_validate(
                        {
                            **policy.model_dump(
                                include=set(WaccAssumptionsV1.model_fields)
                            ),
                            "tax_rate": operating.tax_rate,
                        }
                    )
                    assert policy.terminal_growth is not None
                    projected = project_enterprise_nodes(
                        operating.forecast,
                        wacc=wacc,
                        terminal_growth=policy.terminal_growth,
                        historical_fact_ids=operating.selected_fact_ids,
                    )
                    cost_equity = projected[0].value
                    assert cost_equity is not None
                    if policy.terminal_growth >= cost_equity:
                        codes.add("TERMINAL_GROWTH_NOT_BELOW_DISCOUNT_RATE")
                    else:
                        nodes = projected
                        enterprise = nodes[-1].value
                except OperatingProjectionError as error:
                    codes.add(error.code)
                except (DecimalException, ValueError):
                    codes.add("ENTERPRISE_SCENARIO_NUMERICAL_INPUT_INVALID")
        results.append(
            EnterpriseScenarioResultV1(
                scenario=scenario,
                status="provisional_conditional_enterprise_value"
                if enterprise is not None
                else "abstained",
                enterprise_value=enterprise,
                nodes=nodes,
                issue_codes=tuple(sorted(codes)),
            )
        )
    return EnterpriseResearchReportV1(
        input_digest=sha256_digest(request),
        model_spec_digest=sha256_digest(model),
        operating_forecast=operating,
        results=tuple(results),
    )
