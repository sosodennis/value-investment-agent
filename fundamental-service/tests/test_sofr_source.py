import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from fundamental_service.snapshots import SnapshotError
from fundamental_service.sofr_source import (
    NEW_YORK_FED_SOFR_PROFILE,
    NEW_YORK_FED_SOFR_SOURCE,
    NEW_YORK_FED_TERMS,
    parse_new_york_fed_sofr,
)


def _uri(day: str = "2025-03-28") -> str:
    return (
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json"
        f"?startDate={day}&endDate={day}"
    )


def _response(rate: str = "4.41", *, day: str = "2025-03-28") -> bytes:
    return (
        '{"refRates":[{"effectiveDate":"'
        + day
        + '","type":"SOFR","percentRate":'
        + rate
        + ',"percentPercentile1":4.34,"percentPercentile25":4.37,'
        + '"percentPercentile75":4.47,"percentPercentile99":4.57,'
        + '"volumeInBillions":2636,"revisionIndicator":""}]}'
    ).encode()


def test_sofr_parser_preserves_official_observation_and_capture_availability():
    captured_at = datetime(2026, 11, 12, 17, 0, tzinfo=timezone.utc)
    raw = _response()
    result = parse_new_york_fed_sofr(
        raw,
        source_uri=_uri(),
        effective_date=date(2025, 3, 28),
        captured_at=captured_at,
    )

    assert result.source_id == NEW_YORK_FED_SOFR_SOURCE
    assert result.source_version == NEW_YORK_FED_SOFR_PROFILE
    assert result.terms_reference == NEW_YORK_FED_TERMS
    assert result.effective_date == date(2025, 3, 28)
    assert result.percent_rate == Decimal("4.41")
    assert result.content_hash == hashlib.sha256(raw).hexdigest()
    assert result.available_at == result.captured_at == captured_at


@pytest.mark.parametrize(
    ("raw", "source_uri", "day"),
    (
        (_response(day="2025-03-31"), _uri(), date(2025, 3, 28)),
        (_response("101"), _uri(), date(2025, 3, 28)),
        (b'{"refRates":[]}', _uri(), date(2025, 3, 28)),
        (
            json.dumps(
                {
                    "refRates": [
                        *json.loads(_response())["refRates"],
                        *json.loads(_response(day="2025-03-27"))["refRates"],
                    ]
                }
            ).encode(),
            _uri(),
            date(2025, 3, 28),
        ),
        (_response()[:-1] + b',"refRates":[]}', _uri(), date(2025, 3, 28)),
        (_response(), _uri("2025-03-31"), date(2025, 3, 28)),
        (
            _response(),
            "https://example.test/api?startDate=2025-03-28&endDate=2025-03-28",
            date(2025, 3, 28),
        ),
    ),
)
def test_sofr_parser_rejects_wrong_identity_or_ambiguous_values(raw, source_uri, day):
    with pytest.raises(SnapshotError) as error:
        parse_new_york_fed_sofr(
            raw,
            source_uri=source_uri,
            effective_date=day,
            captured_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOFR_SOURCE_INVALID"


def test_sofr_parser_rejects_effective_date_before_the_overnight_period_ends():
    with pytest.raises(SnapshotError) as error:
        parse_new_york_fed_sofr(
            _response(),
            source_uri=_uri(),
            effective_date=date(2025, 3, 28),
            captured_at=datetime(2025, 3, 28, 20, tzinfo=timezone.utc),
        )
    assert error.value.code == "SOFR_SOURCE_INVALID"
