from __future__ import annotations

import re
from datetime import date, datetime

_SEC_SEARCH_URL_TEMPLATE = "https://www.sec.gov/edgar/search/#/entityName={ticker}"
_SEC_ARCHIVES_INDEX_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/"
    "{cik}/{accession_no_dash}/{accession}-index.html"
)
_TEXT_MAX_CHARS = 120_000
_SIGNAL_STALE_WARNING_DAYS = 540
_SIGNAL_STALE_HIGH_RISK_DAYS = 900


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _extract_snippet(text: str, start: int, end: int, radius: int = 70) -> str | None:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = " ".join(text[left:right].split())
    if not snippet:
        return None
    if len(snippet) > 220:
        return snippet[:217] + "..."
    return snippet


def _append_unique_evidence(
    evidence: list[dict[str, object]],
    candidate: dict[str, object],
) -> None:
    snippet_raw = candidate.get("text_snippet")
    if not isinstance(snippet_raw, str) or not snippet_raw:
        return
    if _has_duplicate_evidence(evidence, candidate):
        return
    evidence.append(candidate)


def _has_duplicate_evidence(
    evidence: list[dict[str, object]],
    candidate: dict[str, object],
) -> bool:
    candidate_scope = _evidence_scope(candidate)
    candidate_norm = _normalize_evidence_snippet(candidate.get("text_snippet"))
    if not candidate_norm:
        return False
    for existing in evidence:
        if _evidence_scope(existing) != candidate_scope:
            continue
        existing_norm = _normalize_evidence_snippet(existing.get("text_snippet"))
        if not existing_norm:
            continue
        if candidate_norm == existing_norm:
            return True
        if (
            len(candidate_norm) >= 80
            and len(existing_norm) >= 80
            and (candidate_norm in existing_norm or existing_norm in candidate_norm)
        ):
            return True
    return False


def _evidence_scope(
    candidate: dict[str, object],
) -> tuple[str | None, str | None, str | None]:
    accession_raw = candidate.get("accession_number")
    accession = (
        accession_raw if isinstance(accession_raw, str) and accession_raw else None
    )
    source_url_raw = candidate.get("source_url")
    source_url = (
        source_url_raw if isinstance(source_url_raw, str) and source_url_raw else None
    )
    doc_type_raw = candidate.get("doc_type")
    doc_type = doc_type_raw if isinstance(doc_type_raw, str) and doc_type_raw else None
    return accession, source_url, doc_type


def _normalize_evidence_snippet(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    lowered = re.sub(r"\s+", " ", lowered)
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered).strip()
    return normalized or None


def _filing_age_days(filing_date: str | None) -> int | None:
    if not isinstance(filing_date, str) or not filing_date:
        return None
    try:
        filing_day = date.fromisoformat(filing_date[:10])
    except ValueError:
        return None
    delta_days = (date.today() - filing_day).days
    if delta_days < 0:
        return 0
    return delta_days


def _staleness_confidence_penalty(filing_age_days: int | None) -> float:
    if filing_age_days is None:
        return 0.0
    if filing_age_days > _SIGNAL_STALE_HIGH_RISK_DAYS:
        return 0.10
    if filing_age_days > _SIGNAL_STALE_WARNING_DAYS:
        return 0.05
    return 0.0


def _build_doc_type(form: str, *, used_focus: bool) -> str:
    if used_focus:
        return f"{form}_focused"
    return form


def _build_sec_source_url(
    *,
    ticker: str,
    accession_number: str | None,
    cik: str | None,
) -> str:
    filing_url = _build_sec_filing_index_url(
        accession_number=accession_number,
        cik=cik,
    )
    if filing_url is not None:
        return filing_url
    return _SEC_SEARCH_URL_TEMPLATE.format(ticker=ticker)


def _build_sec_filing_index_url(
    *,
    accession_number: str | None,
    cik: str | None,
) -> str | None:
    normalized_accession = _normalize_accession_number(accession_number)
    if normalized_accession is None:
        return None
    accession_no_dash = normalized_accession.replace("-", "")
    if not accession_no_dash.isdigit():
        return None
    cik_digits = _normalize_cik(cik)
    if cik_digits is None:
        cik_digits = normalized_accession.split("-", maxsplit=1)[0]
    cik_path = cik_digits.lstrip("0")
    if not cik_path:
        return None
    return _SEC_ARCHIVES_INDEX_URL_TEMPLATE.format(
        cik=cik_path,
        accession_no_dash=accession_no_dash,
        accession=normalized_accession,
    )


def _safe_get_filing(filings: object, index: int) -> object | None:
    try:
        getter = getattr(filings, "get", None)
        if callable(getter):
            return getter(index)
    except Exception:
        return None
    return None


def _safe_get_filing_text(filing: object) -> str | None:
    try:
        text_fn = getattr(filing, "text", None)
        if callable(text_fn):
            text = text_fn()
            normalized = _normalize_text(text)
            if normalized:
                return normalized[:_TEXT_MAX_CHARS]
        full_text_fn = getattr(filing, "full_text_submission", None)
        if callable(full_text_fn):
            full_text = full_text_fn()
            normalized_full_text = _normalize_text(full_text)
            if normalized_full_text:
                return normalized_full_text[:_TEXT_MAX_CHARS]
    except Exception:
        return None
    return None


def _normalize_text(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized if normalized else None


def _normalize_accession_number(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    accession_match = re.search(r"(\d{10}-\d{2}-\d{6})", stripped)
    if accession_match is not None:
        return accession_match.group(1)
    digits = re.sub(r"\D", "", stripped)
    if len(digits) != 18:
        return None
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def _normalize_cik(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value < 0:
            return None
        return str(value)
    if isinstance(value, str):
        digits = re.sub(r"\D", "", value)
        if not digits:
            return None
        return digits
    return None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
