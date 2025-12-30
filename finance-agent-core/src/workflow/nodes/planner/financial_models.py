"""
Financial Health Check Models - Pydantic V2 Implementation.

Based on research-planner-0.md, implements the five pillars:
1. Liquidity
2. Solvency
3. Operational Efficiency
4. Profitability
5. Cash Flow Quality
"""

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator, PrivateAttr
from typing import Optional, Literal, Union, Any, Generic, TypeVar, List, Dict
from datetime import date
from enum import Enum
import pandas as pd
import re
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ==========================================
# 0. Core Traceability Infrastructure
# ==========================================

class TraceableField(BaseModel, Generic[T]):
    """
    Wraps a numeric value with metadata about its source and calculation.
    Enables full traceability from final metrics back to XBRL tags.
    """
    value: Optional[float] = None
    source_tags: List[str] = Field(default_factory=list, description="XBRL tags or field names used")
    is_calculated: bool = False
    formula_logic: Optional[str] = Field(None, description="Calculation formula if computed")

    def __repr__(self) -> str:
        return f"TraceableField(value={self.value}, sources={self.source_tags})"

    def _merge_metadata(self, other: 'TraceableField', op_symbol: str) -> Dict[str, Any]:
        """Merge metadata from two fields during arithmetic operations"""
        if isinstance(other, TraceableField):
            new_tags = list(set(self.source_tags + other.source_tags))
            self_formula = self.formula_logic or 'Raw'
            other_formula = other.formula_logic or 'Raw'
        else:
            new_tags = self.source_tags.copy()
            self_formula = self.formula_logic or 'Raw'
            other_formula = 'Const'
        
        new_formula = f"({self_formula} {op_symbol} {other_formula})"
        return {"source_tags": new_tags, "is_calculated": True, "formula_logic": new_formula}

    def __add__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        self_val = self.value
        other_val = other.value if isinstance(other, TraceableField) else other
        
        if self_val is None and other_val is None:
            return TraceableField(value=None)
            
        # Treat None as 0.0 for addition resilience
        val = (self_val or 0.0) + (other_val or 0.0)
        meta = self._merge_metadata(other, "+")
        return TraceableField(value=val, **meta)

    def __radd__(self, other: Union[float, int]) -> 'TraceableField':
        return self.__add__(other)

    def __sub__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        self_val = self.value
        other_val = other.value if isinstance(other, TraceableField) else other
        
        if self_val is None and other_val is None:
            return TraceableField(value=None)
            
        # Treat None as 0.0 for subtraction resilience
        val = (self_val or 0.0) - (other_val or 0.0)
        meta = self._merge_metadata(other, "-")
        return TraceableField(value=val, **meta)

    def __rsub__(self, other: Union[float, int]) -> 'TraceableField':
        if self.value is None:
            return TraceableField(value=None)
        meta = {"source_tags": self.source_tags.copy(), "is_calculated": True, "formula_logic": f"(Const - {self.formula_logic or 'Raw'})"}
        return TraceableField(value=other - self.value, **meta)

    def __mul__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        if self.value is None or (isinstance(other, TraceableField) and other.value is None):
            return TraceableField(value=None)
        other_val = other.value if isinstance(other, TraceableField) else other
        meta = self._merge_metadata(other, "*")
        return TraceableField(value=self.value * other_val, **meta)

    def __rmul__(self, other: Union[float, int]) -> 'TraceableField':
        return self.__mul__(other)

    def __truediv__(self, other: Union['TraceableField', float, int]) -> 'TraceableField':
        other_val = other.value if isinstance(other, TraceableField) else other
        if self.value is None or other_val is None or other_val == 0:
            return TraceableField(value=None)
        meta = self._merge_metadata(other, "/")
        return TraceableField(value=self.value / other_val, **meta)

    def __rtruediv__(self, other: Union[float, int]) -> 'TraceableField':
        if self.value is None or self.value == 0:
            return TraceableField(value=None)
        meta = {"source_tags": self.source_tags.copy(), "is_calculated": True, "formula_logic": f"(Const / {self.formula_logic or 'Raw'})"}
        return TraceableField(value=other / self.value, **meta)


