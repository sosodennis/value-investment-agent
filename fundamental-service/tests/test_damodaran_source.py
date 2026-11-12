from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from fundamental_service.damodaran_source import (
    DAMODARAN_BETA_PROFILE,
    DAMODARAN_COUNTRY_PROFILE,
    DAMODARAN_SOURCE,
    DAMODARAN_TERMS,
    DamodaranReferenceProvider,
)
from fundamental_service.market_reference import (
    MarketReferenceProviderPort,
    ReferenceMetric,
    reproduce_reference_vintage,
    select_reference_vintage,
)
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_evidence import RetainedSourceV1
from reference_source_fixtures import beta_xls, country_xlsx

CAPTURE = datetime(2026, 11, 12, tzinfo=UTC)


def source(*, beta: bool = False, change: str = "") -> RetainedSourceV1:
    return RetainedSourceV1(
        source_id=DAMODARAN_SOURCE,
        uri="https://pages.stern.nyu.edu/~adamodar/pc/archives/"
        + ("betas24.xls" if beta else "ctryprem24.xlsx"),
        source_version=DAMODARAN_BETA_PROFILE if beta else DAMODARAN_COUNTRY_PROFILE,
        terms_reference=DAMODARAN_TERMS,
        content=beta_xls(change=change) if beta else country_xlsx(change=change),
        captured_at=CAPTURE,
    )


def test_beta_uses_unlevered_column_and_retains_binary_precision_and_missing_industry():
    provider: MarketReferenceProviderPort = DamodaranReferenceProvider()
    vintage = reproduce_reference_vintage(
        provider, metric="industry.unlevered_beta", sources=(source(beta=True),)
    )
    rows = {row.subject: row for row in vintage.rows}
    retail = rows["Retail (Special Lines)"]
    assert retail.value == Decimal.from_float(1.0024856714394297)
    assert retail.raw_value == "0x1.00a2e6a58a7bdp+0"
    assert retail.number_format == "0.00"
    assert retail.value_basis == "published_biff_cache"
    assert retail.locator == "Industry Averages!F11"
    assert rows["Other industry"].value is None
    assert rows["Other industry"].missing_reason == "empty_cell"
    assert rows["Total Market"].subject_kind == "aggregate"
    assert vintage.source_updated_on == date(2025, 1, 5)
    assert {c.name: c.raw_value for c in vintage.context} == {
        "tax_basis": "Marginal",
        "marginal_tax_raw_binary64": "0x1.0000000000000p-2",
    }


