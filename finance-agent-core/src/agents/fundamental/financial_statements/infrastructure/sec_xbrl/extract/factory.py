from functools import partial
from typing import Literal, TypeVar

from src.agents.fundamental.shared.contracts.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)
from src.shared.kernel.tools.logger import get_logger

from ..fetch.resolver import ParsedCandidate
from ..map.base_model_mapping_resolver_service import (
    resolve_configs as resolve_configs_util,
)
from ..map.extension_token_normalizer import normalize_extension_type_token
from ..map.mapping import get_mapping_registry
from .base_model_assembler import assemble_base_financial_model
from .base_model_context_balance_builder import build_context_balance_fields
from .base_model_debt_builder import DebtBuilderOps, build_total_debt_field
from .base_model_debt_policy_service import (
    log_total_debt_diagnostics as log_total_debt_diagnostics_util,
)
from .base_model_debt_policy_service import (
    resolve_total_debt_policy as resolve_total_debt_policy_util,
)
from .base_model_extraction_context import BaseModelExtractionContext
from .base_model_field_extraction_service import (
    build_resolution_stages as build_resolution_stages_util,
)
from .base_model_field_extraction_service import (
    collect_parsed_candidates as collect_parsed_candidates_util,
)
from .base_model_field_extraction_service import extract_field as extract_field_util
from .base_model_income_cashflow_builder import (
    IncomeCashflowOps,
    build_income_cashflow_and_derived_fields,
)
from .derived_field_service import (
    build_real_estate_debt_combined_ex_leases as build_real_estate_debt_combined_ex_leases_util,
)
from .derived_field_service import (
    build_total_debt_with_policy as build_total_debt_with_policy_util,
)
from .derived_field_service import (
    calc_invested_capital as calc_invested_capital_util,
)
from .derived_field_service import (
    calc_nopat as calc_nopat_util,
)
from .derived_field_service import (
    calc_ratio as calc_ratio_util,
)
from .derived_field_service import (
    calc_subtract as calc_subtract_util,
)
from .derived_field_service import (
    field_source_label as field_source_label_util,
)
from .derived_field_service import (
    relax_statement_filters as relax_statement_filters_util,
)
from .extractor import SearchConfig, SECReportExtractor
from .financial_services_extension_builder import (
    build_financial_services_extension,
)
from .industrial_extension_builder import build_industrial_extension
from .real_estate_extension_builder import build_real_estate_extension
from .report_contracts import (
    BaseFinancialModel,
    FinancialReport,
    FinancialServicesExtension,
    IndustrialExtension,
    RealEstateExtension,
)

T = TypeVar("T")
logger = get_logger(__name__)

BS_STATEMENT_TOKENS = ["balance", "financial position"]
IS_STATEMENT_TOKENS = ["income", "operation", "earning"]
CF_STATEMENT_TOKENS = ["cash"]
USD_UNITS = ["usd"]
SHARES_UNITS = ["shares"]
RATIO_UNITS = ["pure", "number"]

TotalDebtPolicy = Literal["include_finance_leases", "exclude_finance_leases"]
DEFAULT_TOTAL_DEBT_POLICY: TotalDebtPolicy = "include_finance_leases"
TOTAL_DEBT_POLICY_ENV = "FUNDAMENTAL_TOTAL_DEBT_POLICY"


