# 企業級金融估值模組拆分研究報告

## 摘要

本報告針對「成熟、企業級、代碼質量高」的金融估值相關開源項目進行調研，聚焦它們如何拆分大模組、如何劃分流程與功能邊界，並結合通用架構最佳實踐提出可落地的拆分建議。研究對象涵蓋 OpenGamma Strata、Open Source Risk Engine (ORE)、QuantLib、finmath-lib 等在行業中廣泛使用的開源估值/風險分析框架；最佳實踐部分則引用 DDD Bounded Context 與 Clean Architecture 的原始或權威來源，並在最後給出對於目前 fundamental 模組的拆分方向建議。[^strata-docs][^strata-flow][^ore-faq][^ore-docs][^quantlib-site][^quantlib-guide][^finmath-separation][^finmath-interfaces][^ddd-fowler][^ddd-ms][^clean-arch]

## 研究問題

1. 成熟估值框架在模組拆分上，主要是「流程導向」還是「功能導向」？
2. 它們如何處理市場數據、模型、產品、計算與報告之間的邊界？
3. 這些做法對我們的 fundamental 大模組可提供哪些具體拆分策略？

## 方法

- 來源限定為官方文檔或作者原始資料，以避免二手傳播失真。
- 針對每個框架整理「模組切分方式、流程分層、擴展點」三個維度。
- 以 DDD/ Clean Architecture 作為跨項目的架構抽象，提煉通用 best practice。

## 案例研究

### 1) OpenGamma Strata（市場風險與估值）

**模組拆分方式**

Strata 將系統拆分為多個清晰模組，例如 `collect`（共用工具庫）、`data`（市場數據容器）、`market`（曲線/曲面等市場表徵）、`loader`（產品/數據載入）、`pricer`（定價/風險分析）、`calc`（計算流程與計算任務執行）、`measure`（PV、PV01 等高階度量）、`report`（報告輸出）。這是一種以「功能與職責」為主的拆分方式。[^strata-docs]

**流程拆分方式**

Strata 明確定義「Calculation Flow」：setup → market data building → scenario building → calculation runner。每一段流程完成其單一職責並支持單獨執行，強調 fail-fast 與關注點分離。[^strata-flow]

**關鍵架構特徵**

- 「市場數據建構」具備獨立組件，能基於需求自動判斷、獲取、校準所需市場數據。[^strata-flow]
- MarketDataFactory 明確將「獲取原始數據」與「校準/建構市場數據」分離，提供外部提供者接口。[^strata-marketdata]

**結論**

Strata 同時採用了功能模組化（模块化拆分）與流程分段（pipeline），在大型估值系統中形成「雙重切分」。

### 2) Open Source Risk Engine (ORE)

**模組拆分方式**

ORE 被拆分為三個核心庫：QuantExt、OREData、OREAnalytics，並配有一個命令列應用示例。這是一個「平台分層」的拆分方式：QuantExt 提供 QuantLib 擴展，OREData 處理交易/市場數據結構與配置，OREAnalytics 對接計算與風險分析。[^ore-faq][^ore-docs]

**流程/用途拆分**

ORE 的官方文檔明確拆分為 User Guide、Product Catalogue、Methods 三大文檔體系；其中 User Guide 涵蓋主流程與參數化說明，Product Catalogue 描述產品與定價方法，Methods 針對風險與分析方法論分章闡述。[^ore-docs]

**成熟度信號**

ORE FAQ 明確指出該框架已在生產環境使用，屬於成熟的企業級參考框架。[^ore-faq]

**結論**

ORE 以「功能分層（Data/Analytics/Extension）」為主，並在文檔層面清晰拆分流程與方法論。

### 3) QuantLib

**模組拆分方式**

推論：QuantLib 以「產品（instrument）」與「定價引擎（pricing engine）」的解耦作為核心概念切分方式，拆分主軸偏向產品/模型/數值方法的分離。[^quantlib-guide]

**核心架構原則**

QuantLib 將「金融產品（instrument）」與「定價引擎（pricing engine）」分離，使同一產品可以選擇不同模型或數值方法計價。這是「產品與模型/數值方法解耦」的典型做法。[^quantlib-guide]

**定位**

QuantLib 官方定位其為「量化金融的開源框架」並強調其覆蓋建模、交易與風險管理。[^quantlib-site]

**結論**

推論：QuantLib 以「產品/模型/數值方法」解耦為核心拆分維度，並強調可替換的 pricing engines；這種拆分方式與大型估值系統的可擴展性需求一致。[^quantlib-guide]

### 4) finmath-lib

**模組拆分方式**

finmath-lib 明確提出「產品（Product）、模型（Model）與數值方法（Numerical Method）」三者分離，並以接口層級和描述子/工廠來解耦具體實現。[^finmath-separation][^finmath-interfaces]

**結論**

finmath-lib 的拆分方式更加偏「方法論 + 產品解耦」導向，與 QuantLib 的設計方向一致但更明確地強調接口與描述子的中介層。

## 橫向綜合：拆分維度對比

| 框架 | 主要拆分主軸 | 流程拆分 | 產品/模型解耦 | 數據與計算分離 |
| --- | --- | --- | --- | --- |
| Strata | 功能模組 + 流程分段 | 明確 calculation flow | 間接支持 | 強調 MarketData 構建與校準 |
| ORE | 平台分層 (QuantExt/OREData/OREAnalytics) | 文檔層級有流程拆分 | 基於 QuantLib 擴展 | Data vs Analytics 明確分離 |
| QuantLib | 產品/模型解耦（由 instrument/engine 分離推論） | 非顯式流程 | 明確 instrument/engine 分離 | 未在本次來源中明確 |
| finmath-lib | 產品/模型/數值方法分離 | 非顯式流程 | 明確 | 模型/數值方法解耦 |

