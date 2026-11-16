"""Conditional disclosed-pool dilution bounds, without release authority."""

from datetime import date
from decimal import Decimal, DecimalException, ROUND_CEILING, ROUND_FLOOR, localcontext
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .arelle_parser import ParsedXbrlFactV1
from .contracts import StrictModel
from .numerical_policy import using_valuation_context
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import sha256_digest

OPTION_POOL_BOUND_POLICY: Literal["disclosed-option-pool-nonnegative-envelope-v1"] = (
    "disclosed-option-pool-nonnegative-envelope-v1"
)
QUANTITY_CONCEPT = "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber"
AVERAGE_STRIKE_CONCEPT = "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice"


class OptionPoolScenarioV1(StrictModel):
    scenario_id: str = Field(min_length=1)
    hypothetical_price: Decimal = Field(gt=0, allow_inf_nan=False)
    assumed_compensation_upper_bound: Decimal | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    compensation_assumption_rationale: str | None = Field(default=None, min_length=40)

    @model_validator(mode="after")
    def assumption_is_explained(self) -> "OptionPoolScenarioV1":
        if (self.assumed_compensation_upper_bound is None) != (
            self.compensation_assumption_rationale is None
        ):
            raise ValueError("a compensation assumption requires its rationale")
        return self


class OptionPoolResearchRequestV1(StrictModel):
    protocol: Literal["option-pool-research-v1"] = "option-pool-research-v1"
    original: OriginalIssuerEvidenceV1
    period_end: date
    quantity_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    average_strike_fact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    instrument_assumption: Literal["one_share_nonnegative_strike_treasury_stock"]
    instrument_assumption_rationale: str = Field(min_length=40)
    assumed_average_strike_error: Decimal = Field(ge=0, allow_inf_nan=False)
    strike_error_rationale: str = Field(min_length=40)
    scenarios: tuple[OptionPoolScenarioV1, ...] = Field(min_length=1, max_length=100)

    @field_validator("scenarios")
    @classmethod
    def canonical_scenarios(
        cls, values: tuple[OptionPoolScenarioV1, ...]
    ) -> tuple[OptionPoolScenarioV1, ...]:
        if len({value.scenario_id for value in values}) != len(values):
            raise ValueError("scenario identities must be unique")
        return tuple(sorted(values, key=lambda value: value.scenario_id))


class OptionPoolBoundV1(StrictModel):
    scenario: OptionPoolScenarioV1
    incremental_shares_lower: Decimal
    incremental_shares_upper: Decimal


class OptionPoolResearchReportV1(StrictModel):
    protocol: Literal["option-pool-research-report-v1"] = (
        "option-pool-research-report-v1"
    )
    policy_version: Literal["disclosed-option-pool-nonnegative-envelope-v1"] = (
        OPTION_POOL_BOUND_POLICY
    )
    numerical_policy: Literal["decimal-50-outward-envelope-v1"] = (
        "decimal-50-outward-envelope-v1"
    )
    status: Literal["provisional_conditional_bounds", "abstained"]
    scope: Literal["disclosed_pool_only"] = "disclosed_pool_only"
    complete_inventory: Literal[False] = False
    supported_history_threshold: None = None
    input_digest: str
    original_evidence_digest: str
    source_content_hash: str
    parser_input_hash: str
    accession_number: str
    selected_fact_digests: tuple[str, ...]
    observations: tuple[ParsedXbrlFactV1, ...]
    bounds: tuple[OptionPoolBoundV1, ...]
    issue_codes: tuple[str, ...]
    unestablished_claims: tuple[str, ...] = (
        "complete_award_inventory",
        "exact_strike_distribution",
        "compensation_allocation",
        "security_identity",
        "source_use_permission",
        "mapping_review",
        "capital_claim_completeness",
        "data_release_authority",
        "caller_approval",
        "issuer_valuation",
    )

    @property
    def output_digest(self) -> str:
        return sha256_digest(self)


class _ResearchRefusal(ValueError):
    pass


