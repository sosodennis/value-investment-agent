"""Rebuild the frozen quarterly and TTM reference cells from SEC originals.

This script owns no production calculation code. It reads the immutable cohort,
parses retained inline-XBRL documents, applies the published Decimal reference
rules, and compares its output with the checked-in golden files.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Annotated, Literal, TypeVar, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from lxml import etree, html
from pydantic import BaseModel, ConfigDict, Field


SCRIPT = Path(__file__).resolve()
SERVICE_ROOT = SCRIPT.parents[1]
REPOSITORY_ROOT = SERVICE_ROOT.parent
DEFAULT_FIXTURE_ROOT = SERVICE_ROOT / "tests/fixtures/quarterly-statements"
DEFAULT_ANNUAL_GOLDEN = (
    SERVICE_ROOT / "tests/fixtures/annual-statements/issue494-golden.json"
)
ROW_IDS_CORE: dict[str, tuple[str, ...]] = {
    "income_statement": ("revenue", "gross_profit", "operating_income", "net_income"),
    "balance_sheet": (
        "current_assets",
        "total_assets",
        "total_liabilities",
        "total_equity",
    ),
    "cash_flow": (
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "cash_flow_ending_balance",
    ),
}
FLOW_ROWS = {"additive_flow"}
MAX_RESPONSE_BYTES = 24_000_000
MAX_SUBMISSION_BYTES = 64_000_000
MIN_SEC_INTERVAL_SECONDS = 0.11
MAX_FIXTURE_BYTES = 500_000
COHORT_BASIS_MATRIX_SHA256 = (
    "a9b4fc174b3ca1350d1f2a363ee5993580a07255332c4f004ec552c3008c664b"
)
COHORT_BASIS_INDEX_SHA256 = (
    "0a71a41eadf2b589901d4d76adebb8c74b2ce846a5d74ea4438bc168b81c2e29"
)
COHORT_BASIS_FILINGS_PATH = "basis/cohort-filings.json"
COHORT_BASIS_SHARDS = {
    "basis/cohort-filings.json": "f5a14892565412946c10a208931a0ed82b12aff81bb297e4251638300541d35f",
    "basis/cohort-aapl-current.json": "e426865ec984560bc92eba6199c7431f71e081e8f238c653932e653d576c37a7",
    "basis/cohort-aapl-historical.json": "3cd3573abc27ab12d6bcba0ed51edf66279c672b48c7e5d3612310d7d33c1611",
    "basis/cohort-msft-current.json": "3c47290410d907e0e9cbb1605a836947f1dd80c9e65bb8d710990fce621916b8",
    "basis/cohort-msft-historical.json": "a33c92ea08afba129b409b1de5da9060653c80dfc5fd5ef1d9b1552ad4ba74c8",
}
CASH_OPENING_ROW = "cash_flow_beginning_balance"
CASH_CLOSING_ROW = "cash_flow_ending_balance"
CASH_NET_CHANGE_ROW = "net_change_in_cash"
SOURCE_ADMISSION_BLOCKED_ACCESSION = "0000950170-24-118967"
REVIEWED_BASIS_PROOFS = {
    "aapl-historical": {
        "basis/aapl-historical-2023-09-30.json": "7d68f0ab91b6bd1a381b544715999b249e2f6e8ccec5474297b4d7839ff42dcc",
    },
}
CASH_FLOW_BALANCE_QNAME = (
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
)


@dataclass(frozen=True)
class Interval:
    lower: Decimal
    upper: Decimal
    lower_inclusive: bool
    upper_inclusive: bool

    def json(self) -> dict[str, object]:
        return {
            "lower": decimal_text(self.lower),
            "upper": decimal_text(self.upper),
            "lower_inclusive": self.lower_inclusive,
            "upper_inclusive": self.upper_inclusive,
        }


@dataclass(frozen=True)
class Fact:
    observation_id: str
    row_id: str
    statement: str
    issuer_id: str
    accession_number: str
    form: str
    filing_date: str
    accepted_at: str
    report_date: str
    primary_document: str
    primary_html_sha256: str
    qname: str
    namespace_uri: str | None
    context_id: str | None
    entity_identifier: str | None
    entity_scheme: str | None
    period: dict[str, str]
    dimensions: tuple[dict[str, str], ...]
    unit_ref: str | None
    unit_measures: tuple[str, ...]
    raw_text: str
    value: Decimal | None
    numeric_error: str | None
    scale: str | None
    sign: str | None
    decimals: str | None
    format_name: str | None
    table_index: int
    row_index: int
    printed_row_label: str | None
    fact_index: int
    consolidation_scope: str = "consolidated"
    revision_basis_id: str | None = None
    cash_basis: str | None = None

    def json(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "row_id": self.row_id,
            "statement": self.statement,
            "issuer_id": self.issuer_id,
            "accession_number": self.accession_number,
            "form": self.form,
            "filing_date": self.filing_date,
            "accepted_at": self.accepted_at,
            "report_date": self.report_date,
            "primary_document": self.primary_document,
            "primary_html_sha256": self.primary_html_sha256,
            "qname": self.qname,
            "namespace_uri": self.namespace_uri,
            "context_id": self.context_id,
            "entity_identifier": self.entity_identifier,
            "entity_scheme": self.entity_scheme,
            "period": self.period,
            "dimensions": list(self.dimensions),
            "unit_ref": self.unit_ref,
            "unit_measures": list(self.unit_measures),
            "raw_text": self.raw_text,
            "canonical_decimal": decimal_text(self.value)
            if self.value is not None
            else None,
            "numeric_error": self.numeric_error,
            "scale": self.scale,
            "sign": self.sign,
            "decimals": self.decimals,
            "format": self.format_name,
            "table_index": self.table_index,
            "row_index": self.row_index,
            "printed_row_label": self.printed_row_label,
            "fact_index": self.fact_index,
            "consolidation_scope": self.consolidation_scope,
            "revision_basis_id": self.revision_basis_id,
            "cash_basis": self.cash_basis,
            "source_locator": {
                "primary_document_sha256": self.primary_html_sha256,
                "table_index": self.table_index,
                "row_index": self.row_index,
                "fact_index": self.fact_index,
                "context_id": self.context_id,
            },
        }


@dataclass
class ParsedFiling:
    metadata: dict[str, object]
    tables: dict[str, dict[str, object]]
    row_facts: dict[str, list[Fact]]
    table_rows: dict[str, list[dict[str, object]]]
    table_facts: dict[str, list[dict[str, object]]]
    namespace_uris: dict[str, str]


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FilingRole = Literal[
    "original_annual", "original_interim", "later_annual", "later_interim"
]
PairRole = Literal[
    "annual_flow",
    "nine_month_flow",
    "year_end_balance",
    "q3_cash_close",
    "year_end_cash_close",
]
CashScope = Literal[
    "includes_restricted_cash", "balance_sheet_cash_and_equivalents", "not_applicable"
]


class BasisRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


BasisModel = TypeVar("BasisModel", bound=BasisRecord)


class BasisParagraph(BasisRecord):
    xpath: str
    sha256: Digest


class BasisObservation(BasisRecord):
    observation_id: str
    sha256: Digest


class BasisFiling(BasisRecord):
    accession_number: str
    form: Literal["10-K", "10-Q"]
    reported_period_end: str
    accepted_at: str
    primary_document_uri: str
    primary_html_sha256: Digest
    primary_html_bytes: int
    opening_cash: BasisObservation
    disclosures: dict[str, BasisParagraph]


class BasisPair(BasisRecord):
    role: PairRole
    original: BasisObservation
    comparative: BasisObservation


class BasisRow(BasisRecord):
    cash_scope: CashScope
    pairs: list[BasisPair]


class BasisScope(BasisRecord):
    case_id: str
    issuer_id: str
    cutoff_at: str
    quarter_id: str
    quarter_start: str
    quarter_end: str
    fiscal_year_start: str
    fiscal_year_days: int
    nine_month_end: str


class BasisReview(BasisRecord):
    verdict: Literal["limited_support_at_filed_precision"]
    report_sha256: Digest
    evidence_snapshot_sha256: Digest
    independent_checker_sha256: Digest
    accounting_scope: Literal["consolidated_us_gaap"]
    policy_summary: str
    cash_summary: str
    limits: str


class ReviewedBasisProof(BasisRecord):
    protocol: Literal["issue495-reviewed-quarter-basis-v1"]
    scope: BasisScope
    filings: dict[FilingRole, BasisFiling]
    rows: dict[str, BasisRow]
    retained_submissions_sha256: Digest
    review: BasisReview


class CohortBasisAuthority(BasisRecord):
    matrix_sha256: Digest
    index_sha256: Digest
    scope: Literal[
        "25 selected primary statement rows at filed USD million precision, exact fixed cohort only"
    ]


class CohortFilingBasis(BasisRecord):
    issuer_id: str
    form: Literal["10-K", "10-Q"]
    reported_period_end: str
    accepted_at: str
    primary_document_uri: str
    primary_html_sha256: Digest
    primary_html_bytes: int = Field(gt=0)
    source_roles_by_case: dict[str, str]
    disclosures: dict[str, list[BasisParagraph]]


class CohortFilingRegistry(BasisRecord):
    protocol: Literal["issue495-reviewed-filing-basis-v1"]
    authority: CohortBasisAuthority
    filings: dict[str, CohortFilingBasis]


class CohortCatalogBasis(BasisRecord):
    submissions_sha256: Digest
    report_dates: Annotated[list[str], Field(min_length=2, max_length=2)]
    recent_accepted_range: Annotated[list[str], Field(min_length=2, max_length=2)]
    archived_filing_date_upper_bounds: list[str]


class CohortQuarterBasis(BasisRecord):
    quarter_id: str
    accession_number: str
    fiscal_year_focus: str
    fiscal_period_focus: Literal["Q1", "Q2", "Q3", "FY"]
    fiscal_year_start: str
    start_date: str
    end_date: str
    inclusive_calendar_days: int = Field(gt=0)
    period_source: dict[str, object]


PairIds = Annotated[list[str], Field(min_length=2, max_length=2)]
BasisVerdict = Literal["supported_limited", "not_comparable_missing_source"]


class CohortQuarterRow(BasisRecord):
    verdict: BasisVerdict
    cell_id: str
    statement: Literal["income_statement", "balance_sheet", "cash_flow"]
    selected_observation_ids: list[str]
    difference_observation_ids: list[str]
    original_comparative_pairs: list[PairIds]
    same_filing_duplicate_pairs: list[PairIds]
    source_available_at: str | None
    uses_blocked_source: bool


class CohortOpeningCash(BasisRecord):
    observation_id: str
    fact_id: str
    xpath: str


class CohortQuarterProof(BasisRecord):
    period: CohortQuarterBasis
    rows: dict[str, CohortQuarterRow]
    original_anchor_accessions: list[str]
    fiscal_opening_cash: list[CohortOpeningCash]


class CohortTtmRow(BasisRecord):
    verdict: BasisVerdict
    selected_quarter_cell_ids: list[str]
    selected_observation_ids: list[str]
    source_available_at: str | None
    uses_blocked_source: bool


class CohortTtmProof(BasisRecord):
    window_id: str
    start_date: str
    end_date: str
    inclusive_calendar_days: int = Field(gt=0)
    quarter_ids: Annotated[list[str], Field(min_length=4, max_length=4)]
    crosses_fiscal_year: bool
    adjacent_cash_boundary_fact_ids: Annotated[
        list[PairIds], Field(min_length=3, max_length=3)
    ]
    rows: dict[str, CohortTtmRow]


class CohortCaseProof(BasisRecord):
    protocol: Literal["issue495-reviewed-cohort-basis-v1"]
    authority: CohortBasisAuthority
    case_id: str
    issuer_id: str
    cutoff_at: str
    catalog: CohortCatalogBasis
    source_accessions: list[str]
    observation_sha256: dict[str, Digest]
    quarters: dict[str, CohortQuarterProof]
    ttm: dict[str, CohortTtmProof]


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite Decimal is not a fiscal statement value")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def local_name(element: object) -> str:
    tag = getattr(element, "tag", "")
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].split(":")[-1].casefold()


def attributes(element: object) -> dict[str, str]:
    values = getattr(element, "attrib", {})
    return {
        str(key).rsplit("}", 1)[-1].casefold(): str(value)
        for key, value in values.items()
    }


def descendants_named(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element.iterdescendants() if local_name(child) == name]


def direct_children_named(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if local_name(child) == name]


def text_content(element: etree._Element) -> str:
    return normalize_space(" ".join(str(item) for item in element.itertext()))


def parse_contexts(tree: etree._Element) -> dict[str, dict[str, object]]:
    contexts: dict[str, dict[str, object]] = {}
    for element in tree.iter():
        if local_name(element) != "context":
            continue
        context_id = attributes(element).get("id")
        if not context_id:
            continue
        identifier_nodes = descendants_named(element, "identifier")
        periods = direct_children_named(element, "period")
        if not periods:
            continue
        period = periods[0]
        instants = direct_children_named(period, "instant")
        starts = direct_children_named(period, "startdate")
        ends = direct_children_named(period, "enddate")
        if instants:
            period_value = {
                "period_type": "instant",
                "instant": text_content(instants[0]),
            }
        else:
            period_value = {
                "period_type": "duration",
                "start_date": text_content(starts[0]) if starts else "",
                "end_date": text_content(ends[0]) if ends else "",
            }
        dimensions = []
        for member in element.iterdescendants():
            kind = local_name(member)
            if kind not in {"explicitmember", "typedmember"}:
                continue
            dimensions.append(
                {
                    "kind": kind,
                    "dimension": attributes(member).get("dimension", ""),
                    "member_or_value": text_content(member),
                }
            )
        contexts[context_id] = {
            "entity_identifier": text_content(identifier_nodes[0])
            if identifier_nodes
            else None,
            "entity_scheme": attributes(identifier_nodes[0]).get("scheme")
            if identifier_nodes
            else None,
            "period": period_value,
            "dimensions": tuple(dimensions),
        }
    return contexts


def parse_units(tree: etree._Element) -> dict[str, tuple[str, ...]]:
    units: dict[str, tuple[str, ...]] = {}
    for element in tree.iter():
        if local_name(element) == "unit":
            unit_id = attributes(element).get("id")
            if unit_id:
                units[unit_id] = tuple(
                    text_content(item) for item in descendants_named(element, "measure")
                )
    return units


def parse_numeric(raw_text: str, scale: str | None, sign: str | None) -> Decimal:
    value = raw_text.strip().replace(",", "").replace("$", "").replace("%", "")
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    number = Decimal(value)
    if sign == "-":
        number = number.copy_abs().copy_negate()
    elif sign == "+":
        number = number.copy_abs()
    if not number.is_finite():
        raise InvalidOperation("non-finite inline XBRL value")
    if scale is not None:
        parts = number.as_tuple()
        number = Decimal((parts.sign, parts.digits, int(parts.exponent) + int(scale)))
    return number


def decimals_interval(value: Decimal, decimals: str | None) -> Interval | None:
    if decimals is None or decimals == "INF":
        return Interval(value, value, True, True)
    try:
        precision = int(decimals)
    except ValueError:
        return None
    quantum = Decimal(1).scaleb(-precision)
    half = quantum / Decimal(2)
    return Interval(value - half, value + half, True, False)


def add_intervals(left: Interval, right: Interval) -> Interval:
    return Interval(
        left.lower + right.lower,
        left.upper + right.upper,
        left.lower_inclusive and right.lower_inclusive,
        left.upper_inclusive and right.upper_inclusive,
    )


def subtract_intervals(left: Interval, right: Interval) -> Interval:
    return Interval(
        left.lower - right.upper,
        left.upper - right.lower,
        left.lower_inclusive and right.upper_inclusive,
        left.upper_inclusive and right.lower_inclusive,
    )


def intervals_overlap(left: Interval, right: Interval) -> bool:
    if left.upper < right.lower or right.upper < left.lower:
        return False
    if left.upper == right.lower:
        return left.upper_inclusive and right.lower_inclusive
    if right.upper == left.lower:
        return right.upper_inclusive and left.lower_inclusive
    return True


def expected_terms(row_id: str, labels: list[str]) -> list[set[str]]:
    del row_id
    return [
        {
            term
            for term in re.findall(r"[a-z]+", label.casefold())
            if term not in {"and", "of", "the", "in", "by"}
        }
        for label in labels
    ]


def label_matches(row_id: str, labels: list[str], actual: str | None) -> bool:
    if not labels or not actual:
        return True
    actual_words = {
        term
        for term in re.findall(r"[a-z]+", actual.casefold())
        if term not in {"and", "of", "the", "in", "by"}
    }
    if row_id == "cash_flow_beginning_balance":
        return "beginning" in actual_words
    if row_id == "cash_flow_ending_balance":
        return "ending" in actual_words or "end" in actual_words
    return any(
        len(terms & actual_words) / len(terms) >= 0.6
        for terms in expected_terms(row_id, labels)
        if terms
    )


def table_heading(table: etree._Element) -> str:
    parts: list[str] = []
    for sibling in table.itersiblings(preceding=True):
        if local_name(sibling) in {"h1", "h2", "h3", "p", "div", "span", "caption"}:
            text = text_content(sibling)
            if text:
                parts.append(text)
            if len(parts) == 4:
                break
    captions = [child for child in table if local_name(child) == "caption"]
    if captions:
        parts.insert(0, text_content(captions[0]))
    return " | ".join(parts)


def row_label(row: etree._Element) -> str | None:
    cells = [cell for cell in row if local_name(cell) in {"td", "th"}]
    if not cells:
        return None
    return text_content(cells[0]) or None


def read_original(
    receipt: dict[str, object], source_root: Path, fetch: bool, user_agent: str | None
) -> bytes:
    content_hash = str(receipt["content_hash"])
    uri = str(receipt["uri"])
    if not re.fullmatch(r"[0-9a-f]{64}", content_hash):
        raise ValueError(f"invalid retained source digest for {uri}")
    suffix = ".json" if receipt["media_type"] == "application/json" else ".bin"
    path = source_root / "content" / content_hash[:2] / f"{content_hash}{suffix}"
    if path.is_file():
        payload = path.read_bytes()
    elif fetch:
        payload = fetch_sec_uri(uri, content_hash, user_agent)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
    else:
        raise FileNotFoundError(
            f"retained source bytes are missing for {receipt['uri']}"
        )
    if hashlib.sha256(payload).hexdigest() != content_hash:
        raise ValueError(f"retained source digest differs for {uri}")
    if len(payload) != integer(receipt["received_size"]):
        raise ValueError(f"retained source size differs for {uri}")
    return payload


def fetch_sec_uri(uri: str, expected_hash: str, user_agent: str | None) -> bytes:
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.sec.gov"
        or parsed.port is not None
    ):
        raise ValueError(
            "SEC re-fetch accepts only exact HTTPS www.sec.gov filing URLs"
        )
    agent = (user_agent or os.environ.get("SEC_USER_AGENT", "")).strip()
    if not agent or "@" not in agent:
        raise ValueError("set SEC_USER_AGENT to an identifiable contact address")
    time.sleep(MIN_SEC_INTERVAL_SECONDS)
    request = Request(
        uri,
        headers={"User-Agent": agent, "Accept": "text/html, application/octet-stream"},
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                limit = (
                    MAX_SUBMISSION_BYTES if uri.endswith(".txt") else MAX_RESPONSE_BYTES
                )
                payload = response.read(limit + 1)
                if len(payload) > limit:
                    raise ValueError(
                        f"SEC filing response exceeded the {limit} byte limit"
                    )
                break
        except HTTPError as error:
            if error.code == 429 or 500 <= error.code < 600:
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
            raise
        except (URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            raise
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValueError(f"SEC bytes no longer match frozen digest {expected_hash}")
    return payload


def response_for_primary(filing: dict[str, object]) -> dict[str, object]:
    responses = cast(list[dict[str, object]], filing["source_responses"])
    primary_document = str(filing["primary_document"])
    matches = [
        response
        for response in responses
        if str(response["uri"]).endswith("/" + primary_document)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one retained primary response for {filing['accession_number']}"
        )
    return matches[0]


def build_row_catalog(
    annual: dict[str, object], policy: dict[str, object]
) -> dict[str, dict[str, dict[str, object]]]:
    rows = cast(list[dict[str, object]], policy["rows"])
    annual_filings = cast(list[dict[str, object]], annual["filings"])
    catalog: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        row_id = str(row["row_id"])
        catalog[row_id] = {}
        for filing in annual_filings:
            issuer_id = str(filing["issuer_id"])
            row_data = next(
                item
                for statement in cast(list[dict[str, object]], filing["statements"])
                for item in cast(list[dict[str, object]], statement["rows"])
                if item["row_id"] == row_id
            )
            entries = catalog[row_id].setdefault(
                issuer_id,
                {"concept_qnames": [], "printed_row_labels": []},
            )
            qnames = cast(list[str], entries["concept_qnames"])
            labels = cast(list[str], entries["printed_row_labels"])
            if (
                row_data.get("printed_row_label")
                and row_data["printed_row_label"] not in labels
            ):
                labels.append(str(row_data["printed_row_label"]))
            for value in cast(list[dict[str, object]], row_data.get("values", [])):
                qname = str(value["concept_qname"])
                if qname not in qnames:
                    qnames.append(qname)
        for issuer in catalog[row_id].values():
            cast(list[str], issuer["concept_qnames"]).sort()
            cast(list[str], issuer["printed_row_labels"]).sort()
    for row in rows:
        row["source_mappings"] = catalog[str(row["row_id"])]
    return catalog


def parse_filing(
    filing: dict[str, object],
    issuer_id: str,
    row_policy: list[dict[str, object]],
    row_catalog: dict[str, dict[str, dict[str, object]]],
    source_root: Path,
    fetch: bool,
    user_agent: str | None,
) -> ParsedFiling:
    receipt_list = cast(list[dict[str, object]], filing["source_responses"])
    accession = str(filing["accession_number"])
    cik = str(int(issuer_id))
    prefix = (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
    )
    expected_uris = {
        prefix + "index.json",
        prefix + accession + "-xbrl.zip",
        prefix + str(filing["primary_document"]),
        prefix + accession + ".txt",
    }
    if {str(item["uri"]) for item in receipt_list} != expected_uris or len(
        receipt_list
    ) != 4:
        raise ValueError(
            f"{accession} does not have the four accession-scoped response receipts"
        )
    for receipt in receipt_list:
        scope = cast(dict[str, object], receipt["scope"])
        if str(int(str(scope["cik"]))) != cik or scope["accession_number"] != accession:
            raise ValueError(
                f"{accession} has a response receipt bound to another filing"
            )
        read_original(receipt, source_root, fetch, user_agent)
    primary_receipt = response_for_primary(filing)
    raw = read_original(primary_receipt, source_root, fetch, user_agent)
    primary_hash = hashlib.sha256(raw).hexdigest()
    try:
        tree = html.fromstring(raw)
    except (etree.ParserError, ValueError, TypeError) as error:
        raise ValueError(
            f"primary HTML could not be parsed for {filing['accession_number']}"
        ) from error
    namespace_uris: dict[str, str] = {}
    for match in re.finditer(
        rb"xmlns(?::([A-Za-z_][A-Za-z0-9_.-]*))?\s*=\s*([\"'])(.*?)\2",
        raw,
        flags=re.IGNORECASE,
    ):
        prefix = (
            match.group(1).decode("ascii", errors="replace") if match.group(1) else ""
        )
        namespace_uris[prefix] = match.group(3).decode("utf-8", errors="replace")
    contexts = parse_contexts(tree)
    units = parse_units(tree)
    identifiers = {
        text_content(element)
        for element in tree.iter()
        if local_name(element) == "nonnumeric"
        and attributes(element).get("name", "").split(":")[-1]
        == "EntityCentralIndexKey"
    }
    if not contexts or not units or issuer_id not in identifiers:
        raise ValueError(f"missing inline XBRL filing identity for {accession}")
    tables = tree.xpath("//table")
    table_index = {table: index for index, table in enumerate(tables)}
    rows_by_table = {table: list(table.iterdescendants("tr")) for table in tables}
    row_index = {
        table: {row: index for index, row in enumerate(rows)}
        for table, rows in rows_by_table.items()
    }
    all_facts: list[dict[str, object]] = []
    xbrl_fact_index = 0
    for element in tree.iter():
        if local_name(element) not in {"nonfraction", "nonnumeric", "fraction"}:
            continue
        attrs = attributes(element)
        qname = attrs.get("name")
        if not qname:
            continue
        context_id = attrs.get("contextref")
        context = contexts.get(context_id or "")
        table = element
        while table is not None and local_name(table) != "table":
            table = table.getparent()
        row = element
        while row is not None and local_name(row) != "tr":
            row = row.getparent()
        table_id = table_index.get(table)
        current_row_index = row_index.get(table, {}).get(row)
        raw_text = text_content(element)
        try:
            value = (
                parse_numeric(raw_text, attrs.get("scale"), attrs.get("sign"))
                if local_name(element) == "nonfraction"
                else None
            )
            numeric_error = (
                None
                if value is not None or local_name(element) != "nonfraction"
                else "empty_numeric_value"
            )
        except (InvalidOperation, ValueError) as error:
            value = None
            numeric_error = str(error)
        all_facts.append(
            {
                "fact_index": xbrl_fact_index,
                "qname": qname,
                "context_id": context_id,
                "context": context,
                "unit_ref": attrs.get("unitref"),
                "unit_measures": units.get(attrs.get("unitref", ""), ()),
                "raw_text": raw_text,
                "value": value,
                "numeric_error": numeric_error,
                "scale": attrs.get("scale"),
                "sign": attrs.get("sign"),
                "decimals": attrs.get("decimals"),
                "format": attrs.get("format"),
                "table_index": table_id,
                "row_index": current_row_index,
                "printed_row_label": row_label(row) if row is not None else None,
            }
        )
        xbrl_fact_index += 1

    selected_tables: dict[str, dict[str, object]] = {}
    statement_table_facts: dict[str, list[dict[str, object]]] = {}
    for statement in ("income_statement", "balance_sheet", "cash_flow"):
        statement_rows = [row for row in row_policy if row["statement"] == statement]
        candidates = []
        for index, table in enumerate(tables):
            table_facts = [fact for fact in all_facts if fact["table_index"] == index]
            covered = set()
            for row in statement_rows:
                row_id = str(row["row_id"])
                qnames = cast(
                    list[str],
                    row_catalog[row_id].get(issuer_id, {}).get("concept_qnames", []),
                )
                if any(fact["qname"] in qnames for fact in table_facts):
                    covered.add(row_id)
            core_covered = len(covered.intersection(ROW_IDS_CORE[statement]))
            if covered:
                candidates.append(
                    {
                        "table_index": index,
                        "row_ids_covered": sorted(covered),
                        "core_rows_covered": core_covered,
                        "table_heading": table_heading(table),
                    }
                )
        if not candidates:
            raise ValueError(
                f"{filing['accession_number']} lacks a mapped {statement} table"
            )
        candidates.sort(
            key=lambda item: (
                integer(item["core_rows_covered"]),
                len(cast(list[str], item["row_ids_covered"])),
            ),
            reverse=True,
        )
        top_score = (
            integer(candidates[0]["core_rows_covered"]),
            len(cast(list[str], candidates[0]["row_ids_covered"])),
        )
        best = [
            item
            for item in candidates
            if (
                integer(item["core_rows_covered"]),
                len(cast(list[str], item["row_ids_covered"])),
            )
            == top_score
        ]
        if len(best) != 1:
            raise ValueError(
                f"{filing['accession_number']} has ambiguous {statement} tables"
            )
        selected = integer(best[0]["table_index"])
        rows = []
        for index, table_row in enumerate(rows_by_table[tables[selected]]):
            rows.append(
                {
                    "row_index": index,
                    "printed_label": row_label(table_row),
                    "text": text_content(table_row),
                    "fact_indexes": [
                        integer(fact["fact_index"])
                        for fact in all_facts
                        if fact["table_index"] == selected
                        and fact["row_index"] == index
                    ],
                }
            )
        selected_tables[statement] = {
            **best[0],
            "selection_basis": "unique primary table with the greatest canonical-row and core-row coverage",
            "all_candidate_tables": candidates,
            "table_rows": rows,
        }
        statement_table_facts[statement] = [
            {
                "fact_index": fact["fact_index"],
                "qname": fact["qname"],
                "namespace_uri": namespace_uris.get(
                    str(fact["qname"]).partition(":")[0]
                ),
                "context_id": fact["context_id"],
                "context": fact["context"],
                "unit_measures": list(cast(tuple[str, ...], fact["unit_measures"])),
                "raw_text": fact["raw_text"],
                "canonical_decimal": decimal_text(cast(Decimal, fact["value"]))
                if fact["value"] is not None
                else None,
                "numeric_error": fact["numeric_error"],
                "scale": fact["scale"],
                "sign": fact["sign"],
                "decimals": fact["decimals"],
                "table_index": selected,
                "row_index": fact["row_index"],
                "printed_row_label": fact["printed_row_label"],
            }
            for fact in all_facts
            if fact["table_index"] == selected
        ]

    row_facts: dict[str, list[Fact]] = {str(row["row_id"]): [] for row in row_policy}
    for row in row_policy:
        row_id = str(row["row_id"])
        statement = str(row["statement"])
        issuer_map = row_catalog[row_id].get(issuer_id, {})
        qnames = cast(list[str], issuer_map.get("concept_qnames", []))
        labels = cast(list[str], issuer_map.get("printed_row_labels", []))
        selected = integer(selected_tables[statement]["table_index"])
        for fact in all_facts:
            if fact["table_index"] != selected:
                continue
            if str(fact["qname"]) not in qnames or not label_matches(
                row_id, labels, cast(str | None, fact["printed_row_label"])
            ):
                continue
            context = cast(dict[str, object] | None, fact["context"])
            period = cast(dict[str, str], context["period"]) if context else {}
            facts_dimensions = (
                cast(tuple[dict[str, str], ...], context["dimensions"])
                if context
                else ()
            )
            fact_value = cast(Decimal | None, fact["value"])
            observation_id = f"{filing['accession_number']}/fact-{fact['fact_index']}"
            row_facts[row_id].append(
                Fact(
                    observation_id=observation_id,
                    row_id=row_id,
                    statement=statement,
                    issuer_id=issuer_id,
                    accession_number=str(filing["accession_number"]),
                    form=str(filing["form"]),
                    filing_date=str(filing["filing_date"]),
                    accepted_at=str(filing["accepted_at"]),
                    report_date=str(filing["reported_period_end"]),
                    primary_document=str(filing["primary_document"]),
                    primary_html_sha256=primary_hash,
                    qname=str(fact["qname"]),
                    namespace_uri=namespace_uris.get(
                        str(fact["qname"]).partition(":")[0]
                    ),
                    context_id=cast(str | None, fact["context_id"]),
                    entity_identifier=cast(str | None, context["entity_identifier"])
                    if context
                    else None,
                    entity_scheme=cast(str | None, context["entity_scheme"])
                    if context
                    else None,
                    period=period,
                    dimensions=facts_dimensions,
                    unit_ref=cast(str | None, fact["unit_ref"]),
                    unit_measures=cast(tuple[str, ...], fact["unit_measures"]),
                    raw_text=str(fact["raw_text"]),
                    value=fact_value,
                    numeric_error=cast(str | None, fact["numeric_error"]),
                    scale=cast(str | None, fact["scale"]),
                    sign=cast(str | None, fact["sign"]),
                    decimals=cast(str | None, fact["decimals"]),
                    format_name=cast(str | None, fact["format"]),
                    table_index=integer(fact["table_index"]),
                    row_index=integer(fact["row_index"]),
                    printed_row_label=cast(str | None, fact["printed_row_label"]),
                    fact_index=integer(fact["fact_index"]),
                )
            )
    selected_table_rows = {
        statement: cast(
            list[dict[str, object]], selected_tables[statement]["table_rows"]
        )
        for statement in selected_tables
    }
    return ParsedFiling(
        metadata={
            **filing,
            "issuer_id": issuer_id,
            "primary_html_sha256": primary_hash,
            "primary_receipt": primary_receipt,
        },
        tables=selected_tables,
        row_facts=row_facts,
        table_rows=selected_table_rows,
        table_facts=statement_table_facts,
        namespace_uris=namespace_uris,
    )


def period_of(fact: Fact) -> tuple[str, ...]:
    if fact.period.get("period_type") == "instant":
        return ("instant", fact.period.get("instant", ""))
    return (
        "duration",
        fact.period.get("start_date", ""),
        fact.period.get("end_date", ""),
    )


def eligible_facts(
    facts: list[Fact],
    issuer_id: str,
    cutoff_at: str,
    expected_period: tuple[str, ...],
) -> list[Fact]:
    cutoff = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
    return [
        fact
        for fact in facts
        if fact.issuer_id == issuer_id
        and period_of(fact) == expected_period
        and fact.entity_identifier == issuer_id
        and not fact.dimensions
        and fact.consolidation_scope == "consolidated"
        and (not fact.form.endswith("/A") or fact.revision_basis_id is not None)
        and fact.value is not None
        and fact.unit_measures == ("iso4217:USD",)
        and datetime.fromisoformat(fact.accepted_at.replace("Z", "+00:00")) <= cutoff
    ]


def choose_latest(candidates: list[Fact]) -> tuple[Fact | None, dict[str, object]]:
    if not candidates:
        return None, {
            "status": "unavailable",
            "reason": "no_eligible_unsegmented_usd_fact",
        }
    candidates = sorted(
        candidates,
        key=lambda item: (item.accepted_at, item.accession_number, item.fact_index),
    )
    latest_acceptance = candidates[-1].accepted_at
    latest = [fact for fact in candidates if fact.accepted_at == latest_acceptance]
    if len(latest) == 1:
        selected = latest[0]
    else:
        intervals = [
            decimals_interval(fact_value(fact), fact.decimals) for fact in latest
        ]
        known = [item for item in intervals if item is not None]
        compatible = len(known) == len(latest) and all(
            intervals_overlap(known[0], item) for item in known[1:]
        )
        duplicate = all(
            fact.value == latest[0].value
            and fact.decimals == latest[0].decimals
            and fact.unit_measures == latest[0].unit_measures
            and fact.context_id == latest[0].context_id
            and fact.qname == latest[0].qname
            for fact in latest[1:]
        )
        if not compatible or not duplicate:
            return None, {
                "status": "conflict",
                "reason": "latest_same_acceptance_facts_are_not_exact_duplicate_observations",
                "latest_candidate_ids": [fact.observation_id for fact in latest],
            }
        selected = sorted(latest, key=lambda item: (item.qname, item.fact_index))[0]
    return selected, {
        "status": "selected",
        "selected_observation_id": selected.observation_id,
        "selection_rule": "latest fact-level disclosure accepted by the case cutoff",
        "candidate_observation_ids": [fact.observation_id for fact in candidates],
        "superseded_observation_ids": [
            fact.observation_id
            for fact in candidates
            if fact.accepted_at < latest_acceptance
        ],
        "same_acceptance_comparatives": [
            fact.observation_id
            for fact in candidates
            if fact.accepted_at == latest_acceptance
            and fact.observation_id != selected.observation_id
        ],
        "latest_acceptance_at": latest_acceptance,
    }


def candidate_json(facts: list[Fact]) -> list[str]:
    return sorted({fact.observation_id for fact in facts})


def row_catalog_for_case(row_id: str, parsed: dict[str, ParsedFiling]) -> list[Fact]:
    return [fact for filing in parsed.values() for fact in filing.row_facts[row_id]]


def fiscal_start_for_target(
    row_id: str,
    target: dict[str, object],
    parsed: dict[str, ParsedFiling],
    case: dict[str, object],
) -> str:
    end = str(target["end_date"])
    accession = str(target["accession_number"])
    current = parsed[accession]
    candidates = [
        fact
        for fact in current.row_facts[row_id]
        if fact.period.get("period_type") == "duration"
        and fact.period.get("end_date") == end
        and fact.entity_identifier == fact.issuer_id
        and not fact.dimensions
        and fact.value is not None
        and fact.unit_measures == ("iso4217:USD",)
    ]
    if not candidates:
        raise ValueError(
            f"{accession} lacks the revenue duration that anchors its fiscal period"
        )
    candidates.sort(
        key=lambda fact: (
            date.fromisoformat(fact.period.get("start_date", end))
            - date.fromisoformat(end)
        )
    )
    # The longest current-year duration ending at the report date is the YTD
    # observation. Q1 has no longer duration, so its quarter start is the FY start.
    return candidates[0].period["start_date"]


def interval_for_fact(fact: Fact | None) -> Interval | None:
    if fact is None or fact.value is None:
        return None
    return decimals_interval(fact.value, fact.decimals)


def fact_interval_json(fact: Fact | None) -> dict[str, object] | None:
    interval = interval_for_fact(fact)
    return interval.json() if interval is not None else None


def fact_value(fact: Fact) -> Decimal:
    if fact.value is None:
        raise ValueError(f"observation {fact.observation_id} lacks a numeric value")
    return fact.value


def fact_values(facts: list[Fact]) -> tuple[list[Fact], list[str]]:
    return [fact for fact in facts if fact.value is not None], candidate_json(facts)


def make_raw_choice(
    row_id: str,
    expected_period: tuple[str, ...],
    parsed: dict[str, ParsedFiling],
    issuer_id: str,
    cutoff_at: str,
) -> tuple[Fact | None, dict[str, object], list[Fact]]:
    row_ids = (
        ("cash_flow_beginning_balance", "cash_flow_ending_balance")
        if row_id == "cash_flow_beginning_balance"
        else (row_id,)
    )
    raw = [
        fact
        for candidate_row in row_ids
        for fact in row_catalog_for_case(candidate_row, parsed)
        if period_of(fact) == expected_period
    ]
    cutoff = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
    eligible = eligible_facts(raw, issuer_id, cutoff_at, expected_period)
    selected, decision = choose_latest(eligible)
    rejected = []
    for fact in raw:
        reasons = []
        if fact.issuer_id != issuer_id or fact.entity_identifier != issuer_id:
            reasons.append("issuer_mismatch")
        if fact.dimensions:
            reasons.append("dimensional_context")
        if fact.consolidation_scope != "consolidated":
            reasons.append("consolidation_scope_mismatch")
        if fact.form.endswith("/A") and fact.revision_basis_id is None:
            reasons.append("unknown_amendment_scope")
        if fact.unit_measures != ("iso4217:USD",):
            reasons.append("unit_mismatch")
        if fact.value is None:
            reasons.append("invalid_numeric_fact")
        if datetime.fromisoformat(fact.accepted_at.replace("Z", "+00:00")) > cutoff:
            reasons.append("after_cutoff")
        if reasons:
            rejected.append({"observation_id": fact.observation_id, "reasons": reasons})
    decision["rejected_candidates"] = rejected
    decision["eligible_candidate_ids"] = candidate_json(eligible)
    return selected, decision, raw


def unavailable_or_missing(
    decisions: list[dict[str, object]], candidates: list[Fact]
) -> str:
    if any(decision.get("status") == "conflict" for decision in decisions):
        return "conflict"
    return "unavailable" if candidates else "missing"


def raw_interval(
    identifiers: list[str], observations: dict[str, dict[str, object]]
) -> Interval | None:
    values = [observations[item] for item in identifiers]
    intervals: list[Interval] = []
    for value in values:
        number = Decimal(str(value["canonical_decimal"]))
        interval = decimals_interval(number, cast(str | None, value["decimals"]))
        if interval is None:
            return None
        intervals.append(interval)
    if not intervals:
        return None
    return intervals[0]


def serialize_fact(fact: Fact) -> dict[str, object]:
    return fact.json()


def fact_basis_signature(fact: Fact) -> tuple[object, ...]:
    return (
        fact.issuer_id,
        fact.entity_identifier,
        fact.entity_scheme,
        fact.namespace_uri,
        fact.qname,
        fact.unit_measures,
        tuple(
            sorted(
                (item["kind"], item["dimension"], item["member_or_value"])
                for item in fact.dimensions
            )
        ),
    )


def basis_conflict(facts: list[dict[str, object]]) -> str | None:
    for field, code in (
        ("issuer_id", "issuer_mismatch"),
        ("entity_identifier", "issuer_mismatch"),
        ("entity_scheme", "entity_scheme_mismatch"),
        ("consolidation_scope", "consolidation_scope_mismatch"),
        ("unit_measures", "unit_mismatch"),
        ("dimensions", "dimension_mismatch"),
        ("qname", "concept_mismatch"),
        ("cash_basis", "cash_basis_mismatch"),
        ("revision_basis_id", "revision_basis_mismatch"),
    ):
        if len({json.dumps(fact.get(field), sort_keys=True) for fact in facts}) > 1:
            return code
    namespaces = {
        re.sub(
            r"^(https?://fasb\.org/us-gaap)/20[0-9]{2}$",
            r"\1",
            str(fact.get("namespace_uri")),
        )
        for fact in facts
    }
    if len(namespaces) > 1:
        return "taxonomy_namespace_mismatch"
    return None


def basis_evidence(facts: list[Fact], *, required_scope: str) -> dict[str, object]:
    signatures = [fact_basis_signature(fact) for fact in facts]
    consistent = bool(signatures) and all(
        signature == signatures[0] for signature in signatures[1:]
    )
    return {
        "status": "same_fact_basis_fingerprint"
        if consistent
        else "basis_fingerprint_mismatch_or_unavailable",
        "same_fact_basis_fingerprint": consistent,
        "proof_scope": required_scope,
        "basis_conflict": basis_conflict([fact.json() for fact in facts]),
        "formal_accounting_policy_and_amendment_lineage": "not_claimed_by_this_reference_fixture",
        "facts": [
            {
                "observation_id": fact.observation_id,
                "issuer_id": fact.issuer_id,
                "entity_identifier": fact.entity_identifier,
                "entity_scheme": fact.entity_scheme,
                "namespace_uri": fact.namespace_uri,
                "qname": fact.qname,
                "unit_measures": list(fact.unit_measures),
                "dimensions": list(fact.dimensions),
                "accession_number": fact.accession_number,
                "accepted_at": fact.accepted_at,
                "form": fact.form,
                "revision_basis_id": fact.revision_basis_id,
                "cash_basis": fact.cash_basis,
                "primary_html_sha256": fact.primary_html_sha256,
                "printed_row_label": fact.printed_row_label,
                "source_locator": fact.json()["source_locator"],
            }
            for fact in facts
        ],
    }


def build_missing_evidence(
    row: dict[str, object],
    issuer_id: str,
    source_accessions: list[str],
    parsed: dict[str, ParsedFiling],
) -> dict[str, object]:
    statement = str(row["statement"])
    if row["row_id"] != "effect_of_exchange_rates_on_cash":
        return {
            "reason": "no_eligible_unsegmented_usd_fact_for_the_requested_period",
            "issuer_id": issuer_id,
            "row_id": row["row_id"],
            "primary_table_scans": [],
        }
    search_terms = ("exchange", "foreign", "currency translation")
    scans = []
    for accession in source_accessions:
        filing = parsed[accession]
        if statement != "cash_flow":
            continue
        rows = filing.table_rows[statement]
        matching = [
            item
            for item in rows
            if any(term in str(item["text"]).casefold() for term in search_terms)
        ]
        matching_indices = {integer(item["row_index"]) for item in matching}
        numeric_facts = [
            fact
            for fact in filing.table_facts[statement]
            if fact["row_index"] in matching_indices
            and fact["canonical_decimal"] is not None
        ]
        untagged_numeric_rows = [
            item
            for item in matching
            if re.search(r"(?:\(?\$?\s*-?\d[\d,]*(?:\.\d+)?\)?%?)", str(item["text"]))
        ]
        scans.append(
            {
                "accession_number": accession,
                "primary_html_sha256": filing.metadata["primary_html_sha256"],
                "selected_table_index": filing.tables[statement]["table_index"],
                "search_terms_casefold": search_terms,
                "matched_statement_rows": matching,
                "numeric_inline_facts_in_matched_rows": numeric_facts,
                "untagged_numeric_rows": untagged_numeric_rows,
                "no_unmapped_primary_table_value": not numeric_facts
                and not untagged_numeric_rows,
            }
        )
    return {
        "reason": "no_exchange_or_foreign_currency_line_with_a_numeric_inline_fact_in_the_primary_cash_flow_table",
        "issuer_id": issuer_id,
        "row_id": row["row_id"],
        "primary_table_scans": scans,
        "no_unmapped_primary_table_value": all(
            scan["no_unmapped_primary_table_value"] for scan in scans
        ),
    }


def missing_state(evidence: dict[str, object]) -> str:
    return (
        "missing"
        if evidence.get("no_unmapped_primary_table_value", True)
        else "unmapped_source_value"
    )


def find_row_candidates(
    row_id: str,
    periods: list[tuple[str, str]],
    parsed: dict[str, ParsedFiling],
    issuer_id: str,
    cutoff_at: str,
) -> list[Fact]:
    matches = [
        fact
        for fact in row_catalog_for_case(row_id, parsed)
        if fact.entity_identifier == issuer_id
        and not fact.dimensions
        and (not fact.unit_measures or fact.unit_measures == ("iso4217:USD",))
        and any(
            period_of(fact) == ("duration", start, end)
            or period_of(fact) == ("instant", end)
            for start, end in periods
        )
    ]
    cutoff = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
    return [
        fact
        for fact in matches
        if datetime.fromisoformat(fact.accepted_at.replace("Z", "+00:00")) <= cutoff
    ]


def build_quarter_cell(
    row: dict[str, object],
    period: dict[str, object],
    fiscal_start: str,
    previous_end: str | None,
    parsed: dict[str, ParsedFiling],
    case: dict[str, object],
    observations: dict[str, dict[str, object]],
) -> dict[str, object]:
    row_id = str(row["row_id"])
    issuer_id = str(case["issuer_id"])
    cutoff = str(case["cutoff_at"])
    start = str(period["start_date"])
    end = str(period["end_date"])
    accession = str(period["accession_number"])
    operation = str(row["aggregation"])
    cell_id = f"{case['case_id']}/{end}/{row_id}"
    if operation == "period_end_instant":
        selected, decision, raw = make_raw_choice(
            row_id, ("instant", end), parsed, issuer_id, cutoff
        )
        candidate_ids = candidate_json(raw)
        return {
            "cell_id": cell_id,
            "row_id": row_id,
            "statement": row["statement"],
            "frequency": "quarter",
            "start_date": start,
            "end_date": end,
            "inclusive_calendar_days": (
                date.fromisoformat(end) - date.fromisoformat(start)
            ).days
            + 1,
            "availability": "reported" if selected else decision["status"],
            "value": decimal_text(fact_value(selected)) if selected else None,
            "operation": "reported_instant_at_period_end",
            "candidate_observation_ids": candidate_ids,
            "selected_observation_ids": [selected.observation_id] if selected else [],
            "selection": decision,
            "precision_interval": fact_interval_json(selected),
            "unit_measures": list(selected.unit_measures) if selected else [],
            "source_reason": "unsegmented instant at the actual quarter end",
        }
    if operation == "cash_flow_boundary":
        if row_id == "cash_flow_beginning_balance":
            instant = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        else:
            instant = end
        selected, decision, raw = make_raw_choice(
            row_id, ("instant", instant), parsed, issuer_id, cutoff
        )
        cash_basis = (
            basis_evidence(
                [selected], required_scope="selected cash boundary observation"
            )
            if selected
            else {
                "status": "unavailable",
                "same_fact_basis_fingerprint": False,
                "proof_scope": "selected cash boundary observation",
                "facts": [],
            }
        )
        return {
            "cell_id": cell_id,
            "row_id": row_id,
            "statement": row["statement"],
            "frequency": "quarter",
            "start_date": start,
            "end_date": end,
            "boundary_instant": instant,
            "availability": "reported_instant" if selected else decision["status"],
            "value": decimal_text(fact_value(selected)) if selected else None,
            "operation": "select_cash_flow_boundary_instant",
            "candidate_observation_ids": candidate_json(raw),
            "selected_observation_ids": [selected.observation_id] if selected else [],
            "selection": decision,
            "precision_interval": fact_interval_json(selected),
            "unit_measures": list(selected.unit_measures) if selected else [],
            "cash_basis": cash_basis,
            "source_observation_roles": sorted({fact.row_id for fact in raw}),
            "source_reason": "cash balances are instants and are never added",
        }
    if operation not in FLOW_ROWS:
        raise ValueError(f"unknown row aggregation {operation}")

    is_q4 = str(period["fiscal_period_focus"]) == "FY"
    if is_q4:
        direct_period = ("duration", start, end)
        annual_period = ("duration", fiscal_start, end)
        nine_month_period = ("duration", fiscal_start, previous_end or "")
        direct, direct_decision, direct_raw = make_raw_choice(
            row_id, direct_period, parsed, issuer_id, cutoff
        )
        annual, annual_decision, annual_raw = make_raw_choice(
            row_id, annual_period, parsed, issuer_id, cutoff
        )
        nine_months, nine_month_decision, nine_month_raw = make_raw_choice(
            row_id, nine_month_period, parsed, issuer_id, cutoff
        )
        selection_conflicts = [
            name
            for name, decision in (
                ("reported_quarter", direct_decision),
                ("annual", annual_decision),
                ("nine_month_ytd", nine_month_decision),
            )
            if decision.get("status") == "conflict"
        ]
        inputs = [fact for fact in (direct, annual, nine_months) if fact is not None]
        comparison = basis_evidence(
            inputs, required_scope="Q4 filing and nine-month comparability"
        )
        calculated = (
            fact_value(annual) - fact_value(nine_months)
            if annual and nine_months
            else None
        )
        calc_interval = None
        if annual and nine_months:
            annual_interval = interval_for_fact(annual)
            nine_month_interval = interval_for_fact(nine_months)
            if annual_interval and nine_month_interval:
                calc_interval = subtract_intervals(annual_interval, nine_month_interval)
        calc_value = (
            decimal_text(cast(Decimal, calculated)) if calculated is not None else None
        )
        direct_interval = interval_for_fact(direct) if direct else None
        crosscheck = "not_available"
        if direct and calc_interval and direct_interval:
            crosscheck = (
                "intervals_overlap"
                if intervals_overlap(direct_interval, calc_interval)
                else "conflict"
            )
        selected = (
            direct
            if direct and (calculated is None or crosscheck == "intervals_overlap")
            else None
        )
        if (
            selection_conflicts
            or crosscheck == "conflict"
            or comparison["basis_conflict"]
        ):
            selected_value = None
            selected_interval = None
            availability = "conflict"
            selected = None
        elif selected is None and not direct and calculated is not None:
            selected_value = calculated
            selected_interval = calc_interval
            availability = "derived"
        elif selected:
            selected_value = fact_value(selected)
            selected_interval = direct_interval
            availability = (
                "reported" if calculated is None else "reported_with_derived_crosscheck"
            )
        elif direct and calculated is not None:
            selected_value = None
            selected_interval = None
            availability = "conflict"
        elif direct and calculated is None:
            selected_value = fact_value(direct)
            selected_interval = direct_interval
            availability = "reported"
        else:
            selected_value = None
            selected_interval = None
            availability = unavailable_or_missing(
                [direct_decision, annual_decision, nine_month_decision],
                direct_raw + annual_raw + nine_month_raw,
            )
        ids = candidate_json(direct_raw + annual_raw + nine_month_raw)
        selected_ids = (
            [selected.observation_id]
            if selected
            else (
                [annual.observation_id, nine_months.observation_id]
                if availability == "derived" and annual and nine_months
                else []
            )
        )
        missing_evidence = None
        if availability == "missing":
            input_accessions = [
                key
                for key, filing in parsed.items()
                if filing.metadata.get("reported_period_end") in (end, previous_end)
            ]
            missing_evidence = build_missing_evidence(
                row, issuer_id, input_accessions, parsed
            )
            availability = missing_state(missing_evidence)
            missing_evidence["derived_status"] = "input_not_reported"
        return {
            "cell_id": cell_id,
            "row_id": row_id,
            "statement": row["statement"],
            "frequency": "quarter",
            "start_date": start,
            "end_date": end,
            "inclusive_calendar_days": (
                date.fromisoformat(end) - date.fromisoformat(start)
            ).days
            + 1,
            "availability": availability,
            "value": decimal_text(selected_value)
            if selected_value is not None
            else None,
            "operation": "fiscal_year_minus_same_year_nine_month_ytd",
            "candidate_observation_ids": ids,
            "selected_observation_ids": selected_ids,
            "reported_quarter": {
                "observation_id": direct.observation_id,
                "value": decimal_text(fact_value(direct)),
                "precision_interval": direct_interval.json()
                if direct_interval
                else None,
            }
            if direct
            else None,
            "annual_input": {
                "observation_id": annual.observation_id,
                "value": decimal_text(fact_value(annual)),
                "precision_interval": fact_interval_json(annual),
            }
            if annual
            else None,
            "nine_month_ytd_input": {
                "observation_id": nine_months.observation_id,
                "value": decimal_text(fact_value(nine_months)),
                "precision_interval": fact_interval_json(nine_months),
            }
            if nine_months
            else None,
            "derived_value": calc_value,
            "derived_precision_interval": calc_interval.json()
            if calc_interval
            else None,
            "direct_derived_crosscheck": crosscheck,
            "source_selection_conflicts": selection_conflicts,
            "basis_evidence": comparison,
            "missing_evidence": missing_evidence,
            "outcome_code": (
                "source_candidate_conflict"
                if selection_conflicts
                else comparison["basis_conflict"]
                or (
                    "direct_derived_conflict"
                    if availability == "conflict"
                    else "input_not_reported"
                    if selected_value is None
                    else "selected"
                )
            ),
            "selection_decision": {
                "direct": direct_decision,
                "annual": annual_decision,
                "nine_month_ytd": nine_month_decision,
                "selected_rule": "select direct only when its quantization interval overlaps the independently derived FY-minus-nine-month interval",
            },
            "unit_measures": list(selected.unit_measures)
            if selected
            else (list(annual.unit_measures) if annual else []),
        }

    target_period = ("duration", start, end)
    direct, direct_decision, direct_raw = make_raw_choice(
        row_id, target_period, parsed, issuer_id, cutoff
    )
    if str(period["fiscal_period_focus"]) == "Q1":
        same_span_ytd, ytd_decision, ytd_raw = make_raw_choice(
            row_id, target_period, parsed, issuer_id, cutoff
        )
        if direct_decision.get("status") == "conflict":
            return {
                "cell_id": cell_id,
                "row_id": row_id,
                "statement": row["statement"],
                "frequency": "quarter",
                "start_date": start,
                "end_date": end,
                "availability": "conflict",
                "value": None,
                "operation": "reported_q1_same_span_ytd",
                "candidate_observation_ids": candidate_json(direct_raw + ytd_raw),
                "selected_observation_ids": [],
                "selection_decision": {
                    "direct": direct_decision,
                    "same_span_ytd": ytd_decision,
                    "duplicate_fact_created": False,
                },
            }
        if (
            direct
            and same_span_ytd
            and direct.observation_id == same_span_ytd.observation_id
        ):
            return {
                "cell_id": cell_id,
                "row_id": row_id,
                "statement": row["statement"],
                "frequency": "quarter",
                "start_date": start,
                "end_date": end,
                "inclusive_calendar_days": (
                    date.fromisoformat(end) - date.fromisoformat(start)
                ).days
                + 1,
                "availability": "reported",
                "value": decimal_text(fact_value(direct)),
                "operation": "same_q1_observation_is_quarter_and_ytd",
                "candidate_observation_ids": candidate_json(direct_raw + ytd_raw),
                "selected_observation_ids": [direct.observation_id],
                "observation_roles": ["reported_quarter", "same_span_ytd"],
                "selection_decision": {
                    "direct": direct_decision,
                    "same_span_ytd": ytd_decision,
                    "duplicate_fact_created": False,
                },
                "precision_interval": fact_interval_json(direct),
                "unit_measures": list(direct.unit_measures),
            }
        if direct:
            return {
                "cell_id": cell_id,
                "row_id": row_id,
                "statement": row["statement"],
                "frequency": "quarter",
                "start_date": start,
                "end_date": end,
                "inclusive_calendar_days": (
                    date.fromisoformat(end) - date.fromisoformat(start)
                ).days
                + 1,
                "availability": "reported",
                "value": decimal_text(fact_value(direct)),
                "operation": "reported_q1_same_span_ytd",
                "candidate_observation_ids": candidate_json(direct_raw + ytd_raw),
                "selected_observation_ids": [direct.observation_id],
                "observation_roles": ["reported_quarter", "same_span_ytd"],
                "selection_decision": {
                    "direct": direct_decision,
                    "same_span_ytd": ytd_decision,
                    "duplicate_fact_created": False,
                },
                "precision_interval": fact_interval_json(direct),
                "unit_measures": list(direct.unit_measures),
            }
        missing_evidence = (
            build_missing_evidence(row, issuer_id, [accession], parsed)
            if not direct_raw
            else None
        )
        availability = unavailable_or_missing(
            [direct_decision, ytd_decision], direct_raw + ytd_raw
        )
        if missing_evidence:
            availability = missing_state(missing_evidence)
        return {
            "cell_id": cell_id,
            "row_id": row_id,
            "statement": row["statement"],
            "frequency": "quarter",
            "start_date": start,
            "end_date": end,
            "inclusive_calendar_days": (
                date.fromisoformat(end) - date.fromisoformat(start)
            ).days
            + 1,
            "availability": availability,
            "value": None,
            "operation": "reported_q1_same_span_ytd",
            "candidate_observation_ids": candidate_json(direct_raw + ytd_raw),
            "selected_observation_ids": [],
            "selection_decision": {
                "direct": direct_decision,
                "same_span_ytd": ytd_decision,
                "duplicate_fact_created": False,
            },
            "missing_evidence": missing_evidence,
            "unit_measures": [],
        }

    fiscal_ytd = ("duration", fiscal_start, end)
    prior_ytd = ("duration", fiscal_start, previous_end or "")
    current, current_decision, current_raw = make_raw_choice(
        row_id, fiscal_ytd, parsed, issuer_id, cutoff
    )
    prior, prior_decision, prior_raw = make_raw_choice(
        row_id, prior_ytd, parsed, issuer_id, cutoff
    )
    selection_conflicts = [
        name
        for name, decision in (
            ("reported_quarter", direct_decision),
            ("current_ytd", current_decision),
            ("prior_ytd", prior_decision),
        )
        if decision.get("status") == "conflict"
    ]
    inputs = [fact for fact in (direct, current, prior) if fact is not None]
    comparison = basis_evidence(
        inputs, required_scope="direct quarter and same-fiscal-year YTD inputs"
    )
    derived_value = (
        fact_value(current) - fact_value(prior) if current and prior else None
    )
    derived_interval = None
    if current and prior:
        current_interval = interval_for_fact(current)
        prior_interval = interval_for_fact(prior)
        if current_interval and prior_interval:
            derived_interval = subtract_intervals(current_interval, prior_interval)
    direct_interval = interval_for_fact(direct) if direct else None
    crosscheck = "not_available"
    if direct and derived_interval and direct_interval:
        crosscheck = (
            "intervals_overlap"
            if intervals_overlap(direct_interval, derived_interval)
            else "conflict"
        )
    selected = direct if direct and crosscheck == "intervals_overlap" else None
    if selection_conflicts or crosscheck == "conflict" or comparison["basis_conflict"]:
        value = None
        availability = "conflict"
        selected_ids = []
        selected_interval = None
    elif selected:
        value = fact_value(selected)
        availability = "reported_with_derived_crosscheck"
        selected_ids = [selected.observation_id]
        selected_interval = direct_interval
    elif direct and derived_value is not None:
        value = None
        availability = "conflict"
        selected_ids = []
        selected_interval = None
    elif derived_value is not None:
        value = derived_value
        availability = "derived"
        selected_ids = [
            cast(Fact, current).observation_id,
            cast(Fact, prior).observation_id,
        ]
        selected_interval = derived_interval
    elif direct:
        value = fact_value(direct)
        availability = "reported"
        selected_ids = [direct.observation_id]
        selected_interval = direct_interval
    else:
        value = None
        availability = "unavailable" if current or prior or direct_raw else "missing"
        selected_ids = []
        selected_interval = None
    all_raw = direct_raw + current_raw + prior_raw
    missing_evidence = (
        build_missing_evidence(row, issuer_id, [accession], parsed)
        if value is None and availability == "missing"
        else None
    )
    if missing_evidence:
        availability = missing_state(missing_evidence)
    return {
        "cell_id": cell_id,
        "row_id": row_id,
        "statement": row["statement"],
        "frequency": "quarter",
        "start_date": start,
        "end_date": end,
        "inclusive_calendar_days": (
            date.fromisoformat(end) - date.fromisoformat(start)
        ).days
        + 1,
        "availability": availability,
        "value": decimal_text(value) if value is not None else None,
        "operation": "same_fiscal_year_ytd_difference_with_direct_crosscheck",
        "candidate_observation_ids": candidate_json(all_raw),
        "selected_observation_ids": selected_ids,
        "reported_quarter": {
            "observation_id": direct.observation_id,
            "value": decimal_text(fact_value(direct)),
            "precision_interval": direct_interval.json() if direct_interval else None,
        }
        if direct
        else None,
        "current_ytd_input": {
            "observation_id": current.observation_id,
            "value": decimal_text(fact_value(current)),
            "precision_interval": fact_interval_json(current),
        }
        if current
        else None,
        "prior_ytd_input": {
            "observation_id": prior.observation_id,
            "value": decimal_text(fact_value(prior)),
            "precision_interval": fact_interval_json(prior),
        }
        if prior
        else None,
        "derived_value": decimal_text(cast(Decimal, derived_value))
        if derived_value is not None
        else None,
        "derived_precision_interval": derived_interval.json()
        if derived_interval
        else None,
        "direct_derived_crosscheck": crosscheck,
        "source_selection_conflicts": selection_conflicts,
        "basis_evidence": comparison,
        "outcome_code": (
            "source_candidate_conflict"
            if selection_conflicts
            else comparison["basis_conflict"]
            or (
                "direct_derived_conflict"
                if availability == "conflict"
                else "prior_ytd_unavailable"
                if current and not prior and value is None
                else "current_ytd_unavailable"
                if prior and not current and value is None
                else "input_not_reported"
                if value is None
                else "selected"
            )
        ),
        "selection_decision": {
            "direct": direct_decision,
            "current_ytd": current_decision,
            "prior_ytd": prior_decision,
            "selected_rule": "select direct only when its precision interval overlaps the independently derived YTD-difference interval",
        },
        "unit_measures": list(direct.unit_measures)
        if direct
        else (list(current.unit_measures) if current else []),
        "missing_evidence": missing_evidence,
        "selected_precision_interval": selected_interval.json()
        if selected_interval
        else None,
    }


def build_source_registry(
    parsed_by_accession: dict[str, ParsedFiling],
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    sources: dict[str, object] = {}
    observations: dict[str, dict[str, object]] = {}
    for accession, filing in sorted(parsed_by_accession.items()):
        metadata = filing.metadata
        all_receipts = cast(list[dict[str, object]], metadata["source_responses"])
        sources[accession] = {
            "issuer_id": metadata["issuer_id"],
            "accession_number": accession,
            "form": metadata["form"],
            "filing_date": metadata["filing_date"],
            "accepted_at": metadata["accepted_at"],
            "reported_period_end": metadata["reported_period_end"],
            "primary_document": metadata["primary_document"],
            "primary_html_sha256": metadata["primary_html_sha256"],
            "namespace_uris": filing.namespace_uris,
            "response_receipts": [
                {
                    "uri": item["uri"],
                    "content_hash": item["content_hash"],
                    "http_status": item["http_status"],
                    "media_type": item["media_type"],
                    "captured_at": item["captured_at"],
                    "declared_size": item["declared_size"],
                    "received_size": item["received_size"],
                    "scope": item["scope"],
                    "response_role": (
                        "index"
                        if str(item["uri"]).endswith("/index.json")
                        else "xbrl_archive"
                        if str(item["uri"]).endswith("-xbrl.zip")
                        else "submission"
                        if str(item["uri"]).endswith(".txt")
                        else "primary_document"
                        if str(item["uri"]).endswith(
                            "/" + str(metadata["primary_document"])
                        )
                        else "other",
                    ),
                }
                for item in all_receipts
            ],
            "primary_statement_tables": filing.tables,
        }
        for row_id, facts in filing.row_facts.items():
            for fact in facts:
                observations[fact.observation_id] = serialize_fact(fact)
    return sources, observations


def build_quarter_periods(
    case: dict[str, object], parsed: dict[str, ParsedFiling], revenue_row: str
) -> list[dict[str, object]]:
    periods = cast(list[dict[str, object]], case["quarter_periods"])
    output = []
    for index, period in enumerate(periods):
        end = str(period["end_date"])
        accession = str(period["accession_number"])
        parsed_filing = parsed[accession]
        fiscal_start = fiscal_start_for_target(revenue_row, period, parsed, case)
        if str(period["fiscal_period_focus"]) == "FY":
            if index == 0:
                raise ValueError(
                    f"{case['case_id']} Q4 target lacks the preceding quarter"
                )
            previous_end = str(periods[index - 1]["end_date"])
            expected_start = (
                date.fromisoformat(previous_end) + timedelta(days=1)
            ).isoformat()
            if str(period["start_date"]) != expected_start:
                raise ValueError(
                    f"{case['case_id']} Q4 period boundary is discontinuous"
                )
            revenue_periods = [
                fact
                for fact in parsed_filing.row_facts[revenue_row]
                if fact.period.get("period_type") == "duration"
                and fact.period.get("end_date") == end
                and fact.period.get("start_date") == fiscal_start
                and not fact.dimensions
            ]
            if not revenue_periods:
                raise ValueError(f"{accession} lacks the fiscal-year revenue context")
        else:
            prior_target_end = str(periods[index - 1]["end_date"]) if index else None
            if (
                period["start_date"] != fiscal_start
                and str(period["fiscal_period_focus"]) == "Q1"
            ):
                raise ValueError(
                    f"{accession} Q1 period start differs from its revenue context"
                )
            if period["start_date"] != fiscal_start and prior_target_end:
                expected_start = (
                    date.fromisoformat(prior_target_end) + timedelta(days=1)
                ).isoformat()
                if str(period["start_date"]) != expected_start:
                    raise ValueError(
                        f"{case['case_id']} has a quarter gap or overlap at {end}"
                    )
        output.append(
            {
                "quarter_id": period["quarter_id"],
                "accession_number": accession,
                "fiscal_year_focus": period["fiscal_year_focus"],
                "fiscal_period_focus": period["fiscal_period_focus"],
                "fiscal_year_start": fiscal_start,
                "start_date": period["start_date"],
                "end_date": end,
                "prior_quarter_end": (
                    str(case["prior_ytd_quarter_end"])
                    if index == 0
                    and str(period["fiscal_period_focus"]) == "Q2"
                    and case.get("prior_ytd_quarter_end")
                    else str(periods[index - 1]["end_date"])
                    if index
                    else None
                ),
                "inclusive_calendar_days": (
                    date.fromisoformat(end)
                    - date.fromisoformat(str(period["start_date"]))
                ).days
                + 1,
                "period_source": period["period_source"],
                "dei_observations": period["dei_observations"],
            }
        )
    return output


def quarter_source_observation_ids(cell: dict[str, object]) -> list[str]:
    ids = strings(cell.get("selected_observation_ids", []))
    if cell["availability"] == "reported_with_derived_crosscheck":
        ids.extend(difference_observation_ids(cell))
    return ids


def build_case_golden(
    case: dict[str, object],
    quarter_periods: list[dict[str, object]],
    parsed: dict[str, ParsedFiling],
    rows: list[dict[str, object]],
    observations: dict[str, dict[str, object]],
) -> dict[str, object]:
    quarter_cells = []
    for period in quarter_periods:
        for row in rows:
            previous_end = cast(str | None, period.get("prior_quarter_end"))
            cell = build_quarter_cell(
                row,
                period,
                str(period["fiscal_year_start"]),
                previous_end,
                parsed,
                case,
                observations,
            )
            selected_ids = strings(cell.get("selected_observation_ids", []))
            cell["source_available_at"] = max(
                (
                    string(observations[observation_id]["accepted_at"])
                    for observation_id in quarter_source_observation_ids(cell)
                ),
                key=datetime.fromisoformat,
                default=None,
            )
            if cell["availability"] == "derived":
                cell["derivation"] = {
                    "policy": "issue495-independent-decimal-golden-v1",
                    "formula": cell["operation"],
                    "inputs": [
                        {"observation_id": observation_id, "coefficient": coefficient}
                        for observation_id, coefficient in zip(
                            selected_ids, (1, -1), strict=True
                        )
                    ],
                }
            quarter_cells.append(cell)
    if len(quarter_cells) != 8 * 25:
        raise ValueError(f"{case['case_id']} did not produce 200 quarterly cells")
    return {
        "protocol": "issue495-quarterly-independent-decimal-golden-v1",
        "case_id": case["case_id"],
        "issuer_id": case["issuer_id"],
        "cutoff_at": case["cutoff_at"],
        "quarter_periods": quarter_periods,
        "cells": quarter_cells,
        "coverage": {
            "quarter_cells": len(quarter_cells),
            "reported": sum(
                cell["availability"]
                in {"reported", "reported_with_derived_crosscheck", "reported_instant"}
                for cell in quarter_cells
            ),
            "derived": sum(cell["availability"] == "derived" for cell in quarter_cells),
            "missing": sum(cell["availability"] == "missing" for cell in quarter_cells),
            "conflict": sum(
                cell["availability"] == "conflict" for cell in quarter_cells
            ),
        },
        "accounting_rules": {
            "decimal_arithmetic": "Python Decimal with no intermediate rounding",
            "q1": "one same-span source fact has both reported-quarter and same-span-YTD roles",
            "q2_q3": "same-fiscal-year current-YTD minus prior-YTD, cross-checked against a reported quarter when present",
            "q4": "reported fiscal-year value minus the same-fiscal-year nine-month value",
            "ttm": "four consecutive quarter cells are summed in the separate TTM golden",
            "cash": "opening and closing values are instant facts at start-minus-one-day and period end",
            "point_in_time": "select the latest eligible fact accepted on or before the cohort cutoff; retain rejected and superseded candidate IDs in cell decisions",
            "revision_scope": "the retained cohort originals contain the required quarter/year filings only; this independent reference does not claim complete amendment-lineage discovery",
        },
    }


def cell_precision_interval(cell: dict[str, object]) -> Interval | None:
    interval_json = cell.get(
        "selected_precision_interval", cell.get("precision_interval")
    )
    if not interval_json:
        return None
    interval = cast(dict[str, object], interval_json)
    return Interval(
        Decimal(str(interval["lower"])),
        Decimal(str(interval["upper"])),
        bool(interval["lower_inclusive"]),
        bool(interval["upper_inclusive"]),
    )


def ttm_period_bounds(quarters: list[dict[str, object]]) -> tuple[str, str]:
    if len(quarters) != 4:
        raise ValueError("missing_quarter")
    identities = [quarter["quarter_id"] for quarter in quarters]
    if len(set(identities)) != 4:
        raise ValueError("duplicate_quarter")
    starts = [date.fromisoformat(string(quarter["start_date"])) for quarter in quarters]
    ends = [date.fromisoformat(string(quarter["end_date"])) for quarter in quarters]
    if any(start > end for start, end in zip(starts, ends, strict=True)):
        raise ValueError("invalid_quarter_duration")
    if starts != sorted(starts):
        raise ValueError("out_of_order_quarters")
    for left_end, right_start in zip(ends, starts[1:]):
        if right_start <= left_end:
            raise ValueError("overlapping_quarters")
        if right_start != left_end + timedelta(days=1):
            raise ValueError("quarter_gap")
    return starts[0].isoformat(), ends[-1].isoformat()


def build_ttm_golden(
    case_goldens: list[dict[str, object]],
    rows: list[dict[str, object]],
    observations_by_case: dict[str, dict[str, dict[str, object]]],
) -> dict[str, object]:
    windows = []
    for case_golden in case_goldens:
        periods = cast(list[dict[str, object]], case_golden["quarter_periods"])
        cells = cast(list[dict[str, object]], case_golden["cells"])
        by_key = {(str(cell["end_date"]), str(cell["row_id"])): cell for cell in cells}
        if len(periods) < 4:
            raise ValueError("missing_quarter")
        for window_index in range(len(periods) - 3):
            quarters = periods[window_index : window_index + 4]
            start, end = ttm_period_bounds(quarters)
            window_id = f"{case_golden['case_id']}/ttm/{quarters[0]['end_date']}-{end}"
            cells_out: list[dict[str, object]] = []
            for row in rows:
                row_id = str(row["row_id"])
                aggregation = str(row["aggregation"])
                if aggregation not in {
                    "additive_flow",
                    "period_end_instant",
                    "cash_flow_boundary",
                }:
                    cells_out.append(
                        {
                            "cell_id": f"{window_id}/{row_id}",
                            "row_id": row_id,
                            "availability": "unsupported",
                            "value": None,
                            "outcome_code": "non_additive_" + aggregation,
                        }
                    )
                    continue
                inputs = [
                    by_key.get(
                        (str(period["end_date"]), row_id),
                        {
                            "cell_id": f"{case_golden['case_id']}/{period['end_date']}/{row_id}",
                            "availability": "missing",
                        },
                    )
                    for period in quarters
                ]
                if aggregation == "additive_flow":
                    required_inputs = inputs
                elif aggregation == "period_end_instant":
                    required_inputs = [inputs[-1]]
                elif row_id == "cash_flow_beginning_balance":
                    required_inputs = [inputs[0]]
                else:
                    required_inputs = [inputs[-1]]

                source_statuses = [
                    str(cell["availability"]) for cell in required_inputs
                ]
                source_values = [
                    cell for cell in required_inputs if cell.get("value") is not None
                ]
                input_failure = (
                    "conflict"
                    if "conflict" in source_statuses
                    else "unavailable"
                    if "unavailable" in source_statuses
                    else "missing"
                )
                selected: list[dict[str, object]] = []
                value: str | None = None
                total_interval: Interval | None = None
                selected_ids: list[str] = []
                if (
                    aggregation == "additive_flow"
                    and len(source_values) == 4
                    and all(
                        status
                        in {"reported", "reported_with_derived_crosscheck", "derived"}
                        for status in source_statuses
                    )
                ):
                    selected = source_values
                    value = decimal_text(
                        sum(
                            (Decimal(str(cell["value"])) for cell in selected),
                            Decimal(0),
                        )
                    )
                    intervals = [cell_precision_interval(cell) for cell in selected]
                    if all(intervals):
                        total_interval = intervals[0]
                        for interval in intervals[1:]:
                            total_interval = add_intervals(
                                cast(Interval, total_interval), cast(Interval, interval)
                            )
                    selected_ids = [str(cell["cell_id"]) for cell in selected]
                    availability = "derived"
                    operation = "sum_four_consecutive_quarter_flows"
                elif (
                    aggregation == "period_end_instant"
                    and len(source_values) == 1
                    and source_statuses[0] in {"reported", "reported_instant"}
                ):
                    selected = source_values
                    last = source_values[0]
                    value = str(last["value"])
                    total_interval = cell_precision_interval(last)
                    selected_ids = [str(last["cell_id"])]
                    availability = "reported_instant"
                    operation = "period_end_instant_as_ttm_as_of"
                elif (
                    aggregation == "cash_flow_boundary"
                    and len(source_values) == 1
                    and source_statuses[0] == "reported_instant"
                ):
                    selected = source_values
                    boundary = source_values[0]
                    value = str(boundary["value"])
                    total_interval = cell_precision_interval(boundary)
                    selected_ids = [str(boundary["cell_id"])]
                    availability = "reported_instant"
                    operation = "select_window_opening_or_closing_cash_instant"
                else:
                    availability = input_failure
                    operation = "missing_or_incomplete_required_quarter_inputs"

                selected_observation_ids = sorted(
                    {
                        observation_id
                        for cell in selected
                        for observation_id in cast(
                            list[str], cell.get("selected_observation_ids", [])
                        )
                    }
                )
                observations = observations_by_case[str(case_golden["case_id"])]
                source_observations = [
                    observations[item] for item in selected_observation_ids
                ]
                basis_issue = basis_conflict(source_observations)
                if availability == "derived" and basis_issue:
                    availability = "conflict"
                    value = None
                    total_interval = None
                    selected_ids = []
                    operation = "incomparable_quarter_inputs"
                basis_fields = (
                    "issuer_id",
                    "entity_identifier",
                    "entity_scheme",
                    "namespace_uri",
                    "qname",
                    "unit_measures",
                    "dimensions",
                )
                fact_fingerprints = {
                    tuple(
                        json.dumps(observation.get(field), sort_keys=True)
                        for field in basis_fields
                    )
                    for observation in source_observations
                }
                selected_units = {
                    json.dumps(observation.get("unit_measures", []), sort_keys=True)
                    for observation in source_observations
                }
                cells_out.append(
                    {
                        "cell_id": f"{window_id}/{row_id}",
                        "row_id": row_id,
                        "statement": row["statement"],
                        "frequency": "ttm",
                        "start_date": start,
                        "end_date": end,
                        "inclusive_calendar_days": (
                            date.fromisoformat(end) - date.fromisoformat(start)
                        ).days
                        + 1,
                        "as_of_date": end,
                        "availability": availability,
                        "value": value,
                        "operation": operation,
                        "source_available_at": max(
                            (
                                string(observations[observation_id]["accepted_at"])
                                for component in selected
                                for observation_id in quarter_source_observation_ids(
                                    component
                                )
                            ),
                            key=datetime.fromisoformat,
                            default=None,
                        )
                        if value is not None
                        else None,
                        "derivation": {
                            "policy": "issue495-independent-decimal-golden-v1",
                            "formula": operation,
                            "inputs": [
                                {"cell_id": item, "coefficient": 1}
                                for item in selected_ids
                            ],
                        }
                        if availability == "derived"
                        else None,
                        "outcome_code": basis_issue
                        or (
                            "required_quarter_unavailable"
                            if value is None
                            else "selected"
                        ),
                        "quarter_input_cell_ids": [
                            str(cell["cell_id"]) for cell in inputs
                        ],
                        "required_input_cell_ids": [
                            str(cell["cell_id"]) for cell in required_inputs
                        ],
                        "selected_input_cell_ids": selected_ids,
                        "precision_interval": total_interval.json()
                        if total_interval
                        else None,
                        "unit_measures": next(
                            (
                                cell.get("unit_measures", [])
                                for cell in reversed(required_inputs)
                                if cell.get("unit_measures")
                            ),
                            [],
                        ),
                        "continuity_check": "passed",
                        "basis_check": {
                            "issuer_id": case_golden["issuer_id"],
                            "unit_consistent": len(selected_units) <= 1,
                            "exact_fact_basis_fingerprint_consistent": len(
                                fact_fingerprints
                            )
                            <= 1
                            and bool(fact_fingerprints),
                            "comparability_status": "not_established_by_independent_reference_fixture",
                            "comparison_fields": list(basis_fields),
                            "selected_observation_ids": selected_observation_ids,
                            "revision_scope": "fact-level cutoff candidates are retained; complete amendment lineage is not claimed",
                        },
                    }
                )

            by_row = {str(cell["row_id"]): cell for cell in cells_out}
            opening = by_row["cash_flow_beginning_balance"]
            closing = by_row["cash_flow_ending_balance"]
            opening_ids = cast(
                list[str],
                cast(dict[str, object], opening["basis_check"])[
                    "selected_observation_ids"
                ],
            )
            closing_ids = cast(
                list[str],
                cast(dict[str, object], closing["basis_check"])[
                    "selected_observation_ids"
                ],
            )
            observations = observations_by_case[str(case_golden["case_id"])]
            opening_facts = [
                observations[item] for item in opening_ids if item in observations
            ]
            closing_facts = [
                observations[item] for item in closing_ids if item in observations
            ]
            cash_basis_fields = (
                "issuer_id",
                "entity_identifier",
                "entity_scheme",
                "qname",
                "unit_measures",
                "dimensions",
                "cash_basis",
                "revision_basis_id",
            )
            opening_fingerprints = {
                tuple(
                    json.dumps(fact.get(field), sort_keys=True)
                    for field in cash_basis_fields
                )
                for fact in opening_facts
            }
            closing_fingerprints = {
                tuple(
                    json.dumps(fact.get(field), sort_keys=True)
                    for field in cash_basis_fields
                )
                for fact in closing_facts
            }
            same_cash_basis = bool(
                opening_fingerprints
                and closing_fingerprints
                and opening_fingerprints == closing_fingerprints
            )
            net_change = by_row["net_change_in_cash"]
            cash_rollforward_status = "unavailable"
            cash_rollforward_difference: str | None = None
            if (
                opening.get("value") is not None
                and closing.get("value") is not None
                and net_change.get("value") is not None
            ):
                expected_closing = Decimal(str(opening["value"])) + Decimal(
                    str(net_change["value"])
                )
                cash_rollforward_difference = decimal_text(
                    Decimal(str(closing["value"])) - expected_closing
                )
                opening_interval = cell_precision_interval(opening)
                closing_interval = cell_precision_interval(closing)
                net_change_interval = cell_precision_interval(net_change)
                if not same_cash_basis:
                    cash_rollforward_status = "basis_fingerprint_differs_or_unavailable"
                elif opening_interval and closing_interval and net_change_interval:
                    expected_interval = add_intervals(
                        opening_interval, net_change_interval
                    )
                    cash_rollforward_status = (
                        "intervals_overlap"
                        if intervals_overlap(closing_interval, expected_interval)
                        else "conflict"
                    )
                else:
                    cash_rollforward_status = "precision_unavailable"
            else:
                required_cash_inputs = (opening, net_change, closing)
                if any(
                    cell["availability"] == "conflict" for cell in required_cash_inputs
                ):
                    cash_rollforward_status = "conflict"
                elif any(
                    cell["availability"] == "missing" for cell in required_cash_inputs
                ):
                    cash_rollforward_status = "missing_required_cash_rollforward_input"

            for cash_cell in (opening, closing):
                if opening_facts and closing_facts and not same_cash_basis:
                    cash_cell["availability"] = "conflict"
                    cash_cell["outcome_code"] = "cash_boundary_basis_mismatch"
                    cash_cell["value"] = None
                    cash_cell["source_available_at"] = None
                    cash_cell["precision_interval"] = None
                    cash_cell["selected_input_cell_ids"] = []
                cash_cell["cash_basis_comparison"] = {
                    "status": "same_observed_fact_basis_fingerprint"
                    if same_cash_basis
                    else "observed_fact_basis_differs_or_unavailable",
                    "same_fact_basis_fingerprint": same_cash_basis,
                    "comparison_fields": list(cash_basis_fields),
                    "opening_observation_ids": opening_ids,
                    "closing_observation_ids": closing_ids,
                    "accounting_policy_comparability": "not_claimed_by_independent_reference_fixture",
                }
                cash_cell["cash_rollforward_reconciliation"] = {
                    "status": cash_rollforward_status,
                    "formula": "opening_cash + TTM_net_change_in_cash = closing_cash",
                    "opening_value": opening.get("value"),
                    "net_change_value": net_change.get("value"),
                    "reported_closing_value": closing.get("value"),
                    "difference": cash_rollforward_difference,
                    "input_cell_ids": [
                        str(cell["cell_id"]) for cell in (opening, net_change, closing)
                    ],
                }
            windows.append(
                {
                    "window_id": window_id,
                    "case_id": case_golden["case_id"],
                    "issuer_id": case_golden["issuer_id"],
                    "start_date": start,
                    "end_date": end,
                    "inclusive_calendar_days": (
                        date.fromisoformat(end) - date.fromisoformat(start)
                    ).days
                    + 1,
                    "quarter_ids": [period["quarter_id"] for period in quarters],
                    "quarter_periods": quarters,
                    "cells": cells_out,
                }
            )
    result = {
        "protocol": "issue495-ttm-independent-decimal-golden-v1",
        "rolling_windows_per_case": 5,
        "window_count": len(windows),
        "cell_count": sum(
            len(cast(list[dict[str, object]], window["cells"])) for window in windows
        ),
        "windows": windows,
    }
    return result


def build_annual_regression(
    annual: dict[str, object], fixture_path: Path, cohort: dict[str, object]
) -> dict[str, object]:
    annual_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    annual_filings = cast(list[dict[str, object]], annual["filings"])
    by_year_issuer = {
        (str(item["issuer_id"]), integer(item["primary_fiscal_year"])): item
        for item in annual_filings
    }
    cases = []
    total = 0
    for case in cast(list[dict[str, object]], cohort["cases"]):
        current_year = int(str(case["cutoff_at"])[:4])
        years = list(range(current_year - 4, current_year + 1))
        if current_year == 2024:
            years = [2020, 2021, 2022, 2023, 2024]
        elif current_year == 2026:
            years = [2022, 2023, 2024, 2025, 2026]
        cells = []
        for year in years:
            filing = by_year_issuer.get((str(case["issuer_id"]), year))
            if filing is None:
                raise ValueError(
                    f"annual regression lacks {case['issuer_id']} FY{year}"
                )
            for statement in cast(list[dict[str, object]], filing["statements"]):
                for row in cast(list[dict[str, object]], statement["rows"]):
                    values = cast(list[dict[str, object]], row.get("values", []))
                    fiscal_period = cast(dict[str, object], filing["fiscal_period"])
                    if row["row_id"] == "cash_flow_beginning_balance":
                        target_instant = (
                            date.fromisoformat(str(fiscal_period["start_date"]))
                            - timedelta(days=1)
                        ).isoformat()
                    else:
                        target_instant = str(fiscal_period["end_date"])
                    matched = []
                    for source_value in values:
                        source_period = record(source_value["source_period"])
                        period_end = str(
                            source_period.get(
                                "end_date", source_period.get("instant", "")
                            )
                        )
                        if period_end == target_instant:
                            matched.append(source_value)
                    if row["status"] == "missing":
                        if matched:
                            raise ValueError(
                                "annual missing row unexpectedly contains a matching fact"
                            )
                        value = None
                    elif len(matched) != 1:
                        raise ValueError(
                            f"annual row {row['row_id']} has {len(matched)} facts for FY{year}"
                        )
                    else:
                        value = str(matched[0]["value"])
                    cells.append(
                        {
                            "cell_id": f"{case['case_id']}/annual/FY{year}/{row['row_id']}",
                            "case_id": case["case_id"],
                            "issuer_id": case["issuer_id"],
                            "fiscal_year": year,
                            "period": filing["fiscal_period"],
                            "row_id": row["row_id"],
                            "statement": statement["statement"],
                            "availability": "missing"
                            if row["status"] == "missing"
                            else "reported",
                            "value": value,
                            "annual_accession": filing["accession_number"],
                            "source_sha256": filing["source_sha256"],
                            "fixture_sha256": annual_hash,
                            "selected_source_values": matched,
                            "missing_reason": row.get("reason")
                            if row["status"] == "missing"
                            else None,
                        }
                    )
        total += len(cells)
        cases.append(
            {
                "case_id": case["case_id"],
                "issuer_id": case["issuer_id"],
                "fiscal_years": years,
                "cells": cells,
            }
        )
    if total != 500:
        raise ValueError(f"expected 500 annual regression cells, got {total}")
    return {
        "protocol": "issue495-annual-regression-golden-v1",
        "source_fixture": "../annual-statements/issue494-golden.json",
        "source_fixture_sha256": annual_hash,
        "cell_count": total,
        "cases": cases,
        "method": "Select the primary annual row value whose context ends on the filing's actual fiscal-year end. Preserve the existing annual source hash and missing outcomes.",
    }


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        + "\n"
    ).encode()


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("expected JSON object with string keys")
    return dict(value)


def integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"expected integer, got {value!r}")
    return value


def records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("expected JSON array of objects")
    return [record(item) for item in value]


def strings(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("expected JSON array of strings")
    return [string(item) for item in value]


def string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected JSON string")
    return value


def load_object(path: Path) -> dict[str, object]:
    return record(json.loads(path.read_bytes()))


def load_cohort(fixture_root: Path) -> dict[str, object]:
    cohort = load_object(fixture_root / "issue495-cohort.json")
    paths = cohort.pop("case_files")
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise ValueError("cohort case_files must be a list of names")
    cohort["cases"] = [load_object(fixture_root / path) for path in paths]
    return cohort


def inspect_catalog(case: dict[str, object], catalog_root: Path) -> dict[str, object]:
    issuer = string(case["issuer_id"])
    cutoff = datetime.fromisoformat(string(case["cutoff_at"]))
    capture = record(case["catalog_capture"])
    receipts = records(capture["response_receipts"])
    if len(receipts) != 1:
        raise ValueError("expected one retained SEC recent submissions response")
    receipt = receipts[0]
    scope = record(receipt["scope"])
    if (
        receipt["uri"] != f"https://data.sec.gov/submissions/CIK{issuer}.json"
        or scope["cik"] != issuer
        or scope["valuation_timestamp"] != case["cutoff_at"]
    ):
        raise ValueError(f"catalog receipt scope differs for {case['case_id']}")
    data = record(json.loads(read_original(receipt, catalog_root, False, None)))
    if data["cik"] != issuer:
        raise ValueError(f"catalog issuer differs for {case['case_id']}")
    filings = record(data["filings"])
    recent = record(filings["recent"])
    columns = (
        "accessionNumber",
        "form",
        "reportDate",
        "filingDate",
        "acceptanceDateTime",
        "primaryDocument",
    )
    selected: list[dict[str, str]] = []
    bindings = records(case["filings"])
    first = min(string(filing["reported_period_end"]) for filing in bindings)
    last = max(string(filing["reported_period_end"]) for filing in bindings)
    for values in zip(*(strings(recent[key]) for key in columns), strict=True):
        row = dict(zip(columns, values, strict=True))
        if (
            row["form"] in {"10-Q", "10-K", "10-Q/A", "10-K/A"}
            and first <= row["reportDate"] <= last
            and datetime.fromisoformat(row["acceptanceDateTime"]) <= cutoff
        ):
            selected.append(row)
    accession_rows = {row["accessionNumber"]: row for row in selected}
    for filing in bindings:
        matched_row = accession_rows.get(string(filing["accession_number"]))
        if matched_row is None or (
            matched_row["form"],
            matched_row["reportDate"],
            matched_row["filingDate"],
            matched_row["primaryDocument"],
            datetime.fromisoformat(matched_row["acceptanceDateTime"]),
        ) != (
            filing["form"],
            filing["reported_period_end"],
            filing["filing_date"],
            filing["primary_document"],
            datetime.fromisoformat(string(filing["accepted_at"])),
        ):
            raise ValueError(
                f"catalog row identity differs for {filing['accession_number']}"
            )
    older_files = records(filings["files"])
    if any(string(item["filingTo"]) >= first for item in older_files):
        raise ValueError(
            f"older SEC submissions file overlaps the sampled dates for {case['case_id']}"
        )
    recent_times = strings(recent["acceptanceDateTime"])
    recent_range = [
        min(recent_times, key=datetime.fromisoformat),
        max(recent_times, key=datetime.fromisoformat),
    ]
    undated_amendments = sorted(
        accession
        for accession, form, report_date, filing_date, accepted_at in zip(
            *(strings(recent[key]) for key in columns[:-1]), strict=True
        )
        if form in {"10-Q/A", "10-K/A"}
        and not report_date
        and filing_date >= first
        and datetime.fromisoformat(accepted_at) <= cutoff
    )
    return {
        "case_id": case["case_id"],
        "cutoff_at": case["cutoff_at"],
        "report_date_range": [first, last],
        "catalog_capture": capture,
        "rows": selected,
        "matching_amendment_accessions": sorted(
            row["accessionNumber"] for row in selected if row["form"].endswith("/A")
        ),
        "undated_amendment_accessions": undated_amendments,
        "recent_accepted_range": recent_range,
        "older_submissions_files_outside_filing_date_range": older_files,
        "scope": "Retained recent SEC submissions catalog and selected reporting dates only. Complete amendment lineage and accounting revision scope are not established.",
    }


def basis_fact_digest(fact: dict[str, object]) -> str:
    fields = (
        "observation_id",
        "row_id",
        "source_locator",
        "entity_identifier",
        "entity_scheme",
        "namespace_uri",
        "qname",
        "period",
        "unit_measures",
        "dimensions",
        "consolidation_scope",
        "printed_row_label",
        "raw_text",
        "canonical_decimal",
        "scale",
        "decimals",
    )
    payload = {key: fact[key] for key in fields}
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def check_basis_fact(
    binding: BasisObservation,
    filing: BasisFiling,
    row_id: str,
    period: dict[str, str],
    issuer_id: str,
    observations: dict[str, dict[str, object]],
) -> dict[str, object]:
    fact = observations.get(binding.observation_id)
    if (
        fact is None
        or (
            fact.get("row_id"),
            fact.get("period"),
            fact.get("issuer_id"),
            fact.get("entity_identifier"),
            fact.get("accession_number"),
            fact.get("accepted_at"),
            fact.get("primary_html_sha256"),
            fact.get("unit_measures"),
            fact.get("dimensions"),
            fact.get("consolidation_scope"),
            fact.get("decimals"),
        )
        != (
            row_id,
            period,
            issuer_id,
            issuer_id,
            filing.accession_number,
            filing.accepted_at,
            filing.primary_html_sha256,
            ["iso4217:USD"],
            [],
            "consolidated",
            "-6",
        )
        or fact.get("canonical_decimal") is None
        or basis_fact_digest(fact) != binding.sha256
    ):
        raise ValueError(
            f"basis observation differs for {row_id}: {binding.observation_id}"
        )
    return fact


def check_basis_disclosures(raw: bytes, filing: BasisFiling) -> None:
    tree = html.fromstring(raw)
    document = tree.getroottree()
    # HTML parsers preserve ix: in tag names. getpath keeps those locators usable.
    paragraphs = {document.getpath(node): node for node in tree.iter("div", "span")}
    for name, disclosure in filing.disclosures.items():
        node = paragraphs.get(disclosure.xpath)
        if (
            node is None
            or hashlib.sha256(text_content(node).encode()).hexdigest()
            != disclosure.sha256
        ):
            raise ValueError(
                f"basis disclosure differs for {filing.accession_number}: {name}"
            )


def replay_basis_filings(
    proof: ReviewedBasisProof,
    period: dict[str, object],
    parsed: dict[str, ParsedFiling],
    observations: dict[str, dict[str, object]],
    source_root: Path,
) -> str:
    scope = proof.scope
    required_roles: set[FilingRole] = {
        "original_annual",
        "original_interim",
        "later_annual",
        "later_interim",
    }
    if (
        set(proof.filings) != required_roles
        or len({filing.accession_number for filing in proof.filings.values()}) != 4
    ):
        raise ValueError("basis proof requires four distinct filings")
    expected_filings: dict[FilingRole, tuple[str, str | None, object]] = {
        "original_annual": ("10-K", scope.quarter_end, period["accession_number"]),
        "original_interim": (
            "10-Q",
            scope.nine_month_end,
            record(period["period_source"])["preceding_quarter_accession"],
        ),
        "later_annual": ("10-K", None, proof.filings["later_annual"].accession_number),
        "later_interim": (
            "10-Q",
            None,
            proof.filings["later_interim"].accession_number,
        ),
    }
    fiscal_opening = (
        date.fromisoformat(scope.fiscal_year_start) - timedelta(days=1)
    ).isoformat()
    opening_amounts = set()
    cutoff = datetime.fromisoformat(scope.cutoff_at)
    for role, filing in proof.filings.items():
        form, end, accession = expected_filings[role]
        source = parsed.get(filing.accession_number)
        if (
            source is None
            or filing.accession_number != accession
            or filing.form != form
        ):
            raise ValueError(f"basis filing role differs for {role}")
        metadata = source.metadata
        receipt = record(metadata["primary_receipt"])
        accepted = datetime.fromisoformat(filing.accepted_at)
        if accepted > cutoff:
            raise ValueError(
                f"basis filing accepted after cutoff: {filing.accession_number}"
            )
        if (
            (end and filing.reported_period_end != end)
            or (
                role.startswith("later_")
                and filing.reported_period_end <= scope.quarter_end
            )
            or (
                metadata["issuer_id"],
                metadata["form"],
                metadata["accepted_at"],
                metadata["reported_period_end"],
                metadata["primary_html_sha256"],
                receipt["uri"],
                receipt["content_hash"],
                receipt["received_size"],
            )
            != (
                scope.issuer_id,
                filing.form,
                filing.accepted_at,
                filing.reported_period_end,
                filing.primary_html_sha256,
                filing.primary_document_uri,
                filing.primary_html_sha256,
                filing.primary_html_bytes,
            )
        ):
            raise ValueError(
                f"basis filing identity differs for {filing.accession_number}"
            )
        if not filing.disclosures:
            raise ValueError(f"basis disclosures missing for {filing.accession_number}")
        check_basis_disclosures(
            read_original(receipt, source_root, False, None), filing
        )
        opening = check_basis_fact(
            filing.opening_cash,
            filing,
            "cash_flow_beginning_balance",
            {"period_type": "instant", "instant": fiscal_opening},
            scope.issuer_id,
            observations,
        )
        if (
            opening["qname"] != CASH_FLOW_BALANCE_QNAME
            or "restricted cash" not in string(opening["printed_row_label"]).lower()
        ):
            raise ValueError(
                f"basis opening cash definition differs for {filing.accession_number}"
            )
        opening_amounts.add(string(opening["canonical_decimal"]))
    if len(opening_amounts) != 1:
        raise ValueError("basis opening cash amount differs across filings")
    return max(
        (filing.accepted_at for filing in proof.filings.values()),
        key=datetime.fromisoformat,
    )


def replay_basis_rows(
    proof: ReviewedBasisProof,
    quarter_cells: dict[str, dict[str, object]],
    observations: dict[str, dict[str, object]],
) -> None:
    scope = proof.scope
    if set(proof.rows) != {
        row_id for row_id, cell in quarter_cells.items() if cell["value"] is not None
    }:
        raise ValueError("basis proof rows differ from the numeric quarter rows")
    expected_pairs: dict[PairRole, tuple[FilingRole, FilingRole, dict[str, str]]] = {
        "annual_flow": (
            "original_annual",
            "later_annual",
            {
                "period_type": "duration",
                "start_date": scope.fiscal_year_start,
                "end_date": scope.quarter_end,
            },
        ),
        "nine_month_flow": (
            "original_interim",
            "later_interim",
            {
                "period_type": "duration",
                "start_date": scope.fiscal_year_start,
                "end_date": scope.nine_month_end,
            },
        ),
        "year_end_balance": (
            "original_annual",
            "later_annual",
            {"period_type": "instant", "instant": scope.quarter_end},
        ),
        "q3_cash_close": (
            "original_interim",
            "later_interim",
            {"period_type": "instant", "instant": scope.nine_month_end},
        ),
        "year_end_cash_close": (
            "original_annual",
            "later_annual",
            {"period_type": "instant", "instant": scope.quarter_end},
        ),
    }
    duration_selection = {"annual_flow": "annual", "nine_month_flow": "nine_month_ytd"}
    for row_id, row in proof.rows.items():
        cell = quarter_cells[row_id]
        roles: list[PairRole]
        if row_id == "cash_flow_beginning_balance":
            roles = ["q3_cash_close"]
        elif row_id == "cash_flow_ending_balance":
            roles = ["year_end_cash_close"]
        elif cell["statement"] == "balance_sheet":
            roles = ["year_end_balance"]
        else:
            roles = ["annual_flow", "nine_month_flow"]
        expected_cash_scope = (
            "includes_restricted_cash"
            if cell["statement"] == "cash_flow"
            else "balance_sheet_cash_and_equivalents"
            if row_id == "cash_and_equivalents"
            else "not_applicable"
        )
        if row.cash_scope != expected_cash_scope:
            raise ValueError(f"basis cash scope differs for {row_id}")
        if [pair.role for pair in row.pairs] != roles or [
            pair.comparative.observation_id for pair in row.pairs
        ] != strings(cell["selected_observation_ids"]):
            raise ValueError(f"basis selection differs for {row_id}")
        comparison = record(cell.get("basis_evidence", cell.get("cash_basis", {})))
        if comparison.get("basis_conflict"):
            raise ValueError(f"basis proof cannot replace a conflict for {row_id}")
        for pair in row.pairs:
            original_role, later_role, period = expected_pairs[pair.role]
            source_row = (
                "cash_flow_ending_balance" if pair.role == "q3_cash_close" else row_id
            )
            original = check_basis_fact(
                pair.original,
                proof.filings[original_role],
                source_row,
                period,
                scope.issuer_id,
                observations,
            )
            later = check_basis_fact(
                pair.comparative,
                proof.filings[later_role],
                source_row,
                period,
                scope.issuer_id,
                observations,
            )
            if original["canonical_decimal"] != later[
                "canonical_decimal"
            ] or basis_conflict([original, later]):
                raise ValueError(f"basis original and comparative differ for {row_id}")
            if pair.role in duration_selection:
                selection = record(
                    record(cell["selection_decision"])[duration_selection[pair.role]]
                )
            else:
                selection = record(cell["selection"])
            candidate_ids = strings(selection["eligible_candidate_ids"])
            if pair.original.observation_id not in candidate_ids or any(
                observations[candidate]["canonical_decimal"]
                != later["canonical_decimal"]
                or basis_conflict([observations[candidate], later])
                for candidate in candidate_ids
            ):
                raise ValueError(
                    f"basis eligible observations differ for {row_id}: {pair.role}"
                )
            if pair.role in {"q3_cash_close", "year_end_cash_close"} and (
                original["qname"] != CASH_FLOW_BALANCE_QNAME
                or any(
                    "restricted cash" not in string(fact["printed_row_label"]).lower()
                    for fact in (original, later)
                )
            ):
                raise ValueError(f"basis closing cash definition differs for {row_id}")


def apply_reviewed_basis_proof(
    proof_path: Path,
    proof_sha256: str,
    golden: dict[str, object],
    parsed: dict[str, ParsedFiling],
    observations: dict[str, dict[str, object]],
    catalog: dict[str, object],
    source_root: Path,
) -> int:
    payload = proof_path.read_bytes()
    proof = ReviewedBasisProof.model_validate_json(payload)
    scope = proof.scope
    period = next(
        (
            item
            for item in records(golden["quarter_periods"])
            if item["quarter_id"] == scope.quarter_id
        ),
        None,
    )
    if (
        period is None
        or (
            golden["case_id"],
            golden["issuer_id"],
            golden["cutoff_at"],
            period["start_date"],
            period["end_date"],
            period["fiscal_year_start"],
            period["prior_quarter_end"],
            period["fiscal_period_focus"],
        )
        != (
            scope.case_id,
            scope.issuer_id,
            scope.cutoff_at,
            scope.quarter_start,
            scope.quarter_end,
            scope.fiscal_year_start,
            scope.nine_month_end,
            "FY",
        )
        or (
            date.fromisoformat(scope.quarter_end)
            - date.fromisoformat(scope.fiscal_year_start)
        ).days
        + 1
        != scope.fiscal_year_days
    ):
        raise ValueError("basis proof case, cutoff or fiscal period differs")
    receipts = records(record(catalog["catalog_capture"])["response_receipts"])
    if len(receipts) != 1 or (
        catalog["case_id"],
        catalog["cutoff_at"],
        receipts[0]["content_hash"],
        catalog["matching_amendment_accessions"],
    ) != (scope.case_id, scope.cutoff_at, proof.retained_submissions_sha256, []):
        raise ValueError("basis proof retained submissions or amendment scope differs")
    public_source_available_at = replay_basis_filings(
        proof, period, parsed, observations, source_root
    )
    cells = {
        string(cell["row_id"]): cell
        for cell in cast(list[dict[str, object]], golden["cells"])
        if cell["end_date"] == scope.quarter_end
    }
    replay_basis_rows(proof, cells, observations)
    if hashlib.sha256(payload).hexdigest() != proof_sha256:
        raise ValueError("basis proof digest differs from the reviewed registry")
    for row_id in proof.rows:
        cell = cells[row_id]
        evidence = record(cell.get("basis_evidence", {}))
        cell["basis_evidence"] = {
            **evidence,
            "reviewed_bridge": {
                "status": proof.review.verdict,
                "proof_shard": f"basis/{proof_path.name}",
                "proof_sha256": proof_sha256,
                "row_id": row_id,
                "selected_observation_ids": cell["selected_observation_ids"],
                "public_source_available_at": public_source_available_at,
            },
        }
    return len(proof.rows)


def pinned_basis_shard(
    path: Path, expected_sha256: str, model: type[BasisModel]
) -> BasisModel:
    payload = path.read_bytes()
    if (
        len(payload) >= MAX_FIXTURE_BYTES
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        raise ValueError(f"reviewed cohort basis digest differs for {path.name}")
    return model.model_validate(load_unique_basis_json(payload))


def load_unique_basis_json(payload: bytes) -> dict[str, object]:
    def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("duplicate field in reviewed cohort basis")
        return fields

    return record(json.loads(payload, object_pairs_hook=unique_fields))


def replay_cohort_filing(
    accession: str,
    filing: CohortFilingBasis,
    parsed: ParsedFiling,
    source_root: Path,
) -> dict[str, tuple[str, str, str]]:
    metadata = parsed.metadata
    receipt = record(metadata["primary_receipt"])
    if (
        metadata["accession_number"],
        metadata["issuer_id"],
        metadata["form"],
        metadata["reported_period_end"],
        metadata["accepted_at"],
        metadata["primary_html_sha256"],
        receipt["uri"],
        receipt["content_hash"],
        receipt["received_size"],
    ) != (
        accession,
        filing.issuer_id,
        filing.form,
        filing.reported_period_end,
        filing.accepted_at,
        filing.primary_html_sha256,
        filing.primary_document_uri,
        filing.primary_html_sha256,
        filing.primary_html_bytes,
    ):
        raise ValueError(f"reviewed cohort primary receipt differs for {accession}")
    required_notes = {"consolidated_gaap"}
    if filing.form == "10-Q":
        required_notes.add("interim_prior_annual_and_adjustments")
    if not required_notes <= filing.disclosures.keys() or not all(
        filing.disclosures.values()
    ):
        raise ValueError(
            f"reviewed cohort accounting disclosures missing for {accession}"
        )
    raw = read_original(receipt, source_root, False, None)
    root = html.fromstring(raw)
    tree = root.getroottree()
    paragraphs = {tree.getpath(node): node for node in tree.iter("p", "div")}
    for label, disclosures in filing.disclosures.items():
        for disclosure in disclosures:
            node = paragraphs.get(disclosure.xpath)
            if (
                node is None
                or hashlib.sha256(text_content(node).encode()).hexdigest()
                != disclosure.sha256
            ):
                raise ValueError(
                    f"reviewed cohort accounting disclosure differs for {accession}/{label}"
                )
    inline = (
        node
        for node in tree.iter("ix:nonfraction", "ix:nonnumeric", "ix:fraction")
        if node.get("name")
    )
    return {
        f"{accession}/fact-{index}": (
            node.get("id", ""),
            tree.getpath(node),
            node.get("name", ""),
        )
        for index, node in enumerate(inline)
        if node.get("name") == CASH_FLOW_BALANCE_QNAME
    }


def replay_cohort_catalog(
    proof: CohortCaseProof,
    case: dict[str, object],
    catalog: dict[str, object],
    registry: CohortFilingRegistry,
) -> None:
    capture = record(catalog["catalog_capture"])
    recent_range = strings(catalog["recent_accepted_range"])
    bindings = records(case["filings"])
    accession_roles = {
        string(filing["accession_number"]): string(filing["source_role"])
        for filing in bindings
    }
    catalog_accessions = {
        string(row["accessionNumber"]) for row in records(catalog["rows"])
    }
    reviewed_accessions = set(proof.source_accessions)
    if (
        proof.cutoff_at != case["cutoff_at"]
        or proof.case_id != case["case_id"]
        or proof.issuer_id != case["issuer_id"]
        or proof.case_id != catalog["case_id"]
        or proof.cutoff_at != catalog["cutoff_at"]
        or len(reviewed_accessions) != len(proof.source_accessions)
        or len(accession_roles) != len(bindings)
        or reviewed_accessions != catalog_accessions
        or accession_roles
        != {
            accession: filing.source_roles_by_case[proof.case_id]
            for accession, filing in registry.filings.items()
            if proof.case_id in filing.source_roles_by_case
            and filing.issuer_id == proof.issuer_id
            and datetime.fromisoformat(filing.accepted_at)
            <= datetime.fromisoformat(proof.cutoff_at)
        }
        or reviewed_accessions != accession_roles.keys()
        or records(capture["response_receipts"])[0]["content_hash"]
        != proof.catalog.submissions_sha256
        or catalog["report_date_range"] != proof.catalog.report_dates
        or recent_range != proof.catalog.recent_accepted_range
        or recent_range[0][:10] >= proof.catalog.report_dates[0]
        or [
            item["filingTo"]
            for item in records(
                catalog["older_submissions_files_outside_filing_date_range"]
            )
        ]
        != proof.catalog.archived_filing_date_upper_bounds
        or catalog["matching_amendment_accessions"]
        or catalog["undated_amendment_accessions"]
    ):
        raise ValueError(
            f"reviewed cohort submissions or amendment scope differs for {proof.case_id}"
        )


def cohort_fact_digest(observation: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            observation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def cohort_same_period_key(observation: dict[str, object]) -> bytes:
    fields = (
        "row_id",
        "issuer_id",
        "entity_identifier",
        "entity_scheme",
        "qname",
        "unit_measures",
        "dimensions",
        "consolidation_scope",
        "cash_basis",
        "period",
    )
    return json.dumps(
        [observation[key] for key in fields], sort_keys=True, separators=(",", ":")
    ).encode()


def cohort_accepted_pairs(
    observation_ids: set[str],
    observations: dict[str, dict[str, object]],
    candidates: dict[bytes, list[str]],
) -> set[tuple[str, str]]:
    pairs = set()
    for observation_id in observation_ids:
        selected = observations[observation_id]
        for counterpart_id in candidates[cohort_same_period_key(selected)]:
            if counterpart_id == observation_id:
                continue
            counterpart = observations[counterpart_id]
            if (selected["canonical_decimal"], selected["decimals"]) != (
                counterpart["canonical_decimal"],
                counterpart["decimals"],
            ):
                raise ValueError(
                    f"reviewed cohort revision differs for {observation_id} and {counterpart_id}"
                )
            earlier, later = sorted(
                (observation_id, counterpart_id),
                key=lambda key: (
                    datetime.fromisoformat(string(observations[key]["accepted_at"])),
                    key,
                ),
            )
            if selected["accession_number"] == counterpart["accession_number"] and any(
                selected[key] != counterpart[key]
                for key in ("table_index", "row_index", "context_id")
            ):
                raise ValueError(
                    f"reviewed cohort same-filing duplicate differs for {observation_id}"
                )
            pairs.add((earlier, later))
    return pairs


def replay_cohort_fact(
    observation_id: str,
    proof: CohortCaseProof,
    observations: dict[str, dict[str, object]],
) -> dict[str, object]:
    fact = observations.get(observation_id)
    if fact is None or (
        fact["accession_number"] not in proof.source_accessions
        or fact["issuer_id"] != proof.issuer_id
        or fact["entity_identifier"] != proof.issuer_id
        or fact["entity_scheme"] != "http://www.sec.gov/CIK"
        or datetime.fromisoformat(string(fact["accepted_at"]))
        > datetime.fromisoformat(proof.cutoff_at)
        or fact["unit_measures"] != ["iso4217:USD"]
        or fact["dimensions"] != []
        or fact["consolidation_scope"] != "consolidated"
        or fact["revision_basis_id"] is not None
        or fact["decimals"] != "-6"
        or fact["canonical_decimal"] is None
        or cohort_fact_digest(fact) != proof.observation_sha256.get(observation_id)
    ):
        raise ValueError(
            f"reviewed cohort fact differs for {proof.case_id}/{observation_id}"
        )
    return fact


def difference_observation_ids(cell: dict[str, object]) -> list[str]:
    return [
        string(record(cell[key])["observation_id"])
        for key in (
            "current_ytd_input",
            "prior_ytd_input",
            "annual_input",
            "nine_month_ytd_input",
        )
        if cell.get(key) is not None
    ]


def replay_cohort_quarter_row(
    cell: dict[str, object],
    binding: CohortQuarterRow,
    period: CohortQuarterBasis,
    observations: dict[str, dict[str, object]],
    candidates: dict[bytes, list[str]],
) -> set[str]:
    row_id = string(cell["row_id"])
    selected = strings(cell["selected_observation_ids"])
    difference = difference_observation_ids(cell)
    required_ids = set(quarter_source_observation_ids(cell))
    present = cell["value"] is not None
    if (
        (
            binding.cell_id,
            binding.statement,
            binding.selected_observation_ids,
            binding.difference_observation_ids,
            binding.source_available_at,
            binding.verdict,
        )
        != (
            cell["cell_id"],
            cell["statement"],
            selected,
            difference,
            cell["source_available_at"],
            "supported_limited" if present else "not_comparable_missing_source",
        )
        or (
            not present
            and (cell["availability"] != "missing" or selected or difference)
        )
        or required_ids != set(selected + difference)
        or binding.uses_blocked_source
        != any(
            observations[observation_id]["accession_number"]
            == SOURCE_ADMISSION_BLOCKED_ACCESSION
            for observation_id in required_ids
        )
    ):
        raise ValueError(f"reviewed cohort quarter inputs differ for {binding.cell_id}")
    pairs = cohort_accepted_pairs(required_ids, observations, candidates)
    same_filing = {
        (earlier, later)
        for earlier, later in pairs
        if observations[earlier]["accession_number"]
        == observations[later]["accession_number"]
    }
    if sorted(map(tuple, binding.original_comparative_pairs)) != sorted(
        pairs - same_filing
    ) or sorted(map(tuple, binding.same_filing_duplicate_pairs)) != sorted(same_filing):
        raise ValueError(
            f"reviewed cohort comparative set differs for {binding.cell_id}"
        )
    if not present:
        return required_ids
    end = period.end_date
    start = period.start_date
    if row_id in (CASH_OPENING_ROW, CASH_CLOSING_ROW):
        instant = (
            (date.fromisoformat(start) - timedelta(days=1)).isoformat()
            if row_id == CASH_OPENING_ROW
            else end
        )
        if len(selected) != 1 or (
            observations[selected[0]]["qname"],
            observations[selected[0]]["period"],
        ) != (CASH_FLOW_BALANCE_QNAME, {"period_type": "instant", "instant": instant}):
            raise ValueError(
                f"reviewed cohort cash scope differs for {binding.cell_id}"
            )
    elif binding.statement == "balance_sheet":
        if len(selected) != 1 or observations[selected[0]]["period"] != {
            "period_type": "instant",
            "instant": end,
        }:
            raise ValueError(f"reviewed cohort instant differs for {binding.cell_id}")
    elif difference:
        current, prior = (observations[key] for key in difference)
        expected_prior_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        if current["period"] != {
            "period_type": "duration",
            "start_date": period.fiscal_year_start,
            "end_date": end,
        } or prior["period"] != {
            "period_type": "duration",
            "start_date": period.fiscal_year_start,
            "end_date": expected_prior_end,
        }:
            raise ValueError(f"reviewed cohort YTD span differs for {binding.cell_id}")
    if (
        binding.statement != "balance_sheet"
        and row_id not in (CASH_OPENING_ROW, CASH_CLOSING_ROW)
        and len(selected) == 1
    ):
        if observations[selected[0]]["period"] != {
            "period_type": "duration",
            "start_date": start,
            "end_date": end,
        }:
            raise ValueError(
                f"reviewed cohort reported quarter span differs for {binding.cell_id}"
            )
    if row_id not in (CASH_OPENING_ROW, CASH_CLOSING_ROW) and any(
        observations[key]["row_id"] != row_id for key in required_ids
    ):
        raise ValueError(f"reviewed cohort row differs for {binding.cell_id}")
    return required_ids.union(*(set(pair) for pair in pairs))


def replay_cohort_opening_cash(
    quarter: CohortQuarterProof,
    all_cash_locators: dict[str, tuple[str, str, str]],
    observations: dict[str, dict[str, object]],
) -> set[str]:
    cash_ids = {binding.observation_id for binding in quarter.fiscal_opening_cash}
    if quarter.period.fiscal_period_focus != "FY":
        if cash_ids or quarter.original_anchor_accessions:
            raise ValueError(
                f"fiscal-year opening cash attached outside Q4: {quarter.period.quarter_id}"
            )
        return cash_ids
    annual = quarter.period.accession_number
    interim = string(quarter.period.period_source["preceding_quarter_accession"])
    anchors = {annual, interim}
    if anchors != set(quarter.original_anchor_accessions):
        raise ValueError(
            f"reviewed cohort Q4 originals differ for {quarter.period.quarter_id}"
        )
    net = quarter.rows[CASH_NET_CHANGE_ROW]
    operands = set(net.difference_observation_ids)
    for left, right in net.original_comparative_pairs:
        if left in operands and observations[right]["accession_number"] in anchors:
            operands.add(right)
        if right in operands and observations[left]["accession_number"] in anchors:
            operands.add(left)
    source_tables = {
        (observations[key]["accession_number"], observations[key]["table_index"])
        for key in operands
    }
    fiscal_opening = (
        date.fromisoformat(quarter.period.fiscal_year_start) - timedelta(days=1)
    ).isoformat()
    bound_tables = set()
    amounts = set()
    for binding in quarter.fiscal_opening_cash:
        fact = observations[binding.observation_id]
        if (
            all_cash_locators.get(binding.observation_id)
            != (binding.fact_id, binding.xpath, CASH_FLOW_BALANCE_QNAME)
            or fact["row_id"] != CASH_OPENING_ROW
            or fact["period"] != {"period_type": "instant", "instant": fiscal_opening}
        ):
            raise ValueError(
                f"reviewed cohort opening cash differs for {binding.observation_id}"
            )
        bound_tables.add((fact["accession_number"], fact["table_index"]))
        amounts.add(string(fact["canonical_decimal"]))
    if (
        len(cash_ids) != len(quarter.fiscal_opening_cash)
        or bound_tables != source_tables
        or len(amounts) != 1
    ):
        raise ValueError(
            f"reviewed cohort Q4 cash basis differs for {quarter.period.quarter_id}"
        )
    for row in quarter.rows.values():
        for identity in row.selected_observation_ids:
            if observations[identity]["accession_number"] in anchors:
                continue
            if not any(
                identity in pair
                and any(
                    observations[member]["accession_number"] in anchors
                    for member in pair
                )
                for pair in row.original_comparative_pairs
            ):
                raise ValueError(
                    f"reviewed cohort Q4 comparative has no original for {row.cell_id}"
                )
    return cash_ids


def cohort_basis_link(
    verdict: BasisVerdict, path: str, cell_id: str, uses_blocked_source: bool
) -> dict[str, object]:
    return {
        "status": verdict,
        "case_proof_shard": path,
        "case_proof_sha256": COHORT_BASIS_SHARDS[path],
        "filing_proof_shard": COHORT_BASIS_FILINGS_PATH,
        "filing_proof_sha256": COHORT_BASIS_SHARDS[COHORT_BASIS_FILINGS_PATH],
        "review_matrix_sha256": COHORT_BASIS_MATRIX_SHA256,
        "cell_id": cell_id,
        "uses_source_admission_blocked_accession": uses_blocked_source,
    }


def replay_cohort_quarters(
    proof: CohortCaseProof,
    golden: dict[str, object],
    observations: dict[str, dict[str, object]],
    all_cash_locators: dict[str, tuple[str, str, str]],
    proof_path: str,
) -> None:
    for observation_id in proof.observation_sha256:
        replay_cohort_fact(observation_id, proof, observations)
    candidates: dict[bytes, list[str]] = {}
    for observation_id, fact in observations.items():
        if fact[
            "accession_number"
        ] in proof.source_accessions and datetime.fromisoformat(
            string(fact["accepted_at"])
        ) <= datetime.fromisoformat(proof.cutoff_at):
            candidates.setdefault(cohort_same_period_key(fact), []).append(
                observation_id
            )
    periods = {
        string(period["end_date"]): period
        for period in records(golden["quarter_periods"])
    }
    cells: dict[str, dict[str, dict[str, object]]] = {end: {} for end in periods}
    ordered_cells = records(golden["cells"])
    for cell in ordered_cells:
        rows = cells[string(cell["end_date"])]
        row_id = string(cell["row_id"])
        if row_id in rows:
            raise ValueError(f"duplicate quarter cell {cell['cell_id']}")
        rows[row_id] = cell
    if proof.quarters.keys() != periods.keys():
        raise ValueError(
            f"reviewed cohort quarter coverage differs for {proof.case_id}"
        )
    facts_used: set[str] = set()
    links = []
    for end, quarter in proof.quarters.items():
        if (
            quarter.period.end_date != end
            or quarter.period.model_dump()
            != {key: periods[end][key] for key in CohortQuarterBasis.model_fields}
            or quarter.rows.keys() != cells[end].keys()
        ):
            raise ValueError(
                f"reviewed cohort quarter period or rows differ for {proof.case_id}/{end}"
            )
        for row_id, binding in quarter.rows.items():
            cell = cells[end][row_id]
            facts_used.update(
                replay_cohort_quarter_row(
                    cell, binding, quarter.period, observations, candidates
                )
            )
            links.append((cell, binding))
        facts_used.update(
            replay_cohort_opening_cash(quarter, all_cash_locators, observations)
        )
    if facts_used != proof.observation_sha256.keys():
        raise ValueError(f"reviewed cohort fact coverage differs for {proof.case_id}")
    for cell, binding in links:
        cell["reviewed_cohort_basis"] = cohort_basis_link(
            binding.verdict, proof_path, binding.cell_id, binding.uses_blocked_source
        )
    golden["cells"] = ordered_cells


def replay_cohort_ttm(
    proof: CohortCaseProof,
    windows: list[dict[str, object]],
    observations: dict[str, dict[str, object]],
    proof_path: str,
) -> None:
    if (
        len(windows) != len(proof.ttm)
        or {window["end_date"] for window in windows} != proof.ttm.keys()
    ):
        raise ValueError(f"reviewed cohort TTM coverage differs for {proof.case_id}")
    periods_by_id = {
        quarter.period.quarter_id: quarter for quarter in proof.quarters.values()
    }
    for window in windows:
        expected = proof.ttm[string(window["end_date"])]
        if any(
            window[key] != getattr(expected, key)
            for key in (
                "window_id",
                "start_date",
                "end_date",
                "inclusive_calendar_days",
                "quarter_ids",
            )
        ):
            raise ValueError(
                f"reviewed cohort TTM period differs for {expected.window_id}"
            )
        quarters = [periods_by_id[key] for key in expected.quarter_ids]
        cash_pairs = [
            [
                left.rows[CASH_CLOSING_ROW].selected_observation_ids[0],
                right.rows[CASH_OPENING_ROW].selected_observation_ids[0],
            ]
            for left, right in zip(quarters, quarters[1:])
        ]
        if (
            len(set(expected.quarter_ids)) != 4
            or sum(quarter.period.inclusive_calendar_days for quarter in quarters)
            != expected.inclusive_calendar_days
            or (len({quarter.period.fiscal_year_focus for quarter in quarters}) > 1)
            != expected.crosses_fiscal_year
            or cash_pairs != expected.adjacent_cash_boundary_fact_ids
        ):
            raise ValueError(
                f"reviewed cohort TTM calendar or cash edges differ for {expected.window_id}"
            )
        for left_id, right_id in cash_pairs:
            left, right = observations[left_id], observations[right_id]
            if any(
                left[key] != right[key]
                for key in ("period", "qname", "canonical_decimal", "cash_basis")
            ):
                raise ValueError(
                    f"reviewed cohort TTM cash boundary differs for {expected.window_id}"
                )
        cells = records(window["cells"])
        if (
            len(cells) != len(expected.rows)
            or {cell["row_id"] for cell in cells} != expected.rows.keys()
        ):
            raise ValueError(
                f"reviewed cohort TTM rows differ for {expected.window_id}"
            )
        for cell in cells:
            row_id = string(cell["row_id"])
            binding = expected.rows[row_id]
            by_id = {
                quarter.rows[row_id].cell_id: quarter.rows[row_id]
                for quarter in quarters
            }
            required = [by_id[key] for key in strings(cell["required_input_cell_ids"])]
            selected = strings(cell["selected_input_cell_ids"])
            earliest = max(
                (
                    row.source_available_at
                    for row in required
                    if row.source_available_at
                ),
                key=datetime.fromisoformat,
                default=None,
            )
            if (
                (
                    binding.selected_quarter_cell_ids,
                    binding.selected_observation_ids,
                    binding.source_available_at,
                )
                != (
                    selected,
                    [
                        key
                        for cell_id in selected
                        for key in by_id[cell_id].selected_observation_ids
                    ],
                    cell["source_available_at"],
                )
                or binding.source_available_at != earliest
                or {row.verdict for row in required} != {binding.verdict}
                or binding.uses_blocked_source
                != any(row.uses_blocked_source for row in required)
                or (cell["value"] is not None)
                != (binding.verdict == "supported_limited")
            ):
                raise ValueError(
                    f"reviewed cohort TTM inputs differ for {cell['cell_id']}"
                )
            cell["reviewed_cohort_basis"] = cohort_basis_link(
                binding.verdict,
                proof_path,
                string(cell["cell_id"]),
                binding.uses_blocked_source,
            )
            cell["basis_check"] = {
                **record(cell["basis_check"]),
                "comparability_status": binding.verdict,
            }
        window["cells"] = cells


def build_goldens(
    fixture_root: Path,
    source_root: Path,
    annual_path: Path,
    fetch: bool,
    user_agent: str | None,
    catalog_root: Path,
) -> tuple[dict[str, bytes], dict[str, object]]:
    cohort = load_cohort(fixture_root)
    row_policy = load_object(fixture_root / "issue495-row-policy.json")
    annual = load_object(annual_path)
    row_catalog = build_row_catalog(annual, row_policy)
    rows = records(row_policy["rows"])
    cases = records(cohort["cases"])
    legacy_basis_paths = {
        name for case_proofs in REVIEWED_BASIS_PROOFS.values() for name in case_proofs
    }
    if {
        str(path.relative_to(fixture_root))
        for path in (fixture_root / "basis").rglob("*.json")
    } != COHORT_BASIS_SHARDS.keys() | legacy_basis_paths:
        raise ValueError("reviewed basis shard inventory differs")
    filing_registry = pinned_basis_shard(
        fixture_root / COHORT_BASIS_FILINGS_PATH,
        COHORT_BASIS_SHARDS[COHORT_BASIS_FILINGS_PATH],
        CohortFilingRegistry,
    )
    if (
        filing_registry.authority.matrix_sha256,
        filing_registry.authority.index_sha256,
    ) != (COHORT_BASIS_MATRIX_SHA256, COHORT_BASIS_INDEX_SHA256):
        raise ValueError("reviewed cohort basis authority differs")
    parsed_by_accession: dict[str, ParsedFiling] = {}
    case_parsed: dict[str, dict[str, ParsedFiling]] = {}
    for case in cases:
        parsed: dict[str, ParsedFiling] = {}
        for filing in records(case["filings"]):
            accession = str(filing["accession_number"])
            for receipt in records(filing["source_responses"]):
                if (
                    record(receipt["scope"]).get("valuation_timestamp")
                    != case["cutoff_at"]
                ):
                    raise ValueError(
                        f"{accession} has a response receipt bound to another cutoff"
                    )
            if accession not in parsed_by_accession:
                parsed_by_accession[accession] = parse_filing(
                    filing,
                    str(case["issuer_id"]),
                    rows,
                    row_catalog,
                    source_root,
                    fetch,
                    user_agent,
                )
            else:
                existing = parsed_by_accession[accession]
                existing_receipts = {
                    receipt["uri"]: receipt["content_hash"]
                    for receipt in records(existing.metadata["source_responses"])
                }
                current_receipts = records(filing["source_responses"])
                if {
                    receipt["uri"]: receipt["content_hash"]
                    for receipt in current_receipts
                } != existing_receipts:
                    raise ValueError(
                        f"shared source {accession} has different pinned bytes across cases"
                    )
                for receipt in current_receipts:
                    scope = record(receipt["scope"])
                    if (scope.get("cik"), scope.get("accession_number")) != (
                        case["issuer_id"],
                        accession,
                    ):
                        raise ValueError(
                            f"{accession} has a shared receipt bound to another filing"
                        )
                    read_original(receipt, source_root, fetch, user_agent)
            parsed[accession] = parsed_by_accession[accession]
        case_parsed[str(case["case_id"])] = parsed

    if parsed_by_accession.keys() != filing_registry.filings.keys():
        raise ValueError("reviewed cohort source coverage differs")
    all_cash_locators = {
        identity: locator
        for accession, filing in filing_registry.filings.items()
        for identity, locator in replay_cohort_filing(
            accession, filing, parsed_by_accession[accession], source_root
        ).items()
    }
    generated: dict[str, bytes] = {}
    source_count = 0
    for accession, parsed_filing in sorted(parsed_by_accession.items()):
        sources, observations = build_source_registry({accession: parsed_filing})
        source_count += len(observations)
        generated[f"golden/sources/{accession}.json"] = json_bytes(
            {"source": sources[accession], "observations": observations}
        )
    case_goldens = []
    basis_proof_rows = 0
    cohort_proofs: dict[str, CohortCaseProof] = {}
    observations_by_case: dict[str, dict[str, dict[str, object]]] = {}
    for case in cases:
        case_id = str(case["case_id"])
        catalog = inspect_catalog(case, catalog_root)
        generated[f"golden/catalog/{case_id}.json"] = json_bytes(catalog)
        accessions = {
            str(filing["accession_number"])
            for filing in cast(list[dict[str, object]], case["filings"])
        }
        _, observations = build_source_registry(
            {accession: parsed_by_accession[accession] for accession in accessions}
        )
        observations_by_case[case_id] = observations
        periods = build_quarter_periods(case, case_parsed[case_id], "revenue")
        golden = build_case_golden(
            case, periods, case_parsed[case_id], rows, observations
        )
        proof_name = f"basis/cohort-{case_id}.json"
        proof = pinned_basis_shard(
            fixture_root / proof_name, COHORT_BASIS_SHARDS[proof_name], CohortCaseProof
        )
        if proof.authority != filing_registry.authority:
            raise ValueError(f"reviewed cohort basis authority differs for {case_id}")
        replay_cohort_catalog(proof, case, catalog, filing_registry)
        replay_cohort_quarters(
            proof, golden, observations, all_cash_locators, proof_name
        )
        cohort_proofs[case_id] = proof
        for name, digest in REVIEWED_BASIS_PROOFS.get(case_id, {}).items():
            basis_proof_rows += apply_reviewed_basis_proof(
                fixture_root / name,
                digest,
                golden,
                case_parsed[case_id],
                observations,
                catalog,
                source_root,
            )
        for period in periods:
            end = period["end_date"]
            generated[f"golden/quarter/{case_id}/{end}.json"] = json_bytes(
                {
                    "period": period,
                    "cells": [
                        cell
                        for cell in records(golden["cells"])
                        if cell["end_date"] == end
                    ],
                }
            )
        generated[f"golden/quarter/{case_id}/index.json"] = json_bytes(
            {
                key: value
                for key, value in golden.items()
                if key not in {"cells", "quarter_periods"}
            }
        )
        case_goldens.append(golden)
    ttm = build_ttm_golden(case_goldens, rows, observations_by_case)
    if ttm["cell_count"] != 500:
        raise ValueError(f"expected 500 TTM cells, got {ttm['cell_count']}")
    ttm_windows = records(ttm["windows"])
    for case_id, proof in cohort_proofs.items():
        replay_cohort_ttm(
            proof,
            [window for window in ttm_windows if window["case_id"] == case_id],
            observations_by_case[case_id],
            f"basis/cohort-{case_id}.json",
        )
    for window in ttm_windows:
        generated[f"golden/ttm/{window['case_id']}/{window['end_date']}.json"] = (
            json_bytes(window)
        )
    annual_regression = build_annual_regression(annual, annual_path, cohort)
    for case in records(annual_regression.pop("cases")):
        generated[f"golden/annual/{case['case_id']}.json"] = json_bytes(case)
    summary = {
        "source_count": len(parsed_by_accession),
        "observation_count": source_count,
        "quarter_cells": sum(len(records(golden["cells"])) for golden in case_goldens),
        "quarter_missing": sum(
            cell["availability"] == "missing"
            for golden in case_goldens
            for cell in records(golden["cells"])
        ),
        "quarter_conflicts": sum(
            cell["availability"] == "conflict"
            for golden in case_goldens
            for cell in records(golden["cells"])
        ),
        "ttm_windows": ttm["window_count"],
        "ttm_cells": ttm["cell_count"],
        "annual_cells": annual_regression["cell_count"],
        "separately_reviewed_first_q4_basis_rows": basis_proof_rows,
        "reviewed_quarter_basis_rows": sum(
            row.verdict == "supported_limited"
            for proof in cohort_proofs.values()
            for quarter in proof.quarters.values()
            for row in quarter.rows.values()
        ),
        "reviewed_ttm_basis_rows": sum(
            row.verdict == "supported_limited"
            for proof in cohort_proofs.values()
            for window in proof.ttm.values()
            for row in window.rows.values()
        ),
        "case_coverage": {
            str(golden["case_id"]): golden["coverage"] for golden in case_goldens
        },
    }
    inputs = [
        fixture_root / name
        for name in (
            "issue495-cohort.json",
            "issue495-row-policy.json",
            "issue495-boundary-cases.json",
            "issue495-legacy-hash-baseline.json",
        )
    ]
    inputs.extend(sorted((fixture_root / "cases").glob("*.json")))
    inputs.extend(
        fixture_root / name
        for name in sorted(COHORT_BASIS_SHARDS.keys() | legacy_basis_paths)
    )
    for path in inputs:
        if path.stat().st_size >= MAX_FIXTURE_BYTES:
            raise ValueError(f"fixture exceeds {MAX_FIXTURE_BYTES} bytes: {path.name}")
    generated["issue495-golden-manifest.json"] = (
        json.dumps(
            {
                "protocol": "issue495-independent-decimal-golden-v1",
                "coverage": summary,
                "annual_regression": annual_regression,
                "inputs": {
                    str(path.relative_to(fixture_root)): hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    for path in inputs
                },
                "shards": {
                    name: {
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                    for name, payload in sorted(generated.items())
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode()
    for name, payload in generated.items():
        if len(payload) >= MAX_FIXTURE_BYTES:
            raise ValueError(f"fixture exceeds {MAX_FIXTURE_BYTES} bytes: {name}")
    return generated, summary


def fixture_diffs(generated: dict[str, bytes], fixture_root: Path) -> list[str]:
    diffs = []
    for name, expected in sorted(generated.items()):
        path = fixture_root / name
        if not path.is_file():
            diffs.append(f"missing: {path}")
        elif path.read_bytes() != expected:
            diffs.append(f"different: {path}")
    for path in sorted((fixture_root / "golden").rglob("*.json")):
        if str(path.relative_to(fixture_root)) not in generated:
            diffs.append(f"unexpected: {path}")
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-root", type=Path, default=DEFAULT_FIXTURE_ROOT)
    parser.add_argument("--annual-golden", type=Path, default=DEFAULT_ANNUAL_GOLDEN)
    parser.add_argument(
        "--source-root",
        type=Path,
        help="Retained SEC CAS root containing content/<prefix>/<sha256>.bin",
    )
    parser.add_argument(
        "--fetch-sec",
        action="store_true",
        help="Fetch missing accession responses from www.sec.gov and compare their pinned hashes",
    )
    parser.add_argument(
        "--catalog-root",
        type=Path,
        help="Retained SEC submissions CAS root. Defaults to --source-root.",
    )
    parser.add_argument(
        "--user-agent",
        help="SEC contact string. Defaults to SEC_USER_AGENT when --fetch-sec is used.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write the generated independent golden fixtures",
    )
    mode.add_argument(
        "--check",
        "--verify",
        action="store_true",
        help="Recompute and compare every generated fixture",
    )
    args = parser.parse_args()
    if args.source_root is None:
        parser.error("--source-root is required")
    if args.fetch_sec and not (args.user_agent or os.environ.get("SEC_USER_AGENT")):
        parser.error("--fetch-sec requires --user-agent or SEC_USER_AGENT")
    generated, summary = build_goldens(
        args.fixture_root,
        args.source_root,
        args.annual_golden,
        args.fetch_sec,
        args.user_agent,
        args.catalog_root or args.source_root,
    )
    if args.write:
        output_root = args.fixture_root
        for name, payload in generated.items():
            path = output_root / name
            if path.exists() and path.read_bytes() == payload:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(path)
        print(json.dumps({"mode": "write", **summary}, sort_keys=True))
        return 0
    differences = fixture_diffs(generated, args.fixture_root)
    print(
        json.dumps(
            {"mode": "check", "differences": differences, **summary}, sort_keys=True
        )
    )
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
