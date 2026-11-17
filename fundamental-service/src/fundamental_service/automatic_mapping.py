"""Deterministic approval of narrowly defined, source-bound US GAAP mappings."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .arelle_parser import ParsedXbrlFactV1
from .automatic_mapping_disclosures import (
    select_option_compensation_disclosure,
    select_stock_compensation_disclosure,
    STOCK_COMPENSATION_DISCLOSURE,
)
from .contracts import IdentityV1, SecIntegrityEvidenceV1
from .data_releases import (
    ArtifactRefV1,
    AutomaticMappingApprovalV1,
    DataReleaseError,
    ReleaseModel,
)
from .facts import CanonicalMappingV1, MappingObservationScopeV1, select_fact
from .automatic_mapping_evidence import AutomaticMappingEvidenceChecks
from .parser_action_evidence import require_current_parser_action_refs
from .mapping_computation import (
    MappingComputationIdentityV1,
    mapping_computation_digest,
)
from .original_issuer import OriginalIssuerEvidenceV1
from .registered_capital_expenditure import (
    CAPITAL_EXPENDITURE,
    select_registered_capital_expenditure,
)
from .registered_depreciation import (
    ADJUSTED_DEPRECIATION,
    DEPRECIATION,
    FIXED_ASSET_DEPRECIATION,
    registered_depreciation_concept,
    select_registered_depreciation,
)
from .registered_investment_assets import (
    investment_asset_concept,
    ROLES as INVESTMENT_ASSET_ROLES,
    select_registered_investment_assets,
)
from .registered_noncontrolling_equity import (
    NONCONTROLLING_EQUITY,
    select_registered_noncontrolling_equity,
)
from .registered_liability_residuals import (
    liability_residual_concept,
    ROLES as LIABILITY_RESIDUAL_ROLES,
    select_registered_liability_residual,
)
from .registered_revenue import (
    CONTRACT_REVENUE,
    registered_revenue_concept,
    select_registered_revenue,
)
from .mapping_input_storage import MappingInputReader, resolve_mapping_input
from .serialization import sha256_digest
from .sec_rebuild import parsed_facts_to_candidates
from .snapshots import SnapshotError
from .standard_accounting_representations import standard_accounting_representation

AUTOMATIC_MAPPING_INPUT_ROLE = "automatic-mapping-input-v1"
AutomaticMappingPolicyVersion = Literal["source-bound-us-gaap-v42"]
AUTOMATIC_MAPPING_POLICY: AutomaticMappingPolicyVersion = "source-bound-us-gaap-v42"
_GAAP_NAMESPACE = re.compile(
    r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?"
)


@dataclass(frozen=True)
class DirectMappingRule:
    concept: str
    period: Literal["annual", "instant"]
    unit: Literal[
        "iso4217:USD",
        "xbrli:shares",
        "iso4217:USD/xbrli:shares",
    ] = "iso4217:USD"
    alternative_concepts: tuple[str, ...] = ()
    namespace_uris: tuple[str, ...] = ()
    nonnegative: bool = False

    @property
    def concepts(self) -> tuple[str, ...]:
        return (self.concept, *self.alternative_concepts)


# Partial revenue tags, absence claims and arbitrary computed partitions have no
# direct rule. Award rules cover only the registered option-outstanding facts;
# they do not establish complete inventory. Aggregate D&A and cash capex require
# registered scope. Every rule change changes the policy digest.
_RULES = {
    "revenue": DirectMappingRule(
        "us-gaap:Revenues", "annual", alternative_concepts=("us-gaap:SalesRevenueNet",)
    ),
    "cost_of_revenue": DirectMappingRule("us-gaap:CostOfRevenue", "annual"),
    "depreciation_and_amortization": DirectMappingRule(DEPRECIATION, "annual"),
    "operating_income": DirectMappingRule("us-gaap:OperatingIncomeLoss", "annual"),
    "income_before_tax": DirectMappingRule(
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "annual",
    ),
    "income_tax_expense": DirectMappingRule(
        "us-gaap:IncomeTaxExpenseBenefit", "annual"
    ),
    "net_income": DirectMappingRule("us-gaap:NetIncomeLoss", "annual"),
    "capital_expenditure": DirectMappingRule(CAPITAL_EXPENDITURE, "annual"),
    "operating_lease_cost": DirectMappingRule("us-gaap:OperatingLeaseCost", "annual"),
    "basic_weighted_average_shares": DirectMappingRule(
        "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
        "annual",
        "xbrli:shares",
    ),
    "diluted_weighted_average_shares": DirectMappingRule(
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
        "annual",
        "xbrli:shares",
    ),
    "operating_current_receivables": DirectMappingRule(
        "us-gaap:AccountsReceivableNetCurrent", "instant"
    ),
    "current_assets": DirectMappingRule("us-gaap:AssetsCurrent", "instant"),
    "current_liabilities": DirectMappingRule("us-gaap:LiabilitiesCurrent", "instant"),
    "inventory": DirectMappingRule("us-gaap:InventoryNet", "instant"),
    "operating_current_payables": DirectMappingRule(
        "us-gaap:AccountsPayableCurrent", "instant"
    ),
    "cash_and_equivalents": DirectMappingRule(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue", "instant"
    ),
    "cash_and_short_term_investments": DirectMappingRule(
        "us-gaap:CashCashEquivalentsAndShortTermInvestments",
        "instant",
        namespace_uris=(
            "http://fasb.org/us-gaap/2023",
            "http://fasb.org/us-gaap/2024",
            "http://fasb.org/us-gaap/2025",
            "http://fasb.org/us-gaap/2026",
        ),
        nonnegative=True,
    ),
    "long_term_interest_bearing_debt": DirectMappingRule(
        "us-gaap:LongTermDebtNoncurrent",
        "instant",
        namespace_uris=(
            "http://fasb.org/us-gaap/2023",
            "http://fasb.org/us-gaap/2024",
            "http://fasb.org/us-gaap/2025",
            "http://fasb.org/us-gaap/2026",
        ),
        nonnegative=True,
    ),
    "current_operating_lease_liabilities": DirectMappingRule(
        "us-gaap:OperatingLeaseLiabilityCurrent", "instant"
    ),
    "long_term_operating_lease_liabilities": DirectMappingRule(
        "us-gaap:OperatingLeaseLiabilityNoncurrent", "instant"
    ),
    "current_finance_lease_liabilities": DirectMappingRule(
        "us-gaap:FinanceLeaseLiabilityCurrent",
        "instant",
        namespace_uris=(
            "http://fasb.org/us-gaap/2023",
            "http://fasb.org/us-gaap/2024",
            "http://fasb.org/us-gaap/2025",
            "http://fasb.org/us-gaap/2026",
        ),
        nonnegative=True,
    ),
    "long_term_finance_lease_liabilities": DirectMappingRule(
        "us-gaap:FinanceLeaseLiabilityNoncurrent",
        "instant",
        namespace_uris=(
            "http://fasb.org/us-gaap/2023",
            "http://fasb.org/us-gaap/2024",
            "http://fasb.org/us-gaap/2025",
            "http://fasb.org/us-gaap/2026",
        ),
        nonnegative=True,
    ),
    "common_shares_outstanding": DirectMappingRule(
        "us-gaap:CommonStockSharesOutstanding", "instant", "xbrli:shares"
    ),
    "equity_award_quantity": DirectMappingRule(
        "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber",
        "instant",
        "xbrli:shares",
    ),
    "equity_award_exercise_price": DirectMappingRule(
        "us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice",
        "instant",
        "iso4217:USD/xbrli:shares",
    ),
}


def automatic_mapping_policy_digest() -> str:
    """Pin executable policy dependencies as well as the explicit rule table."""
    root = Path(__file__).parent
    return sha256_digest(
        {
            "policy_version": AUTOMATIC_MAPPING_POLICY,
            "rules": {key: asdict(rule) for key, rule in sorted(_RULES.items())},
            "sources": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in (
                    "automatic_mapping.py",
                    "automatic_mapping_evidence.py",
                    "automatic_mapping_batch.py",
                    "automatic_mapping_runner.py",
                    "mapping_input_storage.py",
                    "mapping_input_identity.py",
                    "automatic_source_mapping.py",
                    "preparation_runner.py",
                    "source_plan_contracts.py",
                    "automatic_mapping_disclosures.py",
                    "registered_depreciation.py",
                    "registered_capital_expenditure.py",
                    "registered_revenue.py",
                    "registered_investment_assets.py",
                    "registered_noncontrolling_equity.py",
                    "registered_liability_residuals.py",
                    "lease_liability_mapping.py",
                    "accounting_roles.py",
                    "arelle_parser.py",
                    "parser_action_contracts.py",
                    "parser_action_identity.py",
                    "parser_native_closure.py",
                    "parser_computation.py",
                    "mapping_computation.py",
                    "parser_action_evidence.py",
                    "parser_actions.py",
                    "inline_xbrl.py",
                    "facts.py",
                    "xbrl_precision.py",
                    "current_debt_mapping.py",
                    "common_stock_mapping.py",
                    "award_disclosures.py",
                    "award_disclosure_mapping.py",
                    "standard_accounting_representations.py",
                    "sec_rebuild.py",
                    "issuer_release_evidence.py",
                    "issuer_identity.py",
                    "original_issuer.py",
                    "regulatory_validation.py",
                    "sec_integrity.py",
                    "serialization.py",
                    "taxonomy_evidence.py",
                )
            },
        }
    )


def _direct_balance_present(
    original: OriginalIssuerEvidenceV1, normalized_field: str
) -> bool:
    rule = _RULES.get(normalized_field)
    return rule is not None and any(
        fact.concept == rule.concept and not fact.dimensions
        for fact in original.report.facts
    )


class AutomaticMappingSourceV1(ReleaseModel):
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluator_id: str = Field(min_length=1)
    original: OriginalIssuerEvidenceV1
    integrity: SecIntegrityEvidenceV1
    evidence_refs: tuple[ArtifactRefV1, ...] = Field(min_length=1)
    security_identity: IdentityV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def evidence_is_canonical(self) -> AutomaticMappingSourceV1:
        ids = tuple(ref.artifact_id for ref in self.evidence_refs)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("automatic mapping evidence must be ordered and unique")
        return self


class AutomaticMappingRequestV1(AutomaticMappingSourceV1):
    protocol: Literal["fundamental.automatic-mapping-input.v1"] = (
        "fundamental.automatic-mapping-input.v1"
    )
    proposal: CanonicalMappingV1


def automatic_mapping_proposal(
    normalized_field: str,
    *,
    mapping_version: str,
    original: OriginalIssuerEvidenceV1 | None = None,
) -> CanonicalMappingV1 | None:
    """Create only proposals supported by the service's executable rule table."""
    rule = _RULES.get(normalized_field)
    disclosed = normalized_field == "stock_based_compensation"
    option_cost = normalized_field == "equity_award_unrecognized_compensation"
    investment_assets = normalized_field in INVESTMENT_ASSET_ROLES and not (
        original is not None and _direct_balance_present(original, normalized_field)
    )
    noncontrolling_equity = normalized_field == "noncontrolling_interests"
    representation = (
        standard_accounting_representation(original, normalized_field)
        if original is not None
        else None
    )
    liability_residual = (
        normalized_field in LIABILITY_RESIDUAL_ROLES
        and representation is None
        and not (
            original is not None and _direct_balance_present(original, normalized_field)
        )
    )
    if option_cost and (
        original is None
        or select_option_compensation_disclosure(original).rules is None
    ):
        return None
    if liability_residual and (
        original is None
        or select_registered_liability_residual(original, normalized_field).rules
        is None
    ):
        return None
    if investment_assets and (
        original is None
        or select_registered_investment_assets(original, normalized_field).rules is None
    ):
        return None
    if noncontrolling_equity and (
        original is None
        or select_registered_noncontrolling_equity(original).rules is None
    ):
        return None
    if (
        rule is None
        and not disclosed
        and not investment_assets
        and not noncontrolling_equity
        and not liability_residual
        and not option_cost
        and representation is None
    ):
        return None
    concept = STOCK_COMPENSATION_DISCLOSURE
    if investment_assets:
        concept = investment_asset_concept(normalized_field)
    if representation is not None:
        concept = representation.source_concept
    elif liability_residual:
        concept = liability_residual_concept(normalized_field)
    elif noncontrolling_equity:
        concept = NONCONTROLLING_EQUITY
    elif (
        not disclosed
        and not investment_assets
        and not option_cost
        and representation is None
    ):
        assert rule is not None
        concept = rule.concept
    if normalized_field == "depreciation_and_amortization" and original is not None:
        concept = registered_depreciation_concept(original)
    if normalized_field == "revenue" and original is not None:
        concept = registered_revenue_concept(original) or concept
    payload = {
        "contract_version": "fundamental.v1",
        "source_concept": concept,
        "normalized_field": normalized_field,
        "mapping_version": mapping_version,
        "confidence": "unresolved",
        "status": "provisional",
    }
    return CanonicalMappingV1.model_validate(
        {**payload, "decision_id": "automatic-proposal-" + sha256_digest(payload)}
    )


