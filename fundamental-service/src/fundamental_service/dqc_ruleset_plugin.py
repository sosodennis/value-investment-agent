"""Select the pinned full DQC ruleset after Arelle loads the filing DTS."""

from collections.abc import Mapping
from typing import Protocol

from fundamental_service.arelle_parser import ArelleParserError
from fundamental_service.dqc_rulesets import DqcRulesetBindingV1, DqcRulesetCatalogV1


class DqcOptions(Protocol):
    xule_rule_set: str


class LoadedDqcModel(Protocol):
    namespaceDocs: Mapping[str, object]


class DqcController(Protocol):
    fundamental_dqc_ruleset_binding: DqcRulesetBindingV1


def select_loaded_ruleset(
    controller: DqcController,
    options: DqcOptions,
    model: LoadedDqcModel,
    *args: object,
    **kwargs: object,
) -> None:
    raw = getattr(options, "fundamental_dqc_ruleset_catalog", None)
    if raw is None:
        return
    try:
        catalog = DqcRulesetCatalogV1.model_validate_json(raw)
        catalog.verify_files()
        binding = catalog.select(tuple(str(uri) for uri in model.namespaceDocs))
    except ValueError as error:
        raise ArelleParserError(
            "DQC_TAXONOMY_RULESET_UNAVAILABLE", str(error)
        ) from error
    options.xule_rule_set = str(binding.path)
    controller.fundamental_dqc_ruleset_binding = binding


__pluginInfo__ = {
    "name": "Fundamental pinned full DQC taxonomy rulesets",
    "version": "1.0.0",
    "CntlrCmdLine.Xbrl.Loaded": select_loaded_ruleset,
}
