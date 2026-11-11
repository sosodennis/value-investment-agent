"""Representation equality must preserve financial content and original evidence."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from audit_history_source_integrity import canonical_xml, read_source

INSTANCE = b"""<?xml version="1.0"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"><!-- & -->
<fact xmlns="urn:fixture">100</fact></xbrl>"""


def test_canonical_relation_covers_only_xml_representation_changes() -> None:
    direct = INSTANCE.replace(b"<!-- & -->", b"<!-- &amp; -->")
    archive = INSTANCE.replace(b"\n", b"\r\n")
    assert canonical_xml(direct) == canonical_xml(archive)
    assert canonical_xml(INSTANCE.replace(b">100<", b">101<")) != canonical_xml(
        INSTANCE
    )
    assert canonical_xml(INSTANCE.replace(b">100<", b"> 100<")) != canonical_xml(
        INSTANCE
    )


@pytest.mark.parametrize(
    "content",
    [
        INSTANCE.replace(b'<?xml version="1.0"?>', b'<?xml version="1.1"?>'),
        INSTANCE.replace(b"<xbrl ", b"<!DOCTYPE xbrl><xbrl "),
        b"<html/>",
    ],
)
def test_noncovered_documents_remain_unresolved(content: bytes) -> None:
    with pytest.raises(ValueError):
        canonical_xml(content)


def test_source_hash_mismatch_is_retained_as_failure(tmp_path: Path) -> None:
    hash_value = "a" * 64
    (tmp_path / "aa").mkdir()
    (tmp_path / "aa" / (hash_value + ".bin")).write_bytes(b"wrong")
    with pytest.raises(ValueError, match="hash mismatch"):
        read_source(tmp_path, {"content_hash": hash_value, "media_type": "text/xml"})