def automatic_mapping_proposals(
    normalized_field: str,
    *,
    mapping_version: str,
    original: OriginalIssuerEvidenceV1,
    observed_only: bool = False,
) -> tuple[CanonicalMappingV1, ...]:
    """Expose declared alternatives for review without approving observations."""
    primary = automatic_mapping_proposal(
        normalized_field, mapping_version=mapping_version, original=original
    )
    if primary is None:
        return ()
    rule = _RULES.get(normalized_field)
    concepts = (
        rule.concepts
        if rule is not None and primary.source_concept == rule.concept
        else (primary.source_concept,)
    )
    representation = standard_accounting_representation(original, normalized_field)
    if (
        rule is not None
        and representation is not None
        and representation.direct_overlap_exclusion
        and primary.source_concept == representation.source_concept
    ):
        selection = representation.select(original, None)
        classified_instants = (
            {p.period.period_end for p in selection.rules.periods}
            if selection.rules is not None
            else set()
        )
        concepts = (
            primary.source_concept,
            *(
                concept
                for concept in rule.concepts
                if any(
                    fact.concept == concept
                    and not fact.dimensions
                    and fact.instant not in classified_instants
                    for fact in original.report.facts
                )
            ),
        )
    proposals = []
    for concept in sorted(concepts):
        if (
            observed_only
            and (representation is None or concept != representation.source_concept)
            and not any(f.concept == concept for f in original.report.facts)
        ):
            continue
        if concept == primary.source_concept:
            proposals.append(primary)
            continue
        payload = primary.model_dump(exclude={"decision_id"})
        payload["source_concept"] = concept
        proposals.append(
            CanonicalMappingV1.model_validate(
                {
                    **payload,
                    "decision_id": "automatic-proposal-" + sha256_digest(payload),
                }
            )
        )
    return tuple(proposals) or (primary,)