@pytest.mark.parametrize("metric", ["country.equity_risk_premium", "country.tax_rate"])
def test_country_references_preserve_lexemes_missing_rows_and_table_scope(
    metric: ReferenceMetric,
):
    original = source()
    vintage = reproduce_reference_vintage(
        DamodaranReferenceProvider(), metric=metric, sources=(original,)
    )
    rows = {row.subject: row for row in vintage.rows}
    us = rows["United States"]
    assert us.value == (
        Decimal("4.3299999999999998E-2")
        if metric == "country.equity_risk_premium"
        else Decimal("0.25")
    )
    assert us.raw_value == (
        "4.3299999999999998E-2" if metric == "country.equity_risk_premium" else "0.25"
    )
    assert rows["Missing country"].value is None
    assert rows["Missing country"].missing_reason == (
        "source_marker" if metric == "country.equity_risk_premium" else "empty_cell"
    )
    assert vintage.source_updated_on == date(
        2025, 1, 1
    )  # Source uses the 1904 Excel date system.
    assert vintage.available_at == CAPTURE
    assert vintage.available_at != datetime(2025, 1, 1, tzinfo=UTC)
    if metric == "country.equity_risk_premium":
        assert (
            rows["Frontier Markets (no sovereign ratings)"].subject_kind == "aggregate"
        )
        assert rows["Frontier Markets (no sovereign ratings)"].value is None
    with pytest.raises(ValueError, match="no reference vintage"):
        select_reference_vintage(
            (vintage,),
            metric=metric,
            population="countries",
            valuation_at=datetime(2025, 4, 1, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "beta,change",
    [
        (True, "header"),
        (True, "duplicate"),
        (True, "precision"),
        (False, "header"),
        (False, "duplicate"),
        (False, "precision"),
        (False, "nonfinite"),
        (False, "unknown"),
        (False, "future"),
        (False, "gap"),
        (False, "external"),
        (False, "duplicate_cell"),
        (False, "doctype"),
    ],
)
def test_changed_originals_fail_closed_without_selecting_another_column(beta, change):
    with pytest.raises(SnapshotError) as error:
        reproduce_reference_vintage(
            DamodaranReferenceProvider(),
            metric="industry.unlevered_beta" if beta else "country.equity_risk_premium",
            sources=(source(beta=beta, change=change),),
        )
    assert error.value.code == "REFERENCE_SOURCE_INVALID"


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "other"),
        ("source_version", "unreviewed"),
        ("terms_reference", "unknown"),
        ("uri", "https://example.test/ctryprem24.xlsx"),
        (
            "uri",
            "https://pages.stern.nyu.edu/~adamodar/pc/archives/ctryprem24.xlsx?expected=0.0433",
        ),
        ("captured_at", datetime(2026, 11, 12)),
        ("content", b"corrupt"),
        ("content", b"x" * (10 * 1024 * 1024 + 1)),
    ],
)
def test_reference_rejects_misbound_profiles_and_corrupt_originals(field, value):
    original = replace(source(), **{field: value})
    with pytest.raises(SnapshotError):
        reproduce_reference_vintage(
            DamodaranReferenceProvider(),
            metric="country.equity_risk_premium",
            sources=(original,),
        )


def test_reference_repeat_is_independent_of_decimal_context():
    from decimal import ROUND_DOWN, localcontext
    from fundamental_service.serialization import canonical_bytes

    original = source(beta=True)
    provider = DamodaranReferenceProvider()
    first = reproduce_reference_vintage(
        provider, metric="industry.unlevered_beta", sources=(original,)
    )
    with localcontext() as context:
        context.prec = 5
        context.rounding = ROUND_DOWN
        repeat = reproduce_reference_vintage(
            provider, metric="industry.unlevered_beta", sources=(original,)
        )
    assert first.content_digest == repeat.content_digest
    assert canonical_bytes(first) == canonical_bytes(repeat)


def test_published_formula_cache_is_retained_without_recalculation():
    original = source(change="formula")
    vintage = reproduce_reference_vintage(
        DamodaranReferenceProvider(),
        metric="country.equity_risk_premium",
        sources=(original,),
    )
    us = next(row for row in vintage.rows if row.subject == "United States")
    assert us.source_formula == "1+1"
    assert us.value_basis == "published_ooxml_cache"
    assert us.value == Decimal("4.3299999999999998E-2")


def test_tax_reference_retains_older_lookup_period_instead_of_calling_it_current_tax():
    vintage = reproduce_reference_vintage(
        DamodaranReferenceProvider(),
        metric="country.tax_rate",
        sources=(source(),),
    )
    assert vintage.source_updated_on == date(2025, 1, 1)
    assert vintage.context[0].raw_value == "Looked up for 2023"
    assert vintage.context[0].locator == "Country Tax Rates!C1"


def test_missing_formula_cache_retains_country_and_reason():
    from io import BytesIO
    from zipfile import ZipFile

    original = source(change="formula")
    output = BytesIO()
    with ZipFile(BytesIO(original.content)) as archive, ZipFile(output, "w") as changed:
        for member in archive.infolist():
            raw = archive.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                raw = raw.replace(
                    b"<f>1+1</f><v>4.3299999999999998E-2</v>", b"<f>1+1</f>"
                )
            changed.writestr(member, raw)
    vintage = reproduce_reference_vintage(
        DamodaranReferenceProvider(),
        metric="country.equity_risk_premium",
        sources=(replace(original, content=output.getvalue()),),
    )
    us = next(row for row in vintage.rows if row.subject == "United States")
    assert us.value is None
    assert us.missing_reason == "formula_cache_missing"
    assert us.source_formula == "1+1"
