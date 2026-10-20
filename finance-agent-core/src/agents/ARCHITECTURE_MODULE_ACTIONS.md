# Architecture Module Actions

Generated from `scripts/architecture_guard.py --write-module-report`.
Each item identifies a source module, exact import target, and first remediation action.
Resolve items within their module, then remove the matching edge from its
`scripts/architecture_guard_exceptions/<source-module>.tsv` shard. CI rejects new
edges, stale edges, and exceptions without a matching action ID in this report.

Current documented findings: 0.