class BaseFinancialModelFactory:
    @staticmethod
    def _resolve_configs(
        *,
        field_key: str,
        industry: str | None,
        issuer: str | None,
    ) -> list[SearchConfig]:
        return resolve_configs_util(
            field_key=field_key,
            industry=industry,
            issuer=issuer,
            registry=get_mapping_registry(),
            logger_=logger,
        )

    @staticmethod
    def _extract_field(
        extractor: SECReportExtractor,
        configs: list[SearchConfig],
        name: str,
        target_type: type[T] = float,
    ) -> TraceableField[T]:
        """
        Helper to extract a single field from a list of candidate SearchConfigs.

        Args:
            extractor: The SEC report extractor instance
            configs: List of SearchConfig objects to try in order
            name: Readable name of the field
            target_type: The expected type of the value (e.g., float, str)
        """
        return extract_field_util(
            extractor=extractor,
            configs=configs,
            name=name,
            target_type=target_type,
            logger_=logger,
        )

    @staticmethod
    def _collect_parsed_candidates(
        *,
        extractor: SECReportExtractor,
        configs: list[SearchConfig],
        name: str,
        target_type: type[T],
    ) -> list[ParsedCandidate[T]]:
        return collect_parsed_candidates_util(
            extractor=extractor,
            configs=configs,
            name=name,
            target_type=target_type,
            logger_=logger,
        )

    @staticmethod
    def _build_resolution_stages(
        configs: list[SearchConfig],
    ) -> list[tuple[str, list[SearchConfig]]]:
        return build_resolution_stages_util(configs)

    @staticmethod
    def create(
        extractor: SECReportExtractor, industry_type: str | None = None
    ) -> BaseFinancialModel:
        extraction_context = BaseModelExtractionContext(
            industry=industry_type or "Industrial",
            issuer_ticker=extractor.ticker,
            resolve_configs_fn=BaseFinancialModelFactory._resolve_configs,
        )

        context_balance_fields = build_context_balance_fields(
            extractor=extractor,
            resolve_configs=extraction_context.resolve_configs,
            build_config=extraction_context.build_config,
            extract_field_fn=BaseFinancialModelFactory._extract_field,
            bs_statement_tokens=BS_STATEMENT_TOKENS,
            is_statement_tokens=IS_STATEMENT_TOKENS,
            usd_units=USD_UNITS,
            shares_units=SHARES_UNITS,
        )

        debt_ops = DebtBuilderOps(
            extract_field_fn=BaseFinancialModelFactory._extract_field,
            resolve_total_debt_policy_fn=partial(
                resolve_total_debt_policy_util,
                env_var=TOTAL_DEBT_POLICY_ENV,
                default_policy=DEFAULT_TOTAL_DEBT_POLICY,
                logger_=logger,
            ),
            relax_statement_filters_fn=relax_statement_filters_util,
            build_total_debt_with_policy_fn=partial(
                build_total_debt_with_policy_util,
                sum_fields_fn=FinancialReportFactory._sum_fields,
            ),
            build_real_estate_debt_combined_ex_leases_fn=partial(
                build_real_estate_debt_combined_ex_leases_util,
                sum_fields_fn=FinancialReportFactory._sum_fields,
            ),
            field_source_label_fn=field_source_label_util,
            log_total_debt_diagnostics_fn=partial(
                log_total_debt_diagnostics_util,
                field_source_label_fn=field_source_label_util,
                logger_=logger,
            ),
        )

        # Debt
        tf_total_debt = build_total_debt_field(
            extractor=extractor,
            industry_type=industry_type,
            resolve_configs=extraction_context.resolve_configs,
            build_config=extraction_context.build_config,
            ops=debt_ops,
            logger_=logger,
            bs_statement_tokens=BS_STATEMENT_TOKENS,
            usd_units=USD_UNITS,
        )

        income_cashflow_ops = IncomeCashflowOps(
            extract_field_fn=BaseFinancialModelFactory._extract_field,
            calc_subtract_fn=calc_subtract_util,
            calc_ratio_fn=calc_ratio_util,
            calc_invested_capital_fn=calc_invested_capital_util,
            calc_nopat_fn=calc_nopat_util,
        )
        income_cashflow_fields = build_income_cashflow_and_derived_fields(
            extractor=extractor,
            resolve_configs=extraction_context.resolve_configs,
            build_config=extraction_context.build_config,
            ops=income_cashflow_ops,
            bs_statement_tokens=BS_STATEMENT_TOKENS,
            is_statement_tokens=IS_STATEMENT_TOKENS,
            cf_statement_tokens=CF_STATEMENT_TOKENS,
            usd_units=USD_UNITS,
            current_assets=context_balance_fields.current_assets,
            current_liabilities=context_balance_fields.current_liabilities,
            total_debt=tf_total_debt,
            total_equity=context_balance_fields.total_equity,
            cash_and_equivalents=context_balance_fields.cash_and_equivalents,
        )

        return assemble_base_financial_model(
            context_balance=context_balance_fields,
            total_debt=tf_total_debt,
            income_cashflow=income_cashflow_fields,
        )


