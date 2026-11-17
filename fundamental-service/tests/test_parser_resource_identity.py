"""One resource read preserves both existing parser dependency identities."""

import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fundamental_service.arelle_parser import _directory_hash
from fundamental_service.parser_action_identity import (
    IncompleteParserClosure,
    _files,
    _resource_digests,
)
from fundamental_service.serialization import sha256_digest
from fundamental_service.snapshots import SnapshotError
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
