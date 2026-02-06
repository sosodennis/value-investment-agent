from typing import TypeVar

from .financial_models import (
    BaseFinancialModel,
    ComputedProvenance,
    FinancialReport,
    FinancialServicesExtension,
    IndustrialExtension,
    ManualProvenance,
    RealEstateExtension,
    TraceableField,
    XBRLProvenance,
)
from .tools.sec_extractor import SearchConfig, SearchType, SECReportExtractor

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
                print(f"Found {name} in {config.concept_regex}: {res.value}")

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
                    print(f"Failed to convert {name} to {target_type}")
                    val = None
                    continue

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
            [
                C("us-gaap:CashAndCashEquivalentsAtCarryingValue"),
                C("us-gaap:CashAndCashEquivalents"),
                C("us-gaap:CashAndCashEquivalentsRestrictedCashAndCashEquivalents"),
                C("us-gaap:Cash"),
                C("us-gaap:CashAndDueFromBanks"),
                C("us-gaap:CashAndDueFromBanksAndInterestBearingDeposits"),
                C("us-gaap:CashEquivalentsAtCarryingValue"),
            ],
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
                    extension = (
                        FinancialReportFactory._create_financial_services_extension(
                            extractor
                        )
                    )
                elif 2000 <= sic <= 3999:  # Manufacturing / Industrial
                    industry_type = "Industrial"
                    extension = FinancialReportFactory._create_industrial_extension(
                        extractor
                    )
                elif sic == 6798:  # REITs
                    industry_type = "Real Estate"
                    extension = FinancialReportFactory._create_real_estate_extension(
                        extractor, base_model
                    )
                else:
                    industry_type = "Industrial"  # Default fallback
                    extension = FinancialReportFactory._create_industrial_extension(
                        extractor
                    )
            except ValueError:
                pass

        # Default if something failed or no SIC code found, though logic above covers most
        if extension is None and industry_type == "General":
            # Fallback to Industrial if we can't determine, or keep as None?
            # Original code defaulted to IndustrialExtension if unknown.
            industry_type = "Industrial"
            extension = FinancialReportFactory._create_industrial_extension(extractor)

        # 4. Return Report
        return FinancialReport(
            base=base_model, extension=extension, industry_type=industry_type
        )

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
        def C(regex: str) -> SearchConfig:
            return SearchType.CONSOLIDATED(regex)

        # Inventory: Net -> Gross
        tf_inventory = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:InventoryNet"), C("us-gaap:InventoryGross")],
            "Inventory",
            target_type=float,
        )

        # Accounts Receivable: Net Current
        tf_ar = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:AccountsReceivableNetCurrent")],
            "Accounts Receivable",
            target_type=float,
        )

        # COGS: GoodsAndServices -> CostOfRevenue
        tf_cogs = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:CostOfGoodsAndServicesSold"), C("us-gaap:CostOfRevenue")],
            "Cost of Goods Sold (COGS)",
            target_type=float,
        )

        # R&D
        tf_rd = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:ResearchAndDevelopmentExpense")],
            "R&D Expense",
            target_type=float,
        )

        # SG&A: Aggregate -> Sum(Selling + G&A)
        tf_sga_aggregate = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:SellingGeneralAndAdministrativeExpense")],
            "SG&A Expense",
            target_type=float,
        )

        if tf_sga_aggregate.value is not None:
            tf_sga = tf_sga_aggregate
        else:
            # Fallback: Calculate Selling + G&A
            tf_selling = BaseFinancialModelFactory._extract_field(
                extractor,
                [C("us-gaap:SellingExpense"), C("us-gaap:SellingAndMarketingExpense")],
                "Selling Expense",
                target_type=float,
            )
            tf_ga = BaseFinancialModelFactory._extract_field(
                extractor,
                [C("us-gaap:GeneralAndAdministrativeExpense")],
                "G&A Expense",
                target_type=float,
            )
            tf_sga = FinancialReportFactory._sum_fields(
                "SG&A Expense (Calculated)", [tf_selling, tf_ga]
            )

        # CapEx: PaymentsToAcquirePropertyPlantAndEquipment
        # TODO: Add filtering by Statement Type to avoid "IncurredButNotYetPaid" issues.
        tf_capex = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")],
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
        def C(regex: str) -> SearchConfig:
            return SearchType.CONSOLIDATED(regex)

        # Loans & Leases
        tf_loans = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:LoansAndLeasesReceivableNetReportedAmount")],
            "Loans and Leases",
            target_type=float,
        )

        # Deposits
        tf_deposits = BaseFinancialModelFactory._extract_field(
            extractor, [C("us-gaap:Deposits")], "Deposits", target_type=float
        )

        # Allowance for Credit Losses: CECL -> Pre-CECL
        tf_allowance = BaseFinancialModelFactory._extract_field(
            extractor,
            [
                C("us-gaap:FinancingReceivableAllowanceForCreditLosses"),  # CECL
                C("us-gaap:AllowanceForLoanAndLeaseLosses"),  # Pre-CECL
            ],
            "Allowance for Credit Losses",
            target_type=float,
        )

        # Interest Income
        tf_int_income = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:InterestIncome")],
            "Interest Income",
            target_type=float,
        )

        # Interest Expense
        tf_int_expense = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:InterestExpense")],
            "Interest Expense",
            target_type=float,
        )

        # Provision for Loan Losses
        tf_provision = BaseFinancialModelFactory._extract_field(
            extractor,
            [
                C("us-gaap:ProvisionForCreditLosses"),
                C("us-gaap:ProvisionForLoanLeaseAndOtherLosses"),
            ],
            "Provision for Loan Losses",
            target_type=float,
        )

        return FinancialServicesExtension(
            loans_and_leases=tf_loans,
            deposits=tf_deposits,
            allowance_for_credit_losses=tf_allowance,
            interest_income=tf_int_income,
            interest_expense=tf_int_expense,
            provision_for_loan_losses=tf_provision,
        )

    @staticmethod
    def _create_real_estate_extension(
        extractor: SECReportExtractor, base_model: BaseFinancialModel
    ) -> RealEstateExtension:
        def C(regex: str) -> SearchConfig:
            return SearchType.CONSOLIDATED(regex)

        # Real Estate Assets
        tf_re_assets = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:RealEstateInvestmentPropertyNet")],
            "Real Estate Assets (at cost)",
            target_type=float,
        )

        # Accumulated Depreciation
        tf_acc_dep = BaseFinancialModelFactory._extract_field(
            extractor,
            [C("us-gaap:RealEstateInvestmentPropertyAccumulatedDepreciation")],
            "Accumulated Depreciation",
            target_type=float,
        )

        # For FFO Calculation:
        # 1. Depreciation & Amortization
        tf_dep = BaseFinancialModelFactory._extract_field(
            extractor,
            [
                C("us-gaap:DepreciationAndAmortizationInRealEstate"),
                C("us-gaap:DepreciationAndAmortization"),
            ],
            "Depreciation & Amortization",
            target_type=float,
        )

        # 2. Gain on Sale
        tf_gain = BaseFinancialModelFactory._extract_field(
            extractor,
            [
                C("us-gaap:GainLossOnSaleOfRealEstateInvestmentProperty"),
                C("us-gaap:GainLossOnSaleOfProperties"),
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
