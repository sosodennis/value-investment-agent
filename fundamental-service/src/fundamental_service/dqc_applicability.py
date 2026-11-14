"""Apply official DQC assertion dates to an original's SEC filing date."""

import hashlib
import json
import re
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .serialization import sha256_digest

_CATALOG_PATH = Path(__file__).with_name("resources") / "dqc-v31-effective-dates.json"
_CATALOG_SHA256 = "47c60da21ed6f7503e6965f6b7eb37cd5419c57192d892dad798a573cecff269"
_OFFICIAL_COMMIT = "cd82706519e384fb209d74f13ccbe535be42da4b"


def dqc_applicability_policy_digest() -> str:
    return sha256_digest(
        {
            "protocol": "dqc-sec-filing-date-applicability-v1",
            "dqc_version": "v31.0.3",
            "document_catalog_sha256": _CATALOG_SHA256,
            "fallback": "exact-final-assertion-document-only",
            "unknown_or_conflicting_dates": "retain-blocking",
            "critical_or_fatal": "retain-blocking",
        }
    )


class DqcFilingContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["dqc-sec-filing-date-applicability-v1"] = (
        "dqc-sec-filing-date-applicability-v1"
    )
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    filing_date: date
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def pinned_policy(self) -> "DqcFilingContextV1":
        if self.policy_digest != dqc_applicability_policy_digest():
            raise ValueError("DQC filing-date context requires the pinned policy")
        return self

    def evidence_marker(self) -> str:
        return self.protocol + ":" + sha256_digest(self)


class DqcRuleApplicabilityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["active", "future", "unknown", "conflict"]
    filing_date: date
    effective_date: date | None
    date_source: Literal[
        "official-xule", "official-rule-document", "unavailable", "conflict"
    ]
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@cache
def _document_dates() -> dict[str, tuple[date, str]]:
    raw = _CATALOG_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _CATALOG_SHA256:
        raise ValueError("official DQC date catalog hash does not match")
    catalog = json.loads(raw)
    if (
        catalog["official_commit"] != _OFFICIAL_COMMIT
        or catalog["dqc_version"] != "v31.0.3"
        or catalog["protocol"] != "dqc-official-assertion-effective-dates-v1"
    ):
        raise ValueError("official DQC date catalog identity does not match")
    result = {}
    for entry in catalog["entries"]:
        for code in entry["assertion_codes"]:
            if code in result or not re.fullmatch(r"DQC\.US\.[0-9]{4}\.[0-9]+", code):
                raise ValueError(
                    "official DQC date catalog repeats or misidentifies an assertion"
                )
            result[code] = (
                date.fromisoformat(entry["effective_date"]),
                entry["document_sha256"],
            )
    return result


def evaluate_dqc_applicability(
    *, code: str, emitted_date: date | None, context: DqcFilingContextV1
) -> DqcRuleApplicabilityV1 | None:
    if not re.fullmatch(r"DQC\.US\.[0-9]{4}\.[0-9]+", code):
        return None
    document = _document_dates().get(code)
    document_date, document_hash = document if document else (None, None)
    conflict = (
        emitted_date is not None
        and document_date is not None
        and emitted_date != document_date
    )
    selected = None if conflict else emitted_date or document_date
    status: Literal["active", "future", "unknown", "conflict"]
    source: Literal[
        "official-xule", "official-rule-document", "unavailable", "conflict"
    ]
    if conflict:
        status, source = "conflict", "conflict"
    elif selected is None:
        status, source = "unknown", "unavailable"
    else:
        status = "future" if context.filing_date < selected else "active"
        source = (
            "official-xule" if emitted_date is not None else "official-rule-document"
        )
    return DqcRuleApplicabilityV1(
        status=status,
        filing_date=context.filing_date,
        effective_date=selected,
        date_source=source,
        document_sha256=document_hash,
    )
