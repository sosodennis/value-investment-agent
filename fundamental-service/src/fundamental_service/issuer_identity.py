"""Deterministic SEC evidence checks for issuer and security identity."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING

from .contracts import IdentityResolutionRequestV1, IdentityV1

if TYPE_CHECKING:
    from .arelle_parser import ParsedXbrlFactV1

ORIGINAL_IDENTITY_CONCEPTS = frozenset(
    {
        "dei:EntityCentralIndexKey",
        "dei:EntityRegistrantName",
        "dei:EntityIncorporationStateCountryCode",
        "dei:DocumentType",
        "dei:DocumentPeriodEndDate",
        "dei:TradingSymbol",
        "dei:Security12bTitle",
    }
)
_DEI_NAMESPACE = re.compile(r"http://xbrl\.(?:sec\.gov|us)/dei/\d{4}(?:-\d{2}-\d{2})?")
_GAAP_NAMESPACE = re.compile(
    r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?"
)

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


def validate_original_filing_identity(
    identity: IdentityV1,
    *,
    cik: str,
    ticker: str,
    accepted_at: datetime,
    facts: tuple[ParsedXbrlFactV1, ...],
) -> None:
    """Bind one security to its original DEI class, without current directories."""

    def refuse(code: str, message: str) -> IdentityResolutionError:
        return IdentityResolutionError(code, message, status_code=422)

    if (
        len(cik) != 10
        or not cik.isascii()
        or not cik.isdigit()
        or accepted_at.tzinfo is None
        or accepted_at.utcoffset() is None
    ):
        raise refuse(
            "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
            "invalid original CIK or acceptance",
        )

    security_concepts = {"dei:TradingSymbol", "dei:Security12bTitle"}
    symbols = tuple(fact for fact in facts if fact.concept == "dei:TradingSymbol")
    if not symbols:
        raise refuse(
            "HISTORICAL_IDENTITY_MISSING", "original filing lacks dei:TradingSymbol"
        )
    matching_symbols = tuple(fact for fact in symbols if fact.value.strip() == ticker)
    if not matching_symbols:
        raise refuse(
            "HISTORICAL_IDENTITY_MISMATCH",
            "requested ticker differs from the original filing",
        )
    security_contexts = {
        (fact.context_id, fact.period_start, fact.period_end, fact.dimensions)
        for fact in matching_symbols
    }
    ticker_contexts = security_contexts
    if len(security_contexts) > 1:
        titles_by_context = {
            context: {
                _name(fact.value)
                for fact in facts
                if fact.concept == "dei:Security12bTitle"
                and (
                    fact.context_id,
                    fact.period_start,
                    fact.period_end,
                    fact.dimensions,
                )
                == context
            }
            for context in security_contexts
        }
        if any(
            len(titles) != 1 or not next(iter(titles))
            for titles in titles_by_context.values()
        ):
            raise refuse(
                "HISTORICAL_IDENTITY_CONFLICT",
                "reused ticker requires one paired title in every security context",
            )
        security_contexts = {
            context
            for context, titles in titles_by_context.items()
            if titles == {_name(identity.share_class)}
        }
    if len(security_contexts) != 1:
        raise refuse(
            "HISTORICAL_IDENTITY_CONFLICT",
            "requested ticker belongs to multiple original security contexts",
        )
    security_context = next(iter(security_contexts))

    values: dict[str, str] = {}
    periods: set[date | None] = set()
    for concept in sorted(ORIGINAL_IDENTITY_CONCEPTS):
        candidates = tuple(
            fact
            for fact in facts
            if fact.concept == concept
            and (
                concept not in security_concepts
                or (
                    fact.context_id,
                    fact.period_start,
                    fact.period_end,
                    fact.dimensions,
                )
                == security_context
            )
        )
        if not candidates:
            raise refuse(
                "HISTORICAL_IDENTITY_MISSING", f"original filing lacks {concept}"
            )
        scope_candidates = (
            tuple(
                fact
                for fact in facts
                if fact.concept == concept
                and (
                    fact.context_id,
                    fact.period_start,
                    fact.period_end,
                    fact.dimensions,
                )
                in ticker_contexts
            )
            if concept in security_concepts
            else candidates
        )
        if any(
            not _DEI_NAMESPACE.fullmatch(fact.namespace_uri or "")
            or fact.entity_scheme != "http://www.sec.gov/CIK"
            or not (fact.entity_identifier or "").isascii()
            or not (fact.entity_identifier or "").isdigit()
            or int(fact.entity_identifier or "0") != int(cik)
            or (
                fact.dimensions
                and not (
                    concept in security_concepts
                    and len(fact.dimensions) == 1
                    and fact.dimensions[0][0] == "us-gaap:StatementClassOfStockAxis"
                    and fact.dimensions[0][1]
                )
            )
            or fact.unit is not None
            or fact.is_numeric
            or fact.instant is not None
            or fact.period_start is None
            or fact.period_end is None
            or fact.period_start > fact.period_end
            for fact in scope_candidates
        ):
            raise refuse(
                "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
                f"original {concept} lacks a supported issuer or security DEI context",
            )
        unique = {" ".join(fact.value.split()) for fact in candidates}
        if len(unique) != 1 or not next(iter(unique)):
            raise refuse(
                "HISTORICAL_IDENTITY_CONFLICT", f"original {concept} conflicts"
            )
        values[concept] = next(iter(unique))
        periods.update(fact.period_end for fact in scope_candidates)
    try:
        report_end = date.fromisoformat(values["dei:DocumentPeriodEndDate"])
    except ValueError as error:
        raise refuse(
            "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED", "invalid original report date"
        ) from error
    if (
        periods != {report_end}
        or report_end > accepted_at.date()
        or values["dei:DocumentType"] != "10-K"
    ):
        raise refuse(
            "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
            "original identity does not belong to the selected annual report period",
        )
    original_cik = values["dei:EntityCentralIndexKey"]
    if (
        not original_cik.isascii()
        or not original_cik.isdigit()
        or int(original_cik) != int(cik)
        or not identity.issuer_id.isascii()
        or not identity.issuer_id.isdigit()
        or int(identity.issuer_id) != int(cik)
        or _name(values["dei:EntityRegistrantName"]) != _name(identity.issuer_name)
        or values["dei:TradingSymbol"] != ticker
        or identity.security_id != ticker
        or _name(identity.share_class) != _name(values["dei:Security12bTitle"])
    ):
        raise refuse(
            "HISTORICAL_IDENTITY_MISMATCH",
            "requested issuer or security differs from the original filing",
        )
    monetary_units = {
        fact.unit
        for fact in facts
        if _GAAP_NAMESPACE.fullmatch(fact.namespace_uri or "")
        and fact.is_numeric
        and fact.unit is not None
        and re.fullmatch(r"iso4217:[A-Z]{3}", fact.unit)
        and not fact.dimensions
        and fact.consolidation_scope == "consolidated"
        and (fact.period_end == report_end or fact.instant == report_end)
        and (fact.entity_identifier or "").isascii()
        and (fact.entity_identifier or "").isdigit()
        and int(fact.entity_identifier or "0") == int(cik)
        and fact.entity_scheme == "http://www.sec.gov/CIK"
    }
    if (
        values["dei:EntityIncorporationStateCountryCode"]
        not in _US_INCORPORATION_STATES
        or identity.domicile != "US"
        or identity.reporting_basis != "us-gaap"
        or identity.currency != "USD"
        or monetary_units != {"iso4217:USD"}
    ):
        raise refuse(
            "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
            "original filing does not establish the supported domestic USD GAAP scope",
        )


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
