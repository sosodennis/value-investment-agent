# 重跑 #493 來源核對

此 how-to 使用固定 SEC originals、保留的 public capture 及部署 policy，
產生來源、解析、語義、用途與拒絕結果。先讀[用途與 coverage reference](source-use-coverage.md)。
所有指令在 repository root 執行，使用 Python 3.12.12 與 `fundamental-service/uv.lock`。

## 取得固定輸入

SEC HTML、accession ZIP 與 2024 taxonomy cache 已在
`fundamental-service/tests/fixtures/sec-edgar/`，其來源及 hash 由現有
`capture_manifest.json` 記錄。不要用今天重新下載的文件冒充相同輸入。

Public capture、terms、research pages 及 full parser reports 由 #493 的版本化證據包提供。
Repo 的 `tests/fixtures/source-coverage/issue493-evidence.json` 記錄下載 URL、archive hash
及結果摘要。下載後先比對 SHA-256，再解壓縮到新的工作目錄。
Evidence 包內保留原始 acquisition requests、時間與 receipts；不要重新產生 timestamp。

```sh
uv sync --frozen --python 3.12.12 --extra dev --project fundamental-service
mkdir -p /tmp/issue493-replay
gh release download issue-493-source-coverage-v1 \
  --repo sosodennis/value-investment-agent \
  --pattern issue493-evidence-v1.tar.gz --dir /tmp/issue493-replay
shasum -a 256 /tmp/issue493-replay/issue493-evidence-v1.tar.gz
# 將上面的值與 repo manifest 核對，符合才解壓縮。
tar -xzf /tmp/issue493-replay/issue493-evidence-v1.tar.gz -C /tmp/issue493-replay
```

## 離線重播

```sh
PYTHONPATH=finance-agent-core uv run --frozen --extra dev --project fundamental-service python \
  fundamental-service/scripts/reproduce_source_coverage.py \
  --cohort fundamental-service/tests/fixtures/source-coverage/issue493-cohort.json \
  --matrix fundamental-service/tests/fixtures/source-coverage/issue493-matrix.json \
  --evidence-dir /tmp/issue493-replay/evidence \
  --output /tmp/issue493-replay/result.json
```

預設不連網。缺少或損壞的 receipt、original、parser report、terms 或 profile pin
會失敗，不會補抓或修復。結果輸出必須放在 evidence directory 之外。
SEC retained report 的來源、內容完整性、runtime、taxonomy 與 profile 仍會重新核對，
再從 report 重算觀察；不信任舊的 summary。

Public 成功案例的 cutoff 是原始 request 與實際 capture availability 的較晚者。
初始 request 早於 HTTP capture 而保留的 `SOURCE_NOT_AVAILABLE_AT_VALUATION`
不改寫；早 cutoff 測試仍必須拒絕。不同 cutoff 是不同 admission，不是更改來源歷史。

同一指令再跑一次，結果應相同，retained inputs 的 bytes 與 mtime 不變；
不呼叫 HTTP 或 parser。新環境須使用相同鎖定依賴，identity 不同不能宣稱 identical-input reuse。
工具首次為未保存的 SEC input 產生 parse-only report 時會執行 parser，之後才可談 reuse。

## 明確重新取得 public 來源

只有調查新輸入時才使用 `--capture-public --user-agent`，並給新的 evidence directory。
User-Agent 須含負責人的有效聯絡方式。此旗標只透過既有 acquisition owner 取 public
來源，不重抓 SEC fixtures，也不能授予用途。新網頁、時間或 hash 是新輸入，
不能與上述固定證據混稱相同輸入重播。
工具要求既有 `requests.json`；以下沿用同一個 business request，新的 capture
另記實際 availability，不改寫原證據。

```sh
mkdir -p /tmp/issue493-new-capture
cp /tmp/issue493-replay/evidence/requests.json /tmp/issue493-new-capture/requests.json
PYTHONPATH=finance-agent-core uv run --frozen --extra dev --project fundamental-service python \
  fundamental-service/scripts/reproduce_source_coverage.py \
  --cohort fundamental-service/tests/fixtures/source-coverage/issue493-cohort.json \
  --evidence-dir /tmp/issue493-new-capture \
  --capture-public --user-agent 'SourceResearch/1.0 contact=YOUR_VALID_CONTACT' \
  --output /tmp/issue493-new-result.json
```

不要把新抓到的條款 digest 自動寫入 policy。若資料時點、用途或 terms pin 拒絕，
保留正式 code，沿 owning layer 處理；來源可得性不會解除計算或授權 gate。
