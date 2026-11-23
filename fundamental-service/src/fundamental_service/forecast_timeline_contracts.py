from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DATED_FCFF_POLICY = "fcff-uniform-accrual-period-end-act365f-v1"


class ForecastPeriodV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ordinal: int = Field(ge=1)
    period_start: date
    period_end: date
    included_start: date
    cash_flow_date: date
    full_period_days: int = Field(ge=365, le=366)
    included_days: int = Field(ge=1, le=366)
    discount_days: int = Field(ge=1)

    @model_validator(mode="after")
    def dates_match_counts(self) -> "ForecastPeriodV1":
        if not self.period_start <= self.included_start <= self.period_end:
            raise ValueError("included coverage must be within its annual period")
        if self.cash_flow_date != self.period_end:
            raise ValueError("dated FCFF settles at annual period end")
        if self.full_period_days != (self.period_end - self.period_start).days + 1:
            raise ValueError("full-period day count does not match its dates")
        if self.included_days != (self.period_end - self.included_start).days + 1:
            raise ValueError("included day count does not match its dates")
        return self


class ForecastTimelineV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal["fcff-uniform-accrual-period-end-act365f-v1"]
    calendar_basis: Literal["source-fixed-month-day", "source-month-end"]
    label_basis: Literal["period-end-year"] = "period-end-year"
    valuation_date: date
    source_period_start: date
    source_period_end: date
    source_revenue_fact_id: str = Field(min_length=1)
    calendar_fact_ids: tuple[str, ...] = Field(min_length=3, max_length=3)
    periods: tuple[ForecastPeriodV1, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def schedule_is_contiguous(self) -> "ForecastTimelineV1":
        if len(set(self.calendar_fact_ids)) != 3:
            raise ValueError("calendar evidence must identify three distinct facts")
        if self.source_revenue_fact_id != self.calendar_fact_ids[-1]:
            raise ValueError("the latest calendar fact must be the revenue anchor")
        if (
            not self.source_period_end
            <= self.valuation_date
            < self.periods[0].period_end
        ):
            raise ValueError("valuation date must precede the first forecast end")
        previous_end = self.source_period_end
        for ordinal, period in enumerate(self.periods, start=1):
            if (
                period.ordinal != ordinal
                or period.period_start != previous_end + timedelta(days=1)
            ):
                raise ValueError("forecast periods must be ordered and contiguous")
            included_start = max(
                period.period_start, self.valuation_date + timedelta(days=1)
            )
            if period.included_start != included_start:
                raise ValueError("included coverage must exclude elapsed accrual")
            if (
                period.discount_days
                != (period.cash_flow_date - self.valuation_date).days
            ):
                raise ValueError("discount days must be measured from valuation date")
            previous_end = period.period_end
        return self
