# #376 Composite Working-Capital Policy Checkpoint

This checkpoint adds an explicitly versioned composite noncash working-capital input to Fundamental Service. It retains the exact six-component requirements profile, adds source-bound current-asset/current-liability totals with required explicit exclusions and issuer-period residual assumptions, and sends resulting history through the existing #352 composer and calculator. Unknown exclusions abstain; missing facts do not become zero, and unspecified residual balances are not automatically classified as operating.

The tested implementation is commit `b410a214a0951f7bbd4072f233a0f9d6bfbd2208` on `codex/issue-376-aggregate-noncash-working-capital`, based on the latest fetched integration branch. The issue-linked checkpoint commit is `8f1569ef` (`feat(fundamental): version composite noncash working-capital inputs`); it retains all existing integration commits. The policy digest is `69b652de5b1ea80ea5282d346ec2581f4ffd1489dc5143e11756cae4ab9d9ca1`.

At the implementation commit, verification passed:

| Check | Result |
| --- | --- |
| Focused working-capital and issuer-release tests | 36 passed |
| Fundamental Service full test suite | 1,407 passed, 68 skipped, one existing duplicate-ZIP fixture warning |
| PostgreSQL metadata suite, isolated project database | 22 passed |
| Ruff, changed-file format check, mypy 1.19.1 | Passed; 9 changed source modules type-checked |
| Architecture guard and `git diff --check` | Passed |
| Isolated service runtime | Compose config valid; PostgreSQL and Fundamental healthy; `/readyz` reports `identity_resolution_configured=true` |

The policy fixture's canonical input digest is `0ad77c2134b41a8d679bc13e83e266e2598bc9b56d14dc8f4c10e1986b34ce41`; its assessment input/output digests are `86306f46dee1ef4221a910515e59ef26beed16521d8090a308fb12318268833f` and `464ee7f238e36ac399baa5583bb9222a93a82041859fa0a61c4f64ac0f3ca7d2`. With the same fixed synthetic source, mapping, model and policy inputs, the #352 operating composer produced `fcff_dcf` output digest `53104b0c77b0b616c19be55d96de31a9c3b4a4a3ef6cf58477c4ed5b8b8ba06d` and `transition_fcff_dcf` output digest `718d5a94deab13a052d09c81381b8d7254a980b8f3a3942d984ec1bbee2f285a`. Reversed fact/input order produces identical canonical outputs. Both remain provisional and keep `supported_history_threshold=null`. These are synthetic contract tests, not empirical NEWMARKET forecasts.

The full valuation regression shares released working-capital source facts with the existing capital bridge without duplicating fact identities; it uses `prepare_automatic_valuation` and the existing `calculate` implementation. Separate tests exercise publication reuse, service reconstruction over the same artifact store, unchanged artifact inventory, source binding and signed-release rejection. Test keys, facts and source records are synthetic and do not establish an independent review or trusted issuer release.

The Docker runtime is isolated under project `via-issue376-wc-policy`, service port `18973`, PostgreSQL port `18974`, with only this project's named volumes and network. The shared `.env` was read but not changed. Its historical taxonomy-cache path now contains zero files, which caused the initial startup hash failure; this project uses the separately captured directory `/private/tmp/issue361-taxonomy-cache-dqc362-candidate` with verified directory hash `c596f7b0aa5d718bc8e9622dfa7d82d11ae8b6e33c8481bd562595f890677860`. The exact tuple and runtime source digest are in [issue-376-runtime.json](issue-376-runtime.json). Docker acceptance proves service startup and readiness, not real SEC acquisition or issuer mapping.

**Research remains open.** No NEWMARKET classification has been independently reviewed or trusted-published. NEWMARKET 2013 continuing-capex scope is unresolved. No real two-model forecast, first subsequent original annual filing label, error analysis or complete deterministic replay has been claimed. The threshold remains null; estimated outputs remain provisional and missing evidence still abstains. The next empirical step remains original-source adjudication for NEWMARKET, especially the 2013 capex question, followed by independent review and the existing trusted release path.
