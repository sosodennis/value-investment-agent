"""Pinned full DQC rulesets selected by the loaded US GAAP namespace."""

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DQC_V18_PROFILE_ID = "sec-efm-us-dqc-v18-xule30055-build-v1"
DQC_V18_CONSTANTS_MARKER = "dqc-v18-official-source-constants-without-overrides-v1"
DQC_V18_SOURCE_COMMIT = "cbb5f1f02d2f3f21b438a72a555127c4090d135b"
DQC_V18_ORIGINAL_RULESETS = {
    "http://fasb.org/us-gaap/2020-01-31": (
        "dqc-us-2020-V18-ruleset.zip",
        "4960f19bf34ed8ffc22b9dced8d63c4d10ce1a5e0c2a8c5d3df90a3bd838692d",
    ),
    "http://fasb.org/us-gaap/2021-01-31": (
        "dqc-us-2021-V18-ruleset.zip",
        "2bffda85463977664244ba3bf48e018d75f3ec8ae61a22f51ed2b173d6ac637b",
    ),
    "http://fasb.org/us-gaap/2022": (
        "dqc-us-2022-V18-ruleset.zip",
        "39b9fab9b3181e836e4a5ce1b3a0e35ff3def918cff2304f8197b2d0fa7d76a1",
    ),
}
DQC_V18_RULESETS = {
    "http://fasb.org/us-gaap/2020-01-31": (
        "dqc-us-2020-v18-xule30055-build-v1.zip",
        "5af206a9c8a6b29c1b5e91c3a386c68a90b38ad7df1e045f458eccb7d3f87a35",
    ),
    "http://fasb.org/us-gaap/2021-01-31": (
        "dqc-us-2021-v18-xule30055-build-v1.zip",
        "9a885021ed5f17daa5a5f1c924cacd77d697b16bfa0c7d9e0df7e9fb0fc96d33",
    ),
    "http://fasb.org/us-gaap/2022": (
        "dqc-us-2022-v18-xule30055-build-v1.zip",
        "2a3ea67e6b1dd523eeadf1622740975b071eaa7d5f9180d144069da241b00598",
    ),
}


class DqcRulesetBindingV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    taxonomy_namespace: str = Field(
        pattern=r"^http://fasb\.org/us-gaap/20[0-9]{2}(?:-01-31)?$"
    )
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DqcRulesetCatalogV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["dqc-us-full-ruleset-catalog-v1"] = (
        "dqc-us-full-ruleset-catalog-v1"
    )
    dqc_version: Literal["v31.0.3", "v18"] = "v31.0.3"
    bindings: tuple[DqcRulesetBindingV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_bindings(self) -> "DqcRulesetCatalogV1":
        namespaces = tuple(item.taxonomy_namespace for item in self.bindings)
        if namespaces != tuple(sorted(set(namespaces))):
            raise ValueError("DQC taxonomy bindings must be unique and canonical")
        if len({item.path.name for item in self.bindings}) != len(self.bindings):
            raise ValueError("DQC ruleset filenames must be unique")
        if self.dqc_version == "v18" and any(
            DQC_V18_RULESETS.get(item.taxonomy_namespace)
            != (item.path.name, item.sha256)
            for item in self.bindings
        ):
            raise ValueError("V18 bindings must match the pinned official-source build")
        if self.dqc_version == "v31.0.3" and any(
            item.taxonomy_namespace in DQC_V18_RULESETS
            or item.sha256 in {digest for _, digest in DQC_V18_RULESETS.values()}
            for item in self.bindings
        ):
            raise ValueError("V18 rulesets cannot be declared as DQC v31.0.3")
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
