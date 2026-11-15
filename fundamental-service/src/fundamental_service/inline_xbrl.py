"""Bounded, default-target Inline XBRL document sets from one SEC submission."""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from io import BytesIO
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile, ZipFile

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .serialization import canonical_bytes, sha256_digest

_FILENAME = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,195}"
_INLINE_NAMESPACES = frozenset(
    {"http://www.xbrl.org/2008/inlineXBRL", "http://www.xbrl.org/2013/inlineXBRL"}
)


class InlineDocumentSetError(ValueError):
    """Invalid or unsupported document-set evidence, before parser execution."""


class InlineDocumentInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(pattern=rf"^{_FILENAME}\.(?i:htm|html|xhtml)$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class InlineDocumentSetInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["sec-inline-document-set-input-v1"] = (
        "sec-inline-document-set-input-v1"
    )
    target: Literal["(default)"] = "(default)"
    documents: tuple[InlineDocumentInputV1, ...] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def canonical_members(self) -> InlineDocumentSetInputV1:
        names = tuple(d.filename for d in self.documents)
        if names != tuple(sorted(set(names))):
            raise ValueError("inline documents must have distinct canonical names")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)

    def paths(self, root: Path) -> tuple[Path, ...]:
        paths = tuple(root / d.filename for d in self.documents)
        total = 0
        for document, path in zip(self.documents, paths):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.resolve().parent != root.resolve()
            ):
                raise InlineDocumentSetError("inline member bytes differ from input")
            size = path.stat().st_size
            total += size
            if not 1 <= size <= 24_000_000 or total > 48_000_000:
                raise InlineDocumentSetError(
                    "inline input exceeds document byte limits"
                )
            if hashlib.sha256(path.read_bytes()).hexdigest() != document.content_hash:
                raise InlineDocumentSetError("inline member bytes differ from input")
        return paths


def inline_document_metadata(content: bytes) -> tuple[bool, tuple[str, ...]]:
    """Inspect XML namespaces using Arelle's recovery semantics and explicit bounds."""
    if len(content) > 24_000_000:
        raise InlineDocumentSetError("inline document exceeds byte limit")
    # Plain ASCII HTML without any namespace declaration cannot contain inline XML.
    # This also avoids treating unclosed HTML void elements as XML nesting.
    if (
        content.isascii()
        and b"\x00" not in content
        and b"xmlns" not in content
        and re.match(rb"\s*<html(?:\s|>)", content)
    ):
        return False, ()
    parser = etree.XMLPullParser(
        events=("start", "end"),
        recover=True,
        huge_tree=True,
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
    )
    is_inline = False
    references: list[str] = []
    bases: list[bool] = []
    count = 0

    def consume_events() -> None:
        nonlocal is_inline, count
        for event, element in parser.read_events():
            if event == "end":
                bases.pop()
                element.clear()
                parent = element.getparent()
                if parent is not None:
                    while element.getprevious() is not None:
                        del parent[0]
                continue
            count += 1
            if len(bases) >= 512 or count > 1_000_000:
                raise InlineDocumentSetError("inline XML structure exceeds limits")
            bases.append(
                (bool(bases) and bases[-1])
                or element.get("{http://www.w3.org/XML/1998/namespace}base") is not None
            )
            namespace = (
                element.tag[1:].partition("}")[0]
                if element.tag.startswith("{")
                else None
            )
            if namespace in _INLINE_NAMESPACES:
                is_inline = True
                if element.get("target", ""):
                    raise InlineDocumentSetError("named inline targets are unsupported")
            if element.tag != "{http://www.xbrl.org/2003/linkbase}schemaRef":
                continue
            if bases[-1]:
                raise InlineDocumentSetError("schema must use the accession base URI")
            href = element.get("{http://www.w3.org/1999/xlink}href", "")
            if not re.fullmatch(rf"{_FILENAME}\.xsd", href):
                raise InlineDocumentSetError("inline schema must be one local filename")
            references.append(href)

    try:
        for offset in range(0, len(content), 16_384):
            parser.feed(content[offset : offset + 16_384])
            consume_events()
        parser.close()
        consume_events()
    except etree.XMLSyntaxError as error:
        raise InlineDocumentSetError("inline document is not parseable XML") from error
    return is_inline, tuple(references)


