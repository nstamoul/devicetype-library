#!/usr/bin/env python3
"""Build the PR body for an upstream sync branch (used by .github/workflows/upstream-sync.yml).

Reads check results from RESULTS_DIR, where each check wrote <name>.rc (an exit code, or
"skipped: <reason>") and <name>.log, and prints Markdown to stdout. Exits 2 when any check
failed or the merge conflicted, so the workflow can mark the PR as a draft (1 means the
script itself crashed).
"""

from __future__ import annotations

import argparse
import collections
import subprocess
import sys
from pathlib import Path

# GitHub rejects PR bodies over 65536 characters.
BODY_LIMIT = 60000
LOG_TAIL_LINES = 40
MAX_MANUFACTURER_ROWS = 200

DEFINITION_DIRS = ("device-types", "module-types", "rack-types")
IMAGE_DIRS = ("elevation-images", "module-images")

CHECKS = (
    ("case_collisions", "Paths differing only by case (`git ls-files | sort -f | uniq -i -D`)"),
    ("yamllint", "`yamllint --strict device-types/ module-types/`"),
    ("definitions", "Upstream `pytest tests/definitions_test.py`"),
    ("contract", "Nautobot import contract (`nautobot_jobs_repo` `tests/test_device_type_library_contract.py`)"),
)


def git(library: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(library), *args], check=True, capture_output=True, text=True
    ).stdout


def read_result(results: Path, name: str) -> tuple[str, str]:
    """Return (status, log) where status is pass, fail or skipped: <reason>."""
    rc_file = results / f"{name}.rc"
    log_file = results / f"{name}.log"
    log = log_file.read_text(errors="replace") if log_file.exists() else ""
    if not rc_file.exists():
        # A check that never recorded a result must not let the PR look green.
        return "fail", log or "check did not run (no result recorded)"
    rc = rc_file.read_text().strip()
    if rc.startswith("skipped"):
        return rc, log
    return ("pass" if rc == "0" else "fail"), log


def tail(text: str, lines: int = LOG_TAIL_LINES) -> str:
    kept = text.rstrip().splitlines()[-lines:]
    return "\n".join(kept)


def summarize_changes(name_status: str):
    """Group a `git diff --name-status` listing by top directory and manufacturer."""
    per_mfr = collections.defaultdict(collections.Counter)
    other = []
    for line in name_status.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        status = fields[0][0]  # R100 -> R
        path = fields[-1]
        parts = path.split("/")
        top = parts[0]
        if top in DEFINITION_DIRS + IMAGE_DIRS and len(parts) >= 3:
            per_mfr[parts[1]][(top, status)] += 1
        else:
            other.append((status, path))
    return per_mfr, other