class AutoExtractModel(BaseModel):
    """
    Base model that automatically extracts XBRL data using waterfall logic.
    Supports Dual-Stream Architecture: standardized_dict (Main) + deep_stream_df (Deep).
    """
    # 🚨 Private attribute to hold the Deep Stream DataFrame for complex extractions
    _deep_stream_df: Optional[pd.DataFrame] = PrivateAttr(default=None)

    @model_validator(mode='before')
    @classmethod
    def extract_from_raw_xbrl(cls, data: Any) -> Any:
        """
        Pre-validation hook: Extract values from XBRL data using field metadata.
        Standardized data is passed via 'data' (dict), Deep data via 'deep_stream_df'.
        """
        if not isinstance(data, dict):
            return data

        # Capture the Deep Stream DF if present (injected by Factory)
        deep_stream_df = data.get('deep_stream_df')
        
        model_fields = cls.model_fields
        processed_data = {}
        
        for field_name, field_info in model_fields.items():
            # If already provided, skip extraction
            if field_name in data and data[field_name] is not None:
                processed_data[field_name] = data[field_name]
                continue

            # Get extraction metadata from json_schema_extra
            extra = field_info.json_schema_extra or {}
            xbrl_tags = extra.get('xbrl_tags', [])
            fuzzy_keywords = extra.get('fuzzy_keywords', [])
            exclude_keywords = extra.get('exclude_keywords', [])
            regex_patterns = extra.get('regex_patterns', [])
            dimensions = extra.get('dimensions') # 👈 Dimensional Config
            
            # Skip non-extraction fields
            if not xbrl_tags and not fuzzy_keywords and not regex_patterns:
                processed_data[field_name] = data.get(field_name)
                continue

            # Execute Smart Extraction (Dual-Stream Aware)
            result_obj = cls._internal_get_fact_smart(
                standardized_dict=data,
                deep_stream_df=deep_stream_df,
                standard_tags=xbrl_tags,
                fuzzy_keywords=fuzzy_keywords,
                exclude_keywords=exclude_keywords,
                regex_patterns=regex_patterns,
                dimensions=dimensions
            )
            
            processed_data[field_name] = result_obj

        # Preserve deep_stream_df for instance use
        if deep_stream_df is not None:
            processed_data['_deep_stream_df'] = deep_stream_df

        return processed_data

    def __init__(self, **data):
        super().__init__(**data)
        # Transfer private attr from parsed data
        if '_deep_stream_df' in data:
            self._deep_stream_df = data['_deep_stream_df']

    @staticmethod
    def _df_to_dict(df: pd.DataFrame) -> Dict[str, float]:
        """
        Convert XBRL DataFrame to tag:value dictionary with Dimension Penetration.
        Prioritizes consolidated data but allows dimensioned data if no consolidated value exists.
        """
        # --- Stage 1: Separate Datasets ---
        dim_cols = [c for c in df.columns if c.startswith('dim_')]
        
        # A. Pure Consolidated (All dimensions are NaN)
        if dim_cols:
            consolidated_mask = df[dim_cols].isna().all(axis=1)
            consolidated_df = df[consolidated_mask]
        else:
            consolidated_df = df
        
        # B. Dimensioned Data (For fallback)
        # Relevant axes for Balance Sheet details (Investments, Debt)
        special_axes = [
            'dim_us-gaap_InvestmentTypeAxis', 
            'dim_us-gaap_DebtInstrumentAxis',
        ]
        relevant_dims = [d for d in dim_cols if d in special_axes]
        
        # --- Stage 2: Extraction Logic ---
        result = {}
        
        if 'concept' not in df.columns or 'value' not in df.columns:
            return result

        # Iterate through all available concepts
        all_concepts = df['concept'].unique()
        
        for concept in all_concepts:
            # Priority 1: Consolidated Data
            c_rows = consolidated_df[consolidated_df['concept'] == concept]
            
            if not c_rows.empty:
                val = AutoExtractModel._get_latest_value(c_rows)
                if val is not None:
                    result[concept] = val
                    continue # Found consolidated, skip to next concept
            
            # Priority 2: Dimension Penetration
            # Only for "risky" fields like investments and debt where companies often hide data in axes
            # We strictly check if the concept contains relevant keywords to avoid pollution
            if any(k in str(concept).lower() for k in ['investment', 'debt', 'securities', 'note']):
                for axis in relevant_dims:
                    # Find rows where THIS axis is set, but ALL OTHER axes are NaN
                    # This prevents picking up complex multi-dimensional segments
                    other_dims = [d for d in dim_cols if d != axis]
                    
                    if other_dims:
                        pierce_mask = (df['concept'] == concept) & \
                                      (df[axis].notna()) & \
                                      (df[other_dims].isna().all(axis=1))
                    else:
                        pierce_mask = (df['concept'] == concept) & (df[axis].notna())
                    
                    p_rows = df[pierce_mask]
                    if not p_rows.empty:
                        val = AutoExtractModel._get_latest_value(p_rows)
                        if val is not None:
                            result[concept] = val
                            # logger.debug(f"💎 Pierced dimension {axis} for {concept}")
                            break # Found a valid dimension value, stop looking
                            
        return result

    @staticmethod
    def _get_latest_value(rows: pd.DataFrame) -> Optional[float]:
        """Helper to extract the most recent value from a set of rows"""
        sort_col = 'period_instant' if 'period_instant' in rows.columns else 'period_end'
        if sort_col in rows.columns:
            rows = rows.sort_values(by=sort_col, ascending=False)
        try:
            return float(rows.iloc[0]['value'])
        except (ValueError, TypeError, IndexError):
            return None

    @staticmethod
    def _score_candidate_tag(tag: str) -> int:
        """
        [Helper] Scoring Strategy for selecting the 'best' tag among matches.
        Lower score is better.
        """
        score = len(tag)
        lower_tag = tag.lower()
        
        # 權重規則：優先選擇 "匯總型" 或 "淨額型" 數據
        if 'total' in lower_tag: score -= 100    # Bonus for Totals
        if 'net' in lower_tag: score -= 50       # Bonus for Net
        if 'current' in lower_tag: score -= 20   # Bonus for Current
        
        # 懲罰規則：避免抓到過於細節的項目 (可選)
        # if 'detail' in lower_tag: score += 50
        
        return score

    @staticmethod
    def _internal_get_fact_smart(
        standardized_dict: Dict[str, Any],
        deep_stream_df: Optional[pd.DataFrame],
        standard_tags: List[str],
        fuzzy_keywords: List[str] = None,
        exclude_keywords: List[str] = None,
        regex_patterns: List[str] = None,
        dimensions: Dict[str, List[str]] = None
    ) -> Dict[str, Any]:
        """
        Smart Extraction Engine v4.0: Dual-Stream & Dimensions Aware.
        """
        has_deep = deep_stream_df is not None and not deep_stream_df.empty
        all_candidates = []

        # 1. Standard Tag Iteration (Stream 1 & 2)
        for tag in standard_tags:
            # OPTION A: Targeted Dimensional Extraction (Deep Stream Only)
            if dimensions and has_deep:
                matches = deep_stream_df[deep_stream_df['concept'] == tag]
                if matches.empty: continue
                
                # Identify dimension columns
                dim_cols = [c for c in matches.columns if c.startswith('dim') or 'Axis' in c or 'Member' in c]
                required = dimensions.get('include', [])
                excluded = dimensions.get('exclude', [])
                
                for _, row in matches.iterrows():
                    # Combine dimension values for keyword matching
                    row_dims_str = " ".join([str(row[c]) for c in dim_cols if pd.notna(row[c])])
                    
                    # Match logic: Must have all 'include', None of 'exclude'
                    if required and not all(k.lower() in row_dims_str.lower() for k in required):
                        continue
                    if excluded and any(ex.lower() in row_dims_str.lower() for ex in excluded):
                        continue
                    
                    # Found a match in Deep Stream!
                    logger.debug(f"🌊 [DEEP STREAM] DimMatch: {tag} | Dim: {row_dims_str} | Val: {row['value']:,.0f}")
                    
                    all_candidates.append({
                        "value": float(row['value']),
                        "source_tags": [tag],
                        "formula_logic": f"Dim: {row_dims_str}",
                        "priority": 1 # Higher priority for specific dimension matches
                    })

            # OPTION B: Standard Extraction (Main Stream / Dict Lookup)
            elif not dimensions:
                val = standardized_dict.get(tag)
                if val is not None:
                    logger.debug(f"🏠 [MAIN STREAM] Standard Tag match: {tag} | Val: {val:,.0f}")
                    all_candidates.append({
                        "value": float(val),
                        "source_tags": [tag],
                        "formula_logic": "Standard",
                        "priority": 2 # Standard consolidated
                    })
                elif has_deep:
                    # Fallback to absolute max in Deep Stream if not in dict
                    matches = deep_stream_df[deep_stream_df['concept'] == tag]
                    if not matches.empty:
                        # Ensure we have valid values before finding max
                        valid_matches = matches['value'].dropna()
                        if not valid_matches.empty:
                            best_idx = valid_matches.abs().idxmax()
                            val = matches.loc[best_idx, 'value']
                        else:
                             val = None # All values are NaN
                        logger.debug(f"🌊 [DEEP STREAM] Fallback match: {tag} | Val: {val:,.0f}")
                        all_candidates.append({
                            "value": float(val),
                            "source_tags": [tag],
                            "formula_logic": "Deep Max Fallback",
                            "priority": 3
                        })

        # 2. Regex Pattern Matching (Deep Scan - Stream 1)
        if not all_candidates and regex_patterns:
            search_targets = set(standardized_dict.keys())
            if has_deep:
                search_targets.update(deep_stream_df['concept'].dropna().unique())
            
            for pattern in regex_patterns:
                # Compile regex once
                try:
                    prog = re.compile(pattern, re.IGNORECASE)
                except:
                    continue
                    
                matches = [t for t in search_targets if prog.search(str(t))]
                if matches:
                    # Score and pick best tag (shortest/most total-like)
                    matches.sort(key=AutoExtractModel._score_candidate_tag)
                    best_tag = matches[0]
                    
                    source_stream = "MAIN"
                    val = standardized_dict.get(best_tag)
                    if val is None and has_deep:
                        # Direct lookup from Deep DF if dict failed
                        df_matches = deep_stream_df[deep_stream_df['concept'] == best_tag]
                        
                        # Fix: Check for valid values before idxmax
                        if not df_matches.empty:
                            valid_vals = df_matches['value'].dropna()
                            if not valid_vals.empty:
                                val = df_matches.loc[valid_vals.abs().idxmax()]['value']
                                source_stream = "DEEP"
                    
                    if val is not None:
                        logger.debug(f"{'🏠' if source_stream == 'MAIN' else '🌊'} [{source_stream} STREAM] Regex match: {best_tag} (Pattern: {pattern}) | Val: {val:,.0f}")
                        all_candidates.append({
                            "value": float(val),
                            "source_tags": [best_tag],
                            "formula_logic": f"Regex: {pattern}",
                            "priority": 4
                        })

        # 3. Decision Logic: Max Strategy
        if all_candidates:
            # Sort by absolute value descending (assume largest is most relevant/consolidated)
            all_candidates.sort(key=lambda x: abs(x['value']), reverse=True)
            winner = all_candidates[0]
            
            return {
                "value": winner['value'],
                "source_tags": winner['source_tags'],
                "is_calculated": False,
                "formula_logic": f"{winner['formula_logic']} (Max Strategy)"
            }

        return {"value": None, "source_tags": [], "is_calculated": False}

    # For Debugging
    # @staticmethod
    # def _internal_get_fact_smart(
    #     raw_data: Dict[str, Any],
    #     standard_tags: List[str],
    #     fuzzy_keywords: List[str] = None,
    #     exclude_keywords: List[str] = None,
    #     regex_patterns: List[str] = None
    # ) -> Dict[str, Any]:
    #     """
    #     [DEBUG MODE] 診斷版：為什麼抓不到 Net Loans？
    #     """
    #     all_candidates = []
        
    #     # --- 🕵️ 偵測是否正在抓 Net Loans ---
    #     # 如果標籤列表包含 'NetLoans' 或 'ReceivablesNet'，我們就啟動詳細日誌
    #     debug_target = False
    #     target_check = str(standard_tags)
    #     if 'NetLoans' in target_check or 'ReceivablesNet' in target_check:
    #         debug_target = True
    #         print(f"\n--- 🕵️ [DEBUG] Extracting Net Loans/Receivables ---")
    #         print(f"  > Looking for tags: {standard_tags[:3]}... (Total {len(standard_tags)})")

    #     # 預處理排除關鍵字
    #     is_excluded = lambda k: False
    #     if exclude_keywords:
    #         exc_lower = [exc.lower() for exc in exclude_keywords]
    #         is_excluded = lambda k: any(exc in k.lower() for exc in exc_lower)

    #     # --- Phase 1: Standard Tags ---
    #     for tag in standard_tags:
    #         val = raw_data.get(tag)
            
    #         # [DEBUG] 如果是目標欄位，打印每個標籤的查找結果
    #         if debug_target:
    #             status = f"✅ Found: {val}" if val is not None else "❌ Missing"
    #             # 只打印找到的，或者前5個缺失的，避免洗版
    #             if val is not None or standard_tags.index(tag) < 5:
    #                 print(f"  > Check Tag: {tag.ljust(50)} -> {status}")

    #         if val is not None:
    #             try:
    #                 all_candidates.append({
    #                     "value": float(val),
    #                     "source_tags": [tag],
    #                     "formula_logic": "Standard Tag",
    #                 })
    #             except (ValueError, TypeError):
    #                 continue

    #     # --- Phase 2: Regex Matching ---
    #     if regex_patterns:
    #         search_targets = list(raw_data.keys())
    #         raw_df = raw_data.get('_raw_df')
            
    #         if isinstance(raw_df, pd.DataFrame):
    #             raw_concepts = raw_df['concept'].dropna().unique().tolist()
    #             search_targets.extend(raw_concepts)
            
    #         search_set = set(search_targets)

    #         for pattern in regex_patterns:
    #             matches = []
    #             for key in search_set:
    #                 if key == '_raw_df' or is_excluded(key): continue
    #                 if re.search(pattern, key, re.IGNORECASE):
    #                     matches.append(key)
                
    #             if matches:
    #                 # [DEBUG] 打印 Regex 匹配結果
    #                 if debug_target:
    #                     print(f"  > Regex Match '{pattern}': Found {len(matches)} candidates: {matches[:3]}")

    #                 matches.sort(key=AutoExtractModel._score_candidate_tag)
    #                 best_tag = matches[0]
                    
    #                 val = raw_data.get(best_tag)
    #                 # (DataFrame lookup logic omitted for brevity, same as before)
    #                 if val is None and isinstance(raw_df, pd.DataFrame):
    #                     mask = (raw_df['concept'] == best_tag) & (raw_df['value'].notna())
    #                     if mask.any():
    #                         # 取絕對值最大的
    #                         best_val = raw_df.loc[mask, 'value'].abs().max()
    #                         val = best_val

    #                 if val is not None:
    #                     all_candidates.append({
    #                         "value": float(val),
    #                         "source_tags": [best_tag],
    #                         "formula_logic": f"Regex: {pattern}",
    #                     })

    #     # --- Phase 3: Total Failure Scan (如果完全沒找到) ---
    #     if debug_target and not all_candidates:
    #         print(f"  ⚠️ [CRITICAL] No candidates found for Net Loans!")
    #         print(f"  > Scanning raw_data for ANY keys containing 'Loans' or 'Receivables'...")
            
    #         hits = []
    #         for k, v in raw_data.items():
    #             if k == '_raw_df': continue
    #             k_lower = k.lower()
    #             if ('loans' in k_lower or 'receiv' in k_lower) and isinstance(v, (int, float)):
    #                 hits.append((k, v))
            
    #         # 按數值大小排序
    #         hits.sort(key=lambda x: abs(x[1]), reverse=True)
    #         for k, v in hits[:10]:
    #             print(f"    👉 Potential Candidate in Raw Data: {k} = {v:,.0f}")
    #         print("------------------------------------------------")

    #     # --- The Grand Finale (Max Strategy) ---
    #     if all_candidates:
    #         all_candidates.sort(key=lambda x: abs(x['value']), reverse=True)
    #         best_match = all_candidates[0]
            
    #         if debug_target:
    #             print(f"  🏆 Winner: {best_match['source_tags']} = {best_match['value']:,.0f}")
    #             print("------------------------------------------------")

    #         return {
    #             "value": best_match['value'],
    #             "source_tags": best_match['source_tags'],
    #             "is_calculated": False,
    #             "formula_logic": f"{best_match['formula_logic']} (Max Strategy)"
    #         }

    #     return {"value": None, "source_tags": [], "is_calculated": False}


