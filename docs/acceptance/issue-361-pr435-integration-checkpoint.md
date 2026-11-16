# #435 serial integration checkpoint

This checkpoint records the independent review and serial integration of PR
[#435](https://github.com/sosodennis/value-investment-agent/pull/435) into the
#361 integration branch. It does not approve a history threshold or complete
the real issuer valuation flow.

## Review and integration

- Reviewed head: `a7f77987abeb37f8e599fbe56e03065f98f4093d`.
- Implementation: `a016e0f9f65875981a8e006b848b10a8cc3db299`.
- Finding: no actionable engineering findings in the reviewed diff, formal
  #352 composer boundary, model-version binding, source/label lineage, failure
  retention, or idempotency.
- CI run: [43413444420](https://github.com/sosodennis/value-investment-agent/actions/runs/43413444420),
  12 executed jobs passed; the release gate was skipped.
- Integration: ordinary `--no-ff` merge, preserving the existing #361 commit
  chain, produced `20e783eb921bc80b86a3f5c6def850d498149b92`.
- GitHub merged PR #435 into `codex/issue-361-replay-evidence` at
  `2026-11-13T11:55:38Z`, using that same merge commit. PR #370 remains
  OPEN/draft; #435 was not merged directly to `main`.

## Exact integration checks

At `20e783eb921bc80b86a3f5c6def850d498149b92`, the PostgreSQL-backed
Fundamental Service suite reports **2,550 passed, 17 skipped**. The skips are
the optional pinned SEC/historical DQC resource checks. The initial no-database
run reported 2,486 passed / 81 skipped; its extra skips were caused by not
starting the isolated PostgreSQL dependency. Ruff, formatting across 245
Python files, changed-source mypy across nine files, both architecture guards,
and `git diff --check` pass. The expected duplicate-ZIP fixture warning is
retained in the command output.

The test stack was isolated to this worktree. No other issue or repository
resources were removed as part of its retirement. Following the Docker address
pool exhaustion, the scoped #361 cleanup was rechecked: no #361 containers,
networks, or image tags remain; 34 #361 named data volumes remain retained.
Creating a temporary Docker network succeeded with subnet `172.30.0.0/16`;
the probe was removed immediately. Other Docker inventory digests were
unchanged during the probe. The canonical cleanup report is retained locally at
`.audit/issue-361-docker-cleanup/dcd4f4c9e64598e6e0bb9b196388758f47efb345b4f4b72d13fa2a293d43b54a.json`,
with input digest
`97c13e0e5155bea72ec74157ad757398fc111282d7fd0c19994e9d997175f0dc`
and output digest
`7a918addb66af4d5130a18bdfa20c7bf9fc7da3293391c54c76f7578381fc51a`.

## Remaining parent acceptance

The integrated study remains conditional and underpowered. The supported
history threshold stays `null`. PR #370 remains draft until the real accounting,
award dilution, issuer/date market policy and lawful quote, trusted release,
authenticated exact-input caller approval, and numerical repeat/concurrency/
restart/restore acceptance pass. Independent parent review, current-head CI,
merge, and merge-commit verification remain required.

Structured checkpoint input/output digests are
`d95e96fab26653b7d472951cd7cf12e71d18eecea0394be05bf7f5c0b2eed299` /
`cec747ddfd7581096eaa578edab601889fe955b903cb8f53a61812367e91fe68`.
The canonical JSON artifact SHA-256 is
`62d34baa0d59509ef41b71ba59b1fb397989a1106923ab9afbe062d994e5b8b0`.
It records the exact commands, runtime pins, outcomes and cleanup state.
