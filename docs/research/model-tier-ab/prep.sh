#!/usr/bin/env bash
# prep.sh REPO AB [REPS] — build one task directory per replayed fix under AB, confirm
# its known answer (red at the parent, green at the fix), then copy the red tree
# into one cell per arm and repetition. No model call. Needs PY (a python with pytest).
# Protocol: ../2026-10-23-workflow-effort-and-reader-ab.md#queued-model-tier-for-implement-stages
set -u
repo=$1 ab=$2 reps=${3:-3}
: "${PY:?set PY to a python that has pytest}"
[ -d "$ab" ] || { echo "AB must be an existing directory: $ab" >&2; exit 2; }
# A cell inside another work tree could read that tree's history, which holds the fixes.
if git -C "$ab" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "AB is inside a git work tree; put it outside any repository" >&2; exit 2
fi
ab=$(cd "$ab" && pwd)
limit=${AB_TIMEOUT:-600}

# ─── Tasks: id, fix commit, verifier (run from the task's checkout root) ───
# shellcheck disable=SC2016  # $PY expands when the verifier runs, not here
P='cd orchestrator && $PY -m pytest -q -p no:cacheprovider'
TASKS="
scrub      bb50fbd $P tests/test_scrub_corrections.py
codexupd   e23e67f $P tests/test_codex_plugin_update.py
archive    4d480c6 $P tests/test_archive_progress.py
scanhealth 71379b4 bash tests/test-scan-health.sh
rmflags    af1c4b2 bash tests/test-pre-tool-guardian.sh
redirect   0b8e29a bash tests/test-correction-pairing.sh
loopmodel  0075a5d bash tests/test-loop-args.sh
droprules  b0665f4 bash tests/test-skill-routing.sh
"
# ─── Build, check the known answer, copy into cells ───
run() { (cd "$1" && HOME="$2" timeout "$limit" bash -c "$3" </dev/null >/dev/null 2>&1); echo $?; }
: > "$ab/kept.txt"
echo "$TASKS" | while read -r id fix verifier; do
  [ -n "$id" ] || continue
  t=$ab/$id; rm -rf "$t"; mkdir -p "$t/home"
  parent=$(git -C "$repo" rev-parse "$fix^")
  files=$(git -C "$repo" show --name-only --format= "$fix")
  tests=$(echo "$files" | grep -E '^(tests/|orchestrator/tests/)')
  # Every other path the fix changed builds the known answer; the agent owns the code among them.
  rest=$(echo "$files" | grep -v -E '^(tests/|orchestrator/tests/)')
  echo "$tests" > "$t/protected.txt"
  echo "$rest" | grep -v -E '(^docs/|\.md$)' > "$t/owned.txt"
  echo "$verifier" > "$t/verifier.txt"
  git -C "$repo" log -1 --format=%s "$fix" | sed -E -e 's/^[a-z]+(\([^)]*\))?: //' -e 's/ \(#[0-9]+\)$//' > "$t/statement.txt"
  mkdir -p "$t/base"; git -C "$repo" archive "$parent" | tar -x -C "$t/base"
  for f in $tests; do mkdir -p "$t/base/$(dirname "$f")"; git -C "$repo" show "$fix:$f" > "$t/base/$f"; done
  (cd "$t/base" && git init -q && git add -A && git -c user.name=ab -c user.email=ab@example.invalid commit -qm base)
  cp -a "$t/base" "$t/known"
  for f in $rest; do git -C "$repo" show "$fix:$f" > "$t/known/$f"; done
  red=$(run "$t/base" "$t/home" "$verifier"); green=$(run "$t/known" "$t/home" "$verifier")
  if [ "$red" = 124 ] || [ "$green" = 124 ]; then
    echo "TIMEOUT $id: parent=$red fix=$green; rerun on a quieter host or raise AB_TIMEOUT"; rm -rf "$t"; continue
  fi
  if [ "$red" = 0 ] || [ "$green" != 0 ]; then
    echo "DROP $id: parent=$red fix=$green (need parent!=0, fix=0)"; rm -rf "$t"; continue
  fi
  for arm in A B C; do r=1; while [ "$r" -le "$reps" ]; do cp -a "$t/base" "$t/$arm-$r"; r=$((r + 1)); done; done
  echo "$id" >> "$ab/kept.txt"
  echo "OK   $id: parent=$red fix=$green owned=$(tr '\n' ' ' < "$t/owned.txt")"
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
