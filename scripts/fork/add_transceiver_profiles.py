#!/usr/bin/env python3
"""Fork-only tooling (nstamoul/devicetype-library); not part of upstream.

Adds upstream's structured ``profile: Transceiver`` + ``attribute_data`` block
to the fork-only, generated Cisco transceiver module types, deriving the values
from the markdown attribute table kept in ``comments``.

Only files that (a) live under ``module-types/``, (b) do not exist in
``upstream/master``, (c) contain the "Generated from Cisco transceiver
compatibility data" table and (d) either have no ``profile`` key yet (converted) or
already carry ``profile: Transceiver`` (derived attribute_data keys are refreshed).
The new keys are inserted as text, right after the identity keys
(manufacturer/model/part_number/description/weight/weight_unit/airflow), so
nothing else in the file is reformatted and the table stays unchanged.
``data_rate`` is the nominal (maximum) line rate: the highest "Normalized speeds" entry.
The script is idempotent: a second run changes nothing.

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
DERIVED_KEYS = set(ATTRIBUTE_ORDER) - {"phy"}
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


def rate_to_mbps(rate):
    value, unit = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([GM])", rate).groups()
    return Decimal(value) * (1000 if unit == "G" else 1)


def derive_data_rate(table):
    """Nominal (maximum) line rate, as in upstream's multirate optics (GLC-T -> 1G, SFP-10G-T-X -> 10G).

    Highest entry of "Normalized speeds"; else "Default speed" (which can be the
    lowest supported rate, so it is only a fallback); else a single-valued "Data rate".
    """
    normalized = [parse_rate(s) for s in table.get("Normalized speeds", "").split(",") if present(s)]
    normalized = [r for r in normalized if r]
    if normalized:
        return max(normalized, key=rate_to_mbps)
    return parse_rate(table.get("Default speed")) or parse_rate(table.get("Data rate"))


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


def replace_attribute_data(text, attributes):
    """Rewrite the existing top-level attribute_data block in place."""
    lines = text.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("attribute_data:"))
    end = start + 1
    while end < len(lines) and lines[end].startswith(" "):
        end += 1
    lines[start:end] = render_block(attributes)[1:]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report only; do not write files")
    parser.add_argument("--upstream-ref", default="upstream/master")
    args = parser.parse_args()

    converted, updated, skipped = [], [], []
    for path in fork_only_candidates(args.upstream_ref):
        text = path.read_text(encoding="utf-8")
        if MARKER not in text:
            continue
        data = yaml.safe_load(text)
        derived = derive_attributes(parse_table(data.get("comments", "")))
        if "profile" in data or "attribute_data" in data:
            if data.get("profile") != "Transceiver" or not isinstance(data.get("attribute_data"), dict):
                continue
            # Previously converted: refresh derived keys, keep any others (e.g. a hand-added phy).
            merged = {**data["attribute_data"], **derived}
            for key in DERIVED_KEYS - derived.keys():
                merged.pop(key, None)
            attributes = {k: merged[k] for k in ATTRIBUTE_ORDER if k in merged}
            if attributes == data["attribute_data"]:
                continue
            new_text = replace_attribute_data(text, attributes)
            target = updated
        else:
            if not derived:
                skipped.append((path, "table has no usable attributes"))
                continue
            attributes = derived
            new_text = insert_block(text, render_block(attributes))
            target = converted
        check = yaml.safe_load(new_text)
        rest = lambda d: {k: v for k, v in d.items() if k not in ("profile", "attribute_data")}  # noqa: E731
        if check["attribute_data"] != attributes or rest(check) != rest(data):
            raise RuntimeError(f"{path}: round-trip mismatch after edit")
        if not args.dry_run:
            path.write_text(new_text, encoding="utf-8")
        target.append(path)

    print(f"converted: {len(converted)}{' (dry run)' if args.dry_run else ''}")
    print(f"updated: {len(updated)}")
    print(f"skipped (insufficient data): {len(skipped)}")
    for path, reason in skipped:
        print(f"  {path}: {reason}")
    for path in converted:
        print(f"  + {path}")
    for path in updated:
        print(f"  ~ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