def select_inline_document_set(
    submission: bytes, index: bytes, primary_document: str
) -> tuple[tuple[str, ...], str | None]:
    """Select every inline member of the single supported default target."""
    if len(submission) > 64_000_000:
        raise InlineDocumentSetError("SEC submission exceeds byte limit")
    documents = re.findall(rb"(?ms)^<DOCUMENT>\s*\n(.*?)^</DOCUMENT>\s*$", submission)
    if (
        not documents
        or len(documents) > 4096
        or len(documents) != len(re.findall(rb"(?m)^<DOCUMENT>[ \t]*\r?$", submission))
        or len(documents) != len(re.findall(rb"(?m)^</DOCUMENT>[ \t]*\r?$", submission))
        or not re.search(rb"(?m)^</SEC-DOCUMENT>\s*\Z", submission)
    ):
        raise InlineDocumentSetError("SEC submission document inventory is incomplete")
    try:
        names = [item["name"] for item in json.loads(index)["directory"]["item"]]
    except (ValueError, KeyError, TypeError) as error:
        raise InlineDocumentSetError("SEC document index is invalid") from error
    selected = []
    seen = set()
    schemas: set[str] = set()
    for document in documents:
        filenames = re.findall(rb"(?m)^<FILENAME>([^\r\n]+)\r?$", document)
        if len(filenames) != 1:
            raise InlineDocumentSetError("SEC document filename is missing or repeated")
        try:
            filename = filenames[0].decode("ascii")
        except UnicodeDecodeError as error:
            raise InlineDocumentSetError("SEC document filename is invalid") from error
        if (
            not re.fullmatch(_FILENAME + r"\.[A-Za-z0-9]+", filename)
            or filename in seen
        ):
            raise InlineDocumentSetError("SEC document filename is unsafe or repeated")
        seen.add(filename)
        if Path(filename).suffix.lower() not in {".htm", ".html", ".xhtml"}:
            continue
        texts = re.findall(rb"(?ms)^<TEXT>[ \t]*\r?\n(.*?)^</TEXT>[ \t]*\r?$", document)
        if len(texts) != 1:
            raise InlineDocumentSetError("SEC HTML document body is incomplete")
        body = texts[0]
        wrapper = re.fullmatch(rb"<XBRL>\s*\n(.*?)\s*</XBRL>\s*", body, re.S)
        if wrapper is not None:
            body = wrapper[1]
        inline, references = inline_document_metadata(body)
        if not inline:
            continue
        if names.count(filename) != 1:
            raise InlineDocumentSetError("inline member is not uniquely indexed")
        selected.append(filename)
        schemas.update(references)
    if primary_document not in selected or not 1 <= len(selected) <= 8:
        raise InlineDocumentSetError("inline inventory does not cover the primary")
    if len(selected) == 1:
        # Existing single-document schema validation and evidence remain unchanged.
        return (), None
    if len(schemas) != 1 or names.count(next(iter(schemas))) != 1:
        raise InlineDocumentSetError("inline set requires one indexed local schema")
    return tuple(sorted(selected)), next(iter(schemas))


def read_inline_document_input(path: Path) -> InlineDocumentSetInputV1:
    raw = path.read_bytes()
    if len(raw) > 16_384:
        raise InlineDocumentSetError("inline input manifest exceeds byte limit")
    manifest = InlineDocumentSetInputV1.model_validate_json(raw)
    if canonical_bytes(manifest) != raw:
        raise InlineDocumentSetError("inline input manifest must be canonical")
    manifest.paths(path.parent)
    return manifest


def archive_inline_document_names(content: bytes) -> tuple[str, ...]:
    """Independently enumerate the complete inline inventory before admission/replay."""
    if len(content) > 24_000_000:
        raise InlineDocumentSetError("inline archive exceeds byte limit")
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                len(infos) > 4096
                or len(names) != len(set(names))
                or sum(info.file_size for info in infos) > 256_000_000
            ):
                raise InlineDocumentSetError(
                    "inline archive inventory is invalid or excessive"
                )
            selected = []
            selected_size = 0
            for info in infos:
                if Path(info.filename).suffix.lower() not in {
                    ".htm",
                    ".html",
                    ".xhtml",
                }:
                    continue
                if info.flag_bits & 1 or info.file_size > 24_000_000:
                    raise InlineDocumentSetError(
                        "inline archive member is encrypted or excessive"
                    )
                raw = archive.read(info)
                if len(raw) != info.file_size:
                    raise InlineDocumentSetError("inline archive member size differs")
                if not inline_document_metadata(raw)[0]:
                    continue
                if not re.fullmatch(
                    rf"{_FILENAME}\.(?i:htm|html|xhtml)", info.filename
                ):
                    raise InlineDocumentSetError(
                        "inline archive member is not a root filename"
                    )
                selected.append(info.filename)
                selected_size += len(raw)
                if len(selected) > 8 or selected_size > 48_000_000:
                    raise InlineDocumentSetError(
                        "inline document set exceeds supported limits"
                    )
            return tuple(sorted(selected))
    except (
        BadZipFile,
        EOFError,
        OSError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as error:
        raise InlineDocumentSetError("inline archive could not be verified") from error
