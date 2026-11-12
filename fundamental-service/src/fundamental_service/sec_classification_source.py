"""Bounded SEC submission-header adapter; current company metadata is excluded."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .issuer_classification import (
    IssuerClassificationAttributeV1,
    IssuerClassificationObservationV1,
)
from .snapshots import SnapshotError
from .source_evidence import RetainedSourceV1, SourceArtifactV1

SEC_CLASSIFICATION_SOURCE = "sec-complete-submission"
SEC_CLASSIFICATION_PROFILE = "sec-submission-header-classification-v1"
SEC_CLASSIFICATION_TERMS = "https://www.sec.gov/os/accessing-edgar-data"
_NEW_YORK = ZoneInfo("America/New_York")
_MAX_HEADER_BYTES = 256 * 1024


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("SEC_CLASSIFICATION_HEADER_INVALID", message)


def _field(text: str, label: str, *, optional: bool = False) -> str | None:
    matches = re.findall(r"(?m)^\s*" + re.escape(label) + r":[ \t]*([^\r\n]*)$", text)
    if optional and not matches:
        return None
    if len(matches) != 1 or not matches[0].strip():
        raise _invalid("SEC classification header has missing or repeated " + label)
    return matches[0].strip()


def _day(value: str | None) -> date:
    if value is None or not re.fullmatch(r"[0-9]{8}", value):
        raise _invalid("SEC classification header date is invalid")
    return datetime.strptime(value, "%Y%m%d").date()


class SecSubmissionClassificationProvider:
    """Transcribe the sole original annual filer's classifications and dates."""

    provider_id = "sec-submission-header"

    def reproduce_classification(
        self, *, sources: tuple[RetainedSourceV1, ...]
    ) -> IssuerClassificationObservationV1:
        if len(sources) != 1:
            raise _invalid("SEC classification requires one complete submission")
        source = sources[0]
        if (
            source.source_id != SEC_CLASSIFICATION_SOURCE
            or source.source_version != SEC_CLASSIFICATION_PROFILE
            or source.terms_reference != SEC_CLASSIFICATION_TERMS
            or not 1 <= len(source.content) <= 64 * 1024 * 1024
        ):
            raise _invalid("SEC classification source profile or size is invalid")
        prefix = source.content[:_MAX_HEADER_BYTES].decode("latin-1")
        match = re.match(
            r"<SEC-DOCUMENT>([0-9]{10}-[0-9]{2}-[0-9]{6})\.txt : ([0-9]{8})\r?\n"
            r"<SEC-HEADER>\1\.hdr\.sgml : ([0-9]{8})\r?\n"
            r"(.*?)</SEC-HEADER>\s*<DOCUMENT>",
            prefix,
            re.DOTALL,
        )
        if match is None:
            raise _invalid("SEC classification requires a complete bounded header")
        header = match[4]
        if (
            header.count("<ACCEPTANCE-DATETIME>") != 1
            or len(re.findall(r"(?m)^FILER:[ \t]*$", header)) != 1
        ):
            raise _invalid("SEC classification requires one unambiguous filer")
        if re.search(r"(?m)^(?:SUBJECT COMPANY|FILED BY|REPORTING-OWNER):", header):
            raise _invalid("SEC classification does not support multi-party headers")
        accession = _field(header, "ACCESSION NUMBER")
        cik = _field(header, "CENTRAL INDEX KEY")
        if (
            accession != match[1]
            or cik is None
            or not re.fullmatch(r"[0-9]{1,10}", cik)
        ):
            raise _invalid("SEC classification accession or CIK is invalid")
        expected_uri = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{accession}.txt"
        )
        if source.uri != expected_uri:
            raise _invalid("SEC classification URI differs from the exact original")
        acceptance = re.findall(r"(?m)^<ACCEPTANCE-DATETIME>([0-9]{14})\r?$", header)
        if len(acceptance) != 1:
            raise _invalid("SEC classification acceptance timestamp is invalid")
        local = datetime.strptime(acceptance[0], "%Y%m%d%H%M%S")
        accepted = local.replace(tzinfo=_NEW_YORK)
        if (
            accepted.utcoffset() != accepted.replace(fold=1).utcoffset()
            or accepted.astimezone(UTC).astimezone(_NEW_YORK).replace(tzinfo=None)
            != local
        ):
            raise _invalid("SEC classification acceptance time is not unambiguous")
        filed = _day(_field(header, "FILED AS OF DATE"))
        changed = _day(_field(header, "DATE AS OF CHANGE"))
        if (
            _day(match[2]) != changed
            or _day(match[3]) != changed
            or not accepted.date() <= filed <= changed
        ):
            raise _invalid("SEC classification publication dates conflict")
        available = max(accepted, datetime.combine(filed, time.min, _NEW_YORK))
        if changed > accepted.date():
            # A corrected header cannot be claimed to exist at original acceptance.
            available = max(
                available,
                datetime.combine(changed + timedelta(days=1), time.min, _NEW_YORK),
            )
        form = _field(header, "CONFORMED SUBMISSION TYPE")
        if form not in {"10-K", "10-K/A"} or _field(header, "FORM TYPE") != form:
            raise _invalid("SEC classification requires an original annual form")
        source_hash = hashlib.sha256(source.content).hexdigest()
        attributes = []
        for role, label, scheme in (
            (
                "incorporation_jurisdiction",
                "STATE OF INCORPORATION",
                "sec-state-country-v1",
            ),
            ("industry_code", "STANDARD INDUSTRIAL CLASSIFICATION", "sec-sic-v1"),
        ):
            value = _field(header, label, optional=True)
            if value is None:
                continue
            source_value = value
            if role == "industry_code":
                sic = re.fullmatch(r"[^\r\n\[\]]+ \[([0-9]{4})\]", value)
                if sic is None:
                    raise _invalid("SEC classification SIC format is invalid")
                value = sic[1]
            elif re.fullmatch(r"[A-Z0-9]{2}", value) is None:
                raise _invalid("SEC classification jurisdiction format is invalid")
            attributes.append(
                IssuerClassificationAttributeV1.model_validate(
                    {
                        "role": role,
                        "scheme": scheme,
                        "value": value,
                        "source_value": source_value,
                        "locator": "SEC-HEADER/FILER/COMPANY DATA/" + label,
                        "source_sha256": source_hash,
                    }
                )
            )
        return IssuerClassificationObservationV1.build(
            provider_id=self.provider_id,
            source_version=SEC_CLASSIFICATION_PROFILE,
            issuer_id=cik.zfill(10),
            accession_number=accession,
            form=form,
            report_period_end=_day(_field(header, "CONFORMED PERIOD OF REPORT")),
            accepted_at=accepted.astimezone(UTC),
            available_at=available.astimezone(UTC),
            captured_at=source.captured_at,
            artifacts=(
                SourceArtifactV1(
                    source_id=source.source_id,
                    uri=source.uri,
                    source_version=source.source_version,
                    terms_reference=source.terms_reference,
                    content_sha256=source_hash,
                    captured_at=source.captured_at,
                ),
            ),
            attributes=tuple(sorted(attributes, key=lambda x: x.role)),
        )
