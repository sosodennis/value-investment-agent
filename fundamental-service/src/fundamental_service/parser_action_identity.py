"""Exact staged-input and conservative runtime identities for parser actions."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from pathlib import Path
from typing import Literal

from .arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    _directory_hash,
    parser_worker_import_paths,
)
from .parser_action_contracts import ParserActionInputV1
from .serialization import sha256_digest
from .snapshots import SnapshotError


class IncompleteParserClosure(ValueError):
    """An unaccounted runtime input requires an ordinary parse."""


def _files(root: Path) -> tuple[tuple[str, str], ...]:
    """Hash exact file contents; never admit based on stat data or a supplied hash."""
    if not root.is_dir() or root.is_symlink():
        raise IncompleteParserClosure("parser input root is not a regular directory")
    # Explicit traversal propagates unreadable-directory errors. Path.rglob can
    # suppress them and silently omit runtime dependencies.
    pending = [root]
    result = []
    count = 0
    while pending:
        path = pending.pop()
        count += 1
        if count > 200_000:
            raise IncompleteParserClosure(
                "parser closure exceeds the supported file count"
            )
        # Symlinked dependencies require a separate closure model. Miss safely.
        if path.is_symlink():
            raise IncompleteParserClosure(
                "symlinked parser dependencies are unsupported"
            )
        if path.is_dir():
            pending.extend(sorted(path.iterdir(), reverse=True))
            continue
        if not path.is_file():
            raise IncompleteParserClosure("parser dependency is not a regular file")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        result.append((path.relative_to(root).as_posix(), digest))
    return tuple(sorted(result))


def _runtime_tree(path: Path, active: set[Path], memo: dict[Path, str]) -> str:
    """Content closure including native libraries and resolved image symlinks."""
    resolved = path.resolve(strict=True)
    if resolved in active or any(
        p in resolved.parents for p in (Path("/proc"), Path("/sys"), Path("/dev"))
    ):
        raise IncompleteParserClosure("cyclic or dynamic runtime dependency")
    if resolved in memo:
        return memo[resolved]
    if len(memo) > 200_000:
        raise IncompleteParserClosure("runtime closure exceeds the file limit")
    if resolved.is_file():
        with resolved.open("rb") as handle:
            result = hashlib.file_digest(handle, "sha256").hexdigest()
    elif resolved.is_dir():
        active.add(resolved)
        try:
            try:
                children = sorted(resolved.iterdir())
            except PermissionError:
                # Listing denial alone is insufficient: mode 0111 still permits
                # opening known descendants. faccessat checks effective IDs,
                # supplementary groups and ACLs, as used by the parser process.
                if os.access(resolved, os.X_OK, effective_ids=True):
                    raise IncompleteParserClosure(
                        "runtime directory cannot be enumerated"
                    )
                stat = resolved.stat()
                return sha256_digest(
                    {
                        "unsearchable_directory": str(resolved),
                        "mode": stat.st_mode,
                        "uid": stat.st_uid,
                        "gid": stat.st_gid,
                        "parser_uid": os.geteuid(),
                        "parser_gid": os.getegid(),
                        "parser_groups": tuple(sorted(os.getgroups())),
                    }
                )
            result = sha256_digest(
                tuple(
                    (
                        child.name,
                        str(child.resolve()) if child.is_symlink() else "",
                        _runtime_tree(child, active, memo),
                    )
                    for child in children
                )
            )
        finally:
            active.remove(resolved)
    else:
        raise IncompleteParserClosure("runtime dependency is not a regular file")
    memo[resolved] = result
    return result


def _runtime_identity() -> str:
    """Conservative image-only Python closure; unsupported installations miss.

    This initial protocol stays delivery-scoped. Cross-delivery reuse requires
    a separately versioned build identity and proof of the external/native closure.
    """
    paths = tuple(Path(p or ".").resolve() for p in sys.path)
    if any(
        os.getenv(name)
        for name in (
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "LD_AUDIT",
            "PYTHONPYCACHEPREFIX",
            "OPENSSL_CONF",
            "OPENSSL_MODULES",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        )
    ):
        raise IncompleteParserClosure("external runtime configuration is unsupported")
    # Deliberately conservative: include all installed image code/native data.
    # SEC sources, profiles, plugins and taxonomy mounts are keyed separately.
    roots = (Path("/app"), Path("/usr"))
    if any(
        path.exists()
        and not any(path == root or root in path.parents for root in roots)
        for path in paths
    ):
        raise IncompleteParserClosure("Python import path escapes the image closure")
    if sys.platform != "linux" or not Path("/app/src/fundamental_service").is_dir():
        raise IncompleteParserClosure(
            "only the controlled Linux service image is supported"
        )
    memo: dict[Path, str] = {}
    executable = _runtime_tree(Path(sys.executable), set(), memo)
    return sha256_digest(
        {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": executable,
            "worker_import_paths": parser_worker_import_paths(),
            "roots": tuple(
                (str(root), _runtime_tree(root, set(), memo)) for root in roots
            ),
            "loader_config": tuple(
                (str(path), _runtime_tree(path, set(), memo))
                for path in (Path("/etc/ld.so.cache"), Path("/etc/localtime"))
                if path.exists()
            ),
            "environment": sha256_digest(
                {
                    name: value
                    for name, value in os.environ.items()
                    if name.startswith(
                        (
                            "PYTHON",
                            "LC_",
                            "LD_",
                            "XDG_",
                            "OPENBLAS_",
                            "OMP_",
                            "MALLOC_",
                            "FUNDAMENTAL_SEC_PARSER_",
                        )
                    )
                    or name in {"LANG", "TZ"}
                }
            ),
        }
    )


def parser_action_input(
    path: Path,
    *,
    representation: Literal["normalized", "archive"],
    delivery_revision: str,
    normalization_inputs: tuple[str, ...],
    profile: ArelleValidationProfileV1,
    taxonomy_version: str,
    taxonomy_cache_dir: Path,
    source_content_hash: str,
) -> ParserActionInputV1:
    resources = [
        ("taxonomy", _directory_hash(taxonomy_cache_dir)),
        ("taxonomy-closure", sha256_digest(_files(taxonomy_cache_dir))),
    ]
    for name, directory in (
        ("edgar", profile.edgar_plugin_dir),
        ("xule", profile.xule_plugin_dir),
        ("historical", profile.historical_dqc_dir),
    ):
        if directory is not None:
            resources.append((name, _directory_hash(directory)))
            resources.append((name + "-closure", sha256_digest(_files(directory))))
    files = [profile.dqc_ruleset_path, profile.historical_dqc_axis_config]
    if profile.dqc_ruleset_catalog is not None:
        files.extend(binding.path for binding in profile.dqc_ruleset_catalog.bindings)
    for item in files:
        if item is not None:
            with item.open("rb") as handle:
                resources.append(
                    (str(item), hashlib.file_digest(handle, "sha256").hexdigest())
                )
    staged = _files(path.parent)
    if dict(staged).get(path.name) != source_content_hash:
        raise SnapshotError("SOURCE_HASH_MISMATCH", "parser action input differs")
    return ParserActionInputV1(
        delivery_revision=delivery_revision,
        representation=representation,
        entrypoint=path.name,
        files=staged,
        normalization_inputs=tuple(sorted(set(normalization_inputs))),
        implementation_digest=sha256_digest(_files(Path(__file__).parent)),
        runtime_digest=_runtime_identity(),
        resources=tuple(sorted(dict(resources).items())),
        profile_digest=profile.digest(),
        taxonomy_version=taxonomy_version,
        source_content_hash=source_content_hash,
        output_schema_digest=sha256_digest(ArelleParseReportV1.model_json_schema()),
    )
