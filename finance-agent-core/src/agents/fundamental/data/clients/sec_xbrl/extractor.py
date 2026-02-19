import logging
import re
from dataclasses import dataclass

import pandas as pd
from edgar import Company, set_identity
from pydantic import BaseModel, Field
from tabulate import tabulate

from src.shared.kernel.tools.logger import get_logger, log_event

# Set SEC identity
set_identity("ValueInvestmentAgent research@example.com")

logger = get_logger(__name__)


@dataclass
class SearchConfig:
    """搜尋配置對象：攜帶搜尋類型與選擇性的維度過濾器"""

    concept_regex: str
    type_name: str = "CONSOLIDATED"
    dimension_regex: str | None = None
    statement_types: list[str] | None = None
    period_type: str | None = None  # "instant" or "duration"
    unit_whitelist: list[str] | None = None
    unit_blacklist: list[str] | None = None


class SearchType:
    """搜尋類型工廠：協助建立 SearchConfig"""

    @staticmethod
    def CONSOLIDATED(
        concept_regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
        unit_blacklist: list[str] | None = None,
    ) -> SearchConfig:
        return SearchConfig(
            concept_regex=concept_regex,
            type_name="CONSOLIDATED",
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
            unit_blacklist=unit_blacklist,
        )

    @staticmethod
    def DIMENSIONAL(
        concept_regex: str,
        dimension_regex: str,
        statement_types: list[str] | None = None,
        period_type: str | None = None,
        unit_whitelist: list[str] | None = None,
        unit_blacklist: list[str] | None = None,
    ) -> SearchConfig:
        return SearchConfig(
            concept_regex=concept_regex,
            type_name="DIMENSIONAL",
            dimension_regex=dimension_regex,
            statement_types=statement_types,
            period_type=period_type,
            unit_whitelist=unit_whitelist,
            unit_blacklist=unit_blacklist,
        )


class SECExtractResult(BaseModel):
    concept: str
    value: str | None
    label: str | None
    statement: str | None
    period_key: str
    dimensions: str | None
    dimension_detail: dict | None = Field(default_factory=dict)
    unit: str | None = None
    decimals: str | None = None
    scale: str | None = None


@dataclass
class Rejection:
    reason: str
    concept: str
    period_key: str
    statement_type: str | None
    unit: str | None
    value_preview: str | None


class SearchStats:
    def __init__(self) -> None:
        self.rejections: list[Rejection] = []

    def add(self, rejection: Rejection) -> None:
        self.rejections.append(rejection)

    def log(self, logger) -> None:
        for rej in self.rejections:
            log_event(
                logger,
                event="fundamental_xbrl_search_rejection",
                message="xbrl row rejected by filters",
                level=logging.DEBUG,
                fields={
                    "reason": rej.reason,
                    "concept": rej.concept,
                    "period_key": rej.period_key,
                    "statement_type": rej.statement_type,
                    "unit": rej.unit,
                    "value_preview": rej.value_preview,
                },
            )


