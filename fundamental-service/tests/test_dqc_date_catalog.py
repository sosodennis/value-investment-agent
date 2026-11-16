"""Offline catalog generation must prove exact official assertion/date bindings."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

builder = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "build_dqc_effective_dates.py")
)

SOURCE = """rule-name-prefix DQC
ASSERT US.0228.10921 satisfied
$rule_id = (rule-name().split('.'))[rule-name().split('.').length];
true
effectiveDate $effective_dates[$rule_id]
"""
RESOURCES = (
    "constant $effective_dates = dict(\nfor $pair in csv-data('"
    + builder["EFFECTIVE_DATES_URL"]
    + "', false, list('string','string'))\nlist($pair[1], $pair[2])\n)\n"
)


def _case(
    tmp_path,
    monkeypatch,
    *,
    source=SOURCE,
    table="10921,2026-06-01\n",
    resources=RESOURCES,
):
    sources = tmp_path / "sources"
    relative = "dqc_us_rules/source/us/2025/DQC_0228.xule"
    path = sources / relative
    path.parent.mkdir(parents=True)
    path.write_text(source)
    resource_path = path.with_name("resources.xule")
    resource_path.write_text(resources)
    dates = tmp_path / "dates.csv"
    dates.write_text(table)
    entries = []
    for name, raw in (
        (relative, path.read_bytes()),
        (relative.rsplit("/", 1)[0] + "/resources.xule", resource_path.read_bytes()),
        (builder["EFFECTIVE_DATES_PATH"], dates.read_bytes()),
    ):
        entries.append(
            {
                "path": name,
                "type": "blob",
                "mode": "100644",
                "sha": hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw
                ).hexdigest(),
            }
        )
    directories = {""}
    for entry in entries:
        parent = str(Path(entry["path"]).parent)
        while parent != ".":
            directories.add(parent)
            parent = str(Path(parent).parent)
    root = ""
    for parent in sorted(
        directories, key=lambda path: path.count("/") + bool(path), reverse=True
    ):
        children = [
            (entry["path"].rpartition("/")[2], entry)
            for entry in entries
            if entry["path"].rpartition("/")[0] == parent
        ]
        raw = b"".join(
            entry["mode"].lstrip("0").encode()
            + b" "
            + name.encode()
            + b"\0"
            + bytes.fromhex(entry["sha"])
            for name, entry in sorted(
                children,
                key=lambda pair: (
                    pair[0] + ("/" if pair[1]["type"] == "tree" else "")
                ).encode(),
            )
        )
        root = hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if parent:
            entries.append(
                {"path": parent, "type": "tree", "mode": "040000", "sha": root}
            )
    monkeypatch.setitem(
        builder["_verified_tree"].__globals__, "OFFICIAL_TREE_SHA", root
    )
    tree = tmp_path / "tree.json"
    tree.write_text(
        json.dumps(
            {"sha": builder["OFFICIAL_COMMIT"], "truncated": False, "tree": entries}
        )
    )
    return sources, dates, tree


def test_catalog_records_exact_assertion_and_both_official_sources(
    tmp_path, monkeypatch
):
    args = _case(tmp_path, monkeypatch)
    catalog = builder["build_assertion_table"](*args)
    assert catalog == builder["build_assertion_table"](*args)
    assert catalog["table_sha256"] == hashlib.sha256(args[1].read_bytes()).hexdigest()
    assert catalog["entries"] == [
        {
            "assertion_code": "DQC.US.0228.10921",
            "effective_date": "2026-06-01",
            "sources": [
                {
                    "path": "dqc_us_rules/source/us/2025/DQC_0228.xule",
                    "sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
                },
                {
                    "path": "dqc_us_rules/source/us/2025/resources.xule",
                    "sha256": hashlib.sha256(RESOURCES.encode()).hexdigest(),
                },
            ],
        }
    ]


@pytest.mark.parametrize("target", ["source", "table", "tree", "resources"])
def test_unpinned_sources_cannot_enter_catalog(tmp_path, monkeypatch, target):
    args = _case(tmp_path, monkeypatch)
    if target == "source":
        path = next(args[0].rglob("*.xule"))
        path.write_text(path.read_text() + "\n")
    elif target == "table":
        args[1].write_text("10921,2020-01-01\n")
    elif target == "resources":
        path = next(args[0].rglob("resources.xule"))
        path.write_text(path.read_text() + "\n")
    else:
        payload = json.loads(args[2].read_bytes())
        payload["truncated"] = True
        args[2].write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="pinned"):
        builder["build_assertion_table"](*args)


def test_self_declared_commit_cannot_authorize_forged_tree_content(
    tmp_path, monkeypatch
):
    args = _case(tmp_path, monkeypatch)
    payload = json.loads(args[2].read_bytes())
    next(item for item in payload["tree"] if item["type"] == "blob")["sha"] = "0" * 40
    args[2].write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="pinned official root"):
        builder["build_assertion_table"](*args)


def test_other_table_definition_cannot_authorize_assertion_date(tmp_path, monkeypatch):
    resources = RESOURCES.replace("effective_dates.csv", "different_dates.csv")
    with pytest.raises(ValueError, match="unsupported official date-table"):
        builder["build_assertion_table"](
            *_case(tmp_path, monkeypatch, resources=resources)
        )


@pytest.mark.parametrize(
    "table",
    [
        "10801,2026-06-01\n",
        "10921,2026-06-01\n10921,2026-06-02\n",
        "10921,UNKNOWN\n",
        "10921,2026-02-30\n",
    ],
)
def test_missing_conflicting_and_invalid_exact_dates_refuse(
    tmp_path, monkeypatch, table
):
    with pytest.raises(ValueError):
        builder["build_assertion_table"](*_case(tmp_path, monkeypatch, table=table))


@pytest.mark.parametrize(
    "source",
    [
        SOURCE.replace("US.0228.10921", "US.0238.10921"),
        SOURCE.replace("rule-name-prefix DQC", "rule-name-prefix OTHER"),
        SOURCE.replace("ASSERT", "ASSERT US.0228.10000 satisfied\nASSERT"),
        SOURCE.replace("$effective_dates[$rule_id]", '"2026-06-01"'),
        SOURCE.replace("rule-name().split('.')", "other_rule_name().split('.')"),
    ],
)
def test_table_date_requires_supported_exact_xule_binding(
    tmp_path, monkeypatch, source
):
    with pytest.raises(ValueError, match="unsupported exact"):
        builder["build_assertion_table"](*_case(tmp_path, monkeypatch, source=source))