class MappingObservationRejectionV1(ReleaseModel):
    observation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str = Field(min_length=1)


class AutomaticMappingDecisionV1(ReleaseModel):
    protocol: Literal["fundamental.automatic-mapping-decision.v1"] = (
        "fundamental.automatic-mapping-decision.v1"
    )
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    computation: MappingComputationIdentityV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluator_id: str = Field(min_length=1)
    policy_version: AutomaticMappingPolicyVersion = AUTOMATIC_MAPPING_POLICY
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["approved", "abstain"]
    reason_codes: tuple[str, ...]
    eligible_observation_digests: tuple[str, ...]
    rejected_observations: tuple[MappingObservationRejectionV1, ...]
    mapping: CanonicalMappingV1 | None

    @model_validator(mode="after")
    def decision_is_coherent(self) -> AutomaticMappingDecisionV1:
        if self.status == "approved":
            if (
                self.mapping is None
                or self.mapping.status != "approved"
                or (
                    self.mapping.observation_scope is None
                    and self.mapping.accounting_rules is None
                )
                or self.reason_codes
            ):
                raise ValueError("approved decisions require an exact scoped mapping")
        elif self.mapping is not None or not self.reason_codes:
            raise ValueError(
                "abstained decisions require reasons and no approved mapping"
            )
        return self


