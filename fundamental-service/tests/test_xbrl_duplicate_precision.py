"""Whole duplicate sets must be consistent before precision selection."""

from datetime import datetime, timezone
from itertools import permutations
from decimal import localcontext

import pytest

from fundamental_service.facts import select_fact
from fundamental_service.snapshots import SnapshotError
from test_facts import candidate, canonical, resolve


@pytest.mark.parametrize(
    "observations,expected",
    (
        ((("10700000000", -8), ("10727000000", -6)), "10727000000"),
        # Closed intervals meet at 0.5; differing decimals allow equal endpoints.
        ((("0", 0), ("0.55", 1)), "0.55"),
        ((("-10700000000", -8), ("-10727000000", -6)), "-10727000000"),
    ),
)
def test_compatible_whole_set_selects_precise_value_in_both_owners(
    observations, expected
):
    for order in permutations(observations):
        values = tuple(
            candidate(str(i), value, "2025-12-15", decimals)
            for i, (value, decimals) in enumerate(order)
        )
        selected = select_fact(values, datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert selected.fact is not None and str(selected.fact.value) == expected
        assert (
            str(resolve(*(canonical(value) for value in values))[0].value) == expected
        )


@pytest.mark.parametrize(
    "observations",
    (
        (("10000000000", -8), ("10727000000", -6)),
        # Both coarse facts overlap the precise interval at 105, but disagree
        # at equal decimals. Checking only the most precise subgroup misses it.
        (("100", -1), ("110", -1), ("105", 2)),
        # The wide first range overlaps each of the others, which are disjoint.
        (("0", -2), ("-40", -1), ("40", 0)),
    ),
)
def test_inconsistent_set_cannot_be_hidden_by_precision_or_pairwise_merging(
    observations,
):
    for order in permutations(observations):
        values = tuple(
            candidate(str(i), value, "2025-12-15", decimals)
            for i, (value, decimals) in enumerate(order)
        )
        selected = select_fact(values, datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert selected.fact is None
        assert selected.issues[0].code == "FACT_CONFLICT"
        assert set(selected.rejected_candidate_ids) == {
            value.candidate_id for value in values
        }
        assert {r.reason for r in selected.rejected_candidate_reasons} == {
            "inconsistent_numeric_duplicates_in_filing"
        }
        with pytest.raises(SnapshotError) as error:
            resolve(*(canonical(value) for value in values))
        assert error.value.code == "FACT_CONFLICT"


def test_missing_precision_does_not_supply_an_invented_numeric_interval():
    values = (
        candidate("unknown", "100", "2025-12-15", 0).model_copy(
            update={"decimals": None}
        ),
        candidate("reported", "101", "2025-12-15", 2),
    )
    selected = select_fact(values, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert selected.fact is None
    assert selected.issues[0].code == "FACT_PRECISION_UNAVAILABLE"


def test_decimal_context_cannot_silently_round_the_interval():
    values = (
        candidate("coarse", "100000000000000000000000000000000", "2025-12-15", -2),
        candidate("precise", "100000000000000000000000000000041", "2025-12-15", 0),
    )
    selected = select_fact(values, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert selected.fact is None
    assert selected.issues[0].code == "FACT_PRECISION_UNAVAILABLE"


def test_callers_decimal_context_does_not_change_admission():
    values = (
        candidate("coarse", "10700000000", "2025-12-15", -8),
        candidate("precise", "10727000000", "2025-12-15", -6),
    )
    with localcontext() as context:
        context.prec = 3
        selected = select_fact(values, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert selected.fact is not None and str(selected.fact.value) == "10727000000"
