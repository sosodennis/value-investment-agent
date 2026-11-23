# Fundamental 數字格式與語義參考

研究日期為 2026-11-23，來源版本為 `cf091fb3b3518ef20c616947ce390bf069bfe031`。本文件是後續實作規格，未改動產品 formatter。原始樣本見 [sample.json](sample.json)，研究結論見 [研究報告](README.md)。

## 值與顯示各有責任

Canonical Decimal 字串是查證、複製及服務輸入的依據。Readable display 只改顯示，不回寫 artifact、不作估值計算。保留 `raw`、`semanticKind`、`currency`、`unit`、`period`、`evidence identity`。圖表浮點座標只能用於定位，標籤、tooltip 和複製仍從 raw 格式化。

欄位語義來自明確的服務 path 或 node unit 與已知欄位 registry。不可因值在 0 與 1 之間便判斷為百分比。未知欄位保留帶單位原文並標記「未定義顯示格式」，不得猜測。`source.scale` 是來源表示法的 metadata，canonical value 已正規化為基礎單位，不再乘 `10^scale`。

## 語義對照與樣本

| 類型 | 服務資料與語義依據 | 主畫面格式 | before → after | 詳細查證 |
| --- | --- | --- | --- | --- |
| 每股值 | `per_share_value`、相同單位的 quantiles | ISO 幣別，2 位小數，`/ share` | `229.88242539685962775556419207139754074672901162460` → `USD 229.88 / share` | 完整 raw，base 或 MC 身分，模型、日期 |
| 企業價值 | base `nodes[enterprise_value]`，currency | ISO 幣別，摘要 compact 2 位 | `1790200428089.1467162549094946817662769043629155565` → `USD 1.79T` | 同一 base 的 formula、inputs、hash |
| 股權總值 | `intrinsic_value`，非每股值 | ISO 幣別，compact 2 位 | `1731474428089.1467162549094946817662769043629155565` → `USD 1.73T` | 不標成 enterprise value |
| 財務金額 | revenue、cash、debt、NOPAT、年度 revenue/FCFF 節點 | 摘要 M/B/T；同表固定單位 | `331839000000` → `USD 331.84B` | `scale=6` 只顯 metadata，不能變成 `331839000000000000` |
| 比例 | terminal growth、forecast growth/margin/reinvestment、WACC、risk-free、ERP、tax、capital weights、服務歷史 ratios | raw × 100 作顯示，2 位小數，同序列一致 | `0.0492` → `4.92%`；`0.40` → `40.00%`；WACC → `10.28%` | raw 仍為 `0.0492`，不是 `4.92` |
| Beta | `assumptions.wacc.beta`，無量綱 | 2 位小數，不加 `%` | `1.27664817807817509986989534809254109859466552734375` → `1.28` | 不能因 raw < 1 時改成百分比 |
| 股數 | `assumptions.capital_bridge.diluted_shares`、facts 的 shares 單位 | shares；摘要 M/B shares；表格保留口徑 | `7532000000` → `7.53B shares`，原始與加權平均與稀釋股數分開 | fraction shares 如服務允許保留，不無條件取整 |
| 年份 | `fiscal_year` 或 fact duration period | `FY2026` 並可查起迄；預測用 `Year 1` | Year 1 不自動改成 2027 | 未提供預測財年對應時保留 ordinal |
| 樣本數 | requested/valid/invalid | 整數，千位分隔，不縮成 K | `256 / 256 / 0` | 診斷 status 與 seed 各自保留，seed 是字串 ID |
| 利率差 | 兩個同口徑已確認 rate，僅 display comparison | `百分點` 或 `bps`，明確命名 | `4.92% → 2.50%`，差 `−2.42 百分點` 或 `−242 bps` | 這是格式測試案例，不新增估值公式；未供應比較值可只並列 |
| 百分比變動 | 同一指標的 relative change | 寫明「相對變動 %」 | 不把利率差寫作 `−2.42%` | denominator=0 或無相同比較口徑則「不適用」 |

股數範例的確切 raw 與 path 以 [sample.json](sample.json) 為準。正式實作必須由 typed registry 決定 diluted_shares 路徑，不從顯示標籤推斷。

## Rounding 與單位