class SECReportExtractor:
    def __init__(self, ticker: str, fiscal_year: int):
        self.ticker = ticker
        self.fiscal_year = fiscal_year
        self.standard_industrial_classification_code = None
        self.df = None
        self.actual_date = None
        self.real_dim_cols = []
        self._load_report_data()

    def _load_report_data(self):
        log_event(
            logger,
            event="fundamental_xbrl_report_load_started",
            message="xbrl report data initialization started",
            fields={"ticker": self.ticker, "fiscal_year": self.fiscal_year},
        )
        company = Company(self.ticker)
        self.standard_industrial_classification_code = company.sic
        # 智慧對齊：考慮申報時差 [1, 2]
        filings = company.get_filings(
            form="10-K", year=[self.fiscal_year, self.fiscal_year + 1], amendments=False
        )

        target_filing = next(
            (
                f
                for f in filings
                if pd.to_datetime(f.period_of_report).year == self.fiscal_year
            ),
            None,
        )
        if not target_filing:
            target_filing = filings.latest()
        if not target_filing:
            raise ValueError(f"找不到 {self.ticker} 報告。")

        # 解析 XBRL 並快取至記憶體 [3, 4]
        xb = target_filing.xbrl()
        if not xb:
            raise ValueError(f"No XBRL data found for {self.ticker}")

        self.df = xb.facts.to_dataframe()

        # 鎖定日期錨點
        dei_mask = self.df["concept"].str.contains(
            "DocumentPeriodEndDate", case=False, na=False
        )
        if dei_mask.any():
            self.actual_date = str(self.df[dei_mask].iloc[0]["value"])[:10]
            log_event(
                logger,
                event="fundamental_xbrl_report_anchor_date_locked",
                message="xbrl report anchor date locked",
                fields={"ticker": self.ticker, "actual_date": self.actual_date},
            )

        # 預先識別維度列
        self.real_dim_cols = self._identify_dimension_columns(self.df.columns)

    def search(self, config: SearchConfig) -> list[SECExtractResult]:
        """
        核心搜尋方法：僅接受配置對象。
        :param config: SearchConfig 對象
        """
        if self.df is None:
            return []

        # 1. 標籤與日期初步過濾
        if self._is_plain_tag(config.concept_regex):
            pattern = re.escape(config.concept_regex) + r"$"
            mask = self.df["concept"].str.match(pattern, flags=re.IGNORECASE, na=False)
        else:
            processed_regex = (
                config.concept_regex
                if ":" in config.concept_regex
                else f".*:{config.concept_regex}$"
            )
            mask = self.df["concept"].str.contains(
                processed_regex, flags=re.IGNORECASE, na=False
            )

        if self.actual_date:
            date_mask = (self.df["period_end"] == self.actual_date) | (
                self.df["period_key"].str.contains(self.actual_date, na=False)
            )
            mask = mask & date_mask

        # Statement/period/unit filters are applied later to capture rejection reasons.

        # 2. 應用 SearchType 過濾邏輯 [5, 6]
        if self.real_dim_cols:
            dim_df = self.df[self.real_dim_cols]
            dim_str = dim_df.astype(str).apply(lambda s: s.str.strip().str.lower())
            empty_tokens = {"", "none", "none (total)", "total"}
            empty_mask = dim_df.isna() | dim_str.isin(empty_tokens)
            is_consolidated_series = empty_mask.all(axis=1)
        else:
            is_consolidated_series = pd.Series(True, index=self.df.index)

        if config.type_name == "CONSOLIDATED":
            mask = mask & is_consolidated_series
        else:
            mask = mask & (~is_consolidated_series)
            # 如果是維度搜尋且有 dimension_regex，執行維度內搜尋 [7, 8]
            if config.dimension_regex and self.real_dim_cols:
                dim_mask = (
                    self.df[self.real_dim_cols]
                    .apply(
                        lambda x: x.astype(str).str.contains(
                            config.dimension_regex, flags=re.IGNORECASE, na=False
                        )
                    )
                    .any(axis=1)
                )
                mask = mask & dim_mask

        matches = self.df[mask].copy()
        if matches.empty:
            log_event(
                logger,
                event="fundamental_xbrl_search_no_matches",
                message="xbrl search returned no matches",
                level=logging.DEBUG,
                fields={
                    "ticker": self.ticker,
                    "concept_regex": config.concept_regex,
                    "search_type": config.type_name,
                },
            )
            return []

        # 3. 格式化結果
        stats = SearchStats()
        final_rows = []
        seen: set[tuple[str, str]] = set()

        for _, row in matches.iterrows():
            unit = self._extract_unit(row)
            normalized_unit = self._normalize_unit(unit) if unit else None

            statement_ok = True
            statement_tokens = (
                [t for t in config.statement_types if t]
                if config.statement_types
                else []
            )
            if statement_tokens and "statement_type" in self.df.columns:
                statement_ok = self._statement_matches(
                    row.get("statement_type"), statement_tokens
                )

            period_ok = True
            if config.period_type:
                period_ok = self._period_matches(row, config.period_type)

            unit_ok = True
            if (
                config.unit_whitelist or config.unit_blacklist
            ) and self._unit_columns_present():
                unit_ok = self._unit_matches(
                    normalized_unit,
                    config.unit_whitelist,
                    config.unit_blacklist,
                )

            if not statement_ok:
                stats.add(
                    Rejection(
                        reason="statement_mismatch",
                        concept=str(row.get("concept")),
                        period_key=str(row.get("period_key")),
                        statement_type=str(row.get("statement_type"))
                        if pd.notna(row.get("statement_type"))
                        else None,
                        unit=str(unit) if unit is not None else None,
                        value_preview=self._value_preview(row.get("value")),
                    )
                )
            if not period_ok:
                stats.add(
                    Rejection(
                        reason="period_mismatch",
                        concept=str(row.get("concept")),
                        period_key=str(row.get("period_key")),
                        statement_type=str(row.get("statement_type"))
                        if pd.notna(row.get("statement_type"))
                        else None,
                        unit=str(unit) if unit is not None else None,
                        value_preview=self._value_preview(row.get("value")),
                    )
                )
            if not unit_ok:
                stats.add(
                    Rejection(
                        reason="unit_mismatch",
                        concept=str(row.get("concept")),
                        period_key=str(row.get("period_key")),
                        statement_type=str(row.get("statement_type"))
                        if pd.notna(row.get("statement_type"))
                        else None,
                        unit=str(unit) if unit is not None else None,
                        value_preview=self._value_preview(row.get("value")),
                    )
                )
            if not (statement_ok and period_ok and unit_ok):
                continue
            key = (str(row.get("concept")), str(row.get("value")))
            if key in seen:
                continue
            seen.add(key)

            dim_detail = {
                col.split("_")[-1]: row[col]
                for col in self.real_dim_cols
                if pd.notna(row[col])
            }
            dim_str = (
                "\n".join([f"{k}: {v}" for k, v in dim_detail.items()])
                if dim_detail
                else "None (Total)"
            )

            # Safe access for optional columns
            label = row.get("label")
            statement = row.get("statement_type")

            final_rows.append(
                SECExtractResult(
                    concept=row["concept"],
                    value=str(row["value"]),
                    label=label if pd.notna(label) else None,
                    statement=str(statement) if pd.notna(statement) else None,
                    period_key=str(row["period_key"]),
                    dimensions=dim_str,
                    dimension_detail=dim_detail,
                    unit=str(unit) if unit is not None else None,
                    decimals=str(row.get("decimals"))
                    if pd.notna(row.get("decimals"))
                    else None,
                    scale=str(row.get("scale")) if pd.notna(row.get("scale")) else None,
                )
            )

        stats.log(logger)
        return final_rows

    def sic_code(self):
        return self.standard_industrial_classification_code

    def debug_asset_issue(self, tag: str):
        # 1. 寬鬆搜尋：只找 Tag，不管維度
        processed_regex = tag if ":" in tag else f".*:{tag}$"
        mask = self.df["concept"].str.contains(
            processed_regex, flags=re.IGNORECASE, na=False
        )
        matches = self.df[mask].copy()

        if matches.empty:
            log_event(
                logger,
                event="fundamental_xbrl_asset_debug_no_rows",
                message="asset debug query returned no rows; tag may differ",
                level=logging.WARNING,
                error_code="FUNDAMENTAL_XBRL_ASSET_DEBUG_EMPTY",
                fields={"ticker": self.ticker, "tag": tag},
            )
            return

        # 2. 找出所有非空的維度欄位
        active_dim_cols = (
            matches[self.real_dim_cols].dropna(axis=1, how="all").columns.tolist()
        )

        # 3. 打印結果
        log_event(
            logger,
            event="fundamental_xbrl_asset_debug_summary",
            message="asset debug summary generated",
            fields={
                "ticker": self.ticker,
                "rows": len(matches),
                "active_dimensions": active_dim_cols,
            },
        )

        display_cols = ["period_end", "value"] + active_dim_cols
        log_event(
            logger,
            event="fundamental_xbrl_asset_debug_table",
            message="asset debug table generated",
            fields={
                "ticker": self.ticker,
                "table": tabulate(
                    matches[display_cols], headers="keys", tablefmt="fancy_grid"
                ),
            },
        )

    @staticmethod
    def _value_preview(value: object, max_len: int = 80) -> str | None:
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

    @staticmethod
    def _statement_matches(statement_value: object, tokens: list[str]) -> bool:
        if statement_value is None:
            return False
        if isinstance(statement_value, float) and pd.isna(statement_value):
            return False
        text = str(statement_value).lower()
        for token in tokens:
            if token and token.lower() in text:
                return True
        return False

    @staticmethod
    def _period_matches(row: pd.Series, period_type: str) -> bool:
        period_type = period_type.lower()
        if "period_type" in row and pd.notna(row.get("period_type")):
            return str(row.get("period_type")).lower() == period_type
        period_key = str(row.get("period_key") or "")
        return period_key.lower().startswith(period_type)

    @staticmethod
    def _unit_matches(
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

    def _unit_columns_present(self) -> bool:
        return any(
            col in self.df.columns
            for col in ("unit", "unit_ref", "unit_ref_id", "unit_id", "unit_key")
        )

    @staticmethod
    def _normalize_unit(unit: str) -> str:
        text = unit.strip()
        if ":" in text:
            text = text.split(":")[-1]
        return text.lower()

    def _extract_unit(self, row: pd.Series) -> str | None:
        for key in ("unit", "unit_ref", "unit_ref_id", "unit_id", "unit_key"):
            if key in row and pd.notna(row[key]):
                return str(row[key])
        return None

    @staticmethod
    def _is_plain_tag(tag: str) -> bool:
        return re.match(r"^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$", tag) is not None

    @staticmethod
    def _identify_dimension_columns(columns: list[str]) -> list[str]:
        dim_cols: list[str] = []
        for col in columns:
            lower = col.lower()
            if lower.startswith("dim_"):
                dim_cols.append(col)
                continue
            if any(
                token in lower for token in ("axis", "member", "segment", "dimension")
            ):
                dim_cols.append(col)
        return dim_cols
