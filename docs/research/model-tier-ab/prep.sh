#!/usr/bin/env bash
# prep.sh REPO AB [REPS [TASK...]] — build one task directory per replayed fix under AB,
# confirm its known answer (red at the parent, green with only the owned files from the
# fix), then copy the red tree into one cell per arm and repetition. Naming TASKs builds
# only those (the pilot builds `scanhealth` with REPS 1). No model call.
# Needs PY (a python with pytest), Linux / GNU coreutils (`timeout`), and an EMPTY AB
# outside any repository. AB_TASKS_FILE replaces the task table below (same format).
# Protocol: ../2026-10-23-workflow-effort-and-reader-ab.md#queued-model-tier-for-implement-stages
set -u
[ $# -ge 2 ] || { echo "usage: prep.sh REPO AB [REPS [TASK...]]" >&2; exit 2; }
repo=$1 ab=$2 reps=${3:-3}
if [ $# -ge 3 ]; then shift 3; else shift $#; fi
only=" $* "
: "${PY:?set PY to a python that has pytest}"
command -v timeout >/dev/null 2>&1 || { echo "prep.sh needs GNU timeout (coreutils)" >&2; exit 2; }
[ -d "$ab" ] || { echo "AB must be an existing directory: $ab" >&2; exit 2; }
# A leftover task directory (an earlier run's cells, or an answer key) would sit next to
# the new cells, so every prep starts from nothing.
[ -z "$(ls -A "$ab")" ] || { echo "AB must be empty: $ab" >&2; exit 2; }
# A cell inside another work tree could read that tree's history, which holds the fixes.
if git -C "$ab" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "AB is inside a git work tree; put it outside any repository" >&2; exit 2
fi
ab=$(cd "$ab" && pwd)
limit=${AB_TIMEOUT:-600}
# The known answer is built here, outside AB, and deleted as soon as it has been run:
# nothing an agent can reach from its cell holds the fix.
scratch=$(mktemp -d "${TMPDIR:-/tmp}/ab-prep.XXXXXX")
trap 'rm -rf "$scratch"' EXIT
case $scratch/ in "$ab"/*) echo "TMPDIR is inside AB; point it elsewhere" >&2; exit 2 ;; esac

# ─── Tasks: id, fix commit, verifier (run from the task's checkout root) ───
# shellcheck disable=SC2016  # $PY expands when the verifier runs, not here
P='cd orchestrator && $PY -m pytest -q -p no:cacheprovider'
TASKS="
archive    4d480c6 $P tests/test_archive_progress.py
scanhealth 71379b4 bash tests/test-scan-health.sh
rmflags    af1c4b2 bash tests/test-pre-tool-guardian.sh
redirect   0b8e29a bash tests/test-correction-pairing.sh
loopmodel  0075a5d bash tests/test-loop-args.sh
droprules  b0665f4 bash tests/test-skill-routing.sh
domain     ff7ea66 bash tests/test-correction-pairing.sh
postedit   c8fe850 bash tests/test-hooks.sh
"
if [ -n "${AB_TASKS_FILE:-}" ]; then TASKS=$(cat "$AB_TASKS_FILE") || exit 2; fi

# ─── Build, check the known answer, copy into cells ───
# run DIR VERIFIER — the verifier's exit code, with a fresh empty HOME and stdin closed.
run() {
  _h=$(mktemp -d "$scratch/home.XXXXXX")
  (cd "$1" && HOME="$_h" timeout "$limit" bash -c "$2" </dev/null >/dev/null 2>&1)
  _rc=$?; rm -rf "$_h"; echo "$_rc"
}
# put_fix FIX DIR FILE... — write each file as the fix left it (delete it if the fix did).
put_fix() {
  _fix=$1 _dir=$2; shift 2
  for _f in "$@"; do
    if git -C "$repo" cat-file -e "$_fix:$_f" 2>/dev/null; then
      mkdir -p "$_dir/$(dirname "$_f")"; git -C "$repo" show "$_fix:$_f" > "$_dir/$_f"
    else rm -f "$_dir/$_f"; fi
  done
}
: > "$ab/kept.txt"
echo "$TASKS" | while read -r id fix verifier; do
  [ -n "$id" ] || continue
  case $only in "  "|*" $id "*) ;; *) continue ;; esac
  t=$ab/$id; mkdir -p "$t"
  parent=$(git -C "$repo" rev-parse "$fix^")
  files=$(git -C "$repo" show --name-only --format= "$fix")
  tests=$(echo "$files" | grep -E '^(tests/|orchestrator/tests/)')
  # The agent owns the fix's code paths. The known answer is the base plus those paths
  # only, which is exactly the tree grade.sh builds, so a task whose verifier also needs
  # the fix's docs is dropped here rather than failing every arm.
  owned=$(echo "$files" | grep -v -E '^(tests/|orchestrator/tests/)' | grep -v -E '(^docs/|\.md$)')
  # A replayed FIX repairs files that already exist. A commit that creates an owned file
  # asks for a new file written to a test, a different task (bb50fbd and e23e67f did
  # that, and left the table on review), so it is dropped before anything is built.
  new=$(echo "$owned" | while read -r f; do
    [ -z "$f" ] || git -C "$repo" cat-file -e "$parent:$f" 2>/dev/null || echo "$f"
  done)
  if [ -n "$new" ]; then
    echo "DROP $id: owned file new at the parent: $(echo "$new" | tr '\n' ' ')(a new-file task, not a fix)"
    rm -rf "$t"; continue
  fi
  echo "$tests" > "$t/protected.txt"
  echo "$owned" > "$t/owned.txt"
  echo "$verifier" > "$t/verifier.txt"
  git -C "$repo" log -1 --format=%s "$fix" | sed -E -e 's/^[a-z]+(\([^)]*\))?: //' -e 's/ \(#[0-9]+\)$//' > "$t/statement.txt"
  mkdir -p "$t/base"; git -C "$repo" archive "$parent" | tar -x -C "$t/base"
  # shellcheck disable=SC2086  # one path per line, no spaces in this repository's paths
  put_fix "$fix" "$t/base" $tests
  (cd "$t/base" && git init -q && git add -A && git -c user.name=ab -c user.email=ab@example.invalid -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -qm base)
  # The brief points the agent's HOME at <cell>/.ab-home; keep it out of every diff.
  mkdir -p "$t/base/.git/info"; echo '/.ab-home/' >> "$t/base/.git/info/exclude"
  # Both checks run in throwaway copies, so base stays exactly the committed tree.
  cp -a "$t/base" "$scratch/$id-red"; red=$(run "$scratch/$id-red" "$verifier"); rm -rf "$scratch/$id-red"
  cp -a "$t/base" "$scratch/$id-known"
  # shellcheck disable=SC2086
  put_fix "$fix" "$scratch/$id-known" $owned
  green=$(run "$scratch/$id-known" "$verifier"); rm -rf "$scratch/$id-known"
  if [ "$red" = 124 ] || [ "$green" = 124 ]; then
    echo "TIMEOUT $id: parent=$red fix=$green; rerun on a quieter host or raise AB_TIMEOUT"; rm -rf "$t"; continue
  fi
  if [ "$red" = 0 ] || [ "$green" != 0 ]; then
    echo "DROP $id: parent=$red fix=$green (need parent!=0, fix=0)"; rm -rf "$t"; continue
  fi
  for arm in A B C; do
    r=1
    while [ "$r" -le "$reps" ]; do cp -a "$t/base" "$t/$arm-$r"; mkdir "$t/$arm-$r/.ab-home"; r=$((r + 1)); done
  done
  echo "$id" >> "$ab/kept.txt"
  echo "OK   $id: parent=$red fix=$green owned=$(tr '\n' ' ' < "$t/owned.txt")"
done
# ─── Nothing under AB may hold a known answer ───
# Each task directory holds base/, the cells and four small text files, nothing else.
for t in "$ab"/*/; do
  [ -d "$t" ] || continue
  for e in "$t"*; do
    [ -e "$e" ] || continue
    case $(basename "$e") in base|[ABC]-[0-9]*|protected.txt|owned.txt|verifier.txt|statement.txt) ;;
      *) echo "unexpected entry under AB: $e" >&2; exit 1 ;;
    esac
  done
done
# ─── The Workflow's args: one object per kept task, in the table's order ───
python3 - "$ab" "$reps" "$PY" > "$ab/args.json" <<'EOF'
import json, pathlib, sys
ab, reps, py = pathlib.Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
read = lambda t, n: (t / n).read_text().strip()
tasks = [{"id": t.name, "statement": read(t, "statement.txt"),
          "owned": read(t, "owned.txt").split(), "verifier": read(t, "verifier.txt")}
         for t in (ab / i for i in (ab / "kept.txt").read_text().split())]
print(json.dumps({"root": str(ab), "py": py, "reps": reps, "tasks": tasks}, indent=1))
EOF
