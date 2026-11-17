"""Cross-delivery parser bodies retain independent build and delivery checks."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from pathlib import Path

import pytest

from test_parser_actions import case, issuer
from fundamental_service.parser_action_evidence import require_parser_action_evidence
from fundamental_service.parser_action_identity import _runtime_tree
from fundamental_service.snapshots import SnapshotError


def cross_delivery_case(tmp_path):
    from fundamental_service.parser_action_contracts import (
        ParserActionInputV2,
        ParserBuildIdentityV1,
    )

    c = case(tmp_path)
    build = ParserBuildIdentityV1(
        implementation_digest=c.request.implementation_digest,
        runtime_digest=c.request.runtime_digest,
        output_schema_digest=c.request.output_schema_digest,
    )
    request = ParserActionInputV2.model_validate(
        {
            **c.request.model_dump(
                exclude={
                    "protocol",
                    "delivery_revision",
                    "implementation_digest",
                    "runtime_digest",
                    "output_schema_digest",
                }
            ),
            "build": build,
        }
    )

    def run(revision="d" * 40, **changes):
        arguments = dict(
            request=request,
            profile=c.profile,
            deadline_at=datetime.now(UTC) + timedelta(seconds=10),
            execute=c.execute,
            check_inputs=lambda: request,
            delivery_revision=revision,
        )
        arguments.update(changes)
        return c.owner._perform(**arguments)

    return SimpleNamespace(c=c, request=request, build=build, run=run)


def test_cross_delivery_body_reuse_retains_real_time_and_new_use_attestation(
    tmp_path, monkeypatch
):
    from fundamental_service.parser_action_identity import ParserBuildChecks
    from fundamental_service.parser_action_contracts import (
        parser_action_markers,
        ParserActionUseV2,
        ParserActionDeliveryV2,
    )

    v = cross_delivery_case(tmp_path)
    published = []
    put = v.c.artifacts.put_with_receipt

    def capture(identity, payload, dependencies=()):
        published.append((identity, payload))
        return put(identity, payload, dependencies)

    monkeypatch.setattr(v.c.artifacts, "put_with_receipt", capture)
    first, second, third = v.run(), v.run("e" * 40), v.run("e" * 40)
    assert second == third
    assert len(v.c.calls) == 1 and len(v.c.index.results) == 1
    assert first.parsed_at == second.parsed_at
    first_marker, second_marker = (
        parser_action_markers(first.validation_evidence)[0],
        parser_action_markers(second.validation_evidence)[0],
    )
    assert first_marker[:4] == second_marker[:4] and first_marker[4] != second_marker[4]
    binding = ParserActionDeliveryV2.model_validate_json(
        v.c.artifacts.read("sec-parser-action-delivery-v2:" + second_marker[4])
    )
    assert binding.delivery_revision == "e" * 40 and binding.build == v.build
    uses = [
        payload
        for identity, payload in published
        if isinstance(payload, ParserActionUseV2)
    ]
    assert len(uses) == 3 and uses[1].reused and uses[2].reused
    assert (
        uses[1].delivery_binding_digest
        == uses[2].delivery_binding_digest
        == second_marker[4]
    )
    assert uses[1].used_at < uses[2].used_at
    monkeypatch.setattr(ParserBuildChecks, "current", lambda self: v.build)
    original = issuer(v.c, second)
    refs = require_parser_action_evidence(
        original, artifacts=v.c.artifacts, delivery_revision="e" * 40
    )
    assert any(
        identity.startswith("sec-parser-action-delivery-v2:") for identity, _ in refs
    )
    with pytest.raises(SnapshotError, match="delivery binding differs"):
        require_parser_action_evidence(
            original, artifacts=v.c.artifacts, delivery_revision="d" * 40
        )
    monkeypatch.setattr(
        ParserBuildChecks,
        "current",
        lambda self: v.build.model_copy(update={"runtime_digest": "0" * 64}),
    )
    with pytest.raises(SnapshotError, match="delivery binding differs"):
        require_parser_action_evidence(
            original, artifacts=v.c.artifacts, delivery_revision="e" * 40
        )


def test_v2_independent_verifier_cannot_use_unestablished_build(tmp_path, monkeypatch):
    from fundamental_service.parser_action_identity import (
        ParserBuildChecks,
        IncompleteParserClosure,
    )

    v = cross_delivery_case(tmp_path)
    original = issuer(v.c, v.run())

    def unavailable(self):
        raise IncompleteParserClosure("writable runtime")

    monkeypatch.setattr(ParserBuildChecks, "current", unavailable)
    with pytest.raises(SnapshotError, match="current parser build is unavailable"):
        require_parser_action_evidence(
            original, artifacts=v.c.artifacts, delivery_revision="d" * 40
        )


def test_v2_use_attestation_revocation_and_bytes_are_checked_at_output(
    tmp_path, monkeypatch
):
    from fundamental_service.parser_action_identity import ParserBuildChecks
    from fundamental_service.parser_action_contracts import parser_action_markers
    from fundamental_service.parser_action_evidence import (
        require_current_parser_action_refs,
    )
    from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError

    v = cross_delivery_case(tmp_path)
    original = issuer(v.c, v.run())
    monkeypatch.setattr(ParserBuildChecks, "current", lambda self: v.build)
    consumed = require_parser_action_evidence(
        original, artifacts=v.c.artifacts, delivery_revision="d" * 40
    )
    refs = tuple(
        ArtifactRefV1(
            artifact_id=i,
            content_hash=r.content_hash,
            media_type=r.media_type,
            role=i.split(":", 1)[0],
        )
        for i, r in consumed
    )
    require_current_parser_action_refs(refs, artifacts=v.c.artifacts)
    use = next(i for i, _ in consumed if i.startswith("sec-parser-action-delivery-v2:"))
    v.c.artifacts.invalidate(use)
    with pytest.raises(DataReleaseError, match="exact valid retained"):
        require_current_parser_action_refs(refs, artifacts=v.c.artifacts)
    assert parser_action_markers(original.report.execution_evidence)


def test_build_scope_hashes_once_but_rejects_configuration_changes(
    tmp_path, monkeypatch
):
    import fundamental_service.parser_action_identity as identity

    configuration = ["first"]
    calls = []
    monkeypatch.setattr(
        identity, "_immutable_build_configuration", lambda: (configuration[0], ())
    )
    monkeypatch.setattr(identity, "_files", lambda path: (("code.py", "1" * 64),))

    def runtime(**kwargs):
        calls.append(True)
        return "2" * 64

    monkeypatch.setattr(identity, "_runtime_identity", runtime)
    scope = identity.ParserBuildChecks()
    first = scope.current()
    assert scope.current() == first and len(calls) == 1
    configuration[0] = "changed-imports-or-mounts"
    with pytest.raises(identity.IncompleteParserClosure, match="configuration changed"):
        scope.verify()
    assert len(calls) == 1


def test_runtime_build_refuses_external_mount_inside_image_closure(tmp_path):
    from fundamental_service.parser_action_identity import IncompleteParserClosure

    (tmp_path / "package").mkdir()
    (tmp_path / "package" / "code.py").write_text("content")
    with pytest.raises(IncompleteParserClosure, match="escapes the immutable image"):
        _runtime_tree(tmp_path, set(), {}, image_mounts=(tmp_path / "package",))


@pytest.mark.parametrize(
    "marker",
    (
        "sec-parser-action-v3:normalized:" + "1" * 64 + ":" + "2" * 64,
        "sec-parser-action-v2:normalized:" + "1" * 64 + ":" + "2" * 64,
    ),
)
def test_unknown_or_incomplete_action_protocol_is_rejected(marker):
    from fundamental_service.parser_action_contracts import parser_action_markers

    with pytest.raises(ValueError):
        parser_action_markers((marker,))


@pytest.mark.parametrize("failure", (None, "outside-root", "unknown", "bind-mount"))
def test_native_dependencies_must_resolve_into_hashed_immutable_image(
    tmp_path, monkeypatch, failure
):
    import fundamental_service.parser_native_closure as native

    inspector = tmp_path / "ldd"
    inspector.write_text("trusted image inspector")
    binary = tmp_path / "extension.so"
    header = bytearray(20)
    header[:4] = b"\x7fELF"
    header[4], header[5], header[16], header[18] = 2, 1, 3, 183
    binary.write_bytes(header)
    dependency = tmp_path / "library.so"
    dependency.write_text("already hashed native dependency")
    monkeypatch.setattr(native, "_INSPECTOR", inspector)
    monkeypatch.setattr(native, "_cache_paths", lambda *args: ())
    monkeypatch.setattr(native.sys, "executable", str(binary))
    monkeypatch.setattr(native, "_search_paths", lambda path: ())
    output = "libexample.so => " + str(dependency) + " (0x1234)"
    if failure == "unknown":
        output = "unrecognized loader output"
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout=output, returncode=0),
    )
    hashed = {p: "1" * 64 for p in (inspector, binary, dependency)}
    if failure == "outside-root":
        del hashed[dependency]
    mounts = (dependency,) if failure == "bind-mount" else ()
    if failure:
        with pytest.raises(native.NativeClosureError):
            native.native_closure(hashed, mounts)
    else:
        assert native.native_closure(hashed, mounts) == (
            ("loader-cache-paths", ()),
            (str(binary), (str(dependency),)),
        )


@pytest.mark.parametrize(
    "configuration",
    ("writable-root", "capability", "privilege-escalation", "external-catalog"),
)
def test_v2_requires_kernel_enforced_immutable_execution_boundary(
    monkeypatch, configuration
):
    import os
    from pathlib import Path
    import fundamental_service.parser_action_identity as identity

    monkeypatch.setattr(identity.sys, "platform", "linux")
    monkeypatch.setattr(identity.os, "geteuid", lambda: 10001)
    status = "CapEff: 0\nCapPrm: 0\nCapAmb: 0\nNoNewPrivs: 1\n"
    if configuration == "capability":
        status = status.replace("CapEff: 0", "CapEff: 1")
    if configuration == "privilege-escalation":
        status = status.replace("NoNewPrivs: 1", "NoNewPrivs: 0")
    mount = "1 0 0:1 / / ro - overlay overlay ro\n"
    original = Path.read_text

    def read(path, *args, **kwargs):
        if str(path) == "/proc/self/status":
            return status
        if str(path) == "/proc/self/mountinfo":
            return mount
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(
        identity.os,
        "statvfs",
        lambda path: SimpleNamespace(
            f_flag=0 if configuration == "writable-root" else os.ST_RDONLY
        ),
    )
    if configuration == "external-catalog":
        monkeypatch.setenv("XML_CATALOG_FILES", "/untrusted/catalog")
    with pytest.raises(identity.IncompleteParserClosure):
        identity._immutable_build_configuration()


def test_elf_loader_search_paths_are_decoded_from_dynamic_table(tmp_path):
    import struct
    from fundamental_service.parser_native_closure import _search_paths

    binary = tmp_path / "extension.so"
    raw = bytearray(512)
    raw[:4], raw[4], raw[5] = b"\x7fELF", 2, 1
    struct.pack_into("<Q", raw, 32, 64)
    struct.pack_into("<HH", raw, 54, 56, 2)
    struct.pack_into("<IIQQQQQQ", raw, 64, 1, 5, 0, 0, 0, 512, 512, 4096)
    struct.pack_into("<IIQQQQQQ", raw, 120, 2, 6, 256, 256, 256, 64, 64, 8)
    struct.pack_into("<qQqQqQ", raw, 256, 5, 384, 29, 0, 0, 0)
    value = b"$ORIGIN/../libs:/usr/lib\0"
    raw[384 : 384 + len(value)] = value
    binary.write_bytes(raw)
    assert _search_paths(binary) == ((tmp_path / "../libs").resolve(), Path("/usr/lib"))
    binary.write_bytes(b"\x7fELF\x02\x01")
    from fundamental_service.parser_native_closure import NativeClosureError

    with pytest.raises(NativeClosureError):
        _search_paths(binary)


@pytest.mark.parametrize("search", ("/tmp", "/usr/mounted", "/usr/lib"))
def test_missing_native_dependency_requires_fixed_search_roots(
    tmp_path, monkeypatch, search
):
    import fundamental_service.parser_native_closure as native

    inspector, binary = tmp_path / "ldd", tmp_path / "binary"
    inspector.write_bytes(b"trusted loader")
    header = bytearray(20)
    header[:4], header[4], header[5], header[16], header[18] = b"\x7fELF", 2, 1, 3, 183
    binary.write_bytes(header)
    monkeypatch.setattr(native, "_INSPECTOR", inspector)
    monkeypatch.setattr(native, "_cache_paths", lambda *args: ())
    monkeypatch.setattr(native.sys, "executable", str(binary))
    monkeypatch.setattr(native, "_search_paths", lambda path: (Path(search),))
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            stdout="liboptional.so => not found", returncode=0
        ),
    )
    hashed = {path: "1" * 64 for path in (inspector, binary)}
    if search == "/usr/lib":
        assert native.native_closure(hashed, ()) == (
            ("loader-cache-paths", ()),
            (str(binary), ("liboptional.so => not found",)),
        )
    else:
        with pytest.raises(native.NativeClosureError):
            native.native_closure(hashed, (Path("/usr/mounted"),))


@pytest.mark.parametrize("destination", ("/usr/lib/libx.so", "/opt/libx.so"))
def test_loader_cache_cannot_reference_external_missing_libraries(
    tmp_path, monkeypatch, destination
):
    import fundamental_service.parser_native_closure as native

    inspector = tmp_path / "ldconfig"
    inspector.write_bytes(b"fixed inspector")
    monkeypatch.setattr(native, "_CACHE_INSPECTOR", inspector)
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=0,
            stdout=f"1 libs found in cache `/etc/ld.so.cache'\n libx.so (libc6) => {destination}\nCache generated by: ldconfig\n",
        ),
    )
    if destination.startswith("/opt"):
        with pytest.raises(native.NativeClosureError):
            native._cache_paths({inspector: "1" * 64}, ())
    else:
        assert native._cache_paths({inspector: "1" * 64}, ()) == (destination,)


def test_final_action_boundary_rechecks_build_after_slow_content_io(
    tmp_path, monkeypatch
):
    from fundamental_service.parser_action_identity import (
        ParserBuildChecks,
        IncompleteParserClosure,
    )
    from fundamental_service.parser_action_evidence import (
        require_current_parser_action_refs,
    )
    from fundamental_service.data_releases import ArtifactRefV1

    v = cross_delivery_case(tmp_path)
    original = issuer(v.c, v.run())
    changed = [False]

    def current(self):
        if changed[0]:
            raise IncompleteParserClosure("mount changed during content read")
        self._build = v.build
        return v.build

    monkeypatch.setattr(ParserBuildChecks, "current", current)
    records = require_parser_action_evidence(
        original, artifacts=v.c.artifacts, delivery_revision="d" * 40
    )
    refs = tuple(
        ArtifactRefV1(
            artifact_id=i,
            content_hash=r.content_hash,
            media_type=r.media_type,
            role=i.split(":", 1)[0],
        )
        for i, r in records
    )
    read = v.c.artifacts.read

    def slow(identity):
        raw = read(identity)
        if identity.startswith("sec-parser-action-delivery-v2:"):
            changed[0] = True
        return raw

    monkeypatch.setattr(v.c.artifacts, "read", slow)
    with pytest.raises(IncompleteParserClosure):
        require_current_parser_action_refs(refs, artifacts=v.c.artifacts)
