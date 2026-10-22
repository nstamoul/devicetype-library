#!/usr/bin/env bash
# Steps of .github/workflows/upstream-sync.yml, kept here so they can be run locally too.
#
#   upstream_sync.sh merge <library> <results>          merge upstream/master into a new sync branch
#   upstream_sync.sh checks <library> <results> [jobs]  run the checks, writing <name>.rc / <name>.log
#                                                       (jobs = nautobot_jobs_repo checkout for the contract)
#
# merge prints key=value lines (proceed, base, upstream, behind, branch) for $GITHUB_OUTPUT.
# Every check records its result instead of failing, so the PR body can report all of them.
set -euo pipefail

UPSTREAM_URL=${UPSTREAM_URL:-https://github.com/netbox-community/devicetype-library.git}
FORK_REPO=${FORK_REPO:-nstamoul/devicetype-library}
BASE_BRANCH=${BASE_BRANCH:-master}

cmd=$1
library=$(cd "$2" && pwd)
mkdir -p "$3"
results=$(cd "$3" && pwd)

merge() {
  cd "$library"
  if [ "$(git rev-parse --is-shallow-repository)" != false ]; then
    echo "::error::$library is a shallow clone; the merge needs full history (fetch-depth: 0)." >&2
    exit 1
  fi
  git config user.email >/dev/null || {
    git config user.name 'github-actions[bot]'
    git config user.email '41898283+github-actions[bot]@users.noreply.github.com'
  }
  git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
  git fetch --no-tags upstream master >&2

  local base up behind branch open
  base=$(git rev-parse HEAD)
  up=$(git rev-parse upstream/master)
  behind=$(git rev-list --count HEAD..upstream/master)
  echo "base=$base"
  echo "upstream=$up"
  echo "behind=$behind"

  if [ "$behind" = 0 ]; then
    echo "::notice::Fork $BASE_BRANCH already contains upstream master ($up); nothing to sync." >&2
    echo "proceed=false"
    return
  fi

  if [ "${DRY_RUN:-false}" != true ] && [ "${ALLOW_PARALLEL:-false}" != true ]; then
    open=$(gh pr list --repo "$FORK_REPO" --state open --base "$BASE_BRANCH" --json headRefName,url \
      --jq '[.[] | select(.headRefName | startswith("sync/upstream-")) | .url] | join(" ")')
    if [ -n "$open" ]; then
      echo "::notice::An upstream sync PR is still open ($open). Merge or close it first, or rerun with allow_parallel." >&2
      echo "proceed=false"
      return
    fi
  fi

  branch="sync/upstream-$(date -u +%F)"
  if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    branch="$branch-${GITHUB_RUN_NUMBER:-$(date -u +%H%M%S)}"
  fi
  git switch -q -c "$branch"

  : >"$results/conflicts.txt"
  if ! git merge --no-ff --no-edit -m "Merge upstream/master into $branch" upstream/master >&2; then
    git diff --name-only --diff-filter=U >"$results/conflicts.txt"
    if [ ! -s "$results/conflicts.txt" ]; then
      echo "::error::git merge failed without conflicted paths; see the log above." >&2
      exit 1
    fi
    echo "::warning::Merge conflicts in $(grep -c . "$results/conflicts.txt") file(s); the branch will be upstream master as-is." >&2
    git merge --abort
    # Push upstream's tip unchanged: the PR then shows the conflicts and a human resolves them
    # by merging master into the branch, instead of us committing conflict markers.
    git reset -q --hard upstream/master
  fi
  echo "branch=$branch"
  echo "proceed=true"
}

record() {  # record <name> <command...>: run a check, keep its exit code and output
  local name=$1
  shift
  set +e
  "$@" >"$results/$name.log" 2>&1
  echo $? >"$results/$name.rc"
  set -e
}

case_collisions() {
  local dupes
  # -i -D (not -Di) so BSD uniq parses it too; a failing pipeline must not read as "no dupes".
  dupes=$(git ls-files | LC_ALL=C sort -f | uniq -i -D) || return 2
  if [ -n "$dupes" ]; then
    echo "$dupes"
    return 1
  fi
}

contract() (
  cd "$1"
  DEVICETYPE_LIBRARY_PATH="$library" python -m pytest -q -p no:cacheprovider tests/test_device_type_library_contract.py
)

checks() {
  local jobs=${1:-}
  # Resolve before cd "$library": the workflow passes the jobs checkout relative to the workspace.
  if [ -n "$jobs" ] && [ -d "$jobs" ]; then jobs=$(cd "$jobs" && pwd); fi
  cd "$library"
  record case_collisions case_collisions
  record yamllint yamllint --strict --format parsable device-types/ module-types/
  # Upstream's test diffs HEAD against the upstream remote, so it validates what the fork
  # adds on top of upstream (slug clashes, schema) rather than re-testing all of upstream.
  record definitions python -m pytest -q -p no:cacheprovider --tb=short tests/definitions_test.py

  if [ -z "$jobs" ]; then
    echo "skipped: NAUTOBOT_JOBS_REPO_DEPLOY_KEY secret is not set" >"$results/contract.rc"
  elif [ -n "${JOBS_CHECKOUT:-}" ] && [ "$JOBS_CHECKOUT" != success ]; then
    echo "Could not check out nstamoul/nautobot_jobs_repo@${JOBS_REPO_REF:-main}; check NAUTOBOT_JOBS_REPO_DEPLOY_KEY." \
      >"$results/contract.log"
    echo 1 >"$results/contract.rc"
  elif [ ! -f "$jobs/tests/test_device_type_library_contract.py" ]; then
    echo "skipped: tests/test_device_type_library_contract.py is not on the checked-out nautobot_jobs_repo ref" \
      >"$results/contract.rc"
  else
    record contract contract "$jobs"
  fi

  local name
  for name in case_collisions yamllint definitions contract; do
    echo "$name: $(cat "$results/$name.rc")" >&2
  done
}

case "$cmd" in
  merge) merge ;;
  checks) checks "${4:-}" ;;
  *)
    echo "usage: $0 merge|checks <library> <results> [jobs]" >&2
    exit 2
    ;;
esac
