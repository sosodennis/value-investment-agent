"""Derive exact assertion dates from retained, pinned official DQC documents."""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

OFFICIAL_COMMIT = "cd82706519e384fb209d74f13ccbe535be42da4b"


def build_catalog(documents: Path, tree_path: Path) -> dict[str, object]:
    tree = json.loads(tree_path.read_bytes())
    if tree.get("sha") != OFFICIAL_COMMIT or tree.get("truncated") is not False:
        raise ValueError("complete Git tree must match the pinned official commit")
    entries = []
    for item in sorted(tree["tree"], key=lambda item: item["path"]):
        source = item["path"]
        if not re.fullmatch(r"docs/DQC_US_[0-9]{4}/DQC_[0-9]{4}\.md", source):
            continue
        raw = (documents / Path(source).name).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != item["sha"]:
            raise ValueError(f"document differs from pinned Git tree: {source}")
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
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--git-tree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    catalog = build_catalog(arguments.documents, arguments.git_tree)
    raw = (json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n").encode()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(raw)
    print(hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