def _select_observation(
    request: OptionPoolResearchRequestV1, concept: str, digest: str, unit: str
) -> ParsedXbrlFactV1:
    original = request.original
    matches = tuple(
        fact
        for fact in original.report.facts
        if fact.concept == concept and fact.instant == request.period_end
    )
    selected = next((fact for fact in matches if sha256_digest(fact) == digest), None)
    if selected is None:
        raise _ResearchRefusal("OPTION_POOL_OBSERVATION_MISSING")
    for fact in matches:
        if (
            not fact.is_numeric
            or fact.unit != unit
            or fact.period_start is not None
            or fact.period_end is not None
            or fact.dimensions
            or fact.consolidation_scope != "consolidated"
            or fact.security_scope not in {"issuer", "consolidated", "unspecified"}
            or fact.entity_scheme != "http://www.sec.gov/CIK"
            or (fact.entity_identifier or "").lstrip("0")
            != original.source.cik.lstrip("0")
            or re.fullmatch(
                r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?",
                fact.namespace_uri or "",
            )
            is None
        ):
            raise _ResearchRefusal("OPTION_POOL_OBSERVATION_SCOPE_INVALID")
        try:
            value = Decimal(fact.value)
            if not value.is_finite() or value < 0:
                raise _ResearchRefusal("OPTION_POOL_OBSERVATION_INVALID")
        except DecimalException as error:
            raise _ResearchRefusal("OPTION_POOL_OBSERVATION_INVALID") from error
    if len({(Decimal(fact.value), fact.decimals) for fact in matches}) != 1:
        raise _ResearchRefusal("OPTION_POOL_OBSERVATION_CONFLICT")
    return selected


@using_valuation_context
def research_option_pool_bounds(
    request: OptionPoolResearchRequestV1,
) -> OptionPoolResearchReportV1:
    """Bound one disclosed pool under explicit assumptions; never an exact valuation.

    For nonnegative strikes/compensation, sum(max(0, n_i - proceeds_i/P))
    lies between max(0, N - total_proceeds/P) and N. Missing compensation
    leaves the lower bound at zero. The upper bound need not be attainable.
    """
    original = request.original
    observations: tuple[ParsedXbrlFactV1, ...] = ()
    bounds: tuple[OptionPoolBoundV1, ...] = ()
    codes: tuple[str, ...] = ()
    try:
        if (
            original.status != "matched"
            or original.identity is None
            or original.source.available_at > original.decision_at
            or original.report_period_end is None
            or request.period_end > original.report_period_end
        ):
            raise _ResearchRefusal("OPTION_POOL_ORIGINAL_UNAVAILABLE")
        quantity = _select_observation(
            request, QUANTITY_CONCEPT, request.quantity_fact_digest, "xbrli:shares"
        )
        average = _select_observation(
            request,
            AVERAGE_STRIKE_CONCEPT,
            request.average_strike_fact_digest,
            f"iso4217:{original.identity.currency}/xbrli:shares",
        )
        observations = (quantity, average)
        count = Decimal(quantity.value)
        if (
            count != count.to_integral_value()
            or (
                quantity.decimals != "INF"
                and re.fullmatch(r"[0-9]+", quantity.decimals or "") is None
            )
            or quantity.namespace_uri != average.namespace_uri
        ):
            raise _ResearchRefusal("OPTION_POOL_WHOLE_COUNT_UNESTABLISHED")
        if average.decimals != "INF":
            if (
                average.decimals is None
                or re.fullmatch(r"-?[0-9]{1,6}", average.decimals) is None
            ):
                raise _ResearchRefusal("OPTION_POOL_STRIKE_PRECISION_UNKNOWN")
            half_unit = Decimal(5).scaleb(-int(average.decimals) - 1)
            if request.assumed_average_strike_error < half_unit:
                raise _ResearchRefusal("OPTION_POOL_STRIKE_ERROR_TOO_SMALL")
        rows = []
        for scenario in request.scenarios:
            lower = Decimal(0)
            if scenario.assumed_compensation_upper_bound is not None:
                # Round proceeds up, then the remaining share count down.
                with localcontext() as context:
                    context.rounding = ROUND_CEILING
                    strike_upper = (
                        Decimal(average.value) + request.assumed_average_strike_error
                    )
                    proceeds_upper = (
                        count * strike_upper + scenario.assumed_compensation_upper_bound
                    )
                    repurchased_upper = proceeds_upper / scenario.hypothetical_price
                    context.rounding = ROUND_FLOOR
                    lower = max(Decimal(0), count - repurchased_upper)
            rows.append(
                OptionPoolBoundV1(
                    scenario=scenario,
                    incremental_shares_lower=lower,
                    incremental_shares_upper=count,
                )
            )
        bounds = tuple(rows)
    except _ResearchRefusal as error:
        codes = (str(error),)
    except DecimalException:
        codes = ("OPTION_POOL_NUMERICAL_RANGE_UNSUPPORTED",)
    return OptionPoolResearchReportV1(
        status="abstained" if codes else "provisional_conditional_bounds",
        input_digest=sha256_digest(request),
        original_evidence_digest=original.output_digest,
        source_content_hash=original.source.content_hash,
        parser_input_hash=original.source.parser_input_hash,
        accession_number=original.source.accession_number,
        selected_fact_digests=(
            request.quantity_fact_digest,
            request.average_strike_fact_digest,
        ),
        observations=observations,
        bounds=bounds,
        issue_codes=codes,
    )
