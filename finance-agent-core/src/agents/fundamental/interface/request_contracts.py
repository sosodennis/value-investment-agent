"""Caller-owned time and fiscal-period contracts for Fundamental valuations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FiscalSelectorVersion = Literal["fundamental.fiscal-period-selector.v1"]


class _StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FiscalPeriodV1(_StrictRequestModel):
    """An issuer fiscal year requested by an explicit-period selector."""

    fiscal_year: int = Field(ge=1900, le=2200)


class LatestCompleteFiscalPeriodSelectorV1(_StrictRequestModel):
    version: FiscalSelectorVersion = "fundamental.fiscal-period-selector.v1"
    mode: Literal["latest_complete"]
    count: int = Field(default=3, ge=1, le=10)


class ExplicitFiscalPeriodSelectorV1(_StrictRequestModel):
    version: FiscalSelectorVersion = "fundamental.fiscal-period-selector.v1"
    mode: Literal["explicit_periods"]
    periods: tuple[FiscalPeriodV1, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def periods_are_unique(self) -> ExplicitFiscalPeriodSelectorV1:
        years = tuple(period.fiscal_year for period in self.periods)
        if len(years) != len(set(years)):
            raise ValueError("explicit fiscal periods must be unique")
        return self


FiscalPeriodSelectorV1 = Annotated[
    LatestCompleteFiscalPeriodSelectorV1 | ExplicitFiscalPeriodSelectorV1,
    Field(discriminator="mode"),
]


class FundamentalRequestTimingV1(_StrictRequestModel):
    """The immutable timing decision made when a valuation request is accepted."""

    contract_version: Literal["fundamental.request.v1"]
    valuation_timestamp: datetime
    fiscal_period_selector: FiscalPeriodSelectorV1
    requested_as_of: datetime | None = None
    timestamp_source: Literal["caller_requested_as_of", "accepted_at"]

    @model_validator(mode="after")
    def timestamps_are_aware_and_bound(self) -> FundamentalRequestTimingV1:
        for name, value in (
            ("valuation_timestamp", self.valuation_timestamp),
            ("requested_as_of", self.requested_as_of),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        if self.requested_as_of is not None and (
            self.valuation_timestamp.astimezone(UTC)
            != self.requested_as_of.astimezone(UTC)
        ):
            raise ValueError("valuation_timestamp must equal requested_as_of")
        expected_source = (
            "caller_requested_as_of"
            if self.requested_as_of is not None
            else "accepted_at"
        )
        if self.timestamp_source != expected_source:
            raise ValueError("timestamp_source does not match the timing decision")
        return self

    @classmethod
    def accept(
        cls,
        payload: Mapping[str, object],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> FundamentalRequestTimingV1:
        """Resolve caller time once and materialize the default selector."""

        context = payload.get("valuation_context")
        context_mapping = context if isinstance(context, Mapping) else {}
        requested_raw = payload.get("requested_as_of")
        requested_as_of = (
            cls._coerce_timestamp(requested_raw, name="requested_as_of")
            if requested_raw is not None
            else None
        )
        context_timestamp = context_mapping.get("valuation_timestamp")
        existing_timestamp = (
            cls._coerce_timestamp(context_timestamp, name="valuation_timestamp")
            if context_timestamp is not None
            else None
        )
        if requested_as_of is not None and existing_timestamp is not None:
            if requested_as_of != existing_timestamp:
                raise ValueError(
                    "requested_as_of must match valuation_context.valuation_timestamp"
                )
        effective_timestamp = requested_as_of or existing_timestamp
        source: Literal["caller_requested_as_of", "accepted_at"]
        if effective_timestamp is None:
            source = "accepted_at"
            effective_timestamp = (clock or (lambda: datetime.now(UTC)))()
            effective_timestamp = cls._coerce_timestamp(
                effective_timestamp, name="accepted_at"
            )
        else:
            source = "caller_requested_as_of" if requested_as_of else "accepted_at"

        selector_raw = payload.get("fiscal_period_selector") or context_mapping.get(
            "fiscal_period_selector"
        )
        selector = cls._parse_selector(selector_raw)
        return cls(
            contract_version="fundamental.request.v1",
            valuation_timestamp=effective_timestamp,
            fiscal_period_selector=selector,
            requested_as_of=requested_as_of,
            timestamp_source=source,
        )

    @staticmethod
    def _coerce_timestamp(value: object, *, name: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must include a timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _parse_selector(value: object) -> FiscalPeriodSelectorV1:
        if value is None:
            return LatestCompleteFiscalPeriodSelectorV1(mode="latest_complete")
        if not isinstance(value, Mapping):
            raise ValueError("fiscal_period_selector must be an object")
        try:
            if value.get("mode") == "latest_complete":
                return LatestCompleteFiscalPeriodSelectorV1.model_validate(value)
            if value.get("mode") == "explicit_periods":
                normalized = dict(value)
                periods = normalized.get("periods")
                if isinstance(periods, list):
                    normalized["periods"] = tuple(periods)
                return ExplicitFiscalPeriodSelectorV1.model_validate(normalized)
        except ValueError as exc:
            raise ValueError(f"invalid fiscal_period_selector: {exc}") from exc
        raise ValueError("fiscal_period_selector.mode is unsupported")


def apply_request_timing(
    payload: Mapping[str, object], timing: FundamentalRequestTimingV1
) -> dict[str, object]:
    """Return the service-shaped payload with the accepted timing decision."""

    context_raw = payload.get("valuation_context")
    context = dict(context_raw) if isinstance(context_raw, Mapping) else {}
    context["valuation_timestamp"] = timing.valuation_timestamp.isoformat()
    context["fiscal_period_selector"] = timing.fiscal_period_selector.model_dump(
        mode="json"
    )
    updated = dict(payload)
    updated.pop("requested_as_of", None)
    updated.pop("fiscal_period_selector", None)
    updated["valuation_context"] = context
    return updated


__all__ = [
    "ExplicitFiscalPeriodSelectorV1",
    "FiscalPeriodSelectorV1",
    "FiscalPeriodV1",
    "FundamentalRequestTimingV1",
    "LatestCompleteFiscalPeriodSelectorV1",
    "apply_request_timing",
]
