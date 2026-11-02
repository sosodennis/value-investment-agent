from __future__ import annotations

import re
from datetime import date

import pandas as pd

from ..extract.extractor_models import (
    Rejection,
    SearchConfig,
    SearchStats,
    SECExtractResult,
)


def build_base_mask(
    *,
    df: pd.DataFrame,
    actual_date: str | None,
    config: SearchConfig,
) -> pd.Series:
    if is_plain_tag(config.concept_regex):
        pattern = re.escape(config.concept_regex) + r"$"
        mask = df["concept"].str.match(pattern, flags=re.IGNORECASE, na=False)
    else:
        processed_regex = (
            config.concept_regex
            if ":" in config.concept_regex
            else f".*:{config.concept_regex}$"
        )
        mask = df["concept"].str.contains(
            processed_regex, flags=re.IGNORECASE, na=False
        )

    if actual_date and config.respect_anchor_date:
        date_mask = (df["period_end"] == actual_date) | (
            df["period_key"].str.contains(actual_date, na=False)
        )
        return mask & date_mask
    return mask


def apply_search_type_mask(
    *,
    df: pd.DataFrame,
    real_dim_cols: list[str],
    base_mask: pd.Series,
    config: SearchConfig,
) -> pd.Series:
    # Statement/period/unit filters are applied later to capture rejection reasons.
    if real_dim_cols:
        dim_df = df[real_dim_cols]
        dim_str = dim_df.astype(str).apply(lambda s: s.str.strip().str.lower())
        empty_tokens = {"", "none", "none (total)", "total"}
        empty_mask = dim_df.isna() | dim_str.isin(empty_tokens)
        is_consolidated_series = empty_mask.all(axis=1)
    else:
        is_consolidated_series = pd.Series(True, index=df.index)

    if config.type_name == "CONSOLIDATED":
        return base_mask & is_consolidated_series

    mask = base_mask & (~is_consolidated_series)
    if config.dimension_regex and real_dim_cols:
        dim_mask = (
            df[real_dim_cols]
            .apply(
                lambda x: x.astype(str).str.contains(
                    config.dimension_regex, flags=re.IGNORECASE, na=False
                )
            )
            .any(axis=1)
        )
        mask = mask & dim_mask
    return mask


def filter_and_format_results(
    *,
    matches: pd.DataFrame,
    config: SearchConfig,
    real_dim_cols: list[str],
    stats: SearchStats,
) -> list[SECExtractResult]:
    final_rows: list[SECExtractResult] = []
    seen: set[tuple[str, str, str | None, tuple[tuple[str, str], ...], str]] = set()

    statement_tokens = (
        [token for token in config.statement_types if token]
        if config.statement_types
        else []
    )
    has_statement_type = "statement_type" in matches.columns
    has_unit_filter = bool(config.unit_whitelist or config.unit_blacklist)
    columns = list(matches.columns)
    column_index = {column: index for index, column in enumerate(columns)}

    for row in matches.itertuples(index=False, name=None):
        concept = str(tuple_get(row, column_index, "concept") or "")
        period_key = str(tuple_get(row, column_index, "period_key") or "")
        statement_value = tuple_get(row, column_index, "statement_type")
        raw_value = tuple_get(row, column_index, "value")

        unit = extract_unit_from_tuple(row, column_index)
        normalized_unit = normalize_unit(unit) if unit else None

        statement_ok = True
        if statement_tokens and has_statement_type:
            statement_ok = statement_matches(statement_value, statement_tokens)

        row_period_type = tuple_get(row, column_index, "period_type")
        period_ok = True
        if config.period_type:
            period_ok = period_matches_values(
                period_key=period_key,
                row_period_type=row_period_type,
                period_type=config.period_type,
            )

        unit_ok = True
        if has_unit_filter and unit_columns_present(columns):
            unit_ok = unit_matches(
                normalized_unit,
                config.unit_whitelist,
                config.unit_blacklist,
            )

        if not statement_ok:
            stats.add(
                Rejection(
                    reason="statement_mismatch",
                    concept=concept,
                    period_key=period_key,
                    statement_type=(
                        str(statement_value) if pd.notna(statement_value) else None
                    ),
                    unit=str(unit) if unit is not None else None,
                    value_preview=value_preview(raw_value),
                )
            )
        if not period_ok:
            stats.add(
                Rejection(
                    reason="period_mismatch",
                    concept=concept,
                    period_key=period_key,
                    statement_type=(
                        str(statement_value) if pd.notna(statement_value) else None
                    ),
                    unit=str(unit) if unit is not None else None,
                    value_preview=value_preview(raw_value),
                )
            )
        if not unit_ok:
            stats.add(
                Rejection(
                    reason="unit_mismatch",
                    concept=concept,
                    period_key=period_key,
                    statement_type=(
                        str(statement_value) if pd.notna(statement_value) else None
                    ),
                    unit=str(unit) if unit is not None else None,
                    value_preview=value_preview(raw_value),
                )
            )
        if not (statement_ok and period_ok and unit_ok):
            continue

        dim_detail = extract_dimension_detail_from_tuple(
            row, column_index, real_dim_cols
        )
        dim_key = tuple(sorted((str(k), str(v)) for k, v in dim_detail.items()))
        dedup_key = (
            concept,
            period_key,
            normalized_unit,
            dim_key,
            str(raw_value),
        )
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        dimensions = (
            "\n".join([f"{k}: {v}" for k, v in dim_detail.items()])
            if dim_detail
            else "None (Total)"
        )
        label = tuple_get(row, column_index, "label")
        decimals = tuple_get(row, column_index, "decimals")
        scale = tuple_get(row, column_index, "scale")
        presentation_score = _to_optional_float(
            tuple_get(row, column_index, "presentation_score")
        )
        calculation_score = _to_optional_float(
            tuple_get(row, column_index, "calculation_score")
        )

        final_rows.append(
            SECExtractResult(
                concept=concept,
                value=str(raw_value),
                label=str(label) if pd.notna(label) else None,
                statement=str(statement_value) if pd.notna(statement_value) else None,
                period_key=period_key,
                dimensions=dimensions,
                dimension_detail=dim_detail,
                unit=str(unit) if unit is not None else None,
                decimals=str(decimals) if pd.notna(decimals) else None,
                scale=str(scale) if pd.notna(scale) else None,
                presentation_score=presentation_score,
                calculation_score=calculation_score,
            )
        )

    return final_rows


