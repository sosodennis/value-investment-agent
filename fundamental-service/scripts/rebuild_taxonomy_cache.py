"""Rebuild a pinned offline Arelle cache without accepting changed upstream bytes."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fundamental_service.arelle_parser import _directory_hash

MAX_RESOURCE_BYTES = 32 * 1024 * 1024


class TaxonomyResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    uri: str
    retrieval_uri: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0, le=MAX_RESOURCE_BYTES)

    @model_validator(mode="after")
    def exact_cache_location(self) -> TaxonomyResource:
        uri = urlsplit(self.uri)
        retrieval = urlsplit(self.download_uri)
        path = PurePosixPath(self.cache_path)
        if (
            uri.scheme not in {"http", "https"}
            or not uri.hostname
            or uri.username
            or uri.password
            or uri.port
            or uri.query
            or uri.fragment
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in self.cache_path
            or retrieval.scheme != "https"
            or retrieval.hostname != uri.hostname
            or retrieval.username
            or retrieval.password
            or retrieval.port
            or retrieval.query
            or retrieval.fragment
        ):
            raise ValueError("taxonomy URI must match its relative cache path")
        return self

    @property
    def cache_path(self) -> str:
        uri = urlsplit(self.uri)
        return f"{uri.scheme}/{uri.netloc}{uri.path}"

    @property
    def download_uri(self) -> str:
        return self.retrieval_uri or self.uri.replace("http://", "https://", 1)


class TaxonomyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["arelle-taxonomy-cache-manifest-v1"]
    cache_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resources: tuple[TaxonomyResource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_inventory(self) -> TaxonomyManifest:
        paths = tuple(item.cache_path for item in self.resources)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("taxonomy cache paths must be unique and sorted")
        return self


class TaxonomyManifestPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def relative_posix_path(self) -> TaxonomyManifestPin:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path:
            raise ValueError(
                "taxonomy base manifest paths must be relative POSIX paths"
            )
        return self


class TaxonomyDeltaManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["arelle-taxonomy-cache-delta-v1"]
    base_manifests: tuple[TaxonomyManifestPin, ...] = Field(min_length=1)
    base_cache_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cache_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resources: tuple[TaxonomyResource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_delta_inventory(self) -> TaxonomyDeltaManifest:
        if self.cache_sha256 == self.base_cache_sha256:
            raise ValueError("taxonomy delta must change the cache hash")
        paths = tuple(item.cache_path for item in self.resources)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("taxonomy delta paths must be unique and sorted")
        return self


def load_manifest(paths: Sequence[Path]) -> TaxonomyManifest:
    manifests = tuple(
        TaxonomyManifest.model_validate_json(path.read_bytes()) for path in paths
    )
    if not manifests or len({manifest.cache_sha256 for manifest in manifests}) != 1:
        raise ValueError("taxonomy manifest fragments must pin one complete cache")
    return TaxonomyManifest(
        protocol="arelle-taxonomy-cache-manifest-v1",
        cache_sha256=manifests[0].cache_sha256,
        resources=tuple(
            sorted(
                (item for manifest in manifests for item in manifest.resources),
                key=lambda item: item.cache_path,
            )
        ),
    )


def load_delta_manifest(
    base_paths: Sequence[Path], delta_path: Path
) -> TaxonomyManifest:
    delta = TaxonomyDeltaManifest.model_validate_json(delta_path.read_bytes())
    expected_paths = tuple(item.path for item in delta.base_manifests)
    actual_paths = tuple(str(path) for path in base_paths)
    if actual_paths != expected_paths:
        raise ValueError("taxonomy delta base manifest paths differ from its pin")
    for path, pin in zip(base_paths, delta.base_manifests, strict=True):
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != pin.sha256
        ):
            raise ValueError(f"taxonomy base manifest differs from its pin: {path}")
    base = load_manifest(base_paths)
    if base.cache_sha256 != delta.base_cache_sha256:
        raise ValueError("taxonomy delta base cache differs from its pin")
    resources = tuple(
        sorted((*base.resources, *delta.resources), key=lambda item: item.cache_path)
    )
    return TaxonomyManifest(
        protocol="arelle-taxonomy-cache-manifest-v1",
        cache_sha256=delta.cache_sha256,
        resources=resources,
    )


def _retain(path: Path, payload: bytes, staging_directory: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("retained taxonomy resource differs from its pin")
        return
    descriptor, temporary = tempfile.mkstemp(
        prefix=".taxonomy-resource-", dir=staging_directory
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ValueError("retained taxonomy resource differs from its pin")
    finally:
        os.unlink(temporary)


def rebuild(
    manifest: TaxonomyManifest,
    destination: Path,
    *,
    retained_cache: Path | None = None,
    user_agent: str | None = None,
    allow_network: bool = False,
) -> str:
    destination_root = destination.resolve()
    if retained_cache is not None:
        retained_root = retained_cache.resolve()
        if destination_root.is_relative_to(
            retained_root
        ) or retained_root.is_relative_to(destination_root):
            raise ValueError(
                "taxonomy destination must differ from retained cache without overlapping"
            )
    for item in manifest.resources:
        target_path = (destination / item.cache_path).resolve()
        if not target_path.is_relative_to(destination_root):
            raise ValueError("taxonomy resource path must remain within destination")
    destination.mkdir(parents=True, exist_ok=True)
    for item in manifest.resources:
        target = destination / item.cache_path
        source = (
            retained_cache / item.cache_path if retained_cache is not None else None
        )
        if target.is_file():
            payload = target.read_bytes()
        elif source is not None and source.is_file():
            payload = source.read_bytes()
        elif allow_network:
            uri = urlsplit(item.uri)
            if uri.hostname in {"sec.gov", "www.sec.gov", "xbrl.sec.gov"}:
                if not user_agent or "@" not in user_agent:
                    raise ValueError(
                        "SEC taxonomy downloads require a contact User-Agent"
                    )
                time.sleep(0.25)
            request = Request(
                item.download_uri,
                headers={
                    "User-Agent": user_agent
                    or "value-investment-agent/taxonomy-resources"
                },
            )
            with urlopen(request, timeout=60) as response:
                payload = response.read(MAX_RESOURCE_BYTES + 1)
        else:
            raise ValueError(f"pinned taxonomy resource is unavailable: {item.uri}")
        if (
            len(payload) != item.byte_size
            or hashlib.sha256(payload).hexdigest() != item.sha256
        ):
            raise ValueError(f"taxonomy resource differs from its pin: {item.uri}")
        _retain(target, payload, destination.parent)
    digest = _directory_hash(destination)
    if digest != manifest.cache_sha256:
        raise ValueError("taxonomy cache composite hash differs from its manifest")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, action="append")
    source.add_argument("--delta-manifest", type=Path)
    parser.add_argument("--base-manifest", type=Path, action="append")
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--retained-cache", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    if args.delta_manifest is not None:
        if not args.base_manifest:
            parser.error("--delta-manifest requires at least one --base-manifest")
        manifest = load_delta_manifest(args.base_manifest, args.delta_manifest)
    else:
        if args.base_manifest:
            parser.error("--base-manifest requires --delta-manifest")
        assert args.manifest
        manifest = load_manifest(args.manifest)
    digest = rebuild(
        manifest,
        args.destination,
        retained_cache=args.retained_cache,
        user_agent=os.environ.get("FUNDAMENTAL_SEC_USER_AGENT"),
        allow_network=args.allow_network,
    )
    print(digest)


if __name__ == "__main__":
    main()
