from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, IntEnum

import pytest
from pydantic import BaseModel

from fundamental_service.serialization import (
    canonical_array_parts,
    canonical_bytes,
    canonical_object_parts,
    sha256_digest,
    sha256_parts,
)


class Phase(str, Enum):
    ACTIVE = "active"


class Rank(IntEnum):
    FIRST = 1


class Record(BaseModel):
    amount: Decimal
    timestamp: datetime
    phase: Phase
    rank: Rank


def test_v1_nested_model_money_time_enum_and_unicode_bytes():
    value = {
        "z": None,
        "nested": (
            Record(
                amount=Decimal("1.2300"),
                timestamp=datetime(
                    2026, 11, 17, 8, tzinfo=timezone(timedelta(hours=8))
                ),
                phase=Phase.ACTIVE,
                rank=Rank.FIRST,
            ),
            False,
            Decimal("1E+3"),
        ),
        "漢": "é",
    }
    assert (
        canonical_bytes(value)
        == (
            '{"nested":[{"amount":"1.2300","phase":"active","rank":1,'
            '"timestamp":"2026-11-17T00:00:00Z"},false,"1000"],"z":null,"漢":"é"}'
        ).encode()
    )


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        ([(10, "integer"), ("10", "text")], b'{"10":"text"}'),
        ([("10", "text"), (10, "integer")], b'{"10":"integer"}'),
    ],
)
def test_v1_key_stringification_preserves_collision_order(pairs, expected):
    assert canonical_bytes(dict(pairs)) == expected


def test_v1_mixed_keys_sort_after_stringification():
    value = {10: "integer", 2: "two", True: "boolean", None: "none"}
    assert canonical_bytes(value) == (
        b'{"10":"integer","2":"two","None":"none","True":"boolean"}'
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_v1_rejects_nonfinite_json_numbers_at_any_depth(value):
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_bytes({"values": [value]})


def test_embedded_canonical_fragments_preserve_nested_values_and_duplicate_items():
    items = ("é", {"漢": Decimal("1.00")}, "é")
    fields = {"timestamp": datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))}
    parts = tuple(
        canonical_object_parts(
            fields,
            {"items": canonical_array_parts(canonical_bytes(item) for item in items)},
        )
    )
    assert b"".join(parts) == canonical_bytes({**fields, "items": items})
    assert sha256_parts(parts) == sha256_digest({**fields, "items": items})
    assert b"".join(canonical_array_parts(())) == b"[]"
    with pytest.raises(ValueError, match="distinct"):
        tuple(canonical_object_parts({"items": 1}, {"items": (b"[]",)}))
