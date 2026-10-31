from __future__ import annotations

import pytest

from src.llm_provider.application.key_import_file import (
    MAX_IMPORT_FILE_BYTES,
    KeyImportFileError,
    parse_key_import_file,
)


def test_txt_import_counts_duplicates_without_returning_keys_in_preview_data() -> None:
    canary = "sk-or-v1-synthetic-credential-0001"
    parsed = parse_key_import_file(
        "keys.txt",
        f"{canary}\n\n{canary}\nsk-or-v1-synthetic-credential-0002\n".encode(),
    )

    assert parsed.row_count == 3
    assert parsed.unique_count == 2
    assert parsed.duplicate_count == 1
    assert parsed.issues == ()
    assert canary not in repr(parsed.issues)


def test_csv_requires_supported_headers_and_reports_only_safe_row_errors() -> None:
    canary = "sk-or-v1-synthetic-credential-0001"
    parsed = parse_key_import_file(
        "keys.csv",
        f"api_key,label\n{canary},primary\nshort,bad row\n".encode(),
    )

    assert parsed.row_count == 2
    assert parsed.items[0].label == "primary"
    assert [(issue.source_line, issue.code) for issue in parsed.issues] == [
        (3, "invalid_csv_row")
    ]
    assert canary not in repr(parsed.issues)

    with pytest.raises(KeyImportFileError, match="missing_api_key_header"):
        parse_key_import_file("keys.csv", b"key\nvalue-that-is-long-enough\n")


@pytest.mark.parametrize("file_type", ["txt", "csv"])
def test_txt_and_csv_accept_one_hundred_unique_keys(file_type: str) -> None:
    keys = [f"sk-or-v1-synthetic-key-{index:04d}-material" for index in range(100)]
    data = (
        "\n".join(keys).encode()
        if file_type == "txt"
        else (
            "api_key,label\n"
            + "\n".join(f"{key},Key {index + 1}" for index, key in enumerate(keys))
        ).encode()
    )

    parsed = parse_key_import_file(f"keys.{file_type}", data)

    assert parsed.row_count == 100
    assert parsed.unique_count == 100
    assert parsed.duplicate_count == 0
    assert len(parsed.items) == 100
    assert parsed.issues == ()


@pytest.mark.parametrize("file_type", ["txt", "csv"])
def test_import_accepts_the_configured_five_hundred_item_limit(file_type: str) -> None:
    keys = [f"sk-or-v1-synthetic-key-{index:04d}-material" for index in range(500)]
    data = (
        "\n".join(keys).encode()
        if file_type == "txt"
        else ("api_key\n" + "\n".join(keys)).encode()
    )

    parsed = parse_key_import_file(f"keys.{file_type}", data)

    assert parsed.row_count == 500
    assert parsed.unique_count == 500
    assert len(parsed.items) == 500


@pytest.mark.parametrize(
    ("filename", "data", "code"),
    [
        ("keys.pdf", b"content", "unsupported_file_type"),
        ("keys.txt", b"\xff", "invalid_encoding"),
        ("keys.txt", b"x" * (MAX_IMPORT_FILE_BYTES + 1), "file_too_large"),
        (
            "keys.txt",
            (("sk-or-v1-" + "x" * 24 + "\n") * 501).encode(),
            "too_many_rows",
        ),
    ],
)
def test_import_rejects_unsupported_or_oversized_input(
    filename: str, data: bytes, code: str
) -> None:
    with pytest.raises(KeyImportFileError) as captured:
        parse_key_import_file(filename, data)
    assert captured.value.code == code
