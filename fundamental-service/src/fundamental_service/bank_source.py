"""Typed parsing for captured FDIC BankFind financial records."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import SourceRecordV1, SourceRole


class BankFindFinancialReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = "fdic-bankfind"
    certificate: str = Field(min_length=1)
    institution_name: str = Field(min_length=1)
    report_date: date
    unit: str = "USD thousand"
    total_assets: Decimal = Field(gt=0)
    book_equity: Decimal = Field(gt=0)
    net_income: Decimal
    deposits: Decimal = Field(gt=0)
    risk_weighted_assets: Decimal = Field(gt=0)
    cet1_ratio: Decimal = Field(gt=0, le=1)
    source_uri: str = Field(min_length=1)
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_at: datetime

    @model_validator(mode="after")
    def source_is_regulatory_entity_evidence(self) -> BankFindFinancialReportV1:
        host = urlsplit(self.source_uri).hostname
        if host != "banks.data.fdic.gov":
            raise ValueError("FDIC record must retain the official BankFind URI")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("FDIC availability timestamp must include a timezone")
        if self.available_at.date() < self.report_date:
            raise ValueError("FDIC data cannot be available before its report date")
        return self


def parse_fdic_bankfind_report(
    payload: bytes,
    *,
    source: SourceRecordV1,
    expected_certificate: str,
) -> BankFindFinancialReportV1:
    """Parse one point-in-time FDIC report without assigning it to an issuer."""

    if source.source_id != "fdic-bankfind" or source.role is not SourceRole.REFERENCE:
        raise ValueError("source is not registered as public FDIC evidence")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != source.content_hash:
        raise ValueError("FDIC payload does not match its immutable source hash")
    parsed_uri = urlsplit(source.uri)
    if (
        parsed_uri.scheme != "https"
        or parsed_uri.hostname != "banks.data.fdic.gov"
        or not parsed_uri.path.startswith("/api/financials")
    ):
        raise ValueError("FDIC source URI is outside the financial-report endpoint")

    try:
        document: Any = json.loads(payload, parse_float=Decimal, parse_int=Decimal)
        rows = document["data"]
        if len(rows) != 1:
            raise ValueError("FDIC financial capture must contain exactly one report")
        values = rows[0]["data"]
        certificate = str(values["CERT"])
        if certificate != expected_certificate:
            raise ValueError(
                "FDIC certificate does not match the requested institution"
            )
        report_date = date.fromisoformat(
            f"{str(values['REPDTE'])[:4]}-{str(values['REPDTE'])[4:6]}-"
            f"{str(values['REPDTE'])[6:8]}"
        )
        report = BankFindFinancialReportV1(
            certificate=certificate,
            institution_name=str(values["NAME"]),
            report_date=report_date,
            total_assets=values["ASSET"],
            book_equity=values["EQ"],
            net_income=values["NETINC"],
            deposits=values["DEP"],
            risk_weighted_assets=values["RWAJT"],
            cet1_ratio=values["IDT1RWAJR"] / Decimal("100"),
            source_uri=source.uri,
            source_content_hash=source.content_hash,
            available_at=source.available_at,
        )
    except (KeyError, IndexError, TypeError, ValueError, ArithmeticError) as error:
        raise ValueError(
            f"FDIC financial report is incomplete or malformed: {error}"
        ) from error

    query = parse_qs(parsed_uri.query)
    filters = query.get("filters", [""])[0]
    expected_filter = f"CERT:{expected_certificate}"
    if (
        expected_filter not in filters
        or report.report_date.strftime("%Y%m%d") not in filters
    ):
        raise ValueError("FDIC URI filters do not identify the captured report")
    return report


def bank_report_issuer_mapping_status(
    *,
    report: BankFindFinancialReportV1,
    issuer_id: str,
) -> tuple[str, tuple[str, ...]]:
    """Report issuer coverage as unsupported until an entity-link gate ships."""

    if not issuer_id or not report.certificate:
        return "unsupported", ("BANK_REGULATORY_ENTITY_UNMAPPED",)
    return "unsupported", ("BANK_REGULATORY_ENTITY_MAPPING_NOT_RELEASED",)


__all__ = [
    "BankFindFinancialReportV1",
    "bank_report_issuer_mapping_status",
    "parse_fdic_bankfind_report",
]
