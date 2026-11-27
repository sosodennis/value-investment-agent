"""Exact staged-input and conservative runtime identities for parser actions."""

from __future__ import annotations

import hashlib
import os
import platform
import sys
from asyncio import current_task
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, get_ident
from types import TracebackType
from typing import Literal, Protocol

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
from .serialization import canonical_bytes, sha256_digest
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


@dataclass(frozen=True)
class ParserActionResources:
    physical: tuple[tuple[str, str], ...]
    logical: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _ResourceDescriptor:
    profile_json: bytes
    taxonomy_cache_dir: Path
    trees: tuple[tuple[str, Path, Path, Path], ...]
    files: tuple[tuple[str, Path, Path, Path], ...]
    build: bytes | None
    configuration: str | None

    def encoded(self) -> bytes:
        return canonical_bytes(
            (
                self.profile_json.decode(),
                str(self.taxonomy_cache_dir),
                tuple(tuple(map(str, item)) for item in self.trees),
                tuple(tuple(map(str, item)) for item in self.files),
                self.build.decode() if self.build is not None else None,
                self.configuration,
            )
        )


def _resource_descriptor(
    profile: ArelleValidationProfileV1,
    taxonomy_cache_dir: Path,
    *,
    build: bytes | None = None,
    configuration: str | None = None,
) -> _ResourceDescriptor:
    trees = (
        ("taxonomy", taxonomy_cache_dir),
        ("edgar", profile.edgar_plugin_dir),
        ("xule", profile.xule_plugin_dir),
        ("historical", profile.historical_dqc_dir),
    )
    files = [
        ("dqc-primary", profile.dqc_ruleset_path),
        ("historical-axis", profile.historical_dqc_axis_config),
    ]
    if profile.dqc_ruleset_catalog is not None:
        files.extend(
            ("dqc-catalog:" + binding.taxonomy_namespace, binding.path)
            for binding in profile.dqc_ruleset_catalog.bindings
        )
    return _ResourceDescriptor(
        canonical_bytes(profile.model_dump(mode="json")),
        taxonomy_cache_dir,
        tuple(
            (role, path, path.absolute(), path.resolve(strict=True))
            for role, path in trees
            if path is not None
        ),
        tuple(
            (role, path, path.absolute(), path.resolve(strict=True))
            for role, path in files
            if path is not None
        ),
        build,
        configuration,
    )


def _read_parser_action_resources(
    descriptor: _ResourceDescriptor,
) -> ParserActionResources:
    resources: list[tuple[str, str]] = []
    for name, _, directory, _ in descriptor.trees:
        content, closure = _resource_digests(directory)
        resources.extend(((name, content), (name + "-closure", closure)))
    resource_trees = tuple(resources)
    logical_files = []
    for role, physical, item, _ in descriptor.files:
        with item.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
            resources.append((str(physical), digest))
            logical_files.append((role + ":" + item.name, digest))
    return ParserActionResources(
        tuple(sorted(dict(resources).items())),
        tuple(sorted((*resource_trees, *logical_files))),
    )


@dataclass(frozen=True)
class _ResourcePrincipal:
    pid: int
    thread: int
    task: object | None
    uid: int
    euid: int
    gid: int
    egid: int
    groups: tuple[int, ...]


def _resource_principal() -> _ResourcePrincipal:
    try:
        task: object | None = current_task()
    except RuntimeError:
        task = None
    return _ResourcePrincipal(
        os.getpid(),
        get_ident(),
        task,
        os.getuid(),
        os.geteuid(),
        os.getgid(),
        os.getegid(),
        tuple(sorted(os.getgroups())),
    )


@dataclass(frozen=True)
class _ResourceObservation:
    resources: ParserActionResources
    build_checks: ParserBuildChecks | None


