from __future__ import annotations

from src.agents.fundamental.infrastructure.sec_xbrl.cache.filing_cache_service import (
    FilingCacheCoordinates,
    FilingCacheService,
    build_arelle_taxonomy_cache_token,
)


def test_filing_cache_key_uses_filing_coordinates() -> None:
    service = FilingCacheService(l2_enabled=False, l3_enabled=False)
    key = service.build_payload_key(
        coordinates=FilingCacheCoordinates(
            cik="0001018724",
            accession="0001018724-26-000012",
            taxonomy_version="us-gaap-2025",
        ),
        field_key="financial_payload_v1",
    )
    assert (
        key == "fundamental:sec_xbrl:payload:0001018724:"
        "0001018724-26-000012:us-gaap-2025:financial_payload_v1"
    )


def test_filing_cache_l3_persists_payload_across_service_instances(tmp_path) -> None:
    cache_dir = tmp_path / "fundamental_xbrl_cache"
    writer = FilingCacheService(
        l1_ttl_seconds=3600,
        l2_enabled=False,
        l3_enabled=True,
        l3_cache_dir=str(cache_dir),
    )
    coordinates = FilingCacheCoordinates(
        cik="0001018724",
        accession="0001018724-26-000012",
        taxonomy_version="us-gaap-2025",
    )
    writer.store_payload(
        ticker="AMZN",
        years=5,
        field_key="financial_payload_v1",
        coordinates=coordinates,
        payload={
            "financial_reports": [],
            "forward_signals": [],
            "diagnostics": {"source": "unit_test"},
            "quality_gates": None,
        },
    )

    reader = FilingCacheService(
        l1_ttl_seconds=3600,
        l2_enabled=False,
        l3_enabled=True,
        l3_cache_dir=str(cache_dir),
    )
    lookup = reader.lookup_payload(
        ticker="AMZN",
        years=5,
        field_key="financial_payload_v1",
    )

    assert lookup.hit is True
    assert lookup.alias_layer == "L3"
    assert lookup.layer == "L3"
    assert isinstance(lookup.payload, dict)
    assert lookup.payload.get("diagnostics") == {"source": "unit_test"}


def test_build_arelle_taxonomy_cache_token_includes_validation_profile() -> None:
    token = build_arelle_taxonomy_cache_token(
        taxonomy_version="us-gaap-2025",
        validation_mode="efm_dqc_validate",
        disclosure_system="efm",
        plugins=("validate/EFM", "validate/DQC"),
        packages=("sec-taxonomy-2025.zip",),
        arelle_version="2.37.77",
    )
    assert token.startswith("us-gaap-2025__efm_dqc_validate__efm__2.37.77__")
