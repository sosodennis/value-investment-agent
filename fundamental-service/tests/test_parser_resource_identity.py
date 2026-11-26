"""One resource read preserves both existing parser dependency identities."""

import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from functools import partial

import pytest

from fundamental_service.arelle_parser import _directory_hash
from fundamental_service.parser_action_identity import (
    IncompleteParserClosure,
    _files,
    _resource_digests,
)
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.resource_hashing import ResourceHashReader
from test_parser_actions import case


def resource_tree(root):
    contents = {
        "a.xml": b"root",
        "a/z.xml": b"nested",
        "empty": b"",
        "large.xml": b"x" * (2 * 1024 * 1024 + 1),
        "generated.pyc/data.xml": b"directory suffix is not a leaf exclusion",
        "__pycache__/ignored.xml": b"excluded from raw digest only",
        "__pycache__/ignored.pyc": b"compiled",
        "ignored.pyo": b"optimized",
        "unicode/\u8cc7\u6599.xml": b"unicode name",
    }
    for name, raw in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (root / "empty-directory").mkdir()
    return contents


def test_one_read_preserves_both_resource_digests_and_their_distinct_orders(
    tmp_path, monkeypatch
):
    contents = resource_tree(tmp_path)
    monkeypatch.setattr(
        "fundamental_service.parser_action_identity.ResourceHashReader",
        partial(ResourceHashReader, direct=False),
    )
    assert sorted((Path("a.xml"), Path("a/z.xml"))) != [
        Path(name) for name in sorted(("a.xml", "a/z.xml"))
    ]
    expected = _directory_hash(tmp_path), sha256_digest(_files(tmp_path))
    opened = Counter()
    original = Path.open

    def open_file(path, *args, **kwargs):
        opened[path.relative_to(tmp_path).as_posix()] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    assert _resource_digests(tmp_path) == expected
    assert opened == Counter({name: 1 for name in contents})


@pytest.mark.parametrize(
    "name", ("__pycache__/ignored.xml", "__pycache__/ignored.pyc", "ignored.pyo")
)
def test_bytecode_exclusions_remain_part_of_the_complete_closure(tmp_path, name):
    resource_tree(tmp_path)
    before = _resource_digests(tmp_path)
    (tmp_path / name).write_bytes(b"changed")
    after = _resource_digests(tmp_path)
    assert before[0] == after[0]
    assert before[1] != after[1]
    assert after == (_directory_hash(tmp_path), sha256_digest(_files(tmp_path)))


def test_same_bytes_under_another_mount_keep_both_identities(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    resource_tree(first)
    resource_tree(second)
    assert _resource_digests(first) == _resource_digests(second)
    (second / "generated.pyc/data.xml").write_bytes(b"changed")
    assert all(
        a != b for a, b in zip(_resource_digests(first), _resource_digests(second))
    )


def test_hard_links_remain_separate_named_dependencies(tmp_path):
    resource_tree(tmp_path)
    (tmp_path / "alias.xml").hardlink_to(tmp_path / "a.xml")
    assert _resource_digests(tmp_path) == (
        _directory_hash(tmp_path),
        sha256_digest(_files(tmp_path)),
    )


def test_file_replaced_after_enumeration_is_rechecked_before_read(
    tmp_path, monkeypatch
):
    import fundamental_service.parser_action_identity as identity

    resource_tree(tmp_path)
    original = identity._regular_files

    def replaced(root):
        yield from original(root)
        path = root / "a.xml"
        path.unlink()
        path.symlink_to(root / "a/z.xml")

    monkeypatch.setattr(identity, "_regular_files", replaced)
    with pytest.raises(IncompleteParserClosure, match="symlinked"):
        _resource_digests(tmp_path)


@pytest.mark.parametrize("kind", ("root-link", "file-link", "directory-link", "fifo"))
def test_unsupported_nodes_refuse_even_in_raw_hash_exclusions(tmp_path, kind):
    resource_tree(tmp_path)
    root = tmp_path
    if kind == "root-link":
        root = tmp_path / "link"
        root.symlink_to(tmp_path, target_is_directory=True)
    else:
        path = tmp_path / "__pycache__" / "invalid"
        if kind == "file-link":
            path.symlink_to(tmp_path / "a.xml")
        elif kind == "directory-link":
            path.symlink_to(tmp_path / "a", target_is_directory=True)
        else:
            os.mkfifo(path)
    with pytest.raises(IncompleteParserClosure):
        _resource_digests(root)


@pytest.mark.parametrize("operation", ("open", "iterdir"))
def test_resource_read_or_enumeration_failure_never_omits_dependencies(
    tmp_path, monkeypatch, operation
):
    resource_tree(tmp_path)
    monkeypatch.setattr(
        "fundamental_service.parser_action_identity.ResourceHashReader",
        partial(ResourceHashReader, direct=False),
    )
    target = tmp_path / "__pycache__"
    if operation == "open":
        target /= "ignored.xml"
    original = getattr(Path, operation)

    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError("unreadable resource")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, operation, denied)
    with pytest.raises(PermissionError, match="unreadable resource"):
        _resource_digests(tmp_path)