class _ParserResourceState:
    def __init__(self, check_deadline: Callable[[], float]) -> None:
        self.nonce = object()
        self._principal = _resource_principal()
        self._check_deadline = check_deadline
        self.status: Literal["new", "open", "finished", "aborted"] = "new"
        self._build: tuple[bytes, str | None] | None = None
        self.observations: dict[_ResourceDescriptor, _ResourceObservation] = {}
        self.active_cut: _ParserResourceCut | None = None
        self.retained_bytes = 0
        self.high_water_keys = 0
        self.high_water_bytes = 0

    def check(self, nonce: object) -> None:
        if (
            nonce is not self.nonce
            or self.status != "open"
            or _resource_principal() != self._principal
        ):
            raise IncompleteParserClosure("parser resource operation is not current")
        self._check_deadline()

    def descriptor(
        self,
        profile: ArelleValidationProfileV1,
        root: Path,
        checks: ParserBuildChecks | None,
    ) -> _ResourceDescriptor:
        build = None
        configuration = None
        if checks is not None:
            try:
                build = canonical_bytes(checks.current())
            except IncompleteParserClosure:
                if self._build is not None:
                    raise
            else:
                configuration = checks._configuration
                identity = build, configuration
                if self._build is not None and identity != self._build:
                    raise IncompleteParserClosure("parser resource build changed")
                self._build = identity
        return _resource_descriptor(
            profile, root, build=build, configuration=configuration
        )

    def observe(
        self,
        nonce: object,
        profile: ArelleValidationProfileV1,
        root: Path,
        checks: ParserBuildChecks | None,
        *,
        reuse: bool,
    ) -> ParserActionResources:
        self.check(nonce)
        descriptor = self.descriptor(profile, root, checks)
        previous = self.observations.get(descriptor)
        if reuse and descriptor.build is not None and previous is not None:
            self.check(nonce)
            return previous.resources
        resources = _read_parser_action_resources(descriptor)
        self.check(nonce)
        if self.descriptor(profile, root, checks) != descriptor:
            raise IncompleteParserClosure("parser resource paths changed")
        if previous is not None:
            if previous.resources != resources:
                raise IncompleteParserClosure("parser resource bytes changed")
        else:
            size = len(descriptor.encoded()) + len(
                canonical_bytes((resources.physical, resources.logical))
            )
            if (
                len(self.observations) >= 32
                or self.retained_bytes + size > 2 * 1024 * 1024
            ):
                raise IncompleteParserClosure(
                    "parser resource operation exceeds its bounds"
                )
            self.observations[descriptor] = _ResourceObservation(resources, checks)
            self.retained_bytes += size
            self.high_water_keys = max(self.high_water_keys, len(self.observations))
            self.high_water_bytes = max(self.high_water_bytes, self.retained_bytes)
        return resources

    def recheck(
        self, descriptor: _ResourceDescriptor, observed: _ResourceObservation
    ) -> None:
        self.check(self.nonce)
        profile = ArelleValidationProfileV1.model_validate_json(descriptor.profile_json)
        if (
            self.descriptor(
                profile, descriptor.taxonomy_cache_dir, observed.build_checks
            )
            != descriptor
        ):
            raise IncompleteParserClosure("parser resource paths changed")
        if _read_parser_action_resources(descriptor) != observed.resources:
            raise IncompleteParserClosure("parser resource bytes changed")
        self.check(self.nonce)
        if (
            self.descriptor(
                profile, descriptor.taxonomy_cache_dir, observed.build_checks
            )
            != descriptor
        ):
            raise IncompleteParserClosure("parser resource paths changed")

    def finish(self) -> None:
        try:
            self.check(self.nonce)
            for descriptor, observed in self.observations.items():
                self.recheck(descriptor, observed)
        except BaseException:
            self.status = "aborted"
            raise
        else:
            self.status = "finished"
        finally:
            self.observations.clear()
            self.retained_bytes = 0


@dataclass(frozen=True)
class _ParserResourceBorrow:
    _state: _ParserResourceState
    _nonce: object

    def observe(
        self,
        profile: ArelleValidationProfileV1,
        root: Path,
        checks: ParserBuildChecks | None,
        *,
        reuse: bool,
    ) -> ParserActionResources:
        return self._state.observe(self._nonce, profile, root, checks, reuse=reuse)


