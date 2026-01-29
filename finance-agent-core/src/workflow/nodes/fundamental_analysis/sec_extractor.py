import re
from dataclasses import dataclass

import pandas as pd
from edgar import Company, set_identity
from pydantic import BaseModel, Field
from tabulate import tabulate

# Set SEC identity
set_identity("ValueInvestmentAgent research@example.com")


@dataclass
class SearchConfig:
    """搜尋配置對象：攜帶搜尋類型與選擇性的維度過濾器"""

    concept_regex: str
    type_name: str = "CONSOLIDATED"
    dimension_regex: str | None = None


class SearchType:
    """搜尋類型工廠：協助建立 SearchConfig"""

    @staticmethod
    def CONSOLIDATED(concept_regex: str) -> SearchConfig:
        return SearchConfig(concept_regex=concept_regex, type_name="CONSOLIDATED")

    @staticmethod
    def DIMENSIONAL(concept_regex: str, dimension_regex: str) -> SearchConfig:
        return SearchConfig(
            concept_regex=concept_regex,
            type_name="DIMENSIONAL",
            dimension_regex=dimension_regex,
        )


class SECExtractResult(BaseModel):
    concept: str
    value: str | None
    label: str | None
    statement: str | None
    period_key: str
    dimensions: str | None
    dimension_detail: dict | None = Field(default_factory=dict)


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
        print(f"\n>>> 初始化 {self.ticker} {self.fiscal_year} 財年數據...")
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
            print(f"[*] 鎖定報表截止日: {self.actual_date}")

        # 預先識別維度列
        self.real_dim_cols = [
            col for col in self.df.columns if "Axis" in col or col.startswith("dim_")
        ]

    def search(self, config: SearchConfig) -> list[SECExtractResult]:
        """
        核心搜尋方法：僅接受配置對象。
        :param config: SearchConfig 對象
        """
        if self.df is None:
            return []

        # print(
        #     f"\n>>> 搜尋執行: '{config.concept_regex}' | 模式: {config.type_name}"
        #     + (
        #         f" | 維度過濾: '{config.dimension_regex}'"
        #         if config.dimension_regex
        #         else ""
        #     )
        # )

        # 1. 標籤與日期初步過濾
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

        # 2. 應用 SearchType 過濾邏輯 [5, 6]
        is_consolidated_series = self.df[self.real_dim_cols].isna().all(axis=1)

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
            print("[-] 找不到匹配結果。")
            return []

        # 3. 格式化結果
        final_rows = []
        unique_df = matches.drop_duplicates(subset=["concept", "value"])

        for _, row in unique_df.iterrows():
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
                )
            )

        # 4. 打印結果
        # if final_rows:
        # table_display = pd.DataFrame([r.model_dump() for r in final_rows])
        # Drop complex dict col for tabulate
        # simple_display = table_display.drop(
        #     columns=["dimension_detail", "dimensions"], errors="ignore"
        # )
        # print(tabulate(simple_display, headers='keys', tablefmt='fancy_grid', showindex=False))

        return final_rows

    def sic_code(self):
        return self.standard_industrial_classification_code

    def debug_asset_issue(self, tag: str):
        # print(
        #     f"\n>>> [DEBUG] 正在診斷 {self.ticker} {self.fiscal_year} 的 us-gaap:Assets..."
        # )

        # 1. 寬鬆搜尋：只找 Tag，不管維度
        processed_regex = tag if ":" in tag else f".*:{tag}$"
        mask = self.df["concept"].str.contains(
            processed_regex, flags=re.IGNORECASE, na=False
        )
        matches = self.df[mask].copy()

        if matches.empty:
            print(
                "[-] 驚人！連原始數據都找不到。可能使用了不同的 Tag (如 AssetsCurrent?)"
            )
            return

        # 2. 找出所有非空的維度欄位
        # 過濾掉全是 NaN 的列，只保留有值的維度列
        active_dim_cols = (
            matches[self.real_dim_cols].dropna(axis=1, how="all").columns.tolist()
        )

        # 3. 打印結果
        print(f"[*] 找到 {len(matches)} 筆 Assets 數據。")
        print(f"[*] 污染數據的維度欄位 (Culprits): {active_dim_cols}")

        display_cols = ["period_end", "value"] + active_dim_cols
        print(tabulate(matches[display_cols], headers="keys", tablefmt="fancy_grid"))
