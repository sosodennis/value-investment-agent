"""Pinned full DQC rulesets selected by the loaded US GAAP namespace."""

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DqcRulesetBindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    taxonomy_namespace: str = Field(pattern=r"^http://fasb\.org/us-gaap/20[0-9]{2}$")
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DqcRulesetCatalogV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["dqc-us-full-ruleset-catalog-v1"] = (
        "dqc-us-full-ruleset-catalog-v1"
    )
    dqc_version: Literal["v31.0.3"] = "v31.0.3"
    bindings: tuple[DqcRulesetBindingV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_bindings(self) -> "DqcRulesetCatalogV1":
        namespaces = tuple(item.taxonomy_namespace for item in self.bindings)
        if namespaces != tuple(sorted(set(namespaces))):
            raise ValueError("DQC taxonomy bindings must be unique and canonical")
        if len({item.path.name for item in self.bindings}) != len(self.bindings):
            raise ValueError("DQC ruleset filenames must be unique")
        return self

    def verify_files(self) -> None:
        for binding in self.bindings:
            if (
                not binding.path.is_file()
                or hashlib.sha256(binding.path.read_bytes()).hexdigest()
                != binding.sha256
            ):
                raise ValueError("pinned DQC taxonomy ruleset hash does not match")

    def select(self, namespaces: tuple[str, ...]) -> DqcRulesetBindingV1:
        gaap = {
            uri
            for uri in namespaces
            if re.fullmatch(
                r"http://fasb\.org/us-gaap/[0-9]{4}(?:-[0-9]{2}-[0-9]{2})?", uri
            )
        }
        selected = tuple(
            item for item in self.bindings if item.taxonomy_namespace in gaap
        )
        if len(gaap) != 1 or len(selected) != 1:
            raise ValueError("loaded US GAAP taxonomy has no unique pinned DQC ruleset")
        return selected[0]
