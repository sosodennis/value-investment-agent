"""Trusted intended-use rules for bounded public aggregate source profiles."""

from .bea_source import BEA_GDP_PROFILE, BEA_GDP_TERMS, BeaNominalGdpVintageProvider
from .damodaran_source import (
    DAMODARAN_BETA_PROFILE,
    DAMODARAN_CAPITAL_PROFILE,
    DAMODARAN_COUNTRY_CURRENT_PROFILE,
    DAMODARAN_COUNTRY_PROFILE,
    DAMODARAN_SOURCE,
    DAMODARAN_TERMS,
    DamodaranReferenceProvider,
)
from .macro_series import MacroSeriesProviderPort
from .market_reference import MarketReferenceProviderPort
from .source_admission import SourceUsePolicyV1, SourceUseRuleV1, TermsRequirementV1
from .sofr_source import (
    NEW_YORK_FED_SOFR_PROFILE,
    NEW_YORK_FED_SOFR_SOURCE,
    NEW_YORK_FED_TERMS,
    NewYorkFedSofrVintageProvider,
)
from .treasury_source import (
    TREASURY_PROFILE,
    TREASURY_SOURCE,
    TREASURY_TERMS,
    AlfredTreasuryVintageProvider,
    TreasuryParYieldVintageProvider,
)

DAMODARAN_USE_URI = (
    "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html"
)
DAMODARAN_USE_SHA256 = (
    "6d8ccb3d77715d951c8fa1ccf76654396fbf4f4bbcf8cb87487ac26656bb04aa"
)
BEA_CITATION_SHA256 = "362a0e376b235df1333aea67d3eb4d4cc103fd754d056d1a5950449bdc99b04f"
US_GOVERNMENT_WORKS_URI = (
    "https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/"
    "USCODE-2024-title17-chap1-sec105.htm"
)
US_GOVERNMENT_WORKS_SHA256 = (
    "be9a8a2918c3f674506e80087565ce9f5479ea358394313daf02e3aa0a1491ba"
)
NEW_YORK_FED_USE_SHA256 = (
    "8338801341327ba9c5066f463c8196032a6a6107a87db4a70c7590859daa67f8"
)


def default_macro_providers() -> tuple[MacroSeriesProviderPort, ...]:
    return (
        BeaNominalGdpVintageProvider(),
        NewYorkFedSofrVintageProvider(),
        TreasuryParYieldVintageProvider(),
        AlfredTreasuryVintageProvider(),
    )


def default_reference_providers() -> tuple[MarketReferenceProviderPort, ...]:
    return (DamodaranReferenceProvider(),)


