from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from src.agents.fundamental.domain.shared.contracts.traceable import (
    ComputedProvenance,
    TraceableField,
)

from .extractor import SearchConfig, SearchType, SECReportExtractor
from .report_contracts import BaseFinancialModel, RealEstateExtension

T = TypeVar("T")


def build_real_estate_extension(
    *,
    extractor: SECReportExtractor,
    base_model: BaseFinancialModel,
    resolve_configs_fn: Callable[..., list[SearchConfig]],
    extract_field_fn: Callable[
        [SECReportExtractor, list[SearchConfig], str, type[T]], TraceableField[T]
    ],
    is_statement_tokens: list[str],
    bs_statement_tokens: list[str],
    usd_units: list[str],
) -> RealEstateExtension:
    def C(
        regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
    ) -> SearchConfig:
        return SearchType.CONSOLIDATED(
            regex,
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
        )

    def R(field_key: str) -> list[SearchConfig]:
        return resolve_configs_fn(
            field_key=field_key,
            industry="Real Estate",
            issuer=extractor.ticker,
        )

    tf_re_assets = extract_field_fn(
        extractor,
        R("real_estate_assets")
        or [
            C(
                "us-gaap:RealEstateInvestmentPropertyNet",
                bs_statement_tokens,
                "instant",
                usd_units,
            )
        ],
        "Real Estate Assets (at cost)",
        float,
    )

    tf_acc_dep = extract_field_fn(
        extractor,
        R("accumulated_depreciation")
        or [
            C(
                "us-gaap:RealEstateInvestmentPropertyAccumulatedDepreciation",
                bs_statement_tokens,
                "instant",
                usd_units,
            )
        ],
        "Accumulated Depreciation",
        float,
    )

    tf_dep = extract_field_fn(
        extractor,
        R("real_estate_dep_amort")
        or [
            C(
                "us-gaap:DepreciationAndAmortizationInRealEstate",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
            C(
                "us-gaap:DepreciationAndAmortization",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
        ],
        "Depreciation & Amortization",
        float,
    )

    tf_gain = extract_field_fn(
        extractor,
        R("gain_on_sale")
        or [
            C(
                "us-gaap:GainLossOnSaleOfRealEstateInvestmentProperty",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
            C(
                "us-gaap:GainLossOnSaleOfProperties",
                is_statement_tokens,
                "duration",
                usd_units,
            ),
        ],
        "Gain on Sale of Properties",
        float,
    )

    tf_net_income = base_model.net_income
    ni_val = tf_net_income.value if tf_net_income.value is not None else 0.0
    dep_val = tf_dep.value if tf_dep.value is not None else 0.0
    gain_val = tf_gain.value if tf_gain.value is not None else 0.0
    ffo_val = ni_val + dep_val - gain_val

    tf_ffo = TraceableField(
        name="FFO (Funds From Operations)",
        value=ffo_val,
        provenance=ComputedProvenance(
            op_code="FFO_CALC",
            expression="NetIncome + Depreciation - GainOnSale",
            inputs={
                "Net Income": tf_net_income,
                "Depreciation": tf_dep,
                "Gain on Sale": tf_gain,
            },
        ),
    )

    return RealEstateExtension(
        real_estate_assets=tf_re_assets,
        accumulated_depreciation=tf_acc_dep,
        depreciation_and_amortization=tf_dep,
        gain_on_sale=tf_gain,
        ffo=tf_ffo,
    )
