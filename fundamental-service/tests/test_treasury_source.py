from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fundamental_service.macro_series import (
    MacroSeriesProviderPort,
    RetainedMacroSourceV1,
    reproduce_macro_vintage,
    select_macro_vintage,
)
from fundamental_service.snapshots import SnapshotError
from fundamental_service.treasury_source import (
    ALFRED_SOURCE,
    ALFRED_TERMS,
    ALFRED_TREASURY_PROFILE,
    TREASURY_PROFILE,
    TREASURY_SERIES,
    TREASURY_SOURCE,
    TREASURY_TERMS,
    AlfredTreasuryVintageProvider,
    TreasuryParYieldVintageProvider,
)
from treasury_source_fixtures import ALFRED_CSV, ALFRED_URI, TREASURY_URI, TREASURY_XML


def source(alfred: bool) -> RetainedMacroSourceV1:
    return RetainedMacroSourceV1(
        source_id=ALFRED_SOURCE if alfred else TREASURY_SOURCE,
        uri=ALFRED_URI if alfred else TREASURY_URI,
        source_version=ALFRED_TREASURY_PROFILE if alfred else TREASURY_PROFILE,
        terms_reference=ALFRED_TERMS if alfred else TREASURY_TERMS,
        content=ALFRED_CSV if alfred else TREASURY_XML,
        captured_at=datetime(2026, 11, 12, tzinfo=UTC),
    )


@pytest.mark.parametrize("alfred", (False, True))
def test_providers_are_interchangeable_and_content_bound(alfred):
    provider: MacroSeriesProviderPort = (
        AlfredTreasuryVintageProvider() if alfred else TreasuryParYieldVintageProvider()
    )
    original = source(alfred)
    vintage = reproduce_macro_vintage(
        provider, series_id=TREASURY_SERIES, sources=(original,)
    )
    assert vintage == reproduce_macro_vintage(
        provider, series_id=TREASURY_SERIES, sources=(original,)
    )
    assert vintage.frequency == "daily"
    assert vintage.unit == "percent"
    assert vintage.observations[0].value == Decimal("4.27")
    assert vintage.observations[0].period_end == date(2025, 3, 28)
    assert vintage.observations[0].source_sha256 == vintage.artifacts[0].content_sha256
    assert vintage.available_at == (
        datetime(2025, 4, 1, 4, tzinfo=UTC) if alfred else original.captured_at
    )
    changed = replace(original, content=original.content.replace(b"4.27", b"4.26"))
    assert (
        vintage.content_digest
        != reproduce_macro_vintage(
            provider, series_id=TREASURY_SERIES, sources=(changed,)
        ).content_digest
    )


def test_current_treasury_capture_cannot_replace_a_historical_vintage():
    current = reproduce_macro_vintage(
        TreasuryParYieldVintageProvider(),
        series_id=TREASURY_SERIES,
        sources=(source(False),),
    )
    historical = reproduce_macro_vintage(
        AlfredTreasuryVintageProvider(),
        series_id=TREASURY_SERIES,
        sources=(source(True),),
    )
    with pytest.raises(ValueError, match="no macro series vintage"):
        select_macro_vintage(
            (current, historical),
            series_id=TREASURY_SERIES,
            valuation_at=datetime(2025, 3, 31, 23, tzinfo=UTC),
        )
    assert (
        select_macro_vintage(
            (current, historical),
            series_id=TREASURY_SERIES,
            valuation_at=datetime(2025, 4, 1, 4, tzinfo=UTC),
        )
        == historical
    )
    assert all(item.period_end != date(2025, 3, 31) for item in historical.observations)


@pytest.mark.parametrize("alfred", (False, True))
@pytest.mark.parametrize(
    "field", ("source_id", "source_version", "terms_reference", "uri")
)
def test_provider_rejects_unbound_source_identity(alfred, field):
    provider = (
        AlfredTreasuryVintageProvider() if alfred else TreasuryParYieldVintageProvider()
    )
    with pytest.raises(SnapshotError):
        reproduce_macro_vintage(
            provider,
            series_id=TREASURY_SERIES,
            sources=(replace(source(alfred), **{field: "untrusted"}),),
        )


