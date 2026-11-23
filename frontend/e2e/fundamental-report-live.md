# Fundamental 真實服務驗收

這組 Playwright 案例連向既有正式頁面及真實服務，不會啟動 server，也沒有 API 回應替身。先依 issue 的 canonical runtime tuple 核對實作 commit、Compose project、env-file hash、實際 ports、Docker health 及 acceptance preflight，再執行本測試。

在 `frontend/` 執行。

```sh
FUNDAMENTAL_LIVE=1 \
FUNDAMENTAL_LIVE_BASE_URL='http://127.0.0.1:<published-frontend-port>' \
FUNDAMENTAL_LIVE_LOGIN_FILE='/absolute/runtime/login.json' \
FUNDAMENTAL_LIVE_HISTORY_THREAD_ID='<retained-thread-id>' \
FUNDAMENTAL_LIVE_HISTORY_RUN_ID='<retained-run-id>' \
FUNDAMENTAL_LIVE_HISTORY_ARTIFACT_ID='<retained-artifact-id>' \
FUNDAMENTAL_LIVE_IMPLEMENTATION_COMMIT='<exact-running-commit>' \
FUNDAMENTAL_LIVE_OUTPUT_DIR='/absolute/diagnostics/live-proof' \
npx playwright test --config e2e/fundamental-report-live.config.ts
```

登入檔只需 `email` 與 `password`。不要提交該檔、session state 或任何 secrets。本設定關閉 trace、video 及自動截圖，只在登入成功後保存明確命名的報告截圖與 JSON 證據。

預備的 history 必須是可讀回的 MSFT 估值，包含 Monte Carlo 分位數、revenue fact、`revenue_1` node 及服務 scenario。UI 新 analysis 須可走到可修改的 automatic preparation。Research 案例要求此隔離環境回傳 unavailable、error 或沒有可接受 claim；licensed Research success 由另案驗證。案例會新建三份 analysis，並從各自的新 run 進行一次成功重算、一次拒絕或一次 Research。

本設定不重試失敗案例。Revision 與 Research 都從 `/workspace` 的新 analysis 開始，提交前會確認未切換成 history route。History 案例使用獨立的唯讀 session，並核對提供的 artifact ID。

一般 CI 未設定 `FUNDAMENTAL_LIVE=1` 時，六個案例會明確 skip。Skip 只代表沒有執行，不是驗收通過。可先用以下指令檢查測試載入，這不會開啟瀏覽器。

```sh
npx playwright test --config e2e/fundamental-report-live.config.ts --list
```

每次實跑會記錄提供的實作 commit、真實 URL、thread/run/artifact、建立日期、preparation digest、result hash、canonical base 與當次分位數。重算與 history 案例使用正式 parser 核對各自資料，不要求 Monte Carlo 數字重現舊樣本。

自動案例涵蓋 draft 與 previous result、精確 raw `0.025`、新結果唯讀、真實 `MANUAL_OVERRIDE_INVALID`、Research 結束、history 無 mutation、各來源 scope、light/dark、320/390/768/1440px、獨立窄 report pane、reduced motion、正反向 Sheet focus cycle、Escape、focus return 與 touch。

真正 200% browser zoom、螢幕閱讀器、系統剪貼簿貼上及視覺品質仍需在同一正式 UI 實測。Headless viewport、DOM focus 與 reduced-motion 設定不代替這些項目。`F01–F09` 的固定樣本與 formatter 邊界由對應回歸測試核對。
