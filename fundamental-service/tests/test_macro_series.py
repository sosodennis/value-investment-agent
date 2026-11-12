from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest
from pydantic import ValidationError

from fundamental_service.macro_series import (
    MacroObservationV1,
    MacroSeriesProviderPort,
    MacroSeriesVintageV1,
    MacroSourceArtifactV1,
    NominalGdpGrowthCeilingV1,
    RetainedMacroSourceV1,
    reproduce_macro_vintage,
    select_macro_vintage,
)
from fundamental_service.serialization import sha256_digest
from fundamental_service.sofr_source import (
    NEW_YORK_FED_SOFR_PROFILE,
    NEW_YORK_FED_SOFR_SOURCE,
    NEW_YORK_FED_TERMS,
    NewYorkFedSofrVintageProvider,
)


class AlternativeGdpProvider:
    """Synthetic second provider demonstrates the unchanged policy dependency."""

    provider_id = "alternative-test-provider"

    def supports(self, series_id: str) -> bool:
        return series_id in {"us.nominal_gdp", "us.real_gdp"}

    def reproduce_vintage(
        self, *, series_id: str, sources: tuple[RetainedMacroSourceV1, ...]
    ) -> MacroSeriesVintageV1:
        source = sources[0]
        raw_hash = hashlib.sha256(source.content).hexdigest()
        artifact = MacroSourceArtifactV1(
            source_id=source.source_id,
            uri=source.uri,
            source_version=source.source_version,
            terms_reference=source.terms_reference,
            captured_at=source.captured_at,
            content_sha256=raw_hash,
        )
        return MacroSeriesVintageV1.build(
            provider_id=self.provider_id,
            series_id=series_id,
            frequency="annual",
            unit="USD millions",
            source_version="synthetic-v1",
            available_at=datetime(2025, 3, 1, tzinfo=UTC),
            captured_at=source.captured_at,
            artifacts=(artifact,),
            observations=tuple(
                MacroObservationV1(
                    series_id=series_id,
                    period_start=date(year, 1, 1),
                    period_end=date(year, 12, 31),
                    value=Decimal(1000) + (year - 2014) * 100,
                    unit="USD millions",
                    source_sha256=raw_hash,
                )
                for year in range(2014, 2025)
            ),
        )