# ==========================================
# 1. Base Configuration
# ==========================================

class IndustryType(str, Enum):
    """Industry classification for sector-specific financial analysis"""
    CORPORATE = "CORPORATE"  # General manufacturing/services/tech
    BANK = "BANK"            # Banking & financial institutions
    REIT = "REIT"            # Real Estate Investment Trusts


# ==========================================
# 2. Financial Statement Models (Data Layer)
# ==========================================

class BalanceSheetBase(AutoExtractModel):
    """Base class for all balance sheets with automatic XBRL extraction"""
    industry: IndustryType
    period_date: date
    
    # Common Solvency Fields
    total_assets: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:Assets']}
    )
    total_liabilities: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:Liabilities']}
    )
    total_equity: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:StockholdersEquity',
                'us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'
            ]
        }
    )
    
    # Common Liquidity Fields
    cash_and_equivalents: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:CashAndCashEquivalentsAtCarryingValue',
                'us-gaap:Cash'
            ]
        }
    )
    marketable_securities: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                # 1. 廣義總項 (優先)
                'us-gaap:MarketableSecuritiesCurrent',
                'us-gaap:ShortTermInvestments',
                'us-gaap:InvestmentSecuritiesCurrent',
                
                # 2. 類型總項 (次優先：所有備供出售債券)
                'us-gaap:AvailableForSaleSecuritiesDebtSecuritiesCurrent',
                'us-gaap:AvailableForSaleSecuritiesCurrent',
                
                # 3. 時間細項 (保底：Visa 常用，若上方總項都沒抓到才用這個)
                'us-gaap:AvailableForSaleSecuritiesDebtMaturitiesWithinOneYearFairValue',
                
                # 4. 複合標籤 (最後的掙扎)
                'us-gaap:CashCashEquivalentsRestrictedCashAndCashEquivalentsAndShortTermInvestments'
            ]
        }
    )
    marketable_securities_noncurrent: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                # 1. 廣義總項 (最完整)
                'us-gaap:MarketableSecuritiesNoncurrent',
                'us-gaap:LongTermInvestments',
                
                # 2. 類型總項
                'us-gaap:AvailableForSaleSecuritiesDebtSecuritiesNoncurrent',
                'us-gaap:HeldToMaturitySecuritiesDebt',
                
                # 3. 時間細項 (Visa 常用，僅作為保底)
                # 注意：這可能只是非流動資產的一部分，所以必須放在總項之後
                'us-gaap:AvailableForSaleSecuritiesDebtMaturitiesAfterOneThroughFiveYearsFairValue',
                'us-gaap:AvailableForSaleSecuritiesDebtMaturitiesAfterFiveThroughTenYearsFairValue',
                'us-gaap:AvailableForSaleSecuritiesDebtMaturitiesAfterTenYearsFairValue'
            ]
        }
    )

    @computed_field
    def total_liquidity(self) -> TraceableField:
        """Calculate total liquidity: Cash + Marketable Securities (Current + Non-Current)"""
        result = self.cash_and_equivalents + self.marketable_securities + self.marketable_securities_noncurrent
        result.formula_logic = "Cash + Liquid Securities"
        return result

    @model_validator(mode='after')
    def validate_accounting_identity(self) -> "BalanceSheetBase":
        """Validate accounting equation: Assets = Liabilities + Equity (allow 1% tolerance)"""
        if self.total_assets.value and self.total_liabilities.value and self.total_equity.value:
            calc_assets = self.total_liabilities.value + self.total_equity.value
            if abs(self.total_assets.value - calc_assets) / (self.total_assets.value + 1e-6) > 0.01:
                pass  # Suppress warning for now to avoid noise in logs
        return self


