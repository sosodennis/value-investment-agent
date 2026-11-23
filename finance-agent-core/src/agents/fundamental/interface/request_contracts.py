"""Caller-owned time and fiscal-period contracts for Fundamental valuations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalForwardEvidenceReviewRefV1,
)
from src.shared.artifacts.fundamental_contracts import CanonicalDecimal

FiscalSelectorVersion = Literal["fundamental.fiscal-period-selector.v1"]


class _StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FundamentalValuationRevisionSourceV1(_StrictRequestModel):
    thread_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    artifact_id: str = Field(min_length=1, max_length=128)
    preparation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class FundamentalRevisionForwardReferenceV1(_StrictRequestModel):
    claim_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1, max_length=2048)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    citation: str = Field(min_length=20, max_length=8192)
    license_reference: str = Field(min_length=1, max_length=2048)


class FundamentalValuationRevisionV1(_StrictRequestModel):
    source: FundamentalValuationRevisionSourceV1
    path: Literal["assumptions.terminal_growth"]
    value: CanonicalDecimal = Field(max_length=128)
    reason: str = Field(min_length=1, max_length=8192)
    forward_reference: FundamentalRevisionForwardReferenceV1 | None = None
    forward_review_ref: FundamentalForwardEvidenceReviewRefV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def reason_is_nonblank(self) -> FundamentalValuationRevisionV1:
        if not self.reason.strip():
            raise ValueError("revision reason must not be blank")
        if (self.forward_reference is None) != (self.forward_review_ref is None):
            raise ValueError(
                "researched revisions require both forward_reference and forward_review_ref"
            )
        return self


class FundamentalValuationIntentV1(_StrictRequestModel):
    """Caller controls without service preparation or provenance authority."""

    contract_version: Literal["fundamental.v1"] = "fundamental.v1"
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"] | None = None
    model_version: str | None = Field(default=None, min_length=1)
    policy_id: str | None = Field(default=None, min_length=1)
    assumptions: dict[str, JsonValue] | None = None
    uncertainty: dict[str, JsonValue] | None = None
    requested_as_of: str | None = None
    fiscal_period_selector: dict[str, JsonValue] | None = None
    revision: FundamentalValuationRevisionV1 | None = None

    @model_validator(mode="after")
    def revision_retains_source_controls(self) -> FundamentalValuationIntentV1:
        if self.revision is not None and any(
            value is not None
            for value in (
                self.assumptions,
                self.uncertainty,
                self.requested_as_of,
                self.fiscal_period_selector,
            )
        ):
            raise ValueError("revision controls come from the retained source report")
        return self


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
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{name} must be an ISO-8601 datetime") from exc
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
    if "historical_facts" not in updated:
        identity = updated.get("identity")
        required_fields = updated.get("required_fields") or context.get(
            "required_fields"
        )
        source_selection_policy = context.get("source_selection_policy")
        coverage_profile = context.get("coverage_profile")
        if (
            isinstance(identity, Mapping)
            and isinstance(required_fields, list | tuple)
            and required_fields
            and isinstance(source_selection_policy, str)
            and isinstance(coverage_profile, str)
        ):
            updated["snapshot_selector"] = {
                "contract_version": "fundamental.v1",
                "identity": dict(identity),
                "valuation_timestamp": timing.valuation_timestamp.isoformat(),
                "fiscal_period_selector": timing.fiscal_period_selector.model_dump(
                    mode="json"
                ),
                "source_selection_policy": source_selection_policy,
                "coverage_profile": coverage_profile,
                "required_fields": list(required_fields),
            }
            updated.pop("required_fields", None)
            context.pop("required_fields", None)
    return updated


__all__ = [
    "FundamentalValuationIntentV1",
    "FundamentalValuationRevisionV1",
    "FundamentalValuationRevisionSourceV1",
    "ExplicitFiscalPeriodSelectorV1",
    "FiscalPeriodSelectorV1",
    "FiscalPeriodV1",
    "FundamentalRequestTimingV1",
    "LatestCompleteFiscalPeriodSelectorV1",
    "apply_request_timing",
]
