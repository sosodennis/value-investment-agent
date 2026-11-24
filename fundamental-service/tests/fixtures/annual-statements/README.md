# 核對 #494 固定原文與預期

先使用 Python 3.12.12 及 `fundamental-service/uv.lock` 安裝依賴。所有命令在 repository root 執行。

```sh
uv sync --frozen --python 3.12.12 --extra dev --project fundamental-service
ISSUE494_SEC_EVIDENCE_DIR=/path/to/retained-sec-evidence \
  uv run --frozen --extra dev --project fundamental-service \
  pytest fundamental-service/tests/test_annual_statement_fixtures.py -ra
```

`ISSUE494_SEC_EVIDENCE_DIR` 指向既有 SEC capture 的證據根目錄，內含 `content/`。內容依 SHA-256 分片保存。先從本票可分享證據包核對外層及包內 hashes，再在新目錄解開。此命令沒有 HTTP、Arelle 或 production statement 輸出依賴。缺少證據目錄時，原文核對測試會 skip。其餘 fixture 一致性測試不能代替原文核對，也不能代替正式 EFM/DQC、mapping 或 workspace 驗收。

`issue494-cohort.json` 固定 Apple 和 Microsoft 兩個 issuer，以及 `2024-11-02T00:00:00Z` 和 `2026-11-24T00:00:00Z` 兩個 cutoff。每案保留當時五份最新 original。2024 歷史案例覆蓋 FY2020–2024，目前案例覆蓋 FY2022–2026。新 capture 的時間與 bytes 保持獨立，不冒稱 #493 相同輸入。每份 original 保存 HTML、完整 submission、accession ZIP 及 index 的實際 receipt metadata 和 hashes。`receipt_refs` 綁定版本化 `sec-response-receipt.v1`、artifact ID、scope、保留路徑與 receipt hash；核對同時驗證 artifact inventory 和原文 bytes。

`issue494-golden.json` 保存 14 份 original 當期主表的 25 個主要行項，以及 Apple FY2024 原件中的 FY2023 和 FY2022 比較欄。數字直接核對原文主表，locator 使用該份 HTML 的 table、row 和 inline-fact 次序。保留實際 QName、context、期間、單位、scale、sign 和 decimals。表格與行次序從零開始。這些預期不由 production parser、canonical facts 或 CompanyFacts 輸出生成。

Apple 的 cash-flow balance 包含 restricted cash。FY2023 balance-sheet cash 為 29,965 百萬美元，cash-flow closing cash 為 30,737 百萬美元，不能混用。Apple 主表沒有獨立 FX 行，因此該 cell 保留 `missing` 與具體理由。三項活動小計等於 reported cash change，以及 beginning cash 加 reported change 等於 ending cash，是分開的核對。它們不能證明未知 FX 為零；完整含 FX 的活動勾稽保留 `unresolved`。Microsoft 主表明列 FX，核對使用原文 FX 值。

`issue494-boundary-cases.json` 固定真實來源限制及合成邊界變異。合成案例明標 `synthetic`，不能被解讀為 issuer 披露。#493 Tesla 原件的 276 facts、修訂件的 0 facts、unknown amendment scope 和 `SEC_VALIDATION_REQUIRED` 不變。該資料只約束原 parse-only 輸入，不授予新三表資格。

每份正向 original 的 `validation_state_at_freeze` 均為 `not_run`。來源可得及原文 golden 不代表完整 strict validation、mapping、release、估值資格或財報附註完整。後續實作需以同一批 immutable inputs 逐案完成正式流程，驗證結果另存，不回填或改寫此處的預期以配合輸出。五年度只是覆蓋目標，`supported_history_threshold` 保持 null。
