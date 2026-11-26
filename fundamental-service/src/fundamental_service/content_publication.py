"""Publication access for private or deployment-trusted content readers."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from .snapshots import SnapshotError


def _refused(code: str, message: str) -> SnapshotError:
    from .snapshots import SnapshotError

    return SnapshotError(code, message)


@dataclass(frozen=True)
class PrivateContentPublication:
    pass


@dataclass(frozen=True)
class TrustedReaderGroupPublication:
    gid: int

    def __post_init__(self) -> None:
        if (
            type(self.gid) is not int
            or not 0 < self.gid < 2**32 - 1
            or self.gid not in {os.getegid(), *os.getgroups()}
        ):
            raise _refused(
                "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE",
                "content reader group is invalid or unavailable to the publisher",
            )


ContentPublicationAccess: TypeAlias = (
    PrivateContentPublication | TrustedReaderGroupPublication
)


def configured_content_publication_access() -> ContentPublicationAccess:
    value = os.getenv("FUNDAMENTAL_SERVICE_CONTENT_READER_GID")
    if value is None:
        return PrivateContentPublication()
    if not re.fullmatch(r"[0-9]{1,10}", value):
        raise _refused(
            "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE",
            "content reader group must be a numeric deployment GID",
        )
    return TrustedReaderGroupPublication(int(value))


def ensure_publication_directory(
    directory: Path, access: ContentPublicationAccess
) -> None:
    if isinstance(access, PrivateContentPublication):
        directory.mkdir(parents=True, exist_ok=True)
        return
    try:
        directory.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        assert_published_access(directory, access)
        return
    except OSError as error:
        raise _refused(
            "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE",
            "content publication directory cannot be created",
        ) from error
    try:
        os.chown(directory, -1, access.gid)
        os.chmod(directory, 0o750)
    except OSError as error:
        raise _refused(
            "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE",
            "content publication directory access cannot be prepared",
        ) from error
    assert_published_access(directory, access)


def prepare_publication_fd(fd: int, access: ContentPublicationAccess) -> None:
    if isinstance(access, PrivateContentPublication):
        return
    try:
        os.fchown(fd, -1, access.gid)
        os.fchmod(fd, 0o640)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_gid != access.gid
            or stat.S_IMODE(info.st_mode) != 0o640
        ):
            raise OSError("content inode access differs from publication policy")
    except OSError as error:
        raise _refused(
            "CONTENT_PUBLICATION_ACCESS_UNAVAILABLE",
            "content publication access cannot be prepared",
        ) from error


def assert_published_access(path: Path, access: ContentPublicationAccess) -> None:
    if isinstance(access, PrivateContentPublication):
        return
    try:
        info = path.stat()
    except PermissionError as error:
        raise _refused(
            "SOURCE_BYTES_FORBIDDEN", "content access is forbidden by storage"
        ) from error
    mode = stat.S_IMODE(info.st_mode)
    expected_mode = 0o750 if stat.S_ISDIR(info.st_mode) else 0o640
    if (
        not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
        or info.st_uid != os.geteuid()
        or info.st_gid != access.gid
        or mode != expected_mode
    ):
        raise _refused(
            "CONTENT_ACCESS_INSTALL_REQUIRED",
            "retained content access requires deployment owner installation",
        )
