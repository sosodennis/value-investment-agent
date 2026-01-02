from typing import TypeVar

from .financial_models import (
    BaseFinancialModel,
    FinancialReport,
    FinancialServicesExtension,
    IndustrialExtension,
    ManualProvenance,
    RealEstateExtension,
    TraceableField,
    XBRLProvenance,
)
from .sec_extractor import SearchConfig, SearchType, SECReportExtractor

T = TypeVar("T")


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
            if results:
                # Take the first match (usually the most relevant if sorted or standard)
                res = results[0]

                # Create Provenance
                provenance = XBRLProvenance(concept=res.concept, period=res.period_key)

                # Parse value safely based on target_type
                try:
                    raw_val = res.value
                    if raw_val is None:
                        val = None
                    else:
                        val = target_type(raw_val)
                except (ValueError, TypeError):
                    # If conversion fails, log/warn or set to None?
                    # For now, strict adherence to target_type is safer than magic fallback
                    val = None

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
    def create(extractor: SECReportExtractor) -> BaseFinancialModel:
        # Helper for brief config creation
        def C(regex: str) -> SearchConfig:
            return SearchType.CONSOLIDATED(regex)

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
            [
                C("dei:EntityCommonStockSharesOutstanding"),
                C("us-gaap:CommonStockSharesOutstanding"),
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
            extractor, [C("us-gaap:Assets")], "Total Assets", target_type=float
        )
        tf_liabilities = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:Liabilities")],
            "Total Liabilities",
            target_type=float,
        )
        tf_equity = BaseFinancialModelFactory._extract_field(
            extractor,
            [
                C("us-gaap:StockholdersEquity"),
                C(
                    "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
                ),
            ],
            "Total Equity",
            target_type=float,
        )
        tf_cash = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:CashAndCashEquivalentsAtCarryingValue")],
            "Cash & Cash Equivalents",
            target_type=float,
        )

        # Income Statement
        tf_revenue = BaseFinancialModelFactory._extract_field(
            extractor,
            [
                C("us-gaap:Revenues"),
                C("us-gaap:SalesRevenueNet"),
                C("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"),
            ],
            "Total Revenue",
            target_type=float,
        )
        tf_net_income = BaseFinancialModelFactory._extract_field(
            extractor, [C("us-gaap:NetIncomeLoss")], "Net Income", target_type=float
        )
        tf_tax = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:IncomeTaxExpenseBenefit")],
            "Income Tax Expense",
            target_type=float,
        )

        # Cash Flow
        tf_ocf = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:NetCashProvidedByUsedInOperatingActivities")],
            "Operating Cash Flow (OCF)",
            target_type=float,
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
            total_revenue=tf_revenue,
            net_income=tf_net_income,
            income_tax_expense=tf_tax,
            operating_cash_flow=tf_ocf,
        )


class FinancialReportFactory:
    @staticmethod
    def create_report(ticker: str, fiscal_year: int) -> FinancialReport:
        # 1. Initialize Extractor
        extractor = SECReportExtractor(ticker, fiscal_year)

        # 2. Create Base Model
        base_model = BaseFinancialModelFactory.create(extractor)

        # 3. Determine Industry and Create Extension
        sic_code = extractor.sic_code()
        extension = None
        industry_type = "General"

        if sic_code:
            try:
                sic = int(sic_code)
                if 6000 <= sic <= 6999:  # Banking / Finance
                    industry_type = "Financial Services"
                    extension = FinancialServicesExtension()  # Empty for now
                elif 2000 <= sic <= 3999:  # Manufacturing / Industrial
                    industry_type = "Industrial"
                    extension = IndustrialExtension()  # Empty for now
                elif sic == 6798:  # REITs
                    industry_type = "Real Estate"
                    extension = RealEstateExtension()  # Empty for now
                else:
                    industry_type = "Industrial"  # Default fallback
                    extension = IndustrialExtension()
            except ValueError:
                pass

        # 4. Return Report
        return FinancialReport(
            base=base_model, extension=extension, industry_type=industry_type
        )
