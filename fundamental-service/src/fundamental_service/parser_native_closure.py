"""Conservative linked-native dependency admission for the immutable image."""

from __future__ import annotations

import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Literal

_INSPECTOR = Path("/usr/bin/ldd")
_CACHE_INSPECTOR = Path("/usr/sbin/ldconfig")


class NativeClosureError(ValueError):
    pass


def _elf_identity(path: Path) -> tuple[int, int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(20)
    if header[:4] != b"\x7fELF":
        return None
    if len(header) < 20 or header[4] not in {1, 2} or header[5] not in {1, 2}:
        raise NativeClosureError("unsupported native object format")
    order: Literal["little", "big"] = "little" if header[5] == 1 else "big"
    return (
        header[4],
        int.from_bytes(header[16:18], order),
        int.from_bytes(header[18:20], order),
    )


def _search_paths(path: Path) -> tuple[Path, ...]:
    """Decode ELF loader paths; missing libraries are safe only in fixed roots."""
    raw = path.read_bytes()
    try:
        wide = raw[4] == 2
        order = "<" if raw[5] == 1 else ">"
        offset = struct.unpack_from(
            order + ("Q" if wide else "I"), raw, 32 if wide else 28
        )[0]
        size, count = struct.unpack_from(order + "HH", raw, 54 if wide else 42)
        segments = []
        for index in range(count):
            fields = struct.unpack_from(
                order + ("IIQQQQQQ" if wide else "IIIIIIII"), raw, offset + index * size
            )
            kind, file_offset, address, file_size = (
                (fields[0], fields[2], fields[3], fields[5])
                if wide
                else (fields[0], fields[1], fields[2], fields[4])
            )
            if file_offset + file_size > len(raw):
                raise NativeClosureError("invalid ELF segment bounds")
            segments.append((kind, file_offset, address, file_size))
        interpreters = []
        for kind, start, _, length in segments:
            if kind == 3:  # PT_INTERP is the executable's actual runtime loader.
                value = raw[start : start + length].rstrip(b"\0").decode("utf-8")
                if not Path(value).is_absolute() or "$" in value:
                    raise NativeClosureError("external ELF interpreter is unsupported")
                interpreters.append(Path(value).resolve())
        strings = None
        paths = []
        step = 16 if wide else 8
        for kind, start, _, length in segments:
            if kind != 2:  # PT_DYNAMIC
                continue
            for position in range(start, start + length, step):
                tag, value = struct.unpack_from(
                    order + ("qQ" if wide else "iI"), raw, position
                )
                if tag == 0:
                    break
                if tag == 5:  # DT_STRTAB virtual address
                    strings = value
                if tag in {1, 15, 29}:  # DT_NEEDED / DT_RPATH / DT_RUNPATH
                    paths.append((tag, value))
        if not paths:
            return tuple(interpreters)
        bases = [
            start + strings - address
            for kind, start, address, length in segments
            if kind == 1
            and strings is not None
            and address <= strings < address + length
        ]
        if len(bases) != 1:
            raise NativeClosureError("ELF loader strings are unavailable")
        resolved = interpreters
        for tag, relative in paths:
            start = bases[0] + relative
            end = raw.index(b"\0", start)
            value = raw[start:end].decode("utf-8")
            if tag == 1 and "/" not in value:
                continue
            for entry in value.split(":"):
                entry = entry.replace("${ORIGIN}", str(path.parent)).replace(
                    "$ORIGIN", str(path.parent)
                )
                if "$" in entry or not Path(entry).is_absolute():
                    raise NativeClosureError(
                        "dynamic native search path is unsupported"
                    )
                selected = Path(entry).resolve()
                resolved.append(selected.parent if tag == 1 else selected)
        return tuple(resolved)
    except (IndexError, ValueError, struct.error) as error:
        raise NativeClosureError("unsupported ELF loader metadata") from error


def _require_image_path(path: Path, image_mounts: tuple[Path, ...]) -> None:
    resolved = path.resolve()
    if not any(
        resolved == root or root in resolved.parents
        for root in (Path("/app"), Path("/usr"))
    ) or any(
        resolved == mount or mount in resolved.parents or resolved in mount.parents
        for mount in image_mounts
    ):
        raise NativeClosureError("native search path escapes the image closure")


def _cache_paths(
    hashed: dict[Path, str], image_mounts: tuple[Path, ...]
) -> tuple[str, ...]:
    inspector = _CACHE_INSPECTOR.resolve(strict=True)
    if inspector not in hashed:
        raise NativeClosureError("native cache inspector is unavailable")
    try:
        result = subprocess.run(
            [str(inspector), "-p"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise NativeClosureError("native cache paths are unavailable") from error
    if result.returncode:
        raise NativeClosureError("native cache paths are unavailable")
    paths = []
    lines = result.stdout.strip().splitlines()
    if not lines or re.fullmatch(r"\d+ libs found in cache `.+'", lines[0]) is None:
        raise NativeClosureError("unsupported native cache format")
    for line in lines[1:]:
        if line.startswith("Cache generated by:"):
            continue
        match = re.fullmatch(r"\s*\S+ \([^)]+\) => (/\S+)", line)
        if match is None:
            raise NativeClosureError("unsupported native cache entry")
        path = Path(match[1]).resolve()
        _require_image_path(path, image_mounts)
        paths.append(str(path))
    return tuple(sorted(set(paths)))


def native_closure(
    hashed: dict[Path, str], image_mounts: tuple[Path, ...]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Require resolved ELF dependencies to belong to the already hashed image.

    The controlled image's inspector is itself hashed. SEC documents and other
    external data are never executed or passed to this command.
    """
    loader = _INSPECTOR.resolve(strict=True)
    if loader not in hashed:
        raise NativeClosureError("native dependency inspector is unavailable")
    interpreter = _elf_identity(Path(sys.executable).resolve(strict=True))
    if interpreter is None:
        raise NativeClosureError("native interpreter architecture is unavailable")
    dependencies: list[tuple[str, tuple[str, ...]]] = [
        ("loader-cache-paths", _cache_paths(hashed, image_mounts))
    ]
    for path in sorted(hashed):
        if not path.is_file():
            continue
        identity = _elf_identity(path)
        if identity is None:
            continue
        elf_class, kind, machine = identity
        if kind == 1:  # ET_REL cannot be an executable or dlopen input.
            continue
        if kind not in {2, 3}:
            raise NativeClosureError("unsupported native object type")
        if (elf_class, machine) != (interpreter[0], interpreter[2]):
            # Arelle bundles Tk libraries for other architectures. Their bytes
            # remain hashed, but this interpreter cannot load their dependencies.
            dependencies.append((str(path), ("incompatible-interpreter-architecture",)))
            continue
        for directory in _search_paths(path):
            _require_image_path(directory, image_mounts)
        try:
            result = subprocess.run(
                [str(loader), str(path)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise NativeClosureError("native dependencies are unavailable") from error
        text = result.stdout.strip()
        if text == "statically linked" and result.returncode == 0:
            dependencies.append((str(path), (text,)))
            continue
        if result.returncode or not text:
            raise NativeClosureError("native dependencies are incomplete")
        selected = []
        for line in text.splitlines():
            value = line.strip()
            if re.fullmatch(r"\S+ => not found", value):
                # Loader cache and default roots are hashed and immutable, and
                # explicit search directories above cannot escape those roots.
                selected.append(value)
                continue
            if re.fullmatch(r"linux-(?:vdso|gate)\.so\.\d+ \(0x[0-9a-f]+\)", value):
                continue
            match = re.fullmatch(r"(?:\S+ => )?(/\S+) \(0x[0-9a-f]+\)", value)
            if match is None:
                raise NativeClosureError("unrecognized native dependency")
            dependency = Path(match[1]).resolve(strict=True)
            if dependency not in hashed or any(
                dependency == mount or mount in dependency.parents
                for mount in image_mounts
            ):
                raise NativeClosureError("native dependency escapes the image closure")
            selected.append(str(dependency))
        dependencies.append((str(path), tuple(sorted(set(selected)))))
    return tuple(dependencies)
