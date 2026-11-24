"""Keep the unchanged V18 resource package alive for one parser worker."""

import hashlib
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from zipfile import ZipFile

V18_PACKAGE_SHA256 = "3578edf5872ed053a4ed9c6c9cc9822b67c9559ee5fb1b1400926fa034dbd855"
V18_PACKAGE_MARKER = "dqc-v18-official-resource-package-lifecycle-v1"


class PackageRegistry(Protocol):
    def add(self, path: str) -> object | None: ...

    def rebuild(self) -> None: ...


@contextmanager
def activate_v18_package(registry: PackageRegistry, ruleset: Path) -> Iterator[str]:
    with ZipFile(ruleset) as archive:
        packages = tuple(
            name for name in archive.namelist() if name.startswith("packages/")
        )
        if packages != ("packages/resources.zip",):
            raise ValueError("V18 ruleset resource package inventory differs")
        payload = archive.read(packages[0])
    if hashlib.sha256(payload).hexdigest() != V18_PACKAGE_SHA256:
        raise ValueError("V18 official resource package hash does not match")
    with tempfile.TemporaryDirectory(prefix="fundamental-dqc-package-") as temporary:
        package = Path(temporary) / "resources.zip"
        package.write_bytes(payload)
        if registry.add(str(package)) is None:
            raise ValueError("V18 official resource package could not be activated")
        registry.rebuild()
        yield f"{V18_PACKAGE_MARKER}:{V18_PACKAGE_SHA256}"
