#!/usr/bin/env python3
"""Merge local coverage.xml files under a directory and print a percentage.

Usage: merge_local_coverage.py [artifacts_dir]

Prints either a percentage like "85%" or the string "unknown".
"""

from pathlib import Path
import sys
from xml.etree import ElementTree as ET


def parse_root_counts(path: Path):
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    covered = root.attrib.get("lines-covered") or root.attrib.get("lines_covered")
    valid = root.attrib.get("lines-valid") or root.attrib.get("lines_valid")
    if covered is not None and valid is not None:
        try:
            return int(covered), int(valid)
        except Exception:
            return None
    lr = root.attrib.get("line-rate") or root.attrib.get("line_rate")
    if lr is not None and (
        valid := root.attrib.get("lines-valid") or root.attrib.get("lines_valid")
    ):
        try:
            v = float(lr)
            return int(float(valid) * v), int(valid)
        except Exception:
            return None
    return None


def fallback_count(path: Path):
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return 0, 0
    total = 0
    covered = 0
    for elem in root.iter():
        if elem.tag.lower().endswith("line") and "hits" in elem.attrib:
            total += 1
            try:
                if int(elem.attrib.get("hits", "0")) > 0:
                    covered += 1
            except Exception:
                pass
    return covered, total


def main(argv):
    artifacts_dir = argv[1] if len(argv) > 1 else "artifacts"
    p = Path(artifacts_dir)
    total_covered = 0
    total_valid = 0
    if not p.exists():
        print("unknown")
        return 0
    for f in p.rglob("coverage.xml"):
        counts = parse_root_counts(f)
        if counts is None:
            counts = fallback_count(f)
        covered, valid = counts
        total_covered += covered
        total_valid += valid
    if total_valid == 0:
        print("unknown")
        return 0
    pct = round((total_covered / total_valid) * 100)
    print(f"{pct}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
