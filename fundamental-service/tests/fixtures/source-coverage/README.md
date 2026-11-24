# #493 固定工程樣本

`issue493-cohort.json` 固定本票的三個真實 SEC 來源與一個政府資料取得請求。
固定時尚未執行本票的 parser、coverage 或 admission 驗收。
`actual_coverage` 保持 `unknown`，實際結果另存驗收證據，不回填成預期結果。

SEC 原文、ZIP、來源 URL、HTTP 狀態、時間及 SHA-256 已由相鄰
`../sec-edgar/capture_manifest.json` 保留。這些既存 capture 是本票的固定輸入，
不是宣稱今日重新下載的結果。公司與 security 欄位是樣本選擇資訊，
不取代正式歷史 DEI identity resolution。

選樣前只核對既存 capture metadata 與原文說明。
Apple FY2024 原文的 Note 1 與 MD&A 明示 FY2024 為 52 週、FY2023 為 53 週。
同一原文因此涵蓋非十二月年結及 52/53 週比較案例。
Tesla 修訂版的 EXPLANATORY NOTE 明示僅補 Part III 等項目，
可檢查獨立三表缺失與修訂不自動取代原版的行為。
這項研究引用不改寫原 capture 的 `amendment_scope=unknown`。

三案只驗來源、原文觀察、解析限制及拒絕語義。
它們不代表全市場，不替代 #376，也不設定歷史充分性門檻。
五年度、八季度、完整三表、claims inventory 與估值資格仍由各正式 owner 驗證。