def _prefer_direct_precision(
    request: AutomaticMappingRequestV1, observations: list[ParsedXbrlFactV1]
) -> tuple[list[ParsedXbrlFactV1], list[MappingObservationRejectionV1], set[str]]:
    groups: dict[
        tuple[str, date | None, date | None, date | None], list[ParsedXbrlFactV1]
    ] = {}
    for fact in observations:
        key = (fact.concept, fact.period_start, fact.period_end, fact.instant)
        groups.setdefault(key, []).append(fact)
    selected: list[ParsedXbrlFactV1] = []
    rejected: list[MappingObservationRejectionV1] = []
    reasons: set[str] = set()
    original = request.original
    for facts in groups.values():
        if any(fact.decimals == "INF" for fact in facts) and any(
            fact.decimals != "INF" for fact in facts
        ):
            reasons.add("MAPPING_PRECISION_MIXED_EXACT_UNSUPPORTED")
            continue
        try:
            candidates = parsed_facts_to_candidates(
                original.report.model_copy(update={"facts": tuple(facts)}),
                source=original.source,
                issuer_id=original.source.cik,
                normalized_field=request.proposal.normalized_field,
            )
            selection = select_fact(
                candidates, valuation_timestamp=original.decision_at
            )
        except SnapshotError as error:
            reasons.add(error.code)
            continue
        if selection.fact is None:
            reason = (
                "MAPPING_PRECISION_UNAVAILABLE"
                if any(
                    issue.code == "FACT_PRECISION_UNAVAILABLE"
                    for issue in selection.issues
                )
                else "MAPPING_OBSERVATION_CONFLICT"
            )
            reasons.add(reason)
            rejected.extend(
                MappingObservationRejectionV1(
                    observation_digest=sha256_digest(fact), reason_code=reason
                )
                for fact in facts
            )
            continue
        for fact in facts:
            decimals = None if fact.decimals == "INF" else int(fact.decimals or "0")
            if (
                Decimal(fact.value) == selection.fact.value
                and decimals == selection.fact.decimals
            ):
                selected.append(fact)
            else:
                rejected.append(
                    MappingObservationRejectionV1(
                        observation_digest=sha256_digest(fact),
                        reason_code="MAPPING_OBSERVATION_LOWER_PRECISION",
                    )
                )
    return selected, rejected, reasons


