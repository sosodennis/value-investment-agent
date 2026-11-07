# Issue #333 Xule Hook Reconciliation

Issue: [#333](https://github.com/sosodennis/value-investment-agent/issues/333)
Branch: `codex/issue-333-xule-hooks`
Base under test: `809d42d96b625440c38e9e6b51c63a878884eda8`

## Result

The historical `DQC_VALIDATION_UNAVAILABLE` report is not reproducible on the
current mainline checkout. The pinned Arelle/DQC/Xule loader resolves DQC's
declared Xule dependency, registers both Xule hooks, and completes the SEC
EFM/DQC parser replay. No source workaround or `Cntlr.addToLog` compatibility
shim was added. The exact earlier checkout and runtime that produced the report
remain unidentified.

## Pinned Runtime

| Resource | Value |
| --- | --- |
| Arelle | `2.47.4` |
| EDGAR plugin | `/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea`; directory hash `054a21fa824797787acc2c6e98af4bb040c51bbee41b613cee1793db8fd144af` |
| Xule plugin | `/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin`; directory hash `63123d67048019e3c49a0efde0e0aa8ec3eba0fc971da56ebd96dea8e40cd713` |
| DQC US rules | `v31.0.3`; `/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip`; SHA-256 `0eb33d095ac0ae08f01c508526b35523534659d661bc62873ac1400deec87930` |
| SEC taxonomy cache | `/private/tmp/issue312-sec-taxonomy-2023-2024`; directory hash `0accc5ab0d4ce6674083bd82cf878a8619b3ac441da8600e0a03aefb8432a3a3` |

The directory hashes use the parser's deterministic tree hash and exclude only
Python bytecode cache artifacts. Pinned versions and paths were unchanged.

## Parser Suite Checkpoint

The exact current-main command was:

```sh
ISSUE328_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
ISSUE328_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
ISSUE328_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
ISSUE328_TAXONOMY_CACHE_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 \
ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
ISSUE312_TAXONOMY_CACHE_DIR=/private/tmp/issue312-sec-taxonomy-2023-2024 \
uv run --extra dev --project fundamental-service pytest -q -vv \
  fundamental-service/tests/test_arelle_parser.py
```

Result: exit `0`, `16 passed in 62.35s`, with no skipped tests or failures.
The suite includes the AAPL and Microsoft SEC EFM/DQC replays, source-hash and
offline guards, DQC completion checks, strict profile selection, and the staged
JPEG replay. The AAPL replay preserves the blocking
`EFM.5.02.05.disallowedElement` finding, completes DQCRT, and records zero
network attempts; the staged-image replay removes the graphic-file error while
preserving other blocking findings and its deterministic digest.

## Direct Plugin Hook Probe

The probe loaded `validate/DQC` through the same temporary plugin root used by
the parser. The resulting plugin manager module registry contained:

- `DQC Rules Validator`, with imported `XBRL rule processor (xule)`;
- `XBRL rule processor (xule)`, with `Xule.RegisterValidator` and
  `Xule.callXuleProcessor` in its class methods.

After clearing `controller._pluginManager.pluginMethodsForClasses`, the hook
counts were still exactly one each:

```text
Xule.callXuleProcessor before_clear 1
Xule.RegisterValidator before_clear 1
Xule.callXuleProcessor after_clear 1
Xule.RegisterValidator after_clear 1
```

This confirms that the DQC `import: xule` dependency resolves and that hook
visibility survives cache invalidation. It does not justify an additional
manual Xule load or an `addToLog` fallback.

The probe was run with `uv run --extra dev --project fundamental-service
python`, constructing `ArelleValidationProfileV1` from the four pinned paths
above, calling `_validation_plugin_root(profile)`, loading
`CntlrCmdLine(...)._pluginManager.addPluginModule('validate/DQC')`, and then
checking `controller.plugins.hooks(...)` before and after the cache clear.

## Acceptance Status

- Current pinned replay: verified on the exact base SHA above.
- DQC completion, strict SEC EFM profile, zero-network replay, staged image
  resolution, and blocking EFM evidence: verified.
- Historical failure origin: open gap; the original failing commit/runtime has
  not been identified.
- Code changes: none; this checkpoint records evidence only.
