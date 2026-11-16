from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from fundamental_service.market_reference import (
    MarketReferenceProviderPort,
    MarketReferenceVintageV1,
    ReferenceMetric,
    ReferenceRowV1,
    reproduce_reference_vintage,
    select_reference_vintage,
)
from fundamental_service.reference_workbook import read_reference_xlsx
from fundamental_service.serialization import sha256_digest
from fundamental_service.source_evidence import RetainedSourceV1, SourceArtifactV1

_CAPTURE = datetime(2026, 11, 12, tzinfo=UTC)
_AVAILABILITY = datetime(2026, 1, 1, tzinfo=UTC)


def _source(content: bytes = b"public reference") -> RetainedSourceV1:
    return RetainedSourceV1(
        source_id="synthetic-reference",
        uri="https://example.test/reference.csv",
        source_version="synthetic-v1",
        terms_reference="synthetic-test-only",
        content=content,
        captured_at=_CAPTURE,
    )


class AlternativeReferenceProvider:
    """A second source implements the same port without changing selection."""

    provider_id = "alternative-reference"

    def supports(self, metric: ReferenceMetric) -> bool:
        return metric == "country.equity_risk_premium"

    def reproduce_vintage(
        self, *, metric: ReferenceMetric, sources: tuple[RetainedSourceV1, ...]
    ) -> MarketReferenceVintageV1:
        source = sources[0]
        digest = hashlib.sha256(source.content).hexdigest()
        artifact = SourceArtifactV1(
            source_id=source.source_id,
            uri=source.uri,
            source_version=source.source_version,
            terms_reference=source.terms_reference,
            content_sha256=digest,
            captured_at=source.captured_at,
        )
        row = ReferenceRowV1(
            subject="United States",
            subject_kind="country",
            value=Decimal("0.0433"),
            missing_reason=None,
            raw_value="0.0433",
            numeric_encoding="decimal_text",
            value_basis="published_cell",
            number_format="0.00%",
            locator="Country!E2",
            source_sha256=digest,
        )
        return MarketReferenceVintageV1.build(
            metric=metric,
            population="countries",
            unit="fraction",
            provider_id=self.provider_id,
            source_version="alternative-v1",
            source_updated_on=date(2025, 12, 31),
            available_at=_AVAILABILITY,
            captured_at=source.captured_at,
            artifacts=(artifact,),
            rows=(row,),
        )


def _xlsx_with_formula() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<workbookPr date1904="1"/><sheets><sheet name="Reference" sheetId="1" '
            'r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/styles.xml",
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<cellXfs count="1"><xf numFmtId="0"/></cellXfs></styleSheet>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1"><f>1+1</f><v>3</v></c></row>'
            "</sheetData></worksheet>",
        )
    return output.getvalue()


def test_alternative_reference_provider_uses_common_selection_contract():
    provider: MarketReferenceProviderPort = AlternativeReferenceProvider()
    vintage = reproduce_reference_vintage(
        provider,
        metric="country.equity_risk_premium",
        sources=(_source(),),
    )
    selected = select_reference_vintage(
        (vintage,),
        metric="country.equity_risk_premium",
        population="countries",
        valuation_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert selected.rows[0].subject == "United States"
    assert selected.rows[0].value == Decimal("0.0433")
    assert selected.provider_id == "alternative-reference"


def test_provider_cannot_return_evidence_for_different_original_bytes():
    class MisboundProvider(AlternativeReferenceProvider):
        def reproduce_vintage(
            self, *, metric: ReferenceMetric, sources: tuple[RetainedSourceV1, ...]
        ) -> MarketReferenceVintageV1:
            vintage = super().reproduce_vintage(metric=metric, sources=sources)
            artifact = vintage.artifacts[0].model_copy(
                update={"uri": "https://example.test/swapped"}
            )
            payload = {
                **vintage.model_dump(exclude={"content_digest"}),
                "artifacts": (artifact,),
            }
            return MarketReferenceVintageV1.model_validate(
                {**payload, "content_digest": sha256_digest(payload)}
            )

    with pytest.raises(ValueError, match="different metric or provider|every original"):
        reproduce_reference_vintage(
            MisboundProvider(),
            metric="country.equity_risk_premium",
            sources=(_source(),),
        )


def test_reference_selection_rejects_future_and_ambiguous_vintages():
    provider = AlternativeReferenceProvider()
    vintage = reproduce_reference_vintage(
        provider,
        metric="country.equity_risk_premium",
        sources=(_source(),),
    )
    with pytest.raises(ValueError, match="no reference vintage"):
        select_reference_vintage(
            (vintage,),
            metric="country.equity_risk_premium",
            population="countries",
            valuation_at=datetime(2025, 12, 31, tzinfo=UTC),
        )
    other = reproduce_reference_vintage(
        provider,
        metric="country.equity_risk_premium",
        sources=(_source(b"different original"),),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        select_reference_vintage(
            (vintage, other),
            metric="country.equity_risk_premium",
            population="countries",
            valuation_at=datetime(2026, 2, 1, tzinfo=UTC),
        )


def test_reference_workbook_keeps_published_formula_and_cache_without_evaluation():
    sheet = read_reference_xlsx(_xlsx_with_formula(), "Reference")
    assert sheet.date_1904 is True
    assert sheet.cell("A1").formula == "1+1"
    assert sheet.cell("A1").number() == 3


def test_reference_build_canonicalizes_multiple_row_construction_orders():
    provider = AlternativeReferenceProvider()
    original = reproduce_reference_vintage(
        provider,
        metric="country.equity_risk_premium",
        sources=(_source(),),
    )
    rows = (
        original.rows[0],
        original.rows[0].model_copy(update={"subject": "Another country"}),
    )
    fields = original.model_dump(
        exclude={"content_digest", "rows", "artifacts", "context"}
    )
    forward = MarketReferenceVintageV1.build(
        **fields, artifacts=original.artifacts, rows=rows
    )
    reverse = MarketReferenceVintageV1.build(
        **fields, artifacts=original.artifacts, rows=tuple(reversed(rows))
    )
    assert forward.content_digest == reverse.content_digest
    assert [row.subject for row in forward.rows] == ["Another country", "United States"]
