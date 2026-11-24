# 核對 #494 固定原文與預期

先使用 Python 3.12.12 及 `fundamental-service/uv.lock` 安裝依賴。所有命令在 repository root 執行。

```sh
uv sync --frozen --python 3.12.12 --extra dev --project fundamental-service
```

## 核對既有 frozen inputs

有原始 retained evidence 時，先執行[來源核對工具](../../../scripts/reproduce_annual_statement_sources.py)。`--evidence-dir` 需已有 `content/`、`artifacts/` 及原始 artifact inventory。工具不連網、不補檔，也不修改原件；缺檔、錯 hash、receipt scope、metadata 或 discovery 選樣均以具名結果拒絕。報告放在證據目錄之外。

```sh
PYTHONPATH=finance-agent-core uv run --frozen --extra dev --project fundamental-service \
  python fundamental-service/scripts/reproduce_annual_statement_sources.py verify \
  --evidence-dir /path/to/retained-sec-evidence \
  --output /path/to/frozen-source-verification.json
ISSUE494_SEC_EVIDENCE_DIR=/path/to/retained-sec-evidence \
  uv run --frozen --extra dev --project fundamental-service \
  pytest fundamental-service/tests/test_annual_statement_fixtures.py -ra
```

來源核對成功回傳 exit 0，`frozen_inputs_match=true`，並核對四組 discovery 和 80 個 source receipt references。原文測試另核對原始主表、context、unit 和 golden 數字。缺少 `ISSUE494_SEC_EVIDENCE_DIR` 時，原文測試會 skip，不能宣稱已通過原文驗收。這些命令不執行 Arelle、canonical ingestion、mapping 或 workspace 驗收。

## 從 SEC 重取新 inputs

