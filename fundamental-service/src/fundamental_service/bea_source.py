"""Reproduce a dated BEA nominal GDP vintage from official retained bytes."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .macro_series import (
    MacroObservationV1,
    MacroSeriesVintageV1,
)
from .snapshots import SnapshotError
from .source_evidence import RetainedSourceV1, SourceArtifactV1

BEA_GDP_PROFILE = "bea-nipa-gdp-vintage-v1"
BEA_GDP_TERMS = "https://www.bea.gov/help/guidelines-for-citing-bea"
_BEA_NEWS_HOST = "www.bea.gov"
_BEA_ARCHIVE_HOST = "apps.bea.gov"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 256
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.hidden_depth == 0 and data.strip():
            self.parts.append(data.strip())


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _cell_column(reference: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", reference)
    if match is None:
        raise ValueError("spreadsheet cell reference is invalid")
    column = 0
    for char in match.group(1):
        column = column * 26 + ord(char) - ord("A") + 1
    return column, int(match.group(2))


def _xml(raw: bytes) -> ElementTree.Element:
    text = raw.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("spreadsheet XML declarations are not allowed")
    return ElementTree.fromstring(text)


def _xlsx_gdp_row(raw: bytes) -> tuple[date, dict[int, Decimal]]:
    if not raw or len(raw) > _MAX_WORKBOOK_BYTES:
        raise ValueError("BEA workbook size is outside the supported profile")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if (
            len(names) > _MAX_ARCHIVE_MEMBERS
            or len(set(names)) != len(names)
            or sum(item.file_size for item in members) > _MAX_UNCOMPRESSED_BYTES
            or any(
                item.filename.startswith("/")
                or ".." in PurePosixPath(item.filename).parts
                or item.flag_bits & 0x1
                for item in members
            )
        ):
            raise ValueError("BEA workbook archive structure is unsupported")

        workbook = _xml(archive.read("xl/workbook.xml"))
        relationships = _xml(archive.read("xl/_rels/workbook.xml.rels"))
        sheet_path: str | None = None
        links = relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
        if len({item.attrib["Id"] for item in links}) != len(links):
            raise ValueError("BEA workbook has duplicate relationship identities")
        targets = {
            item.attrib["Id"]: item.attrib["Target"]
            for item in links
            if item.attrib.get("TargetMode") != "External"
        }
        sheets = workbook.findall(f".//{{{_SHEET_NS}}}sheet")
        if len({item.attrib["name"] for item in sheets}) != len(sheets):
            raise ValueError("BEA workbook has duplicate sheet names")
        for sheet in sheets:
            if sheet.attrib.get("name") == "T10105-A":
                relationship_id = sheet.attrib.get(f"{{{_OFFICE_REL_NS}}}id")
                target = targets.get(relationship_id or "")
                if target is None:
                    raise ValueError("BEA annual GDP sheet is not bound")
                target_path = PurePosixPath(target)
                if target_path.is_absolute() or ".." in target_path.parts:
                    raise ValueError("BEA annual GDP sheet path is invalid")
                sheet_path = str(PurePosixPath("xl") / target_path)
                break
        if sheet_path not in names:
            raise ValueError("BEA annual GDP sheet is missing")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared_root = _xml(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.itertext())
                for node in shared_root.findall(f"{{{_SHEET_NS}}}si")
            ]
        worksheet = _xml(archive.read(sheet_path))
        rows: dict[int, dict[int, str]] = {}
        for row in worksheet.findall(f".//{{{_SHEET_NS}}}row"):
            for cell in row.findall(f"{{{_SHEET_NS}}}c"):
                if cell.find(f"{{{_SHEET_NS}}}f") is not None:
                    raise ValueError(
                        "BEA GDP source table must contain published values"
                    )
                reference = cell.attrib.get("r", "")
                column, row_number = _cell_column(reference)
                cell_type = cell.attrib.get("t")
                if cell_type == "inlineStr":
                    value = "".join(cell.itertext())
                else:
                    value_element = cell.find(f"{{{_SHEET_NS}}}v")
                    value = "" if value_element is None else value_element.text or ""
                    if cell_type == "s":
                        if int(value) < 0:
                            raise ValueError(
                                "BEA worksheet shared string index is invalid"
                            )
                        value = shared_strings[int(value)]
                cells = rows.setdefault(row_number, {})
                if column in cells:
                    raise ValueError("BEA worksheet contains duplicate cells")
                cells[column] = value.strip()

    title = rows.get(1, {}).get(1, "")
    units = rows.get(2, {}).get(1, "")
    if (
        title != "Table 1.1.5. Gross Domestic Product"
        or units != "[Millions of dollars]"
    ):
        raise ValueError("BEA annual GDP table title or units do not match")
    published = rows.get(5, {}).get(1, "")
    match = re.fullmatch(
        r"Data published ([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})", published
    )
    if match is None:
        raise ValueError("BEA annual GDP table omits its published date")
    try:
        published_date = date(
            int(match.group(3)), _MONTHS.index(match.group(1)) + 1, int(match.group(2))
        )
    except ValueError as error:
        raise ValueError("BEA annual GDP table published date is invalid") from error

    header = rows.get(8, {})
    years = {
        column: int(value) for column, value in header.items() if column >= 4 and value
    }
    if not years or sorted(years.values()) != list(
        range(min(years.values()), max(years.values()) + 1)
    ):
        raise ValueError("BEA annual GDP years are missing or nonconsecutive")
    gdp_rows = [
        cells
        for cells in rows.values()
        if cells.get(1) == "1"
        and cells.get(2, "").strip() == "Gross domestic product"
        and cells.get(3) == "A191RC"
    ]
    if len(gdp_rows) != 1:
        raise ValueError("BEA annual GDP row is missing or ambiguous")
    values = {year: Decimal(gdp_rows[0][column]) for column, year in years.items()}
    if any(not value.is_finite() or value <= 0 for value in values.values()):
        raise ValueError("BEA nominal GDP row contains a non-positive value")
    return published_date, values


def parse_bea_nominal_gdp_vintage(
    workbook: bytes,
    release_html: bytes,
    *,
    workbook_uri: str,
    release_uri: str,
    workbook_captured_at: datetime,
    release_captured_at: datetime,
) -> MacroSeriesVintageV1:
    """Bind archived BEA GDP values to publication time and normalized periods."""
    try:
        workbook_parts = urlsplit_checked(workbook_uri, _BEA_ARCHIVE_HOST)
        release_parts = urlsplit_checked(release_uri, _BEA_NEWS_HOST)
        archive_match = re.fullmatch(
            r"/HistData/Files/Releases/GDP_and_PI/([0-9]{4})/Q4/Third_([A-Za-z]+)-([0-9]{1,2})-([0-9]{4})/Section1all_xls\.xlsx",
            workbook_parts,
        )
        if archive_match is None or not re.fullmatch(
            r"/news/[0-9]{4}/gross-domestic-product-[a-z0-9-]+", release_parts
        ):
            raise ValueError("BEA source URI does not match the GDP vintage profile")
        if (
            len(release_html) > 2 * 1024 * 1024
            or not _aware(workbook_captured_at)
            or not _aware(release_captured_at)
        ):
            raise ValueError("BEA source capture metadata is invalid")

        visible = _VisibleText()
        visible.feed(release_html.decode("utf-8"))
        release_text = " ".join(" ".join(visible.parts).split())
        publications = tuple(
            re.finditer(
                r"EMBARGOED UNTIL RELEASE AT ([0-9]{1,2}):([0-9]{2}) a\.m\. (EDT|EST), ([A-Za-z]+), ([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})",
                release_text,
                re.IGNORECASE,
            )
        )
        if len(publications) != 1 or "Gross Domestic Product" not in release_text:
            raise ValueError("BEA GDP release publication metadata is missing")
        publication = publications[0]
        hour, minute = int(publication.group(1)), int(publication.group(2))
        if not 1 <= hour <= 12:
            raise ValueError("BEA GDP release hour is invalid")
        release_weekday = publication.group(4)
        month = _MONTHS.index(publication.group(5)) + 1
        release_date = date(int(publication.group(7)), month, int(publication.group(6)))
        if _WEEKDAYS[release_date.weekday()].casefold() != release_weekday.casefold():
            raise ValueError("BEA release weekday conflicts with its date")
        archive_date = date(
            int(archive_match.group(4)),
            _MONTHS.index(archive_match.group(2)) + 1,
            int(archive_match.group(3)),
        )
        if not release_date <= archive_date <= release_date + timedelta(days=7):
            raise ValueError("BEA archive and publication dates conflict")
        zone = ZoneInfo("America/New_York")
        release_at = datetime(
            release_date.year,
            release_date.month,
            release_date.day,
            hour % 12,
            minute,
            tzinfo=zone,
        )
        if publication.group(3).upper() == "EST" and release_at.dst() != timedelta(0):
            raise ValueError("BEA release timezone abbreviation conflicts with date")
        if publication.group(3).upper() == "EDT" and not release_at.dst():
            raise ValueError("BEA release timezone abbreviation conflicts with date")

        published_date, values = _xlsx_gdp_row(workbook)
        if published_date != release_date:
            raise ValueError("BEA workbook and release page dates conflict")
        latest_year = release_date.year - 1
        if not re.search(
            rf"Gross Domestic Product, (?:4th|Fourth) Quarter and Year {latest_year} "
            r"\(Third Estimate\)",
            release_text,
            re.IGNORECASE,
        ):
            raise ValueError("BEA release does not identify the Q4 third estimate")
        if (
            not values
            or max(values) != latest_year
            or int(archive_match.group(1)) != latest_year
        ):
            raise ValueError("BEA workbook vintage does not end in the latest year")
        captured_at = max(
            workbook_captured_at.astimezone(UTC),
            release_captured_at.astimezone(UTC),
        )
        # Archive dates identify a day, not an exact posting time. Wait until
        # that day has ended; the public release time alone cannot prove when
        # this full-history workbook was available in the archive.
        available_at = datetime.combine(
            archive_date + timedelta(days=1), time(), tzinfo=zone
        ).astimezone(UTC)
        if available_at > min(workbook_captured_at, release_captured_at):
            raise ValueError("BEA release timestamp is later than source capture")
        workbook_hash = _sha256(workbook)
        artifacts = (
            SourceArtifactV1(
                source_id="bea-nipa-archive",
                uri=workbook_uri,
                source_version=BEA_GDP_PROFILE,
                terms_reference=BEA_GDP_TERMS,
                content_sha256=workbook_hash,
                captured_at=workbook_captured_at.astimezone(UTC),
            ),
            SourceArtifactV1(
                source_id="bea-gdp-release",
                uri=release_uri,
                source_version=BEA_GDP_PROFILE,
                terms_reference=BEA_GDP_TERMS,
                content_sha256=_sha256(release_html),
                captured_at=release_captured_at.astimezone(UTC),
            ),
        )
        return MacroSeriesVintageV1.build(
            series_id="us.nominal_gdp",
            provider_id="bea-nipa",
            frequency="annual",
            unit="USD millions",
            source_version=BEA_GDP_PROFILE,
            available_at=available_at,
            captured_at=captured_at,
            artifacts=artifacts,
            observations=tuple(
                MacroObservationV1(
                    series_id="us.nominal_gdp",
                    period_start=date(year, 1, 1),
                    period_end=date(year, 12, 31),
                    value=value,
                    unit="USD millions",
                    source_sha256=workbook_hash,
                )
                for year, value in sorted(values.items())
            ),
        )
    except SnapshotError:
        raise
    except (
        KeyError,
        IndexError,
        ValueError,
        InvalidOperation,
        TypeError,
        UnicodeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        ValidationError,
        OverflowError,
    ) as error:
        raise SnapshotError(
            "BEA_GDP_SOURCE_INVALID",
            "retained BEA evidence does not reproduce the GDP vintage profile",
        ) from error


def urlsplit_checked(uri: str, expected_host: str) -> str:
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_host
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("BEA source URI is outside the official source profile")
    return parsed.path


class BeaNominalGdpVintageProvider:
    """BEA implementation of the provider-neutral macro vintage port."""

    provider_id = "bea-nipa"
    _SERIES_ID = "us.nominal_gdp"
    _SOURCE_IDS = {"bea-gdp-release", "bea-nipa-archive"}

    def supports(self, series_id: str) -> bool:
        return series_id == self._SERIES_ID

    def reproduce_vintage(
        self, *, series_id: str, sources: tuple[RetainedSourceV1, ...]
    ) -> MacroSeriesVintageV1:
        by_source = {source.source_id: source for source in sources}
        if (
            not self.supports(series_id)
            or len(sources) != 2
            or set(by_source) != self._SOURCE_IDS
            or any(source.source_version != BEA_GDP_PROFILE for source in sources)
            or any(source.terms_reference != BEA_GDP_TERMS for source in sources)
        ):
            raise SnapshotError(
                "BEA_GDP_SOURCE_INVALID",
                "BEA GDP vintage requires one release page and one NIPA workbook",
            )
        workbook = by_source["bea-nipa-archive"]
        release = by_source["bea-gdp-release"]
        return parse_bea_nominal_gdp_vintage(
            workbook.content,
            release.content,
            workbook_uri=workbook.uri,
            release_uri=release.uri,
            workbook_captured_at=workbook.captured_at,
            release_captured_at=release.captured_at,
        )
