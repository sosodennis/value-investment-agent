# #532 retained-data recovery runtime 部分驗收紀錄

狀態為 PARTIAL。本文保存固定 `c7ac47cc8abcabf59e906be130cee5d22b2c8b85` 的隔離還原、重試及讀取結果。未撰寫 operator runner 的 reviewer 已給予窄範圍 runtime PASS。完整 #532 與 #495 仍未完成，必要 blockers 保持 pending。

[PR #536](https://github.com/sosodennis/value-investment-agent/pull/536) 為 Draft，尚未合併。此證據基準的 main 為 `9b76e799aa65a28dd77b19a65d732468f0817a18`。C7 的結果不移用至其他 PR head。來源材料的年度 materialization revision 仍為 `31b2483d064e5aee8b3ea6bc79e391eeec6ae7a5`，原 `5753be99` witness 身分與 publication records 保留，沒有新 build 的 current witness、classification、display 或 valuation 批准。

## 固定身分與停止狀態

| 項目 | 留存值 |
| --- | --- |
| Implementation commit | `c7ac47cc8abcabf59e906be130cee5d22b2c8b85` |
| 驗收 worktree | `/Users/denniswong/.codex/worktrees/issue-532-recovery-runtime/value-investment-agent` |
| 驗收 branch | `codex/issue-532-recovery-runtime` |
| Compose project | `value-investment-agent-denniswong-532-recovery-c7` |
| Image | `sha256:b8921be60bbf3bd0d5f68d62198adb7fa13a275616e9f1e20ffd1d24280231b1` |
| 已安裝 source | 213 個 Python 檔逐 bytes 等於 c7 checkout |
| Image pins | Python 3.12.16、Arelle 2.47.4、Pydantic 2.14.2 |
| Host test Python | 3.12.12，與 image pin 分別記錄 |
| Ordered Compose files | `compose/verification/docker-compose.issue280-operations.yml`、`docker-compose.issue312-sec-ingestion.yml`、`docker-compose.parser-actions.yml`，再加當輪 external `runtime.yml` |
| 驗收時 bindings | App `127.0.0.1:23890`、target PostgreSQL `127.0.0.1:23891`。Source PostgreSQL 預定 23893，fence 後無 binding |
| App project 與 browser | 無 application project，browser 未執行 |
| 現在狀態 | 本輪三個服務全 STOPPED。原 21 個 containers 未變，volumes、host content 與兩份新 v2 保留 |

完整歷史 tuple、env 路徑與 SHA-256 在包內 `payload/operator/runtime-tuple.json`。Tuple 與 handoff 的 healthy 是驗證當時狀態，後續停止紀錄為 `payload/root/idle-stop.json`。本機 paths 僅用於連結當次證據，收件人核對公開包不需具備這些路徑。Env 本文與 credentials 不公開。這份文件及其 evidence JSON 不是 canonical runtime manifest，也不取代原 preflight。

## 備份、來源 fence 與重試

| 輸入 | Manifest digest | Objects／tables／rows |
| --- | --- | --- |
| 原 v1，原 575 revision | `bf9d604c9dcb97b0b0b880cb22c0d22a5a1bc965419727a33bdcf8edae9b0710` | 5333／19／17768 |
| 第一份新 v2，c7 | `94464283379f040a473b7a3344981918825775ebfc9a0d88bd4b7345c88d42d2` | 5333／26／17776 |
| 選定第二份新 v2，c7 | `c473c1a036e50da3db2cf482657ea9d9ac1d7d30c8df48e8e26c2543f4f81197` | 5333／26／17776 |

舊 v1 以原官方 image 讀取，沒有改標成 v2。兩份新 v2 除 frontier 外完整 manifest 相同，第一份仍保留。獨立 reviewer 逐檔核對三份 backup inventory。Target 的 5333 個檔案、1,992,794,265 bytes 另以完整集合、長度與 hash 核對相同。26 表依正式 immutable prefix、target additions 與 bootstrap timestamp 契約核對通過。公開包保留核對摘要，不含 inventory 中的資料本體。

Source cluster system identifier 為 `7712057061483032610`，origin 為 `f9540aeb-fcf7-489b-a4c6-9eb2ce635f62`。Target 為另一個 cluster，system identifier `7712057532341739555`，origin `02a6875a-f2c0-4f0b-96d5-6aaea3fcb9ad`，timeline 1、database OID 16384。新 source 在 target import 前已停止，source fence 的留存 hash 為 `bcc9ab66108e65b581a2deb0947a00675fbc7044a95b62a8d338de4216f12226`。原其他 runtime 不作為本輪 source fence。

Maintenance UID10002 獨立建立 pin。Pin 綁定選定 v2、source origin、target physical identity、runtime role 及 source fence。Operation ID 與 pin canonical SHA-256 同為 `6507303fe4c6c046d3836e2246b45292db80805246e6c4d799b1e0ffeb06814b`。公開內容只有 pin metadata receipt，沒有 authorization pin 本文。

| 時間 | UTC |
| --- | --- |
| Source frontier F | `2026-11-25T10:52:25.299308Z` |
| Target import commit C | `2026-11-25T10:57:47.361133Z` |
| Target visibility U | `2026-11-25T10:57:47.365972Z` |

三次官方 restore 均 exit 0，符合 F < C <= U。三份完整 receipts 除 `wrote` 外相同，`wrote` 依序為 true、false、false。第三次發生在正常低權限 runtime 追加 local raw artifact evidence checkpoint 之後。隨後的公開 history 純讀確認三個 entries、payload bytes、digests、C/U 與 epoch 均保留，零 checkpoint、seal 或 signing。Imported entries 的 `require_current_epoch` 明確拒絕，local raw artifact checkpoint 接受。這個 epoch 分型不構成 authority 或 classification 批准。

## 真實角色、偏離與獨立核對

App 的實際 UID 為 10001，SQL `current_user` 與 `session_user` 均為 `issue532_runtime`，AUTO_MIGRATE=0。Reviewer 以實際 app DSN 完成 readonly 查詢、公開 history read 與 26 表核對。Runtime 沒有 owner membership、privileged attributes、有效 ADMIN、schema CREATE、recovery staging、installer EXECUTE、server-file 或 program 能力。實際 env 沒有 maintenance credential keys，mounts 沒有 maintenance volume、Docker socket 或 private focus key。

正常內容讀取所需 `content_objects` INSERT 來自既有 `INSERT ON CONFLICT DO NOTHING`。History 的 `FOR SHARE` 所需 UPDATE 只授予 `artifact_references.status` 單欄。沒有 artifact hash UPDATE、DELETE、owner 或 recovery 能力，核對的 metadata 投影保持相同。

Standalone runtime env 曾多帶未使用的 owner password 變數。這次準備偏離保留在 correction 與 operator handoff。修正後重驗實際 env 及 SQL role，同 checkpoint entries、C/U 不變，再作第二份新 frontier export。第一份 v2 與舊錯誤紀錄保留，第一輪 checkpoint 不作為 OS credential 隔離證據。

Operator 以 UID10001 對 UID10002 的 private pin 實測讀取、寫入及建立 sibling，三案均為 PermissionError 13。獨立 reviewer 核對留存 log，沒有重跑此 OS probe。Reviewer 自行核對 live app 的角色、env keys 及無 maintenance mount。兩種核對範圍分別記錄。

獨立驗證固定 76 個 handoff pins，開始與結束的 178 份 input hashes 相同。報告與結果在 `payload/independent/review.md`、`results.json`。[先前 53 cases 的 ACL 與 clock 修正 review](https://github.com/sosodennis/value-investment-agent/pull/536#issuecomment-7159138546) 是另一輪範圍，不能替代本輪 runtime 驗證，也不等於完整 recovery/security 審閱。Operator 與 reviewer 的工具準備錯誤保留在原報告，沒有算成產品負例或成功 gate。

## 年度讀取與命令結果索引

Apple、Microsoft 各 historical 與 current 四案，內部 authenticated HTTP 均 200，完整 `result` objects 等於原 31b materialization responses，共 500 格。比較不包含 correlation/context 的整個 HTTP response bytes。這輪沒有重做 core ownership、saved artifact GET、workspace 或 browser 驗收，也沒有重標原年度身份。

以下為已執行結果與官方入口的索引。命令中的 deployment、env、bundle 與輸出路徑由每次驗收的獨立 tuple 定義。

| 命令或檢查 | 結果 | 包內證據或公開紀錄 |
| --- | --- | --- |
| 原 Dockerfile build、source bytes 與版本核對 | exit 0，213 檔相同 | `payload/operator/build-and-resource-result.json`、`runtime-tuple.json` |
| `fundamental-persistence export --source-revision "$IMPLEMENTATION_COMMIT" --destination "$BACKUP_ROOT"` | 兩份新 v2 export 成功，保留不同 frontier | `payload/operator/handoff.md`、`runtime-tuple.json` |
| `fundamental-persistence restore --bundle "$RETAINED_BUNDLE" --manifest-digest "$MANIFEST_DIGEST" --authorization "$PRIVATE_AUTHORIZATION"` | 三次均 exit 0 | `payload/receipts/restore-1.json` 至 `restore-3.json`、獨立報告 |
| Canonical Compose `config --quiet` 及 SEC preflight | exit 0，PASS，`full_replay_acceptance=false` | `payload/independent/preflight-result.json`、`review.md` |
| 獨立 bundle bytes、runtime history、26 表及年度 live read | 各 exit 0 | `payload/independent/results.json` 與各摘要 |
| Host 完整 Fundamental suite | exit 0，6088 passed、84 skipped、0 failed | `payload/root/service-suite.json`，含原命令與 skip 原因 |
| Retained annual originals 補跑 | exit 0，207 passed、0 skipped | [#532 測試交付紀錄](https://github.com/sosodennis/value-investment-agent/issues/532#issuecomment-7159660724)。原 log 留存，未放入公開包 |
| 固定 c7 CI | success，服務 suite 6091 passed、81 skipped | [CI run 45590766177](https://github.com/sosodennis/value-investment-agent/actions/runs/45590766177)、`payload/ci/run-summary.json` |
| 停止本輪三個服務 | Compose config 與 stop 均 exit 0 | `payload/root/idle-stop.json` |

CI 的 `fundamental-service-release-gate` 成功，另一個名為 `fundamental-release-gate` 的條件性 job 為 skipped。整體 CI success 不代表 skipped job 已執行，suite skips 也不代表正式季度來源驗證通過。

Canonical preflight report SHA-256 為 `d5692c93c30796215fd919d3712ccb147270a4b274f55dc12f4b8d29ccf7a09d`。其參數化入口如下，這是命令語法參考，不表示停止中的 runtime 目前可讀。

```sh
ACCEPTANCE_MANIFEST="$OWN_CANONICAL_MANIFEST" \
REQUIRE_SEC_IDENTITY_RESOLUTION=1 START_ACCEPTANCE_STACK=0 ACCEPTANCE_BUILD=0 \
bash "$CHECKOUT/scripts/acceptance_preflight.sh" --report-directory "$OWN_REPORT_DIRECTORY"
```

## 可分享證據的封裝狀態

[issue-532-recovery-evidence.json](issue-532-recovery-evidence.json) 記錄封裝身份。[PARTIAL prerelease](https://github.com/sosodennis/value-investment-agent/releases/tag/issue-532-recovery-runtime-c7-v1) 已發布，tag `issue-532-recovery-runtime-c7-v1` 指向固定 c7。[獨立 privacy／accuracy 審閱](https://github.com/sosodennis/value-investment-agent/pull/536#issuecomment-7162105863) 與 [GitHub 全新下載核對](https://github.com/sosodennis/value-investment-agent/pull/536#issuecomment-7162361159) 均為窄範圍 PASS。封裝 bytes 保持下列固定值。

| 項目 | 值 |
| --- | --- |
| ZIP | `issue-532-recovery-runtime-c7-v1.zip`，37,488 bytes |
| ZIP SHA-256 | `b8c17d632c703f3050da7cd86584b2bf86c690b5fee6e96549e10bb110134379` |
| Manifest SHA-256 | `6fba4a79f750112d4c90faae53505d5608e30758174cdea8555d62ddac059213` |
| 包內集合 | 30 個 regular files，含 manifest 的 28 個 declared members、`manifest.json` 與 `SHA256SUMS` |
| Payload | 26 份原 bytes metadata 與 1 份派生 CI 摘要，另有 README |
| 檢查 | 兩次 build 相同、完整 allowlist 及逐檔 bytes/hash 通過、未知 member 與 corruption 拒絕，absolute 與 traversal 名稱在建包時拒絕 |

公開樹只含 `README.md`、`payload/...`、`manifest.json` 與 `SHA256SUMS`。Manifest 協定為 `issue532-recovery-runtime-evidence-v1`，逐檔保存 member path、bytes、SHA-256、來源 alias 與 source hash。CI 摘要明列 derived，其 source SHA-256 為 `bd58bbb6dfa0258a9d0ca2f3d277a394401259fe6dc85cc5a9fd48fa7b1515f0`，只保留 head、status、conclusion 及 job 名稱與狀態，沒有完整 CI log。Manifest 不含自身 hash，`SHA256SUMS` 不列自身，ZIP 外層 hash 由 repository metadata 另記。

每份來源 metadata 已人工閱讀。秘密值掃描從既有 private env 在記憶體讀取 PASSWORD、TOKEN、SECRET 及 DSN password，公開 members 沒有 matches。沒有列印或保存秘密值。未寫包者已對固定公開包及原版文件完成獨立發布 review；其後的兩個引用增量由另一位 fresh-download reviewer 核對，包的 bytes 未變。實際 publication URL／狀態由 Root 讀回後追加，不把舊文件 hash 的 review 說成新 metadata 全量審閱。

封裝的完整性核對依序比較外層 ZIP hash、manifest hash、30 個檔案的完整集合、每個 declared member 的長度與 hash，以及 `SHA256SUMS`。核對契約拒絕未知或重複 member、absolute path、`..`、symlink 及內容差異。公開摘要只能支持核對已觀察結果，不能單靠本包重算財務或恢復資料庫。

完整重播另外需要合法 retained originals、完整 bundle、正式 resources、private authority 與收件人自己的部署配置。官方操作與來源取得方法見[operations runbook](../../fundamental-service/docs/operations-runbook.md)、[年度 fixtures README](../../fundamental-service/tests/fixtures/annual-statements/README.md)、[季度 fixtures README](../../fundamental-service/tests/fixtures/quarterly-statements/README.md)及[來源用途界線](../../fundamental-service/docs/source-use-coverage.md)。重取產生的新 capture metadata 如實保留為新 input，不借本包變更原 source revision。公開包沒有 SEC 原件、完整備份、DB rows、完整 artifact 或 HTTP body、env 本文、private keys 或 authorization pin，也不擴張來源再分發、display 或 valuation 權利。

## 未完成的必要範圍

原完整 recovery/security、current-epoch 與 classification consumers 仍 pending。本輪 raw checkpoint 與窄 runtime PASS 不解除這些 blockers。季度與 TTM 的正式 release/read、core artifacts、workspace、Q01–Q14、必要完整獨立審閱與 main 交付仍未完成，#495 的完整使用者結果不變。

可核對的公開交接為[獨立 runtime 報告](https://github.com/sosodennis/value-investment-agent/pull/536#issuecomment-7161285399)、[#532 交付紀錄](https://github.com/sosodennis/value-investment-agent/issues/532#issuecomment-7161297854)與[#495 checkpoint](https://github.com/sosodennis/value-investment-agent/issues/495#issuecomment-7161308551)。文件與封裝完成不代表任一功能票可合併或結案。
