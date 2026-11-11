"""Treasury-stock arithmetic for the formal composer; release checks stay outside."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import CanonicalFactV1, PeriodType, QualityStatus, SourceRole, TraceV1
from .numerical_policy import VALUATION_NUMERICAL_POLICY, using_valuation_context
from .serialization import sha256_digest


class DilutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DilutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RestrictedStockAwardV1(DilutionModel):
    kind: Literal["restricted_stock_unit"] = "restricted_stock_unit"
    instrument_id: str = Field(min_length=1)
    quantity: CanonicalFactV1
    unrecognized_compensation: CanonicalFactV1


class StockOptionAwardV1(DilutionModel):
    kind: Literal["stock_option"] = "stock_option"
    instrument_id: str = Field(min_length=1)
    quantity: CanonicalFactV1
    exercise_price: CanonicalFactV1
    unrecognized_compensation: CanonicalFactV1


class PerformanceStockAwardV1(DilutionModel):
    kind: Literal["performance_stock_unit"] = "performance_stock_unit"
    instrument_id: str = Field(min_length=1)
    quantity: CanonicalFactV1
    unrecognized_compensation: CanonicalFactV1
    conditions_satisfied: bool
    condition_evidence: TraceV1


AwardV1 = Annotated[
    RestrictedStockAwardV1 | StockOptionAwardV1 | PerformanceStockAwardV1,
    Field(discriminator="kind"),
]


class EquityAwardInventoryV1(DilutionModel):
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    security_id: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    period_end: date
    complete_inventory: Literal[True]
    coverage_evidence: TraceV1
    instruments: tuple[AwardV1, ...] = Field(min_length=1)

    @field_validator("instruments")
    @classmethod
    def canonical_instrument_order(
        cls, values: tuple[AwardV1, ...]
    ) -> tuple[AwardV1, ...]:
        return tuple(sorted(values, key=lambda item: item.instrument_id))

    @model_validator(mode="after")
    def inventory_does_not_repeat_observations(self) -> EquityAwardInventoryV1:
        ids = tuple(item.instrument_id for item in self.instruments)
        if len(set(ids)) != len(ids):
            raise ValueError("award inventory must have distinct instrument identities")
        facts = tuple(fact for item in self.instruments for fact in _award_facts(item))
        keys = tuple(
            (
                fact.source.content_hash,
                fact.concept,
                fact.instant,
                fact.unit,
                fact.context.entity_scope,
                fact.context.consolidation_scope,
                tuple(
                    (dimension.name, dimension.member)
                    for dimension in fact.context.dimensions
                ),
            )
            for fact in facts
        )
        if len(set(keys)) != len(keys) or len({fact.fact_id for fact in facts}) != len(
            facts
        ):
            raise ValueError(
                "award inventory cannot count an original observation twice"
            )
        scopes: dict[tuple[str, str], set[bool]] = {}
        for fact in facts:
            scopes.setdefault((fact.source.content_hash, fact.concept), set()).add(
                bool(fact.context.dimensions)
            )
        if any(len(values) > 1 for values in scopes.values()):
            raise ValueError("award inventory cannot mix totals with class components")
        return self


class CommonShareQuoteV1(DilutionModel):
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    security_id: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    source_id: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime
    available_at: datetime
    captured_at: datetime

    @model_validator(mode="after")
    def quote_times_are_ordered(self) -> CommonShareQuoteV1:
        times = (self.as_of, self.available_at, self.captured_at)
        if any(value.tzinfo is None or value.utcoffset() is None for value in times):
            raise ValueError("quote timestamps require a timezone")
        if self.as_of > self.available_at or self.available_at > self.captured_at:
            raise ValueError("quote timestamps are reversed")
        return self


class TreasuryStockPolicyV1(DilutionModel):
    protocol: Literal["treasury-stock-v1"] = "treasury-stock-v1"
    policy_version: str = Field(min_length=1)
    max_quote_age_seconds: int = Field(gt=0)


class InstrumentDilutionV1(DilutionModel):
    instrument_id: str
    kind: Literal["restricted_stock_unit", "stock_option", "performance_stock_unit"]
    quantity: Decimal
    exercise_proceeds: Decimal
    unrecognized_compensation: Decimal
    assumed_repurchased_shares: Decimal
    incremental_shares: Decimal
    anti_dilutive: bool
    source_fact_ids: tuple[str, ...]
    input_evidence_digests: tuple[str, ...]


class TreasuryStockResultV1(DilutionModel):
    protocol: Literal["treasury-stock-v1"] = "treasury-stock-v1"
    input_digest: str
    policy_version: str
    numerical_policy: str = VALUATION_NUMERICAL_POLICY
    incremental_shares: Decimal
    instruments: tuple[InstrumentDilutionV1, ...]
    quote_content_hash: str

    @property
    def digest(self) -> str:
        return sha256_digest(self)


def _award_facts(award: AwardV1) -> tuple[CanonicalFactV1, ...]:
    return (
        (award.quantity, award.exercise_price, award.unrecognized_compensation)
        if isinstance(award, StockOptionAwardV1)
        else (award.quantity, award.unrecognized_compensation)
    )


def _validate_trace(
    trace: TraceV1, *, inventory: EquityAwardInventoryV1, cutoff: datetime
) -> None:
    if (
        not trace.source_refs
        or trace.as_of is None
        or trace.as_of.date() != inventory.period_end
        or trace.available_at is None
        or trace.available_at > cutoff
        or trace.captured_at is None
    ):
        raise DilutionError(
            "DILUTION_COVERAGE_UNAVAILABLE",
            "award coverage requires dated source evidence for its exact instant",
        )


@using_valuation_context
def compute_treasury_stock_dilution(
    inventory: EquityAwardInventoryV1,
    quote: CommonShareQuoteV1,
    policy: TreasuryStockPolicyV1,
    *,
    valuation_timestamp: datetime,
) -> TreasuryStockResultV1:
    """Compute only arithmetic; completeness/review/release are owning caller gates."""
    if valuation_timestamp.tzinfo is None or valuation_timestamp.utcoffset() is None:
        raise DilutionError(
            "DILUTION_TIMESTAMP_INVALID", "valuation timestamp requires a timezone"
        )
    if (quote.issuer_id, quote.security_id, quote.currency) != (
        inventory.issuer_id,
        inventory.security_id,
        inventory.currency,
    ):
        raise DilutionError(
            "DILUTION_QUOTE_SCOPE_MISMATCH",
            "quote must match the inventory issuer, security and currency",
        )
    if (
        quote.available_at > valuation_timestamp
        or inventory.period_end > valuation_timestamp.date()
    ):
        raise DilutionError(
            "DILUTION_FUTURE_EVIDENCE",
            "award inventory and quote must be available by valuation time",
        )
    if valuation_timestamp - quote.as_of > timedelta(
        seconds=policy.max_quote_age_seconds
    ):
        raise DilutionError(
            "DILUTION_QUOTE_STALE", "quote exceeds the explicit policy freshness limit"
        )
    _validate_trace(
        inventory.coverage_evidence, inventory=inventory, cutoff=valuation_timestamp
    )
    rows = []
    for award in inventory.instruments:
        if isinstance(award, PerformanceStockAwardV1):
            _validate_trace(
                award.condition_evidence,
                inventory=inventory,
                cutoff=valuation_timestamp,
            )
            if not award.conditions_satisfied:
                raise DilutionError(
                    "DILUTION_PERFORMANCE_UNRESOLVED",
                    "performance awards require resolved conditions before treasury-stock use",
                )
        facts = _award_facts(award)
        for fact in facts:
            if (
                fact.issuer_id != inventory.issuer_id
                or fact.security_id != inventory.security_id
                or fact.security_scope
                not in {
                    inventory.security_id,
                    "segmented" if fact.context.dimensions else "unspecified",
                }
                or fact.instant != inventory.period_end
                or fact.period_start is not None
                or fact.period_end != inventory.period_end
                or fact.context.instant != inventory.period_end
                or fact.context.period_type is not PeriodType.INSTANT
                or fact.context.concept_qname != fact.concept
                or fact.context.start_date is not None
                or fact.context.end_date is not None
                or fact.context.entity_scope != inventory.issuer_id
                or fact.context.consolidation_scope
                != ("segmented" if fact.context.dimensions else "consolidated")
                or any(
                    dimension.name != "us-gaap:AwardTypeAxis"
                    for dimension in fact.context.dimensions
                )
                or len(fact.context.dimensions) > 1
                or fact.context.dimensions != award.quantity.context.dimensions
                or fact.source.content_hash != award.quantity.source.content_hash
                or fact.source.accession_number
                != award.quantity.source.accession_number
                or fact.source.source_role is not SourceRole.FILING
                or fact.source.accession_number is None
                or fact.accession_number != fact.source.accession_number
                or fact.is_amendment
                or fact.quality
                not in {QualityStatus.PROVISIONAL, QualityStatus.VERIFIED}
                or fact.source.content_hash
                not in inventory.coverage_evidence.source_refs
            ):
                raise DilutionError(
                    "DILUTION_FACT_SCOPE_MISMATCH",
                    "award facts must share the reviewed original, issuer, security and instant",
                )
            if (
                fact.available_at > valuation_timestamp
                or fact.source.available_at > valuation_timestamp
            ):
                raise DilutionError(
                    "DILUTION_FUTURE_EVIDENCE",
                    "award observation is unavailable at valuation time",
                )
            if (
                not isinstance(fact.value, Decimal)
                or not fact.value.is_finite()
                or fact.value < 0
            ):
                raise DilutionError(
                    "DILUTION_FACT_INVALID",
                    "award observations must be finite nonnegative quantities",
                )
        units = (award.quantity.unit, award.unrecognized_compensation.unit)
        if (
            units != ("xbrli:shares", f"iso4217:{inventory.currency}")
            or (
                isinstance(award, StockOptionAwardV1)
                and award.exercise_price.unit
                != f"iso4217:{inventory.currency}/xbrli:shares"
            )
            or award.quantity.currency is not None
            or award.unrecognized_compensation.currency != inventory.currency
            or (
                isinstance(award, StockOptionAwardV1)
                and award.exercise_price.currency != inventory.currency
            )
            or any(fact.context.unit_qname != fact.unit for fact in facts)
        ):
            raise DilutionError(
                "DILUTION_UNIT_MISMATCH",
                "award quantities, compensation and exercise prices require their exact units",
            )
        quantity = award.quantity.value
        compensation = award.unrecognized_compensation.value
        assert isinstance(quantity, Decimal) and isinstance(compensation, Decimal)
        if quantity == 0 and compensation != 0:
            raise DilutionError(
                "DILUTION_FACT_INCONSISTENT",
                "zero outstanding awards cannot carry remaining award compensation",
            )
        exercise = Decimal(0)
        if isinstance(award, StockOptionAwardV1):
            assert isinstance(award.exercise_price.value, Decimal)
            exercise = quantity * award.exercise_price.value
        repurchased = (exercise + compensation) / quote.price
        rows.append(
            InstrumentDilutionV1(
                instrument_id=award.instrument_id,
                kind=award.kind,
                quantity=quantity,
                exercise_proceeds=exercise,
                unrecognized_compensation=compensation,
                assumed_repurchased_shares=repurchased,
                incremental_shares=max(Decimal(0), quantity - repurchased),
                anti_dilutive=repurchased >= quantity,
                source_fact_ids=tuple(f.fact_id for f in facts),
                input_evidence_digests=tuple(sha256_digest(f) for f in facts),
            )
        )
    inputs = {
        "inventory": inventory,
        "quote": quote,
        "policy": policy,
        "valuation_timestamp": valuation_timestamp,
        "numerical_policy": VALUATION_NUMERICAL_POLICY,
    }
    return TreasuryStockResultV1(
        input_digest=sha256_digest(inputs),
        policy_version=policy.policy_version,
        incremental_shares=sum((row.incremental_shares for row in rows), Decimal(0)),
        instruments=tuple(rows),
        quote_content_hash=quote.content_hash,
    )
