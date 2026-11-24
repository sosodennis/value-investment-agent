"""Rebuild a pinned offline Arelle cache without accepting changed upstream bytes."""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
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
    retrieval_uri: str
    cache_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0, le=MAX_RESOURCE_BYTES)

    @model_validator(mode="after")
    def exact_cache_location(self) -> TaxonomyResource:
        uri = urlsplit(self.uri)
        retrieval = urlsplit(self.retrieval_uri)
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
            or self.cache_path != f"{uri.scheme}/{uri.netloc}{uri.path}"
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


def _retain(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("retained taxonomy resource differs from its pin")
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
                item.retrieval_uri,
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
        _retain(target, payload)
    digest = _directory_hash(destination)
    if digest != manifest.cache_sha256:
        raise ValueError("taxonomy cache composite hash differs from its manifest")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--retained-cache", type=Path)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    manifest = TaxonomyManifest.model_validate_json(args.manifest.read_bytes())
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
