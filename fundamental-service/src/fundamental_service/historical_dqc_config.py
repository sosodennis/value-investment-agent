"""Build the pinned 2013 DQC1 config from the original standard taxonomy, offline."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import socket
import subprocess
import tempfile
import zipfile
from importlib.metadata import version
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from .arelle_parser import _directory_hash
from .historical_dqc import V3_2013_PROFILE, _load_package
from .replay import ArtifactStore
from .serialization import canonical_bytes, is_digest, sha256_digest
from .snapshots import SnapshotError

TAXONOMY_URL = "https://xbrl.fasb.org/us-gaap/2013/us-gaap-2013-01-31.zip"
TAXONOMY_SHA256 = "18ac2f2dd8c66578edeafc114e61dd3013297ecd5a2f35737e4f34e80f6a54bf"
ENTRYPOINT = "us-gaap-2013-01-31/entire/us-gaap-entryPoint-std-2013-01-31.xsd"
RULE_SHA256 = "9a428c1a045cfe3ca9d9652031310967003a9d7c69bd06aaa50e5f2ebc19bce9"


def generate_axis_config(
    *, taxonomy_archive: Path, official_root: Path, taxonomy_cache: Path
) -> dict[str, dict[str, JsonValue]]:
    """Use the official config-generation traversal, never filing-specific members."""
    if hashlib.sha256(taxonomy_archive.read_bytes()).hexdigest() != TAXONOMY_SHA256:
        raise ValueError("FASB 2013 taxonomy archive hash does not match")
    if _directory_hash(official_root) != V3_2013_PROFILE.source_sha256:
        raise ValueError("official historical DQC package hash does not match")
    if version("arelle-release") != "2.47.4":
        raise ValueError("Arelle 2.47.4 is required")
    from arelle import Cntlr, ModelManager, XbrlConst

    package = _load_package(official_root)
    module = importlib.import_module(f"{package.__name__}.dqc_us_0001")
    config = TypeAdapter(dict[str, dict[str, JsonValue]]).validate_json(
        (official_root / "resources/DQC_US_0001/dqc_0001.json").read_bytes()
    )
    with tempfile.TemporaryDirectory(prefix="fundamental-gaap2013-") as directory:
        stage = Path(directory).resolve()
        with zipfile.ZipFile(taxonomy_archive) as archive:
            for member in archive.infolist():
                target = (stage / member.filename).resolve()
                if not target.is_relative_to(stage):
                    raise ValueError(
                        "taxonomy archive member escapes its staging directory"
                    )
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
        controller = Cntlr.Cntlr(logFileName=None, disable_persistent_config=True)
        controller.webCache.workOffline = True
        controller.webCache.cacheDir = str(taxonomy_cache)
        manager = ModelManager.initialize(controller)
        controller.modelManager = manager
        try:
            model = manager.load(str(stage / ENTRYPOINT))
            if model is None or model.errors:
                raise ValueError(
                    "complete original standard taxonomy could not load offline"
                )
            for axis, info in config.items():
                concept = model.nameConcepts.get(axis, (None,))[0]
                # Match official _create_config, including its absent-axis object.
                info["defined_members"] = (
                    sorted(
                        module._tr_mem(
                            None,
                            None,
                            model,
                            concept,
                            XbrlConst.dimensionDomain,
                            None,
                            set(),
                        )
                    )
                    if concept is not None
                    else {}
                )
        finally:
            manager.close()
            controller.close()
    if sha256_digest(config) != V3_2013_PROFILE.axis_config_sha256:
        raise ValueError("generated config differs from the reviewed profile pin")
    return config


def publish_axis_config(
    *,
    taxonomy_archive: Path,
    official_root: Path,
    taxonomy_cache: Path,
    artifacts: ArtifactStore,
    implementation_commit: str,
) -> dict[str, object]:
    if (
        implementation_commit != implementation_commit.lower()
        or len(implementation_commit) != 40
        or not is_digest(implementation_commit + "0" * 24)
    ):
        raise ValueError("exact implementation commit must be a full lowercase SHA")
    inputs = {
        "protocol": "historical-dqc1-gaap2013-config-build-v1",
        "implementation_commit": implementation_commit,
        "taxonomy_url": TAXONOMY_URL,
        "taxonomy_digest": hashlib.sha256(taxonomy_archive.read_bytes()).hexdigest(),
        "official_source_commit": V3_2013_PROFILE.source_commit,
        "official_package_digest": _directory_hash(official_root),
        "official_rule_digest": RULE_SHA256,
        "taxonomy_cache_digest": _directory_hash(taxonomy_cache),
        "entrypoint": ENTRYPOINT,
        "python": platform.python_version(),
        "arelle": version("arelle-release"),
        "pydantic": version("pydantic"),
        "builder_source_digest": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }
    if (
        inputs["taxonomy_digest"] != TAXONOMY_SHA256
        or inputs["official_package_digest"] != V3_2013_PROFILE.source_sha256
    ):
        raise ValueError("config inputs do not match the fixed official sources")
    config_digest = V3_2013_PROFILE.axis_config_sha256
    config_id = f"historical-dqc1-config-{config_digest}"
    report = {
        "inputs": inputs,
        "input_digest": sha256_digest(inputs),
        "output_digest": config_digest,
        "profile_id": V3_2013_PROFILE.profile_id,
        "release_authority": False,
    }
    report_id = "historical-dqc1-config-build-" + sha256_digest(report)
    # Re-read the caller's source/cache pins before reuse, and verify stored bytes.
    try:
        stored_report = artifacts.read(report_id)
    except SnapshotError as error:
        if error.code != "ARTIFACT_NOT_FOUND":
            raise
    else:
        if stored_report != canonical_bytes(report):
            raise ValueError("stored config build receipt differs")
        if hashlib.sha256(artifacts.read(config_id)).hexdigest() != config_digest:
            raise ValueError("stored config differs from the fixed profile pin")
        return {
            **report,
            "config_artifact_id": config_id,
            "report_artifact_id": report_id,
            "wrote": False,
            "generated": False,
        }
    config = generate_axis_config(
        taxonomy_archive=taxonomy_archive,
        official_root=official_root,
        taxonomy_cache=taxonomy_cache,
    )
    if _directory_hash(taxonomy_cache) != inputs["taxonomy_cache_digest"]:
        raise ValueError("taxonomy cache changed during config generation")
    dependencies = (sha256_digest(inputs),)
    # A config can be reused across commits; its identity depends only on bytes.
    config_write = artifacts.put_with_receipt(config_id, config)
    report_write = artifacts.put_with_receipt(report_id, report, dependencies)
    return {
        **report,
        "config_artifact_id": config_id,
        "report_artifact_id": report_id,
        "wrote": config_write.wrote or report_write.wrote,
        "generated": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy-archive", type=Path, required=True)
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--taxonomy-cache", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--implementation-commit", required=True)
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[3]
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()
    if revision != args.implementation_commit:
        parser.error("implementation commit differs from the executing checkout")
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=checkout, text=True
    ).strip():
        parser.error("exact-commit config build requires a clean checkout")

    def deny_network(*args: object, **kwargs: object) -> None:
        raise OSError("historical taxonomy config builder forbids network")

    # This CLI owns its process; the library never changes global socket state.
    socket.socket.connect = deny_network  # type: ignore[method-assign]
    socket.socket.connect_ex = deny_network  # type: ignore[method-assign,assignment]
    try:
        result = publish_axis_config(
            taxonomy_archive=args.taxonomy_archive,
            official_root=args.official_root,
            taxonomy_cache=args.taxonomy_cache,
            artifacts=ArtifactStore(args.output_dir),
            implementation_commit=args.implementation_commit,
        )
    except (OSError, ValueError, SnapshotError) as error:
        print(
            json.dumps(
                {"error": "HISTORICAL_DQC_CONFIG_BUILD_FAILED", "message": str(error)},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
