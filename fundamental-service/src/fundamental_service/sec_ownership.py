"""Source-only SEC ownership observations; no award classification or valuation."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from lxml import etree
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .serialization import sha256_digest
from .snapshots import ContentAddressedStore, SnapshotError

OWNERSHIP_PROFILE: Literal["sec-ownership-observations-v1"] = (
    "sec-ownership-observations-v1"
)
OwnershipForm = Literal["3", "3/A", "4", "4/A", "5", "5/A"]
_NEW_YORK = ZoneInfo("America/New_York")
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_XML_BYTES = 8 * 1024 * 1024


class OwnershipModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SecOwnershipSourceV1(OwnershipModel):
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    form: OwnershipForm
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_at: AwareDatetime
    filing_date: date
    captured_at: AwareDatetime

    @field_validator("accepted_at", "captured_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class SecOwnershipRequestV1(OwnershipModel):
    protocol: Literal["sec-ownership-observations-v1"] = OWNERSHIP_PROFILE
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    valuation_at: AwareDatetime
    sources: tuple[SecOwnershipSourceV1, ...] = Field(min_length=1, max_length=1000)

    @field_validator("valuation_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def fixed_source_set(self) -> SecOwnershipRequestV1:
        if self.sources != tuple(
            sorted(self.sources, key=lambda x: (x.accepted_at, x.accession_number))
        ) or len({x.accession_number for x in self.sources}) != len(self.sources):
            raise ValueError("ownership source manifest must be ordered and distinct")
        return self


class OwnershipFieldV1(OwnershipModel):
    """Verbatim XML leaf, including empty values, codes and footnote references."""

    locator: str
    text: str | None
    attributes: tuple[tuple[str, str], ...]


class OwnershipRowV1(OwnershipModel):
    kind: Literal[
        "derivativeTransaction",
        "derivativeHolding",
        "nonDerivativeTransaction",
        "nonDerivativeHolding",
    ]
    locator: str
    fields: tuple[OwnershipFieldV1, ...]


class OwnershipOwnerV1(OwnershipModel):
    cik: str
    fields: tuple[OwnershipFieldV1, ...]


class OwnershipFootnoteV1(OwnershipModel):
    footnote_id: str
    locator: str
    text: str


class SecOwnershipObservationV1(OwnershipModel):
    issuer_id: str
    accession_number: str
    form: OwnershipForm
    source_uri: str
    source_sha256: str
    document_sha256: str
    period_of_report: date
    accepted_at: AwareDatetime
    available_at: AwareDatetime
    filing_date: date
    changed_date: date
    captured_at: AwareDatetime
    owners: tuple[OwnershipOwnerV1, ...]
    document_fields: tuple[OwnershipFieldV1, ...]
    rows: tuple[OwnershipRowV1, ...]
    footnotes: tuple[OwnershipFootnoteV1, ...]
    issue_codes: tuple[str, ...]
    complete_inventory: Literal[False] = False


class SecOwnershipResultV1(OwnershipModel):
    source: SecOwnershipSourceV1
    status: Literal["parsed", "refused"]
    observation: SecOwnershipObservationV1 | None
    issue_codes: tuple[str, ...]

    @model_validator(mode="after")
    def consistent_outcome(self) -> SecOwnershipResultV1:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("ownership issue codes must be canonical")
        observation = self.observation
        if self.status == "refused":
            if observation is not None or not self.issue_codes:
                raise ValueError(
                    "ownership refusal requires reasons and no observation"
                )
        elif (
            observation is None
            or observation.issue_codes != self.issue_codes
            or observation.accession_number != self.source.accession_number
            or observation.form != self.source.form
            or observation.source_sha256 != self.source.content_sha256
        ):
            raise ValueError("ownership observation must bind its exact source")
        return self


class SecOwnershipEvidenceV1(OwnershipModel):
    request: SecOwnershipRequestV1
    input_digest: str
    results: tuple[SecOwnershipResultV1, ...]
    output_digest: str
    complete_inventory: Literal[False] = False
    mapping_approved: Literal[False] = False
    supported_history_threshold: None = None

    @model_validator(mode="after")
    def complete_and_reproducible_results(self) -> SecOwnershipEvidenceV1:
        if (
            tuple(result.source for result in self.results) != self.request.sources
            or self.input_digest != sha256_digest(self.request)
            or self.output_digest != sha256_digest(self.results)
        ):
            raise ValueError(
                "ownership evidence must retain every source and both digests"
            )
        return self


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("SEC_OWNERSHIP_SOURCE_INVALID", message)


def _one(text: str, label: str) -> str:
    matches = re.findall(r"(?m)^\s*" + re.escape(label) + r":[ \t]*([^\r\n]*)$", text)
    if len(matches) != 1 or not matches[0].strip():
        raise _invalid("ownership header has missing or repeated " + label)
    return matches[0].strip()


def _cik(value: str) -> str:
    if not re.fullmatch(r"[0-9]{1,10}", value):
        raise _invalid("ownership CIK is invalid")
    return value.zfill(10)


def _xml_text(root: etree._Element, path: str) -> str:
    nodes = root.findall(path)
    if len(nodes) != 1 or nodes[0].text is None or len(nodes[0]):
        raise _invalid("ownership XML has missing or repeated " + path)
    return nodes[0].text.strip()


def _fields(root: etree._Element) -> tuple[OwnershipFieldV1, ...]:
    tree = root.getroottree()
    return tuple(
        OwnershipFieldV1(
            locator=tree.getpath(node),
            text=node.text,
            attributes=tuple(sorted(node.attrib.items())),
        )
        for node in root.iter()
        if isinstance(node.tag, str) and not len(node)
    )


def _header(
    raw: bytes, source: SecOwnershipSourceV1, issuer_id: str
) -> tuple[date, date, date, datetime, datetime, tuple[str, ...]]:
    prefix = raw[: 256 * 1024].decode("latin-1")
    match = re.match(
        r"<SEC-DOCUMENT>([0-9]{10}-[0-9]{2}-[0-9]{6})\.txt : ([0-9]{8})\r?\n"
        r"<SEC-HEADER>\1\.hdr\.sgml : ([0-9]{8})\r?\n"
        r"(.*?)</SEC-HEADER>\s*<DOCUMENT>",
        prefix,
        re.DOTALL,
    )
    if match is None:
        raise _invalid("ownership requires a complete bounded SEC header")
    header = match[4]
    if (
        match[1] != source.accession_number
        or _one(header, "ACCESSION NUMBER") != source.accession_number
        or _one(header, "CONFORMED SUBMISSION TYPE") != source.form
    ):
        raise _invalid("ownership accession or form differs from the source manifest")
    sections = re.split(r"(?m)^(?=[A-Z][A-Z- ]*:)", header)
    issuers = [s for s in sections if s.startswith("ISSUER:")]
    owners = [s for s in sections if s.startswith("REPORTING-OWNER:")]
    if len(issuers) != 1 or not owners:
        raise _invalid("ownership requires one issuer and explicit reporting owners")
    if _cik(_one(issuers[0], "CENTRAL INDEX KEY")) != issuer_id:
        raise _invalid("ownership header belongs to a different issuer")
    owner_ciks = tuple(_cik(_one(s, "CENTRAL INDEX KEY")) for s in owners)
    if len(set(owner_ciks)) != len(owner_ciks):
        raise _invalid("ownership header repeats a reporting owner")
    acceptance = re.findall(r"(?m)^<ACCEPTANCE-DATETIME>([0-9]{14})\r?$", header)
    if len(acceptance) != 1:
        raise _invalid("ownership acceptance time is missing or ambiguous")
    try:
        local = datetime.strptime(acceptance[0], "%Y%m%d%H%M%S")
        accepted = local.replace(tzinfo=_NEW_YORK)
        filed = datetime.strptime(_one(header, "FILED AS OF DATE"), "%Y%m%d").date()
        changed = datetime.strptime(_one(header, "DATE AS OF CHANGE"), "%Y%m%d").date()
        period = datetime.strptime(
            _one(header, "CONFORMED PERIOD OF REPORT"), "%Y%m%d"
        ).date()
    except ValueError as error:
        raise _invalid("ownership header dates are invalid") from error
    if (
        accepted.utcoffset() != accepted.replace(fold=1).utcoffset()
        or accepted.astimezone(UTC).astimezone(_NEW_YORK).replace(tzinfo=None) != local
        or accepted.astimezone(UTC) != source.accepted_at
        or source.filing_date != filed
        or not period <= accepted.date() <= filed <= changed
        or match[2] != changed.strftime("%Y%m%d")
        or match[3] != changed.strftime("%Y%m%d")
    ):
        raise _invalid("ownership header dates conflict with their source binding")
    available = max(accepted, datetime.combine(filed, time.min, _NEW_YORK))
    if changed > accepted.date():
        available = max(
            available,
            datetime.combine(changed + timedelta(days=1), time.min, _NEW_YORK),
        )
    return (
        period,
        filed,
        changed,
        accepted.astimezone(UTC),
        available.astimezone(UTC),
        owner_ciks,
    )


def _document(raw: bytes, form: OwnershipForm) -> tuple[bytes, etree._Element]:
    documents = re.findall(rb"(?ms)^<DOCUMENT>\s*\n(.*?)^</DOCUMENT>\s*$", raw)
    if (
        not re.search(rb"(?m)^</SEC-DOCUMENT>\s*\Z", raw)
        or not documents
        or len(documents) > 128
        or len(documents) != len(re.findall(rb"(?m)^<DOCUMENT>[ \t]*\r?$", raw))
        or len(documents) != len(re.findall(rb"(?m)^</DOCUMENT>[ \t]*\r?$", raw))
    ):
        raise _invalid("ownership submission has incomplete or excessive documents")
    matches = []
    for document in documents:
        types = re.findall(rb"(?m)^<TYPE>([^\r\n]+)\r?$", document)
        if len(types) != 1:
            raise _invalid("ownership document type is missing or repeated")
        if types[0].strip() != form.encode():
            if b"<ownershipDocument" in document:
                raise _invalid(
                    "ownership XML is attached to a conflicting document type"
                )
            continue
        xml = re.findall(rb"(?ms)^<XML>[ \t]*\r?\n(.*?)^</XML>[ \t]*\r?$", document)
        if len(xml) != 1 or not 1 <= len(xml[0]) <= _MAX_XML_BYTES:
            raise _invalid("ownership requires one bounded XML payload")
        matches.append(xml[0])
    if len(matches) != 1:
        raise _invalid("ownership primary XML document is missing or ambiguous")
    xml = matches[0]
    try:
        root = etree.fromstring(
            xml,
            etree.XMLParser(
                resolve_entities=False,
                load_dtd=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                recover=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError as error:
        raise _invalid("ownership XML is malformed") from error
    if (
        root.tag != "ownershipDocument"
        or root.getroottree().docinfo.doctype
        or any(not isinstance(n.tag, str) or "{" in n.tag for n in root.iter())
    ):
        raise _invalid(
            "ownership XML root, DTD, entities or extensions are unsupported"
        )
    return xml, root


def parse_sec_ownership_source(
    raw: bytes, *, issuer_id: str, valuation_at: datetime, source: SecOwnershipSourceV1
) -> SecOwnershipObservationV1:
    """Transcribe one exact original without treating transactions as grants."""
    if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
        raise _invalid("ownership valuation time requires a timezone")
    if not re.fullmatch(r"[0-9]{10}", issuer_id):
        raise _invalid("ownership issuer must use its canonical CIK")
    if (
        not 1 <= len(raw) <= _MAX_SOURCE_BYTES
        or hashlib.sha256(raw).hexdigest() != source.content_sha256
    ):
        raise _invalid("ownership original size or source digest differs")
    period, filed, changed, accepted, available, owner_ciks = _header(
        raw, source, issuer_id
    )
    if available > valuation_at:
        raise SnapshotError(
            "SEC_OWNERSHIP_NOT_AVAILABLE",
            "ownership source was not available at the decision",
        )
    if available > source.captured_at:
        raise _invalid("ownership original was captured before its availability")
    xml, root = _document(raw, source.form)
    if (
        _cik(_xml_text(root, "issuer/issuerCik")) != issuer_id
        or _xml_text(root, "documentType") != source.form
    ):
        raise _invalid("ownership XML issuer or form differs from its header")
    try:
        xml_period = date.fromisoformat(_xml_text(root, "periodOfReport"))
    except ValueError as error:
        raise _invalid("ownership report period is invalid") from error
    if xml_period != period:
        raise _invalid("ownership XML period differs from its header")
    tree = root.getroottree()
    owners = tuple(
        OwnershipOwnerV1(
            cik=_cik(_xml_text(node, "reportingOwnerId/rptOwnerCik")),
            fields=_fields(node),
        )
        for node in root.findall("reportingOwner")
    )
    if sorted(o.cik for o in owners) != sorted(owner_ciks):
        raise _invalid("ownership XML owners differ from its header")
    footnotes = tuple(
        OwnershipFootnoteV1(
            footnote_id=node.get("id", ""),
            locator=tree.getpath(node),
            text="".join(node.itertext()),
        )
        for node in root.findall("footnotes/footnote")
    )
    note_ids = {note.footnote_id for note in footnotes}
    if (
        "" in note_ids
        or len(note_ids) != len(footnotes)
        or any(node.get("id") not in note_ids for node in root.findall(".//footnoteId"))
    ):
        raise _invalid("ownership footnotes are duplicate, missing or dangling")
    rows = []
    for table, kinds in (
        ("derivativeTable", ("derivativeTransaction", "derivativeHolding")),
        ("nonDerivativeTable", ("nonDerivativeTransaction", "nonDerivativeHolding")),
    ):
        if len(root.findall(table)) > 1:
            raise _invalid("ownership XML repeats a security table")
        for node in root.findall(table + "/*"):
            if node.tag not in kinds:
                raise _invalid("ownership table contains an unsupported row")
            rows.append(
                OwnershipRowV1.model_validate(
                    {
                        "kind": node.tag,
                        "locator": tree.getpath(node),
                        "fields": _fields(node),
                    }
                )
            )
    issues = []
    if not any(row.kind.startswith("derivative") for row in rows):
        issues.append("SEC_OWNERSHIP_NO_DERIVATIVE_ROWS")
    if source.form.endswith("/A"):
        issues.append("SEC_OWNERSHIP_AMENDMENT_REQUIRES_RECONCILIATION")
    return SecOwnershipObservationV1(
        issuer_id=issuer_id,
        accession_number=source.accession_number,
        form=source.form,
        source_uri=f"https://www.sec.gov/Archives/edgar/data/{int(issuer_id)}/{source.accession_number.replace('-', '')}/{source.accession_number}.txt",
        source_sha256=source.content_sha256,
        document_sha256=hashlib.sha256(xml).hexdigest(),
        period_of_report=period,
        accepted_at=accepted,
        available_at=available,
        filing_date=filed,
        changed_date=changed,
        captured_at=source.captured_at,
        owners=owners,
        document_fields=tuple(
            field
            for child in root
            if child.tag
            not in {
                "derivativeTable",
                "nonDerivativeTable",
                "reportingOwner",
                "footnotes",
            }
            for field in _fields(child)
        ),
        rows=tuple(rows),
        footnotes=footnotes,
        issue_codes=tuple(sorted(issues)),
    )


def inspect_sec_ownership_sources(
    request: SecOwnershipRequestV1, *, content: ContentAddressedStore
) -> SecOwnershipEvidenceV1:
    """Retain every manifest entry, including unavailable bytes and parser refusals."""
    results = []
    for source in request.sources:
        try:
            raw = content.get(source.content_sha256, media_type="text/plain")
            observation = parse_sec_ownership_source(
                raw,
                issuer_id=request.issuer_id,
                valuation_at=request.valuation_at,
                source=source,
            )
        except SnapshotError as error:
            results.append(
                SecOwnershipResultV1(
                    source=source,
                    status="refused",
                    observation=None,
                    issue_codes=(error.code,),
                )
            )
        else:
            results.append(
                SecOwnershipResultV1(
                    source=source,
                    status="parsed",
                    observation=observation,
                    issue_codes=observation.issue_codes,
                )
            )
    return SecOwnershipEvidenceV1(
        request=request,
        input_digest=sha256_digest(request),
        results=tuple(results),
        output_digest=sha256_digest(results),
    )
