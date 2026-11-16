# Issue 361 local mapping WIP retirement

The 2026-11-16 maintenance checkpoint retired recoverable, superseded local
mapping work without changing canonical facts, mapping domain rows, published
releases, SEC originals or shared taxonomy assets. This is storage maintenance;
M1, M2 and M3 remain incomplete.

The inspected Git head was `59e953fd2f63f84b61639a1ae854e4aa5ac80fdf`.
The installed runtime remained `71c100874a6abfe47a636b4e810c30a1bfac6f92` in
Compose project `value-investment-agent-361-current-issuer`, ports 21471/21472.
No source preparation process was active. Only this project's service was
paused; PostgreSQL remained available. All 46 unrelated containers retained
their IDs, images, start times and states.

## Scope and integrity

Every existing artifact was hash checked, and complete JSON values were checked
against artifact and domain identities/digests. Protected roots included all
canonical facts and mappings, all published releases/activations/registries,
original/validation/market assets, unclassified artifacts, and current acceptance
and resume revisions. Their transitive dependencies remained protected. Only
unprotected old mapping inputs and their obsolete reverse users were eligible.
There were zero retained-to-retired reference edges.

Retired rows:

| Table | Rows |
| --- | ---: |
| artifact_references | 4,190 |
| content_objects | 4,190 |
| snapshot_manifests | 11 |
| snapshot_facts | 392 |
| sec_ingestion_acquisitions | 10 |
| source_acquisition_audits | 10 |

The artifacts included 1,517 individual mapping inputs. All 4,338 canonical facts
and 1,477 mapping domain rows remained unchanged, as did all seven published
release manifests/verifications and four active release pointers. Historical
failure logs and backups remain outside Git.

A pre-existing missing 21-byte synthetic test fixture was restored from the exact
bytes in `test_artifact_publication_is_concurrent_and_hash_verified`; no real
source data was reconstructed. After retirement, all 6,656 retained content paths
passed size, SHA-256 and readability checks, with no missing or extra files.
Service readiness and SEC identity-resolution capability passed after restart.

## Recovery and space

Existing backups supplied 3,749 verified objects (10,340,193,143 bytes). Only the
missing 441 objects (1,585,248,165 bytes) were supplemented, in a 56,541,166-byte
compressed archive. All 4,190 retiring objects (11,925,441,308 bytes) were restored
into an independent empty directory and hash checked. An independent database
rehearsed exact metadata retirement and restoration, with identical before and
restored digests. Both temporary restore targets were removed. This rehearsal
is not M3's real numerical pipeline recovery acceptance.

Retirement used exclusive metadata locks, an unchanged-inventory check, content
quarantine, a metadata transaction, retained-data validation, and final unlink.

| Measurement | Bytes |
| --- | ---: |
| Content logical net reduction, including fixture repair | 11,925,441,287 |
| Content allocated net reduction | 11,938,316,288 |
| Docker VM free-space increase at unlink | 11,939,373,056 |
| Docker.raw allocated reduction observed | 11,927,433,216 |
| Host available-space increase observed | 11,858,157,568 |
| Evidence directory allocation after maintenance | 172,720,128 |

Host/VM observations include concurrent system activity and are not a causal
attribution of every byte. The content volume reduction was measured directly.
No global prune, Docker daemon restart, manual VM trim or unrelated cleanup ran.

## Evidence identities

Detailed manifests, IDs, scripts, locator paths and receipts remain in the
ignored worktree directory `.audit/issue-361-mapping-retirement-5a393f7c/`.
The directory name identifies the planning start, not the maintenance head.

| Receipt | SHA-256 |
| --- | --- |
| candidate-plan.json | `03de22f8ecd17434da431fcb25092bf06c93e8a2d0165c4d7e679571d1540db9` |
| recovery-manifest.json | `8a0259342ef52d7928d765a3b6039b6abcf2bfc92c1e69580e0d278ec7be35a4` |
| restore-rehearsal-receipt.json | `02e6d2943b1a90eeadc8f8569d2c38d9381fe706c088d6195da64a7045df64cb` |
| cleanup-receipt.json | `b0a934b3918b0674a8643a58e63e5b01514bf1645699bb6ab48e680b905e21e2` |

`recovery-manifest.json` binds the exact metadata inventory, existing verified
backup locators and the supplemental archive hash. `rehearse_restore.py` and
`retirement_common.py` encode the exercised row restore order and content checks.
The same selected rows and bytes can be reinstated during a stopped-service
maintenance window, after first verifying the manifest and retained-state
preconditions. Do not replace current metadata wholesale or overwrite newer rows.

At the maintenance checkpoint, storage amplification remained unresolved.
The subsequent `2e385256` increment introduced the versioned
`fundamental.mapping-input-artifact.v2` envelope: individual and batch inputs
reference one shared immutable parser report, bind its digest and the complete
resolved semantic input, and validate both again on replay. Existing retained
v1 evidence remains readable; corrupt v2 evidence cannot fall back to v1.
Real MSFT publication reduced an approximately 8.58 MB individual input to an
approximately 41 KB envelope referencing one 8.54 MB report; repeated publication
returned `wrote=false`. This addresses repeated report storage separately from
the retirement above. It does not establish M2 or M3 numerical acceptance.
