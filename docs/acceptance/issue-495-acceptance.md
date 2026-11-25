# #495 季度與 TTM 驗收紀錄

狀態為 WIP。PR [#523](https://github.com/sosodennis/value-investment-agent/pull/523) 尚未完成正式功能驗收。實作票 [#495](https://github.com/sosodennis/value-investment-agent/issues/495)，parent [#490](https://github.com/sosodennis/value-investment-agent/issues/490)。本紀錄不授予展示或估值資格。

## 固定預期

四案為 Apple 與 Microsoft 的 historical/current，每案八個實際 fiscal quarters。Cohort 保留 33 個不同 accessions、34 個 case bindings、800 個季度格及 500 個 TTM 格。另有 500 個年度格，只作 #494 frozen regression。固定範圍、原文重建、行項政策與獨立 Decimal 預期見[季度 fixtures](../../fundamental-service/tests/fixtures/quarterly-statements/README.md)。不得依 production 結果改成 expected missing。

Apple FX 缺失及 unresolved 勾稽維持原義。`supported_history_threshold=null`、`valuation_eligibility=not_evaluated` 不變。既有年度 materialization、serving 與 manifest 身分沿 [#494 acceptance](issue-494-acceptance.md)，不改標為本次 build。

## Source-stage runtime

[Runtime tuple](issue-495-runtime.json) 記錄 implementation `293c068cc8cca6a4329b13a21f88ce93c1b47326`、隔離 project、ordered Compose、env-file SHA、資源、image 與來源 digest。此階段只有 Fundamental service，沒有 application 或 browser session。Tuple 的 generic service profile 是既有 schema 的要求，所有未執行的 valuation checks 保持 `not_run`。

正式來源使用新 taxonomy cache `af63b0b36d5cad6f2788e90fc323b56955ce581fd84e41330bac4ba765f3a6f0`，container 上限 3 GiB、parser child 上限 2 GiB、1 CPU。Overlay 包含既有 `docker-compose.parser-actions.yml`，強制唯讀 image、no-new-privileges 與獨立 scratch。年度 cache 身分維持 `fbcd82b406a2420f37bf17c7afc8baa823e7cfadd2308ccb8bfecf88648a9691`。

以 tuple 的完整參數執行 `scripts/acceptance_preflight.sh`，並設 `REQUIRE_SEC_IDENTITY_RESOLUTION=1`，exit 0。Report SHA 為 `de3618384a77c6e7b9b685c90b25c1b5f7a3b61c50c7bf3b5d4705575f618b07`。這只證明該 runtime 的來源、pins、health 與 identity readiness，不代表 Q01–Q14 通過。

## 已觀察的正式來源結果

Apple `0000320193-23-000064`、period end `2023-04-01`，已經正式 CLI discovery、完整 EFM/DQC validation 與 retained read，三個命令均 exit 0。結果為 `complete_matched`、metadata matched、raw quality pass，829 個 facts，normalized/archive 共 6 個 action references，parser network attempts 為 0。Retained read 的 evidence 與首次輸出相同。

Validation artifact 為 `fiscal-original-validation:8b9ee0010f489ee672d64d6949d05e9ad9defa8745101f8e0ca0a351e7b3c478`，content hash 為 `5a62a71e97ddb784cf187383c0ad01ef6b02b1deda400d5f4a372dcd896cc3e8`。完整原件與 parser bodies 依 SEC retained-storage 用途保存，不在公開驗收附件再分發。

固定 `293c068c` 的完整 cohort 已完成 33 份不同原件、34 個 case bindings 的正式 CLI validation 與 retained read。32 個 bindings 為 `complete_matched`，同一 Microsoft `0000950170-24-118967` 在兩個 cutoff 的兩個 bindings 均為 `complete_refused`，metadata matched、原始品質 block。34 次 retained read 均與各自首次 validation evidence 相同。

凍結原始 observations 與正式完整 parser reports 的 checker 使用 `--require-complete` 及 Python `-O` 執行，exit 0。結果為 34 個 case/cutoff bindings、33 個 accessions、2,111 次 observations 比對，缺件與差異皆空。凍結的 unique observations 是 2,061 筆，共用 Microsoft 原件在第二個 cutoff 的 50 筆另核一次。Checker 只比對已承諾的原始 observations，不代表額外 facts、候選衝突或 production 季度公式已驗。

來源完成摘要的 SHA-256 繫結如下。

| 記錄 | SHA-256 |
| --- | --- |
| 完整 validation/read cohort | `5b152c944a19be5c9f74bfed9287f4b101e3082aae0852775fb6eaea21b2742f` |
| 原始 observations 完整比較 | `4bf5d86aba4c86229c0a20872d21294b288d23f733c78ab18d689b2480e55bc8` |
| 修正版比較工具 | `fdea4f8cd7132ec3294092d6e4b2fbd03495f3042fd2629d59dfead51c27b94d` |
| 凍結 golden manifest | `4706db4be83a1ac530fee7ca5c27991dda466fb83a771f3f71eac75cff0ae41f` |

四個正式來源代表另由未參與實作的 reviewer 直接讀取 SGML、DEI、index、ZIP、兩種表示的 raw reports、metadata、action、delivery、current build 與掛載資源，限定來源審閱通過。Reviewer 也獨立對 30 個已完成快照的 1,842 次 observations 直比，全部相符。比較工具的 case/cutoff 與 fixture 完整性 findings 已修正，另一輪獨立審閱以 12 個暫存正反案例核對後通過。

這完成固定 build 的原始來源驗證與 replay 關卡。#521 展示准入、季度與 TTM 推導、release/read、core/artifact、workspace、Q01–Q14 及 main 交付仍待完成。後續 production source build 改變時，依當前 action identity 重新 materialize，不將本次 artifacts 改標新版本。

## 修正與未解關卡

第一輪 source runtime 漏配既有 immutable-parser overlay，正式驗證明確拒絕。修正設定後使用新 tuple，原失敗紀錄保留，沒有放寬 parser guard。

[#524](https://github.com/sosodennis/value-investment-agent/issues/524) 的 operation deadline、SQL、索引、節流、提交及取消清理已完成限定獨立審閱與真 PostgreSQL 回歸。[#525](https://github.com/sosodennis/value-investment-agent/issues/525) 的完整 CLI report JSON 輸出已修正，正向測試涵蓋 Path、時間與保存的 evidence，並以本次正式 Apple CLI 重跑。兩票均待全功能及 main 驗證，不在切片整合時結案。

[#521](https://github.com/sosodennis/value-investment-agent/issues/521) 的原始 DQC blocking finding 保持拒絕。可信 source-bound witness、獨立 accounting classification、分權簽署 decision、期限及撤銷檢查尚未完成。[#522](https://github.com/sosodennis/value-investment-agent/issues/522) 的新 cache 資源已建立，但年度與 fiscal runtime pins 在同一服務共存，以及 #494 四案的正式 read/replay，仍須完成。

## 檢查範圍

`293c068c` 整合後的 golden/source/CLI 聚焦測試為 195 passed、1 個需要 PostgreSQL 的 skip，exit 0。CLI 修正作者另以 owned PostgreSQL 執行 116 項相關測試，全數通過。獨立 CLI reviewer 執行非空三命令輸出與 deadline 回歸，2 passed、1 PostgreSQL skip，並額外核對 strict DTO 拒絕不完整 payload。

前一個 adapter 版本 `1d608959` 的 [CI](https://github.com/sosodennis/value-investment-agent/actions/runs/45513797328)、[本版本 CI](https://github.com/sosodennis/value-investment-agent/actions/runs/45517088588) 及首份驗收 metadata 的 [CI](https://github.com/sosodennis/value-investment-agent/actions/runs/45517972808) 均已通過。Ruff、mypy、兩個 architecture guards 及 52 個保護檔案的逐位元組核對已有本切片證據，不能代替 browser 驗收。
