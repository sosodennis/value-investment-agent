"""Deterministic approval of narrowly defined, source-bound US GAAP mappings."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .arelle_parser import ParsedXbrlFactV1
from .automatic_mapping_disclosures import (
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
from .facts import CanonicalMappingV1, MappingObservationScopeV1
from .issuer_release_evidence import verify_original_bytes, verify_original_integrity
from .issuer_identity import IdentityResolutionError, validate_original_filing_identity
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
from .registered_non_operating_assets import (
    NON_OPERATING_ASSETS,
    select_registered_non_operating_assets,
)
from .registered_noncontrolling_equity import (
    NONCONTROLLING_EQUITY,
    select_registered_noncontrolling_equity,
)
from .registered_noncurrent_liabilities import (
    NONCURRENT_LIABILITY_RESIDUAL,
    ROLES as NONCURRENT_LIABILITY_ROLES,
    select_registered_noncurrent_liabilities,
)
from .serialization import sha256_digest
from .taxonomy_evidence import require_original_taxonomy

AUTOMATIC_MAPPING_INPUT_ROLE = "automatic-mapping-input-v1"
AUTOMATIC_MAPPING_POLICY: Literal["source-bound-us-gaap-v10"] = (
    "source-bound-us-gaap-v10"
)
_GAAP_NAMESPACE = re.compile(
    r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?"
)


@dataclass(frozen=True)
class DirectMappingRule:
    concept: str
    period: Literal["annual", "instant"]
    unit: Literal["iso4217:USD", "xbrli:shares"] = "iso4217:USD"
    alternative_concepts: tuple[str, ...] = ()

    @property
    def concepts(self) -> tuple[str, ...]:
        return (self.concept, *self.alternative_concepts)


# Partial revenue tags, absence claims, arbitrary computed partitions and awards
# have no direct rule. Aggregate D&A and cash capex require registered scope.
# Every rule change changes the policy digest.
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
    "current_operating_lease_liabilities": DirectMappingRule(
        "us-gaap:OperatingLeaseLiabilityCurrent", "instant"
    ),
    "long_term_operating_lease_liabilities": DirectMappingRule(
        "us-gaap:OperatingLeaseLiabilityNoncurrent", "instant"
    ),
    "common_shares_outstanding": DirectMappingRule(
        "us-gaap:CommonStockSharesOutstanding", "instant", "xbrli:shares"
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
                    "automatic_mapping_disclosures.py",
                    "registered_depreciation.py",
                    "registered_capital_expenditure.py",
                    "registered_non_operating_assets.py",
                    "registered_noncontrolling_equity.py",
                    "registered_noncurrent_liabilities.py",
                    "accounting_roles.py",
                    "arelle_parser.py",
                    "facts.py",
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
    investment_assets = normalized_field == "non_operating_assets"
    noncontrolling_equity = normalized_field == "noncontrolling_interests"
    noncurrent_liabilities = normalized_field in NONCURRENT_LIABILITY_ROLES
    if noncurrent_liabilities and (
        original is None
        or select_registered_noncurrent_liabilities(original, normalized_field).rules
        is None
    ):
        return None
    if investment_assets and (
        original is None
        or select_registered_non_operating_assets(original).rules is None
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
        and not noncurrent_liabilities
    ):
        return None
    concept = (
        NON_OPERATING_ASSETS if investment_assets else STOCK_COMPENSATION_DISCLOSURE
    )
    if noncurrent_liabilities:
        concept = NONCURRENT_LIABILITY_RESIDUAL
    elif noncontrolling_equity:
        concept = NONCONTROLLING_EQUITY
    elif not disclosed and not investment_assets:
        assert rule is not None
        concept = rule.concept
    if normalized_field == "depreciation_and_amortization" and original is not None:
        concept = registered_depreciation_concept(original)
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


class MappingObservationRejectionV1(ReleaseModel):
    observation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_code: str = Field(min_length=1)


class AutomaticMappingDecisionV1(ReleaseModel):
    protocol: Literal["fundamental.automatic-mapping-decision.v1"] = (
        "fundamental.automatic-mapping-decision.v1"
    )
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    evaluator_id: str = Field(min_length=1)
    policy_version: Literal["source-bound-us-gaap-v10"] = AUTOMATIC_MAPPING_POLICY
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


def _observation_rejection(
    fact: ParsedXbrlFactV1, request: AutomaticMappingRequestV1, rule: DirectMappingRule
) -> str | None:
    original = request.original
    if not _GAAP_NAMESPACE.fullmatch(fact.namespace_uri or ""):
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
        if not Decimal(fact.value).is_finite():
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
    request: AutomaticMappingRequestV1, *, contents: dict[str, bytes]
) -> AutomaticMappingDecisionV1:
    """Approve or retain abstention without providers, publication or signatures."""
    policy_digest = automatic_mapping_policy_digest()
    reasons: set[str] = set()
    original, proposal = request.original, request.proposal
    if original.status != "matched":
        reasons.update(original.issue_codes)
    try:
        for ref in request.evidence_refs:
            if (
                ref.content_hash not in contents
                or hashlib.sha256(contents[ref.content_hash]).hexdigest()
                != ref.content_hash
            ):
                raise DataReleaseError(
                    "MAPPING_SOURCE_ARTIFACT_UNAVAILABLE",
                    "automatic mapping requires its retained evidence bytes",
                )
        require_original_taxonomy(
            original.report.taxonomy_cache_hash or "", request.evidence_refs, contents
        )
        verify_original_integrity(
            original, request.integrity, parser_version=original.report.parser_version
        )
        verify_original_bytes(request.integrity, contents)
    except DataReleaseError as error:
        reasons.add(error.code)
    if request.security_identity is not None:
        try:
            validate_original_filing_identity(
                request.security_identity,
                cik=original.source.cik,
                ticker=request.security_identity.security_id,
                accepted_at=original.source.available_at,
                facts=original.report.facts,
            )
        except IdentityResolutionError as error:
            reasons.add(error.code)
    rule = _RULES.get(proposal.normalized_field)
    disclosed = (
        proposal.normalized_field == "stock_based_compensation"
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
    adjusted = depreciation and proposal.source_concept == ADJUSTED_DEPRECIATION
    investment_assets = (
        proposal.normalized_field == "non_operating_assets"
        and proposal.source_concept == NON_OPERATING_ASSETS
    )
    noncontrolling_equity = (
        proposal.normalized_field == "noncontrolling_interests"
        and proposal.source_concept == NONCONTROLLING_EQUITY
    )
    noncurrent_liabilities = (
        proposal.normalized_field in NONCURRENT_LIABILITY_ROLES
        and proposal.source_concept == NONCURRENT_LIABILITY_RESIDUAL
    )
    computed = (
        disclosed
        or adjusted
        or investment_assets
        or noncontrolling_equity
        or noncurrent_liabilities
    )
    if (
        (
            not computed
            and not depreciation
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
    if noncurrent_liabilities:
        liabilities = select_registered_noncurrent_liabilities(
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
        assets = select_registered_non_operating_assets(
            original,
            security_id=(
                request.security_identity.security_id
                if request.security_identity is not None
                else None
            ),
        )
        reasons.update(assets.reason_codes)
        selected.extend(assets.selected)
        accounting_rules = assets.rules
    if disclosed:
        disclosure = select_stock_compensation_disclosure(
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
    for fact in sorted(original.report.facts, key=sha256_digest):
        if (
            disclosed
            or depreciation
            or capital_expenditure
            or investment_assets
            or noncontrolling_equity
            or noncurrent_liabilities
            or fact.concept != proposal.source_concept
        ):
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
    periods: dict[tuple[object, ...], set[Decimal]] = {}
    for fact in () if computed else selected:
        key = (fact.period_start, fact.period_end, fact.instant)
        periods.setdefault(key, set()).add(Decimal(fact.value))
    if rule is not None and len(rule.concepts) > 1:
        for fact in sorted(original.report.facts, key=sha256_digest):
            if (
                fact.concept not in rule.concepts
                or fact.concept == proposal.source_concept
                or _observation_rejection(fact, request, rule) is not None
            ):
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
                parser_replay_digest=original.report.replay_digest(),
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
                original.report.replay_digest(),
                policy_digest,
            ),
            "observation_scope": scope,
        }
        if computed:
            anchor = DEPRECIATION
            if disclosed:
                anchor = STOCK_COMPENSATION_DISCLOSURE
            elif investment_assets:
                anchor = NON_OPERATING_ASSETS
            elif noncontrolling_equity:
                anchor = NONCONTROLLING_EQUITY
            elif noncurrent_liabilities:
                anchor = NONCURRENT_LIABILITY_RESIDUAL
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
        input_digest=sha256_digest(request),
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


class MappingEvidenceReader(Protocol):
    def read(self, artifact_id: str) -> bytes: ...


def verify_automatic_mapping_replay(
    approval: AutomaticMappingApprovalV1,
    mapping: CanonicalMappingV1,
    *,
    artifacts: MappingEvidenceReader,
) -> AutomaticMappingRequestV1:
    """Re-evaluate retained inputs; a trusted signature alone is insufficient."""
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
    request = AutomaticMappingRequestV1.model_validate_json(raw)
    if approval.evidence_refs != (refs[0], *request.evidence_refs):
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_EVIDENCE_MISMATCH",
            "automatic source references differ",
        )
    contents = {
        ref.content_hash: artifacts.read(ref.artifact_id)
        for ref in request.evidence_refs
    }
    decision = evaluate_automatic_mapping(request, contents=contents)
    if (
        request.evaluator_id != approval.evaluator_id
        or request.source_revision != approval.source_revision
        or sha256_digest(request) != approval.input_digest
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
    return request
