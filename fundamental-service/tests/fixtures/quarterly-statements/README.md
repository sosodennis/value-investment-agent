# #495 季度與 TTM 參考資料

## 從 SEC 原件重算

從 repository 根目錄執行。將 `--source-root` 指向合法保留的 accession 原件目錄，將 `--catalog-root` 指向保留的 SEC submissions 目錄。若兩者共用內容存放目錄，可省略 `--catalog-root`。兩個目錄都以 `content/<SHA-256 前兩碼>/<SHA-256>.bin` 存放原件，JSON 則使用 `.json`。四案的 `cases/*.json` 記錄 accession 原件與 submissions 回應的 URI、大小、雜湊、捕捉時間、scope 和回應標頭。

```sh
uv run --python 3.12.12 --frozen --project fundamental-service --extra dev \
  python fundamental-service/scripts/reproduce_fiscal_statement_sources.py \
  --source-root /path/to/retained-accession-store \
  --catalog-root /path/to/retained-submissions-store --verify

uv run --python 3.12.12 --frozen --project fundamental-service --extra dev \
  python -m pytest -q fundamental-service/tests/test_issue495_fiscal_statement_reference.py
```

`--verify` 重讀 33 個 accession 的 index、XBRL ZIP、primary HTML 和完整 submission。範圍相同的 34 個 case-filing 綁定共引用 136 份 receipts。工具核對原件雜湊和大小，從 primary HTML 重讀 inline XBRL，以 Decimal 計算 1,300 個季度及 TTM 格，再逐位元組比較 manifest 和輸出分檔。年度回歸另讀 500 個 #494 frozen 預期。成功時退出碼為 0，且輸出含 `"differences": []`。工具不依賴服務計算程式。

需要核對某份缺失的 accession 回應時，可對上述重跑命令加上 `--fetch-sec` 並設定 `SEC_USER_AGENT` 為有效組織名稱與聯絡電郵。工具只讀已釘選的 `www.sec.gov` accession URL，採節流與大小上限，只有雜湊相同才保留新下載的 bytes。舊 receipt 仍代表原捕捉時間。SEC submissions 目錄需帶有原件，因為即時 catalog 會變動。新的正式來源應走專案的 SEC capture，生成新的 receipts 和 SHA-256，再獨立審閱 cohort。

## 四案的資料範圍

每案保留八個實際季度、五個滾動 TTM 視窗及 25 個行項。年度回歸每案另取五年。下表的起點、終點都是季度結束日，完整日期及前期依賴見 `cases/` 和季度分檔。

| 案例 | UTC cutoff | 首季至末季 | 季度 reported / derived / missing | TTM | 年度 |
| --- | --- | --- | --- | --- | --- |
| AAPL historical | 2024-11-02 00:00 | 2022-12-31 至 2024-09-28 | 154 / 38 / 8 | 125 | 125 |
| AAPL current | 2026-11-24 00:00 | 2024-12-28 至 2026-09-26 | 154 / 38 / 8 | 125 | 125 |
| MSFT historical | 2024-11-02 00:00 | 2022-12-31 至 2024-09-30 | 176 / 24 / 0 | 125 | 125 |
| MSFT current | 2026-11-24 00:00 | 2024-12-31 至 2026-09-30 | 176 / 24 / 0 | 125 | 125 |

每個 Apple 案例的八個季度與五個 TTM 視窗都保留現金匯率影響缺值。季度 evidence 附上現金流量表的表格與行掃描。Q4 分別掃描 10-K 與九個月 10-Q，保留 `input_not_reported` 原因。#494 年度同一行各有五格缺值。MSFT 的兩案各額外保留一份前置 Q1 以支援首個 Q2 的 YTD 差分。其中 2024-09-30 accession 同時出現在兩案。Apple FY2023 為 2022-09-25 至 2023-09-30，共 371 天。

## 從格子追到披露

