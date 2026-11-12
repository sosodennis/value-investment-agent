"""Explicit SEC SIC rules for selected U.S. Damodaran industry rows."""

from .classification_crosswalk import (
    ClassificationCrosswalkProviderPort,
    IndustryCrosswalkRuleV1,
)
from .serialization import sha256_digest

SEC_SIC_DAMODARAN_PROVIDER = "sec-sic-damodaran-us-industry"
SEC_SIC_DAMODARAN_VERSION = "sec-sic-damodaran-us-2025-v1"
DAMODARAN_US_INDUSTRY_TAXONOMY = "damodaran-us-industry-labels-v1"

_RULES = (
    IndustryCrosswalkRuleV1(
        rule_id="sic-3571-computers-peripherals-v1",
        source_scheme="sec-sic-v1",
        source_code="3571",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computers/Peripherals",
        basis="SEC SIC 3571 identifies electronic computers; use the same named hardware industry proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-3572-computers-peripherals-v1",
        source_scheme="sec-sic-v1",
        source_code="3572",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computers/Peripherals",
        basis="SEC SIC 3572 identifies computer storage devices; use the same named hardware industry proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-3575-computers-peripherals-v1",
        source_scheme="sec-sic-v1",
        source_code="3575",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computers/Peripherals",
        basis="SEC SIC 3575 identifies computer terminals; use the same named hardware industry proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-3577-computers-peripherals-v1",
        source_scheme="sec-sic-v1",
        source_code="3577",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computers/Peripherals",
        basis="SEC SIC 3577 identifies computer peripheral equipment; use the same named hardware industry proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-3674-semiconductor-v1",
        source_scheme="sec-sic-v1",
        source_code="3674",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Semiconductor",
        basis="SEC SIC 3674 identifies semiconductor devices; use the same named semiconductor industry proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7371-computer-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7371",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computer Services",
        basis="SEC SIC 7371 identifies computer programming services; use the named computer-services proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7372-software-system-application-v1",
        source_scheme="sec-sic-v1",
        source_code="7372",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Software (System & Application)",
        basis="SEC SIC 7372 identifies prepackaged software; use the named software industry proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7373-computer-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7373",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computer Services",
        basis="SEC SIC 7373 identifies computer systems design services; use the named computer-services proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7374-computer-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7374",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computer Services",
        basis="SEC SIC 7374 identifies data processing services; use the named computer-services proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7375-information-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7375",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Information Services",
        basis="SEC SIC 7375 identifies information retrieval services; use the named information-services proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7376-computer-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7376",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computer Services",
        basis="SEC SIC 7376 identifies computer facilities management services; use the named computer-services proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7377-computer-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7377",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computer Services",
        basis="SEC SIC 7377 identifies computer rental and leasing services; use the named computer-services proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7378-computer-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7378",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computer Services",
        basis="SEC SIC 7378 identifies computer maintenance services; use the named computer-services proxy.",
    ),
    IndustryCrosswalkRuleV1(
        rule_id="sic-7379-computer-services-v1",
        source_scheme="sec-sic-v1",
        source_code="7379",
        target_taxonomy=DAMODARAN_US_INDUSTRY_TAXONOMY,
        target_population="us-companies",
        target_subject="Computer Services",
        basis="SEC SIC 7379 identifies other computer-related services; use the named computer-services proxy.",
    ),
)


class SecSicDamodaranIndustryCrosswalk:
    """A small exact-rule crosswalk; unsupported SIC codes remain unmapped."""

    provider_id = SEC_SIC_DAMODARAN_PROVIDER
    mapping_version = SEC_SIC_DAMODARAN_VERSION
    target_taxonomy = DAMODARAN_US_INDUSTRY_TAXONOMY

    @property
    def mapping_digest(self) -> str:
        return sha256_digest(
            {
                "provider_id": self.provider_id,
                "mapping_version": self.mapping_version,
                "target_taxonomy": self.target_taxonomy,
                "rules": _RULES,
            }
        )

    def candidates(
        self, *, source_scheme: str, source_code: str, target_taxonomy: str
    ) -> tuple[IndustryCrosswalkRuleV1, ...]:
        if target_taxonomy != self.target_taxonomy:
            return ()
        return tuple(
            rule
            for rule in _RULES
            if rule.source_scheme == source_scheme and rule.source_code == source_code
        )


def default_classification_crosswalks() -> tuple[
    ClassificationCrosswalkProviderPort, ...
]:
    """Composition registry for supported source-to-industry crosswalks."""
    return (SecSicDamodaranIndustryCrosswalk(),)