沒有原始 retained evidence 時，從[固定 cohort](issue494-cohort.json) 的 SEC URLs 重取。原始 issuer filing 的公開轉供權限未由本 fixture 成立，因此沒有可公開下載的原文證據包。請依 [SEC fair access](https://www.sec.gov/about/developer-resources) 提供包含有效聯絡方式的 User-Agent，不將原始 filing 公開發佈。

設定 `FUNDAMENTAL_SEC_USER_AGENT` 後，選一個新的 evidence directory。以目前 checkout 的完整 commit SHA 傳入 `--source-revision`。

```sh
PYTHONPATH=finance-agent-core uv run --frozen --extra dev --project fundamental-service \
  python fundamental-service/scripts/reproduce_annual_statement_sources.py capture \
  --evidence-dir /path/to/new-sec-evidence \
  --source-revision "$(git rev-parse HEAD)" \
  --user-agent-env FUNDAMENTAL_SEC_USER_AGENT \
  --timeout-seconds 900 \
  --output /path/to/new-source-comparison.json
```

工具沿既有 `AnnualDiscovery` 和 `RetainedSecSourceAdapter` 執行，保留識別 User-Agent、節流、deadline、immutable bytes 和真實 receipts。每個 cutoff 必須重現相同 originals 及申報 metadata；若選樣不同，保留新的 discovery，該案例不改抓較舊原件。每份 original 保存 index、完整 accession ZIP、primary HTML 和 complete submission。重試使用同一目錄與 request，可重用成功 captures，補取先前失敗部分。

新 capture 一律保留真實取得時間、headers、content hash、receipt hash 和 scope。報告逐來源列出相對 frozen inputs 的 `changed_fields` 和具名結果。原文 bytes 改變是 `SOURCE_CONTENT_DIFFERENT`；取得時間或 headers 改變是 `SOURCE_CAPTURE_METADATA_DIFFERENT`，這只表示 input 身分不同，不表示原文數字錯誤。receipt 身分改變則保留 `SOURCE_RECEIPT_DIFFERENT`。任何差異回傳 exit 2，報告及成功的新證據仍保留；不要改寫 frozen cohort、回填舊 timestamps，或把新 capture 宣稱為相同歷史輸入重播。輸出報告已存在但內容不同時，改用新報告路徑。

新 capture 通常因時間與 headers 不同而無法通過 frozen 原文測試。新路徑仍可依 cohort 的原始 ZIP URL、accession、原文 hash 與 [golden locators](issue494-golden.json) 獨立核對主表數字；必須記錄當次 input identity 與差異。不能把這項核對報成 frozen 33 項測試通過，也不能用工具的來源取得結果解除正式 validation 或計算 gate。

`issue494-cohort.json` 固定 Apple 和 Microsoft 兩個 issuer，以及 `2024-11-02T00:00:00Z` 和 `2026-11-24T00:00:00Z` 兩個 cutoff。每案保留當時五份最新 original。2024 歷史案例覆蓋 FY2020–2024，目前案例覆蓋 FY2022–2026。新 capture 的時間與 bytes 保持獨立，不冒稱 #493 相同輸入。每份 original 保存 HTML、完整 submission、accession ZIP 及 index 的實際 receipt metadata 和 hashes。`receipt_refs` 綁定版本化 `sec-response-receipt.v1`、artifact ID、scope、保留路徑與 receipt hash；核對同時驗證 artifact inventory 和原文 bytes。

`issue494-golden.json` 保存 14 份 original 當期主表的 25 個主要行項，以及 Apple FY2024 原件中的 FY2023 和 FY2022 比較欄。數字直接核對原文主表，locator 使用該份 HTML 的 table、row 和 inline-fact 次序。保留實際 QName、context、期間、單位、scale、sign 和 decimals。表格與行次序從零開始。這些預期不由 production parser、canonical facts 或 CompanyFacts 輸出生成。

Apple 的 cash-flow balance 包含 restricted cash。FY2023 balance-sheet cash 為 29,965 百萬美元，cash-flow closing cash 為 30,737 百萬美元，不能混用。Apple 主表沒有獨立 FX 行，因此該 cell 保留 `missing` 與具體理由。三項活動小計等於 reported cash change，以及 beginning cash 加 reported change 等於 ending cash，是分開的核對。它們不能證明未知 FX 為零；完整含 FX 的活動勾稽保留 `unresolved`。Microsoft 主表明列 FX，核對使用原文 FX 值。

Microsoft FY2020、FY2021 的 primary cash-flow table 已用含 restricted cash 的 cash balance 與 net-change 概念，但 FX 行仍用 `us-gaap:EffectOfExchangeRateOnCashAndCashEquivalents`。兩份原件的 FX locator 分別為 table 155／row 53 與 table 141／row 51；其 SHA-256 分別為 `99d1dfdd564d8e7cc42fa9c6c3b44c0bc131fece7e6638f28e24ec7cb49faa7a` 和 `0168b995b37d463102f295f989710294eb61b98db1636a9384ea1ccc276dddcb`。同表的期初、期末及變動 locator、contexts 與原值皆保留於 golden。FY2022 的 table 152／row 51 改用含 restricted cash 的 FX 概念，仍呈現相同 FY2020 的 -201 百萬美元與 FY2021 的 -29 百萬美元。這些已核准的 primary FX 行沿用其 cash-rollforward balance 的 basis，原始 FX tag 不改寫。這項來源歸屬不代表 restricted cash 或其 FX 為零，也不授權其他 context 或未審閱來源。新政策須經新的 mapping approval 與 release，不能重用舊簽核。

`issue494-boundary-cases.json` 固定真實來源限制及合成邊界變異。合成案例明標 `synthetic`，不能被解讀為 issuer 披露。#493 Tesla 原件的 276 facts、修訂件的 0 facts、unknown amendment scope 和 `SEC_VALIDATION_REQUIRED` 不變。該資料只約束原 parse-only 輸入，不授予新三表資格。

每份正向 original 的 `validation_state_at_freeze` 均為 `not_run`。來源可得及原文 golden 不代表完整 strict validation、mapping、release、估值資格或財報附註完整。後續實作需以同一批 immutable inputs 逐案完成正式流程，驗證結果另存，不回填或改寫此處的預期以配合輸出。五年度只是覆蓋目標，`supported_history_threshold` 保持 null。
