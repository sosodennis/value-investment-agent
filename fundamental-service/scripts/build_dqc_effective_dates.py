"""Derive exact assertion dates from retained, pinned official DQC documents."""

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path

OFFICIAL_COMMIT = "cd82706519e384fb209d74f13ccbe535be42da4b"
OFFICIAL_TREE_SHA = "7b0c7a372dcaf1f2e468ff5edfcb3908ab139841"
EFFECTIVE_DATES_PATH = "dqc_us_rules/resources/Effective_Dates/effective_dates.csv"
EFFECTIVE_DATES_URL = (
    "https://raw.githubusercontent.com/DataQualityCommittee/dqc_us_rules/v31/"
    + EFFECTIVE_DATES_PATH
)


def _verified_tree(tree_path: Path) -> dict[str, str]:
    tree = json.loads(tree_path.read_bytes())
    if (
        tree.get("sha") not in {OFFICIAL_COMMIT, OFFICIAL_TREE_SHA}
        or tree.get("truncated") is not False
    ):
        raise ValueError("complete Git tree must match the pinned official commit")
    entries = {item["path"]: item for item in tree["tree"]}
    if len(entries) != len(tree["tree"]):
        raise ValueError("pinned Git tree cannot contain duplicate paths")
    children: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for path, item in entries.items():
        if (
            path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\0" in path
            or (item["type"], item["mode"])
            not in {
                ("tree", "040000"),
                ("blob", "100644"),
                ("blob", "100755"),
                ("blob", "120000"),
                ("commit", "160000"),
            }
            or not re.fullmatch(r"[0-9a-f]{40}", item["sha"])
        ):
            raise ValueError("invalid pinned Git tree entry")
        parent, _, name = path.rpartition("/")
        if parent and entries.get(parent, {}).get("type") != "tree":
            raise ValueError("pinned Git tree is missing a parent tree")
        children.setdefault(parent, []).append((name, item))
    for parent in ("", *(p for p, item in entries.items() if item["type"] == "tree")):
        raw = b"".join(
            item["mode"].lstrip("0").encode()
            + b" "
            + name.encode()
            + b"\0"
            + bytes.fromhex(item["sha"])
            for name, item in sorted(
                children.get(parent, []),
                key=lambda pair: (
                    pair[0] + ("/" if pair[1]["type"] == "tree" else "")
                ).encode(),
            )
        )
        actual = hashlib.sha1(
            b"tree " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        expected = entries[parent]["sha"] if parent else OFFICIAL_TREE_SHA
        if actual != expected:
            raise ValueError("Git tree contents differ from the pinned official root")
    return {
        item["path"]: item["sha"] for item in tree["tree"] if item.get("type") == "blob"
    }


def _read_verified(path: Path, source: str, tree: dict[str, str]) -> bytes:
    raw = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != tree.get(source):
        raise ValueError(f"source differs from pinned Git tree: {source}")
    return raw


def build_assertion_table(
    sources: Path, effective_dates: Path, tree_path: Path
) -> dict[str, object]:
    """Bind single-assertion XULE rules to their exact official table entries."""

    tree = _verified_tree(tree_path)
    table = _read_verified(effective_dates, EFFECTIVE_DATES_PATH, tree)
    dates: dict[str, set[str]] = {}
    for row in csv.reader(io.StringIO(table.decode("utf-8-sig"))):
        if len(row) == 2 and re.fullmatch(r"[0-9]+", row[0]):
            dates.setdefault(row[0], set()).add(row[1])
    entries: dict[str, dict[str, object]] = {}
    for path in sorted(sources.rglob("DQC_*.xule")):
        source = path.relative_to(sources).as_posix()
        match = re.fullmatch(
            r"dqc_us_rules/source/us/202[3-6]/DQC_([0-9]{4})\.xule", source
        )
        if match is None:
            raise ValueError(f"unsupported assertion source path: {source}")
        raw = _read_verified(path, source, tree)
        text = raw.decode()
        resources_path = path.with_name("resources.xule")
        resources_source = resources_path.relative_to(sources).as_posix()
        resources = _read_verified(resources_path, resources_source, tree)
        definition = (
            "constant$effective_dates=dict(for$pairincsv-data('"
            + EFFECTIVE_DATES_URL
            + "',false,list('string','string'))list($pair[1],$pair[2]))"
        )
        if definition not in re.sub(r"\s+", "", resources.decode()):
            raise ValueError(f"unsupported official date-table definition: {source}")
        assertions = re.findall(r"^ASSERT\s+(\S+)", text, re.MULTILINE)
        if (
            len(assertions) != 1
            or not re.fullmatch(rf"US\.{match[1]}\.[0-9]+", assertions[0])
            or not re.search(r"^rule-name-prefix DQC\s*$", text, re.MULTILINE)
            or "$rule_id = (rule-name().split('.'))[rule-name().split('.').length];"
            not in text
            or not re.search(
                r"^effectiveDate \$effective_dates\[\$rule_id\]\s*$",
                text,
                re.MULTILINE,
            )
        ):
            raise ValueError(f"unsupported exact assertion/date binding: {source}")
        code = "DQC." + assertions[0]
        values = dates.get(code.rsplit(".", 1)[1], set())
        if len(values) != 1:
            raise ValueError(f"missing or conflicting official dates: {code}")
        value = next(iter(values))
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError(f"invalid official date: {code}")
        effective_date = datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        entry = entries.setdefault(
            code,
            {"assertion_code": code, "effective_date": effective_date, "sources": []},
        )
        refs = entry["sources"]
        assert isinstance(refs, list)
        for name, content in ((source, raw), (resources_source, resources)):
            reference = {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
            if reference not in refs:
                refs.append(reference)
    if not entries:
        raise ValueError("no exact assertion/table bindings found")
    return {
        "protocol": "dqc-official-assertion-date-table-v1",
        "dqc_version": "v31.0.3",
        "official_commit": OFFICIAL_COMMIT,
        "git_tree_sha": OFFICIAL_TREE_SHA,
        "table_path": EFFECTIVE_DATES_PATH,
        "table_sha256": hashlib.sha256(table).hexdigest(),
        "entries": [entries[code] for code in sorted(entries)],
    }


def build_catalog(documents: Path, tree_path: Path) -> dict[str, object]:
    verified = _verified_tree(tree_path)
    tree = json.loads(tree_path.read_bytes())
    if tree.get("sha") != OFFICIAL_COMMIT or tree.get("truncated") is not False:
        raise ValueError("complete Git tree must match the pinned official commit")
    entries = []
    for item in sorted(tree["tree"], key=lambda item: item["path"]):
        source = item["path"]
        if not re.fullmatch(r"docs/DQC_US_[0-9]{4}/DQC_[0-9]{4}\.md", source):
            continue
        raw = _read_verified(documents / Path(source).name, source, verified)
        header = raw.decode().split("##", 1)[0]
        rule = re.search(r"^Rule ID:\s*(.+)$", header, re.MULTILINE)
        dates = re.findall(
            r"^Effective date:\s*([A-Za-z]+ [0-9]{1,2}, [0-9]{4})\s*$",
            header,
            re.MULTILINE,
        )
        codes = re.findall(r"DQC\.US\.[0-9]{4}\.[0-9]+", rule[1] if rule else "")
        if (
            not codes
            or len(dates) != 1
            or not re.search(r"^Status:\s*Final\s*$", header, re.MULTILINE)
        ):
            continue
        entries.append(
            {
                "assertion_codes": sorted(set(codes)),
                "effective_date": datetime.strptime(dates[0], "%B %d, %Y")
                .date()
                .isoformat(),
                "document_path": source,
                "document_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if not entries:
        raise ValueError("no explicit final assertion dates found")
    return {
        "protocol": "dqc-official-assertion-effective-dates-v1",
        "dqc_version": "v31.0.3",
        "official_commit": OFFICIAL_COMMIT,
        "git_tree_sha": tree["sha"],
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--documents", type=Path)
    inputs.add_argument("--rule-sources", type=Path)
    parser.add_argument("--effective-dates", type=Path)
    parser.add_argument("--git-tree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.rule_sources is not None:
        if arguments.effective_dates is None:
            parser.error("--rule-sources requires --effective-dates")
        catalog = build_assertion_table(
            arguments.rule_sources, arguments.effective_dates, arguments.git_tree
        )
    else:
        if arguments.effective_dates is not None:
            parser.error("--effective-dates requires --rule-sources")
        catalog = build_catalog(arguments.documents, arguments.git_tree)
    raw = (json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n").encode()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(raw)
    print(hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