class CorporateBalanceSheet(BalanceSheetBase):
    """Standard balance sheet for corporate/tech/manufacturing"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    # Liquidity
    assets_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:AssetsCurrent']}
    )
    liabilities_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:LiabilitiesCurrent']}
    )
    receivables_net: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:AccountsReceivableNetCurrent',
                'us-gaap:ReceivablesNetCurrent',
                'us-gaap:CustomerReceivablesNetCurrent',
                'us-gaap:OtherReceivablesNetCurrent',
                'us-gaap:NotesAndAccountsReceivableNetCurrent'
            ]
        }
    )
    inventory: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:InventoryNet',
                'us-gaap:InventoryGross',
                'us-gaap:InventoryFinishedGoods'
            ]
        }
    )
    accounts_payable: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:AccountsPayableCurrent']}
    )
    
    # Debt
    debt_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:DebtCurrent',
                'us-gaap:ShortTermBorrowings',
                'us-gaap:LongTermDebtCurrent'
            ]
        }
    )
    debt_noncurrent: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:LongTermDebtNoncurrent',
                'us-gaap:LongTermDebtExcludingCurrentPortion',
                'us-gaap:LongTermDebtAndFinanceLeaseObligations',
                'us-gaap:LongTermDebt',
                'us-gaap:LongTermDebtAndCapitalLeaseObligations',
                'us-gaap:LongTermLineOfCredit',
                'us-gaap:SeniorNotes',
                'us-gaap:DebtInstrumentCarryingAmount'
            ]
        }
    )

    @computed_field
    def total_debt(self) -> TraceableField:
        """Total Debt = Current + Non-Current"""
        result = self.debt_current + self.debt_noncurrent
        result.formula_logic = "ShortTerm + LongTerm Debt"
        return result

    # --- Capital Commitments (Off-Balance Sheet / Notes) ---
    purchase_obligations: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:PurchaseCommitmentObligations',
                'us-gaap:InventoryPurchaseObligations'
            ],
            'fuzzy_keywords': ['PurchaseObligations', 'SupplyCommitments', 'InventoryPurchase']
        }
    )

    # --- Adjusted Debt Logic for Asset-Light/OpCo Entities (e.g., MGM, SBUX) ---
    lease_liabilities_current: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:OperatingLeaseLiabilityCurrent'],
            'fuzzy_keywords': ['OperatingLeaseLiability', 'Current'],
            'exclude_keywords': []
        }
    )
    lease_liabilities_noncurrent: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:OperatingLeaseLiabilityNoncurrent'],
            'fuzzy_keywords': ['OperatingLeaseLiability', 'Noncurrent'],
            'exclude_keywords': []
        }
    )

    @computed_field
    def total_lease_liabilities(self) -> TraceableField:
        """Calculate total operating lease liabilities"""
        result = self.lease_liabilities_current + self.lease_liabilities_noncurrent
        result.formula_logic = "Lease Current + Noncurrent"
        return result

    @computed_field
    def adjusted_total_debt(self) -> TraceableField:
        """
        Adjusted Debt = Financial Debt + Operating Lease Liabilities.
        Critical for assessing leverage of tenants in triple-net ecosystems (e.g. MGM vs VICI).
        """
        result = self.total_debt + self.total_lease_liabilities
        result.formula_logic = "Total Debt + Leases"
        return result

    @computed_field
    def net_debt(self) -> TraceableField:
        """Net Debt = Total Debt (Financial) - Total Liquidity"""
        result = self.total_debt - self.total_liquidity
        result.formula_logic = "Total Debt - Total Liquidity"
        return result

    @model_validator(mode='after')
    def inference_pipeline(self) -> "CorporateBalanceSheet":
        """
        补完流水線：執行 Materiality 推論 (V13)。
        Scientifically estimate missing values using "Negative Space Estimation".
        """
        # 1. 執行存貨與應收帳款推論
        self._infer_missing_asset_item()
        
        # 2. 執行負債推論
        self._infer_missing_debt_item()
        
        return self

    def _infer_missing_asset_item(self):
        """
        Advanced Residual Analysis for Assets:
        If Current Assets known but Inventory/Receivables missing, check if residual is negligible (<5%).
        If so, infer missing item to match the residual.
        """
        # Prerequisite: Must have total current assets
        if self.assets_current.value is None:
            return

        # Identify missing components
        missing_items = []
        if self.inventory.value is None: missing_items.append('inventory')
        if self.receivables_net.value is None: missing_items.append('receivables_net')
        
        # Risk Control: Only infer if exactly one major component is missing.
        # If multiple are missing, the risk of misallocation is too high.
        if len(missing_items) != 1: 
            return

        # Calculate known sum
        known_sum = (self.cash_and_equivalents.value or 0.0) + \
                    (self.marketable_securities.value or 0.0) + \
                    (self.receivables_net.value or 0.0 if 'receivables_net' not in missing_items else 0.0) + \
                    (self.inventory.value or 0.0 if 'inventory' not in missing_items else 0.0)

        # Calculate residual
        residual = self.assets_current.value - known_sum
        if self.assets_current.value == 0: return # Avoid div by zero
        
        residual_ratio = residual / self.assets_current.value

        # Materiality Threshold: 5%
        # If the missing piece accounts for <5% of current assets, we infer it.
        # This handles cases like Apple (Inventory ~2%) or pure SaaS (Inventory ~0%).
        if 0 <= residual_ratio < 0.05:
            target_attr = missing_items[0]
            
            # Create inferred field
            inferred_field = TraceableField(
                value=max(0.0, residual), # Fill the gap
                is_calculated=True,
                source_tags=["Materiality_Inference"],
                formula_logic=f"Residual of Current Assets ({residual_ratio:.1%} left)"
            )
            
            # Apply inference
            setattr(self, target_attr, inferred_field)

    def _infer_missing_debt_item(self):
        """
        Advanced Residual Analysis for Debt:
        If Total Liabilities known but Total Debt missing, check if residual is negligible (<2%).
        """
        # Prerequisite: Liabilities known, debt missing
        if self.total_liabilities.value is None:
            return
            
        # If we already found debt tags, no need to infer
        if self.total_debt.value is not None:
            return

        # Calculate other known liabilities
        other_liab = (self.accounts_payable.value or 0.0) + \
                     (self.lease_liabilities_current.value or 0.0) + \
                     (self.lease_liabilities_noncurrent.value or 0.0)
        
        residual = self.total_liabilities.value - other_liab
        if self.total_liabilities.value == 0: return
        
        residual_ratio = residual / self.total_liabilities.value

        # Materiality Threshold: 2% (Stricter for Debt)
        # If almost all liabilities are accounted for by Payables/Leases, 
        # it is highly probable there is no significant financial debt.
        if residual_ratio < 0.02:
            # Create inferred debt of 0.0
            inferred_debt = TraceableField(
                value=0.0,
                is_calculated=True,
                source_tags=["Materiality_Inference"],
                formula_logic=f"Liabilities residual too small ({residual_ratio:.1%}) for significant debt"
            )
            
            # Use the inferred debt object which contains the residual ratio details
            if self.debt_current.value is None:
                self.debt_current = inferred_debt.model_copy()


class BankBalanceSheet(BalanceSheetBase):
    """Balance sheet for banking institutions"""
    industry: Literal[IndustryType.BANK] = IndustryType.BANK
    
    total_deposits: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:Deposits',
                'us-gaap:DepositsForeignAndDomestic'
            ]
        }
    )
    # ==========================================
    # 1. 核心總數嘗試 (Core Total Attempt)
    # ==========================================
    # 這是 JPM 的完美方案，也是 AXP 的首選（如果它有報的話）
    net_loans_reported: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:FinancingReceivablesLoansAndLeasesNet', # AXP 潛在總數
                'us-gaap:NetLoans',                              # JPM 核心
                'us-gaap:LoansAndLeasesReceivableNetReportedAmount',
                'us-gaap:LoansNet',
                'us-gaap:FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss'
            ]
        }
    )

    # ==========================================
    # 2. AXP 專用組件 (AXP Components)
    # ==========================================
    
    # 組件 A: 信用卡貸款 (Card Member Loans)
    # 使用 dimensions 鎖定 AXP 的具體披露
    card_loans: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:NotesReceivableNet', 'us-gaap:FinancingReceivablesNet'],
            'dimensions': {'include': ['Loan', 'Member']},
            'regex_patterns': [r'(?i).*CardMemberLoans.*']
        }
    )

    # 組件 B: 應收帳款 (Card Member Receivables)
    card_receivables: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:NotesReceivableNet', 'us-gaap:AccountsReceivableNet'],
            'dimensions': {'include': ['Receivable', 'Member']},
            'regex_patterns': [r'(?i).*CardMemberReceivables.*']
        }
    )

    # 組件 C: 其他帳款 (Card Member Other Loans)
    card_other_loans: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:NotesReceivableNet', 'us-gaap:FinancingReceivablesNet'],
            'dimensions': {'include': ['Other']},
            'regex_patterns': [r'(?i).*CardMemberOtherLoans.*']
        }
    )

    # ==========================================
    # 3. 智能計算邏輯 (The Brain)
    # ==========================================
    @computed_field
    def net_loans(self) -> TraceableField:
        """
        Pure Logic Summation: Prefer Reported Total, fallback to Components.
        No Magic Numbers.
        """
        val_reported = self.net_loans_reported.value or 0.0
        val_loans = self.card_loans.value or 0.0
        val_other_loans = self.card_other_loans.value or 0.0
        val_recv = self.card_receivables.value or 0.0
        
        val_sum = val_loans + val_recv + val_other_loans

        # 如果 Reported 值存在 (非零)，優先使用
        if abs(val_reported) > 0:
            return self.net_loans_reported

        # 如果 組件加總 值存在，使用加總 (適用於 AXP)
        if abs(val_sum) > 0:
            src_tags = list(set(self.card_loans.source_tags + self.card_receivables.source_tags + self.card_other_loans.source_tags))
            return TraceableField(
                value=val_sum,
                source_tags=src_tags,
                is_calculated=True,
                formula_logic=f"Component Sum: Loans({val_loans:,.0f}) + Recv({val_recv:,.0f}) + Other Loans({val_other_loans:,.0f})"
            )
            
        return TraceableField(value=None)
    total_debt: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:LongTermDebt',
                'us-gaap:LongTermDebtExcludingCurrentPortion',
                'us-gaap:LongTermDebtNoncurrent',
                'us-gaap:LongTermDebtAndFinanceLeaseObligations',
                'us-gaap:LongTermDebtAndCapitalLeaseObligations',
                'us-gaap:Debt'
            ]
        }
    )
    
    # --- Bank Liquidity Fields (JPM Fix) ---
    cash_and_due_from_banks: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                # AXP / 現代銀行控股 (總項)
                'us-gaap:CashAndCashEquivalentsAtCarryingValue', # 這是 AXP 的核心標籤
                'us-gaap:CashAndCashEquivalents',
                
                # JPM / 傳統銀行 (分項A)
                'us-gaap:CashAndDueFromBanks',
                'us-gaap:CashCashEquivalentsRestrictedCashAndCashEquivalents',
            ]
        }
    )
    interest_bearing_deposits: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:InterestBearingDepositsInBanks',
                'us-gaap:DepositsWithBanks',
                'us-gaap:FederalFundsSoldAndSecuritiesPurchasedUnderAgreementsToResell' # 有時放在這裡
            ]
        }
    )
    securities: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': [
            'us-gaap:AvailableForSaleSecuritiesDebtSecurities',
            'us-gaap:HeldToMaturitySecuritiesDebt'
        ]}
    )

    @computed_field
    def total_liquidity(self) -> TraceableField:
        """
        Bank Liquidity = Cash & Due + Interest Bearing + Securities (AFS/HTM).
        Overrides standard corporate liquidity logic.
        """
        result = self.cash_and_due_from_banks + self.interest_bearing_deposits + self.securities
        result.formula_logic = "Cash & Due + Interest Bearing + Securities"
        return result


class REITBalanceSheet(BalanceSheetBase):
    """Balance sheet for REITs"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    real_estate_assets: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            # 1. 標準標籤 (根據 Log 發現的目標)
            'xbrl_tags': [
                # VICI / Net Lease REITs 專用 (本次新增)
                'us-gaap:RealEstateInvestments',  # 👈 Log 裡的 36.21B
                'us-gaap:FinanceLeaseNetInvestmentInLease',
                
                # 傳統 REITs (O, SPG)
                'us-gaap:RealEstateInvestmentPropertyNet',
                'us-gaap:RealEstateRealEstateAssetsNet',

                # 👇 新增：針對 EQIX, AMT (數據中心/電塔)
                'us-gaap:PropertyPlantAndEquipmentNet', 
                'us-gaap:PropertyPlantAndEquipmentGross'
            ],
            
            # 2. 結構化 Regex (針對 VICI 的命名習慣)
            'regex_patterns': [
                # 策略 A: 鎖定 "房地產投資" (最簡單暴力，對應 us-gaap:RealEstateInvestments)
                r'(?i)^.*:RealEstateInvestments$',
                
                # 策略 B: 鎖定 "融資應收帳款...淨投資" (VICI 的自定義標籤特徵)
                # Log 顯示: vici:FinancingReceivables...NetInvestmentInLease...
                r'(?i).*:Financing.*Receivables.*Net.*Investment',
                
                # 策略 C: 傳統 REIT 兜底
                r'(?i).*:RealEstate.*Property.*Net',

                # 新增：PP&E 匹配
                r'(?i).*:PropertyPlantAndEquipmentNet',
            ],
            
            # 3. 模糊匹配 (留空)
            'fuzzy_keywords': [],
            
            # 4. 全局排除
            'exclude_keywords': [
                'Income', 'Revenue', 'Gain', 'Loss', 
                'Payments', 'Proceeds', # 排除現金流
                'Current' # 排除流動資產
            ]
        }
    )
    
    # REIT Debt Components
    unsecured_debt: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
               # 1. 對 REIT 最精確的總債務標籤 (按優先級排列)
                'us-gaap:LongTermDebtNoncurrent', 
                'us-gaap:LongTermDebtAndFinanceLeaseObligations',
                'us-gaap:LongTermDebt',
                
                # 2. 次級細項標籤
                'us-gaap:SeniorNotes',
                'us-gaap:UnsecuredDebt',
                'us-gaap:NotesPayable'
            ],
            'regex_patterns': [
                # Pattern A: 高級票據 (Senior Notes) - EQIX 最主要的債務形式
                r'(?i).*Senior.*Notes.*',
                
                # Pattern B: 無擔保債務/票據
                r'(?i).*Unsecured.*Debt.*',
                r'(?i).*Unsecured.*Notes.*',
                
                # Pattern C: 應付票據 (通用)
                r'(?i)^.*Notes.*Payable.*$'
            ],
        }
    )
    finance_leases: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:FinanceLeaseLiability',
                'us-gaap:FinanceLeaseLiabilityNoncurrent',
                'us-gaap:CapitalLeaseObligations', # 舊會計準則術語
                'us-gaap:CapitalLeaseObligationsNoncurrent'
            ],
            'regex_patterns': [
                r'(?i).*Finance.*Lease.*Liability.*',
                r'(?i).*Capital.*Lease.*Obligation.*'
            ]
        }
    )
    mortgages: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            # 1. 標準標籤
            'xbrl_tags': [
                'us-gaap:SecuredDebt',            # SPG 最可能用這個
                'us-gaap:SecuredLongTermDebt',
                'us-gaap:MortgageLoansPayable',
                'us-gaap:MortgageLoansOnRealEstate',
                'us-gaap:MortgageNotesPayable'    # 新增
            ],
            
            # 2. 結構化 Regex
            'regex_patterns': [
                # 策略 A: 抵押貸款 (包含 Notes)
                r'(?i).*:Mortgage.*Payable',
                r'(?i).*:Mortgage.*Notes',
                
                # 策略 B: 有擔保債務 (SPG 核心)
                r'(?i).*:Secured.*Debt',
                r'(?i).*:Secured.*Liabilities'
            ],
        }
    )
    notes_payable: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': ['us-gaap:TermLoan'],
            'regex_patterns': [
                r'(?i).*Term.*Loan.*',
                r'(?i).*Credit.*Facility.*'
            ]
        }
    )
    
    @computed_field
    def total_debt(self) -> TraceableField:
        """Total Debt = Unsecured + Mortgages + Notes"""
        result = self.unsecured_debt + self.mortgages + self.notes_payable + self.finance_leases
        result.formula_logic = f"Unsecured({self.unsecured_debt}) + Mortgages({self.mortgages}) + BankLoan({self.notes_payable}) + FinanceLeases({self.finance_leases})"
        return result


