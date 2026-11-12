"""Provider-neutral, immutable country and industry reference evidence."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .serialization import sha256_digest
from .source_evidence import RetainedSourceV1, SourceArtifactV1

ReferenceMetric = Literal[
    "industry.unlevered_beta", "country.equity_risk_premium", "country.tax_rate"
]


class ReferenceContextV1(BaseModel):
    """Source-declared methodology context, without approving an issuer policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    raw_value: str = Field(min_length=1)
    numeric_encoding: Literal["binary64", "decimal_text", "text"]
    number_format: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReferenceRowV1(BaseModel):
    """A published value or explicit missing cell, including its original encoding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(min_length=1)
    subject_kind: Literal["country", "industry", "aggregate"]
    value: Decimal | None
    missing_reason: (
        Literal["empty_cell", "source_marker", "cell_error", "formula_cache_missing"]
        | None
    )
    raw_value: str
    numeric_encoding: Literal["binary64", "decimal_text", "missing"]
    value_basis: Literal[
        "published_cell", "published_biff_cache", "published_ooxml_cache"
    ]
    source_formula: str | None = None
    source_formula_attributes: tuple[tuple[str, str], ...] = ()
    number_format: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def original_number_matches(self) -> ReferenceRowV1:
        if self.source_formula_attributes != tuple(
            sorted(self.source_formula_attributes)
        ):
            raise ValueError("reference formula attributes are not canonical")
        if len(dict(self.source_formula_attributes)) != len(
            self.source_formula_attributes
        ):
            raise ValueError("reference formula attributes repeat an identity")
        if self.source_formula is None and self.source_formula_attributes:
            raise ValueError("reference formula attributes require a formula")
        if (self.source_formula is not None) != (
            self.value_basis == "published_ooxml_cache"
        ):
            raise ValueError("reference formula and value basis do not match")
        if self.subject != self.subject.strip():
            raise ValueError("reference subject must use canonical whitespace")
        if self.value is None:
            if self.missing_reason is None or self.numeric_encoding != "missing":
                raise ValueError("missing reference value requires a source reason")
        else:
            if self.missing_reason is not None or not self.value.is_finite():
                raise ValueError("reference value must be finite and observed")
            if self.numeric_encoding == "binary64":
                original = float.fromhex(self.raw_value)
                if original.hex() != self.raw_value:
                    raise ValueError("binary reference number must use canonical hex")
                reproduced = Decimal.from_float(original)
            elif self.numeric_encoding == "decimal_text":
                reproduced = Decimal(self.raw_value)
            else:
                raise ValueError("observed reference value requires numeric evidence")
            if reproduced != self.value:
                raise ValueError("reference value does not match its source encoding")
        return self


class MarketReferenceVintageV1(BaseModel):
    """One metric and population, without selecting an issuer or approving policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: ReferenceMetric
    population: str = Field(min_length=1)
    unit: Literal["multiple", "fraction"]
    provider_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_updated_on: date
    available_at: datetime
    captured_at: datetime
    artifacts: tuple[SourceArtifactV1, ...] = Field(min_length=1)
    context: tuple[ReferenceContextV1, ...]
    rows: tuple[ReferenceRowV1, ...] = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        metric: ReferenceMetric,
        population: str,
        unit: Literal["multiple", "fraction"],
        provider_id: str,
        source_version: str,
        source_updated_on: date,
        available_at: datetime,
        captured_at: datetime,
        artifacts: tuple[SourceArtifactV1, ...],
        context: tuple[ReferenceContextV1, ...] = (),
        rows: tuple[ReferenceRowV1, ...],
    ) -> MarketReferenceVintageV1:
        payload = {
            "metric": metric,
            "population": population,
            "unit": unit,
            "provider_id": provider_id,
            "source_version": source_version,
            "source_updated_on": source_updated_on,
            "available_at": available_at,
            "captured_at": captured_at,
            "artifacts": tuple(sorted(artifacts, key=lambda x: (x.source_id, x.uri))),
            "context": tuple(sorted(context, key=lambda x: x.name)),
            "rows": tuple(sorted(rows, key=lambda x: (x.subject_kind, x.subject))),
        }
        return cls.model_validate({**payload, "content_digest": sha256_digest(payload)})

    @model_validator(mode="after")
    def canonical_evidence(self) -> MarketReferenceVintageV1:
        for timestamp in (self.available_at, self.captured_at):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("reference timestamps require a timezone")
        if (
            self.available_at > self.captured_at
            or self.source_updated_on > self.available_at.date()
            or any(item.captured_at > self.captured_at for item in self.artifacts)
        ):
            raise ValueError("reference source dates are inconsistent")
        keys = {(row.subject_kind, row.subject) for row in self.rows}
        if len(keys) != len(self.rows):
            raise ValueError("reference contains duplicate or conflicting subjects")
        if self.rows != tuple(
            sorted(self.rows, key=lambda x: (x.subject_kind, x.subject))
        ):
            raise ValueError("reference rows are not in canonical order")
        if self.artifacts != tuple(
            sorted(self.artifacts, key=lambda x: (x.source_id, x.uri))
        ) or len({(x.source_id, x.uri) for x in self.artifacts}) != len(self.artifacts):
            raise ValueError("reference source artifacts are repeated or unordered")
        hashes = {item.content_sha256 for item in self.artifacts}
        if any(row.source_sha256 not in hashes for row in self.rows) or any(
            item.source_sha256 not in hashes for item in self.context
        ):
            raise ValueError("reference row is not bound to an original source")
        if self.context != tuple(sorted(self.context, key=lambda x: x.name)) or len(
            {x.name for x in self.context}
        ) != len(self.context):
            raise ValueError("reference context is repeated or unordered")
        expected_unit = (
            "multiple" if self.metric == "industry.unlevered_beta" else "fraction"
        )
        kinds = (
            {"industry", "aggregate"}
            if expected_unit == "multiple"
            else (
                {"country", "aggregate"}
                if self.metric == "country.equity_risk_premium"
                else {"country"}
            )
        )
        if self.unit != expected_unit or any(
            x.subject_kind not in kinds for x in self.rows
        ):
            raise ValueError("reference units or subject kinds do not match the metric")
        if self.metric != "industry.unlevered_beta" and any(
            row.value is not None and not Decimal(0) <= row.value < Decimal(1)
            for row in self.rows
        ):
            raise ValueError("reference numeric value is outside the metric domain")
        if self.content_digest != sha256_digest(
            self.model_dump(exclude={"content_digest"})
        ):
            raise ValueError("reference digest does not match content")
        return self


