#!/usr/bin/env python3
"""Fork-only tooling (nstamoul/devicetype-library); not part of upstream.

Adds upstream's structured ``profile: Transceiver`` + ``attribute_data`` block
to the fork-only, generated Cisco transceiver module types, deriving the values
from the markdown attribute table kept in ``comments``.

Only files that (a) live under ``module-types/``, (b) do not exist in
``upstream/master``, (c) contain the "Generated from Cisco transceiver
compatibility data" table and (d) have no ``profile`` key yet are touched.
The new keys are inserted as text, right after the identity keys
(manufacturer/model/part_number/description/weight/weight_unit/airflow), so
nothing else in the file is reformatted and the table stays unchanged.
The script is idempotent: converted files have a ``profile`` key and are skipped.

Usage (from the repository root, after ``git fetch upstream``):

    python -I scripts/fork/add_transceiver_profiles.py [--dry-run] [--upstream-ref REF]
"""

import argparse
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

MARKER = "Generated from Cisco transceiver compatibility data"
IDENTITY_KEYS = {"manufacturer", "model", "part_number", "description", "weight", "weight_unit", "airflow"}
# Key order follows upstream's Transceiver files (phy is not derivable from the table).
ATTRIBUTE_ORDER = ("phy", "media", "reach", "data_rate", "form_factor", "connector_type")
TOP_LEVEL_KEY = re.compile(r"^([A-Za-z0-9_-]+):(?:\s|$)")
ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*$")
MISSING = {"", "-", "n/a", "na", "none"}


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def parse_table(comments):
    """Return {attribute: value} from the '| Attribute | Value |' table in comments."""
    table = {}
    started = False
    for line in comments.splitlines():
        if not started:
            started = line.strip() == "| Attribute | Value |"
            continue
        m = ROW.match(line.strip())
        if not m:
            if table:
                break
            continue
        key, value = m.groups()
        if set(key) <= {"-", " "}:
            continue
        table.setdefault(key, value)
    return table


def present(value):
    return value is not None and value.strip().lower() not in MISSING


def parse_reach_m(value):
    """'400m' -> 400.0, '10km' -> 10000.0, '2.5m' -> 2.5; None if absent/non-numeric."""
    if not present(value):
        return None
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(km|m)", value.strip().lower())
    if not m:
        return None
    try:
        metres = Decimal(m.group(1)) * (1000 if m.group(2) == "km" else 1)
    except InvalidOperation:
        return None
    return float(metres)


def normalize_connector(value):
    """'LC (UPC)' -> 'LC/UPC', 'MPO-12 (APC)' -> 'MPO-12/APC'; 'N/A' -> None."""
    if not present(value):
        return None
    value = re.sub(r"\s+", " ", value.strip())
    if value == "LC (PC or UPC)":
        # PC and UPC polishes are interchangeable for LC; upstream spells the optics "LC/UPC".
        return "LC/UPC"
    m = re.fullmatch(r"(.+?) \((\w+)\)", value)
    return f"{m.group(1)}/{m.group(2)}" if m else value


def parse_rate(value):
    """'10 Gbps' -> '10G', '100 Mbps' -> '100M', '25G' -> '25G'; None if not a single rate."""
    if not present(value):
        return None
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(G|M)(?:bps)?", value.strip())
    return f"{m.group(1)}{m.group(2)}" if m else None


def derive_data_rate(table):
    # Default speed first; then a single normalized speed; then a single-valued "Data rate".
    rate = parse_rate(table.get("Default speed"))
    if rate:
        return rate
    normalized = [s.strip() for s in table.get("Normalized speeds", "").split(",") if present(s)]
    if len(normalized) == 1 and parse_rate(normalized[0]):
        return parse_rate(normalized[0])
    return parse_rate(table.get("Data rate"))


def derive_attributes(table):
    """Return attribute_data (schema key order) derived from the table."""
    values = {
        "media": table["Media"].strip() if present(table.get("Media")) else None,
        "reach": parse_reach_m(table.get("Reach")),
        "data_rate": derive_data_rate(table),
        "form_factor": table["Form factor"].strip() if present(table.get("Form factor")) else None,
        "connector_type": normalize_connector(table.get("Connector type")),
    }
    return {k: values[k] for k in ATTRIBUTE_ORDER if values.get(k) is not None}


def render_block(attributes):
    lines = ["profile: Transceiver", "attribute_data:"]
    for key, value in attributes.items():
        lines.append(f"  {key}: {value!r}" if key == "reach" else f"  {key}: {value}")
    return lines


def insert_block(text, block):
    """Insert block lines before the first top-level key that is not an identity key."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = TOP_LEVEL_KEY.match(line)
        if m and m.group(1) not in IDENTITY_KEYS:
            lines[i:i] = block
            return "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text + "\n".join(block) + "\n"


def fork_only_candidates(upstream_ref):
    upstream = set(git("ls-tree", "-r", "--name-only", upstream_ref, "--", "module-types").splitlines())
    for path in sorted(Path("module-types").rglob("*.yaml")):
        if path.as_posix() not in upstream:
            yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report only; do not write files")
    parser.add_argument("--upstream-ref", default="upstream/master")
    args = parser.parse_args()

    converted, skipped = [], []
    for path in fork_only_candidates(args.upstream_ref):
        text = path.read_text(encoding="utf-8")
        if MARKER not in text:
            continue
        data = yaml.safe_load(text)
        if "profile" in data or "attribute_data" in data:
            continue
        attributes = derive_attributes(parse_table(data.get("comments", "")))
        if not attributes:
            skipped.append((path, "table has no usable attributes"))
            continue
        new_text = insert_block(text, render_block(attributes))
        check = yaml.safe_load(new_text)
        if check["attribute_data"] != attributes or {k: v for k, v in check.items() if k not in ("profile", "attribute_data")} != {
            k: v for k, v in data.items()
        }:
            raise RuntimeError(f"{path}: round-trip mismatch after insertion")
        if not args.dry_run:
            path.write_text(new_text, encoding="utf-8")
        converted.append(path)

    print(f"converted: {len(converted)}{' (dry run)' if args.dry_run else ''}")
    print(f"skipped (insufficient data): {len(skipped)}")
    for path, reason in skipped:
        print(f"  {path}: {reason}")
    for path in converted:
        print(f"  + {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