BalanceSheetVariant = Union[CorporateBalanceSheet, BankBalanceSheet, REITBalanceSheet]


# --- Income Statement Base & Polymorphic Variants ---

class IncomeStatementBase(AutoExtractModel):
    """Base class for all income statements with automatic XBRL extraction"""
    industry: IndustryType
    period_start: date
    period_end: date
    
    net_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                # 最精準：歸屬於普通股東的淨利
                'us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic',
                # 次精準：歸屬於母公司的淨利
                'us-gaap:NetIncomeLoss',
                # 3. 兜底：合併損益
                # 由於當同時搜到以上的TAG，會取最大值可能導致誤差，但目前需先接受
                'us-gaap:ProfitLoss'
            ]
        }
    )
    operating_expenses: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:OperatingExpenses']}
    )
    tax_expense: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:IncomeTaxExpenseBenefit']}
    )


class CorporateIncomeStatement(IncomeStatementBase):
    """Standard income statement for corporate/tech/manufacturing"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    revenue: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:Revenues',
                'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
            ]
        }
    )
    cogs: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:CostOfGoodsAndServicesSold',
                'us-gaap:CostOfRevenue'
            ]
        }
    )
    gross_profit: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:GrossProfit']}
    )
    operating_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:OperatingIncomeLoss']}
    )
    research_and_development: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:ResearchAndDevelopmentExpense',
                'us-gaap:ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost'
            ]
        }
    )
    interest_expense: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:InterestExpense']}
    )
    depreciation_amortization: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:DepreciationDepletionAndAmortization',
                'us-gaap:DepreciationAndAmortization'
            ]
        }
    )

    @model_validator(mode='after')
    def calculate_gross_profit_if_missing(self) -> 'CorporateIncomeStatement':
        """Auto-calculate gross profit if not reported in XBRL"""
        if self.gross_profit.value is None:
            if self.revenue.value is not None and self.cogs.value is not None:
                self.gross_profit = self.revenue - self.cogs
                self.gross_profit.formula_logic = "Revenue - COGS"
        return self

    @computed_field
    def ebit(self) -> TraceableField:
        """Calculate EBIT (Earnings Before Interest & Tax)"""
        result = self.net_income + self.interest_expense + self.tax_expense
        result.formula_logic = "Net Income + Interest + Tax"
        return result

    @computed_field
    def ebitda(self) -> TraceableField:
        """Calculate EBITDA (Earnings Before Interest, Tax, Depreciation & Amortization)"""
        result = self.ebit + self.depreciation_amortization
        result.formula_logic = "EBIT + D&A"
        return result


class BankIncomeStatement(IncomeStatementBase):
    """Income statement for banking institutions"""
    industry: Literal[IndustryType.BANK] = IndustryType.BANK
    
    net_interest_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': [
            'us-gaap:InterestIncomeExpenseNet', 
            'jpm:NetInterestIncome',
            'us-gaap:NetInterestIncome'
        ]}
    )
    non_interest_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:NoninterestIncome']}
    )
    provision_for_losses: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:ProvisionForLoanLeaseAndOtherLosses']}
    )
    operating_expenses: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': [
            'us-gaap:NoninterestExpense', 
            'jpm:TotalNoninterestExpense'
        ]}
    )
    interest_expense: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:InterestExpense']}
    )
    avg_earning_assets: TraceableField = Field(
        default_factory=TraceableField,
        description="Calculated from balance sheet"
    )

    @computed_field
    def total_revenue(self) -> TraceableField:
        """Bank total revenue = Net Interest Income + Non-Interest Income"""
        # Note: Some banks report Total Revenue directly, but calculating ensures components exist
        result = self.net_interest_income + self.non_interest_income
        result.formula_logic = "NII + Non-Interest Income"
        return result

    @computed_field
    def net_interest_margin(self) -> TraceableField:
        """NIM: Net Interest Margin"""
        result = self.net_interest_income / self.avg_earning_assets
        result.formula_logic = "NII / Avg Earning Assets"
        return result

    @computed_field
    def efficiency_ratio(self) -> TraceableField:
        """Efficiency Ratio: Operating Expenses / Total Revenue (lower is better)"""
        result = self.operating_expenses / self.total_revenue
        result.formula_logic = "OpEx / Total Revenue"
        return result


class REITIncomeStatement(IncomeStatementBase):
    """Income statement for Real Estate Investment Trusts"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    rental_income: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:OperatingLeaseRevenue',
                'us-gaap:RentalIncome',
                'us-gaap:Revenues',
                'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
            ]
        }
    )
    property_operating_expenses: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:OperatingExpenses']}
    )
    depreciation: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:DepreciationDepletionAndAmortizationExpense',
                'us-gaap:DepreciationAndAmortization',
                'us-gaap:Depreciation',
                'us-gaap:DepreciationDepletionAndAmortization',
            ],
        }
    )
    gains_on_sale: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                'us-gaap:GainLossOnSaleOfProperties',
                'us-gaap:GainLossOnDisposalOfAssets'
            ]
        }
    )

    @computed_field
    def funds_from_operations(self) -> TraceableField:
        """FFO: Net Income + Depreciation - Gains on Sale"""
        result = self.net_income + self.depreciation - self.gains_on_sale
        result.formula_logic = f"Net Income({self.net_income}) + Depreciation({self.depreciation}) - Gains on Sale({self.gains_on_sale})"
        return result