class FinancialReportFactory:
    @staticmethod
    def create_report(ticker: str, fiscal_year: int | None) -> FinancialReport:
        # 1. Initialize Extractor
        extractor = SECReportExtractor(ticker, fiscal_year)

        # 2. Determine Industry (legacy routing label for mappings/overrides)
        sic_code = extractor.sic_code()
        routing_industry_type = FinancialReportFactory._resolve_industry_type(sic_code)

        # 3. Create Base Model (with industry overrides)
        base_model = BaseFinancialModelFactory.create(extractor, routing_industry_type)

        # 4. Create Extension
        extension = None
        if routing_industry_type == "Financial Services":
            extension = FinancialReportFactory._create_financial_services_extension(
                extractor
            )
        elif routing_industry_type == "Real Estate":
            extension = FinancialReportFactory._create_real_estate_extension(
                extractor, base_model
            )
        else:
            # Default to Industrial for General/Industrial
            extension = FinancialReportFactory._create_industrial_extension(extractor)

        # 5. Return Report
        extension_type = FinancialReportFactory._resolve_extension_type(
            routing_industry_type
        )
        return FinancialReport(
            base=base_model,
            extension=extension,
            # Canonical payload token; source-specific labels stay internal to routing.
            industry_type=extension_type,
            extension_type=extension_type,
            filing_metadata=extractor.get_selected_filing_metadata(),
        )

    @staticmethod
    def create_latest_report(ticker: str) -> FinancialReport:
        return FinancialReportFactory.create_report(ticker, None)

    @staticmethod
    def _resolve_industry_type(sic_code: object) -> str:
        if not sic_code:
            return "General"
        try:
            sic = int(sic_code)
        except (ValueError, TypeError):
            return "General"

        if sic == 6798:
            return "Real Estate"
        if 6000 <= sic <= 6999:
            return "Financial Services"
        if 2000 <= sic <= 3999:
            return "Industrial"
        return "Industrial"

    @staticmethod
    def _resolve_extension_type(
        industry_type: object,
    ) -> Literal["Industrial", "FinancialServices", "RealEstate"]:
        extension_type = normalize_extension_type_token(
            industry_type,
            context="sec_xbrl.industry_type",
        )
        if extension_type is None:
            return "Industrial"
        return extension_type

    @staticmethod
    def _sum_fields(
        name: str, fields: list[TraceableField[float]]
    ) -> TraceableField[float]:
        total = 0.0
        all_none = True
        inputs_map: dict[str, TraceableField[float]] = {}
        field_names: list[str] = []

        for field in fields:
            inputs_map[field.name] = field
            field_names.append(field.name)
            if field.value is not None:
                total += field.value
                all_none = False

        if all_none:
            return TraceableField(
                name=name,
                value=None,
                provenance=ManualProvenance(
                    description=(
                        "All components missing for calculation: "
                        + ", ".join(field_names)
                    )
                ),
            )

        return TraceableField(
            name=name,
            value=total,
            provenance=ComputedProvenance(
                op_code="SUM", expression=" + ".join(field_names), inputs=inputs_map
            ),
        )

    @staticmethod
    def _create_industrial_extension(
        extractor: SECReportExtractor,
    ) -> IndustrialExtension:
        return build_industrial_extension(
            extractor=extractor,
            resolve_configs_fn=BaseFinancialModelFactory._resolve_configs,
            extract_field_fn=BaseFinancialModelFactory._extract_field,
            sum_fields_fn=FinancialReportFactory._sum_fields,
            bs_statement_tokens=BS_STATEMENT_TOKENS,
            is_statement_tokens=IS_STATEMENT_TOKENS,
            cf_statement_tokens=CF_STATEMENT_TOKENS,
            usd_units=USD_UNITS,
        )

    @staticmethod
    def _create_financial_services_extension(
        extractor: SECReportExtractor,
    ) -> FinancialServicesExtension:
        return build_financial_services_extension(
            extractor=extractor,
            resolve_configs_fn=BaseFinancialModelFactory._resolve_configs,
            extract_field_fn=BaseFinancialModelFactory._extract_field,
            bs_statement_tokens=BS_STATEMENT_TOKENS,
            is_statement_tokens=IS_STATEMENT_TOKENS,
            usd_units=USD_UNITS,
            ratio_units=RATIO_UNITS,
        )

    @staticmethod
    def _create_real_estate_extension(
        extractor: SECReportExtractor, base_model: BaseFinancialModel
    ) -> RealEstateExtension:
        return build_real_estate_extension(
            extractor=extractor,
            base_model=base_model,
            resolve_configs_fn=BaseFinancialModelFactory._resolve_configs,
            extract_field_fn=BaseFinancialModelFactory._extract_field,
            is_statement_tokens=IS_STATEMENT_TOKENS,
            bs_statement_tokens=BS_STATEMENT_TOKENS,
            usd_units=USD_UNITS,
        )
