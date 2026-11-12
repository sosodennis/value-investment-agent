# #416 Composite exclusion accounting coverage

Exact implementation `18d72bff1c35ccd4123e7c1a41db4b2fceaf1607` on `codex/issue-376-aggregate-noncash-working-capital`, delivered through draft PR #414 against #361. Ordinary merge `23201c26` includes parent `634e8896` and preserves earlier WIP commits. Independent review, CI and serial integration remain pending; #416 stays open until delivery to main.

The old evaluator accepted operating payables as coverage of current interest-bearing debt, returning 35 with no missing evidence. V2 binds five direct canonical exclusion roles to their exact accounting class and balance-sheet side. The combined cash/short-term-investments role covers exactly both asset classes and is subtracted once. Unsupported roles, other combinations and class/side substitutions abstain. The relation participates in the policy digest; V1 evidence cannot authorize V2. No valuation formula changed.

| Exact-commit check | Result |
| --- | --- |
| Fundamental Service / own PostgreSQL DB | 1,727 passed; 11 optional external SEC-resource skips; one existing duplicate-ZIP fixture warning |
| Focused coverage / working-capital / release checks | 44 passed before the exact-commit full suite |
| Ruff / format / mypy | Passed; 9 affected source modules checked |
| Root and Service architecture guards / diff | Passed |
| Docker installed source | 85 Python files match exact commit; SEC identity readiness configured |
| Accounting refusals | 5 assessment substitutions and 2 trusted synthetic release substitutions rejected |
| Desktop / Docker / restart repeat | Same output; release/report reused, wrote=false; release bytes/sizes/mtimes unchanged |
| Real complete study / threshold | 0/100; null |

Synthetic replay input `ac03f22dc4bc03d687296fad61e0096345ef5ee2e3bc3bbec55bff9e29ded31e`; output `9843353980ef28f455d4e5afe58744648f66d11aa27acc8b491f0c25f1a66394`. Desktop Python 3.11.15 and container Python 3.12.16 both use Arelle 2.47.4/Pydantic 2.14.2. Cross-runtime equality supplements the same-runtime repeats. Image `sha256:9b711834daf452d0150113574c820a819e4b919ff7176356a5ba0969b47c8026`.

Isolated project `value-investment-agent-416-accounting-coverage`, ports 18981/18982, own network and two volumes. Exact tuple: [issue-416-runtime.json](issue-416-runtime.json). Preflight input `4342c3b6d65b0644cf70e4d07d247e17a5a87503b112f02db569cb155f5d87da`, output `84cbb55f8741b0d0cccddd113ea7f73ae8a0fbf1cce7094a54ba1902e45cf320`; second report wrote=false. Own stack/image tag/network/volumes were removed after retaining evidence. Of 69 baseline containers, 68 retain exact IDs/image IDs/start times; the main chat's capture-profiles service was concurrently replaced. Cleanup selected only the #416 project.

Generated evidence stays outside Git at `/Users/denniswong/Desktop/Project/value-investment-agent-issue-416-coverage-evidence`. External checkpoint `de870f1ffbdaf2043f9ee2b85bf6ddc7d5c8dd620e7da0a88362b07039220971` records exact commands, exit codes and digests. External harness JSON decoding and manifest-profile errors were corrected; product validation was not relaxed. Policy: [composite-working-capital-v2.md](../../fundamental-service/docs/composite-working-capital-v2.md).

Next: independent review/current-head CI and serial integration, then dependency-scoped requirements, real transition evidence and first-original label/comparison. NEWMARKET exclusion values and classifications remain unresolved. Synthetic signatures prove a boundary and do not approve real accounting evidence. #415/#377 and original research acceptance remain open; no quality or threshold promotion.
