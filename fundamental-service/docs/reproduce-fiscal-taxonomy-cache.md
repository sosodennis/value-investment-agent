# 重建 fiscal taxonomy cache

本文件補充 [operations runbook](operations-runbook.md) 的離線 taxonomy cache
章節。`tests/fixtures/annual-statements/` 內的兩個 base manifest 固定 issue
#494 retained inventory。Issue #522 delta fixture 只增加官方 ECD submission
schema `https://xbrl.sec.gov/ecd/2026/ecd-sub-2026.xsd`，並固定 bytes、SHA-256、
base manifest 檔案 hash、舊 cache hash 與新 cache hash。

從 repository root 執行。`--retained-cache` 指向保留的舊 cache，
`--destination` 必須是另一個新目錄，兩個目錄不能互相包含。

```sh
export FUNDAMENTAL_SEC_USER_AGENT='Your Name your.email@example.com'
uv run --frozen --project fundamental-service python fundamental-service/scripts/rebuild_taxonomy_cache.py \
  --delta-manifest fundamental-service/tests/fixtures/annual-statements/issue522-ecd-taxonomy-resource-delta.json \
  --base-manifest fundamental-service/tests/fixtures/annual-statements/issue494-sec-taxonomy-resources-part-1.json \
  --base-manifest fundamental-service/tests/fixtures/annual-statements/issue494-sec-taxonomy-resources-part-2.json \
  --retained-cache /path/to/retained-cache \
  --destination /path/to/new-cache \
  --allow-network
```

`--allow-network` 只在缺少 pinned resource 時，依官方 HTTPS URL 取得該檔案。
已有新增 schema 的 retained cache 可斷網重建，移除 `--allow-network`，並將
`--retained-cache` 指向該 cache。每個 resource 都會核對 byte size 與 SHA-256。
重跑同一 target 會保留相同 bytes 與 mtime。builder 會拒絕 changed base、missing
或 corrupt resource、unexpected file、相交的目錄，以及離開 target 的 resource symlink。

命令輸出的 SHA-256 必須等於 delta fixture 的新 `cache_sha256`。
舊 cache hash `fbcd82b406a2420f37bf17c7afc8baa823e7cfadd2308ccb8bfecf88648a9691`
保持不變。新 cache hash
`af63b0b36d5cad6f2788e90fc323b56955ce581fd84e41330bac4ba765f3a6f0`
是另一個 resource identity，供 fiscal runtime 明確選用。年度 retained validation
與 read 繼續使用原 pin。