@pytest.mark.parametrize("name", ("a.xml", "__pycache__/ignored.pyc"))
def test_resource_change_during_parser_execution_prevents_result_publication(
    tmp_path, name
):
    owner = case(tmp_path / "owner")
    resources = tmp_path / "resources"
    resource_tree(resources)

    def request():
        raw, closure = _resource_digests(resources)
        return owner.request.model_copy(
            update={
                "resources": (
                    *owner.request.resources,
                    ("fixture", raw),
                    ("fixture-closure", closure),
                )
            }
        )

    def execute():
        (resources / name).write_bytes(b"changed while parsing")
        return owner.execute()

    with pytest.raises(SnapshotError) as error:
        owner.owner._perform(
            request=request(),
            profile=owner.profile,
            deadline_at=datetime.now(UTC) + timedelta(seconds=10),
            execute=execute,
            check_inputs=request,
        )
    assert error.value.code == "PARSER_ACTION_DEPENDENCY_CHANGED"
    assert not owner.index.results and not owner.index.held


def resource_action_case(tmp_path, monkeypatch):
    import fundamental_service.parser_action_identity as identity
    from fundamental_service.parser_action_contracts import ParserBuildIdentityV1
    from types import SimpleNamespace
    import hashlib

    build = ParserBuildIdentityV1(
        implementation_digest="1" * 64,
        runtime_digest="2" * 64,
        output_schema_digest="3" * 64,
    )
    monkeypatch.setattr(identity.ParserBuildChecks, "current", lambda self: build)
    for name in ("taxonomy", "edgar", "xule", "filing"):
        (tmp_path / name).mkdir(parents=True)
        (tmp_path / name / "content").write_bytes(b"fixed bytes")
    rules = tmp_path / "rules.zip"
    rules.write_bytes(b"fixed rules")
    profile = case(tmp_path / "case").profile.model_copy(
        update={
            "edgar_plugin_dir": tmp_path / "edgar",
            "xule_plugin_dir": tmp_path / "xule",
            "dqc_ruleset_path": rules,
        }
    )
    arguments = dict(
        representation="normalized",
        delivery_revision="d" * 40,
        normalization_inputs=("2" * 64,),
        profile=profile,
        taxonomy_version="2025",
        taxonomy_cache_dir=tmp_path / "taxonomy",
        source_content_hash=hashlib.sha256(b"fixed bytes").hexdigest(),
        build_checks=identity.ParserBuildChecks(),
    )

    def request(**changes):
        return identity.parser_action_input(
            tmp_path / "filing/content", **{**arguments, **changes}
        )

    return SimpleNamespace(**locals())


def test_candidate_resource_operation_preserves_wire_and_reads_first_and_final_bytes(
    tmp_path, monkeypatch
):
    from fundamental_service.parser_action_identity import _ParserResourceOperation

    c = resource_action_case(tmp_path, monkeypatch)
    expected = c.request()
    opened = Counter()
    original = Path.open

    def observed(path, *args, **kwargs):
        opened[path] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed)
    with _ParserResourceOperation(lambda: 60.0) as owner:
        assert c.request() == expected
        assert c.request() == expected
        assert opened[c.rules] == 1
        owner.finish()
        assert opened[c.rules] == 2
        assert owner._state.high_water_keys == 1
        assert 0 < owner._state.high_water_bytes <= 2 * 1024 * 1024
        with pytest.raises(IncompleteParserClosure, match="not current"):
            c.request()


@pytest.mark.parametrize(
    "mutation", ("same-length", "membership", "logical-file", "symlink")
)
def test_candidate_terminal_scan_refuses_changed_consumed_resources(
    tmp_path, monkeypatch, mutation
):
    from fundamental_service.parser_action_identity import _ParserResourceOperation

    c = resource_action_case(tmp_path, monkeypatch)
    with pytest.raises((IncompleteParserClosure, OSError)):
        with _ParserResourceOperation(lambda: 60.0) as owner:
            first = c.request()
            if mutation == "same-length":
                (tmp_path / "taxonomy/content").write_bytes(b"other bytes")
            elif mutation == "membership":
                (tmp_path / "taxonomy/added").write_bytes(b"new")
            elif mutation == "logical-file":
                c.rules.write_bytes(b"other rules")
            else:
                (tmp_path / "taxonomy/content").unlink()
                (tmp_path / "taxonomy/content").symlink_to(c.rules)
            assert c.request() == first
            owner.finish()


def test_explicit_current_and_v1_remain_fresh_inside_candidate_operation(
    tmp_path, monkeypatch
):
    from fundamental_service.parser_action_identity import (
        _ParserResourceOperation,
        parser_action_resources,
    )

    c = resource_action_case(tmp_path, monkeypatch)
    with pytest.raises(IncompleteParserClosure, match="bytes changed"):
        with _ParserResourceOperation(lambda: 60.0):
            c.request()
            c.rules.write_bytes(b"other rules")
            parser_action_resources(c.profile, tmp_path / "taxonomy")
    monkeypatch.setattr(c.identity, "_runtime_identity", lambda: "4" * 64)
    expected = c.request(build_checks=None)
    with _ParserResourceOperation(lambda: 60.0) as owner:
        assert c.request(build_checks=None) == expected
        owner.finish()
    with pytest.raises(IncompleteParserClosure, match="bytes changed"):
        with _ParserResourceOperation(lambda: 60.0):
            c.request(build_checks=None)
            c.rules.write_bytes(b"newer rules")
            c.request(build_checks=None)


