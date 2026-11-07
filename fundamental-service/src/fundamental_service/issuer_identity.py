"""Deterministic SEC evidence checks for issuer and security identity."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .contracts import IdentityResolutionRequestV1, IdentityV1

_US_INCORPORATION_STATES = frozenset(
    (
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "DC",
        "AS",
        "GU",
        "MP",
        "PR",
        "VI",
    )
)


class IdentityResolutionError(ValueError):
    """Stable, non-provider-specific failure from SEC identity validation."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _source_invalid() -> IdentityResolutionError:
    return IdentityResolutionError(
        "ISSUER_IDENTITY_SOURCE_INVALID",
        "SEC issuer evidence does not match its required structure",
        status_code=502,
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _source_invalid()
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _source_invalid()
    return " ".join(value.split()).casefold()


def _cik(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _source_invalid()
    raw = str(value)
    if not re.fullmatch(r"\d{1,10}", raw):
        raise _source_invalid()
    return str(int(raw)).zfill(10)


def _has_supported_currency_facts(us_gaap: Mapping[str, object]) -> bool:
    has_usd = False
    for raw_fact in us_gaap.values():
        if not isinstance(raw_fact, Mapping):
            continue
        units = raw_fact.get("units")
        if not isinstance(units, Mapping):
            continue
        for raw_unit, observations in units.items():
            if not isinstance(raw_unit, str) or not isinstance(observations, list):
                continue
            if not observations:
                continue
            if raw_unit == "USD":
                has_usd = True
    return has_usd


def resolve_issuer_cik(
    request: IdentityResolutionRequestV1, *, ticker_directory: object
) -> str:
    """Find one canonical CIK for a ticker before fetching issuer resources."""
    directory = _mapping(ticker_directory)
    matches = [
        record
        for record in directory.values()
        if isinstance(record, Mapping)
        and isinstance(record.get("ticker"), str)
        and record["ticker"].strip().upper() == request.ticker
    ]
    if not matches:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_UNRESOLVED",
            "the selected ticker is not present in SEC issuer evidence",
            status_code=404,
        )
    if len(matches) != 1:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_AMBIGUOUS",
            "SEC issuer evidence maps the selected ticker more than once",
            status_code=409,
        )
    return _cik(matches[0].get("cik_str"))


def resolve_issuer_identity(
    request: IdentityResolutionRequestV1,
    *,
    ticker_directory: object,
    submissions: object,
    companyfacts: object,
) -> IdentityV1:
    """Resolve a selected SEC ticker only when all required evidence agrees."""
    directory = _mapping(ticker_directory)
    cik = resolve_issuer_cik(request, ticker_directory=directory)
    ticker_record = next(
        record
        for record in directory.values()
        if isinstance(record, Mapping)
        and isinstance(record.get("ticker"), str)
        and record["ticker"].strip().upper() == request.ticker
    )
    issuer_name = _name(ticker_record.get("title"))

    issuer = _mapping(submissions)
    if _cik(issuer.get("cik")) != cik:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_MISMATCH",
            "SEC submissions CIK does not match the ticker directory",
            status_code=422,
        )
    tickers = issuer.get("tickers")
    if not isinstance(tickers, list) or not all(
        isinstance(item, str) for item in tickers
    ):
        raise _source_invalid()
    if request.ticker not in {item.strip().upper() for item in tickers}:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_MISMATCH",
            "SEC submissions do not associate the selected ticker with this issuer",
            status_code=422,
        )
    if _name(issuer.get("name")) != issuer_name:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_MISMATCH",
            "SEC issuer names do not match across the ticker directory and submissions",
            status_code=422,
        )

    state = issuer.get("stateOfIncorporation")
    if not isinstance(state, str) or state.strip().upper() not in (
        _US_INCORPORATION_STATES
    ):
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_UNSUPPORTED",
            "SEC evidence does not establish a supported US domicile",
            status_code=422,
        )
    filings = _mapping(issuer.get("filings"))
    recent = _mapping(filings.get("recent"))
    forms = recent.get("form")
    if not isinstance(forms, list) or not all(isinstance(item, str) for item in forms):
        raise _source_invalid()
    if "10-K" not in forms:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_UNSUPPORTED",
            "SEC evidence does not establish a supported domestic filing profile",
            status_code=422,
        )

    facts = _mapping(companyfacts)
    if _cik(facts.get("cik")) != cik:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_MISMATCH",
            "SEC companyfacts CIK does not match the ticker directory",
            status_code=422,
        )
    if _name(facts.get("entityName")) != issuer_name:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_MISMATCH",
            "SEC companyfacts issuer name does not match the ticker directory",
            status_code=422,
        )
    fact_namespaces = _mapping(facts.get("facts"))
    us_gaap = fact_namespaces.get("us-gaap")
    if not isinstance(us_gaap, Mapping) or not us_gaap:
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_UNSUPPORTED",
            "SEC companyfacts does not establish US-GAAP reporting",
            status_code=422,
        )
    if not _has_supported_currency_facts(us_gaap):
        raise IdentityResolutionError(
            "ISSUER_IDENTITY_UNSUPPORTED",
            "SEC companyfacts does not establish USD reporting",
            status_code=422,
        )

    return IdentityV1(
        issuer_id=cik,
        issuer_name=str(ticker_record["title"]).strip(),
        domicile="US",
        reporting_basis="us-gaap",
        # The SEC ticker is used as an opaque series key. No share-class label
        # is inferred from the selected symbol.
        security_id=request.ticker,
        share_class=request.ticker,
        currency="USD",
    )
