"""Build unchanged official V18 rules with the pinned Xule 30055 compiler."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import pickle
import posixpath
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict

from fundamental_service.arelle_parser import _directory_hash
from fundamental_service.dqc_rulesets import (
    DQC_V18_ORIGINAL_RULESETS,
    DQC_V18_RULESETS,
    DQC_V18_SOURCE_COMMIT,
    DqcRulesetBindingV1,
    DqcRulesetCatalogV1,
)
from fundamental_service.serialization import canonical_bytes

ARCHIVE_SHA256 = "2a089f9260651fc7c316613e17139734c5e602418c823d017e271c650854200c"
ARCHIVE_URL = (
    "https://codeload.github.com/DataQualityCommittee/dqc_us_rules/zip/"
    + DQC_V18_SOURCE_COMMIT
)
COMPILER_SHA256 = "63123d67048019e3c49a0efde0e0aa8ec3eba0fc971da56ebd96dea8e40cd713"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
SOURCE_MTIME = 1668470400


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    file_hash: str


class RuleInventory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    files: tuple[SourceFile, ...]
    rules: dict[str, object]
    functions: dict[str, object]
    constants: dict[str, object]
    namespaces: dict[str, object]
    output_attributes: dict[str, object]
    xule_compiled_version: str | int


def _retain(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("retained V18 resource differs from its pinned bytes")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".resource-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ValueError("retained V18 resource differs from its pinned bytes")
    finally:
        os.unlink(temporary)


def _inventory(archive: ZipFile) -> RuleInventory:
    return RuleInventory.model_validate(pickle.loads(archive.read("catalog")))


def _stage_sources(
    archive: ZipFile, year: int, target: Path, expected: RuleInventory
) -> None:
    root = f"dqc_us_rules-{DQC_V18_SOURCE_COMMIT}/"
    prefix = root + f"dqc_us_rules/source/us/{year}/"
    hashes = {source.name: source.file_hash for source in expected.files}
    observed = {}
    for info in archive.infolist():
        if not info.filename.startswith(prefix) or not info.filename.endswith(".xule"):
            continue
        name = info.filename.removeprefix(prefix)
        payload = archive.read(info)
        if info.external_attr >> 16 & 0o170000 == 0o120000:
            source = posixpath.normpath(
                posixpath.join(posixpath.dirname(info.filename), payload.decode())
            )
            if not source.startswith(root):
                raise ValueError("official source link escapes its source archive")
            payload = archive.read(source)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != hashes.get(name):
            raise ValueError("V18 source differs from the official compiled inventory")
        path = (target / name).resolve()
        if not path.is_relative_to(target.resolve()):
            raise ValueError("official source path escapes staging directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        os.utime(path, (SOURCE_MTIME, SOURCE_MTIME))
        observed[name] = digest
    if observed != hashes:
        raise ValueError("V18 build must retain every original source file")


def _compile_year(
    archive: ZipFile, namespace: str, destination: Path, compiler: Path
) -> tuple[DqcRulesetBindingV1, dict[str, object]]:
    year = int(namespace.split("/")[-1][:4])
    original_name, original_digest = DQC_V18_ORIGINAL_RULESETS[namespace]
    original = archive.read(
        f"dqc_us_rules-{DQC_V18_SOURCE_COMMIT}/dqc_us_rules/{original_name}"
    )
    if hashlib.sha256(original).hexdigest() != original_digest:
        raise ValueError("official compiled V18 ruleset hash does not match")
    name, expected_digest = DQC_V18_RULESETS[namespace]
    with (
        ZipFile(io.BytesIO(original)) as old,
        tempfile.TemporaryDirectory() as temporary,
    ):
        previous = _inventory(old)
        stage = Path(temporary)
        sources = stage / "sources"
        sources.mkdir()
        _stage_sources(archive, year, sources, previous)
        output = stage / f"derived-{year}.zip"
        command = [
            sys.executable,
            "-m",
            "arelle.CntlrCmdLine",
            "--plugins",
            str(compiler / "xule"),
            "--xule-compile",
            str(sources),
            "--xule-rule-set",
            str(output),
            "--xule-compile-type",
            "pickle",
            "--xule-compile-workers",
            "1",
            "--disablePersistentConfig",
            "--workOffline",
        ]
        with (stage / "compile.log").open("wb") as log:
            subprocess.run(
                command,
                env={
                    **os.environ,
                    "PYTHONHASHSEED": "0",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=600,
            )
        with ZipFile(output) as new:
            current = _inventory(new)
            if str(current.xule_compiled_version) != "30053":
                raise ValueError(
                    "derived V18 ruleset has an unexpected compiler format"
                )
            for key in (
                "rules",
                "functions",
                "constants",
                "namespaces",
                "output_attributes",
            ):
                if set(getattr(previous, key)) != set(getattr(current, key)):
                    raise ValueError("derived V18 inventory differs from original")
            if {f.name: f.file_hash for f in previous.files} != {
                f.name: f.file_hash for f in current.files
            }:
                raise ValueError("derived V18 sources differ from original")
            normalized = io.BytesIO()
            with ZipFile(normalized, "w", ZIP_DEFLATED) as result:
                for member in sorted([*new.namelist(), "packages/resources.zip"]):
                    payload = (
                        old.read(member)
                        if member == "packages/resources.zip"
                        else new.read(member)
                    )
                    info = ZipInfo(member, (2022, 11, 15, 0, 0, 0))
                    info.compress_type = ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    result.writestr(info, payload)
            raw = normalized.getvalue()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected_digest:
                _retain(destination / f"candidate-{year}-{digest}.zip", raw)
                raise ValueError(
                    "derived V18 build differs from its reviewed artifact: " + digest
                )
            target = destination / name
            _retain(target, raw)
            evidence = {
                "namespace": namespace,
                "original_sha256": original_digest,
                "derived_sha256": digest,
                "source_files": len(current.files),
                "assertions": len(current.rules),
                "functions": len(current.functions),
                "constants": len(current.constants),
                "resource_package_sha256": hashlib.sha256(
                    old.read("packages/resources.zip")
                ).hexdigest(),
            }
    return DqcRulesetBindingV1(
        taxonomy_namespace=namespace, path=target.resolve(), sha256=digest
    ), evidence


def prepare(
    destination: Path, source_archive: Path | None, compiler: Path
) -> DqcRulesetCatalogV1:
    if (
        sys.version_info[:3] != (3, 12, 12)
        or version("arelle-release") != "2.47.4"
        or version("pyparsing") != "3.3.3"
        or _directory_hash(compiler) != COMPILER_SHA256
    ):
        raise ValueError("V18 build requires the pinned compiler and Python runtime")
    destination.mkdir(parents=True, exist_ok=True)
    retained = destination / "dqc-v18-source.zip"
    if source_archive is not None:
        raw = source_archive.read_bytes()
    elif retained.exists():
        raw = retained.read_bytes()
    else:
        request = Request(
            ARCHIVE_URL,
            headers={"User-Agent": "value-investment-agent/dqc-resource-preparation"},
        )
        with urlopen(request, timeout=60) as response:
            raw = response.read(MAX_ARCHIVE_BYTES + 1)
    if (
        len(raw) > MAX_ARCHIVE_BYTES
        or hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256
    ):
        raise ValueError("official V18 source archive hash does not match")
    _retain(retained, raw)
    bindings, builds = [], []
    with ZipFile(io.BytesIO(raw)) as archive:
        for namespace in DQC_V18_RULESETS:
            binding, evidence = _compile_year(archive, namespace, destination, compiler)
            bindings.append(binding)
            builds.append(evidence)
    catalog = DqcRulesetCatalogV1(dqc_version="v18", bindings=tuple(bindings))
    catalog.verify_files()
    _retain(
        destination / "catalog.json", canonical_bytes(catalog.model_dump(mode="json"))
    )
    _retain(
        destination / "source.json",
        canonical_bytes(
            {
                "protocol": "dqc-v18-xule30055-build-v1",
                "official_commit": DQC_V18_SOURCE_COMMIT,
                "source_url": ARCHIVE_URL,
                "source_sha256": ARCHIVE_SHA256,
                "compiler_sha256": COMPILER_SHA256,
                "compiler_version": "30055",
                "compiled_format_version": "30053",
                "python_version": "3.12.12",
                "arelle_version": "2.47.4",
                "pyparsing_version": "3.3.3",
                "python_hash_seed": 0,
                "source_mtime": SOURCE_MTIME,
                "builds": builds,
            }
        ),
    )
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path)
    parser.add_argument("--xule-plugin-directory", type=Path, required=True)
    args = parser.parse_args()
    catalog = prepare(args.destination, args.source_archive, args.xule_plugin_directory)
    print(catalog.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