def value_preview(value: object, max_len: int = 80) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).replace("\n", " ").strip()
    if not text:
        return None
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def statement_matches(statement_value: object, tokens: list[str]) -> bool:
    if statement_value is None:
        return False
    if isinstance(statement_value, float) and pd.isna(statement_value):
        return False
    text = str(statement_value).lower()
    for token in tokens:
        if token and token.lower() in text:
            return True
    return False


def period_matches_values(
    *,
    period_key: str,
    row_period_type: object,
    period_type: str,
) -> bool:
    expected = period_type.lower()
    if row_period_type is not None and pd.notna(row_period_type):
        return str(row_period_type).lower() == expected
    return str(period_key).lower().startswith(expected)


def period_sort_key(period_key: str) -> date:
    # period_key examples:
    # - instant_2025-12-31
    # - duration_2025-01-01_2025-12-31
    if period_key.startswith("instant_"):
        candidate = period_key.removeprefix("instant_")
        parsed = parse_date(candidate)
        if parsed:
            return parsed
    if period_key.startswith("duration_"):
        parts = period_key.removeprefix("duration_").split("_")
        if len(parts) == 2:
            parsed = parse_date(parts[1])
            if parsed:
                return parsed
    return date.min


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def unit_matches(
    normalized_unit: str | None,
    unit_whitelist: list[str] | None,
    unit_blacklist: list[str] | None,
) -> bool:
    if unit_whitelist is not None:
        allowed = {u.lower() for u in unit_whitelist}
        if normalized_unit not in allowed:
            return False
    if unit_blacklist:
        blocked = {u.lower() for u in unit_blacklist}
        if normalized_unit in blocked:
            return False
    return True


def unit_columns_present(columns: list[str]) -> bool:
    return any(
        col in columns
        for col in ("unit", "unit_ref", "unit_ref_id", "unit_id", "unit_key")
    )


def normalize_unit(unit: str) -> str:
    text = unit.strip()
    if ":" in text:
        text = text.split(":")[-1]
    # Some filings use unit refs like "U_USD" / "U_shares".
    if text.lower().startswith("u_"):
        text = text[2:]
    return text.lower()


def tuple_get(
    row: tuple[object, ...],
    column_index: dict[str, int],
    key: str,
) -> object | None:
    index = column_index.get(key)
    if index is None:
        return None
    return row[index]


def extract_unit_from_tuple(
    row: tuple[object, ...],
    column_index: dict[str, int],
) -> str | None:
    for key in ("unit", "unit_ref", "unit_ref_id", "unit_id", "unit_key"):
        value = tuple_get(row, column_index, key)
        if value is not None and pd.notna(value):
            return str(value)
    return None


def extract_dimension_detail_from_tuple(
    row: tuple[object, ...],
    column_index: dict[str, int],
    real_dim_cols: list[str],
) -> dict[str, object]:
    details: dict[str, object] = {}
    for column in real_dim_cols:
        value = tuple_get(row, column_index, column)
        if value is not None and pd.notna(value):
            details[column.split("_")[-1]] = value
    return details


def is_plain_tag(tag: str) -> bool:
    return re.match(r"^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$", tag) is not None


def _to_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        if pd.isna(value):
            return None
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except ValueError:
        return None


def identify_dimension_columns(columns: list[str]) -> list[str]:
    dim_cols: list[str] = []
    for col in columns:
        lower = col.lower()
        if lower.startswith("dim_"):
            dim_cols.append(col)
            continue
        if any(token in lower for token in ("axis", "member", "segment", "dimension")):
            dim_cols.append(col)
    return dim_cols