@pytest.mark.parametrize(
    "before,after",
    (
        (b"DGS10_20250331", b"DGS10_20250401"),
        (b"DGS10_20250331", b"DGS2_20250331"),
        (b"4.27", b"."),
        (b"4.27", b"NaN"),
        (b"4.27", b"Infinity"),
        (b"4.27", b"100"),
        (b"2025-03-28,4.27", b"2025-04-01,4.27"),
        (b"2025-03-28,4.27", b"2025-03-27,4.27"),
        (b"2025-03-28,4.27", b"2025-03-28,4.27,extra"),
        (b"2025-03-28,4.27", b"2025-03-28,4.27\n2025-03-28,4.28"),
        (b"2025-03-28,4.27", b""),
    ),
)
def test_alfred_retains_failures_instead_of_silently_filling_or_dropping(before, after):
    original = source(True)
    with pytest.raises(SnapshotError) as error:
        reproduce_macro_vintage(
            AlfredTreasuryVintageProvider(),
            series_id=TREASURY_SERIES,
            sources=(
                replace(original, content=original.content.replace(before, after)),
            ),
        )
    assert error.value.code == "ALFRED_SOURCE_INVALID"


@pytest.mark.parametrize(
    "captured",
    (
        datetime(2025, 3, 31, 0, tzinfo=UTC),
        datetime(2025, 4, 1, 3, 59, 59, tzinfo=UTC),
        datetime(2026, 1, 1),
    ),
)
def test_alfred_vintage_day_must_end_before_capture(captured):
    with pytest.raises(SnapshotError):
        reproduce_macro_vintage(
            AlfredTreasuryVintageProvider(),
            series_id=TREASURY_SERIES,
            sources=(replace(source(True), captured_at=captured),),
        )


def test_alfred_availability_obeys_winter_new_york_timezone():
    original = source(True)
    winter = replace(
        original,
        uri=original.uri.replace("03-28", "01-02").replace("03-31", "01-03"),
        content=original.content.replace(b"20250331", b"20250103").replace(
            b"03-28", b"01-02"
        ),
    )
    vintage = reproduce_macro_vintage(
        AlfredTreasuryVintageProvider(), series_id=TREASURY_SERIES, sources=(winter,)
    )
    assert vintage.available_at == datetime(2025, 1, 4, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "before,after",
    (
        (b"DailyTreasuryYieldCurveRateData", b"DailyTreasuryRealYieldCurveRateData"),
        (b"2025-03-28", b"2024-03-28"),
        (b"T00:00:00", b"T12:00:00"),
        (b"Edm.Double", b"Edm.String"),
        (b"4.27", b""),
        (b"4.27", b"NaN"),
        (b"4.27", b"Infinity"),
        (b"<d:BC_10YEAR", b'<d:BC_10YEAR m:null="true"'),
        (
            b"</d:BC_10YEAR>",
            b'</d:BC_10YEAR><d:BC_10YEAR m:type="Edm.Double">4.28</d:BC_10YEAR>',
        ),
        (b"</feed>", b""),
        (b"<feed", b'<!DOCTYPE feed [<!ENTITY x "4.27">]><feed'),
        (b"</entry>", b"</entry><entry/>"),
    ),
)
def test_treasury_rejects_ambiguous_or_unreproducible_xml(before, after):
    original = source(False)
    with pytest.raises(SnapshotError) as error:
        reproduce_macro_vintage(
            TreasuryParYieldVintageProvider(),
            series_id=TREASURY_SERIES,
            sources=(
                replace(original, content=original.content.replace(before, after)),
            ),
        )
    assert error.value.code == "TREASURY_SOURCE_INVALID"


def test_treasury_rejects_future_observations_and_duplicate_dates():
    original = source(False)
    with pytest.raises(SnapshotError):
        reproduce_macro_vintage(
            TreasuryParYieldVintageProvider(),
            series_id=TREASURY_SERIES,
            sources=(replace(original, captured_at=datetime(2025, 3, 27, tzinfo=UTC)),),
        )
    entry = original.content[
        original.content.index(b"<entry>") : original.content.index(b"</entry>")
        + len(b"</entry>")
    ]
    with pytest.raises(SnapshotError):
        reproduce_macro_vintage(
            TreasuryParYieldVintageProvider(),
            series_id=TREASURY_SERIES,
            sources=(
                replace(
                    original,
                    content=original.content.replace(b"</feed>", entry + b"</feed>"),
                ),
            ),
        )
