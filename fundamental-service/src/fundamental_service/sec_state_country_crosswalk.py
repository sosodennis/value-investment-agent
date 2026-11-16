"""Exact SEC U.S. incorporation-state codes to country reference mapping."""

from .issuer_country_crosswalk import (
    CountryCrosswalkProviderPort,
    CountryCrosswalkRuleV1,
)
from .serialization import sha256_digest

SEC_STATE_COUNTRY_PROVIDER = "sec-state-country"
SEC_STATE_COUNTRY_VERSION = "sec-us-state-to-country-v1"
DAMODARAN_COUNTRY_TAXONOMY = "damodaran-country-labels-v1"
SEC_STATE_COUNTRY_SCHEME = "sec-state-country-v1"

_US_JURISDICTIONS = tuple(
    "AK AL AR AZ CA CO CT DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN MO MS MT NC ND NE NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT WA WI WV WY DC".split()
)
_RULES = tuple(
    CountryCrosswalkRuleV1(
        rule_id=f"sec-us-jurisdiction-{code}-country-v1",
        source_scheme=SEC_STATE_COUNTRY_SCHEME,
        source_code=code,
        target_taxonomy=DAMODARAN_COUNTRY_TAXONOMY,
        target_country_code="US",
        target_population="countries",
        target_subject="United States",
        basis="SEC incorporation jurisdiction is an exact U.S. state or District of Columbia code.",
    )
    for code in _US_JURISDICTIONS
)


class SecStateCountryCrosswalk:
    """Map only recognized U.S. state or D.C. codes; all others abstain."""

    provider_id = SEC_STATE_COUNTRY_PROVIDER
    mapping_version = SEC_STATE_COUNTRY_VERSION
    target_taxonomy = DAMODARAN_COUNTRY_TAXONOMY

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
    ) -> tuple[CountryCrosswalkRuleV1, ...]:
        if target_taxonomy != self.target_taxonomy:
            return ()
        return tuple(
            rule
            for rule in _RULES
            if rule.source_scheme == source_scheme and rule.source_code == source_code
        )


def default_country_crosswalks() -> tuple[CountryCrosswalkProviderPort, ...]:
    return (SecStateCountryCrosswalk(),)