def _observation_rejection(
    fact: ParsedXbrlFactV1, request: AutomaticMappingRequestV1, rule: DirectMappingRule
) -> str | None:
    original = request.original
    if not _GAAP_NAMESPACE.fullmatch(fact.namespace_uri or "") or (
        rule.namespace_uris and fact.namespace_uri not in rule.namespace_uris
    ):
        return "MAPPING_NAMESPACE_UNSUPPORTED"
    if (
        fact.entity_scheme != "http://www.sec.gov/CIK"
        or not re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "")
        or int(fact.entity_identifier or "0") != int(original.source.cik)
    ):
        return "MAPPING_ISSUER_MISMATCH"
    if (
        fact.dimensions
        or fact.consolidation_scope != "consolidated"
        or fact.security_scope not in {"unspecified", "issuer"}
    ):
        return "MAPPING_SCOPE_UNSUPPORTED"
    if not fact.is_numeric or fact.unit != rule.unit:
        return "MAPPING_UNIT_UNSUPPORTED"
    try:
        value = Decimal(fact.value)
        if not value.is_finite() or (rule.nonnegative and value < 0):
            return "MAPPING_VALUE_INVALID"
    except InvalidOperation:
        return "MAPPING_VALUE_INVALID"
    if (
        fact.decimals != "INF"
        and re.fullmatch(r"-?[0-9]+", fact.decimals or "") is None
    ):
        return "MAPPING_PRECISION_UNAVAILABLE"
    if rule.period == "annual":
        if (
            fact.instant is not None
            or fact.period_start is None
            or fact.period_end is None
            or not 300 <= (fact.period_end - fact.period_start).days <= 380
        ):
            return "MAPPING_PERIOD_UNSUPPORTED"
        end = fact.period_end
    else:
        if (
            fact.instant is None
            or fact.period_start is not None
            or fact.period_end is not None
        ):
            return "MAPPING_PERIOD_UNSUPPORTED"
        end = fact.instant
    if original.report_period_end is None or end > original.report_period_end:
        return "MAPPING_PERIOD_AFTER_ORIGINAL"
    return None


