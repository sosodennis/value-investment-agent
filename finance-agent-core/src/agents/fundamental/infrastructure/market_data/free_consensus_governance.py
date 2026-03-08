from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FreeConsensusProviderGovernance:
    provider: str
    robots_url: str
    terms_url: str


_GOVERNANCE_PROFILES: dict[str, FreeConsensusProviderGovernance] = {
    "tipranks": FreeConsensusProviderGovernance(
        provider="tipranks",
        robots_url="https://www.tipranks.com/robots.txt",
        terms_url="https://www.tipranks.com/terms-of-use",
    ),
    "investing": FreeConsensusProviderGovernance(
        provider="investing",
        robots_url="https://www.investing.com/robots.txt",
        terms_url="https://www.investing.com/about-us/terms-and-conditions",
    ),
    "marketbeat": FreeConsensusProviderGovernance(
        provider="marketbeat",
        robots_url="https://www.marketbeat.com/robots.txt",
        terms_url="https://www.marketbeat.com/terms/",
    ),
}


def governance_warning_for_provider(provider_name: str) -> str | None:
    profile = _GOVERNANCE_PROFILES.get(provider_name)
    if profile is None:
        return None
    return (
        f"{provider_name} governance review required: robots={profile.robots_url};"
        f"terms={profile.terms_url} [code=provider_governance_review_required]"
    )