1. 顯示 rounding 採十進位 nearest，tie away from zero，即 Decimal `ROUND_HALF_UP`。使用字串 decimal 運算或經評估的既有工具，不先用 `Number(raw)` 再決定最終字元。
2. 英文金融符號固定 `.` 小數點與 `,` 千位分隔，ISO 幣別避免 `$` 歧義。中文文件中的 M、B、T 分別為 `10^6`、`10^9`、`10^12`，不能解作萬或億。
3. 摘要先按量級挑 M/B/T，rounding 跨門檻時升級單位。`999995000` 顯示 `USD 1.00B`，避免 `1000.00M`。小於 1M 的獨立金額保留千位分隔。
4. 年度比較表和圖軸固定 `USD B`，每格不再重複幣別，也不逐格切 M/B/T。表頭和 chart caption 都寫單位。股數另表，不能與金額共用軸。
5. 同一序列採同小數位。若 2 位會把非零顯成零，擴展該序列的精度至最多 6 位；仍不足則用 3 位有效數的科學記號，並在 caption 解釋。不可顯示 `−0.00` 或把非零 clamp 成零。
6. 絕對值大於或等於 `10^15` 的金額以帶 ISO 幣別的 3 位有效數科學記號表示，避免輸出無限長的 T 值。所有 compact 與 scientific display 均可取得完整原文。
7. 原文精度不是來源 accuracy。服務計算的長 Decimal 不暗示數十位可預測精度。概覽標「顯示已四捨五入」，而不是把完整 Decimal 當作分析品質。

## 邊界案例

下列是 formatter 驗收用例，除了列明的 MSFT 值，其餘均為合成邊界資料。

| 輸入與語義 | 預期顯示 | 防止的錯誤 |
| --- | --- | --- |
| `1.005` USD/share | `USD 1.01 / share` | binary float tie 漂移 |
| `-1.005` USD/share | `USD −1.01 / share` | 負數採不一致 rounding |
| `-0.000000004` USD/share | `USD −4.00e−9 / share` | 非零顯零、遺失負號 |
| `0.000000004` rate | `4.00e−7%` | raw 乘 100 後仍失去非零 |
| `0.00001234` USD/share | `USD 0.000012 / share` | 全欄一律兩位 |
| `0` rate | `0.00%` | 零誤當 missing |
| `-0.000` rate | `0.00%` | 負零干擾方向 |
| `null` | `缺失` 加原因 | 缺失補零 |
| not applicable | `不適用` 加原因 | 與缺失共用短橫 |
| unavailable | `尚無可用資料` 加原因 | 以 loading 無限等待 |
| `0.6` Beta | `0.60` | 看值域猜百分比 |
| `1.25` rate | `125.00%` | clamp 比例至 100% |
| `999995000` currency | `USD 1.00B` | rounding 跨門檻不換單位 |
| `1000000000000000000000000` currency | `USD 1.00e+24` | 超長數字撐破容器 |
| `1000000` count | `1,000,000` | count 誤變 currency 或 compact |
| raw `331839000000`、scale `6` | `USD 331.84B` | 重複套用 source scale |
| 同表 331.839B 與 0.00003B | 一致 `USD B`，提高精度或 scientific cell 並註明 | 個別換單位讓欄位不能比較 |
| NaN、Infinity、空字串、錯誤型別 | boundary parser 錯誤 | component 隨意 fallback 成零 |

負數用 Unicode minus，且仍有文字或符號，不只靠紅色。股數使用 `shares`，基本、稀釋、期末普通股均有完整名稱。

## 完整精度與來源入口

每個主數值都是具名按鈕，例如「查看 deterministic base 每股值的來源」。Enter、Space 或觸控均開相同 inspector。Hover tooltip 只是額外預覽，不能是取得完整數字的唯一方式。

Inspector 先顯金融名稱、來源類型、期間、單位、完整 Decimal，再顯公式與來源文件。原文允許換行，使用 Geist Mono；主值不在每個字元間斷行。長 URL 和 hash 可折行，技術身分預設收起。

「複製原始數值」只複製 raw，不含幣別、千分符、換行或顯示 rounding。「複製顯示值」另設按鈕，回饋明確說明複製哪一種。剪貼簿失敗時顯示可選取原文字區，不假稱成功。關閉 inspector 後 focus 返回原數值；若原元素因切報告消失，返回報告標題。

## 依據

2026-11-23 已讀 ONS [rounding](https://service-manual.ons.gov.uk/content/numbers/rounding)、[money](https://service-manual.ons.gov.uk/content/numbers/money)、[percentages and percentage points](https://service-manual.ons.gov.uk/content/numbers/percentages)。採納按任務取精度、同序列一致小數位與區分百分點的原則。ISO 幣別、M/B/T、HALF_UP 與微小值例外是本專案研究建議，不冒稱 ONS 的強制金融標準。
