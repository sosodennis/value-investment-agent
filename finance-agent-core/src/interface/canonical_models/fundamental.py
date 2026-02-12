from __future__ import annotations

import math
from collections.abc import Mapping
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    model_serializer,
    model_validator,
)

from src.common.types import JSONObject

from .shared import (
    as_mapping,
    to_json,
    to_optional_string,
    to_string,
    validate_and_dump,
)

FUNDAMENTAL_BASE_KEYS: tuple[str, ...] = (
    "fiscal_year",
    "fiscal_period",
    "period_end_date",
    "currency",
    "company_name",
    "cik",
    "sic_code",
    "shares_outstanding",
    "total_revenue",
    "net_income",
    "income_tax_expense",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "cash_and_equivalents",
    "operating_cash_flow",
)

INDUSTRIAL_EXTENSION_KEYS: tuple[str, ...] = (
    "inventory",
    "accounts_receivable",
    "cogs",
    "rd_expense",
    "sga_expense",
    "capex",
)

FINANCIAL_SERVICES_EXTENSION_KEYS: tuple[str, ...] = (
    "loans_and_leases",
    "deposits",
    "allowance_for_credit_losses",
    "interest_income",
    "interest_expense",
    "provision_for_loan_losses",
    "risk_weighted_assets",
    "tier1_capital_ratio",
)

REAL_ESTATE_EXTENSION_KEYS: tuple[str, ...] = (
    "real_estate_assets",
    "accumulated_depreciation",
    "depreciation_and_amortization",
    "ffo",
)


def normalize_extension_type_token(value: object, context: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        raise TypeError(f"{context} must be a string")
    normalized = value.strip().lower()
    if normalized == "industrial":
        return "Industrial"
    if normalized in {
        "financialservices",
        "financial_services",
        "financial services",
        "financial",
    }:
        return "FinancialServices"
    if normalized in {"realestate", "real_estate", "real estate"}:
        return "RealEstate"
    if normalized == "general":
        return None
    raise TypeError(f"{context} has unsupported value: {value!r}")


def infer_extension_type_from_extension(extension: Mapping[str, object]) -> str | None:
    if any(key in extension for key in INDUSTRIAL_EXTENSION_KEYS):
        return "Industrial"
    if any(key in extension for key in FINANCIAL_SERVICES_EXTENSION_KEYS):
        return "FinancialServices"
    if any(key in extension for key in REAL_ESTATE_EXTENSION_KEYS):
        return "RealEstate"
    return None


class TraceableFieldModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    value: str | int | float | None
    provenance: dict[str, object] | None = None
    timestamp: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_scalar(cls, data: object) -> object:
        if data is None:
            return None
        if isinstance(data, bool):
            raise TypeError("traceable field cannot be boolean")
        if isinstance(data, str | int | float):
            if isinstance(data, float) and not math.isfinite(data):
                return {"value": None}
            return {"value": data}
        return data

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: object) -> str | int | float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError("traceable value cannot be boolean")
        if isinstance(value, str):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                return None
            return value
        raise TypeError("traceable value must be string | number | null")

    @field_validator("provenance", mode="before")
    @classmethod
    def _provenance(cls, value: object) -> dict[str, object] | None:
        if value is None:
            return None
        parsed = to_json(value, "traceable.provenance")
        if not isinstance(parsed, dict):
            raise TypeError("traceable.provenance must serialize to object")
        return parsed

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, value: object) -> str | None:
        return to_optional_string(value, "traceable.timestamp")

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str | None:
        return to_optional_string(value, "traceable.name")

    @model_serializer(mode="plain")
    def _serialize(self) -> dict[str, object]:
        data: dict[str, object] = {"value": self.value}
        if self.name is not None:
            data["name"] = self.name
        if self.provenance is not None:
            data["provenance"] = self.provenance
        if self.timestamp is not None:
            data["timestamp"] = self.timestamp
        return data


class FundamentalBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    fiscal_year: TraceableFieldModel | None = None
    fiscal_period: TraceableFieldModel | None = None
    period_end_date: TraceableFieldModel | None = None
    currency: TraceableFieldModel | None = None
    company_name: TraceableFieldModel | None = None
    cik: TraceableFieldModel | None = None
    sic_code: TraceableFieldModel | None = None
    shares_outstanding: TraceableFieldModel | None = None
    total_revenue: TraceableFieldModel | None = None
    net_income: TraceableFieldModel | None = None
    income_tax_expense: TraceableFieldModel | None = None
    total_assets: TraceableFieldModel | None = None
    total_liabilities: TraceableFieldModel | None = None
    total_equity: TraceableFieldModel | None = None
    cash_and_equivalents: TraceableFieldModel | None = None
    operating_cash_flow: TraceableFieldModel | None = None

    @model_validator(mode="before")
    @classmethod
    def _ensure_required_keys(cls, data: object) -> object:
        mapping = dict(as_mapping(data, "fundamental.base"))
        for key in FUNDAMENTAL_BASE_KEYS:
            mapping.setdefault(key, None)
        return mapping


class IndustrialExtensionModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    inventory: TraceableFieldModel | None = None
    accounts_receivable: TraceableFieldModel | None = None
    cogs: TraceableFieldModel | None = None
    rd_expense: TraceableFieldModel | None = None
    sga_expense: TraceableFieldModel | None = None
    capex: TraceableFieldModel | None = None


class FinancialServicesExtensionModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    loans_and_leases: TraceableFieldModel | None = None
    deposits: TraceableFieldModel | None = None
    allowance_for_credit_losses: TraceableFieldModel | None = None
    interest_income: TraceableFieldModel | None = None
    interest_expense: TraceableFieldModel | None = None
    provision_for_loan_losses: TraceableFieldModel | None = None


class RealEstateExtensionModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    real_estate_assets: TraceableFieldModel | None = None
    accumulated_depreciation: TraceableFieldModel | None = None
    depreciation_and_amortization: TraceableFieldModel | None = None
    ffo: TraceableFieldModel | None = None


class FinancialReportModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base: FundamentalBaseModel
    industry_type: str
    extension_type: Literal["Industrial", "FinancialServices", "RealEstate"] | None = (
        None
    )
    extension: (
        IndustrialExtensionModel
        | FinancialServicesExtensionModel
        | RealEstateExtensionModel
        | None
    ) = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_report(cls, data: object) -> object:
        mapping = dict(as_mapping(data, "financial report"))
        if "base" not in mapping:
            raise TypeError("financial report.base is required")

        extension_raw = mapping.get("extension")
        extension_map: Mapping[str, object] | None = None
        if extension_raw is not None:
            extension_map = as_mapping(extension_raw, "financial report.extension")

        extension_type = normalize_extension_type_token(
            mapping.get("extension_type"), "financial report.extension_type"
        )
        if extension_type is None and "industry_type" in mapping:
            extension_type = normalize_extension_type_token(
                mapping.get("industry_type"), "financial report.industry_type"
            )
        if extension_type is None and extension_map is not None:
            extension_type = infer_extension_type_from_extension(extension_map)
            if extension_type is None:
                raise TypeError(
                    "financial report.extension present but extension_type is unresolved"
                )

        mapping["extension_type"] = extension_type
        mapping["industry_type"] = extension_type or "General"
        if extension_map is not None:
            mapping["extension"] = extension_map
        return mapping

    @field_validator("extension", mode="before")
    @classmethod
    def _normalize_extension_field(cls, value: object, info) -> object:
        if value is None:
            return None
        extension_type = info.data.get("extension_type")
        if extension_type == "Industrial":
            return IndustrialExtensionModel.model_validate(value)
        if extension_type == "FinancialServices":
            return FinancialServicesExtensionModel.model_validate(value)
        if extension_type == "RealEstate":
            return RealEstateExtensionModel.model_validate(value)
        raise TypeError("financial report.extension requires extension_type")


class FundamentalArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    model_type: str
    company_name: str
    sector: str
    industry: str
    reasoning: str
    financial_reports: list[FinancialReportModel]
    status: Literal["done"]

    @model_validator(mode="before")
    @classmethod
    def _normalize_root(cls, data: object) -> object:
        mapping = dict(as_mapping(data, "fundamental artifact"))
        ticker = to_string(mapping.get("ticker"), "fundamental artifact.ticker")
        status = to_string(mapping.get("status"), "fundamental artifact.status")
        if status != "done":
            raise TypeError("fundamental artifact.status must be 'done'")
        mapping["ticker"] = ticker
        mapping["company_name"] = (
            to_optional_string(
                mapping.get("company_name"), "fundamental artifact.company_name"
            )
            or ticker
        )
        mapping["sector"] = (
            to_optional_string(mapping.get("sector"), "fundamental artifact.sector")
            or "Unknown"
        )
        mapping["industry"] = (
            to_optional_string(mapping.get("industry"), "fundamental artifact.industry")
            or "Unknown"
        )
        mapping["reasoning"] = (
            to_optional_string(
                mapping.get("reasoning"), "fundamental artifact.reasoning"
            )
            or ""
        )
        mapping["status"] = "done"
        return mapping

    @field_validator(
        "ticker",
        "model_type",
        "company_name",
        "sector",
        "industry",
        "reasoning",
        mode="before",
    )
    @classmethod
    def _text_fields(cls, value: object) -> str:
        return to_string(value, "fundamental artifact text")


def parse_financial_reports_model(value: object) -> list[JSONObject]:
    if not isinstance(value, list):
        raise TypeError("financial reports must be a list")
    reports: list[JSONObject] = []
    for index, item in enumerate(value):
        report = validate_and_dump(
            FinancialReportModel, item, f"financial report[{index}]", exclude_none=False
        )
        reports.append(report)
    return reports


def parse_fundamental_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        FundamentalArtifactModel, value, "fundamental artifact", exclude_none=False
    )
