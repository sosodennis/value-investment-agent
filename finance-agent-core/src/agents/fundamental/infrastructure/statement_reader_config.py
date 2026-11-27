from __future__ import annotations

import os

from pydantic import TypeAdapter

from src.shared.artifacts.statement_read_artifact import (
    StatementEditionV2,
)


def load_statement_reader_editions() -> tuple[StatementEditionV2, ...]:
    editions = TypeAdapter(tuple[StatementEditionV2, ...]).validate_json(
        os.getenv("FUNDAMENTAL_STATEMENT_EDITIONS_V2", "[]")
    )
    if len({edition.edition_id for edition in editions}) != len(editions):
        raise ValueError("Statement edition selectors must be unique")
    return editions