def evaluate_automatic_mapping(
    request: AutomaticMappingRequestV1,
    *,
    contents: dict[str, bytes],
    evidence_checks: AutomaticMappingEvidenceChecks | None = None,
) -> AutomaticMappingDecisionV1:
    """Approve or retain abstention without providers, publication or signatures."""
    policy_digest = automatic_mapping_policy_digest()
    checks = (
        evidence_checks
        if evidence_checks is not None
        else AutomaticMappingEvidenceChecks()
    )
    reasons = set(checks.assess(request, contents=contents))
    original, proposal = request.original, request.proposal
    rule = _RULES.get(proposal.normalized_field)
    disclosed = (
        proposal.normalized_field == "stock_based_compensation"
        and proposal.source_concept == STOCK_COMPENSATION_DISCLOSURE
    )
    option_cost = (
        proposal.normalized_field == "equity_award_unrecognized_compensation"
        and proposal.source_concept == STOCK_COMPENSATION_DISCLOSURE
    )
    depreciation = (
        proposal.normalized_field == "depreciation_and_amortization"
        and proposal.source_concept
        in {DEPRECIATION, ADJUSTED_DEPRECIATION, FIXED_ASSET_DEPRECIATION}
    )
    capital_expenditure = (
        proposal.normalized_field == "capital_expenditure"
        and proposal.source_concept == CAPITAL_EXPENDITURE
    )
    registered_revenue = (
        proposal.normalized_field == "revenue"
        and proposal.source_concept == CONTRACT_REVENUE
    )
    adjusted = depreciation and proposal.source_concept == ADJUSTED_DEPRECIATION
    investment_assets = (
        proposal.normalized_field in INVESTMENT_ASSET_ROLES
        and proposal.source_concept
        == investment_asset_concept(proposal.normalized_field)
    )
    noncontrolling_equity = (
        proposal.normalized_field == "noncontrolling_interests"
        and proposal.source_concept == NONCONTROLLING_EQUITY
    )
    representation = standard_accounting_representation(
        original, proposal.normalized_field
    )
    standard = (
        representation is not None
        and proposal.source_concept == representation.source_concept
    )
    liability_residual = (
        proposal.normalized_field in LIABILITY_RESIDUAL_ROLES
        and proposal.source_concept
        == liability_residual_concept(proposal.normalized_field)
    )
    computed = (
        disclosed
        or adjusted
        or investment_assets
        or noncontrolling_equity
        or liability_residual
        or option_cost
        or standard
    )
    if (
        (
            not computed
            and not depreciation
            and not registered_revenue
            and (rule is None or proposal.source_concept not in rule.concepts)
        )
        or proposal.accounting_rules is not None
        or proposal.observation_scope is not None
        or proposal.status != "provisional"
    ):
        reasons.add("MAPPING_AUTOMATIC_RULE_UNSUPPORTED")
    selected: list[ParsedXbrlFactV1] = []
    rejected: list[MappingObservationRejectionV1] = []
    accounting_rules = None
    classified_instants: set[date] = set()
    if representation is not None:
        selection = representation.select(
            original,
            request.security_identity.security_id
            if request.security_identity is not None
            else None,
        )
        reasons.update(selection.reason_codes)
        if standard:
            selected.extend(selection.selected)
            accounting_rules = selection.rules
        elif representation.direct_overlap_exclusion and selection.rules is not None:
            classified_instants.update(
                p.period.period_end for p in selection.rules.periods
            )
        elif not representation.direct_overlap_exclusion:
            reasons.add("MAPPING_STANDARD_REPRESENTATION_REQUIRED")
    if liability_residual:
        if _direct_balance_present(original, proposal.normalized_field) or (
            proposal.normalized_field == "current_interest_bearing_debt"
            and representation is not None
        ):
            reasons.add("MAPPING_DEBT_DIRECT_REPRESENTATION_REQUIRED")
        liabilities = select_registered_liability_residual(
            original,
            proposal.normalized_field,
            security_id=(
                request.security_identity.security_id
                if request.security_identity is not None
                else None
            ),
        )
        reasons.update(liabilities.reason_codes)
        selected.extend(liabilities.selected)
        accounting_rules = liabilities.rules
    if noncontrolling_equity:
        equity = select_registered_noncontrolling_equity(
            original,
            security_id=(
                request.security_identity.security_id
                if request.security_identity is not None
                else None
            ),
        )
        reasons.update(equity.reason_codes)
        selected.extend(equity.selected)
        accounting_rules = equity.rules
    if investment_assets:
        if _direct_balance_present(original, proposal.normalized_field):
            reasons.add("MAPPING_INVESTMENT_DIRECT_REPRESENTATION_REQUIRED")
        assets = select_registered_investment_assets(
            original,
            proposal.normalized_field,
            security_id=(
                request.security_identity.security_id
                if request.security_identity is not None
                else None
            ),
        )
        reasons.update(assets.reason_codes)
        selected.extend(assets.selected)
        accounting_rules = assets.rules
    if disclosed or option_cost:
        selector = (
            select_option_compensation_disclosure
            if option_cost
            else select_stock_compensation_disclosure
        )
        disclosure = selector(
            original,
            security_id=(
                request.security_identity.security_id
                if request.security_identity is not None
                else None
            ),
        )
        reasons.update(disclosure.reason_codes)
        selected.extend(disclosure.selected)
        accounting_rules = disclosure.rules
        rejected.extend(
            MappingObservationRejectionV1(
                observation_digest=sha256_digest(fact), reason_code=reason
            )
            for fact, reason in disclosure.rejected
        )
    if depreciation:
        classification = select_registered_depreciation(
            original,
            adjusted=adjusted,
            source_concept=proposal.source_concept,
            security_id=(
                request.security_identity.security_id
                if request.security_identity is not None
                else None
            ),
        )
        reasons.update(classification.reason_codes)
        accounting_rules = classification.rules
        for fact in classification.selected:
            reason = (
                None
                if adjusted
                else _observation_rejection(
                    fact, request, _RULES[proposal.normalized_field]
                )
            )
            if reason is None:
                selected.append(fact)
            else:
                rejected.append(
                    MappingObservationRejectionV1(
                        observation_digest=sha256_digest(fact), reason_code=reason
                    )
                )
        rejected.extend(
            MappingObservationRejectionV1(
                observation_digest=sha256_digest(fact), reason_code=reason
            )
            for fact, reason in classification.rejected
        )
    if capital_expenditure:
        capex = select_registered_capital_expenditure(original)
        reasons.update(capex.reason_codes)
        for fact in capex.selected:
            reason = _observation_rejection(
                fact, request, _RULES["capital_expenditure"]
            )
            if reason is None:
                selected.append(fact)
            else:
                rejected.append(
                    MappingObservationRejectionV1(
                        observation_digest=sha256_digest(fact), reason_code=reason
                    )
                )
        rejected.extend(
            MappingObservationRejectionV1(
                observation_digest=sha256_digest(fact), reason_code=reason
            )
            for fact, reason in capex.rejected
        )
    if registered_revenue:
        revenue = select_registered_revenue(original)
        reasons.update(revenue.reason_codes)
        for fact in revenue.selected:
            reason = _observation_rejection(fact, request, _RULES["revenue"])
            if reason is None:
                selected.append(fact)
            else:
                rejected.append(
                    MappingObservationRejectionV1(
                        observation_digest=sha256_digest(fact), reason_code=reason
                    )
                )
        rejected.extend(
            MappingObservationRejectionV1(
                observation_digest=sha256_digest(fact), reason_code=reason
            )
            for fact, reason in revenue.rejected
        )
    specialized = (
        disclosed
        or depreciation
        or capital_expenditure
        or registered_revenue
        or investment_assets
        or noncontrolling_equity
        or liability_residual
        or option_cost
        or standard
    )
    candidates = (
        ()
        if specialized
        else tuple(
            fact
            for fact in original.report.facts
            if fact.concept == proposal.source_concept
        )
    )
    for fact in sorted(candidates, key=sha256_digest):
        if fact.instant in classified_instants:
            rejected.append(
                MappingObservationRejectionV1(
                    observation_digest=sha256_digest(fact),
                    reason_code="MAPPING_LEASE_CLASSIFIED_REPRESENTATION_REQUIRED",
                )
            )
            continue
        reason = (
            "MAPPING_AUTOMATIC_RULE_UNSUPPORTED"
            if rule is None or proposal.source_concept not in rule.concepts
            else _observation_rejection(fact, request, rule)
        )
        if reason:
            rejected.append(
                MappingObservationRejectionV1(
                    observation_digest=sha256_digest(fact), reason_code=reason
                )
            )
        else:
            selected.append(fact)
    if not selected:
        reasons.add("MAPPING_NO_ELIGIBLE_OBSERVATIONS")
    if not computed and selected and not reasons:
        selected, precision_rejections, precision_reasons = _prefer_direct_precision(
            request, selected
        )
        rejected.extend(precision_rejections)
        reasons.update(precision_reasons)
    periods: dict[tuple[object, ...], set[Decimal]] = {}
    for fact in () if computed else selected:
        key = (fact.period_start, fact.period_end, fact.instant)
        periods.setdefault(key, set()).add(Decimal(fact.value))
    if rule is not None and len(rule.concepts) > 1:
        alternatives = (
            fact
            for fact in original.report.facts
            if fact.concept in rule.concepts and fact.concept != proposal.source_concept
        )
        for fact in sorted(alternatives, key=sha256_digest):
            if _observation_rejection(fact, request, rule) is not None:
                continue
            key = (fact.period_start, fact.period_end, fact.instant)
            if key in periods and Decimal(fact.value) not in periods[key]:
                periods[key].add(Decimal(fact.value))
                rejected.append(
                    MappingObservationRejectionV1(
                        observation_digest=sha256_digest(fact),
                        reason_code="MAPPING_OBSERVATION_CONFLICT",
                    )
                )
    if any(len(values) != 1 for values in periods.values()):
        reasons.add("MAPPING_OBSERVATION_CONFLICT")
    mapping = None
    if not reasons:
        scope = (
            None
            if computed
            else MappingObservationScopeV1(
                issuer_id=original.source.cik,
                accession_number=original.source.accession_number,
                raw_content_hash=original.source.content_hash,
                parser_input_hash=original.source.parser_input_hash,
                parser_replay_digest=checks.report_replay_digest(original.report),
                observation_digests=tuple(sorted({sha256_digest(f) for f in selected})),
            )
        )
        payload: dict[str, object] = {
            "contract_version": "fundamental.v1",
            "source_concept": f"computed:{proposal.normalized_field}"
            if computed
            else proposal.source_concept,
            "normalized_field": proposal.normalized_field,
            "mapping_version": proposal.mapping_version,
            "confidence": "high",
            "status": "approved",
            "reviewer": f"automatic:{request.evaluator_id}",
            "evidence_refs": (
                original.source.content_hash,
                checks.report_replay_digest(original.report),
                policy_digest,
            ),
            "observation_scope": scope,
        }
        if computed:
            anchor = DEPRECIATION
            if disclosed or option_cost:
                anchor = STOCK_COMPENSATION_DISCLOSURE
            elif investment_assets:
                anchor = investment_asset_concept(proposal.normalized_field)
            elif noncontrolling_equity:
                anchor = NONCONTROLLING_EQUITY
            elif liability_residual:
                anchor = liability_residual_concept(proposal.normalized_field)
            elif standard:
                assert representation is not None
                anchor = representation.source_concept
            payload.update(
                {
                    "anchor_concept": anchor,
                    "accounting_rules": accounting_rules,
                }
            )
        mapping = CanonicalMappingV1.model_validate(
            {**payload, "decision_id": "automatic-mapping-" + sha256_digest(payload)}
        )
    return AutomaticMappingDecisionV1(
        input_digest=checks.identities.input_digest(request),
        computation=MappingComputationIdentityV1(
            digest=mapping_computation_digest(
                request, policy_digest, input_digests=checks.identities
            )
        )
        if original.policy_version == "original-issuer-operating-v2"
        else None,
        source_revision=request.source_revision,
        evaluator_id=request.evaluator_id,
        policy_digest=policy_digest,
        status="abstain" if reasons else "approved",
        reason_codes=tuple(sorted(reasons)),
        eligible_observation_digests=tuple(
            sorted({sha256_digest(f) for f in selected})
        ),
        rejected_observations=tuple(rejected),
        mapping=mapping,
    )


