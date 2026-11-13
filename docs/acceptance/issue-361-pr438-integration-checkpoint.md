# PR #438 independent engineering review and integration

Reviewed head `e2cfc6593519bac870b84524fd04452c5aca1f65`, implementation
`596f75f3af26f13377ed8b4f8fa092382ff3979c`. No actionable engineering findings
remain in the eight-file diff, conditional authority, observation-scoped SEC
mapping, model binding, formal #352 composer call, source/label lineage,
failure retention or content-addressed publication. Independently ran all 22
new boundary tests; verified five canonical reports and their input/output
digests, raw/parser XML text equality, and nine desktop/Linux financial artifact
hashes. The reviewed head changes acceptance Markdown only after implementation.
PR CI 43445192042 has 12 executed jobs passing; release gate skipped.

GitHub ordinarily merged #438 into `codex/issue-361-replay-evidence` at
`159124836157fe1b4c730449e1662125e60f8172`, parents `3eaacf3944acdeb7d798c9df2b46db07ebe81f4e`
and `e2cfc6593519bac870b84524fd04452c5aca1f65`. Existing WIP commits remain.
No reset, rebase, squash or force-push occurred. PR #370 remains draft.

At this exact integration commit:

- Full Service/PostgreSQL: **2,635 passed, 17 explicitly skipped**, one expected
  duplicate-ZIP fixture warning. Skips require separately configured fixed SEC
  EFM/DQC/historical parser resources.
- Full Service Ruff 0.14.10, changed-file format, five-file source-aware mypy
  1.19.1, both architecture guards and `git diff --check origin/main` pass.
- Merge CI [43449955716](https://github.com/sosodennis/value-investment-agent/actions/runs/43449955716)
  passes all 12 executed jobs; release gate skipped.
- The real fixed-origin NEWMARKET compiler, three/four/five-year replay,
  forecast/label/error export and analysis run twice on desktop and twice in
  fresh Linux workers with network disabled. All nine financial artifacts match
  the reviewed implementation; every second publication returns `wrote=false`,
  without added files or changes in bytes, sizes or mtimes.

Own Compose project `value-investment-agent-361-pr438` used localhost ports
19971/19972 and subnet `10.231.82.0/28`. All 123 installed Python/SQL files and
the frozen lock equal the integration commit. Both services were healthy;
`/readyz` correctly reports SEC identity resolution unconfigured. This is
offline conditional research/runtime validation, not SEC acquisition or complete
valuation readiness. Image:
`sha256:6eef0cf38360bd3e3e8af47f807f0afb4227389a56df5498a16910f89aae74f9`.
Workers were bounded to one CPU/2 GiB and exited without OOM.

Initial harness failures remain retained: Docker interpreted a raw image ID in
`FROM` as a registry reference; a report destination inside the checkout was
refused; the first suite lacked its disposable test database. A project-owned
base tag, an external report root and explicit test database creation resolve
these harness prerequisites. The complete subsequent runs pass; production
guards were not relaxed. The two project volumes contained disposable suite
databases and an independently checked empty service content store. Only this
project's containers/network/volumes were removed. All **65** baseline containers
retain ID/image/start/status. Generated evidence survives outside Docker/Git.

Canonical checkpoint `6c015ec63faee7f80c55b7699560039dec97a0a57c4379cc8b383d5131f5593a`;
input/output digests
`f284e832f1d7f3c49d45d446c3da75c13f4b1913c6e3a3d12a7eb7f9784dcf3d` /
`e86c1b754d5750d7223c735cf08434a55c2f30aee037b46316f374605761ef09`.
Commands, failures, runtime tuple and digests are retained in ignored
`.audit/issue-361-pr438/`. Desktop repeat proof
`ed55841bb3e5129baa4d2cca63625445588aa966b85eebbbb75d87cb8816a6b1`
has input/output
`3048ffd48356778e705d94ef660b266c42adfc00df4a635d68c7648f90ae7fd2` /
`a0f0c5f7e84ea0c50cd66171e0aa38b065834cd51fce71ef2904df444637779d`.
Linux repeat proof
`aaf1a59c74f723e6a6f41496b61275899448b918c2b1dbc1b9dd19faf453292d`
has input/output
`83efd594ff6c5174e66a0ad57482cbb1592b3a38c52d44764c0da956a977482c` /
`3af8d0b34e34fe11781941bfa6b855f1e390629a8951c1984b40d7869f92f838`.

This passes engineering review for the conditional NEWMARKET increment. Both
registered models still share arithmetic; they are not independent predictive
methods. This is not accounting approval, trusted release, threshold approval,
parent acceptance or delivery to main. #376/#377/#383 remain OPEN;
`supported_history_threshold=null`, conditional outputs provisional, exact study
underpowered. Next: resume #361 NVE award/claims and dated market/quote evidence,
trusted release/exact-input approval and actual numerical recovery acceptance,
then independent parent review, main delivery and merge-commit verification.