推論：成熟估值框架通常同時使用「功能/領域拆分」與「流程拆分」，但會偏重其中一個作為主軸；Strata 更強調流程分段，QuantLib/finmath 更強調產品與模型解耦，而 ORE 將其封裝為平台分層。[^strata-docs][^strata-flow][^ore-faq][^ore-docs][^quantlib-guide][^finmath-separation]

## 最佳實踐（基於權威架構來源）

### 1) DDD 的 Bounded Context

- Bounded Context 是 DDD 處理大型系統的核心策略，用於將大模型拆分為多個一致且可獨立演進的上下文。[^ddd-fowler]
- Microsoft 的 DDD microservice 指南將 bounded context 與 microservice 對齊，並指出邊界設計是關鍵工作，應以業務問題劃分邊界。[^ddd-ms]

### 2) Clean Architecture 的 Dependency Rule

- 核心規則是「依賴只能向內指向」，內層（業務規則/用例）不應依賴外層（框架、UI、資料庫）。[^clean-arch]
- 這種規則使核心業務邏輯穩定，可替換外部實作細節而不影響內核。[^clean-arch]

推論：對估值系統而言，核心估值邏輯（產品/模型/計算）應作為穩定內核，而市場數據抓取、來源爬取、文件解析等應是可替換的外層。這與 QuantLib/finmath 的產品-模型分離，以及 Strata 的 MarketDataFactory 具有一致方向。[^clean-arch][^quantlib-guide][^finmath-separation][^strata-marketdata]

## 對 fundamental 模組的拆分建議（研究結論）

> 下列為研究結論性建議，並未直接修改現有代碼結構。

### 建議一：以「領域功能」作為主拆分軸

根據 QuantLib/finmath/ORE 的經驗，建議以穩定概念（Domain）拆出核心模組，再由流程 orchestrator 編排。

推薦拆分方向：

- `core_valuation`：估值模型、數值方法、審計與計算結果組裝（對應產品/模型/方法）。
- `financial_statements`：XBRL/財報解析與 canonicalization。
- `forward_signals`：前瞻信號抽取、信號校準、政策與 guardrails。
- `model_selection`：模型選擇規則、信號評分、解釋輸出。
- `market_data`：市場數據聚合與快照組裝（外層 adapter）。
- `artifacts_provenance`：artifact 存取、TraceableField/Provenance 保持一致。
- `workflow_orchestrator`：串接流程與錯誤控制。

這對應於 DDD 中的多個 bounded contexts，讓不同子域獨立演進，避免單一巨型模組。[^ddd-fowler][^ddd-ms]

### 建議二：流程拆分應作為「第二層」

Strata 的案例顯示流程拆分（calc flow）有助於 fail-fast 與責任分離，但它是「在功能模組之上」的流程編排層。[^strata-flow]

對 fundamental 而言，可以將流程層維持為 `financial_health -> model_selection -> calculation` 的 orchestrator，但每一步內部由上述 domain 模組提供能力，以避免流程層膨脹成巨型 use case。

### 建議三：明確定義內外層依賴方向

以 Clean Architecture 的依賴規則作為約束：

- 估值核心不得直接依賴 web crawler、SEC API、外部數據庫 SDK。
- 外層 adapter 實作透過 ports/clients 注入，讓核心保持穩定。[^clean-arch]

### 建議四：保持「產品/模型/數值方法」可替換

借鑒 QuantLib/finmath 的產品-模型-數值方法分離設計，對 fundamental 的 valuation runtime 做出可替換的 calculator/parameterization 模型集合，避免每次添加新模型都觸碰核心流程。[^quantlib-guide][^finmath-separation]

## 結語

企業級估值系統的成熟拆分模式通常不是單一維度，而是「功能/領域」與「流程分段」疊加，並以 DDD 與 Clean Architecture 作為邊界治理規則。對 fundamental 模組而言，先做 domain-driven 拆分，再以流程 orchestrator 組裝，將是降低模組膨脹與提高可維護性的最穩妥路徑。

## 參考資料

[^strata-docs]: https://strata.opengamma.io/docs
[^strata-flow]: https://strata.opengamma.io/calculation_flow/
[^strata-marketdata]: https://strata.opengamma.io/apidocs/com/opengamma/strata/calc/marketdata/MarketDataFactory.html
[^ore-docs]: https://www.opensourcerisk.org/documentation/
[^ore-faq]: https://www.opensourcerisk.org/faqs/
[^quantlib-site]: https://www.quantlib.org/
[^quantlib-guide]: https://www.quantlibguide.com/Instruments%20and%20pricing%20engines.html
[^finmath-separation]: https://www.finmath.net/finmath-lib/concepts/separationofproductandmodel/
[^finmath-interfaces]: https://www.finmath.net/finmath-lib/concepts/separationofproductandmodel/modelandproductinterfaces.html
[^ddd-fowler]: https://martinfowler.com/bliki/BoundedContext.html
[^ddd-ms]: https://learn.microsoft.com/en-us/dotnet/architecture/microservices/microservice-ddd-cqrs-patterns/ddd-oriented-microservice
[^clean-arch]: https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html