def verify_automatic_mapping_replay(
    approval: AutomaticMappingApprovalV1,
    mapping: CanonicalMappingV1,
    *,
    artifacts: MappingInputReader,
    evidence_checks: AutomaticMappingEvidenceChecks | None = None,
) -> AutomaticMappingRequestV1:
    """Re-evaluate retained inputs; a trusted signature alone is insufficient."""
    if evidence_checks is None:
        evidence_checks = AutomaticMappingEvidenceChecks()
    artifacts = evidence_checks.reader(artifacts)
    refs = tuple(
        ref
        for ref in approval.evidence_refs
        if ref.role == AUTOMATIC_MAPPING_INPUT_ROLE
    )
    if len(refs) != 1:
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_INPUT_UNAVAILABLE",
            "retain one automatic mapping input",
        )
    raw = artifacts.read(refs[0].artifact_id)
    if hashlib.sha256(raw).hexdigest() != refs[0].content_hash:
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_INPUT_HASH_MISMATCH",
            "automatic mapping input changed",
        )
    request = resolve_mapping_input(
        raw,
        AutomaticMappingRequestV1,
        artifacts=artifacts,
        original_checks=evidence_checks.originals,
        input_digests=evidence_checks.identities,
    )
    if approval.evidence_refs != (refs[0], *request.evidence_refs):
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_EVIDENCE_MISMATCH",
            "automatic source references differ",
        )
    contents = {
        ref.content_hash: artifacts.read(ref.artifact_id)
        for ref in request.evidence_refs
    }
    evidence_checks.require_parser_actions(request, artifacts=artifacts)
    decision = evaluate_automatic_mapping(
        request, contents=contents, evidence_checks=evidence_checks
    )
    if (
        request.evaluator_id != approval.evaluator_id
        or request.source_revision != approval.source_revision
        or decision.input_digest != approval.input_digest
        or decision.computation != approval.computation
        or sha256_digest(decision) != approval.output_digest
        or decision.policy_digest != approval.policy_digest
        or decision.mapping != mapping
        or mapping.decision_id != approval.mapping_id
        or sha256_digest(mapping) != approval.mapping_digest
        or decision.status != "approved"
    ):
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_REPLAY_MISMATCH",
            "automatic approval differs from its retained policy evaluation",
        )
    require_current_parser_action_refs(
        request.evidence_refs, artifacts=artifacts, build_checks=evidence_checks.builds
    )
    return request