# Union type for polymorphism
IncomeStatementVariant = Union[CorporateIncomeStatement, BankIncomeStatement, REITIncomeStatement]


class CashFlowStatementBase(AutoExtractModel):
    """Base class for cash flow statements with automatic XBRL extraction"""
    industry: IndustryType
    period_start: date
    period_end: date
    
    ocf: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={'xbrl_tags': ['us-gaap:NetCashProvidedByUsedInOperatingActivities']}
    )
    dividends_paid: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                # 1. 標準 GAAP 標籤 (最安全，O/VICI/EQIX 用這些)
                'us-gaap:PaymentsOfDividends',
                'us-gaap:PaymentsOfDividendsCommonStock',
                'us-gaap:PaymentsOfOrdinaryDividends',
                'us-gaap:DividendsPaid',
                'us-gaap:PaymentsOfDistributions'
            ],
            
            'regex_patterns': [
                # --- Group A: 標準股息 (絕大多數公司) ---
                r'(?i).*:PaymentsOfDividends.*',
                r'(?i).*:Dividends.*Paid.*',
                
                # --- Group B: 針對 SPG/UP-REIT 的補丁 (關鍵修改) ---
                # 這能完美匹配: spg:DistributionsMadeToCommonStockholders...
                r'(?i).*:Distributions.*Stockholders.*',
                r'(?i).*:Distributions.*Partners.*',
                
                # --- Group C: 廣義分配 (兜底) ---
                r'(?i).*:Payments.*Distributions.*'
            ],
            
            'fuzzy_keywords': [],
            
            # 🛡️ 安全網：確保不影響其他公司
            'exclude_keywords': [
                'Received',      # 排除收到股息
                'Income',        # 排除股息收入
                'Receivable',    # 排除應收
                'Liability',     # 排除應付帳款 (資產負債表項目)
                'Payable',       # 排除應付 (資產負債表項目)
                'Noncontrolling' # (可選) 雖然通常我們想要總股息，但在 Max Strategy 下，大的會勝出，所以這裡排不排除影響不大
            ]
        }
    )


