# #493 來源用途與固定 coverage 驗收

本票交付 17 列來源研究矩陣、預先提交的三案 SEC cohort、正式 owner 重跑工具及可攜證據。
它不授予新資料用途，也不完成年度三表、金融指標或報價功能。
[來源 reference](../../fundamental-service/docs/source-use-coverage.md)、
[重跑指令](../../fundamental-service/docs/reproduce-source-coverage.md)與
[證據 manifest](../../fundamental-service/tests/fixtures/source-coverage/issue493-evidence.json)
是交接入口。PR、獨立審閱、main CI、merge commit 及資源清理記錄在
[#493](https://github.com/sosodennis/value-investment-agent/issues/493)。

## 固定輸入與 identity

- 固定 cohort commit：`a6220db071df8fc39e70bbbee8cc70f2da8b6533`，先於本票 coverage 驗收。
- 實作驗收 commit：`bc52a6a59d157865060a130386b00501916030b3`。
  後續交付 metadata 不更改服務或核對工具；如實作更改，須重新驗收。
- Python `3.12.12`、Pydantic `2.14.2`、Arelle `2.47.4`，依 frozen lock 執行。
- Runtime policy：`free-market-source-use-v5`，digest
  `e6b7b31dfd37f8d7c5b7c3547b4cccf86b24029db609ba05689e344b3fd2b597`。
- 結果 SHA-256：`639d63ae43cd4d3931aedee3845c577e8eed42cd1369efaa5b7dafe07e4a88ea`。
- `actual_coverage=unknown` 與 `supported_history_threshold=null` 的固定樣本欄位不回填。

SEC originals、ZIP 與 taxonomy cache 依 repo capture manifest 核對。
Public request 時間、實際 HTTP capture availability 與 admission cutoff 分開保留。
同時保留單獨 HTML 與 ZIP 的 hash；單獨 HTML 是 parse-only entrypoint，
不把 ZIP 內 HTML 的差異忽略成 archive integrity admission。

## 真實來源結果

三案來源皆可核對；下表的 facts 數是 parser 輸出數量，不是會計完整性分數。
語義可比性、SEC 用途與完整計算資格沒有因 fact 存在而成立。

| 固定樣本 | Parser 結果 | 原文及下游界線 |
| --- | --- | --- |
| Apple FY2024 原版 | `parsed`，1,127 facts | 三表 anchors、shares、SBC、claims 與 dimensions 可查。FY2024 context 為 364 日、FY2023 為 371 日，保留 52/53 週差異，不年化。 |
| Tesla FY2023 原版 | `partial`，276 extension facts | 原文有 US-GAAP／DEI，卻未被 parser 讀出；不是未揭露。固定 cache 缺 2023 DTS，見 #507。 |
| Tesla FY2024 修訂 | `unsupported`，0 parsed facts | 原文有 DEI 股數，parser 未讀出；查詢的三表 anchors 原文也缺。Part III 修訂不作完整三表重述，`amendment_scope=unknown` 不改。 |

Apple 原文與 parser 數值核對包括 FY2024 Assets `364980000000 USD`、
NetIncomeLoss `93736000000 USD`、OCF `118254000000 USD`、
SBC `11688000000 USD`。原文標為 millions，inline scale 為 6；保留原始 context、
period、unit 與 dimensions。年結普通股數與十月 DEI cover 股數分開，不互換。
Custom QName 只作 inventory，不是 approved accounting mapping。
三案均實際經 `require_sec_validation_evidence` 拒絕：`SEC_VALIDATION_REQUIRED`。

Treasury 真實 2026 XML 經 `PublicSourceAcquisition` 留存、provider 重現，
再由 `PublicSourceAdmission` 得到 `admitted`。有 224 筆 10 年 par-yield observations；
最後一筆為 2026-11-23 的 `4.92 percent`，不轉稱 issuer 借款成本。
§105 terms raw hash 符合既有 policy；所需 Treasury 引用與無背書 notice 仍保留。

Admission cutoff 為 `2026-11-24T00:30:23.054394Z`，是 request 與 capture availability
的較晚者。原始 request 較早而產生的 acquisition cutoff 拒絕仍在 receipts；
不把資料觀察日冒充事前可得日。成功 admission output digest：
`f57f6d71f76476439f95985f99eb7a5df234c9e7952c5e7447512f70712f9779`。

## 正式拒絕與重播

| 案例 | 正式 code |
| --- | --- |
| 原始資料再分發 | `SOURCE_USE_PURPOSE_UNSUPPORTED` |
| 缺條款 | `SOURCE_USE_TERMS_MISSING` |
| 錯 policy digest | `SOURCE_ADMISSION_POLICY_MISMATCH`，不產生 admission |
| 原始 request cutoff 早於 capture | `SOURCE_NOT_AVAILABLE_AT_VALUATION` |
| 改條款的明示 mutation check | `SOURCE_USE_TERMS_CHANGED` |
| 移除 rule 的明示 mutation check | `SOURCE_USE_POLICY_MISSING` |

前四案經正式 `PublicSourceAdmission.execute`。後兩案將保留輸入複製後，
經既有 `admit_macro_source` 執行，不捏造真實來源 capture。
現行 policy file/digest 必須成對且匹配的 loader 拒絕也由 focused suite 核對。

以同一組 39 個 retained 檔案重播時，HTTP capture 與 parser 入口被設為一旦呼叫就失敗。
結果 bytes 完全相同；全部檔案的 bytes、size、mtime_ns 不變。
重播從完整 parser reports 重新核對來源、runtime、profile、taxonomy 及 integrity，
重新產生 observations，不以 summary cache 代替。證據包附 `replay_probe.py`、
`replay-proof.json`、full reports 與原始 requests，可在任意新路徑核對。

## 檢查與審閱

以下指令對實作驗收 commit 執行，exit code 均為 0。完整輸出在證據包 `reports/`。

```sh
PYTHONPATH=finance-agent-core uv run --frozen --extra dev --project fundamental-service pytest \
  fundamental-service/tests/test_source_coverage.py \
  fundamental-service/tests/test_source_admission.py \
  fundamental-service/tests/test_source_admission_evidence.py \
  fundamental-service/tests/test_source_use_deployment.py \
  fundamental-service/tests/test_personal_local_source_policy.py \
  fundamental-service/tests/test_public_acquisition.py -q -ra
uvx --from ruff==0.14.10 ruff check fundamental-service
uvx --from ruff==0.14.10 ruff format --check \
  fundamental-service/scripts/reproduce_source_coverage.py \
  fundamental-service/scripts/verify_source_research_matrix.py \
  fundamental-service/tests/test_source_coverage.py
MYPYPATH=finance-agent-core uv run --frozen --project fundamental-service --with mypy==1.19.1 mypy \
  --no-incremental --follow-imports=silent --ignore-missing-imports \
  fundamental-service/scripts/reproduce_source_coverage.py \
  fundamental-service/scripts/verify_source_research_matrix.py
python3 scripts/architecture_guard.py --exceptions-dir scripts/architecture_guard_exceptions
git diff --check origin/main
```

Focused tests：106 passed、1 skipped。Skip 是需要隔離 PostgreSQL 的既有 acquisition
測試，由 required CI 的 PostgreSQL job 補驗；不是宣稱資料庫測試已在本機執行。
Ruff、format、mypy（兩個 scripts）與 architecture guard 通過。

`deslop` 檢查完整 diff；沒有新增 compatibility shim、寬泛 exception 或型別逃逸。
`no-comments` 的獨立審查接受刪除兩行敘述性 docstring，沒有 `MUST KILL`；
保留作 CLI help 的 API 說明及 style-only `E402`。整合後 tokenizer inventory 再核對一致。
未參與撰寫的 reviewer 另核對原文、條款、程式、成功、拒絕與可攜重播；
審閱原件及 digest 隨證據 manifest 提供。測試與 CI 不代替該審閱。
Reviewer 已從 GitHub 下載證據包，核對 archive 與包內所有 file hashes，
在新的目錄停用 socket、HTTP 與 parser 重跑正式 CLI，結果相同且 retained files 不變。
最終[獨立審閱報告](https://github.com/sosodennis/value-investment-agent/releases/download/issue-493-source-coverage-v1/issue493-independent-review.md)
批准合併，required CI 與 main 驗證仍需另外通過。
審閱找到的逐列 evidence 借用及 registration／policy 混合核對問題已在驗證 owner 修正；
四個反例先重現失敗，再證明錯引用與 profile／metric／provider 漂移均拒絕。

本次 diff 只有未安裝至服務的驗證 scripts、測試、fixture 及文件；
沒有修改 `fundamental-service/src`、policy、capture/admission、Compose、API 或 UI。
因此 Docker／瀏覽器驗收不適用，未啟停任何 stack，也未接管其他票的 runtime。
合併仍須通過最新 required checks 與獨立審閱，再驗證 main merge commit。

## 有據不可用及交接

- [#507](https://github.com/sosodennis/value-investment-agent/issues/507)：Tesla 2023 DTS，
  限制這兩案的標準 fact coverage。#494／#496 先使用已有 SEC 基礎，逐案補足正式 ingestion、mapping 與完整性。
- [#506](https://github.com/sosodennis/value-investment-agent/issues/506)：New York Fed terms
  整頁 pin 不符，只限制 SOFR。新舊 hash 不同不能自行解讀為法律條款變更或自動授權。
- BEA／NYU 本次只核對條款及 policy projection，未驗本次 workbook 數值；
  ALFRED 無預設 grant，IR 仍需逐公司核對；它們不能冒稱已接入。
- Yahoo 個人本機 policy 不是供應商自動取得授權；Nasdaq 沒有可用 production permission。
  #503、#504、#505 的依賴不解除，Twelve Data 不啟用。
- #376、#350、#339 維持 deferred；沒有提高歷史門檻或改動金融公式。

用途矩陣及本票結果是工程與來源研究，不是法律認證、完整市場 coverage 或投資績效證明。