class _ResourceCompletion(Protocol):
    def seal(self) -> None: ...


@dataclass(frozen=True)
class _LegacyResourceCompletion:
    operation: _ParserResourceOperation
    terminal: bool

    def seal(self) -> None:
        if self.terminal:
            self.operation.finish()
        else:
            self.operation._state.check(self.operation._state.nonce)


@dataclass(frozen=True)
class _CurrentResourceBorrow:
    cut: _ParserResourceCut
    nonce: object

    def observe(
        self,
        profile: ArelleValidationProfileV1,
        root: Path,
        checks: ParserBuildChecks | None,
        *,
        reuse: bool,
    ) -> ParserActionResources:
        return self.cut.observe(self.nonce, profile, root, checks)


class _ParserResourceCut(AbstractContextManager["_ParserResourceCut"]):
    """Opening/closing byte samples for one synchronous readonly candidate proof.

    Intermediate helpers borrow only this cut's opening observation. Restored
    transient changes between samples are not continuous-immutability evidence.
    """

    def __init__(
        self, operation: _CurrentParserResourceOperation, terminal: bool
    ) -> None:
        self._operation = operation
        self._state = operation._state
        self._lifetime_nonce = self._state.nonce
        self._nonce = object()
        self._borrow = _CurrentResourceBorrow(self, self._nonce)
        self._terminal = terminal
        self._phase: Literal["new", "open", "sealed", "aborted"] = "new"
        self._observed: set[_ResourceDescriptor] = set()
        self._token: (
            Token[_ParserResourceBorrow | _CurrentResourceBorrow | None] | None
        ) = None

    def check(self, nonce: object) -> None:
        self._state.check(self._lifetime_nonce)
        self._operation._require_owner()
        if (
            nonce is not self._nonce
            or self._phase != "open"
            or self._state.active_cut is not self
            or _RESOURCE_OPERATION.get() is not self._borrow
        ):
            raise IncompleteParserClosure("parser resource cut is not current")

    def __enter__(self) -> _ParserResourceCut:
        self._state.check(self._lifetime_nonce)
        self._operation._require_owner()
        if self._phase != "new" or self._state.active_cut is not None:
            raise IncompleteParserClosure("parser resource cut cannot reopen or nest")
        self._phase = "open"
        self._state.active_cut = self
        self._token = _RESOURCE_OPERATION.set(self._borrow)
        return self

    def observe(
        self,
        nonce: object,
        profile: ArelleValidationProfileV1,
        root: Path,
        checks: ParserBuildChecks | None,
    ) -> ParserActionResources:
        self.check(nonce)
        descriptor = self._state.descriptor(profile, root, checks)
        if (
            descriptor in self._observed
            and descriptor.build is not None
            and descriptor.configuration is not None
        ):
            self.check(nonce)
            return self._state.observations[descriptor].resources
        resources = self._state.observe(
            self._lifetime_nonce, profile, root, checks, reuse=False
        )
        self.check(nonce)
        key = next(key for key in self._state.observations if key == descriptor)
        self._observed.add(key)
        return resources

    def seal(self) -> None:
        try:
            self.check(self._nonce)
            if self._terminal:
                for descriptor, observed in self._state.observations.items():
                    if descriptor not in self._observed:
                        self._state.recheck(descriptor, observed)
                        self._observed.add(descriptor)
            for descriptor in self._observed:
                self.check(self._nonce)
                self._state.recheck(descriptor, self._state.observations[descriptor])
            self.check(self._nonce)
        except BaseException:
            self._phase = "aborted"
            self._state.status = "aborted"
            raise
        else:
            self._phase = "sealed"
            if self._terminal:
                self._state.status = "finished"
        finally:
            self._observed.clear()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        try:
            if exc_type is None and self._phase != "sealed":
                raise IncompleteParserClosure("parser resource cut did not seal")
        finally:
            if self._token is not None:
                _RESOURCE_OPERATION.reset(self._token)
                self._token = None
            self._state.active_cut = None
            self._observed.clear()
            if exc_type is not None or self._phase != "sealed":
                self._phase = "aborted"
                self._state.status = "aborted"
        return False


