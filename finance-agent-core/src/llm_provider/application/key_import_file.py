from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from pathlib import PurePath

MAX_IMPORT_FILE_BYTES = 1_048_576
MAX_IMPORT_ROWS = 500
MAX_MULTIPART_OVERHEAD_BYTES = 65_536


@dataclass(frozen=True)
class ParsedKey:
    source_line: int
    label: str
    api_key: str


@dataclass(frozen=True)
class KeyImportParseIssue:
    source_line: int
    code: str


@dataclass(frozen=True)
class ParsedKeyImportFile:
    file_type: str
    row_count: int
    duplicate_count: int
    items: tuple[ParsedKey, ...]
    issues: tuple[KeyImportParseIssue, ...]

    @property
    def unique_count(self) -> int:
        return max(0, len(self.items) - self.duplicate_count)


class KeyImportFileError(ValueError):
    def __init__(self, code: str, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def parse_key_import_file(filename: str, data: bytes) -> ParsedKeyImportFile:
    if len(data) > MAX_IMPORT_FILE_BYTES:
        raise KeyImportFileError("file_too_large", 413)
    suffix = PurePath(filename).suffix.lower()
    if suffix not in {".txt", ".csv"}:
        raise KeyImportFileError("unsupported_file_type", 415)
    try:
        content = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise KeyImportFileError("invalid_encoding", 400) from exc
    if suffix == ".txt":
        return _parse_text(content)
    return _parse_csv(content)


def _parse_text(content: str) -> ParsedKeyImportFile:
    items: list[ParsedKey] = []
    issues: list[KeyImportParseIssue] = []
    seen: set[str] = set()
    duplicate_count = 0
    row_count = 0
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue
        row_count += 1
        if row_count > MAX_IMPORT_ROWS:
            raise KeyImportFileError("too_many_rows", 413)
        api_key = raw_line.strip()
        if not _valid_key_shape(api_key):
            issues.append(KeyImportParseIssue(line_number, "invalid_key_format"))
            continue
        fingerprint = _fingerprint(api_key)
        if fingerprint in seen:
            duplicate_count += 1
        seen.add(fingerprint)
        items.append(
            ParsedKey(
                source_line=line_number,
                label=f"OpenRouter key {row_count}",
                api_key=api_key,
            )
        )
    return ParsedKeyImportFile(
        file_type="txt",
        row_count=row_count,
        duplicate_count=duplicate_count,
        items=tuple(items),
        issues=tuple(issues),
    )


def _parse_csv(content: str) -> ParsedKeyImportFile:
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
        headers = reader.fieldnames
    except csv.Error as exc:
        raise KeyImportFileError("invalid_csv", 400) from exc
    if not headers or "api_key" not in headers:
        raise KeyImportFileError("missing_api_key_header", 400)
    if len(headers) != len(set(headers)) or set(headers) - {"api_key", "label"}:
        raise KeyImportFileError("invalid_csv_header", 400)

    items: list[ParsedKey] = []
    issues: list[KeyImportParseIssue] = []
    seen: set[str] = set()
    duplicate_count = 0
    row_count = 0
    try:
        for row in reader:
            source_line = reader.line_num
            if row is None or not any((value or "").strip() for value in row.values()):
                continue
            row_count += 1
            if row_count > MAX_IMPORT_ROWS:
                raise KeyImportFileError("too_many_rows", 413)
            api_key_value = row.get("api_key")
            label_value = row.get("label") or ""
            if (
                None in row
                or api_key_value is None
                or not _valid_key_shape(api_key_value.strip())
            ):
                issues.append(KeyImportParseIssue(source_line, "invalid_csv_row"))
                continue
            api_key = api_key_value.strip()
            label = label_value.strip() or f"OpenRouter key {row_count}"
            if len(label) > 80:
                issues.append(KeyImportParseIssue(source_line, "invalid_label"))
                continue
            fingerprint = _fingerprint(api_key)
            if fingerprint in seen:
                duplicate_count += 1
            seen.add(fingerprint)
            if api_key in label:
                label = label.replace(api_key, "[redacted]")
            items.append(ParsedKey(source_line, label, api_key))
    except csv.Error as exc:
        raise KeyImportFileError("invalid_csv", 400) from exc

    return ParsedKeyImportFile(
        file_type="csv",
        row_count=row_count,
        duplicate_count=duplicate_count,
        items=tuple(items),
        issues=tuple(issues),
    )


def _valid_key_shape(value: str) -> bool:
    return (
        20 <= len(value) <= 500
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