def test_resource_operations_are_fresh_nested_isolated_and_cleanup_on_error(
    tmp_path, monkeypatch
):
    from fundamental_service.parser_action_identity import (
        _ParserResourceOperation,
        _RESOURCE_OPERATION,
    )
    import asyncio

    c = resource_action_case(tmp_path, monkeypatch)
    with _ParserResourceOperation(lambda: 60.0) as owner:
        first = c.request()
        borrow = _RESOURCE_OPERATION.get()
        assert not hasattr(borrow, "finish")
        with _ParserResourceOperation(lambda: 60.0) as nested:
            assert c.request() == first
            assert _RESOURCE_OPERATION.get() is not borrow
            nested.finish()
        assert _RESOURCE_OPERATION.get() is borrow
        owner.finish()
    assert _RESOURCE_OPERATION.get() is None
    c.rules.write_bytes(b"other rules")
    with _ParserResourceOperation(lambda: 60.0) as owner:
        assert c.request() != first
        owner.finish()
    with pytest.raises(IncompleteParserClosure, match="did not finish"):
        with _ParserResourceOperation(lambda: 60.0):
            c.request()
    with pytest.raises(asyncio.CancelledError):
        with _ParserResourceOperation(lambda: 60.0):
            c.request()
            raise asyncio.CancelledError()
    assert _RESOURCE_OPERATION.get() is None
    assert c.request() != first
    with pytest.raises(IncompleteParserClosure, match="cannot reopen"):
        with owner:
            pass


@pytest.mark.parametrize(
    "identity", ("pid", "thread", "task", "principal", "configuration", "build")
)
def test_candidate_resource_borrow_refuses_changed_execution_identity(
    tmp_path, monkeypatch, identity
):
    from fundamental_service.parser_action_identity import _ParserResourceOperation

    c = resource_action_case(tmp_path, monkeypatch)
    with pytest.raises(IncompleteParserClosure):
        with _ParserResourceOperation(lambda: 60.0):
            c.request()
            if identity == "pid":
                monkeypatch.setattr(c.identity.os, "getpid", lambda: -1)
            elif identity == "thread":
                monkeypatch.setattr(c.identity, "get_ident", lambda: -1)
            elif identity == "task":
                monkeypatch.setattr(c.identity, "current_task", lambda: object())
            elif identity == "principal":
                monkeypatch.setattr(c.identity.os, "geteuid", lambda: -1)
            elif identity == "configuration":
                c.arguments["build_checks"]._configuration = "changed"
            else:
                monkeypatch.setattr(
                    c.identity.ParserBuildChecks,
                    "current",
                    lambda self: c.build.model_copy(
                        update={"runtime_digest": "9" * 64}
                    ),
                )
            c.request()


def test_copied_async_context_cannot_borrow_parent_resource_operation(
    tmp_path, monkeypatch
):
    import asyncio
    from fundamental_service.parser_action_identity import _ParserResourceOperation

    c = resource_action_case(tmp_path, monkeypatch)

    async def child():
        c.request()

    async def parent():
        with _ParserResourceOperation(lambda: 60.0) as owner:
            first = c.request()
            with pytest.raises(IncompleteParserClosure, match="not current"):
                await asyncio.create_task(child())
            assert c.request() == first
            owner.finish()

    asyncio.run(parent())


def test_candidate_resource_finish_preserves_original_deadline_error(
    tmp_path, monkeypatch
):
    from fundamental_service.parser_action_identity import _ParserResourceOperation

    c = resource_action_case(tmp_path, monkeypatch)
    expired = False
    error = SnapshotError("REQUEST_DEADLINE_EXCEEDED", "original deadline")

    def budget():
        if expired:
            raise error
        return 60.0

    with pytest.raises(SnapshotError) as caught:
        with _ParserResourceOperation(budget) as owner:
            c.request()
            expired = True
            owner.finish()
    assert caught.value is error


@pytest.mark.parametrize("bound", ("keys", "bytes"))
def test_candidate_resource_union_refuses_overflow_without_dropping_keys(
    tmp_path, monkeypatch, bound
):
    from fundamental_service.parser_action_identity import _ParserResourceOperation

    c = resource_action_case(tmp_path, monkeypatch)
    with pytest.raises(IncompleteParserClosure, match="exceeds its bounds"):
        with _ParserResourceOperation(lambda: 60.0) as owner:
            if bound == "keys":
                for index in range(33):
                    c.request(
                        profile=c.profile.model_copy(update={"profile_id": str(index)})
                    )
            else:
                c.request(
                    profile=c.profile.model_copy(
                        update={"profile_id": "x" * (2 * 1024 * 1024)}
                    )
                )
    assert owner._state.observations == {}
