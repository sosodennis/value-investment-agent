# #477 交付提交檢查

交付提交`849df68e7f03da8489ae285dafe0cdcf39cdfa74`含Header修正與正式圖。Frontend tree為`d94bad25652d1e6f2d1b06e37fe33f2dba78d26d`，與75c75c29相同；c46d9fba之後唯一frontend source差異為app-shell Header。後續僅本issue驗收Markdown／JSON。

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

Frontend image：`sha256:43077280f5381252d85131bc6761cfd42a56d7289baa7b13ffbc3fb94caec08c`。實際 binding：`127.0.0.1:22681`。

```sh
ACCEPTANCE_MANIFEST=/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/runtime/runtime-tuple.json REQUIRE_SEC_IDENTITY_RESOLUTION=1 scripts/acceptance_preflight.sh
python3 /Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/runtime/verify-runtime-source.py
```

兩命令 exit 0，exact commit=849df68e，SEC identity capability=true。Fundamental 183 files、backend 818 files 無 mismatch，沒有 extra Python files。

## 原生檢查

正式 Chrome reload c46d9fba 後，以 Cmd+Plus 五次觀察 Zoom:200%，公司、估值、分位與關鍵假設重排可讀；Cmd+0 後還原 100%。正式 Copy original value 顯示 Original value copied.，以 Cmd+V 貼入原生 TextEdit，AX value 逐字等於：

```text
229.88242539685962775556419207139754074672901162460
```

已 undo 暫存貼文並返回 Fundamental。沒有使用 navigator mock 代替剪貼簿。Clipboard inspector source在849df68e未變；75c75c29另重新載入正式Chrome，核對真正200%zoom、公司及數字reflow，並還原100%，畫面已公開。

VoiceOver 已嘗試啟動，但沒有可核對的朗讀、字幕或 Copy Last Phrase 輸出。實際朗讀仍未驗證；依使用者最新優先序不作本次交付門檻。未把process或AX tree當成朗讀pass。

## 最終真實服務結果

實作及 runtime 提交：`849df68e7f03da8489ae285dafe0cdcf39cdfa74`。以下命令在 `frontend/` 執行，trace、video 與自動截圖均關閉。

```sh
FUNDAMENTAL_LIVE=1 \
FUNDAMENTAL_LIVE_BASE_URL=http://127.0.0.1:22681 \
FUNDAMENTAL_LIVE_LOGIN_FILE=/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/runtime/login.json \
FUNDAMENTAL_LIVE_HISTORY_THREAD_ID=thread_7a3a4b05-00cb-4d0c-9525-4124a2f46a79 \
FUNDAMENTAL_LIVE_HISTORY_RUN_ID=cb0bd42e-4580-4671-8513-d7cdfa4c2aaf \
FUNDAMENTAL_LIVE_HISTORY_ARTIFACT_ID=bb6147b4-341c-4cae-a904-c69b18b5207f \
FUNDAMENTAL_LIVE_IMPLEMENTATION_COMMIT=849df68e7f03da8489ae285dafe0cdcf39cdfa74 \
FUNDAMENTAL_LIVE_OUTPUT_DIR=/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/live-849df68e \
npx playwright test --config e2e/fundamental-report-live.config.ts --grep 'real service'
```

最終runner為6passed（4.8m）；`.last-run.json`為status=passed、failedTests=[]。Result verifier exit0，核對全部6案完成及每案JSON的implementationCommit為849df68e。原始log在runtime/live-849df68e.log。Layout未改斷言、retries=0、workers=1。

| 案例 | 結果 |
| --- | --- |
| 2.5% draft／revision | pass |
| 5%服務拒絕／previous／draft | pass |
| Research termination | pass |
| Immutable history／raw／scope | pass |
| Layout四寬／明暗／窄pane／reduced motion／完整focus cycle | pass |
| Touch evidence | pass |

Header額外10個route/width控制項檢查exit0；settings內容overflow另列#482，未宣稱整頁pass。獨立reviewer另核對light/dark×四寬與nav/org focus。No-comments及Header delta專項為0 findings，未替代完整review。

Retained 命令使用 `FUNDAMENTAL_RETAINED_DIR=/Users/denniswong/.codex/diagnostics/issue-462-fundamental-report/runtime`。檔名與固定 SHA-256 在 `frontend/e2e/fundamental-report-live.retained.spec.ts`，重現步驟在 `frontend/e2e/fundamental-report-live.md`。
