"""Read hash-pinned retained original records without restoring a checkout."""

from __future__ import annotations

import base64
import gzip
import io
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from analyze_history_study import hash_value, list_value, object_value, text_value
from audit_history_study_labels import decode_json
from plan_history_study_precision import DesignError, canonical_bytes, digest

SOURCE_REVISION: Literal["32be2dafbbc7756bf185e228dc8fdcc280fe6cf3"] = (
    "32be2dafbbc7756bf185e228dc8fdcc280fe6cf3"
)
PARSER_EXECUTION = "62f121f386534ea65f0be15b04efc83ed4478d09"
PREFIX = "docs/acceptance/issue-361-marker62-evidence-v1/"
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024


def checked_document(raw: bytes, expected: str) -> dict[str, object]:
    if digest(raw) != expected:
        raise DesignError("retained original content digest differs")
    document = object_value(decode_json(raw))
    if canonical_bytes(document) != raw:
        raise DesignError("retained original must use canonical JSON")
    return document


def unpack(packed: bytes) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as handle:
        raw = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise DesignError("retained original exceeds document bound")
    return raw


@dataclass(frozen=True)
class OriginalReader:
    repository: Path
    revision: str = SOURCE_REVISION

    def packed(self, path: str) -> bytes:
        relative = PurePosixPath(path)
        if (
            not re.fullmatch(r"[0-9a-f]{40}", self.revision)
            or self.revision != SOURCE_REVISION
            or relative.is_absolute()
            or ".." in relative.parts
            or str(relative) != path
            or not path.startswith(PREFIX)
        ):
            raise DesignError("unsafe or unpinned original evidence reference")
        return subprocess.check_output(
            ["git", "-C", str(self.repository), "show", f"{self.revision}:{path}"]
        )

    def document(self, value: object) -> dict[str, object]:
        ref = object_value(value)
        expected = hash_value(ref["sha256"])
        length = ref["bytes"]
        if (
            not isinstance(length, int)
            or isinstance(length, bool)
            or not 0 < length <= MAX_DOCUMENT_BYTES
        ):
            raise DesignError("retained original length is invalid")
        storage = text_value(ref["storage"])
        if storage == "canonical-json-gzip":
            raw = unpack(self.packed(text_value(ref["path"])))
        elif storage == "canonical-json-chunks":
            pieces = []
            offset = 0
            for value in list_value(ref["chunks"]):
                chunk_ref = object_value(value)
                if chunk_ref["offset"] != offset:
                    raise DesignError("original chunks must be contiguous and ordered")
                chunk = checked_document(
                    unpack(self.packed(text_value(chunk_ref["path"]))),
                    hash_value(chunk_ref["sha256"]),
                )
                piece = base64.b64decode(
                    text_value(chunk["content_base64"]), validate=True
                )
                if (
                    len(piece) != chunk_ref["bytes"]
                    or digest(piece) != chunk_ref["content_sha256"]
                ):
                    raise DesignError("original chunk payload differs")
                pieces.append(piece)
                offset += len(piece)
                if offset > length:
                    raise DesignError("original chunks exceed declared length")
            raw = b"".join(pieces)
        else:
            raise DesignError("unsupported original evidence storage")
        if len(raw) != length:
            raise DesignError("retained original byte length differs")
        return checked_document(raw, expected)