def free_market_source_policy() -> SourceUsePolicyV1:
    """Allow retained originals and derived valuations, with source attribution.

    The owner authorized deterministic approval of evidenced free sources. Rules
    cover the reproduced aggregate profiles only; they grant no company-level
    data, quote, benchmark-substitution or complete financial-policy authority.
    """
    rules = [
        SourceUseRuleV1(
            rule_id=f"damodaran-{metric}"
            + ("-v2" if profile == DAMODARAN_COUNTRY_CURRENT_PROFILE else ""),
            provider_id="damodaran-public-aggregates",
            metric_id=metric,
            population="us-companies"
            if metric.startswith("industry.")
            else "countries",
            source_id=DAMODARAN_SOURCE,
            source_version=profile,
            terms_reference=DAMODARAN_TERMS,
            permitted_uses=("valuation_preparation", "derived_valuation_display"),
            terms=(
                TermsRequirementV1(
                    uri=DAMODARAN_USE_URI, content_sha256=DAMODARAN_USE_SHA256
                ),
            ),
            required_notices=(
                "Public processed aggregate reference: Aswath Damodaran, NYU Stern; "
                "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html. "
                "Underlying company-level commercial data is excluded.",
            ),
            basis="Publisher shares processed data with 'no strings attached'; "
            "the bounded parser reproduces only public industry/country aggregates. "
            "No underlying company dataset or full-table redistribution is authorized here.",
        )
        for metric, profile in (
            ("country.equity_risk_premium", DAMODARAN_COUNTRY_PROFILE),
            ("country.tax_rate", DAMODARAN_COUNTRY_PROFILE),
            ("country.equity_risk_premium", DAMODARAN_COUNTRY_CURRENT_PROFILE),
            ("country.tax_rate", DAMODARAN_COUNTRY_CURRENT_PROFILE),
            ("industry.unlevered_beta", DAMODARAN_BETA_PROFILE),
            ("industry.equity_beta", DAMODARAN_CAPITAL_PROFILE),
            ("industry.pre_tax_cost_of_debt", DAMODARAN_CAPITAL_PROFILE),
            ("industry.debt_weight", DAMODARAN_CAPITAL_PROFILE),
            ("industry.equity_weight", DAMODARAN_CAPITAL_PROFILE),
        )
    ]
    rules.extend(
        SourceUseRuleV1(
            rule_id=f"bea-nominal-gdp-{source_id}",
            provider_id="bea-nipa",
            metric_id="us.nominal_gdp",
            population="us.nominal_gdp",
            source_id=source_id,
            source_version=BEA_GDP_PROFILE,
            terms_reference=BEA_GDP_TERMS,
            permitted_uses=("valuation_preparation", "derived_valuation_display"),
            terms=(
                TermsRequirementV1(
                    uri=BEA_GDP_TERMS, content_sha256=BEA_CITATION_SHA256
                ),
                TermsRequirementV1(
                    uri=US_GOVERNMENT_WORKS_URI,
                    content_sha256=US_GOVERNMENT_WORKS_SHA256,
                ),
            ),
            required_notices=(
                "Source: U.S. Bureau of Economic Analysis, NIPA table 1.1.5 and "
                "the cited GDP release. Derived calculations are by value-investment-agent; "
                "no BEA endorsement is implied.",
            ),
            basis="17 U.S.C. 105(a) excludes U.S. Government works from U.S. copyright; "
            "this profile covers BEA's own public aggregate GDP table and release. "
            "Preserve citations and do not imply BEA endorsement. "
            "This is not blanket permission for third-party content on government sites.",
        )
        for source_id in ("bea-gdp-release", "bea-nipa-archive")
    )
    rules.extend(
        (
            SourceUseRuleV1(
                rule_id="treasury-par-yield-10y",
                provider_id="us-treasury",
                metric_id="us.treasury_par_yield_10y",
                population="us.treasury_par_yield_10y",
                source_id=TREASURY_SOURCE,
                source_version=TREASURY_PROFILE,
                terms_reference=TREASURY_TERMS,
                permitted_uses=("valuation_preparation", "derived_valuation_display"),
                terms=(
                    TermsRequirementV1(
                        uri=US_GOVERNMENT_WORKS_URI,
                        content_sha256=US_GOVERNMENT_WORKS_SHA256,
                    ),
                ),
                required_notices=(
                    "Source: U.S. Department of the Treasury, daily Treasury par yield curve. "
                    "Derived calculations are by value-investment-agent; no Treasury endorsement is implied.",
                ),
                basis="17 U.S.C. 105(a), restricted to Treasury's own public par-yield observations. "
                "The legacy fiscaldata terms URL is not the permission basis; "
                "this grant excludes third-party site content.",
            ),
            SourceUseRuleV1(
                rule_id="new-york-fed-overnight-sofr",
                provider_id="new-york-fed",
                metric_id="us.sofr_overnight",
                population="us.sofr_overnight",
                source_id=NEW_YORK_FED_SOFR_SOURCE,
                source_version=NEW_YORK_FED_SOFR_PROFILE,
                terms_reference=NEW_YORK_FED_TERMS,
                permitted_uses=("valuation_preparation", "derived_valuation_display"),
                terms=(
                    TermsRequirementV1(
                        uri=NEW_YORK_FED_TERMS, content_sha256=NEW_YORK_FED_USE_SHA256
                    ),
                ),
                required_notices=(
                    "© Federal Reserve Bank of New York. Content from the New York Fed "
                    "subject to the Terms of Use at newyorkfed.org.",
                    "The Secured Overnight Financing Rate (SOFR) is subject to the Terms of Use "
                    "posted at newyorkfed.org. The New York Fed is not responsible for publication "
                    "of SOFR by value-investment-agent, does not sanction or endorse any particular "
                    "republication, and has no liability for your use.",
                    "value-investment-agent is not affiliated with the New York Fed. "
                    "Derived calculations and modifications are by value-investment-agent.",
                ),
                basis="Publisher's Permissible Use permits automated access, download, storage "
                "and business use with its Conditions and Reference Rates notice. "
                "No endorsement, exclusive reference-rate naming claim or CME Term SOFR use.",
            ),
        )
    )
    return SourceUsePolicyV1(
        policy_version="free-market-source-use-v3",
        rules=tuple(sorted(rules, key=lambda x: x.rule_id)),
    )