_RESOURCE_OPERATION: ContextVar[
    _ParserResourceBorrow | _CurrentResourceBorrow | None
] = ContextVar("parser_resource_operation", default=None)


class _ParserResourceOperation(AbstractContextManager["_ParserResourceOperation"]):
    def __init__(self, check_deadline: Callable[[], float]) -> None:
        self._state = _ParserResourceState(check_deadline)
        self._token: (
            Token[_ParserResourceBorrow | _CurrentResourceBorrow | None] | None
        ) = None

    def __enter__(self) -> _ParserResourceOperation:
        if self._state.status != "new":
            raise IncompleteParserClosure("parser resource operation cannot reopen")
        self._state.status = "open"
        self._state.check(self._state.nonce)
        self._token = _RESOURCE_OPERATION.set(
            _ParserResourceBorrow(self._state, self._state.nonce)
        )
        return self

    def completion(self, *, terminal: bool) -> _ResourceCompletion:
        return _LegacyResourceCompletion(self, terminal)

    @contextmanager
    def current_cut(self, *, terminal: bool) -> Iterator[_ResourceCompletion]:
        yield self.completion(terminal=terminal)

    def finish(self) -> None:
        self._state.finish()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        try:
            if exc_type is None and self._state.status != "finished":
                raise IncompleteParserClosure(
                    "parser resource operation did not finish"
                )
        finally:
            if self._token is not None:
                _RESOURCE_OPERATION.reset(self._token)
            if self._state.status != "finished":
                self._state.status = "aborted"
            self._state.observations.clear()
            self._state.retained_bytes = 0
        return False


class _CurrentParserResourceOperation(_ParserResourceOperation):
    def __init__(
        self, check_deadline: Callable[[], float], require_owner: Callable[[], None]
    ) -> None:
        super().__init__(check_deadline)
        self._require_owner = require_owner

    def __enter__(self) -> _CurrentParserResourceOperation:
        if self._state.status != "new":
            raise IncompleteParserClosure("parser resource operation cannot reopen")
        self._require_owner()
        self._state.status = "open"
        self._state.check(self._state.nonce)
        return self

    @contextmanager
    def current_cut(self, *, terminal: bool) -> Iterator[_ResourceCompletion]:
        with _ParserResourceCut(self, terminal) as cut:
            yield cut

    def finish(self) -> None:
        raise IncompleteParserClosure("readonly resources require a terminal cut")


def parser_action_resources(
    profile: ArelleValidationProfileV1, taxonomy_cache_dir: Path
) -> ParserActionResources:
    """Read fresh bytes, or borrow inside a mandatory readonly candidate cut seal."""
    operation = _RESOURCE_OPERATION.get()
    if operation is not None:
        return operation.observe(
            profile, taxonomy_cache_dir, ParserBuildChecks(), reuse=False
        )
    return _read_parser_action_resources(
        _resource_descriptor(profile, taxonomy_cache_dir)
    )


def parser_action_resource_descriptor(
    profile: ArelleValidationProfileV1,
    taxonomy_cache_dir: Path,
    checks: ParserBuildChecks,
) -> bytes:
    """Commit stable resource identity after proving the current local boundary."""
    return _resource_descriptor(
        profile,
        taxonomy_cache_dir,
        build=canonical_bytes(checks.current()),
    ).encoded()


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
    operation = _RESOURCE_OPERATION.get()
    resources = (
        operation.observe(profile, taxonomy_cache_dir, build_checks, reuse=True)
        if operation is not None
        else parser_action_resources(profile, taxonomy_cache_dir)
    )
    staged = _files(path.parent)
    if dict(staged).get(path.name) != source_content_hash:
        raise SnapshotError("SOURCE_HASH_MISMATCH", "parser action input differs")
    fields = dict(
        representation=representation,
        entrypoint=path.name,
        files=staged,
        normalization_inputs=tuple(sorted(set(normalization_inputs))),
        resources=resources.physical,
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
                    "resources": resources.logical,
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
