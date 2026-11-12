"""Provider-neutral contracts for immutable point-in-time macro series."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .numerical_policy import using_valuation_context
from .serialization import sha256_digest


@dataclass(frozen=True)
class RetainedMacroSourceV1:
    """Original bytes and acquisition identity passed to a source provider."""

    source_id: str
    uri: str
    source_version: str
    terms_reference: str
    content: bytes
    captured_at: datetime


class MacroSeriesProviderPort(Protocol):
    """Provider adapter that reproduces one canonical macro series vintage."""

    provider_id: str

    def supports(self, series_id: str) -> bool: ...

    def reproduce_vintage(
        self, *, series_id: str, sources: tuple[RetainedMacroSourceV1, ...]
    ) -> MacroSeriesVintageV1: ...


class MacroSourceArtifactV1(BaseModel):
    """Digest-only provenance for one immutable provider source artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime

    @model_validator(mode="after")
    def timezone_required(self) -> MacroSourceArtifactV1:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("macro source capture time must include a timezone")
        return self


class MacroObservationV1(BaseModel):
    """One normalized observation whose source bytes remain externally retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    series_id: str = Field(min_length=1)
    period_start: date
    period_end: date
    value: Decimal
    unit: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete_observation(self) -> MacroObservationV1:
        if self.period_end < self.period_start:
            raise ValueError("macro observation period is reversed")
        if not self.value.is_finite():
            raise ValueError("macro observation value must be finite")
        return self


class MacroSeriesVintageV1(BaseModel):
    """Normalized series, vintage availability, and source content identities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    series_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    frequency: Literal["annual", "quarterly", "monthly", "daily"]
    unit: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    available_at: datetime
    captured_at: datetime
    artifacts: tuple[MacroSourceArtifactV1, ...] = Field(min_length=1)
    observations: tuple[MacroObservationV1, ...] = Field(min_length=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def build(
        cls,
        *,
        series_id: str,
        provider_id: str,
        frequency: Literal["annual", "quarterly", "monthly", "daily"],
        unit: str,
        source_version: str,
        available_at: datetime,
        captured_at: datetime,
        artifacts: tuple[MacroSourceArtifactV1, ...],
        observations: tuple[MacroObservationV1, ...],
    ) -> MacroSeriesVintageV1:
        payload = {
            "series_id": series_id,
            "provider_id": provider_id,
            "frequency": frequency,
            "unit": unit,
            "source_version": source_version,
            "available_at": available_at,
            "captured_at": captured_at,
            "artifacts": tuple(
                sorted(artifacts, key=lambda item: (item.source_id, item.uri))
            ),
            "observations": tuple(
                sorted(observations, key=lambda item: item.period_start)
            ),
        }
        return cls.model_validate({**payload, "content_digest": sha256_digest(payload)})

    @model_validator(mode="after")
    def provenance_and_digest_match(self) -> MacroSeriesVintageV1:
        for name, value in (
            ("available_at", self.available_at),
            ("captured_at", self.captured_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must include a timezone")
        if self.available_at > self.captured_at:
            raise ValueError("macro vintage cannot be available after capture")
        if any(item.captured_at > self.captured_at for item in self.artifacts):
            raise ValueError("macro vintage contains a later artifact capture")
        artifact_hashes = {item.content_sha256 for item in self.artifacts}
        artifact_keys = {(item.source_id, item.uri) for item in self.artifacts}
        observation_keys = {
            (item.period_start, item.period_end) for item in self.observations
        }
        if len(artifact_keys) != len(self.artifacts):
            raise ValueError("macro vintage repeats a source artifact")
        if len(observation_keys) != len(self.observations):
            raise ValueError("macro vintage repeats an observation period")
        if (
            tuple(sorted(self.artifacts, key=lambda item: (item.source_id, item.uri)))
            != self.artifacts
        ):
            raise ValueError("macro source artifacts must be in canonical order")
        if tuple(sorted(self.observations, key=lambda item: item.period_start)) != (
            self.observations
        ):
            raise ValueError("macro observations must be in chronological order")
        if any(
            observation.series_id != self.series_id
            or observation.unit != self.unit
            or observation.source_sha256 not in artifact_hashes
            for observation in self.observations
        ):
            raise ValueError("macro observation identity or source link is invalid")
        if any(
            item.period_end > self.available_at.date() for item in self.observations
        ):
            raise ValueError("macro vintage contains an observation not yet completed")
        expected = sha256_digest(self.model_dump(exclude={"content_digest"}))
        if expected != self.content_digest:
            raise ValueError("macro vintage digest does not match content")
        return self


def reproduce_macro_vintage(
    provider: MacroSeriesProviderPort,
    *,
    series_id: str,
    sources: tuple[RetainedMacroSourceV1, ...],
) -> MacroSeriesVintageV1:
    """Use an injected provider and bind every original artifact to its output."""
    if not provider.supports(series_id):
        raise ValueError("macro provider does not support the requested series")
    vintage = provider.reproduce_vintage(series_id=series_id, sources=sources)
    if vintage.series_id != series_id or vintage.provider_id != provider.provider_id:
        raise ValueError("macro provider returned a different series or provider")
    artifacts = tuple(
        MacroSourceArtifactV1(
            source_id=source.source_id,
            uri=source.uri,
            source_version=source.source_version,
            terms_reference=source.terms_reference,
            content_sha256=hashlib.sha256(source.content).hexdigest(),
            captured_at=source.captured_at,
        )
        for source in sources
    )
    if sorted(sha256_digest(item) for item in artifacts) != sorted(
        sha256_digest(item) for item in vintage.artifacts
    ):
        raise ValueError("macro provider did not bind every original source artifact")
    return vintage


def select_macro_vintage(
    vintages: tuple[MacroSeriesVintageV1, ...],
    *,
    series_id: str,
    valuation_at: datetime,
) -> MacroSeriesVintageV1:
    """Select one latest source-independent vintage available at the cutoff."""
    if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
        raise ValueError("valuation timestamp must include a timezone")
    cutoff = valuation_at.astimezone(UTC)
    eligible = tuple(
        {
            vintage.content_digest: vintage
            for vintage in vintages
            if vintage.series_id == series_id
            and vintage.available_at.astimezone(UTC) <= cutoff
        }.values()
    )
    if not eligible:
        raise ValueError("no macro series vintage is available at the valuation time")
    latest_at = max(item.available_at.astimezone(UTC) for item in eligible)
    latest = tuple(
        item for item in eligible if item.available_at.astimezone(UTC) == latest_at
    )
    if len(latest) != 1:
        raise ValueError("macro series vintage selection is ambiguous")
    return latest[0]


class NominalGdpGrowthCeilingV1(BaseModel):
    """Versioned deterministic derivation from a source-neutral GDP vintage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = "nominal-gdp-cagr-ceiling-v1"
    vintage_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    valuation_at: datetime
    available_at: datetime
    start_year: int
    end_year: int
    start_value: Decimal = Field(gt=0)
    end_value: Decimal = Field(gt=0)
    horizon_years: int = Field(gt=0)
    nominal_gdp_cagr: Decimal
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    @using_valuation_context
    def derive(
        cls,
        vintage: MacroSeriesVintageV1,
        *,
        valuation_at: datetime,
        horizon_years: int = 10,
    ) -> NominalGdpGrowthCeilingV1:
        if (
            vintage.series_id != "us.nominal_gdp"
            or vintage.unit != "USD millions"
            or vintage.frequency != "annual"
        ):
            raise ValueError("GDP ceiling requires the canonical nominal GDP series")
        if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
            raise ValueError("valuation timestamp must include a timezone")
        valuation_at = valuation_at.astimezone(UTC)
        available_at = vintage.available_at.astimezone(UTC)
        if available_at > valuation_at:
            raise ValueError("GDP vintage is unavailable at the valuation timestamp")
        if horizon_years < 1:
            raise ValueError("GDP ceiling horizon must be positive")
        eligible: dict[int, MacroObservationV1] = {}
        for item in vintage.observations:
            if (
                item.period_start.month == 1
                and item.period_start.day == 1
                and item.period_end.month == 12
                and item.period_end.day == 31
                and item.period_start.year == item.period_end.year
                and item.period_end <= valuation_at.date()
            ):
                eligible[item.period_end.year] = item
        if not eligible:
            raise ValueError("GDP vintage has no annual observation by valuation date")
        end_year = max(eligible)
        start_year = end_year - horizon_years
        if start_year not in eligible:
            raise ValueError("GDP vintage lacks a complete nominal GDP horizon")
        if any(year not in eligible for year in range(start_year, end_year + 1)):
            raise ValueError("GDP vintage has a gap in the nominal GDP horizon")
        start_value, end_value = eligible[start_year].value, eligible[end_year].value
        if start_value <= 0 or end_value <= 0:
            raise ValueError("GDP ceiling endpoints must be positive")
        growth = (end_value / start_value) ** (Decimal(1) / Decimal(horizon_years)) - 1
        payload = {
            "policy_version": "nominal-gdp-cagr-ceiling-v1",
            "vintage_digest": vintage.content_digest,
            "valuation_at": valuation_at,
            "available_at": available_at,
            "start_year": start_year,
            "end_year": end_year,
            "start_value": start_value,
            "end_value": end_value,
            "horizon_years": horizon_years,
            "nominal_gdp_cagr": growth,
        }
        return cls.model_validate({**payload, "content_digest": sha256_digest(payload)})

    @model_validator(mode="after")
    def digest_matches(self) -> NominalGdpGrowthCeilingV1:
        if self.valuation_at.tzinfo is None or self.valuation_at.utcoffset() is None:
            raise ValueError("valuation timestamp must include a timezone")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("GDP vintage availability must include a timezone")
        expected = sha256_digest(self.model_dump(exclude={"content_digest"}))
        if expected != self.content_digest:
            raise ValueError("GDP ceiling digest does not match content")
        return self
