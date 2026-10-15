# Upstream sync (fork only)

`workflows/upstream-sync.yml` merges `netbox-community/devicetype-library` `master` into a
`sync/upstream-<date>` branch every Monday and opens a PR against this fork's `master`.
It never pushes to `master`; a human reviews and merges each PR. Nautobot then imports from
`master` through `sync_device_types_from_library` and `import_module_types_from_library`
in `nstamoul/nautobot_jobs_repo`.

Each run:

1. Checks out the fork with full history (`fetch-depth: 0`) and merges `upstream/master`.
   A run is skipped when the fork is up to date or an earlier `sync/upstream-*` PR is still open.
2. On conflicts, pushes upstream's tip unchanged and opens a **draft** PR that lists the
   conflicted files. Resolve locally with `git merge origin/master` on the sync branch.
3. Runs the checks and reports each in the PR body:
   - paths that differ only by case (`git ls-files | sort -f | uniq -i -D`)
   - `yamllint --strict device-types/ module-types/`
   - upstream's `pytest tests/definitions_test.py` (diffs against upstream, so it validates
     the fork's additions)
   - the Nautobot import contract, `tests/test_device_type_library_contract.py` from
     `nstamoul/nautobot_jobs_repo`
4. Writes the PR body (commit count, changed files per manufacturer, check results), opens the
   PR as a draft when anything failed, and sets an `upstream-sync/checks` commit status.

The steps live in `scripts/upstream_sync.sh` and `scripts/upstream_sync_report.py`, so they can
be run locally:

```bash
.github/scripts/upstream_sync.sh merge . /tmp/sync-results
.github/scripts/upstream_sync.sh checks . /tmp/sync-results ../nautobot_jobs_repo
```

Run them in a full clone on Linux: on a case-insensitive filesystem only one file of each
case-colliding pair is checked out, so the contract can miss what `git ls-files` reports.

## Setup

- **Actions** runs on this fork (verified 2026-10-15). If a fork's Actions tab ever shows
  *Workflows aren't being run on this forked repository*, click **I understand my workflows, go
  ahead and enable them**.
- **`NAUTOBOT_JOBS_REPO_TOKEN`** (repository secret): fine-grained PAT limited to
  `nstamoul/nautobot_jobs_repo` with **Contents: read**. Without it the contract is skipped.
- **`UPSTREAM_SYNC_TOKEN`** (optional repository secret): fine-grained PAT limited to
  `nstamoul/devicetype-library` with **Contents**, **Pull requests**, **Commit statuses** and
  **Workflows** read/write. The default `GITHUB_TOKEN` cannot push commits that change
  `.github/workflows/`, which upstream does roughly monthly, and PRs it opens do not trigger
  `validation.yml`. One PAT that covers both repositories can be stored in both secrets.

Run by hand from **Actions → Upstream sync → Run workflow**, or:

```bash
gh workflow run upstream-sync.yml --repo nstamoul/devicetype-library -f dry_run=true
```

`jobs_repo_ref` picks the `nautobot_jobs_repo` branch the contract comes from (default `main`).

## Inherited upstream workflows

These are disabled on the fork with `gh workflow disable`, not deleted. Deleting them would
turn every upstream change to them (dependabot bumps arrive about monthly) into a
modify/delete conflict in the sync PR. A disabled workflow stays disabled when upstream
edits it.

| Workflow | State | Why |
|---|---|---|
| `stale.yml` | disabled | would mark and close open sync PRs after 37 days |
| `master-slugs.yml` | disabled | commits to `master` on every push via `SLUG_DEPLOY_KEY` |
| `build-cache.yml` | disabled | only warms upstream's CI cache |
| `update-generated-schema.yml` | disabled | opens schema PRs assigned to an upstream maintainer, twice a day |
| `validation.yml` | active | lint and schema checks on PRs to `master` |

If a sync PR adds a new upstream workflow, its body warns about it; disable it with
`gh workflow disable <file> --repo nstamoul/devicetype-library` unless it should run here.