def _alternative_vintage() -> MacroSeriesVintageV1:
    provider: MacroSeriesProviderPort = AlternativeGdpProvider()
    return reproduce_macro_vintage(
        provider,
        series_id="us.nominal_gdp",
        sources=(
            RetainedMacroSourceV1(
                source_id="synthetic-gdp",
                uri="https://example.test/gdp",
                source_version="synthetic-v1",
                terms_reference="synthetic-test-only",
                content=b"synthetic GDP fixture",
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ),
    )


def _rehash_vintage(vintage: MacroSeriesVintageV1, **changes) -> MacroSeriesVintageV1:
    payload = {**vintage.model_dump(exclude={"content_digest"}), **changes}
    return MacroSeriesVintageV1.model_validate(
        {**payload, "content_digest": sha256_digest(payload)}
    )


def test_gdp_policy_accepts_alternative_provider_without_provider_switches():
    vintage = _alternative_vintage()
    cutoff = datetime(2025, 4, 1, tzinfo=UTC)
    selected = select_macro_vintage(
        (vintage,), series_id="us.nominal_gdp", valuation_at=cutoff
    )
    result = NominalGdpGrowthCeilingV1.derive(selected, valuation_at=cutoff)
    assert result.start_value == 1000
    assert result.end_value == 2000
    assert str(result.nominal_gdp_cagr) == (
        "0.0717734625362931642130063250233420229063846049776"
    )


def test_one_provider_can_reproduce_different_requested_series():
    nominal = _alternative_vintage()
    provider: MacroSeriesProviderPort = AlternativeGdpProvider()
    source = RetainedMacroSourceV1(
        source_id="synthetic-real-gdp",
        uri="https://example.test/real-gdp",
        source_version="synthetic-v1",
        terms_reference="synthetic-test-only",
        content=b"synthetic real GDP fixture",
        captured_at=nominal.captured_at,
    )
    real = reproduce_macro_vintage(provider, series_id="us.real_gdp", sources=(source,))
    assert real.series_id == "us.real_gdp"
    assert all(item.series_id == "us.real_gdp" for item in real.observations)
    assert real.content_digest != nominal.content_digest
    with pytest.raises(ValueError, match="canonical nominal GDP"):
        NominalGdpGrowthCeilingV1.derive(
            real, valuation_at=datetime(2025, 4, 1, tzinfo=UTC)
        )
    with pytest.raises(ValueError, match="does not support"):
        reproduce_macro_vintage(provider, series_id="unknown", sources=(source,))


@pytest.mark.parametrize("binding", ("provider", "series", "bytes", "profile", "uri"))
def test_injected_provider_cannot_replace_requested_identity_or_originals(binding: str):
    class MisboundProvider(AlternativeGdpProvider):
        def reproduce_vintage(
            self, *, series_id: str, sources: tuple[RetainedMacroSourceV1, ...]
        ) -> MacroSeriesVintageV1:
            vintage = super().reproduce_vintage(series_id=series_id, sources=sources)
            if binding == "provider":
                return _rehash_vintage(vintage, provider_id="another-provider")
            if binding == "series":
                return _rehash_vintage(
                    vintage,
                    series_id="us.real_gdp",
                    observations=tuple(
                        item.model_copy(update={"series_id": "us.real_gdp"})
                        for item in vintage.observations
                    ),
                )
            source = vintage.artifacts[0]
            if binding == "bytes":
                changed = source.model_copy(update={"content_sha256": "0" * 64})
                return _rehash_vintage(
                    vintage,
                    artifacts=(changed,),
                    observations=tuple(
                        item.model_copy(update={"source_sha256": "0" * 64})
                        for item in vintage.observations
                    ),
                )
            changed = source.model_copy(
                update={"source_version" if binding == "profile" else "uri": "altered"}
            )
            return _rehash_vintage(vintage, artifacts=(changed,))

    source = RetainedMacroSourceV1(
        source_id="synthetic-gdp",
        uri="https://example.test/gdp",
        source_version="synthetic-v1",
        terms_reference="synthetic-test-only",
        content=b"synthetic GDP fixture",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="different series or provider|every original"):
        reproduce_macro_vintage(
            MisboundProvider(), series_id="us.nominal_gdp", sources=(source,)
        )


def test_growth_policy_is_independent_of_caller_decimal_context():
    vintage = _alternative_vintage()
    cutoff = datetime(2025, 4, 1, tzinfo=UTC)
    baseline = NominalGdpGrowthCeilingV1.derive(vintage, valuation_at=cutoff)
    with localcontext() as context:
        context.prec = 8
        context.rounding = ROUND_DOWN
        actual = NominalGdpGrowthCeilingV1.derive(vintage, valuation_at=cutoff)
    assert actual.content_digest == baseline.content_digest
    assert actual.nominal_gdp_cagr == baseline.nominal_gdp_cagr


def test_vintage_selection_filters_future_and_rejects_conflicting_provider_ties():
    original = _alternative_vintage()
    future = _rehash_vintage(original, available_at=datetime(2025, 5, 1, tzinfo=UTC))
    cutoff = datetime(2025, 4, 1, tzinfo=UTC)
    assert (
        select_macro_vintage(
            (future, original, original),
            series_id="us.nominal_gdp",
            valuation_at=cutoff,
        )
        == original
    )
    with pytest.raises(ValueError, match="no macro series vintage"):
        select_macro_vintage((future,), series_id="us.nominal_gdp", valuation_at=cutoff)
    conflicting = _rehash_vintage(original, provider_id="another-test-provider")
    with pytest.raises(ValueError, match="ambiguous"):
        select_macro_vintage(
            (original, conflicting), series_id="us.nominal_gdp", valuation_at=cutoff
        )


@pytest.mark.parametrize(
    "case", ("digest", "future", "duplicate", "source", "unit", "order")
)
def test_canonical_vintage_rejects_invalid_identity_or_provenance(case: str):
    original = _alternative_vintage()
    with pytest.raises(ValidationError):
        if case == "digest":
            payload = original.model_dump()
            payload["content_digest"] = "0" * 64
            MacroSeriesVintageV1.model_validate(payload)
        elif case == "future":
            _rehash_vintage(original, available_at=datetime(2023, 1, 1, tzinfo=UTC))
        elif case == "duplicate":
            _rehash_vintage(
                original, observations=original.observations + original.observations[:1]
            )
        elif case == "source":
            changed = original.observations[0].model_copy(
                update={"source_sha256": "0" * 64}
            )
            _rehash_vintage(
                original, observations=(changed, *original.observations[1:])
            )
        elif case == "unit":
            _rehash_vintage(original, unit="USD billions")
        elif case == "order":
            _rehash_vintage(
                original, observations=tuple(reversed(original.observations))
            )


def test_sofr_and_gdp_share_the_same_macro_provider_port_without_unit_confusion():
    provider: MacroSeriesProviderPort = NewYorkFedSofrVintageProvider()
    source = RetainedMacroSourceV1(
        source_id=NEW_YORK_FED_SOFR_SOURCE,
        uri="https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2025-03-28&endDate=2025-03-28",
        source_version=NEW_YORK_FED_SOFR_PROFILE,
        terms_reference=NEW_YORK_FED_TERMS,
        content=b'{"refRates":[{"effectiveDate":"2025-03-28","type":"SOFR","percentRate":4.34,"revisionIndicator":""}]}',
        captured_at=datetime(2026, 11, 12, tzinfo=UTC),
    )
    vintage = reproduce_macro_vintage(
        provider, series_id="us.sofr_overnight", sources=(source,)
    )
    assert provider.supports("us.sofr_overnight")
    assert not provider.supports("us.sofr_term")
    assert vintage.unit == "percent"
    assert vintage.observations[0].value == Decimal("4.34")
    assert vintage.available_at == source.captured_at
    with pytest.raises(ValueError, match="canonical nominal GDP series"):
        NominalGdpGrowthCeilingV1.derive(vintage, valuation_at=source.captured_at)