class MarketReferenceProviderPort(Protocol):
    """Reproduce a reference table from original bytes without issuer selection."""

    provider_id: str

    def supports(self, metric: ReferenceMetric) -> bool: ...

    def reproduce_vintage(
        self, *, metric: ReferenceMetric, sources: tuple[RetainedSourceV1, ...]
    ) -> MarketReferenceVintageV1: ...


def reproduce_reference_vintage(
    provider: MarketReferenceProviderPort,
    *,
    metric: ReferenceMetric,
    sources: tuple[RetainedSourceV1, ...],
) -> MarketReferenceVintageV1:
    if not provider.supports(metric):
        raise ValueError("reference provider does not support this metric")
    vintage = provider.reproduce_vintage(metric=metric, sources=sources)
    if vintage.metric != metric or vintage.provider_id != provider.provider_id:
        raise ValueError("reference provider returned a different metric or identity")
    originals = tuple(
        SourceArtifactV1(
            source_id=x.source_id,
            uri=x.uri,
            source_version=x.source_version,
            terms_reference=x.terms_reference,
            captured_at=x.captured_at,
            content_sha256=hashlib.sha256(x.content).hexdigest(),
        )
        for x in sources
    )
    if sorted(sha256_digest(x) for x in originals) != sorted(
        sha256_digest(x) for x in vintage.artifacts
    ):
        raise ValueError("reference provider did not bind every original source")
    return vintage


def select_reference_vintage(
    vintages: tuple[MarketReferenceVintageV1, ...],
    *,
    metric: ReferenceMetric,
    population: str,
    valuation_at: datetime,
) -> MarketReferenceVintageV1:
    if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
        raise ValueError("valuation timestamp requires a timezone")
    eligible = {
        x.content_digest: x
        for x in vintages
        if x.metric == metric
        and x.population == population
        and x.available_at <= valuation_at
    }
    if not eligible:
        raise ValueError("no reference vintage is available at the valuation time")
    latest = max(x.available_at for x in eligible.values())
    matches = [x for x in eligible.values() if x.available_at == latest]
    if len(matches) != 1:
        raise ValueError("reference vintage selection is ambiguous")
    return matches[0]