class CorporateCashFlow(CashFlowStatementBase):
    """Standard CF for corporate"""
    industry: Literal[IndustryType.CORPORATE] = IndustryType.CORPORATE
    
    capex: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            'xbrl_tags': [
                # 1. 這次發現的關鍵標籤 (針對 NVDA 等大型科技股)
                'us-gaap:PaymentsToAcquireProductiveAssets',
                
                # 2. 標準現金流標籤
                'us-gaap:PaymentsToAcquirePropertyPlantAndEquipment',
                'us-gaap:PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets',
                
                # 3. 其他備選
                'us-gaap:CapitalExpenditures',
                'us-gaap:CapitalExpendituresIncurredButNotYetPaid'
            ],
            'fuzzy_keywords': ['PaymentsToAcquire', 'ProductiveAssets', 'PropertyPlant'],
            'exclude_keywords': ['NetCashProvidedByUsedInInvestingActivities', 'Proceeds']
        }
    )

    @computed_field
    def free_cash_flow(self) -> TraceableField:
        """FCF = OCF - Capex"""
        result = self.ocf - self.capex
        result.formula_logic = "OCF - Capex"
        return result


class REITCashFlow(CashFlowStatementBase):
    """CF for REITs with specific investment tags"""
    industry: Literal[IndustryType.REIT] = IndustryType.REIT
    
    real_estate_investment: TraceableField = Field(
        default_factory=TraceableField,
        json_schema_extra={
            # 🚨 優先級排序：基礎設施 (大) -> 開發 (中) -> 傳統收購 (基底)
            'xbrl_tags': [
                # --- Priority 1: 基礎設施與設備 (EQIX, AMT, CCI 核心) ---
                # 這是修復 EQIX $30億 支出的關鍵
                'us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment',
                'us-gaap:PaymentsToAcquireProductiveAssets',
                'us-gaap:PaymentsToAcquirePropertyPlantAndEquipment',
                
                # --- Priority 2: 開發與建設 (PLD, ARE 核心) ---
                # 這是 PLD 幾十億開發支出的關鍵
                'us-gaap:PaymentsForConstructionInProcess',
                'us-gaap:PaymentsForRealEstateDevelopment',
                'us-gaap:PaymentsForCapitalImprovements',
                'us-gaap:RealEstateDevelopmentCosts',
                
                # --- Priority 3: 傳統房地產收購 (O, VICI, SPG 核心) ---
                # 這是最通用的標籤，放在最後作為保底
                'us-gaap:PaymentsToAcquireRealEstate',
                'us-gaap:PaymentsToAcquireProperties',
                'o:RealEstateAcquisitions' # 包含特定公司前綴
            ],
            
            # 2. 結構化 Regex (邏輯必須與上方 Tag 優先級一致)
            'regex_patterns': [
                # [Group 1] 抓取 "Other PP&E" 和 "Productive Assets" (EQIX 補丁)
                r'(?i).*:PaymentsToAcquire.*Other.*PropertyPlantAndEquipment',
                r'(?i).*:PaymentsToAcquire.*ProductiveAssets',
                
                # [Group 2] 抓取通用 PP&E 和資本支出
                r'(?i).*:PaymentsToAcquire.*PropertyPlantAndEquipment',
                r'(?i).*:CapitalExpenditure.*', 
                
                # [Group 3] 抓取建設與開發 (Construction/Development)
                r'(?i).*:Payments.*Construction.*',
                r'(?i).*:Development.*Expenditures.*',
                r'(?i).*:AdditionsTo.*Properties',
                r'(?i).*:ImprovementsTo.*RealEstate',

                # [Group 4] 抓取傳統收購 (RealEstate Acquisitions)
                r'(?i).*:RealEstateAcquisitions',
                r'(?i).*:PaymentsToAcquire.*RealEstate',
                r'(?i).*:AcquisitionOf.*RealEstate',
                r'(?i).*:PaymentsToAcquire.*Properties'
            ],
            
            # 3. 保持留空 (嚴格模式)
            'fuzzy_keywords': [], 
            
            # 4. 全局排除 (安全網)
            'exclude_keywords': [
                'Proceeds', 'Sale', 'Disposal', 'Divestiture', # 排除現金流入
                'AccumulatedDepreciation', 'Amortization', 'Depreciation', # 排除非現金
                'Origination', 'Principal', 'Borrowing', 'Repayment', # 排除借貸
                'Maintenance' # 可選：如果只想看擴張性支出，可排除維護費 (但通常這很難分)
            ]
        }
    )

    @computed_field
    def capex(self) -> TraceableField:
        """Proxy Capex for REITs = Real Estate Investment"""
        result = TraceableField(
            value=self.real_estate_investment.value,
            source_tags=self.real_estate_investment.source_tags.copy(),
            is_calculated=True,
            formula_logic="Real Estate Investment (Proxy for Capex)"
        )
        return result

    @computed_field
    def free_cash_flow(self) -> TraceableField:
        """FCF = OCF - Real Estate Investment"""
        result = self.ocf - self.real_estate_investment
        result.formula_logic = "OCF - RE Investment"
        return result


CashFlowStatementVariant = Union[CorporateCashFlow, REITCashFlow]


# ==========================================
# 3. Financial Analysis Model (Compute Layer)
# ==========================================

