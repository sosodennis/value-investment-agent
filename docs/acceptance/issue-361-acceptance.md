# #361 persistent source preparation and valuation flow

The accepted outcome is the complete normal Fundamental Service flow: issuer and
valuation timestamp, eligible SEC evidence, persistent canonical facts/snapshot,
automatic preparation, the existing #352 composer/calculator, and retrieval of
the persisted valuation artifact. Repeated requests reuse eligible evidence.

The repository owner revised [#361](https://github.com/sosodennis/value-investment-agent/issues/361)
on 2026-11-11. The fixed-100-issuer history-threshold investigation is separate
research. Its historical failures remain evidence, but its corpus is not a
runtime dependency or this issue's delivery criterion. Neither model has an
approved numerical history threshold; `supported_history_threshold` stays null.
The existing provisional/abstain, source availability and release-trust rules
still apply. #351–#355 acceptance is unchanged and #350 is not started.

## Flow and acceptance

1. Resolve source identity using CIK, original accession, valuation timestamp and
   source-selection profile. Read existing receipts/snapshots first; fetch missing
   eligible evidence without exposing future facts or overwriting older bytes.
2. Persist immutable source bytes in the service-owned content volume and
   manifests/facts in PostgreSQL. Capture failures retain raw evidence and reasons
   without publishing an approved snapshot.
3. Prepare with the formal #352 composer and trusted mapping/model/policy
   releases. Existing caller approval/override contracts remain. A project signer
   does not replace semantic review or supply missing facts.
4. Validate/calculate with the existing deterministic calculator and retain the
   result plus source, mapping, model and policy digests. Calculation stays
   stateless; do not introduce server-owned valuation sessions or jobs.
5. Demonstrate one supported real-filing-backed numerical result, artifact
   retrieval, repeated acquisition/valuation without duplicate evidence or
   artifacts, concurrent deduplication, restart against the same store, and
   digest-checked recovery to an empty isolated store. Document unsupported
   historical profiles and missing/conflicting inputs as explicit refusals.
6. Run exact-commit tests, architecture/lint/type/contract checks, isolated #361
   Docker acceptance, complete-flow repeat and review/CI before merge. Verify the
   merge commit before closing the issue or cleaning issue-owned resources.

The required manifest profile is `persistent-valuation-flow-v1`.
[Runtime metadata](issue-361-runtime.json) is WIP; every new flow check is
`not_run`, and the prior runtime tuple must be revalidated. Passing research
checks cannot verify this scope. #369/#371 still limit requests that require
unsupported historical evidence; #372 remains a separate legacy release gap.

## Research preservation and removal

Baseline `59830e161c9300e44b2b7b54eea3e43567835bff` has tree
`c155f53fcc8f099c2bef6469bbc9ace9f9e60ee0`, identical to pre-squash
`a74238ec4433aaadf85e285f6fa399bdb366292e`. Its original checkpoint chain remains
at local branch `codex/issue-361-replay-evidence-presquash-a74238ec` and in the
verified `source-history.bundle` alongside the research archive.

[Archive reference](issue-361-research-archive.json) records the exact baseline,
input digest, archive/manifest hashes and local preservation directory. The
archive contains all 10,358 baseline #361 acceptance/research files. All members
were compared with the committed bytes, then restored to a clean temporary
directory and checked against the per-file SHA-256 manifest before removal.
The branch removes 10,357 files and replaces the old runtime acceptance with the
new WIP scope. No source bytes, prior failures or checkpoint history are lost.

The archive is a local research backup, not a published service snapshot or a
shared production recovery source. This preservation does not satisfy the
complete flow's persistence/restore acceptance. Production storage and its
export/import or pinned source preparation must be verified separately.

To inspect or restore research, obtain the referenced archive and `manifest.json`
from the recorded preservation directory, verify both hashes against the checked
reference, and extract to a separate directory. Do not restore research over the
current worktree or import failed/unapproved observations as canonical facts.

Research-only replay, proposal, signing and fixed-inventory validation commands
and their tests are also removed from this product PR. Their exact paths and
hashes are recorded in the archive reference and are recoverable from the Git
bundle at the baseline commit. The production acquisition, retained-capture,
parser, mapping, preparation and calculator tests remain in scope. A clean CI
checkout must not require the local research archive to run those tests.

```sh
git bundle verify /path/to/research-archive/source-history.bundle
shasum -a 256 /path/to/research-archive/research-evidence.tar.gz
shasum -a 256 /path/to/research-archive/manifest.json
mkdir /tmp/issue361-research-inspection
tar -xzf /path/to/research-archive/research-evidence.tar.gz \
  -C /tmp/issue361-research-inspection
```

The archived original manifest lists every path, byte length and content hash.
The prior preflight at digest
`e298ab873bb96a44a8d8e916a8aeb1f7d110dd335b2f2fac79e2a84bf5085de0`
remains in that archive and at the baseline Git commit. Its zero canonical
forecasts are not changed or claimed as success.
