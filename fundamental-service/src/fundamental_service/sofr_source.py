"""Typed capture profile for the New York Fed's overnight SOFR observations."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .macro_series import (
    MacroObservationV1,
    MacroSeriesVintageV1,
)
from .snapshots import SnapshotError
from .source_evidence import RetainedSourceV1, SourceArtifactV1

NEW_YORK_FED_SOFR_SOURCE = "new-york-fed-sofr"
NEW_YORK_FED_SOFR_PROFILE = "new-york-fed-markets-api-sofr-v1"
NEW_YORK_FED_TERMS = "https://www.newyorkfed.org/privacy/termsofuse"
_SOFR_ENDPOINT = "/api/rates/secured/sofr/search.json"


class _Rate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    effectiveDate: date
    type: Literal["SOFR"]
    percentRate: Decimal = Field(ge=0, le=100)
    revisionIndicator: str = Field(max_length=32)


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")

    refRates: tuple[_Rate, ...]


class SofrObservationV1(BaseModel):
    """A reproduced SOFR row; availability is conservatively the capture time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: Literal["new-york-fed-sofr"] = "new-york-fed-sofr"
    source_version: Literal["new-york-fed-markets-api-sofr-v1"] = (
        "new-york-fed-markets-api-sofr-v1"
    )
    terms_reference: Literal["https://www.newyorkfed.org/privacy/termsofuse"] = (
        "https://www.newyorkfed.org/privacy/termsofuse"
    )
    source_uri: str = Field(min_length=1)
    effective_date: date
    percent_rate: Decimal = Field(ge=0, le=100)
    revision_indicator: str = Field(max_length=32)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_at: datetime
    captured_at: datetime


def _unique_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def parse_new_york_fed_sofr(
    raw: bytes,
    *,
    source_uri: str,
    effective_date: date,
    captured_at: datetime,
) -> SofrObservationV1:
    """Reproduce one daily overnight SOFR row without inferring historical availability."""
    try:
        uri = urlsplit(source_uri)
        query = parse_qs(uri.query, keep_blank_values=True, strict_parsing=True)
        requested = effective_date.isoformat()
        if (
            len(raw) > 1024 * 1024
            or captured_at.tzinfo is None
            or captured_at.utcoffset() is None
            or uri.scheme != "https"
            or uri.netloc != "markets.newyorkfed.org"
            or uri.path != _SOFR_ENDPOINT
            or uri.fragment
            or set(query) != {"startDate", "endDate"}
            or any(len(values) != 1 for values in query.values())
            or query["startDate"] != [requested]
            or query["endDate"] != [requested]
            or effective_date
            >= captured_at.astimezone(ZoneInfo("America/New_York")).date()
        ):
            raise ValueError("SOFR capture does not match its source profile")
        payload = json.loads(
            raw,
            parse_float=Decimal,
            object_pairs_hook=_unique_members,
        )
        response = _Response.model_validate(payload)
        matches = tuple(
            row
            for row in response.refRates
            if row.type == "SOFR" and row.effectiveDate == effective_date
        )
        if len(matches) != 1 or len(response.refRates) != 1:
            raise ValueError("SOFR response must contain one requested observation")
        row = matches[0]
        return SofrObservationV1(
            source_uri=source_uri,
            effective_date=effective_date,
            percent_rate=row.percentRate,
            revision_indicator=row.revisionIndicator,
            content_hash=hashlib.sha256(raw).hexdigest(),
            available_at=captured_at,
            captured_at=captured_at,
        )
    except (ValueError, TypeError, UnicodeError, ValidationError) as error:
        raise SnapshotError(
            "SOFR_SOURCE_INVALID",
            "retained New York Fed response does not reproduce the SOFR profile",
        ) from error


class NewYorkFedSofrVintageProvider:
    """Normalize overnight SOFR through the shared macro provider contract."""

    provider_id = "new-york-fed"

    def supports(self, series_id: str) -> bool:
        return series_id == "us.sofr_overnight"

    def reproduce_vintage(
        self, *, series_id: str, sources: tuple[RetainedSourceV1, ...]
    ) -> MacroSeriesVintageV1:
        if not self.supports(series_id) or len(sources) != 1:
            raise SnapshotError(
                "SOFR_SOURCE_INVALID", "SOFR requires one retained source"
            )
        source = sources[0]
        if (
            source.source_id != NEW_YORK_FED_SOFR_SOURCE
            or source.source_version != NEW_YORK_FED_SOFR_PROFILE
            or source.terms_reference != NEW_YORK_FED_TERMS
        ):
            raise SnapshotError(
                "SOFR_SOURCE_INVALID", "SOFR source profile does not match"
            )
        try:
            query = parse_qs(urlsplit(source.uri).query)
            effective_date = date.fromisoformat(query["startDate"][0])
        except (KeyError, ValueError, IndexError) as error:
            raise SnapshotError(
                "SOFR_SOURCE_INVALID", "SOFR source date is invalid"
            ) from error
        observation = parse_new_york_fed_sofr(
            source.content,
            source_uri=source.uri,
            effective_date=effective_date,
            captured_at=source.captured_at,
        )
        return MacroSeriesVintageV1.build(
            series_id="us.sofr_overnight",
            provider_id=self.provider_id,
            frequency="daily",
            unit="percent",
            source_version=NEW_YORK_FED_SOFR_PROFILE,
            available_at=observation.available_at,
            captured_at=source.captured_at,
            artifacts=(
                SourceArtifactV1(
                    source_id=source.source_id,
                    uri=source.uri,
                    source_version=source.source_version,
                    terms_reference=source.terms_reference,
                    content_sha256=observation.content_hash,
                    captured_at=source.captured_at,
                ),
            ),
            observations=(
                MacroObservationV1(
                    series_id="us.sofr_overnight",
                    period_start=effective_date,
                    period_end=effective_date,
                    value=observation.percent_rate,
                    unit="percent",
                    source_sha256=observation.content_hash,
                ),
            ),
        )
