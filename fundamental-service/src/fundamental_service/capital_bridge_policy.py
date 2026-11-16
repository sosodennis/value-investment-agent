"""Shared source-observation policy for exact and conditional equity bridges."""

from decimal import Decimal

from .contracts import CanonicalFactV1, SourceSnapshotV1
from .serialization import sha256_digest
from .valuation_requirements import valuation_requirements_profile


class CapitalBridgePolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _positive_observation_keys(fact: CanonicalFactV1) -> set[str]:
    evidence = fact.accounting_evidence
    if evidence is None:
        return {
            sha256_digest(
                {
                    "issuer": fact.issuer_id,
                    "concept": fact.concept,
                    "instant": fact.instant,
                    "start": fact.period_start,
                    "end": fact.period_end,
                    "unit": fact.unit.removeprefix("iso4217:"),
                    "dimensions": tuple(
                        sorted(
                            (dimension.name, dimension.member)
                            for dimension in fact.context.dimensions
                        )
                    ),
                }
            )
        }
    positive = {
        component.parsed_fact_digest
        for component in evidence.period_rule.components
        if component.sign == 1
    }
    return {
        sha256_digest(
            {
                "issuer": fact.issuer_id,
                "concept": observation.concept,
                "instant": observation.instant,
                "start": observation.period_start,
                "end": observation.instant or observation.period_end,
                "unit": (observation.unit or "").removeprefix("iso4217:"),
                "dimensions": tuple(sorted(observation.dimensions)),
            }
        )
        for observation in evidence.source_facts
        if observation.is_numeric and sha256_digest(observation) in positive
    }


def require_disjoint_non_operating_assets(
    capital_facts: dict[str, CanonicalFactV1],
    facts: tuple[CanonicalFactV1, ...],
    snapshot: SourceSnapshotV1,
) -> None:
    asset = capital_facts["non_operating_assets"]
    cash = capital_facts["cash_and_equivalents"]
    if (
        asset.instant != cash.instant
        or asset.source.content_hash != cash.source.content_hash
        or asset.accession_number != cash.accession_number
        or asset.currency != snapshot.identity.currency
        or asset.unit not in {asset.currency, f"iso4217:{asset.currency}"}
        or asset.context.dimensions
        or asset.context.consolidation_scope != "consolidated"
        or not isinstance(asset.value, Decimal)
        or not asset.value.is_finite()
        or asset.value < 0
    ):
        raise CapitalBridgePolicyError(
            "NON_OPERATING_ASSET_SCOPE_INVALID",
            "non-operating assets require a nonnegative consolidated currency amount at the cash balance date",
        )
    operating_fields = valuation_requirements_profile("fcff_dcf").annual_instant_fields
    used = _positive_observation_keys(cash)
    for fact in facts:
        if fact.normalized_field in operating_fields and fact.instant == asset.instant:
            used.update(_positive_observation_keys(fact))
    if _positive_observation_keys(asset) & used:
        raise CapitalBridgePolicyError(
            "NON_OPERATING_ASSET_OVERLAP",
            "non-operating assets cannot reuse cash or operating working-capital observations",
        )