`issue495-golden-manifest.json` 列出輸入與輸出雜湊、bytes 和 coverage。`golden/quarter/` 以案例和實際季末分檔，`golden/ttm/` 以案例和視窗末日分檔，`golden/annual/` 以案例分檔。沿格子的 observation ID 到 `golden/sources/<accession>.json` 讀 QName、context、單位、scale、sign、decimals 和 Decimal 原值。表格、行和 fact index 從零起算。原文的 `printed_row_label` 與 row policy 的通用名稱各自保留。

季度選擇在 cutoff 前可取得的原件觀察，保留後續比較披露、排除理由和兩種季度值的精度比對。Q1 由同一來源 observation 同時代表單季與 YTD。Q2、Q3 以同財年 YTD 相減，Q4 以全年減九個月。TTM 流量保留四季及其 observation ID，資產負債表取視窗期末，現金則分別取開頭前一日和最後一日。基礎單位、維度、來源 QName、會計範圍和已知不同修訂口徑的檢查結果保留在格子中。

每格的 `reviewed_cohort_basis` 連到對應的案例與申報覆核分檔。覆核涵蓋 784 個有值季度格與 490 個有值 TTM 格，限固定四案、25 個合併 US GAAP 行項及原報百萬美元精度。案例分檔保留入選原值、差分輸入、同期間原刊與比較欄對照及 TTM 使用的季度。申報分檔以 URI、原件雜湊、XPath 和段落雜湊定位相關附註。案例與申報分檔均釘選獨立矩陣與來源索引的 SHA-256。[申報覆核分檔](basis/cohort-filings.json)

`source_available_at` 採完整格所需原值的最晚公開時間。單季原報若有差分核對，時間同時涵蓋該季與前季的實際 YTD 輸入。TTM 取必要季度的最晚時間。原始 observation 自身保留原刊受理時間。

Apple historical FY2023 Q4 另保留首批獨立覆核，24 個有值格的 `basis_evidence.reviewed_bridge` 繫結四份申報、35 組原刊與比較欄及四個財年期初現金觀察。該證明的 `public_source_available_at` 涵蓋所用的四份申報。[FY2023 Q4 覆核分檔](basis/aapl-historical-2023-09-30.json)

`--verify` 用保留的申報與 submissions 重播附註、原始 facts、受理時間、比較欄、實際期間及 TTM 現金邊界。四案的指定報告日期內無 10-K/A 或 10-Q/A。晚於 cutoff 的比較欄只供事後核對。通用的重分類聲明未逐項說明其他受影響科目，跨年度的 US GAAP namespace 各自保留原 URI。Apple FX 持續缺值。

`issue495-boundary-cases.json` 為稀釋 EPS、稀釋加權平均股數與毛利率各提供四季合成觀察。測試依各行項的聚合分類執行 TTM reference checker，確認回傳 `unsupported`。稀釋 EPS 須依全期盈餘與稀釋股數計算，加權平均股數反映全期的時間權重，毛利率則須用全期毛利除以全期營收。

## 正式驗收範圍

離線資源可行性已涵蓋 33 個 accession。31 份在原 cache 無阻斷，最新 MSFT 經 #522 的 ECD cache 重跑後無阻斷。MSFT 2024-09-30 的 `DQC.US.0015.5970` 仍為 active error block，使用該原件的參考格附有來源標記。樣本覆核限會計可比性。正式 validation action、ingestion、mapping、release、authenticated read 和瀏覽器驗收各有驗收條件。 [#521](https://github.com/sosodennis/value-investment-agent/issues/521) [#522](https://github.com/sosodennis/value-investment-agent/issues/522)

`issue495-cohort.json` 固定正式頁面的抽樣與操作。三種 frequency、三張表、適用的 reported、derived 與 missing 狀態都有樣本。每次驗收需記錄四個寬度、實際窄報告面板、淺色與深色、瀏覽器原生 200% 縮放、觸控與鍵盤、焦點回復、URL 重載、歷史導覽和延遲回應。瀏覽器記錄只涵蓋實際操作的樣本，逐格驗證由數值 checker 提供。