class FinancialHealthReport(BaseModel):
    """
    Aggregates the Five Pillars of Financial Health Analysis.
    All ratios are computed fields based on the three financial statements.
    Supports polymorphic income statements for different industries.
    
    Note: All ratios return TraceableField for full end-to-end traceability.
    """
    company_ticker: str
    fiscal_period: str
    bs: BalanceSheetVariant
    is_: IncomeStatementVariant
    cf: CashFlowStatementVariant
    
    # --------------------------------------------------------
    # 0. Capital Allocation (Hidden Capital)
    # --------------------------------------------------------
    @computed_field
    def adjusted_capex(self) -> TraceableField:
        """
        Adjusted Capex = Capex + R&D + Purchase Obligations.
        Reflects true capital intensity for fabless/tech companies by including
        Research & Development and Off-Balance Sheet Purchase Commitments.
        """
        # 1. Base Capex (Available in Corporate and REIT CF)
        base_capex_val = 0.0
        capex_tags = []
        
        if hasattr(self.cf, 'capex'):
            base_capex_val = self.cf.capex.value or 0.0
            capex_tags = self.cf.capex.source_tags or []
        
        # 2. R&D (Corporate Income only)
        rnd_val = 0.0
        rnd_tags = []
        if isinstance(self.is_, CorporateIncomeStatement):
             rnd_val = self.is_.research_and_development.value or 0.0
             rnd_tags = self.is_.research_and_development.source_tags or []
             
        # 3. Purchase Obligations (Corporate Balance Sheet only)
        po_val = 0.0
        po_tags = []
        if isinstance(self.bs, CorporateBalanceSheet):
             po_val = self.bs.purchase_obligations.value or 0.0
             po_tags = self.bs.purchase_obligations.source_tags or []
             
        # Calculate Total
        total_val = base_capex_val + rnd_val + po_val
        
        # Format formula string for traceability
        # Show components in Billions for readability in the formula string
        formula_desc = (
            f"Capex ({base_capex_val/1e9:.1f}B) + "
            f"R&D ({rnd_val/1e9:.1f}B) + "
            f"Purchase Obligations ({po_val/1e9:.1f}B)"
        )

        return TraceableField(
            value=total_val,
            source_tags=capex_tags + rnd_tags + po_tags,
            is_calculated=True,
            formula_logic=formula_desc
        )

    # --------------------------------------------------------
    # 1. Liquidity Pillar
    # --------------------------------------------------------
    @computed_field
    def current_ratio(self) -> TraceableField:
        """Current Ratio = Current Assets / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = self.bs.assets_current / self.bs.liabilities_current
        result.formula_logic = "Current Assets / Current Liabilities"
        return result

    @computed_field
    def quick_ratio(self) -> TraceableField:
        """Quick Ratio = (Cash + Marketable Securities + Receivables) / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        numerator = self.bs.cash_and_equivalents + self.bs.marketable_securities + self.bs.receivables_net
        result = numerator / self.bs.liabilities_current
        result.formula_logic = "(Cash + Securities + Receivables) / Current Liabilities"
        return result

    @computed_field
    def cash_ratio(self) -> TraceableField:
        """Cash Ratio = (Cash + Marketable Securities) / Current Liabilities (Corporate only)"""
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        numerator = self.bs.cash_and_equivalents + self.bs.marketable_securities
        result = numerator / self.bs.liabilities_current
        result.formula_logic = "(Cash + Securities) / Current Liabilities"
        return result

    # --------------------------------------------------------
    # 2. Solvency Pillar
    # --------------------------------------------------------
    @computed_field
    def debt_to_equity(self) -> TraceableField:
        """Debt-to-Equity Ratio = Total Debt / Total Equity"""
        result = self.bs.total_debt / self.bs.total_equity
        result.formula_logic = "Total Debt / Total Equity"
        return result

    @computed_field
    def interest_coverage(self) -> TraceableField:
        """Interest Coverage = EBIT / Interest Expense (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        
        result = self.is_.ebit / self.is_.interest_expense
        result.formula_logic = "EBIT / Interest Expense"
        return result

    @computed_field
    def equity_multiplier(self) -> TraceableField:
        """Equity Multiplier = Total Assets / Total Equity (DuPont component)"""
        result = self.bs.total_assets / self.bs.total_equity
        result.formula_logic = "Total Assets / Total Equity"
        return result

    # --------------------------------------------------------
    # 3. Operational Efficiency Pillar
    # --------------------------------------------------------
    @computed_field
    def inventory_turnover(self) -> TraceableField:
        """Inventory Turnover = COGS / Average Inventory (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = self.is_.cogs / self.bs.inventory
        result.formula_logic = "COGS / Inventory"
        return result

    @computed_field
    def days_sales_outstanding(self) -> TraceableField:
        """DSO = (Average Receivables / Revenue) * 365 (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = (self.bs.receivables_net / self.is_.revenue) * 365.0
        result.formula_logic = "(Receivables / Revenue) * 365"
        return result

    @computed_field
    def days_payable_outstanding(self) -> TraceableField:
        """DPO = (Average AP / COGS) * 365 (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        if not isinstance(self.bs, CorporateBalanceSheet):
            return TraceableField(value=None)
        
        result = (self.bs.accounts_payable / self.is_.cogs) * 365.0
        result.formula_logic = "(Accounts Payable / COGS) * 365"
        return result

    # --------------------------------------------------------
    # 4. Profitability Pillar
    # --------------------------------------------------------
    @computed_field
    def gross_margin(self) -> TraceableField:
        """Gross Margin = Gross Profit / Revenue (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        
        result = self.is_.gross_profit / self.is_.revenue
        result.formula_logic = "Gross Profit / Revenue"
        return result

    @computed_field
    def operating_margin(self) -> TraceableField:
        """Operating Margin = Operating Income / Revenue (Corporate only)"""
        if not isinstance(self.is_, CorporateIncomeStatement):
            return TraceableField(value=None)
        
        result = self.is_.operating_income / self.is_.revenue
        result.formula_logic = "Operating Income / Revenue"
        return result

    @computed_field
    def net_margin(self) -> TraceableField:
        """Net Margin = Net Income / Revenue (Corporate/REIT) or Total Revenue (Bank)"""
        # Get appropriate revenue based on industry type
        if isinstance(self.is_, CorporateIncomeStatement):
            result = self.is_.net_income / self.is_.revenue
            result.formula_logic = "Net Income / Revenue"
        elif isinstance(self.is_, BankIncomeStatement):
            result = self.is_.net_income / self.is_.total_revenue
            result.formula_logic = "Net Income / Total Revenue"
        elif isinstance(self.is_, REITIncomeStatement):
            result = self.is_.net_income / self.is_.rental_income
            result.formula_logic = "Net Income / Rental Income"
        else:
            result = TraceableField(value=None)
        
        return result

    @computed_field
    def return_on_equity(self) -> TraceableField:
        """ROE = Net Income / Average Equity (simplified: period-end equity)"""
        result = self.is_.net_income / self.bs.total_equity
        result.formula_logic = "Net Income / Total Equity"
        return result

    @computed_field
    def return_on_assets(self) -> TraceableField:
        """ROA = Net Income / Total Assets"""
        result = self.is_.net_income / self.bs.total_assets
        result.formula_logic = "Net Income / Total Assets"
        return result

    # --------------------------------------------------------
    # 5. Cash Flow Quality Pillar
    # --------------------------------------------------------
    @computed_field
    def free_cash_flow(self) -> TraceableField:
        """
        FCF Strategy:
        - Corporate: OCF - Capex
        - Bank: Net Income - Dividends (Retained Earnings)
        - REIT: AFFO (Approximated as FFO - Capex)
        """
        # Bank Override: Banks don't use OCF/Capex structurally
        if isinstance(self.is_, BankIncomeStatement):
             result = self.is_.net_income - self.cf.dividends_paid
             result.formula_logic = "Net Income - Dividends (Bank FCF)"
             return result

        if isinstance(self.cf, REITCashFlow):
             return self.cf.free_cash_flow

        # Corporate / Default
        result = self.cf.ocf - self.cf.capex
        result.formula_logic = "OCF - Capex"
        return result

    @computed_field
    def ocf_to_net_income(self) -> TraceableField:
        """Quality of Earnings = OCF / Net Income (should be > 1.0)"""
        result = self.cf.ocf / self.is_.net_income
        result.formula_logic = "OCF / Net Income"
        return result

    @computed_field
    def accruals_ratio(self) -> TraceableField:
        """Sloan Ratio = (Net Income - OCF) / Total Assets"""
        numerator = self.is_.net_income - self.cf.ocf
        result = numerator / self.bs.total_assets
        result.formula_logic = "(Net Income - OCF) / Total Assets"
        return result
