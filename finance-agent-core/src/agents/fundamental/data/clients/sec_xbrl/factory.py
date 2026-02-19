import logging
from typing import TypeVar

from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
    XBRLProvenance,
)

from .extractor import SearchConfig, SearchType, SECReportExtractor
from .mapping import REGISTRY
from .models import (
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
PURE_UNITS = ["pure"]


class BaseFinancialModelFactory:
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

        for config in configs:
            results = extractor.search(config)
            if not results:
                log_event(
                    logger,
                    event="fundamental_xbrl_field_no_matches",
                    message="no xbrl matches for field under config",
                    level=logging.DEBUG,
                    fields={"field_name": name, "concept_regex": config.concept_regex},
                )
                continue

            for res in results:
                raw_val = res.value

                # Skip empty values
                if raw_val is None:
                    log_event(
                        logger,
                        event="fundamental_xbrl_field_skip_empty",
                        message="skip empty xbrl value",
                        level=logging.DEBUG,
                        fields={
                            "field_name": name,
                            "concept": res.concept,
                            "period_key": res.period_key,
                        },
                    )
                    continue

                if target_type is float:
                    scale = BaseFinancialModelFactory._parse_scale(res.scale)
                    parsed = BaseFinancialModelFactory._parse_numeric(raw_val, scale)
                    if parsed is None:
                        log_event(
                            logger,
                            event="fundamental_xbrl_field_skip_non_numeric",
                            message="skip non-numeric xbrl value",
                            level=logging.DEBUG,
                            fields={
                                "field_name": name,
                                "concept": res.concept,
                                "period_key": res.period_key,
                                "statement": res.statement,
                                "value_preview": BaseFinancialModelFactory._preview_value(
                                    raw_val
                                ),
                            },
                        )
                        continue
                    val = parsed
                else:
                    try:
                        val = target_type(raw_val)
                    except (ValueError, TypeError):
                        log_event(
                            logger,
                            event="fundamental_xbrl_field_skip_non_castable",
                            message="skip non-castable xbrl value",
                            level=logging.DEBUG,
                            fields={
                                "field_name": name,
                                "concept": res.concept,
                                "period_key": res.period_key,
                                "value_preview": BaseFinancialModelFactory._preview_value(
                                    raw_val
                                ),
                            },
                        )
                        continue

                log_event(
                    logger,
                    event="fundamental_xbrl_field_hit",
                    message="xbrl field hit",
                    fields={
                        "field_name": name,
                        "concept": res.concept,
                        "period_key": res.period_key,
                        "value_preview": BaseFinancialModelFactory._preview_value(
                            raw_val
                        ),
                    },
                )

                # Create Provenance
                provenance = XBRLProvenance(concept=res.concept, period=res.period_key)

                return TraceableField(name=name, value=val, provenance=provenance)

        # Fallback if no tags match
        tags_searched = [c.concept_regex for c in configs]
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(
                description=f"Not found in XBRL. Searched: {tags_searched}"
            ),
        )

    @staticmethod
    def _parse_numeric(raw_val: object, scale: int | None = None) -> float | None:
        if isinstance(raw_val, int | float):
            value = float(raw_val)
            return value * (10**scale) if scale else value
        if not isinstance(raw_val, str):
            return None

        text = raw_val.strip().replace(",", "").replace("\u00a0", "")
        if not text:
            return None

        # Handle parentheses for negative values
        if text.startswith("(") and text.endswith(")"):
            text = f"-{text[1:-1]}"

        # Reject obvious HTML/text blocks
        if "<" in text or ">" in text:
            return None

        # Allow scientific notation
        import re

        pattern = r"^[-+]?((\d+(\.\d*)?)|(\.\d+))([eE][-+]?\d+)?$"
        if not re.match(pattern, text):
            return None

        try:
            value = float(text)
            return value * (10**scale) if scale else value
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_scale(scale: object) -> int | None:
        if scale is None:
            return None
        try:
            return int(scale)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _preview_value(raw_val: object, max_len: int = 80) -> str:
        text = str(raw_val).replace("\n", " ").strip()
        if len(text) > max_len:
            return f"{text[:max_len]}..."
        return text

    @staticmethod
    def _calc_ratio(
        name: str,
        numerator: TraceableField[float],
        denominator: TraceableField[float],
        expression: str,
    ) -> TraceableField[float]:
        if numerator.value is None or denominator.value in (None, 0):
            return TraceableField(
                name=name,
                value=None,
                provenance=ManualProvenance(
                    description=f"Missing or invalid denominator for {expression}"
                ),
            )
        return TraceableField(
            name=name,
            value=float(numerator.value) / float(denominator.value),
            provenance=ComputedProvenance(
                op_code="DIV",
                expression=expression,
                inputs={numerator.name: numerator, denominator.name: denominator},
            ),
        )

    @staticmethod
    def _calc_subtract(
        name: str,
        left: TraceableField[float],
        right: TraceableField[float],
        expression: str,
    ) -> TraceableField[float]:
        if left.value is None or right.value is None:
            return TraceableField(
                name=name,
                value=None,
                provenance=ManualProvenance(
                    description=f"Missing inputs for {expression}"
                ),
            )
        return TraceableField(
            name=name,
            value=float(left.value) - float(right.value),
            provenance=ComputedProvenance(
                op_code="SUB",
                expression=expression,
                inputs={left.name: left, right.name: right},
            ),
        )

    @staticmethod
    def _calc_invested_capital(
        total_equity: TraceableField[float],
        total_debt: TraceableField[float],
        cash: TraceableField[float],
    ) -> TraceableField[float]:
        if total_equity.value is None or total_debt.value is None or cash.value is None:
            return TraceableField(
                name="Invested Capital",
                value=None,
                provenance=ManualProvenance(
                    description="Missing equity, debt, or cash for invested capital"
                ),
            )
        value = float(total_equity.value) + float(total_debt.value) - float(cash.value)
        return TraceableField(
            name="Invested Capital",
            value=value,
            provenance=ComputedProvenance(
                op_code="INVESTED_CAPITAL",
                expression="TotalEquity + TotalDebt - Cash",
                inputs={
                    "Total Equity": total_equity,
                    "Total Debt": total_debt,
                    "Cash": cash,
                },
            ),
        )

    @staticmethod
    def _calc_nopat(
        operating_income: TraceableField[float],
        effective_tax_rate: TraceableField[float],
    ) -> TraceableField[float]:
        if operating_income.value is None or effective_tax_rate.value is None:
            return TraceableField(
                name="NOPAT",
                value=None,
                provenance=ManualProvenance(
                    description="Missing operating income or tax rate for NOPAT"
                ),
            )
        value = float(operating_income.value) * (1.0 - float(effective_tax_rate.value))
        return TraceableField(
            name="NOPAT",
            value=value,
            provenance=ComputedProvenance(
                op_code="NOPAT",
                expression="OperatingIncome * (1 - EffectiveTaxRate)",
                inputs={
                    "Operating Income": operating_income,
                    "Effective Tax Rate": effective_tax_rate,
                },
            ),
        )

    @staticmethod
    def create(
        extractor: SECReportExtractor, industry_type: str | None = None
    ) -> BaseFinancialModel:
        # Helper for brief config creation
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
            spec = REGISTRY.get(field_key, "Industrial")
            if not spec:
                return []
            return spec.configs

        # 1. Context Fields
        ticker_val = extractor.ticker
        cik_results = extractor.search(C("dei:EntityCentralIndexKey"))
        cik_val = cik_results[0].value if cik_results else None

        name_results = extractor.search(C("dei:EntityRegistrantName"))
        name_val = name_results[0].value if name_results else None

        # Context Traceable Fields (Constructed manually or found)
        tf_ticker = TraceableField(
            name="Ticker",
            value=ticker_val,
            provenance=ManualProvenance(description="Input Ticker"),
        )
        tf_cik = TraceableField(
            name="CIK",
            value=cik_val,
            provenance=XBRLProvenance(
                concept="dei:EntityCentralIndexKey", period="Current"
            )
            if cik_val
            else ManualProvenance(description="Missing"),
        )
        tf_name = TraceableField(
            name="Company Name",
            value=name_val,
            provenance=XBRLProvenance(
                concept="dei:EntityRegistrantName", period="Current"
            )
            if name_val
            else ManualProvenance(description="Missing"),
        )

        tf_sic = TraceableField(
            name="SIC Code",
            value=str(extractor.sic_code()),
            provenance=ManualProvenance(description="From Company Profile"),
        )

        # 2. Financial Fields
        # Shares
        tf_shares = BaseFinancialModelFactory._extract_field(
            extractor,
            R("shares_outstanding")
            or [
                C(
                    "dei:EntityCommonStockSharesOutstanding",
                    unit_whitelist=SHARES_UNITS,
                ),
                C("us-gaap:CommonStockSharesOutstanding", unit_whitelist=SHARES_UNITS),
            ],
            "Shares Outstanding",
            target_type=float,
        )

        # Fiscal Year/Period - TARGET TYPE IS STRING
        tf_fy = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("dei:DocumentFiscalYearFocus")],
            "Fiscal Year",
            target_type=str,
        )
        tf_fp = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("dei:DocumentFiscalPeriodFocus")],
            "Fiscal Period",
            target_type=str,
        )

        # Balance Sheet
        tf_assets = BaseFinancialModelFactory._extract_field(
            extractor,
            R("total_assets")
            or [C("us-gaap:Assets", BS_STATEMENT_TOKENS, "instant", USD_UNITS)],
            "Total Assets",
            target_type=float,
        )
        tf_liabilities = BaseFinancialModelFactory._extract_field(
            extractor,
            R("total_liabilities")
            or [C("us-gaap:Liabilities", BS_STATEMENT_TOKENS, "instant", USD_UNITS)],
            "Total Liabilities",
            target_type=float,
        )
        tf_equity = BaseFinancialModelFactory._extract_field(
            extractor,
            R("total_equity")
            or [
                C(
                    "us-gaap:StockholdersEquity",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
            ],
            "Total Equity",
            target_type=float,
        )
        tf_cash = BaseFinancialModelFactory._extract_field(
            extractor,
            R("cash_and_equivalents")
            or [
                C(
                    "us-gaap:CashAndCashEquivalentsAtCarryingValue",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:CashAndCashEquivalents",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:CashAndCashEquivalentsRestrictedCashAndCashEquivalents",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C("us-gaap:Cash", BS_STATEMENT_TOKENS, "instant", USD_UNITS),
                C(
                    "us-gaap:CashAndDueFromBanks",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:CashAndDueFromBanksAndInterestBearingDeposits",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:CashEquivalentsAtCarryingValue",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
            ],
            "Cash & Cash Equivalents",
            target_type=float,
        )
        tf_current_assets = BaseFinancialModelFactory._extract_field(
            extractor,
            R("current_assets")
            or [C("us-gaap:AssetsCurrent", BS_STATEMENT_TOKENS, "instant", USD_UNITS)],
            "Current Assets",
            target_type=float,
        )
        tf_current_liabilities = BaseFinancialModelFactory._extract_field(
            extractor,
            R("current_liabilities")
            or [
                C(
                    "us-gaap:LiabilitiesCurrent",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                )
            ],
            "Current Liabilities",
            target_type=float,
        )

        # Debt
        tf_debt_combined = BaseFinancialModelFactory._extract_field(
            extractor,
            R("total_debt_combined")
            or [
                C(
                    "us-gaap:DebtLongTermAndShortTermCombinedAmount",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C("us-gaap:Debt", BS_STATEMENT_TOKENS, "instant", USD_UNITS),
                C(
                    "us-gaap:LongTermDebtAndCapitalLeaseObligations",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
            ],
            "Total Debt (Combined)",
            target_type=float,
        )
        tf_debt_short = BaseFinancialModelFactory._extract_field(
            extractor,
            R("debt_short")
            or [
                C(
                    "us-gaap:ShortTermBorrowings",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C("us-gaap:DebtCurrent", BS_STATEMENT_TOKENS, "instant", USD_UNITS),
                C(
                    "us-gaap:LongTermDebtCurrent",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
            ],
            "Short-Term Debt",
            target_type=float,
        )
        tf_debt_long = BaseFinancialModelFactory._extract_field(
            extractor,
            R("debt_long")
            or [
                C(
                    "us-gaap:LongTermDebtNoncurrent",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C("us-gaap:LongTermDebt", BS_STATEMENT_TOKENS, "instant", USD_UNITS),
                C(
                    "us-gaap:LongTermDebtAndCapitalLeaseObligations",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
            ],
            "Long-Term Debt",
            target_type=float,
        )

        if tf_debt_combined.value is not None:
            tf_total_debt = TraceableField(
                name="Total Debt",
                value=tf_debt_combined.value,
                provenance=tf_debt_combined.provenance,
            )
        else:
            tf_total_debt = FinancialReportFactory._sum_fields(
                "Total Debt", [tf_debt_short, tf_debt_long]
            )

        tf_preferred = BaseFinancialModelFactory._extract_field(
            extractor,
            R("preferred_stock")
            or [
                C(
                    "us-gaap:PreferredStockValue",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:PreferredStockCarryingAmount",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),
                C("us-gaap:PreferredStock", BS_STATEMENT_TOKENS, "instant", USD_UNITS),
            ],
            "Preferred Stock",
            target_type=float,
        )
        if tf_preferred.value is None:
            tf_preferred = TraceableField(
                name="Preferred Stock",
                value=0.0,
                provenance=ManualProvenance(
                    description="Assumed 0 due to no disclosure or no implementaion now"
                ),
            )

        # Income Statement
        tf_revenue = BaseFinancialModelFactory._extract_field(
            extractor,
            R("total_revenue")
            or [
                C("us-gaap:Revenues", IS_STATEMENT_TOKENS, "duration", USD_UNITS),
                C(
                    "us-gaap:SalesRevenueNet",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
            ],
            "Total Revenue",
            target_type=float,
        )
        tf_operating_income = BaseFinancialModelFactory._extract_field(
            extractor,
            R("operating_income")
            or [
                C(
                    "us-gaap:OperatingIncomeLoss",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:OperatingIncomeLossContinuingOperations",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
            ],
            "Operating Income (EBIT)",
            target_type=float,
        )
        tf_income_before_tax = BaseFinancialModelFactory._extract_field(
            extractor,
            R("income_before_tax")
            or [
                C(
                    "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:IncomeBeforeTax",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C("us-gaap:PretaxIncome", IS_STATEMENT_TOKENS, "duration", USD_UNITS),
            ],
            "Income Before Tax",
            target_type=float,
        )
        tf_interest_expense = BaseFinancialModelFactory._extract_field(
            extractor,
            R("interest_expense")
            or [
                C(
                    "us-gaap:InterestExpense",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:InterestExpenseDebt",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
            ],
            "Interest Expense",
            target_type=float,
        )
        tf_da = BaseFinancialModelFactory._extract_field(
            extractor,
            R("depreciation_and_amortization")
            or [
                C(
                    "us-gaap:DepreciationAndAmortization",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:DepreciationAndAmortization",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:DepreciationDepletionAndAmortization",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:DepreciationDepletionAndAmortization",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:DepreciationAmortizationAndAccretionNet",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:DepreciationAmortizationAndAccretionNet",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C("us-gaap:Depreciation", IS_STATEMENT_TOKENS, "duration", USD_UNITS),
                C("us-gaap:Depreciation", CF_STATEMENT_TOKENS, "duration", USD_UNITS),
            ],
            "Depreciation & Amortization",
            target_type=float,
        )
        tf_sbc = BaseFinancialModelFactory._extract_field(
            extractor,
            R("share_based_compensation")
            or [
                C(
                    "us-gaap:ShareBasedCompensation",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:ShareBasedCompensation",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:ShareBasedCompensationExpense",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:ShareBasedCompensationExpense",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:ShareBasedCompensationCost",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:ShareBasedCompensationCost",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
            ],
            "Share-Based Compensation",
            target_type=float,
        )
        tf_net_income = BaseFinancialModelFactory._extract_field(
            extractor,
            R("net_income")
            or [C("us-gaap:NetIncomeLoss", IS_STATEMENT_TOKENS, "duration", USD_UNITS)],
            "Net Income",
            target_type=float,
        )
        tf_tax = BaseFinancialModelFactory._extract_field(
            extractor,
            R("income_tax_expense")
            or [
                C(
                    "us-gaap:IncomeTaxExpenseBenefit",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                )
            ],
            "Income Tax Expense",
            target_type=float,
        )

        # EBITDA (Derived)
        if tf_operating_income.value is not None and tf_da.value is not None:
            tf_ebitda = TraceableField(
                name="EBITDA",
                value=tf_operating_income.value + tf_da.value,
                provenance=ComputedProvenance(
                    op_code="EBITDA_CALC",
                    expression="OperatingIncome + DepreciationAndAmortization",
                    inputs={
                        "Operating Income": tf_operating_income,
                        "Depreciation & Amortization": tf_da,
                    },
                ),
            )
        else:
            tf_ebitda = TraceableField(
                name="EBITDA",
                value=None,
                provenance=ManualProvenance(
                    description="Missing Operating Income or D&A"
                ),
            )

        # Cash Flow
        tf_ocf = BaseFinancialModelFactory._extract_field(
            extractor,
            R("operating_cash_flow")
            or [
                C(
                    "us-gaap:NetCashProvidedByUsedInOperatingActivities",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                )
            ],
            "Operating Cash Flow (OCF)",
            target_type=float,
        )
        tf_dividends = BaseFinancialModelFactory._extract_field(
            extractor,
            R("dividends_paid")
            or [
                C(
                    "us-gaap:PaymentsOfDividends",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:PaymentsOfDividendsCommonStock",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:DividendsCommonStockCash",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C("us-gaap:DividendsPaid", CF_STATEMENT_TOKENS, "duration", USD_UNITS),
            ],
            "Dividends Paid",
            target_type=float,
        )

        # Derived Metrics (single-period)
        tf_working_capital = BaseFinancialModelFactory._calc_subtract(
            "Working Capital",
            tf_current_assets,
            tf_current_liabilities,
            "CurrentAssets - CurrentLiabilities",
        )
        tf_effective_tax_rate = BaseFinancialModelFactory._calc_ratio(
            "Effective Tax Rate",
            tf_tax,
            tf_income_before_tax,
            "IncomeTaxExpense / IncomeBeforeTax",
        )
        tf_interest_cost_rate = BaseFinancialModelFactory._calc_ratio(
            "Interest Cost Rate",
            tf_interest_expense,
            tf_total_debt,
            "InterestExpense / TotalDebt",
        )
        tf_ebit_margin = BaseFinancialModelFactory._calc_ratio(
            "EBIT Margin",
            tf_operating_income,
            tf_revenue,
            "OperatingIncome / Revenue",
        )
        tf_net_margin = BaseFinancialModelFactory._calc_ratio(
            "Net Margin",
            tf_net_income,
            tf_revenue,
            "NetIncome / Revenue",
        )
        tf_invested_capital = BaseFinancialModelFactory._calc_invested_capital(
            tf_equity,
            tf_total_debt,
            tf_cash,
        )
        tf_nopat = BaseFinancialModelFactory._calc_nopat(
            tf_operating_income,
            tf_effective_tax_rate,
        )
        tf_roic = BaseFinancialModelFactory._calc_ratio(
            "ROIC",
            tf_nopat,
            tf_invested_capital,
            "NOPAT / InvestedCapital",
        )

        # Create Model
        return BaseFinancialModel(
            ticker=tf_ticker,
            cik=tf_cik,
            company_name=tf_name,
            sic_code=tf_sic,
            fiscal_year=tf_fy,
            fiscal_period=tf_fp,
            shares_outstanding=tf_shares,
            total_assets=tf_assets,
            total_liabilities=tf_liabilities,
            total_equity=tf_equity,
            cash_and_equivalents=tf_cash,
            current_assets=tf_current_assets,
            current_liabilities=tf_current_liabilities,
            total_debt=tf_total_debt,
            preferred_stock=tf_preferred,
            total_revenue=tf_revenue,
            operating_income=tf_operating_income,
            income_before_tax=tf_income_before_tax,
            interest_expense=tf_interest_expense,
            depreciation_and_amortization=tf_da,
            share_based_compensation=tf_sbc,
            net_income=tf_net_income,
            income_tax_expense=tf_tax,
            ebitda=tf_ebitda,
            operating_cash_flow=tf_ocf,
            dividends_paid=tf_dividends,
            working_capital=tf_working_capital,
            working_capital_delta=TraceableField(
                name="Working Capital Delta",
                value=None,
                provenance=ManualProvenance(
                    description="Requires prior period working capital"
                ),
            ),
            effective_tax_rate=tf_effective_tax_rate,
            interest_cost_rate=tf_interest_cost_rate,
            ebit_margin=tf_ebit_margin,
            net_margin=tf_net_margin,
            invested_capital=tf_invested_capital,
            nopat=tf_nopat,
            roic=tf_roic,
            reinvestment_rate=TraceableField(
                name="Reinvestment Rate",
                value=None,
                provenance=ManualProvenance(
                    description="Requires CapEx, D&A, delta WC, NOPAT"
                ),
            ),
        )


class FinancialReportFactory:
    @staticmethod
    def create_report(ticker: str, fiscal_year: int) -> FinancialReport:
        # 1. Initialize Extractor
        extractor = SECReportExtractor(ticker, fiscal_year)

        # 2. Determine Industry (used for overrides)
        sic_code = extractor.sic_code()
        industry_type = FinancialReportFactory._resolve_industry_type(sic_code)

        # 3. Create Base Model (with industry overrides)
        base_model = BaseFinancialModelFactory.create(extractor, industry_type)

        # 4. Create Extension
        extension = None
        if industry_type == "Financial Services":
            extension = FinancialReportFactory._create_financial_services_extension(
                extractor
            )
        elif industry_type == "Real Estate":
            extension = FinancialReportFactory._create_real_estate_extension(
                extractor, base_model
            )
        else:
            # Default to Industrial for General/Industrial
            extension = FinancialReportFactory._create_industrial_extension(extractor)
            industry_type = (
                "Industrial" if industry_type == "General" else industry_type
            )

        # 5. Return Report
        return FinancialReport(
            base=base_model, extension=extension, industry_type=industry_type
        )

    @staticmethod
    def _resolve_industry_type(sic_code: object) -> str:
        if not sic_code:
            return "General"
        try:
            sic = int(sic_code)
        except (ValueError, TypeError):
            return "General"

        # REITs should be classified before Financial Services range match
        if sic == 6798:
            return "Real Estate"
        if 6000 <= sic <= 6999:
            return "Financial Services"
        if 2000 <= sic <= 3999:
            return "Industrial"
        return "Industrial"

    @staticmethod
    def _sum_fields(
        name: str, fields: list[TraceableField[float]]
    ) -> TraceableField[float]:
        """
        Helper to sum multiple TraceableFields and create a ComputedProvenance.
        Treats None values as 0.0 for calculation, but if all are None, returns None.
        """
        total = 0.0
        all_none = True
        inputs_map = {}

        field_names = []

        for f in fields:
            inputs_map[f.name] = f
            field_names.append(f.name)
            if f.value is not None:
                total += f.value
                all_none = False

        if all_none:
            return TraceableField(
                name=name,
                value=None,
                provenance=ManualProvenance(
                    description=f"All components missing for calculation: {', '.join(field_names)}"
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
            spec = REGISTRY.get(field_key, "Financial Services")
            if not spec:
                return []
            return spec.configs

        # Inventory: Net -> Gross
        tf_inventory = BaseFinancialModelFactory._extract_field(
            extractor,
            R("inventory")
            or [
                C("us-gaap:InventoryNet", BS_STATEMENT_TOKENS, "instant", USD_UNITS),
                C("us-gaap:InventoryGross", BS_STATEMENT_TOKENS, "instant", USD_UNITS),
            ],
            "Inventory",
            target_type=float,
        )

        # Accounts Receivable: Net Current
        tf_ar = BaseFinancialModelFactory._extract_field(
            extractor,
            R("accounts_receivable")
            or [
                C(
                    "us-gaap:AccountsReceivableNetCurrent",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                )
            ],
            "Accounts Receivable",
            target_type=float,
        )

        # COGS: GoodsAndServices -> CostOfRevenue
        tf_cogs = BaseFinancialModelFactory._extract_field(
            extractor,
            R("cogs")
            or [
                C(
                    "us-gaap:CostOfGoodsAndServicesSold",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C("us-gaap:CostOfRevenue", IS_STATEMENT_TOKENS, "duration", USD_UNITS),
            ],
            "Cost of Goods Sold (COGS)",
            target_type=float,
        )

        # R&D
        tf_rd = BaseFinancialModelFactory._extract_field(
            extractor,
            R("rd_expense")
            or [
                C(
                    "us-gaap:ResearchAndDevelopmentExpense",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                )
            ],
            "R&D Expense",
            target_type=float,
        )

        # SG&A: Aggregate -> Sum(Selling + G&A)
        tf_sga_aggregate = BaseFinancialModelFactory._extract_field(
            extractor,
            R("sga_expense")
            or [
                C(
                    "us-gaap:SellingGeneralAndAdministrativeExpense",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                )
            ],
            "SG&A Expense",
            target_type=float,
        )

        if tf_sga_aggregate.value is not None:
            tf_sga = tf_sga_aggregate
        else:
            # Fallback: Calculate Selling + G&A
            tf_selling = BaseFinancialModelFactory._extract_field(
                extractor,
                R("selling_expense")
                or [
                    C(
                        "us-gaap:SellingExpense",
                        IS_STATEMENT_TOKENS,
                        "duration",
                        USD_UNITS,
                    ),
                    C(
                        "us-gaap:SellingAndMarketingExpense",
                        IS_STATEMENT_TOKENS,
                        "duration",
                        USD_UNITS,
                    ),
                ],
                "Selling Expense",
                target_type=float,
            )
            tf_ga = BaseFinancialModelFactory._extract_field(
                extractor,
                R("ga_expense")
                or [
                    C(
                        "us-gaap:GeneralAndAdministrativeExpense",
                        IS_STATEMENT_TOKENS,
                        "duration",
                        USD_UNITS,
                    )
                ],
                "G&A Expense",
                target_type=float,
            )
            tf_sga = FinancialReportFactory._sum_fields(
                "SG&A Expense (Calculated)", [tf_selling, tf_ga]
            )

        # CapEx: PaymentsToAcquirePropertyPlantAndEquipment
        # Note: statement-type filtering can further reduce false-positive tag matches.
        tf_capex = BaseFinancialModelFactory._extract_field(
            extractor,
            R("capex")
            or [
                C(
                    "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
                    CF_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                )
            ],
            "Capital Expenditures (CapEx)",
            target_type=float,
        )

        return IndustrialExtension(
            inventory=tf_inventory,
            accounts_receivable=tf_ar,
            cogs=tf_cogs,
            rd_expense=tf_rd,
            sga_expense=tf_sga,
            capex=tf_capex,
        )

    @staticmethod
    def _create_financial_services_extension(
        extractor: SECReportExtractor,
    ) -> FinancialServicesExtension:
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
            spec = REGISTRY.get(field_key, "Real Estate")
            if not spec:
                return []
            return spec.configs

        # Loans & Leases
        tf_loans = BaseFinancialModelFactory._extract_field(
            extractor,
            R("loans_and_leases")
            or [
                C(
                    "us-gaap:LoansAndLeasesReceivableNetReportedAmount",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                )
            ],
            "Loans and Leases",
            target_type=float,
        )

        # Deposits
        tf_deposits = BaseFinancialModelFactory._extract_field(
            extractor,
            R("deposits")
            or [C("us-gaap:Deposits", BS_STATEMENT_TOKENS, "instant", USD_UNITS)],
            "Deposits",
            target_type=float,
        )

        # Allowance for Credit Losses: CECL -> Pre-CECL
        tf_allowance = BaseFinancialModelFactory._extract_field(
            extractor,
            R("allowance_for_credit_losses")
            or [
                C(
                    "us-gaap:FinancingReceivableAllowanceForCreditLosses",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),  # CECL
                C(
                    "us-gaap:AllowanceForLoanAndLeaseLosses",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                ),  # Pre-CECL
            ],
            "Allowance for Credit Losses",
            target_type=float,
        )

        # Interest Income
        tf_int_income = BaseFinancialModelFactory._extract_field(
            extractor,
            R("interest_income")
            or [
                C("us-gaap:InterestIncome", IS_STATEMENT_TOKENS, "duration", USD_UNITS)
            ],
            "Interest Income",
            target_type=float,
        )

        # Interest Expense
        tf_int_expense = BaseFinancialModelFactory._extract_field(
            extractor,
            R("interest_expense_financial")
            or [
                C("us-gaap:InterestExpense", IS_STATEMENT_TOKENS, "duration", USD_UNITS)
            ],
            "Interest Expense",
            target_type=float,
        )

        # Provision for Loan Losses
        tf_provision = BaseFinancialModelFactory._extract_field(
            extractor,
            R("provision_for_loan_losses")
            or [
                C(
                    "us-gaap:ProvisionForCreditLosses",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:ProvisionForLoanLeaseAndOtherLosses",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
            ],
            "Provision for Loan Losses",
            target_type=float,
        )

        tf_rwa = BaseFinancialModelFactory._extract_field(
            extractor,
            R("risk_weighted_assets")
            or [C("us-gaap:RiskWeightedAssets", None, "instant", USD_UNITS)],
            "Risk-Weighted Assets",
            target_type=float,
        )

        tf_tier1 = BaseFinancialModelFactory._extract_field(
            extractor,
            R("tier1_capital_ratio")
            or [
                C("us-gaap:Tier1CapitalRatio", None, "instant", PURE_UNITS),
                C("us-gaap:Tier1RiskBasedCapitalRatio", None, "instant", PURE_UNITS),
            ],
            "Tier 1 Capital Ratio",
            target_type=float,
        )

        return FinancialServicesExtension(
            loans_and_leases=tf_loans,
            deposits=tf_deposits,
            allowance_for_credit_losses=tf_allowance,
            interest_income=tf_int_income,
            interest_expense=tf_int_expense,
            provision_for_loan_losses=tf_provision,
            risk_weighted_assets=tf_rwa,
            tier1_capital_ratio=tf_tier1,
        )

    @staticmethod
    def _create_real_estate_extension(
        extractor: SECReportExtractor, base_model: BaseFinancialModel
    ) -> RealEstateExtension:
        industry_type = "Real Estate"

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
            spec = REGISTRY.get(field_key, industry_type)
            if not spec:
                return []
            return spec.configs

        # Real Estate Assets
        tf_re_assets = BaseFinancialModelFactory._extract_field(
            extractor,
            R("real_estate_assets")
            or [
                C(
                    "us-gaap:RealEstateInvestmentPropertyNet",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                )
            ],
            "Real Estate Assets (at cost)",
            target_type=float,
        )

        # Accumulated Depreciation
        tf_acc_dep = BaseFinancialModelFactory._extract_field(
            extractor,
            R("accumulated_depreciation")
            or [
                C(
                    "us-gaap:RealEstateInvestmentPropertyAccumulatedDepreciation",
                    BS_STATEMENT_TOKENS,
                    "instant",
                    USD_UNITS,
                )
            ],
            "Accumulated Depreciation",
            target_type=float,
        )

        # For FFO Calculation:
        # 1. Depreciation & Amortization
        tf_dep = BaseFinancialModelFactory._extract_field(
            extractor,
            R("real_estate_dep_amort")
            or [
                C(
                    "us-gaap:DepreciationAndAmortizationInRealEstate",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:DepreciationAndAmortization",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
            ],
            "Depreciation & Amortization",
            target_type=float,
        )

        # 2. Gain on Sale
        tf_gain = BaseFinancialModelFactory._extract_field(
            extractor,
            R("gain_on_sale")
            or [
                C(
                    "us-gaap:GainLossOnSaleOfRealEstateInvestmentProperty",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
                C(
                    "us-gaap:GainLossOnSaleOfProperties",
                    IS_STATEMENT_TOKENS,
                    "duration",
                    USD_UNITS,
                ),
            ],
            "Gain on Sale of Properties",
            target_type=float,
        )

        # 3. Net Income (From Base Model)
        tf_net_income = base_model.net_income

        # Calculate FFO: Net Income + Depreciation - GainOnSale
        # We need to handle None values carefully.

        ni_val = tf_net_income.value if tf_net_income.value is not None else 0.0
        dep_val = tf_dep.value if tf_dep.value is not None else 0.0
        gain_val = tf_gain.value if tf_gain.value is not None else 0.0

        ffo_val = ni_val + dep_val - gain_val

        # If all key components are missing (e.g. Net Income is None), strictly speaking FFO is invalid,
        # but usually Net Income is present. If Net Income is None, the base model extraction failed significantly.
        # We'll calculate it if at least Net Income is present or we have some data.

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
            ffo=tf_ffo,
        )
