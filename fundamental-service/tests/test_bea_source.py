from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from fundamental_service.bea_source import (
    BEA_GDP_PROFILE,
    BEA_GDP_TERMS,
    BeaNominalGdpVintageProvider,
)
from fundamental_service.macro_series import (
    MacroSeriesProviderPort,
    NominalGdpGrowthCeilingV1,
    reproduce_macro_vintage,
)
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_evidence import RetainedSourceV1

CAPTURED_AT = datetime(2026, 11, 12, 9, tzinfo=UTC)
WORKBOOK_URI = (
    "https://apps.bea.gov/HistData/Files/Releases/GDP_and_PI/2024/Q4/"
    "Third_March-27-2025/Section1all_xls.xlsx"
)
RELEASE_URI = (
    "https://www.bea.gov/news/2025/"
    "gross-domestic-product-fourth-quarter-and-year-2024-third-estimate"
)


def _write(archive: ZipFile, name: str, content: str) -> None:
    info = ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    archive.writestr(info, content)


def _workbook(
    *,
    published: str = "March 27, 2025",
    years=range(2014, 2025),
    title: str = "Table 1.1.5. Gross Domestic Product",
    final_value: int = 2000,
) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        _write(
            archive,
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="T10105-A" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        _write(
            archive,
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        year_cells = "".join(
            f'<c r="{chr(68 + offset)}8"><v>{year}</v></c>'
            for offset, year in enumerate(years)
        )
        values = "".join(
            f'<c r="{chr(68 + offset)}9"><v>{final_value if offset == len(years) - 1 else 1000 + offset * 100}</v></c>'
            for offset, _year in enumerate(years)
        )
        _write(
            archive,
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData>"
            '<row r="1"><c r="A1" t="inlineStr"><is><t>'
            f"{title}</t></is></c></row>"
            '<row r="2"><c r="A2" t="inlineStr"><is><t>[Millions of dollars]</t></is></c></row>'
            f'<row r="5"><c r="A5" t="inlineStr"><is><t>Data published {published}'
            "</t></is></c></row>"
            f'<row r="8">{year_cells}</row>'
            '<row r="9"><c r="A9" t="inlineStr"><is><t>1</t></is></c>'
            '<c r="B9" t="inlineStr"><is><t>Gross domestic product</t></is></c>'
            '<c r="C9" t="inlineStr"><is><t>A191RC</t></is></c>'
            f"{values}</row></sheetData></worksheet>",
        )
    return output.getvalue()


def _release(*, release_day: str = "Thursday, March 27, 2025") -> bytes:
    return (
        "<html><body><h1>Gross Domestic Product, 4th Quarter and Year 2024 "
        "(Third Estimate)</h1><p>EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, "
        f"{release_day}</p></body></html>"
    ).encode()


def _sources(
    workbook: bytes | None = None, release: bytes | None = None
) -> tuple[RetainedSourceV1, RetainedSourceV1]:
    return (
        RetainedSourceV1(
            source_id="bea-nipa-archive",
            uri=WORKBOOK_URI,
            source_version=BEA_GDP_PROFILE,
            terms_reference=BEA_GDP_TERMS,
            content=_workbook() if workbook is None else workbook,
            captured_at=CAPTURED_AT,
        ),
        RetainedSourceV1(
            source_id="bea-gdp-release",
            uri=RELEASE_URI,
            source_version=BEA_GDP_PROFILE,
            terms_reference=BEA_GDP_TERMS,
            content=_release() if release is None else release,
            captured_at=CAPTURED_AT,
        ),
    )


def test_bea_provider_reproduces_provider_neutral_vintage_and_growth_policy():
    provider: MacroSeriesProviderPort = BeaNominalGdpVintageProvider()
    vintage = reproduce_macro_vintage(
        provider, series_id="us.nominal_gdp", sources=_sources()
    )

    assert provider.supports("us.nominal_gdp")
    assert not provider.supports("us.real_gdp")
    assert vintage.series_id == "us.nominal_gdp"
    assert vintage.unit == "USD millions"
    assert vintage.available_at.isoformat() == "2025-03-28T04:00:00+00:00"
    assert len(vintage.observations) == 11
    assert vintage.observations[0].period_start.isoformat() == "2014-01-01"
    assert vintage.observations[-1].period_end.isoformat() == "2024-12-31"
    assert vintage.observations[0].value == 1000
    assert vintage.observations[-1].value == 2000

    decision = NominalGdpGrowthCeilingV1.derive(
        vintage,
        valuation_at=datetime(2025, 4, 1, tzinfo=UTC),
    )
    assert decision.start_year == 2014
    assert decision.end_year == 2024
    assert str(decision.nominal_gdp_cagr) == (
        "0.0717734625362931642130063250233420229063846049776"
    )
    assert decision.vintage_digest == vintage.content_digest
    assert len(vintage.content_digest) == 64
    assert len(decision.content_digest) == 64


def test_bea_provider_repeat_has_identical_digest_and_observation_order():
    provider = BeaNominalGdpVintageProvider()
    first = provider.reproduce_vintage(series_id="us.nominal_gdp", sources=_sources())
    second = provider.reproduce_vintage(series_id="us.nominal_gdp", sources=_sources())

    assert first.content_digest == second.content_digest
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert [item.period_start for item in first.observations] == sorted(
        item.period_start for item in first.observations
    )


def test_bea_provider_source_order_does_not_change_canonical_output():
    provider = BeaNominalGdpVintageProvider()
    sources = _sources()
    original = reproduce_macro_vintage(
        provider, series_id="us.nominal_gdp", sources=sources
    )
    reordered = reproduce_macro_vintage(
        provider, series_id="us.nominal_gdp", sources=tuple(reversed(sources))
    )
    assert original.model_dump_json() == reordered.model_dump_json()


@pytest.mark.parametrize(
    ("workbook", "release"),
    [
        (b"not-an-xlsx", _release()),
        (_workbook(published="March 28, 2025"), _release()),
        (_workbook(), _release(release_day="Friday, March 28, 2025")),
        (_workbook(title="wrong"), _release()),
    ],
)
def test_bea_provider_rejects_corrupt_conflicting_or_incomplete_vintage(
    workbook: bytes, release: bytes
):
    with pytest.raises(SnapshotError) as error:
        BeaNominalGdpVintageProvider().reproduce_vintage(
            series_id="us.nominal_gdp", sources=_sources(workbook, release)
        )
    assert error.value.code == "BEA_GDP_SOURCE_INVALID"


def test_bea_provider_rejects_unbound_source_evidence():
    provider = BeaNominalGdpVintageProvider()
    sources = _sources()
    with pytest.raises(SnapshotError) as error:
        provider.reproduce_vintage(series_id="us.nominal_gdp", sources=(sources[0],))
    assert error.value.code == "BEA_GDP_SOURCE_INVALID"


def test_vintage_digest_binds_original_source_bytes():
    provider = BeaNominalGdpVintageProvider()
    sources = _sources()
    original = provider.reproduce_vintage(series_id="us.nominal_gdp", sources=sources)
    changed = provider.reproduce_vintage(
        series_id="us.nominal_gdp",
        sources=_sources(workbook=_workbook(final_value=2100)),
    )

    assert hashlib.sha256(sources[0].content).hexdigest() in {
        item.content_sha256 for item in original.artifacts
    }
    assert original.content_digest != changed.content_digest


def test_nominal_gdp_policy_rejects_future_vintage_and_gapped_years():
    provider = BeaNominalGdpVintageProvider()
    vintage = provider.reproduce_vintage(series_id="us.nominal_gdp", sources=_sources())
    with pytest.raises(ValueError, match="unavailable"):
        NominalGdpGrowthCeilingV1.derive(
            vintage,
            valuation_at=datetime(2025, 3, 1, tzinfo=UTC),
        )
    short = provider.reproduce_vintage(
        series_id="us.nominal_gdp",
        sources=_sources(workbook=_workbook(years=range(2015, 2025))),
    )
    with pytest.raises(ValueError, match="complete nominal GDP horizon"):
        NominalGdpGrowthCeilingV1.derive(
            short,
            valuation_at=datetime(2025, 4, 1, tzinfo=UTC),
        )


def _replace_member(raw: bytes, name: str, before: bytes, after: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as old, ZipFile(output, "w") as new:
        for member in old.infolist():
            content = old.read(member.filename)
            if member.filename == name:
                assert before in content
                content = content.replace(before, after)
            new.writestr(member, content)
    return output.getvalue()


@pytest.mark.parametrize(
    ("before", "after"),
    (
        (b'<c r="D9"><v>1000</v></c>', b'<c r="D9"><v>NaN</v></c>'),
        (b'<c r="D9"><v>1000</v></c>', b'<c r="D9"><v>0</v></c>'),
        (b'<c r="D9"><v>1000</v></c>', b'<c r="D9"><f>1+1</f><v>1000</v></c>'),
        (
            b'<c r="D9"><v>1000</v></c>',
            b'<c r="D9"><v>1000</v></c><c r="D9"><v>1001</v></c>',
        ),
        (b'<c r="E8"><v>2015</v></c>', b'<c r="E8"><v>2014</v></c>'),
    ),
)
def test_bea_source_rejects_missing_conflicting_or_formula_values(
    before: bytes, after: bytes
):
    workbook = _replace_member(_workbook(), "xl/worksheets/sheet1.xml", before, after)
    with pytest.raises(SnapshotError) as error:
        BeaNominalGdpVintageProvider().reproduce_vintage(
            series_id="us.nominal_gdp", sources=_sources(workbook=workbook)
        )
    assert error.value.code == "BEA_GDP_SOURCE_INVALID"


def test_bea_source_rejects_duplicate_release_timestamp_and_timezone_conflict():
    for html in (_release() + _release(), _release().replace(b"EDT", b"EST")):
        with pytest.raises(SnapshotError) as error:
            BeaNominalGdpVintageProvider().reproduce_vintage(
                series_id="us.nominal_gdp", sources=_sources(release=html)
            )
        assert error.value.code == "BEA_GDP_SOURCE_INVALID"


@pytest.mark.parametrize(
    ("before", "after"),
    (
        (b"Year 2024", b"Year 2023"),
        (b"Third Estimate", b"Second Estimate"),
        (b"4th Quarter", b"3rd Quarter"),
    ),
)
def test_bea_source_rejects_release_for_another_estimate_or_period(
    before: bytes, after: bytes
):
    with pytest.raises(SnapshotError) as error:
        BeaNominalGdpVintageProvider().reproduce_vintage(
            series_id="us.nominal_gdp",
            sources=_sources(release=_release().replace(before, after)),
        )
    assert error.value.code == "BEA_GDP_SOURCE_INVALID"


def test_bea_source_rejects_wrong_host_query_and_naive_capture():
    from dataclasses import replace

    provider = BeaNominalGdpVintageProvider()
    sources = _sources()
    for workbook in (
        replace(sources[0], uri=WORKBOOK_URI.replace("apps.bea.gov", "example.test")),
        replace(sources[0], uri=WORKBOOK_URI + "?vintage=current"),
        replace(sources[0], captured_at=datetime(2026, 11, 12)),
        replace(sources[0], captured_at=datetime(2025, 3, 27, tzinfo=UTC)),
    ):
        with pytest.raises(SnapshotError) as error:
            provider.reproduce_vintage(
                series_id="us.nominal_gdp", sources=(workbook, sources[1])
            )
        assert error.value.code == "BEA_GDP_SOURCE_INVALID"