def fmt_counts(counter: collections.Counter, *tops: str) -> str:
    cells = []
    for status, label in (("A", "+"), ("M", "~"), ("R", "→"), ("D", "−")):
        count = sum(counter.get((top, status), 0) for top in tops)
        if count:
            cells.append(f"{label}{count}")
    return " ".join(cells)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--base", required=True, help="fork master commit the branch starts from")
    parser.add_argument("--upstream", required=True, help="upstream master commit being merged")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--conflicts", type=Path, required=True, help="file listing conflicted paths, one per line")
    parser.add_argument("--jobs-ref", default="main")
    parser.add_argument("--run-url", default="")
    args = parser.parse_args()

    lib = args.library
    commits = int(git(lib, "rev-list", "--count", f"{args.base}..{args.upstream}").strip())
    conflicts = [p for p in args.conflicts.read_text().splitlines() if p.strip()] if args.conflicts.exists() else []
    # Three-dot diff = what the PR shows: upstream's changes since the merge base, plus our merge fixes.
    name_status = git(lib, "diff", "--name-status", "-M", f"{args.base}...HEAD")
    per_mfr, other = summarize_changes(name_status)

    results = {name: read_result(args.results, name) for name, _ in CHECKS}
    failed = [name for name, (status, _) in results.items() if status == "fail"]

    out = []
    out.append(
        f"Weekly merge of [netbox-community/devicetype-library](https://github.com/netbox-community/devicetype-library) "
        f"`master` @ `{args.upstream[:10]}` into this fork's `master` @ `{args.base[:10]}`."
    )
    out.append("")
    out.append(f"- **Upstream commits:** {commits}")
    if conflicts:
        out.append(
            f"- **Merge:** ⚠️ CONFLICTS in {len(conflicts)} file(s). This branch is upstream `master` as-is, so "
            "GitHub shows the conflicts; resolve locally (see below). Checks ran against upstream's tree, "
            "without the fork's additions."
        )
    else:
        out.append("- **Merge:** clean")
    for name, label in CHECKS:
        status, _ = results[name]
        icon = {"pass": "✅", "fail": "❌"}.get(status, "⏭️")
        out.append(f"- **{label}:** {icon} {status}")
    if args.run_url:
        out.append(f"- **Workflow run:** {args.run_url}")
    out.append("")

    if conflicts:
        out.append("### Conflicted files")
        out.append("")
        out.extend(f"- `{p}`" for p in conflicts)
        out.append("")
        out.append("Resolve with:")
        out.append("")
        out.append("```bash")
        out.append("git fetch origin")
        out.append("git switch <this branch>")
        out.append("git merge origin/master   # fix conflicts, then commit and push")
        out.append("```")
        out.append("")

    out.append("### Changed files per manufacturer")
    out.append("")
    if per_mfr:
        out.append("`+` added, `~` modified, `→` renamed, `−` deleted.")
        out.append("")
        out.append("| Manufacturer | device-types | module-types | rack-types | elevation + module images |")
        out.append("|---|---|---|---|---|")
        ranked = sorted(per_mfr.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower()))
        for mfr, counter in ranked[:MAX_MANUFACTURER_ROWS]:
            out.append(
                f"| {mfr} | {fmt_counts(counter, 'device-types')} | {fmt_counts(counter, 'module-types')} "
                f"| {fmt_counts(counter, 'rack-types')} | {fmt_counts(counter, *IMAGE_DIRS)} |"
            )
        if len(ranked) > MAX_MANUFACTURER_ROWS:
            rest = ranked[MAX_MANUFACTURER_ROWS:]
            out.append(
                f"| _{len(rest)} more manufacturers_ | | | | {sum(sum(c.values()) for _, c in rest)} files |"
            )
        totals = collections.Counter()
        for counter in per_mfr.values():
            totals.update(counter)
        out.append(
            f"| **Total ({len(per_mfr)} manufacturers)** | {fmt_counts(totals, 'device-types')} "
            f"| {fmt_counts(totals, 'module-types')} | {fmt_counts(totals, 'rack-types')} "
            f"| {fmt_counts(totals, *IMAGE_DIRS)} |"
        )
    else:
        out.append("No definition or image changes.")
    out.append("")

    if other:
        workflow_changes = [p for _, p in other if p.startswith(".github/workflows/")]
        out.append(f"### Other paths ({len(other)})")
        out.append("")
        if workflow_changes:
            out.append(
                "> ⚠️ Upstream changed GitHub workflow files. Workflows disabled on this fork stay disabled, but a "
                "newly added upstream workflow is enabled by default: disable it with "
                "`gh workflow disable <file> --repo nstamoul/devicetype-library` unless it should run here."
            )
            out.append("")
        out.extend(f"- `{s}` `{p}`" for s, p in other[:100])
        if len(other) > 100:
            out.append(f"- … {len(other) - 100} more")
        out.append("")

    details = []
    for name, label in CHECKS:
        status, log = results[name]
        if status == "pass" or not log.strip():
            continue
        count = len(log.rstrip().splitlines())
        details.append(
            f"<details><summary>{label}: {status} ({count} output lines, last {min(count, LOG_TAIL_LINES)} shown)"
            f"</summary>\n\n```text\n{tail(log)}\n```\n\n</details>\n"
        )
    if details:
        out.append("### Check output (last lines)")
        out.append("")
        out.extend(details)

    out.append("---")
    out.append(
        f"Generated by `.github/workflows/upstream-sync.yml`; contract from `nstamoul/nautobot_jobs_repo@{args.jobs_ref}`. "
        "Review before merging; the workflow never pushes to `master`."
    )

    body = "\n".join(out)
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT] + "\n\n… truncated; see the workflow run summary for the rest."
    sys.stdout.write(body + "\n")
    return 2 if (failed or conflicts) else 0


if __name__ == "__main__":
    sys.exit(main())
