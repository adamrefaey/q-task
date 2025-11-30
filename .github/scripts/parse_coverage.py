#!/usr/bin/env python3
"""Parse a coverage XML file and print a percentage like '90.0%' or 'unknown'.

Supports common formats: coverage.py (line-rate), JaCoCo <counter type="LINE">,
Cobertura attributes, and a fallback that counts <line hits="..."> elements.
"""

from pathlib import Path
import sys
from xml.etree import ElementTree as ET


def parse_coverage(path: Path) -> str:
    try:
        tree = ET.parse(path)
        root = tree.getroot()

        # 1) Try coverage.py / generic: root attribute 'line-rate'
        lr = (
            root.attrib.get("line-rate")
            or root.attrib.get("line_rate")
            or root.attrib.get("lineRate")
        )
        if lr:
            try:
                v = float(lr)
                return f"{v * 100:.1f}%"
            except Exception:
                pass

        # 2) JaCoCo style: <counter type="LINE" missed="..." covered="..."/>
        for elem in root.iter():
            if elem.tag.lower().endswith("counter") and elem.attrib.get("type") == "LINE":
                try:
                    covered = int(elem.attrib.get("covered", 0))
                    missed = int(elem.attrib.get("missed", 0))
                    total = covered + missed
                    pct = (covered / total) if total > 0 else 0.0
                    return f"{pct * 100:.1f}%"
                except Exception:
                    pass

        # 3) Cobertura-style metrics: attributes 'lines-covered' and 'lines-valid'
        for elem in root.iter():
            if "lines-covered" in elem.attrib and "lines-valid" in elem.attrib:
                try:
                    covered = int(elem.attrib["lines-covered"])
                    valid = int(elem.attrib["lines-valid"])
                    pct = (covered / valid) if valid > 0 else 0.0
                    return f"{pct * 100:.1f}%"
                except Exception:
                    pass
            if "lines_covered" in elem.attrib and "lines_valid" in elem.attrib:
                try:
                    covered = int(elem.attrib["lines_covered"])
                    valid = int(elem.attrib["lines_valid"])
                    pct = (covered / valid) if valid > 0 else 0.0
                    return f"{pct * 100:.1f}%"
                except Exception:
                    pass

        # 4) Fallback: count explicit <line hits="..."> elements (coverage.py format)
        total = 0
        covered_count = 0
        for elem in root.iter():
            if elem.tag.lower().endswith("line") and "hits" in elem.attrib:
                total += 1
                try:
                    if int(elem.attrib.get("hits", "0")) > 0:
                        covered_count += 1
                except Exception:
                    pass
        if total > 0:
            pct = covered_count / total
            return f"{pct * 100:.1f}%"

        return "unknown"
    except Exception:
        return "unknown"


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("coverage.xml")
    if not path.exists():
        print("unknown")
        return 0
    print(parse_coverage(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
