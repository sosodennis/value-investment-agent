# #477 交付提交檢查

交付提交 `541c8a9ca550e179173ddb7341cdeee3cea0dff4` 的 frontend Git tree 為 `503fd670d117a044b05f1c9ed0c7183f7669a4c7`，與產品審閱及正式截圖 commit `c46d9fba191c3b793749198ca444b5ef96f3396d` 完全相同。交付提交新增公開驗收與圖片，未改 frontend source。

## 前端檢查

命令在 canonical runtime worktree 的 `frontend/` 執行。

| 命令 | Exit | 結果 |
| --- | --- | --- |
| `npm run lint` | 0 | pass |
| `npm run typecheck` | 0 | pass |
| `npm run test -- --run` | 0 | 59 files，517 tests |
| `npm run check:contrast` | 0 | pass |
| `npx playwright test --config e2e/fundamental-report-live.config.ts --grep retained` | 0 | 5 cases；完整 #462 artifacts／snapshots，先核對 SHA-256 |

## Runtime 檢查

Frontend image：`sha256:98de139b6effa715776d6312b3fe153be70a4f839c2ef14881c56cc0ad1e11ea`。實際 binding：`127.0.0.1:22681`。

```sh
ACCEPTANCE_MANIFEST=/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/runtime/runtime-tuple.json REQUIRE_SEC_IDENTITY_RESOLUTION=1 scripts/acceptance_preflight.sh
python3 /Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/runtime/verify-runtime-source.py
```

兩命令 exit 0，exact commit=541c8a9c，SEC identity capability=true。Fundamental 183 files、backend 818 files 無 mismatch，沒有 extra Python files。

## 原生檢查

正式 Chrome reload c46d9fba 後，以 Cmd+Plus 五次觀察 Zoom:200%，公司、估值、分位與關鍵假設重排可讀；Cmd+0 後還原 100%。正式 Copy original value 顯示 Original value copied.，以 Cmd+V 貼入原生 TextEdit，AX value 逐字等於：

```text
229.88242539685962775556419207139754074672901162460
```

已 undo 暫存貼文並返回 Fundamental。沒有使用 navigator mock 代替剪貼簿。此原生檢查的 frontend source 與 541c8a9c 相同。

VoiceOver 已嘗試啟動，但沒有可核對的朗讀、字幕或 Copy Last Phrase 輸出。F20 仍未通過；啟動 process 與 AX tree 不能證明 screen reader 可用。

## 最終真實服務結果

實作及 runtime 提交：`541c8a9ca550e179173ddb7341cdeee3cea0dff4`。以下命令在 `frontend/` 執行，trace、video 與自動截圖均關閉。

```sh
FUNDAMENTAL_LIVE=1 \
FUNDAMENTAL_LIVE_BASE_URL=http://127.0.0.1:22681 \
FUNDAMENTAL_LIVE_LOGIN_FILE=/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/runtime/login.json \
FUNDAMENTAL_LIVE_HISTORY_THREAD_ID=thread_7a3a4b05-00cb-4d0c-9525-4124a2f46a79 \
FUNDAMENTAL_LIVE_HISTORY_RUN_ID=cb0bd42e-4580-4671-8513-d7cdfa4c2aaf \
FUNDAMENTAL_LIVE_HISTORY_ARTIFACT_ID=bb6147b4-341c-4cae-a904-c69b18b5207f \
FUNDAMENTAL_LIVE_IMPLEMENTATION_COMMIT=541c8a9ca550e179173ddb7341cdeee3cea0dff4 \
FUNDAMENTAL_LIVE_OUTPUT_DIR=/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/live-541c8a9c \
npx playwright test --config e2e/fundamental-report-live.config.ts --grep 'real service'
```

Exit 1，5 passed、1 failed，4.2m。唯一失敗是 light/dark 在 320px 的 document 寬 327px。390/768/1440px、獨立窄 pane、reduced motion 與完整 focus cycle 已執行並保存證據；soft assertion 失敗仍使測試失敗。

| 案例 | 結果 |
| --- | --- |
| 2.5% draft／revision | pass |
| 5%服務拒絕／previous／draft | pass |
| Research termination | pass |
| Immutable history／raw／scope | pass |
| Layout | fail，#480 |
| Touch evidence | pass |

Retained 命令使用 `FUNDAMENTAL_RETAINED_DIR=/Users/denniswong/.codex/diagnostics/issue-462-fundamental-report/runtime`。檔名與固定 SHA-256 在 `frontend/e2e/fundamental-report-live.retained.spec.ts`，重現步驟在 `frontend/e2e/fundamental-report-live.md`。
