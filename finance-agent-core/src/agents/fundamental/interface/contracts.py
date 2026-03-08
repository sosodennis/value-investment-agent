from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    model_serializer,
    model_validator,
)

from src.agents.fundamental.domain.report_semantics import (
    FUNDAMENTAL_BASE_KEYS,
)
from src.interface.artifacts.artifact_model_shared import (
    as_mapping,
    to_optional_string,
    to_string,
    validate_and_dump,
    validate_list_and_dump,
)
from src.shared.kernel.types import JSONObject

from .types import (
    FundamentalText,
    OptionalFundamentalNumber,
    OptionalFundamentalText,
    TraceableOptionalText,
    TraceableProvenance,
    TraceableValue,
)

CANONICAL_INDUSTRY_TYPES: tuple[str, ...] = (
    "General",
    "Industrial",
    "FinancialServices",
    "RealEstate",
)
CANONICAL_EXTENSION_TYPES: tuple[str, ...] = (
    "Industrial",
    "FinancialServices",
    "RealEstate",
)


def _parse_canonical_industry_type(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    token = to_string(value, context).strip()
    if token in CANONICAL_INDUSTRY_TYPES:
        return token
    allowed = ", ".join(CANONICAL_INDUSTRY_TYPES)
    raise TypeError(f"{context} must be canonical token ({allowed})")


def _parse_canonical_extension_type(value: object, *, context: str) -> str | None:
    if value is None:
        return None
    token = to_string(value, context).strip()
    if token in CANONICAL_EXTENSION_TYPES:
        return token
    allowed = ", ".join(CANONICAL_EXTENSION_TYPES)
    raise TypeError(f"{context} must be canonical token ({allowed})")


class TraceableFieldModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: TraceableOptionalText = None
    value: TraceableValue
    provenance: TraceableProvenance = None
    timestamp: TraceableOptionalText = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_scalar(cls, data: object) -> object:
        if data is None:
            return None
        if isinstance(data, Mapping):
            return data
        if isinstance(data, bool):
            raise TypeError("traceable field cannot be boolean")
        raise TypeError("traceable field must be an object")

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
    weighted_average_shares_basic: TraceableFieldModel | None = None
    weighted_average_shares_diluted: TraceableFieldModel | None = None
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
    selling_expense: TraceableFieldModel | None = None
    ga_expense: TraceableFieldModel | None = None
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
    gain_on_sale: TraceableFieldModel | None = None
    ffo: TraceableFieldModel | None = None


class FilingMetadataModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    form: str | None = None
    accession_number: str | None = None
    filing_date: str | None = None
    accepted_datetime: str | None = None
    period_of_report: str | None = None
    requested_fiscal_year: int | None = None
    matched_fiscal_year: int | None = None
    selection_mode: str | None = None


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
    filing_metadata: FilingMetadataModel | None = None

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

        extension_type = _parse_canonical_extension_type(
            mapping.get("extension_type"),
            context="financial report.extension_type",
        )
        industry_type = _parse_canonical_industry_type(
            mapping.get("industry_type"),
            context="financial report.industry_type",
        )
        if (
            industry_type is not None
            and extension_type is not None
            and industry_type != extension_type
        ):
            raise TypeError(
                "financial report.industry_type conflicts with extension_type"
            )
        if extension_type is None and extension_map is not None:
            raise TypeError(
                "financial report.extension requires extension_type in canonical payload"
            )

        resolved_industry_type = industry_type
        if resolved_industry_type is None and extension_type is not None:
            resolved_industry_type = extension_type
        mapping["extension_type"] = extension_type
        mapping["industry_type"] = resolved_industry_type or "General"
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

    ticker: FundamentalText
    model_type: FundamentalText
    company_name: FundamentalText
    sector: FundamentalText
    industry: FundamentalText
    reasoning: FundamentalText
    financial_reports: list[FinancialReportModel]
    forward_signals: list[dict[str, object]] | None = None
    valuation_diagnostics: dict[str, object] | None = None
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


class FundamentalPreviewInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: FundamentalText
    company_name: FundamentalText
    sector: FundamentalText
    industry: FundamentalText
    status: FundamentalText
    selected_model: OptionalFundamentalText = None
    model_type: OptionalFundamentalText = None
    valuation_summary: OptionalFundamentalText = None
    valuation_score: OptionalFundamentalNumber = None
    assumption_breakdown: dict[str, object] | None = None
    data_freshness: dict[str, object] | None = None
    assumption_risk_level: OptionalFundamentalText = None
    data_quality_flags: list[str] | None = None
    time_alignment_status: OptionalFundamentalText = None
    forward_signal_summary: dict[str, object] | None = None
    forward_signal_risk_level: OptionalFundamentalText = None
    forward_signal_evidence_count: OptionalFundamentalNumber = None


def _inject_default_provenance_into_field(
    value: object, *, context: str
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    field = dict(value)
    if "value" not in field:
        raise TypeError(f"{context} must contain 'value'")
    if field.get("provenance") is None:
        field["provenance"] = {
            "type": "MANUAL",
            "description": "Canonicalized without explicit provenance",
        }
    return field


def _inject_default_provenance_into_report(
    report: Mapping[str, object], *, context: str
) -> JSONObject:
    payload: JSONObject = dict(report)
    base_raw = payload.get("base")
    if not isinstance(base_raw, Mapping):
        raise TypeError(f"{context}.base must be an object")

    base: JSONObject = {}
    for key, value in base_raw.items():
        if value is None:
            base[key] = None
            continue
        if isinstance(value, Mapping):
            base[key] = _inject_default_provenance_into_field(
                value,
                context=f"{context}.base.{key}",
            )
            continue
        raise TypeError(f"{context}.base.{key} must be an object")
    payload["base"] = base

    extension_raw = payload.get("extension")
    if extension_raw is None:
        return payload
    if not isinstance(extension_raw, Mapping):
        raise TypeError(f"{context}.extension must be an object")

    extension: JSONObject = {}
    for key, value in extension_raw.items():
        if value is None:
            extension[key] = None
            continue
        if isinstance(value, Mapping):
            extension[key] = _inject_default_provenance_into_field(
                value,
                context=f"{context}.extension.{key}",
            )
            continue
        raise TypeError(f"{context}.extension.{key} must be an object")
    payload["extension"] = extension
    return payload


def parse_financial_reports_model(
    value: object,
    context: str = "financial reports",
    *,
    inject_default_provenance: bool = False,
) -> list[JSONObject]:
    reports = validate_list_and_dump(
        FinancialReportModel,
        value,
        context,
        exclude_none=False,
    )
    if not inject_default_provenance:
        return reports
    return [
        _inject_default_provenance_into_report(
            report,
            context=f"{context}[{index}]",
        )
        for index, report in enumerate(reports)
    ]


def parse_fundamental_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        FundamentalArtifactModel, value, "fundamental artifact", exclude_none=False
    )
