# RFC-003: SEC Forward Signals Semantic Hardening (8-K + Regex/Lemma/Dependency)

- Status: In Progress
- Author: Codex
- Date: 2026-02-25
- Scope: `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl`
- Constraint: Single path only (no feature flag, no dual implementation)

## 1. 背景與問題定義

目前 `forward_signals_text` 的主要問題不是「完全沒有前瞻資訊」，而是「命中規則過窄 + 匹配過嚴」導致漏抓：

1. 短語庫過窄：`_SIGNAL_PATTERNS` 對真實財報措辭覆蓋不足。
2. 精確匹配過嚴：`_find_pattern_hits` 偏向字面匹配，無法涵蓋詞形變化與句法變體。
3. 8-K 噪音高：經常抽到程序性文字、簽名段、索引段，導致有效語句稀釋。

補充：本文檔統一使用 **8-K**（非 K8）。

## 2. 目標 / 非目標

### 2.1 目標

1. 提高 growth/margin 類 forward signal 的召回率，同時維持精度。
2. 改善 8-K 可用內容抽取，降低非業務文字干擾。
3. 保持企業級可維護性：單一職責、小型 class、可測試、可觀測。
4. 維持現有輸出 contract（對下游兼容）。

### 2.2 非目標

1. 不引入 feature flag。
2. 不維護雙版本 pipeline。
3. 本階段不做 ONNX/FastEmbed 路線。

## 3. 技術決策（分層匹配）

採用「高精度到高覆蓋」三層策略，最終融合去重：

1. Layer A: Regex Numeric Rules（高精度）
2. Layer B: Lemma Matcher（詞形歸一覆蓋）
3. Layer C: Dependency Rules（句法關係覆蓋）

### 3.1 Layer A: Regex Numeric Rules

用途：捕捉具體指引數值（如 `%`, `bps`, range）。

1. 擴充 pattern catalog：同義詞、時態變體、常見 guidance 動詞。
2. 保留嚴格數值校驗，避免噪音誤報。
3. 輸出最高 base confidence。

### 3.2 Layer B: Lemma Matcher（spaCy）

用途：處理不同詞形與措辭變體。

1. 使用 spaCy `Matcher` + token lemma 規則。
2. 規則示例：
   - growth: `expect/project/anticipate` + `revenue/sales/growth`
   - margin: `expand/improve/contract` + `margin`
3. 只要無明確數值，也可產生候選（較低 confidence）。

### 3.3 Layer C: Dependency Rules（spaCy）

用途：處理跨距離語法關係（主語-謂語-補語）。

1. 使用 spaCy `DependencyMatcher`。
2. 規則示例：
   - `we/company` -> `expect/guide` -> `growth up/down`。
3. 適合處理長句與插入語，補 regex/lemma 漏網。

### 3.4 融合與去重

1. 同一句可能命中多層，先做 candidate normalization。
2. 去重鍵：`(metric, direction, normalized_value, sentence_hash)`。
3. 置信度融合：`regex > dependency > lemma`，並疊加時效與來源品質分。

## 4. 8-K 抽取重構

### 4.1 章節優先順序

8-K 優先抽取下列條目（若存在）：

1. Item 2.02（Results of Operations and Financial Condition）
2. Item 8.01（Other Events）
3. Exhibit 99.*（尤其新聞稿正文）

### 4.2 噪音段落過濾

新增 deterministic filter：

1. `SIGNATURE`, `INDEX`, `FORM 8-K` boilerplate 段落降權或跳過。
2. 段落最小語義密度檢查（字母比、數字比、句子長度）。
3. 無實質財務敘述時標記 `fast_skip` 並寫入 diagnostics（非錯誤）。

## 5. 可維護性與 class 複雜度約束（必遵守）

1. 一個 class 只做一件事（Single Responsibility）。
2. `forward_signals_text.py` 只保留 orchestration，不承載大量規則細節。
3. 規則實作拆分為小型元件，避免 God class。
4. 目標約束：
   - 單 class 建議 <= 200 行
   - 單 public method 建議 <= 40 行
   - 複雜邏輯抽成 pure functions
5. 嚴格型別與明確 schema，避免 `dict[str, object]` 在核心路徑流竄。

建議模組：

1. `signal_pattern_catalog.py`：規則與詞庫定義
2. `regex_signal_extractor.py`：Regex Layer
3. `lemma_signal_matcher.py`：Lemma Layer
4. `dependency_signal_matcher.py`：Dependency Layer
5. `signal_candidate_resolver.py`：融合、去重、置信度
6. `filing_section_selector.py`：10-K/10-Q/8-K 章節選擇與降噪

## 6. 監控與驗收

### 6.1 Diagnostics（新增/保留）

1. `pipeline_pattern_regex_hits_total`
2. `pipeline_pattern_lemma_hits_total`
3. `pipeline_pattern_dependency_hits_total`
4. `pipeline_8k_sections_selected_total`
5. `pipeline_8k_noise_paragraphs_skipped_total`
6. `pipeline_fls_fast_skip_ratio`

### 6.2 驗收標準

1. 既有測試全數通過（含 contract/evidence 相關）。
2. 固定樣本上，growth/margin 信號召回率提升。
3. 不可出現無 evidence 的 signal。
4. 8-K 場景中，程序性段落命中率顯著下降。

## 7. 實作順序（邊文檔邊實作）

1. P1: 擴充 regex catalog + matcher（低風險、最快見效）
2. P2: 導入 lemma matcher（spaCy）
3. P3: 導入 dependency matcher（spaCy）
4. P4: 8-K section selector 與噪音過濾
5. P5: 回歸測試、真實 log 對比、RFC 更新結果

