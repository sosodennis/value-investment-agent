# Historical DQC compatibility diagnostic for #361

This document preserves the earlier 14-case checkpoint. Current full-suite conformance, original acquisition and Docker evidence are in [historical validation evidence](issue-361-historical-validation-evidence.md).

Status: **PARTIAL_DIAGNOSTIC_NOT_RELEASE_ACCEPTANCE**. Exact execution commit: `8970281cd954e6f649877754033c31721fc705da`. Production parser contracts are unchanged. #361, #369 and #371 remain open; PR #370 remains draft; supported history thresholds remain null.

## Observed behavior

Official DQC `v1.0.0`, immutable commit `266946cdecddf37c3d7d43b258eecb945a2daed3`, executed its six modules representing seven rule families with Arelle 2.47.4, strict all-years EFM 26.3 and XULE 30055. A captured temporary adapter invokes the original hooks on Arelle's actual validation object. It contains no rule or valuation formulas.

The original sample CIK `0001539778`, accession `0001477932-16-007985`, uses US GAAP 2014. All six modules returned. Its negative `us-gaap:PropertyPlantAndEquipmentAdditions` fact produced `DQC.US.0015.2098`, retaining the actual value, period, unit and XML reference. Earlier incomplete original-source receipts remain a limitation.

The diagnostic selects the first declared no-error variation and first declared error variation in each of the seven official families, in fixed family/pass-fail order. All 14 code/count comparisons match the official expectations and all six modules returned for each selected case. Two actual executions with identical inputs and `PYTHONHASHSEED=0` produced identical semantic outputs, zero network attempts and no missing-resource/runtime errors. The second semantic artifact write returned `wrote=false` and preserved its modification time.

The initial attempt is retained: all code/count comparisons matched, but six missing SEC taxonomy resources caused exit 1. Those resources' original HTTPS bytes and response receipts were captured in a separate probe cache. The original cache remains `9d3b620dea156fbe37d7cb08da453aa2cec168b926851e2d50a7dcb7c25bed29`; the expanded cache is `1b91d766abeae3bb8337f40dfbc9ea05fc0fe9570247cd681bc78f0aa59c001b`. Both subsequent executions exited 0.

## Evidence identities

Artifacts are below `issue-361-historical-dqc-candidate-v1/`. Filenames hash decompressed canonical JSON; publication uses the existing temporary-file/atomic-rename writer. The official-assets and verification documents exceed the repository's 500 KB file limit. Their exact canonical bytes are stored in fixed 256 KiB chunks, indexed by storage manifest `afec5cad4afa8c9d27d749dc5bb7edea4ae0f0a1321f7d8eccbf77fdf3dd0b2d`. Reconstruction checks every chunk digest and reproduces both original document digests below. All 90 chunks fit the limit, repeat publication returns wrote=false, and the roundtrip is byte-identical. Full local originals are preserved under ignored `.audit/issue-361-historical-dqc-originals/`.

| Kind | Digest |
| --- | --- |
| Official source, selected fixtures and taxonomy receipts | `099d8030f5e2f95694e3cbc570a9cf67162e90f310248f39aa2e05ee62bce07b` |
| Input and captured executor/adapter scripts | `fc0112433800de77a8721ebe29a40674676344fb5ad9781be13d596bf7f1661d` |
| Semantic output | `28d463ce25a7e563af72091bb87c3bc3173519d9798b93e2573fcf7d4376bbaa` |
| Verification, raw observations and initial failure | `6b0c940e5570e4635e02876d838da6d11a139613516c157e30401780061e7e71` |
| Canonical integrity audit and recording script | `8366863e44d8347953e65617dc9a58752f63d7ccf7b895b7f251b75f2a46f5c6` |

The official full suite archive SHA-256 is `df30183a1315ba1323b873aea572a2c068b8c5e70d4939c5d824f1cdedd6994f`. Original licensed code, acquisition receipts, official variation definitions, selected fixture files and temporary script bytes are captured, so the diagnostic does not depend on its `/tmp` scripts surviving.

Commands executed from the issue worktree:

```sh
PYTHONHASHSEED=0 UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service \
  python /tmp/issue361-dqc-v1-conformance.py
UV_CACHE_DIR=/tmp/.uv-cache uv run --extra dev --project fundamental-service \
  pytest fundamental-service/tests/test_history_review_signing.py -q
python3 scripts/architecture_guard.py
UV_CACHE_DIR=/tmp/.uv-cache uvx --from ruff==0.14.10 ruff check fundamental-service
git diff --check
```

Diagnostic exit codes: `[0, 0]`. Signing tests: 11 passed. Architecture guard, Ruff and diff checks: exit 0. Both existing proposal seals verified against their original subjects. Signer initialization reused the key/public identity with `key_wrote=false` and `wrote=false`. No mapping-review attestation or policy approval was created.

## Remaining acceptance

This is not full official conformance: 2,335 of 2,349 variations remain unexecuted. Code/count comparison does not assert severity equivalence: official expectations declare errors, while EDGAR 26.3 logs these DQC findings as warnings. Both expectations and actual severities are retained. Production adoption must resolve this difference in the owning validation policy.

Official v1 lists US GAAP 2012–2015 and DEI through 2014. Other historical taxonomies require compatible reviewed resources. This candidate has not run in Docker and is not an activated canonical profile. A diagnostic result cannot substitute for a release certificate.

Next: finish conformance and year/severity coverage, then implement the historical profile coherently in parser, acquisition and validation contracts. Independent issuer/period review, historical market-policy approval, canonical original-filing releases, actual fixed-cohort composer replay twice, full type acceptance, review/CI, merge verification and issue-owned cleanup remain outstanding. No verified valuation or threshold promotion is asserted.

To inspect either chunked document without publishing a large tracked file:

```python
import base64, gzip, hashlib, json
from pathlib import Path

root = Path("docs/acceptance/issue-361-historical-dqc-candidate-v1")
manifest = json.loads(gzip.decompress((root / "storage/afec5cad4afa8c9d27d749dc5bb7edea4ae0f0a1321f7d8eccbf77fdf3dd0b2d.json.gz").read_bytes()))
for artifact in manifest["chunked_artifacts"]:
    pieces = []
    for entry in artifact["chunks"]:
        canonical = gzip.decompress((root / entry["path"]).read_bytes())
        assert hashlib.sha256(canonical).hexdigest() == entry["canonical_digest"]
        chunk = json.loads(canonical)
        data = base64.b64decode(chunk["content_base64"], validate=True)
        assert hashlib.sha256(data).hexdigest() == entry["content_sha256"]
        assert len(data) == entry["bytes"]
        pieces.append(data)
    canonical = b"".join(pieces)
    assert hashlib.sha256(canonical).hexdigest() == artifact["original_canonical_sha256"]
    document = json.loads(canonical)
    print(artifact["original_kind"], artifact["original_canonical_sha256"], document["schema_version"])
```
