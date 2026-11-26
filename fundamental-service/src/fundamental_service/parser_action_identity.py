"""Exact staged-input and conservative runtime identities for parser actions."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal

from .arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    parser_worker_import_paths,
)
from .parser_action_contracts import (
    ParserActionInput,
    ParserActionInputV1,
    ParserActionInputV3,
    ParserBuildIdentityV1,
)
from .serialization import sha256_digest
from .parser_native_closure import NativeClosureError, native_closure
from .resource_hashing import ResourceHashReader
from .snapshots import SnapshotError


class IncompleteParserClosure(ValueError):
    """An unaccounted runtime input requires an ordinary parse."""


def _regular_files(root: Path) -> Iterator[Path]:
    if not root.is_dir() or root.is_symlink():
        raise IncompleteParserClosure("parser input root is not a regular directory")
    # Explicit traversal propagates unreadable-directory errors. Path.rglob can
    # suppress them and silently omit runtime dependencies.
    pending = [root]
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
        yield path


def _files(root: Path) -> tuple[tuple[str, str], ...]:
    """Hash exact file contents; never admit based on stat data or a supplied hash."""
    result = []
    for path in _regular_files(root):
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        result.append((path.relative_to(root).as_posix(), digest))
    return tuple(sorted(result))


def _resource_digests(root: Path) -> tuple[str, str]:
    """Compute the existing directory and complete closure identities in one read."""
    directory = hashlib.sha256()
    files = []
    with ResourceHashReader() as reader:
        for path in sorted(_regular_files(root)):
            if path.is_symlink():
                raise IncompleteParserClosure(
                    "symlinked parser dependencies are unsupported"
                )
            if not path.is_file():
                raise IncompleteParserClosure("parser dependency is not a regular file")
            relative = path.relative_to(root)
            included = "__pycache__" not in relative.parts and path.suffix not in {
                ".pyc",
                ".pyo",
            }
            if included:
                directory.update(str(relative).encode("utf-8"))
                directory.update(b"\0")
            digest = hashlib.sha256()

            def consume(chunk: memoryview) -> None:
                digest.update(chunk)
                if included:
                    directory.update(chunk)

            reader.update(path, consume)
            files.append((relative.as_posix(), digest.hexdigest()))
    return directory.hexdigest(), sha256_digest(tuple(sorted(files)))


def _runtime_tree(
    path: Path,
    active: set[Path],
    memo: dict[Path, str],
    *,
    image_mounts: tuple[Path, ...] | None = None,
) -> str:
    """Content closure including native libraries and resolved image symlinks."""
    resolved = path.resolve(strict=True)
    location = str(resolved)
    if image_mounts is not None:
        if any(
            location == str(mount) or location.startswith(str(mount).rstrip("/") + "/")
            for mount in image_mounts
        ):
            raise IncompleteParserClosure("build closure escapes the immutable image")
    if resolved in active or location.startswith(("/proc/", "/sys/", "/dev/")):
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
                    }
                )
            result = sha256_digest(
                tuple(
                    (
                        child.name,
                        str(child.resolve()) if child.is_symlink() else "",
                        _runtime_tree(child, active, memo, image_mounts=image_mounts),
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


def _runtime_identity(*, image_mounts: tuple[Path, ...] | None = None) -> str:
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
    executable = _runtime_tree(
        Path(sys.executable), set(), memo, image_mounts=image_mounts
    )
    roots_digest = tuple(
        (str(root), _runtime_tree(root, set(), memo, image_mounts=image_mounts))
        for root in roots
    )
    try:
        native = native_closure(memo, image_mounts) if image_mounts is not None else ()
    except NativeClosureError as error:
        raise IncompleteParserClosure(str(error)) from error
    return sha256_digest(
        {
            **(
                {"execution_flags": (repr(sys.flags), sys._xoptions)}
                if image_mounts is not None
                else {}
            ),
            "python": sys.version,
            "platform": platform.platform(),
            "executable": executable,
            "worker_import_paths": parser_worker_import_paths(),
            "roots": roots_digest,
            **({"native_dependencies": native} if image_mounts is not None else {}),
            "loader_config": tuple(
                (str(path), _runtime_tree(path, set(), memo, image_mounts=image_mounts))
                for path in (
                    Path("/etc/ld.so.cache"),
                    Path("/etc/localtime"),
                    *(
                        (Path("/etc/ld.so.preload"),)
                        if image_mounts is not None
                        else ()
                    ),
                )
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


def _immutable_build_configuration() -> tuple[str, tuple[Path, ...]]:
    """Establish the image boundary from kernel state, not deployment claims.

    A read-only image root predates Python startup. No writable/bind descendant
    in the resolved build closure is allowed; source mounts are keyed separately.
    """
    if sys.platform != "linux" or os.geteuid() == 0:
        raise IncompleteParserClosure("immutable parser image is unavailable")
    if any(os.getenv(name) for name in ("XML_CATALOG_FILES", "SGML_CATALOG_FILES")):
        raise IncompleteParserClosure("external XML catalogs are unsupported")
    if any(
        os.getenv(name) for name in ("GCONV_PATH", "LOCPATH", "TZDIR", "GLIBC_TUNABLES")
    ):
        raise IncompleteParserClosure(
            "external native runtime configuration is unsupported"
        )
    if any(name.startswith("LD_") and value for name, value in os.environ.items()):
        raise IncompleteParserClosure(
            "external native loader configuration is unsupported"
        )
    if any(
        Path(name).exists() for name in ("/etc/xml", "/etc/sgml", "/etc/ld.so.preload")
    ):
        raise IncompleteParserClosure(
            "external native/XML configuration is unsupported"
        )
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        any(
            int(status.get(name, "0").strip(), 16)
            for name in ("CapEff", "CapPrm", "CapAmb")
        )
        or status.get("NoNewPrivs", "0").strip() != "1"
    ):
        raise IncompleteParserClosure("parser may change its image boundary")
    mounts = Path("/proc/self/mountinfo").read_text()
    parsed = [line.split() for line in mounts.splitlines()]
    roots = [fields for fields in parsed if fields[4] == "/"]
    if (
        len(roots) != 1
        or "ro" not in roots[0][5].split(",")
        or not os.statvfs("/").f_flag & os.ST_RDONLY
    ):
        raise IncompleteParserClosure("parser image root is writable")
    if roots[0][roots[0].index("-") + 1] != "overlay":
        raise IncompleteParserClosure("parser root is not the controlled image")
    # Mountinfo escapes whitespace and backslashes with octal codes.
    mounts_below = tuple(
        Path(replace_mount_escapes(fields[4])) for fields in parsed if fields[4] != "/"
    )
    configuration = sha256_digest(
        (
            mounts,
            tuple(sorted(os.environ.items())),
            tuple(sys.path),
            tuple(str(Path(path or ".").resolve()) for path in sys.path),
            sys.executable,
            str(Path(sys.executable).resolve()),
            sys.version,
            repr(sys.flags),
            sys._xoptions,
            os.geteuid(),
            os.getegid(),
            tuple(sorted(os.getgroups())),
        )
    )
    return configuration, mounts_below


def replace_mount_escapes(value: str) -> str:
    for escaped, char in (
        ("\\040", " "),
        ("\\011", "\t"),
        ("\\012", "\n"),
        ("\\134", "\\"),
    ):
        value = value.replace(escaped, char)
    return value


@dataclass(frozen=True)
class _ImmutableBuild:
    configuration: str
    value: ParserBuildIdentityV1


_BUILD_LOCK = Lock()
_SHARED_BUILD: _ImmutableBuild | None = None


def _reset_build_after_fork() -> None:
    global _BUILD_LOCK, _SHARED_BUILD
    _BUILD_LOCK = Lock()
    _SHARED_BUILD = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_build_after_fork)


def _calculate_build(
    configuration: str, mounts: tuple[Path, ...]
) -> ParserBuildIdentityV1:
    implementation = sha256_digest(_files(Path(__file__).parent))
    runtime = _runtime_identity(image_mounts=mounts)
    build = ParserBuildIdentityV1(
        implementation_digest=implementation,
        runtime_digest=runtime,
        output_schema_digest=sha256_digest(ArelleParseReportV1.model_json_schema()),
    )
    if _immutable_build_configuration()[0] != configuration:
        raise IncompleteParserClosure("parser image changed during verification")
    return build


class ParserBuildChecks:
    """Independent boundary checks over an owner-computed immutable build value."""

    def __init__(self, *, share_image: bool = True) -> None:
        self._pid = os.getpid()
        self._share_image = share_image
        self._configuration: str | None = None
        self._build: ParserBuildIdentityV1 | None = None

    def current(self) -> ParserBuildIdentityV1:
        global _SHARED_BUILD
        with _BUILD_LOCK:
            if self._pid != os.getpid():
                self._pid = os.getpid()
                self._configuration = None
                self._build = None
            # Prove this consumer's boundary after waiting for initialization.
            configuration, mounts = _immutable_build_configuration()
            if self._configuration is not None and self._configuration != configuration:
                raise IncompleteParserClosure("parser image configuration changed")
            if self._build is None:
                shared = _SHARED_BUILD if self._share_image else None
                if shared is not None and shared.configuration == configuration:
                    build = shared.value
                else:
                    build = _calculate_build(configuration, mounts)
                    if self._share_image:
                        _SHARED_BUILD = _ImmutableBuild(configuration, build)
                self._configuration = configuration
                self._build = build
            return self._build

    def verify(self) -> None:
        if self._build is not None:
            self.current()


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
    build_checks: ParserBuildChecks | None = None,
) -> ParserActionInput:
    resources: list[tuple[str, str]] = []
    for name, directory in (
        ("taxonomy", taxonomy_cache_dir),
        ("edgar", profile.edgar_plugin_dir),
        ("xule", profile.xule_plugin_dir),
        ("historical", profile.historical_dqc_dir),
    ):
        if directory is not None:
            content, closure = _resource_digests(directory)
            resources.extend(((name, content), (name + "-closure", closure)))
    resource_trees = tuple(resources)
    files = [
        ("dqc-primary", profile.dqc_ruleset_path),
        ("historical-axis", profile.historical_dqc_axis_config),
    ]
    if profile.dqc_ruleset_catalog is not None:
        files.extend(
            ("dqc-catalog:" + binding.taxonomy_namespace, binding.path)
            for binding in profile.dqc_ruleset_catalog.bindings
        )
    logical_files = []
    for role, item in files:
        if item is not None:
            with item.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
                resources.append((str(item), digest))
                logical_files.append((role + ":" + item.name, digest))
    staged = _files(path.parent)
    if dict(staged).get(path.name) != source_content_hash:
        raise SnapshotError("SOURCE_HASH_MISMATCH", "parser action input differs")
    fields = dict(
        representation=representation,
        entrypoint=path.name,
        files=staged,
        normalization_inputs=tuple(sorted(set(normalization_inputs))),
        resources=tuple(sorted(dict(resources).items())),
        profile_digest=profile.digest(),
        taxonomy_version=taxonomy_version,
        source_content_hash=source_content_hash,
    )
    if build_checks is not None:
        try:
            build = build_checks.current()
        except IncompleteParserClosure:
            pass
        else:
            return ParserActionInputV3.model_validate(
                {
                    **fields,
                    "resources": tuple(sorted((*resource_trees, *logical_files))),
                    "build": build,
                }
            )
    return ParserActionInputV1.model_validate(
        {
            **fields,
            "delivery_revision": delivery_revision,
            "implementation_digest": sha256_digest(_files(Path(__file__).parent)),
            "runtime_digest": _runtime_identity(),
            "output_schema_digest": sha256_digest(
                ArelleParseReportV1.model_json_schema()
            ),
        }
    )