## 8. 風險與對策

1. 召回上升但誤報上升
   - 對策：confidence gating + evidence 必要條件 + regression fixture
2. 規則爆炸造成維護困難
   - 對策：pattern catalog 分域管理（growth/margin/guidance），每類獨立測試
3. spaCy 依賴增加啟動成本
   - 對策：沿用現有容器預載機制，並避免在請求路徑重複初始化

## 9. 結論

在不引入 feature flag 的前提下，最可行且企業級的路線是：

1. 保留 regex 作為高精度核心。
2. 疊加 spaCy lemma + dependency 規則補足語義覆蓋。
3. 針對 8-K 做章節與噪音治理。
4. 以小型、可測試、低耦合 class 實作，優先可維護性。

## 10. 實作進度（2026-02-25）

已完成（P1）：

1. 拆出 pattern catalog：
   - 新增 `signal_pattern_catalog.py`
   - 統一管理 retrieval query 與 metric pattern（growth/margin）
2. 拆出 regex 抽取層：
   - 新增 `regex_signal_extractor.py`
   - 封裝 lexical hits / numeric guidance hits / cue helpers
3. `forward_signals_text.py` 改為 orchestrator 調用新層：
   - 移除內嵌 `_SIGNAL_PATTERNS` 與 `_find_pattern_hits` 等規則細節
   - 保持輸出 contract 與 diagnostics 欄位不變

已完成（P2）：

1. 新增 `lemma_signal_matcher.py`（spaCy tokenizer + lemma-like normalization）：
   - 以 metric/direction/cue 三元條件做保守匹配
   - 輸出 `lemma_pattern` hits，並保留 negation/historical 抑制
2. `forward_signals_text.py` 接入 lemma layer：
   - 與 regex layer 合併評分（單一路徑）
   - 新增 diagnostics：
     - `pipeline_pattern_lemma_hits_total`
     - `pipeline_pattern_lemma_hits_by_metric`
3. 新增測試覆蓋 lemma 詞形變體命中場景（無需 exact phrase）

已完成（P3）：

1. 新增 `dependency_signal_matcher.py`（spaCy dependency parser layer）：
   - 以 cue token 的 dependency neighborhood 抽取 metric/direction 關係
   - 命中 evidence `rule=dependency_pattern`
   - 缺少 spaCy dependency model 時，單一路徑下自動跳過 dependency layer 並記錄 log event
2. `forward_signals_text.py` 接入 dependency layer：
   - 與 regex + lemma 合併評分（單一路徑）
   - 新增 diagnostics：
     - `pipeline_pattern_dependency_hits_total`
     - `pipeline_pattern_dependency_hits_by_metric`
   - 補齊 regex 命中別名 diagnostics：
     - `pipeline_pattern_regex_hits_total`
     - `pipeline_pattern_regex_hits_by_metric`
3. 新增 dependency layer 整合測試（以 stub 驗證管線接入與指標累計）

已完成（P4）：

1. 新增 `filing_section_selector.py`：
   - 8-K 章節優先選擇：`Item 2.02 -> Item 8.01 -> Item 7.01 -> Exhibit 99.*`
   - 程序性噪音句過濾（`SIGNATURE` / `INDEX` / `FORM 8-K` boilerplate）
   - 低語義密度句過濾（最小詞數與字母密度）
2. `forward_signals_text.py` 接入 8-K section selector：
   - 在 record 分析前先做 8-K 文字精煉
   - 新增 diagnostics：
     - `pipeline_8k_sections_selected_total`
     - `pipeline_8k_noise_paragraphs_skipped_total`
3. 8-K focus 抽取優先策略補強：
   - 對 filing object 新增 `Item 8.01`、`item_801`、`Exhibit 99.*` 候選
4. 新增測試：
   - `test_sec_text_filing_section_selector.py`
   - `test_extract_forward_signals_from_sec_text_tracks_8k_section_diagnostics`

已完成（P5-1 ~ P5-3，log 導向修正）：

1. P5-1：讓 dependency layer 在容器可用
   - `finance-agent-core/Dockerfile` build 階段安裝 `en_core_web_sm`
   - `docker-compose.yml` 新增：
     - `SEC_TEXT_DEPENDENCY_WARMUP=1`
     - `SEC_TEXT_DEPENDENCY_MODEL=en_core_web_sm`
   - `api/server.py` 新增 dependency matcher warmup，啟動即驗證可用性
2. P5-2：加入 retrieval debug 預覽（預設關閉）
   - `forward_signals_text.py` 新增可控 diagnostics 字段：
     - `pipeline_metric_retrieval_preview_by_metric`
   - 開關環境變數：
     - `SEC_TEXT_DEBUG_RETRIEVAL_SENTENCES=1`
     - `SEC_TEXT_DEBUG_RETRIEVAL_SENTENCES_LIMIT`（預設 3）
     - `SEC_TEXT_DEBUG_RETRIEVAL_SENTENCE_CHARS`（預設 200）
3. P5-3：擴充 pattern catalog（優先補 GOOG 常見措辭）
   - growth/margin up/down pattern 與 retrieval query 擴充
   - 覆蓋 `fx headwind`、`depreciation expense`、`top line growth` 等語句

驗證結果：

1. `ruff` 檢查通過（變更檔案）
2. 測試通過：
   - `test_sec_text_forward_signals.py`
   - `test_sec_text_filing_section_selector.py`
   - `test_sec_text_sentence_pipeline.py`
   - `test_sec_text_model_loader_circuit_breaker.py`
   - `test_sec_text_forward_signals_eval.py`
   - `test_sec_xbrl_forward_signals.py`
