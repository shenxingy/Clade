#!/usr/bin/env bash
# test-memory-staleness.sh — anchored-memory staleness and review reporting.
#
# Hermetic: every repository, memory directory, HOME and hook transcript lives
# under one mktemp directory. The final sections remove guards one at a time and
# require the same behavioral cases to go red; an unchanged control stays green.
#
# Usage: bash tests/test-memory-staleness.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${MEMORY_STALENESS_SCRIPT:-$REPO_ROOT/configs/scripts/memory-staleness.py}"
HOOK="${MEMORY_STALENESS_HOOK:-$REPO_ROOT/configs/hooks/memory-staleness.sh}"
REAL_SCRIPT="$SCRIPT"
REAL_HOOK="$HOOK"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() {
  TESTS_RUN=$((TESTS_RUN + 1))
  TESTS_PASSED=$((TESTS_PASSED + 1))
  printf "  ${GREEN}✓${NC} %s\n" "$1"
}
fail() {
  TESTS_RUN=$((TESTS_RUN + 1))
  TESTS_FAILED=$((TESTS_FAILED + 1))
  printf "  ${RED}✗${NC} %s\n" "$1"
  [[ -n "${2:-}" ]] && printf "    ${RED}→ %s${NC}\n" "$2"
  return 0
}
section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }

assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"
  else fail "$3" "want '$1', got '$2'"; fi
}
assert_contains() {
  if grep -qF -- "$2" <<< "$1"; then pass "$3"
  else fail "$3" "missing '$2' in: $(head -4 <<< "$1")"; fi
}
assert_not_contains() {
  if ! grep -qF -- "$2" <<< "$1"; then pass "$3"
  else fail "$3" "unexpected '$2' in: $(head -4 <<< "$1")"; fi
}
assert_empty() {
  if [[ -z "$1" ]]; then pass "$2"
  else fail "$2" "expected no output, got: $(head -4 <<< "$1")"; fi
}
assert_incomplete() {
  assert_contains "$OUT" '⚠STALE-CHECK incomplete:' "$1 names the incomplete check"
  assert_contains "$OUT" '--budget 30' "$1 includes a bounded retry command"
  assert_eq 0 "$(grep -c '^⚠STALE ' <<< "$OUT")" "$1 contains no partial STALE lines"
  assert_eq "${2:-1}" "$(printf '%s\n' "$OUT" | wc -l | tr -d ' ')" "$1 has the expected output line count"
}

command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 is required"; exit 1; }
command -v git >/dev/null 2>&1 || { echo "FATAL: git is required"; exit 1; }
REAL_GIT="$(command -v git)"
REAL_PYTHON="$(command -v python3)"
export REAL_GIT REAL_PYTHON

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
export GIT_CONFIG_NOSYSTEM=1
export TZ=UTC
unset GIT_DIR GIT_WORK_TREE
mkdir -p "$HOME"

run_script() {
  OUT=$(python3 "$SCRIPT" "$@" 2>"$TMP/script-stderr")
  RC=$?
}

run_scan_harness() {  # run_scan_harness <record|walk-timeout|git-timeout> <mem> <repo> <log> [budget]
  local mode="$1" memory_dir="$2" project_dir="$3" log="$4" budget="${5:-30}"
  OUT=$(python3 - "$SCRIPT" "$mode" "$memory_dir" "$project_dir" "$log" "$budget" 2>"$TMP/script-stderr" <<'PY'
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

script, mode, memory_dir, project_dir, log, budget = sys.argv[1:]
sys.argv = [script, memory_dir, project_dir, "--budget", budget]
calls = []
real_scandir = os.scandir


class FakeTime:
    now = 0.0

    @classmethod
    def monotonic(cls):
        return cls.now


class ReverseOrderScan:
    """A repository directory's entries in reverse name order: the worst order a
    filesystem may return, so a walk that depends on it fails on every host."""

    def __init__(self, path):
        with real_scandir(path) as scanner:
            self.entries = sorted(scanner, key=lambda entry: entry.name, reverse=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.entries)


def recording_scandir(path):
    path_string = os.fspath(path)
    if path_string.startswith(project_dir):
        calls.append(path_string)
        if mode == "walk-timeout":
            FakeTime.now += 1.0
        return ReverseOrderScan(path)
    return real_scandir(path)


if mode == "walk-timeout":
    time.monotonic = FakeTime.monotonic
os.scandir = recording_scandir
if mode == "git-timeout":
    real_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        calls.append("timeout=%r" % (kwargs.get("timeout"),))
        if "log" in command[1:] and kwargs.get("timeout") is not None:
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0))
        return real_run(command, *args, **kwargs)

    subprocess.run = fake_run
try:
    runpy.run_path(script, run_name="__main__")
finally:
    Path(log).write_text("\n".join(calls) + ("\n" if calls else ""), encoding="utf-8")
PY
)
  RC=$?
}

memory() {  # memory <file> <modified|-> <block-list anchors|->
  local file="$1" modified="$2" anchors="$3"
  {
    printf '%s\n' '---' "name: ${1%.md}" "description: fixture for $1"
    if [[ "$modified" != "-" ]]; then printf 'modified: %s\n' "$modified"; fi
    printf '%s\n' 'metadata:' '  type: project'
    if [[ "$anchors" != "-" ]]; then printf '%s\n' 'anchors:' "$anchors"; fi
    printf '%s\n' '---' 'A fixture fact.'
  } > "$MEM/$file"
}

commit_all() {  # commit_all <repo> <message> <ISO timestamp>
  git -C "$1" add -A || return 1
  GIT_AUTHOR_DATE="$3" GIT_COMMITTER_DATE="$3" git -C "$1" commit -q -m "$2"
}

FIX="$TMP/fixture"
REPO="$FIX/repo"
MEM="$FIX/memory"
mkdir -p "$REPO/src" "$MEM"
git init -q "$REPO"
git -C "$REPO" config user.name Fixture
git -C "$REPO" config user.email fixture@example.invalid

for f in a.py old.py glob_one.py glob_two.txt deleted.py hook.py; do
  printf 'initial %s\n' "$f" > "$REPO/src/$f"
done
mkdir -p "$REPO/dir" "$REPO/app/[id]" "$REPO/app/[slug]" "$REPO/docs" "$REPO/a/b/c"
printf 'initial nested\n' > "$REPO/dir/nested.py"
printf 'initial commit\n' > "$REPO/commit.txt"
printf 'initial dynamic route\n' > "$REPO/app/[id]/page.tsx"
printf 'initial dynamic route\n' > "$REPO/app/[slug]/page.tsx"
printf 'initial CJK path\n' > "$REPO/docs/问题.md"
printf 'initial deep glob match\n' > "$REPO/a/b/c/foo_1.md"
commit_all "$REPO" initial 2026-01-02T00:00:00Z || exit 1
FIRST_SHA=$(git -C "$REPO" rev-parse HEAD)

printf 'later a\n' > "$REPO/src/a.py"
printf 'later glob\n' > "$REPO/src/glob_one.py"
printf 'later nested\n' > "$REPO/dir/nested.py"
printf 'later commit\n' > "$REPO/commit.txt"
printf 'later dynamic route\n' > "$REPO/app/[slug]/page.tsx"
printf 'later CJK path\n' > "$REPO/docs/问题.md"
printf 'committer Fixture <fixture@example.invalid> 1769990400 +0000\n' > "$REPO/src/committer.txt"
git -C "$REPO" rm -q src/deleted.py
commit_all "$REPO" later 2026-02-02T00:00:00Z || exit 1
HEAD_SHA=$(git -C "$REPO" rev-parse HEAD)
BLOB_SHA=$(git -C "$REPO" rev-parse HEAD:src/committer.txt)

memory stale.md 2026-01-15T00:00:00Z '  - src/a.py'
memory clean.md 2026-02-03T00:00:00Z '  - src/a.py'
memory unchanged.md 2026-01-15T00:00:00Z '  - src/old.py'
memory equal.md 2026-02-02T00:00:00Z '  - src/a.py'
memory deleted.md 2026-02-03T00:00:00Z '  - src/deleted.py'
memory never.md 2026-01-15T00:00:00Z '  - src/never-existed.py'
memory mtime.md - '  - src/a.py'
memory bad-date.md not-a-date '  - src/a.py'
memory glob.md 2026-01-15T00:00:00Z '  - "src/glob_*.py"'
memory glob-clean.md 2026-02-03T00:00:00Z '  - src/glob_*.py'
memory glob-missing.md 2026-01-15T00:00:00Z '  - src/no-*.py'
memory directory.md 2026-01-15T00:00:00Z '  - dir'
memory multi.md 2026-01-15T00:00:00Z '  - src/old.py
  - src/a.py'
memory commit-old.md 2026-02-03T00:00:00Z "  - src/a.py
  - commit: $FIRST_SHA"
memory commit-current.md 2026-01-15T00:00:00Z "  - src/a.py
  - commit: $HEAD_SHA"
memory commit-missing.md 2026-01-15T00:00:00Z '  - src/old.py
  - commit: deadbeef'
memory outside.md 2026-01-15T00:00:00Z '  - ../outside-missing.py'
memory absolute.md 2026-01-15T00:00:00Z '  - /definitely/missing.py'
memory old-anchored.md 2025-01-01T00:00:00Z '  - src/old.py'
memory old-unanchored.md 2025-01-01T00:00:00Z -
memory invalid-anchors-old.md 2025-01-01T00:00:00Z -
printf 'anchors: not-a-list\n' >> "$MEM/invalid-anchors-old.md"
RECENT_DATE=$(python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')
FORTY_FIVE_DATE=$(python3 -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc)-timedelta(days=45)).isoformat())')
memory recent.md "$RECENT_DATE" -
memory forty-five.md "$FORTY_FIVE_DATE" -
memory commit-only.md "$RECENT_DATE" "  - commit: $FIRST_SHA"
cat > "$MEM/inline.md" <<'EOF'
---
name: inline
modified: 2026-01-15T00:00:00Z
anchors: [src/a.py, "src/old.py"]
---
Inline anchors.
EOF
cat > "$MEM/malformed.md" <<'EOF'
---
name: malformed
modified: 2026-01-15T00:00:00Z
anchors:
  - src/a.py
This frontmatter never closes.
EOF
cat > "$MEM/anchors-map.md" <<'EOF'
---
name: anchors-map
modified: 2026-01-15T00:00:00Z
anchors:
  commit: deadbeef
---
Unknown anchor shape.
EOF
cat > "$MEM/bad-list.md" <<'EOF'
---
name: bad-list
modified: 2026-01-15T00:00:00Z
anchors:
  - nested: [src/a.py]
---
Unknown list item shape.
EOF
cat > "$MEM/MEMORY.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - src/a.py
---
- [stale](stale.md) — the index is not a fact file
EOF
cat > "$MEM/no-frontmatter.md" <<'EOF'
A memory without frontmatter or anchors.
EOF
python3 - "$MEM/mtime.md" "$MEM/bad-date.md" <<'PY'
import os, sys
from datetime import datetime, timezone
stamp = datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp()
for name in sys.argv[1:]:
    os.utime(name, (stamp, stamp))
PY

script_guard_cases() {
  section "Path, glob and commit anchors"
  run_script "$MEM" "$REPO"
  assert_eq 0 "$RC" "the scan exits 0"
  assert_contains "$OUT" '⚠STALE stale.md: src/a.py changed 2026-02-02 (memory 2026-01-15)' \
    "a newer anchor commit is STALE with both dates"
  assert_not_contains "$OUT" 'clean.md:' "an anchor older than the memory is clean"
  assert_not_contains "$OUT" 'unchanged.md:' "an unchanged anchor is clean"
  assert_not_contains "$OUT" 'equal.md:' "an anchor at exactly the memory time is clean"
  assert_contains "$OUT" '⚠STALE deleted.md: src/deleted.py changed 2026-02-02 (memory 2026-02-03)' \
    "a deleted anchor is STALE even when its memory is newer"
  assert_contains "$OUT" '⚠STALE never.md: src/never-existed.py changed unknown (memory 2026-01-15)' \
    "an anchor with no path and no history is STALE without inventing a date"
  assert_contains "$OUT" 'mtime.md: src/a.py' "file mtime supplies a missing modified date"
  assert_contains "$OUT" 'bad-date.md: src/a.py' "file mtime replaces an invalid modified date"
  assert_contains "$OUT" 'glob.md: src/glob_*.py changed 2026-02-02' "a changed glob match is STALE"
  assert_not_contains "$OUT" 'glob-clean.md:' "a glob whose changes predate the memory is clean"
  assert_contains "$OUT" 'glob-missing.md: src/no-*.py changed unknown' "a glob with no existing match is STALE"
  assert_contains "$OUT" 'directory.md: dir changed 2026-02-02' "a directory anchor covers files below it"
  assert_contains "$OUT" 'inline.md: src/a.py changed 2026-02-02' "a simple inline YAML list is accepted"
  assert_contains "$OUT" '⚠STALE commit-old.md: src/a.py changed 2026-02-02 (memory 2026-02-03)' \
    "a path changed between its commit baseline and HEAD is STALE even after the memory date"
  assert_not_contains "$OUT" 'commit-current.md:' "an empty HEAD-to-HEAD baseline range is clean"
  assert_contains "$OUT" '⚠STALE commit-missing.md: anchor commit deadbeef not in this repository' \
    "an unknown path baseline is named explicitly"
  assert_not_contains "$OUT" 'outside.md:' "a parent-traversing anchor is skipped"
  assert_not_contains "$OUT" 'absolute.md:' "an absolute anchor is skipped"
  assert_not_contains "$OUT" 'malformed.md:' "unclosed frontmatter is skipped without a crash"
  assert_not_contains "$OUT" 'anchors-map.md:' "a mapping instead of an anchors list is skipped"
  assert_not_contains "$OUT" 'bad-list.md:' "an unknown list-item shape is skipped"
  assert_not_contains "$OUT" 'MEMORY.md:' "the MEMORY.md index is never scanned as a fact"
  assert_contains "$OUT" 'old-anchored.md: src/old.py changed 2026-01-02' \
    "an old anchored memory is stale in the normal scan but excluded from review"
  assert_eq 1 "$(grep -c '^⚠STALE multi.md:' <<< "$OUT")" "one memory emits one line even with two anchors"
  assert_eq 13 "$(grep -c '^⚠STALE ' <<< "$OUT")" "only the thirteen stale fixtures emit lines"

  section "Review of old unanchored memories"
  REVIEW_MEM="$TMP/review-memory"
  rm -rf "$REVIEW_MEM"
  mkdir -p "$REVIEW_MEM"
  cp "$MEM/old-unanchored.md" "$MEM/invalid-anchors-old.md" "$MEM/old-anchored.md" \
     "$MEM/recent.md" "$MEM/forty-five.md" "$MEM/commit-only.md" "$REVIEW_MEM/"
  run_script "$REVIEW_MEM" "$REPO" --review
  assert_eq 0 "$RC" "review exits 0"
  assert_contains "$OUT" '⚠REVIEW old-unanchored.md:' "an old unanchored memory is listed"
  assert_contains "$OUT" '⚠REVIEW invalid-anchors-old.md:' "an unusable anchors field counts as unanchored"
  assert_contains "$OUT" '⚠REVIEW commit-only.md: commit anchor without paths' \
    "a commit anchor with no path anchors is a review finding"
  assert_not_contains "$OUT" 'old-anchored.md:' "an old anchored memory is not in review"
  assert_not_contains "$OUT" 'recent.md:' "a recent unanchored memory is not in review"
  assert_not_contains "$OUT" 'forty-five.md:' "45 days is below the default 60-day review threshold"
  assert_eq 3 "$(grep -c '^⚠REVIEW ' <<< "$OUT")" "review emits two age findings and one pathless commit anchor"
  run_script "$REVIEW_MEM" "$REPO" --review --days 9999
  assert_contains "$OUT" '⚠REVIEW commit-only.md: commit anchor without paths' \
    "a pathless commit anchor is reviewed regardless of age"
  run_script "$REVIEW_MEM" "$REPO" --review --days 30
  assert_contains "$OUT" 'forty-five.md:' "--days 30 includes the 45-day memory"
  run_script "$REVIEW_MEM" "$TMP/not-a-repository" --review
  assert_eq 0 "$RC" "review needs no git repository"
  assert_contains "$OUT" 'old-unanchored.md:' "review still works outside git"

  section "Silence and resource bounds"
  run_script "$MEM" "$TMP/not-a-repository"
  assert_eq 0 "$RC" "a non-git project exits 0"
  assert_empty "$OUT" "a non-git project is silent"
  run_script "$MEM" "$REPO" --budget 0
  assert_eq 0 "$RC" "an exhausted budget exits 0"
  assert_incomplete "an exhausted budget"

  mkdir -p "$TMP/git-bin"
  cat > "$TMP/git-bin/git" <<'EOF'
#!/bin/sh
printf 'call\n' >> "$GIT_CALL_LOG"
exec "$REAL_GIT" "$@"
EOF
  chmod +x "$TMP/git-bin/git"
  GIT_CALL_LOG="$TMP/git-calls"
  : > "$GIT_CALL_LOG"
  OUT=$(GIT_CALL_LOG="$GIT_CALL_LOG" PATH="$TMP/git-bin:$PATH" python3 "$SCRIPT" "$MEM" "$REPO" 2>/dev/null)
  RC=$?
  assert_eq 0 "$RC" "the wrapped-git scan exits 0"
  assert_eq 5 "$(wc -l < "$GIT_CALL_LOG" | tr -d ' ')" \
    "two commit baselines are batched into five git calls, not one call per memory"
  : > "$GIT_CALL_LOG"
  OUT=$(GIT_CALL_LOG="$GIT_CALL_LOG" PATH="$TMP/git-bin:$PATH" python3 "$SCRIPT" "$MEM" "$REPO" --review 2>/dev/null)
  assert_eq 0 "$(wc -l < "$GIT_CALL_LOG" | tr -d ' ')" "review makes no git calls"
  mkdir -p "$TMP/no-anchor-memory"
  cp "$MEM/recent.md" "$TMP/no-anchor-memory/recent.md"
  : > "$GIT_CALL_LOG"
  OUT=$(GIT_CALL_LOG="$GIT_CALL_LOG" PATH="$TMP/git-bin:$PATH" python3 "$SCRIPT" "$TMP/no-anchor-memory" "$REPO" 2>/dev/null)
  assert_empty "$OUT" "a memory set with no anchors is silent"
  assert_eq 0 "$(wc -l < "$GIT_CALL_LOG" | tr -d ' ')" "a memory set with no anchors skips git entirely"

  mkdir -p "$TMP/slow-memory"
  cp "$MEM/stale.md" "$TMP/slow-memory/stale.md"
  run_script "$TMP/slow-memory" "$REPO" --budget 30
  assert_contains "$OUT" '⚠STALE stale.md:' "the unbounded slow-git control completes"
  run_scan_harness git-timeout "$TMP/slow-memory" "$REPO" "$TMP/git-timeout-scans" 0.05
  assert_eq 0 "$RC" "a deterministic git timeout exits 0"
  assert_incomplete "a deterministic git timeout"
  if python3 - "$TMP/git-timeout-scans" 0.05 <<'PY'
import sys
budget = float(sys.argv[2])
values = [line.split("=", 1)[1].strip() for line in open(sys.argv[1], encoding="utf-8")
          if line.startswith("timeout=")]
sys.exit(0 if values and all(v != "None" and float(v) <= budget for v in values) else 1)
PY
  then
    pass "every git call is given at most the remaining budget as its timeout"
  else
    fail "every git call is given at most the remaining budget as its timeout" \
      "$(grep '^timeout=' "$TMP/git-timeout-scans" | tr '\n' ' ')"
  fi

  cat > "$TMP/git-bin/git" <<'EOF'
#!/bin/sh
if [ "${3:-}" = log ]; then exit 1; fi
exec "$REAL_GIT" "$@"
EOF
  chmod +x "$TMP/git-bin/git"
  mkdir -p "$TMP/failed-log-memory"
  cp "$MEM/never.md" "$TMP/failed-log-memory/never.md"
  OUT=$(PATH="$TMP/git-bin:$PATH" python3 "$SCRIPT" "$TMP/failed-log-memory" "$REPO" 2>/dev/null)
  RC=$?
  assert_eq 0 "$RC" "a failed git log exits 0"
  assert_empty "$OUT" "a failed git log never becomes a missing-history report"
}

script_guard_cases

# ─── Reviewer edge fixtures ──────────────────────────────────────────
EDGE_MEM="$TMP/edge-memory"
mkdir -p "$EDGE_MEM"
edge_memory() {  # edge_memory <file> <modified> <block-list anchors>
  {
    printf '%s\n' '---' "name: ${1%.md}" "modified: $2" 'anchors:' "$3" '---' 'Edge fixture.'
  } > "$EDGE_MEM/$1"
}
edge_memory next-clean.md 2026-01-15T00:00:00Z '  - app/[id]/page.tsx'
edge_memory next-dir.md 2026-01-15T00:00:00Z '  - app/[id]'
edge_memory next-changed.md 2026-01-15T00:00:00Z '  - app/[slug]/page.tsx'
edge_memory cjk.md 2026-01-15T00:00:00Z '  - docs/问题.md'
edge_memory deep-glob.md 2026-01-15T00:00:00Z '  - "**/foo_*.md"'
edge_memory commented.md 2026-01-15T00:00:00Z '  - src/a.py # tracked entry'
edge_memory commit-blob.md 2026-01-15T00:00:00Z "  - src/old.py
  - commit: $BLOB_SHA"
cat > "$EDGE_MEM/column-zero.md" <<'EOF'
---
name: column-zero
anchors:
- src/a.py
modified: 2026-01-15T00:00:00Z
tags:
  - src/old.py
---
Column-zero block sequence, followed by two top-level keys.
EOF
cat > "$EDGE_MEM/after-anchors.md" <<'EOF'
---
name: after-anchors
modified: 2026-01-15T00:00:00Z
anchors:
- src/old.py
tags:
  - src/a.py
---
Only the old anchor belongs to this memory.
EOF
cat > "$EDGE_MEM/unterminated-inline.md" <<'EOF'
---
name: unterminated-inline
modified: 2026-01-15T00:00:00Z
anchors: ["src/a.py]
---
An unterminated quote is not an anchor.
EOF

BRACKET_REPO="$TMP/repo[bracket]"
BRACKET_MEM="$TMP/bracket-memory"
mkdir -p "$BRACKET_REPO/src" "$BRACKET_MEM"
git init -q "$BRACKET_REPO"
git -C "$BRACKET_REPO" config user.name Fixture
git -C "$BRACKET_REPO" config user.email fixture@example.invalid
printf 'initial bracket root\n' > "$BRACKET_REPO/src/keep.py"
commit_all "$BRACKET_REPO" initial 2026-01-02T00:00:00Z || exit 1
cat > "$BRACKET_MEM/root-bracket.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - src/*.py
---
The repository root itself contains a bracket.
EOF

ORDER_REPO="$TMP/order-repo"
ORDER_MEM="$TMP/order-memory"
mkdir -p "$ORDER_REPO/src" "$ORDER_MEM"
git init -q "$ORDER_REPO"
git -C "$ORDER_REPO" config user.name Fixture
git -C "$ORDER_REPO" config user.email fixture@example.invalid
printf 'initial ordering\n' > "$ORDER_REPO/src/order.py"
commit_all "$ORDER_REPO" initial 2026-01-02T00:00:00Z || exit 1
printf 'highest timestamp\n' > "$ORDER_REPO/src/order.py"
commit_all "$ORDER_REPO" highest 2026-02-02T00:00:00Z || exit 1
printf 'later topology, earlier timestamp\n' > "$ORDER_REPO/src/order.py"
commit_all "$ORDER_REPO" earlier 2026-01-10T00:00:00Z || exit 1
cat > "$ORDER_MEM/order.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - src/order.py
---
Committer timestamps are not git log ordering.
EOF

WALK_REPO="$TMP/walk-repo"
WALK_MEM="$TMP/walk-memory"
PRUNE_MEM="$TMP/prune-memory"
PRUNED_MEM="$TMP/pruned-memory"
MISSING_MEM="$TMP/missing-prefix-memory"
DOTGIT_MEM="$TMP/dotgit-memory"
GLOBDIR_MEM="$TMP/globdir-memory"
UNREADABLE_MEM="$TMP/unreadable-memory"
mkdir -p "$WALK_REPO/src/match" "$WALK_REPO/sdk/a" "$WALK_REPO/unreadable" \
  "$WALK_MEM" "$PRUNE_MEM" "$PRUNED_MEM" "$MISSING_MEM" "$DOTGIT_MEM" \
  "$GLOBDIR_MEM" "$UNREADABLE_MEM"
git init -q "$WALK_REPO"
git -C "$WALK_REPO" config user.name Fixture
git -C "$WALK_REPO" config user.email fixture@example.invalid
printf 'seed\n' > "$WALK_REPO/seed"
printf 'initial direct source\n' > "$WALK_REPO/src/k.py"
printf 'initial nested source\n' > "$WALK_REPO/sdk/a/x.py"
commit_all "$WALK_REPO" initial 2026-01-02T00:00:00Z || exit 1
python3 - "$WALK_REPO" <<'PY'
import os, sys
for index in range(40):
    os.mkdir(os.path.join(sys.argv[1], "aaa-empty-%05d" % index))
os.mkdir(os.path.join(sys.argv[1], "src", "aaa-noise"))
for index in range(20):
    os.mkdir(os.path.join(sys.argv[1], "src", "aaa-noise", "empty-%05d" % index))
PY
printf 'later nested source\n' > "$WALK_REPO/sdk/a/x.py"
printf 'later globbed source\n' > "$WALK_REPO/src/match/k.py"
commit_all "$WALK_REPO" later 2026-02-02T00:00:00Z || exit 1
printf 'not a memory anchor match\n' > "$WALK_REPO/.git/ORIG_HEAD"
cat > "$WALK_MEM/walk.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - "**/no_such_file_*.zz"
---
A non-matching recursive glob must still observe the deadline.
EOF
cat > "$PRUNE_MEM/fixed-prefix.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - src/*.py
  - sdk
---
A fixed-prefix glob must not walk the unrelated root directories.
EOF
cat > "$PRUNED_MEM/pruned.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - src/*/*.py
---
Only directories that can still match may be descended.
EOF
cat > "$MISSING_MEM/missing-prefix.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - zz-missing/*.py
---
A missing literal prefix is an immediate missing anchor.
EOF
cat > "$DOTGIT_MEM/dotgit.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - "**/ORIG_HEAD"
---
A match under .git does not count as an existing anchor.
EOF
cat > "$GLOBDIR_MEM/glob-dir.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - sdk/*
---
A directory matched by a glob covers files below it.
EOF
cat > "$UNREADABLE_MEM/unreadable.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - unreadable/**/*.py
---
An unreadable directory must not hide other memories.
EOF
cat > "$UNREADABLE_MEM/unreadable-prefix.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - unreadable/sub/*.py
---
A literal prefix below an unreadable directory cannot be checked.
EOF
cat > "$UNREADABLE_MEM/sdk-stale.md" <<'EOF'
---
modified: 2026-01-15T00:00:00Z
anchors:
  - sdk
---
This finding must survive an unreadable directory elsewhere.
EOF

edge_guard_cases() {
  section "Literal brackets, raw git paths and YAML edge shapes"
  run_script "$EDGE_MEM" "$REPO"
  assert_eq 0 "$RC" "the reviewer edge scan exits 0"
  assert_not_contains "$OUT" 'next-clean.md:' "an unchanged literal [id] route is clean"
  assert_not_contains "$OUT" 'next-dir.md:' "an unchanged literal [id] directory anchor is clean"
  assert_contains "$OUT" '⚠STALE next-changed.md: app/[slug]/page.tsx changed 2026-02-02 (memory 2026-01-15)' \
    "a changed literal dynamic route reports its real commit date"
  assert_contains "$OUT" '⚠STALE cjk.md: docs/问题.md changed 2026-02-02 (memory 2026-01-15)' \
    "NUL-delimited git output preserves a CJK path"
  assert_not_contains "$OUT" 'deep-glob.md:' "a deep match below a ** glob is not falsely STALE"
  assert_contains "$OUT" 'column-zero.md: src/a.py changed 2026-02-02' \
    "a column-zero YAML block sequence is anchored"
  assert_not_contains "$OUT" 'after-anchors.md:' "a tags list after anchors is not swallowed"
  assert_contains "$OUT" 'commented.md: src/a.py changed 2026-02-02' \
    "an unquoted trailing YAML comment is stripped"
  assert_not_contains "$OUT" 'unterminated-inline.md:' "an unterminated inline quote is skipped"
  assert_contains "$OUT" "⚠STALE commit-blob.md: anchor commit $BLOB_SHA not in this repository" \
    "a blob cannot serve as a commit baseline"
  assert_eq 5 "$(grep -c '^⚠STALE ' <<< "$OUT")" "only the five positive reviewer edge fixtures emit lines"
  run_script "$EDGE_MEM" "$REPO" --review
  assert_not_contains "$OUT" 'column-zero.md:' "a column-zero anchored memory is not reported as unanchored"

  run_script "$BRACKET_MEM" "$BRACKET_REPO"
  assert_eq 0 "$RC" "a bracketed repository root exits 0"
  assert_empty "$OUT" "a bracketed repository root does not break glob existence"

  section "History ordering and non-commit objects"
  run_script "$ORDER_MEM" "$ORDER_REPO"
  assert_eq 0 "$RC" "the non-chronological history scan exits 0"
  assert_contains "$OUT" '⚠STALE order.md: src/order.py changed 2026-02-02 (memory 2026-01-15)' \
    "the maximum committer timestamp wins over git log order"

  section "Argument validation"
  run_script "$EDGE_MEM" "$REPO" --review --days -1
  assert_eq 2 "$RC" "negative --days is rejected"
  assert_contains "$(cat "$TMP/script-stderr")" 'non-negative' "negative --days explains the error"
  run_script "$EDGE_MEM" "$REPO" --budget -1
  assert_eq 2 "$RC" "negative --budget is rejected"
  assert_contains "$(cat "$TMP/script-stderr")" 'non-negative' "negative --budget explains the error"

  section "A recursive glob walk observes its deadline"
  run_script "$WALK_MEM" "$WALK_REPO" --budget 30
  assert_eq 0 "$RC" "the unbounded non-matching walk exits 0"
  assert_contains "$OUT" '⚠STALE walk.md:' "the unbounded walk completes and reports the missing anchor"
  run_scan_harness walk-timeout "$WALK_MEM" "$WALK_REPO" "$TMP/walk-timeout-scans" 0.05
  assert_eq 0 "$RC" "a deterministic directory deadline exits 0"
  assert_incomplete "a deterministic directory deadline"
  assert_contains "$(cat "$TMP/walk-timeout-scans")" "$WALK_REPO" \
    "the deadline is forced inside the repository walk"
}

edge_guard_cases

final_edge_guard_cases() {
  section "Literal prefixes and pruned directory walks"
  run_scan_harness record "$PRUNE_MEM" "$WALK_REPO" "$TMP/fixed-prefix-scans" 30
  assert_eq 0 "$RC" "a fixed-prefix glob exits 0 with a large budget"
  assert_contains "$OUT" '⚠STALE fixed-prefix.md: sdk changed 2026-02-02 (memory 2026-01-15)' \
    "a fixed-prefix glob does not hide another anchor's finding"
  assert_eq 1 "$(wc -l < "$TMP/fixed-prefix-scans" | tr -d ' ')" \
    "a fixed-prefix match opens exactly one directory"
  assert_eq "$WALK_REPO/src" "$(cat "$TMP/fixed-prefix-scans")" \
    "a fixed-prefix match never opens the unrelated tree"
  run_scan_harness record "$PRUNED_MEM" "$WALK_REPO" "$TMP/pruned-scans" 30
  assert_eq 0 "$RC" "a segment-pruned glob exits 0 with a large budget"
  assert_contains "$OUT" '⚠STALE pruned.md: src/*/*.py changed 2026-02-02 (memory 2026-01-15)' \
    "segment pruning avoids unrelated nested directories"
  assert_contains "$(cat "$TMP/pruned-scans")" "$WALK_REPO/src/aaa-noise" \
    "the pruned walk may open a first-level directory matched by the star"
  assert_not_contains "$(cat "$TMP/pruned-scans")" '/aaa-empty-' \
    "the segment-pruned walk never opens the unrelated root tree"
  assert_not_contains "$(cat "$TMP/pruned-scans")" '/src/aaa-noise/empty-' \
    "the segment-pruned walk never opens a directory the next segment cannot match"
  run_scan_harness record "$MISSING_MEM" "$WALK_REPO" "$TMP/missing-prefix-scans" 30
  assert_eq 0 "$RC" "a missing literal prefix exits 0 with a large budget"
  assert_contains "$OUT" '⚠STALE missing-prefix.md: zz-missing/*.py changed unknown (memory 2026-01-15)' \
    "a missing literal prefix reports STALE without walking"
  assert_empty "$(cat "$TMP/missing-prefix-scans")" "a missing literal prefix opens no directory"
  assert_not_contains "$OUT" '⚠STALE-CHECK incomplete' "a missing prefix does not exhaust the budget"

  section "Git metadata and directory-covering globs"
  run_script "$DOTGIT_MEM" "$WALK_REPO" --budget 30
  assert_eq 0 "$RC" "the .git exclusion scan exits 0"
  assert_contains "$OUT" '⚠STALE dotgit.md: **/ORIG_HEAD changed unknown (memory 2026-01-15)' \
    "a match only under .git is still a missing anchor"
  run_script "$GLOBDIR_MEM" "$WALK_REPO"
  assert_eq 0 "$RC" "the directory-covering glob scan exits 0"
  assert_contains "$OUT" '⚠STALE glob-dir.md: sdk/* changed 2026-02-02 (memory 2026-01-15)' \
    "a glob matching a directory covers changed files below it"

  if [[ "$(id -u)" -eq 0 ]]; then
    printf '  SKIP: unreadable-directory guard (root ignores chmod 000)\n'
  else
    chmod 000 "$WALK_REPO/unreadable"
    run_script "$UNREADABLE_MEM" "$WALK_REPO" --budget 30
    chmod 700 "$WALK_REPO/unreadable"
    assert_eq 0 "$RC" "an unreadable directory does not fail the scan"
    assert_contains "$OUT" '⚠STALE sdk-stale.md: sdk changed 2026-02-02 (memory 2026-01-15)' \
      "an unreadable directory does not hide another memory's finding"
    assert_contains "$OUT" '⚠STALE unreadable-prefix.md: unreadable/sub/*.py' \
      "a glob prefix below an unreadable directory reports as missing"
  fi
}

final_edge_guard_cases

# ─── Verifier fixtures: spellings and refs that used to read as clean ─
VER_REPO="$TMP/verifier-repo"
VER_MEM="$TMP/verifier-memory"
mkdir -p "$VER_REPO/nested" "$VER_MEM"
git init -q "$VER_REPO"
git -C "$VER_REPO" config user.name Fixture
git -C "$VER_REPO" config user.email fixture@example.invalid
printf 'initial root\n' > "$VER_REPO/root.md"
printf 'initial nested\n' > "$VER_REPO/nested/keep.py"
commit_all "$VER_REPO" initial 2026-01-02T00:00:00Z || exit 1
printf 'later root\n' > "$VER_REPO/root.md"
printf 'later nested\n' > "$VER_REPO/nested/keep.py"
commit_all "$VER_REPO" later 2026-02-02T00:00:00Z || exit 1
VER_HEAD=$(git -C "$VER_REPO" rev-parse HEAD)
# Two blobs sharing a 7-hex prefix that sorts BEFORE VER_HEAD, so a parser that
# stops at "<prefix> ambiguous" loses the valid baseline listed after it.
AMBIGUOUS=$(python3 - "$VER_HEAD" <<'PY'
import hashlib, sys
seen = {}
index = 0
while True:
    content = b"ambiguity-%d\n" % index
    prefix = hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()[:7]
    if prefix in seen and prefix < sys.argv[1]:
        print(prefix, seen[prefix].decode().strip(), content.decode().strip())
        break
    seen.setdefault(prefix, content)
    index += 1
PY
)
read -r AMBIGUOUS_PREFIX AMBIGUOUS_ONE AMBIGUOUS_TWO <<< "$AMBIGUOUS"
printf '%s\n' "$AMBIGUOUS_ONE" | git -C "$VER_REPO" hash-object -w --stdin >/dev/null
printf '%s\n' "$AMBIGUOUS_TWO" | git -C "$VER_REPO" hash-object -w --stdin >/dev/null
ver_memory() {  # ver_memory <file> <block-list anchors>
  printf '%s\n' '---' "name: ${1%.md}" 'modified: 2026-01-15T00:00:00Z' 'anchors:' "$2" '---' 'Verifier fixture.' \
    > "$VER_MEM/$1"
}
ver_memory root-doublestar.md '  - "**/root.md"'
ver_memory dot-slash.md '  - ./nested/keep.py'
ver_memory pathless-unknown.md '  - commit: cafebabe'
ver_memory ambiguous.md "  - nested/keep.py
  - commit: $AMBIGUOUS_PREFIX"
ver_memory after-ambiguous.md "  - nested/keep.py
  - commit: $VER_HEAD"

verifier_edge_cases() {
  section "Root-level ** matches, ./ spellings and unresolvable refs"
  if [[ "$(printf '%s\n' "$AMBIGUOUS_PREFIX" | git -C "$VER_REPO" cat-file --batch 2>/dev/null)" == "$AMBIGUOUS_PREFIX ambiguous" ]]; then
    pass "fixture: $AMBIGUOUS_PREFIX is ambiguous and sorts before the valid baseline"
  else
    fail "fixture: $AMBIGUOUS_PREFIX is ambiguous and sorts before the valid baseline"
  fi
  run_script "$VER_MEM" "$VER_REPO"
  assert_eq 0 "$RC" "the verifier edge scan exits 0"
  assert_contains "$OUT" '⚠STALE root-doublestar.md: **/root.md changed 2026-02-02 (memory 2026-01-15)' \
    "**/x sees the history of a root-level x"
  assert_contains "$OUT" '⚠STALE dot-slash.md: nested/keep.py changed 2026-02-02 (memory 2026-01-15)' \
    "a ./-prefixed anchor matches git's repository-relative paths"
  assert_not_contains "$OUT" 'pathless-unknown.md:' "a pathless commit anchor is never STALE, even when unknown"
  assert_contains "$OUT" "⚠STALE ambiguous.md: anchor commit $AMBIGUOUS_PREFIX not in this repository" \
    "an ambiguous short baseline does not resolve"
  assert_not_contains "$OUT" 'after-ambiguous.md:' "an ambiguous ref does not hide the valid baseline after it"
  assert_eq 3 "$(grep -c '^⚠STALE ' <<< "$OUT")" "only the three positive verifier fixtures emit lines"
}

verifier_edge_cases

# ─── Hook fixtures and end-to-end cases ──────────────────────────────
HOOK_SESSION="$TMP/hook session"
HOOK_MEM="$HOOK_SESSION/memory"
HOOK_PROJECT="$TMP/hook-project"
HOOK_TRANSCRIPT="$HOOK_SESSION/transcript.jsonl"

setup_hook_fixture() {
  rm -rf "$HOOK_SESSION" "$HOOK_PROJECT" "$HOME/.claude"
  mkdir -p "$HOOK_MEM" "$HOOK_PROJECT"
  git init -q "$HOOK_PROJECT"
  git -C "$HOOK_PROJECT" config user.name Fixture
  git -C "$HOOK_PROJECT" config user.email fixture@example.invalid
  local i
  for i in $(seq 1 12); do printf 'initial %s\n' "$i" > "$HOOK_PROJECT/hook-$i.py"; done
  commit_all "$HOOK_PROJECT" initial 2026-01-02T00:00:00Z || return 1
  for i in $(seq 1 12); do printf 'later %s\n' "$i" > "$HOOK_PROJECT/hook-$i.py"; done
  commit_all "$HOOK_PROJECT" later 2026-02-02T00:00:00Z || return 1
  for i in $(seq 1 12); do
    local file
    file=$(printf 'hook%02d.md' "$i")
    {
      printf '%s\n' '---' "name: ${file%.md}" 'modified: 2026-01-15T00:00:00Z' 'anchors:'
      printf '  - hook-%s.py\n' "$i"
      printf '%s\n' '---' 'Hook fixture.'
    } > "$HOOK_MEM/$file"
    printf -- '- [%s](%s) — fixture\n' "$file" "$file" >> "$HOOK_MEM/MEMORY.md"
  done
  cat > "$HOOK_MEM/clean.md" <<'EOF'
---
modified: 2026-02-03T00:00:00Z
anchors:
  - hook-1.py
---
Clean.
EOF
  cat > "$HOOK_MEM/old-unanchored.md" <<'EOF'
---
modified: 2025-01-01T00:00:00Z
---
Old but deliberately not part of the per-session review output.
EOF
}

hook_payload() {  # hook_payload <transcript> <cwd>
  python3 - "$1" "$2" <<'PY'
import json, sys
print(json.dumps({"transcript_path": sys.argv[1], "cwd": sys.argv[2]}))
PY
}

run_hook() {  # run_hook <transcript> <cwd> [hook]
  local payload
  payload=$(hook_payload "$1" "$2")
  OUT=$(printf '%s' "$payload" | bash "${3:-$HOOK}" 2>"$TMP/hook-stderr")
  RC=$?
}

hook_guard_cases() {
  section "SessionStart hook"
  setup_hook_fixture || { fail "hook fixture setup"; return; }
  local before after clean_session no_repo_session layout
  before=$(cksum "$HOOK_MEM/MEMORY.md")
  run_hook "$HOOK_TRANSCRIPT" "$HOOK_PROJECT"
  assert_eq 0 "$RC" "the hook exits 0"
  assert_contains "$OUT" '## Memory staleness' "the hook prints its context header"
  assert_eq 10 "$(grep -c '^⚠STALE ' <<< "$OUT")" "the hook caps stale lines at 10"
  assert_contains "$OUT" '... and 2 more' "the cap says how many lines were omitted"
  assert_not_contains "$OUT" 'hook11.md:' "the eleventh stale memory is omitted"
  assert_not_contains "$OUT" 'hook12.md:' "the twelfth stale memory is omitted"
  assert_not_contains "$OUT" '⚠REVIEW' "the per-session hook does not turn review into daily noise"
  after=$(cksum "$HOOK_MEM/MEMORY.md")
  assert_eq "$before" "$after" "the hook never rewrites MEMORY.md"

  clean_session="$TMP/clean-session"
  mkdir -p "$clean_session/memory"
  cp "$HOOK_MEM/clean.md" "$clean_session/memory/clean.md"
  run_hook "$clean_session/transcript.jsonl" "$HOOK_PROJECT"
  assert_eq 0 "$RC" "a clean hook run exits 0"
  assert_empty "$OUT" "no stale anchors means no header"

  run_hook "$TMP/no-memory/transcript.jsonl" "$HOOK_PROJECT"
  assert_eq 0 "$RC" "a missing memory directory exits 0"
  assert_empty "$OUT" "a missing memory directory is silent"

  no_repo_session="$TMP/no-repo-session"
  mkdir -p "$no_repo_session/memory" "$TMP/no-repo"
  cp "$HOOK_MEM/hook01.md" "$no_repo_session/memory/hook01.md"
  run_hook "$no_repo_session/transcript.jsonl" "$TMP/no-repo"
  assert_eq 0 "$RC" "a non-git project hook exits 0"
  assert_empty "$OUT" "a non-git project hook is silent"

  OUT=$(printf '{' | bash "$HOOK" 2>/dev/null)
  RC=$?
  assert_eq 0 "$RC" "malformed hook JSON exits 0"
  assert_empty "$OUT" "malformed hook JSON is silent"
  OUT=$(printf '{}' | bash "$HOOK" 2>/dev/null)
  assert_empty "$OUT" "missing transcript/cwd fields are silent"

  mkdir -p "$HOOK_PROJECT/memory"
  cp "$HOOK_MEM/hook01.md" "$HOOK_PROJECT/memory/hook01.md"
  OUT=$(python3 - "$HOOK_PROJECT" <<'PY' | (cd "$HOOK_PROJECT" && bash "$HOOK" 2>/dev/null)
import json, sys
print(json.dumps({"cwd": sys.argv[1]}))
PY
)
  RC=$?
  assert_eq 0 "$RC" "cwd without transcript_path exits 0"
  assert_empty "$OUT" "cwd without transcript_path never derives ./memory"
  OUT=$(python3 - "$HOOK_TRANSCRIPT" <<'PY' | (cd "$HOOK_PROJECT" && bash "$HOOK" 2>/dev/null)
import json, sys
print(json.dumps({"transcript_path": sys.argv[1]}))
PY
)
  RC=$?
  assert_eq 0 "$RC" "transcript_path without cwd exits 0"
  assert_empty "$OUT" "transcript_path without cwd never uses the process repository"

  layout="$TMP/failing-layout"
  rm -rf "$layout"
  mkdir -p "$layout/hooks" "$layout/scripts"
  cp "$HOOK" "$layout/hooks/memory-staleness.sh"
  cat > "$layout/scripts/memory-staleness.py" <<'EOF'
#!/usr/bin/env python3
import sys
print('⚠STALE fake.md: x changed 2026-02-02 (memory 2026-01-01)')
sys.exit(1)
EOF
  run_hook "$HOOK_TRANSCRIPT" "$HOOK_PROJECT" "$layout/hooks/memory-staleness.sh"
  assert_eq 0 "$RC" "a failing checker never fails the hook"
  assert_empty "$OUT" "output from a failing checker is withheld"

  cat > "$layout/scripts/memory-staleness.py" <<'EOF'
#!/usr/bin/env python3
print('⚠STALE fake.md: x changed 2026-02-02 (memory 2026-01-01)')
EOF
  run_hook "$TMP/no-memory/transcript.jsonl" "$HOOK_PROJECT" "$layout/hooks/memory-staleness.sh"
  assert_empty "$OUT" "the no-memory guard runs before the checker"

  layout="$TMP/missing-layout"
  rm -rf "$layout"
  mkdir -p "$layout/hooks"
  cp "$HOOK" "$layout/hooks/memory-staleness.sh"
  run_hook "$HOOK_TRANSCRIPT" "$HOOK_PROJECT" "$layout/hooks/memory-staleness.sh"
  assert_eq 0 "$RC" "a missing checker exits 0"
  assert_empty "$OUT" "a missing checker is silent"

  layout="$TMP/installed-layout"
  rm -rf "$layout" "$HOME/.claude"
  mkdir -p "$layout/hooks" "$HOME/.claude/scripts"
  cp "$HOOK" "$layout/hooks/memory-staleness.sh"
  cp "$REAL_SCRIPT" "$HOME/.claude/scripts/memory-staleness.py"
  run_hook "$HOOK_TRANSCRIPT" "$HOOK_PROJECT" "$layout/hooks/memory-staleness.sh"
  assert_contains "$OUT" '## Memory staleness' "the installed ~/.claude/scripts copy is found"

  mkdir -p "$TMP/nopy"
  ln -sf "$(command -v cat)" "$TMP/nopy/cat"
  OUT=$(hook_payload "$HOOK_TRANSCRIPT" "$HOOK_PROJECT" | PATH="$TMP/nopy" "$(command -v bash)" "$HOOK" 2>/dev/null)
  RC=$?
  assert_eq 0 "$RC" "no python3 on PATH exits 0"
  assert_empty "$OUT" "no python3 on PATH is silent"
}

hook_guard_cases

hook_timeout_case() {
  section "SessionStart hook reports an incomplete check"
  mkdir -p "$TMP/timeout-hook-python"
  printf '#!%s\n' "$REAL_PYTHON" > "$TMP/timeout-hook-python/python3"
  cat >> "$TMP/timeout-hook-python/python3" <<'PY'
import os
import runpy
import subprocess
import sys

if sys.argv[1] == "-c":
    os.execv(os.environ["REAL_PYTHON"], [os.environ["REAL_PYTHON"], *sys.argv[1:]])
real_run = subprocess.run


def fake_run(command, *args, **kwargs):
    if "log" in command[1:] and kwargs.get("timeout") is not None:
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 0))
    return real_run(command, *args, **kwargs)


subprocess.run = fake_run
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
PY
  chmod +x "$TMP/timeout-hook-python/python3"
  local payload
  payload=$(hook_payload "$HOOK_TRANSCRIPT" "$HOOK_PROJECT")
  OUT=$(printf '%s' "$payload" | PATH="$TMP/timeout-hook-python:$PATH" bash "$HOOK" 2>/dev/null)
  RC=$?
  assert_eq 0 "$RC" "a timed-out hook exits 0"
  assert_contains "$OUT" '## Memory staleness' "a timed-out hook still prints its header"
  assert_incomplete "a timed-out hook" 2
}

hook_timeout_case

section "Wiring and deployment"
python3 - "$REPO_ROOT/configs/settings-hooks.json" <<'PY'
import json, sys
settings = json.load(open(sys.argv[1], encoding="utf-8"))
entries = [h for group in settings["hooks"]["SessionStart"] for h in group["hooks"]
           if h.get("id") == "memory-staleness"]
assert len(entries) == 1, "memory-staleness must have one SessionStart entry"
entry = entries[0]
assert entry["command"].endswith("/hooks/memory-staleness.sh")
assert isinstance(entry.get("timeout"), int) and 0 < entry["timeout"] <= 10
assert not entry.get("async"), "stdout must reach SessionStart context synchronously"
PY
if [[ $? -eq 0 ]]; then pass "settings-hooks.json wires a synchronous, bounded SessionStart hook"
else fail "settings-hooks.json wires a synchronous, bounded SessionStart hook"; fi
if grep -qF 'cp "$SCRIPT_DIR/configs/hooks/"*.sh' "$REPO_ROOT/install.sh" && \
   grep -qF 'for f in "$SCRIPT_DIR/configs/scripts/"*.py' "$REPO_ROOT/install.sh"; then
  pass "install.sh's existing sweeps deploy both new files"
else
  fail "install.sh's existing sweeps deploy both new files"
fi
if [[ -x "$REPO_ROOT/configs/hooks/memory-staleness.sh" ]]; then
  pass "the shipped hook is executable"
else
  fail "the shipped hook is executable"
fi

# ─── Guard mutations ─────────────────────────────────────────────────
section "Each Python guard turns the behavioral cases red when removed"
MUT_ROOT="$TMP/mutations"
mkdir -p "$MUT_ROOT"
python_mutation() {  # python_mutation <red|green> <name> <anchor> <replacement> [cases]
  local want="$1" name="$2" failed cases="${5:-script_guard_cases}"
  if ! python3 - "$REAL_SCRIPT" "$MUT_ROOT/memory-staleness.py" "$3" "$4" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
if src.count(sys.argv[3]) != 1:
    sys.exit(3)
open(sys.argv[2], "w", encoding="utf-8").write(src.replace(sys.argv[3], sys.argv[4], 1))
PY
  then
    fail "Python mutation '$name': anchor does not occur exactly once"
    return 0
  fi
  failed=$(SCRIPT="$MUT_ROOT/memory-staleness.py"; TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
           "$cases" >/dev/null 2>&1; echo "$TESTS_FAILED")
  if [[ "$want" == red && "$failed" -gt 0 ]]; then
    pass "removing $name turns the script cases red ($failed failed)"
  elif [[ "$want" == green && "$failed" -eq 0 ]]; then
    pass "unchanged Python control stays green: $name"
  else
    fail "Python mutation '$name' (want $want)" "$failed script case(s) failed"
  fi
}

python_mutation green "an unchanged docstring control" \
  "Only Python's standard library is used, and no file is modified." \
  "Only Python's standard library is used; no file is modified."
python_mutation red "the closed-frontmatter requirement" '    if closing is None:
        return None, ()' '    if closing is None:
        closing = len(lines)'
python_mutation red "repo-relative anchor validation" '    if not value or value.startswith(("/", ":")) or ".." in PurePosixPath(value).parts:
        return None' '    if False:
        return None'
python_mutation red "inline-list parsing" '        if raw.startswith("[") and raw.endswith("]"):' \
  '        if False:'
python_mutation red "block-list parsing" '                if item:' '                if False:'
python_mutation red "the no-anchor fast path" '    if not any(anchor.kind == "path" for memory in memories for anchor in memory.anchors):
        return []' '    if False:
        return []'
python_mutation red "mtime fallback" \
  '        modified = modified if modified is not None else path.stat().st_mtime' \
  '        modified = time.time()'
python_mutation red "MEMORY.md exclusion" '    if path.name == "MEMORY.md" or not path.is_file():' \
  '    if not path.is_file():'
python_mutation red "batched path history" '    if default_path_anchors:' '    if False:'
python_mutation red "the missing-anchor rule" '        if not _anchor_exists(root, anchor, deadline):' \
  '        if False:'
python_mutation red "the newer-than-memory comparison" \
  '        elif latest is not None and latest > memory.modified:' '        elif False:'
python_mutation red "glob history matching" \
  '    return _has_glob(anchor) and _glob_covers(anchor, path)' '    return False'
python_mutation red "plain-path existence" '    if (root / anchor.value).exists():' \
  '    if True:'
python_mutation red "glob existence" \
  '            if _glob_match(anchor.value, relative) and os.path.exists(entry.path):' \
  '            if _glob_match(anchor.value, relative) and False:'
python_mutation red "directory-anchor matching" \
  '    if path == anchor or path.startswith(anchor.rstrip("/") + "/"):' \
  '    if path == anchor:'
python_mutation red "scalar path parsing" \
  '    return _path_anchor(value)' '    return None'
python_mutation red "commit SHA validation" \
  '        if re.fullmatch(r"[0-9a-fA-F]{7,40}", sha):' '        if False:'
python_mutation red "non-empty baseline range staleness" \
  '            if latest is not None:' '            if False:'
python_mutation red "baseline range history selection" \
  '        memory_history = baseline_histories.get(anchored[0], {})' \
  '        memory_history = history'
python_mutation red "unknown-baseline reporting" \
  '        anchored = commits.get(baseline.value)' \
  '        anchored = commits.get(baseline.value) or ("", 0)'
python_mutation red "batched baseline range logs" \
  '    for oid, paths in sorted(baseline_paths.items()):' \
  '    for oid, paths in ():'
python_mutation red "pathless commit-anchor review" \
  '        if _baseline(memory) is not None and not any(anchor.kind == "path" for anchor in memory.anchors):' \
  '        if False:'
python_mutation red "anchored-memory review exclusion" '        if memory.anchors:' '        if False:'
python_mutation red "review age filtering" '        if memory.modified >= cutoff:' '        if False:'
python_mutation red "the git-call deadline" '    remaining = deadline.remaining()' '    remaining = 10.0'
python_mutation red "the subprocess timeout" '            timeout=remaining,' '            timeout=None,'
python_mutation red "failed-history suppression" '        if output is None:
            return []
        history = _history(output)' '        if output is None:
            output = b""
        history = _history(output)'
python_mutation red "the git exit-status check" \
  '    return proc.stdout if proc.returncode == 0 else None' '    return proc.stdout'
python_mutation red "literal-before-glob history matching" '    if path == anchor or path.startswith(anchor.rstrip("/") + "/"):
        return True' '    if False:
        return True' edge_guard_cases
python_mutation red "literal-before-glob existence" '    if (root / anchor.value).exists():' \
  '    if False:' edge_guard_cases
python_mutation red "a name-ordered walk" '                entries = sorted(scanner, key=lambda entry: entry.name)' \
  '                entries = list(scanner)' final_edge_guard_cases
python_mutation red "the repository-root glob walk" '    pending = [(base, len(prefix))]' \
  '    pending = []' edge_guard_cases
python_mutation red "the per-directory walk deadline" '        current, pattern_index = pending.pop()
        if deadline.remaining() <= 0:
            raise BudgetExceeded()' '        current, pattern_index = pending.pop()
        if False:
            raise BudgetExceeded()' edge_guard_cases
python_mutation red "recursive double-star depth" '    if "**" in pattern[:index + 1]:
        return True
    if index >= len(pattern):
        return False' '    if index >= len(pattern):
        return False
    if "**" in pattern[:index + 1]:
        return True' edge_guard_cases
if [[ "$(id -u)" -eq 0 ]]; then
  printf '  SKIP: unreadable-directory mutation (root ignores chmod 000)\n'
else
  python_mutation red "an error-proof literal-prefix check" '    if not os.path.isdir(base):' \
    '    if not (os.stat(base).st_mode & 0o040000):' final_edge_guard_cases
  python_mutation red "per-directory scandir errors" '                entries = sorted(scanner, key=lambda entry: entry.name)
        except OSError:
            continue' '                entries = sorted(scanner, key=lambda entry: entry.name)
        except FileNotFoundError:
            continue' final_edge_guard_cases
fi
python_mutation red "NUL-delimited git history" \
  '_git_bytes(root, ["log", "--name-only", "-z", "--format=%ct"' \
  '_git_bytes(root, ["log", "--name-only", "--format=%ct"' edge_guard_cases
python_mutation red "column-zero YAML block items" \
  '                item = re.match(r"^[ \t]*-[ \t]*(.*?)\s*$", lines[index])' \
  '                item = re.match(r"^\s+-\s*(.*?)\s*$", lines[index])' edge_guard_cases
python_mutation red "the top-level block-list terminator" \
  '                elif re.match(r"^[A-Za-z_][A-Za-z0-9_-]*\s*:", lines[index]):' \
  '                elif False:' edge_guard_cases
python_mutation red "unterminated inline-quote rejection" '    if quote:
        return ()' '    if False:
        return ()' edge_guard_cases
python_mutation red "unquoted trailing-comment stripping" \
  '        return value.split(" #", 1)[0].rstrip()' '        return value.rstrip()' edge_guard_cases
python_mutation red "non-commit object rejection" '        if header[1] != b"commit":' \
  '        if False:' edge_guard_cases
python_mutation red "negative argument rejection" \
  '    if args.days < 0 or args.budget < 0:' '    if False:' edge_guard_cases
python_mutation red "maximum timestamp history" \
  '        history[path] = max(timestamp, history.get(path, timestamp))' \
  '        history.setdefault(path, timestamp)' edge_guard_cases
python_mutation red "the budget-exhaustion notice" '    except BudgetExceeded:
        lines = [_incomplete(args.memory_dir, args.project_dir, args.budget, args.review)]' \
  '    except BudgetExceeded:
        return 0'
python_mutation red "the literal-prefix walk root" '    base = root.joinpath(*prefix)' \
  '    base = root' final_edge_guard_cases
python_mutation red "segment-by-segment descent pruning" \
  '    return fnmatch.fnmatchcase(name, pattern[index])' '    return True' final_edge_guard_cases
python_mutation red "the missing-prefix short-circuit" '    if not os.path.isdir(base):' \
  '    if False:' final_edge_guard_cases
python_mutation red "the .git exclusion" '            if ".git" in relative.split("/"):' \
  '            if False:' final_edge_guard_cases
python_mutation red "directory-covering glob history" \
  '    return any(_glob_match(pattern, "/".join(parts[:end])) for end in range(1, len(parts) + 1))' \
  '    return _glob_match(pattern, path)' final_edge_guard_cases
python_mutation red "root-level ** history (glob pathspecs)" \
  '            specs.add(":(glob)" + anchor)' '            pass' verifier_edge_cases
python_mutation red "** matching zero directories" \
  '            return (match(pattern_index + 1, path_index) or
                    (path_index < len(path_parts) and match(pattern_index, path_index + 1)))' \
  '            return (path_index < len(path_parts) and
                    (match(pattern_index + 1, path_index + 1) or match(pattern_index, path_index + 1)))' \
  verifier_edge_cases
python_mutation red "./ anchor normalisation" \
  '    value = "/".join(part for part in value.split("/") if part not in ("", "."))' \
  '    pass' verifier_edge_cases
python_mutation red "unresolvable-ref parsing past an ambiguous ref" \
  '        if len(header) == 2:  # "<ref> missing" or "<ref> ambiguous": no body follows' \
  '        if len(header) == 2 and header[1] == b"missing":' verifier_edge_cases
python_mutation red "the pathless commit-anchor guard" '    if not path_anchors:
        return None' '    if False:
        return None' verifier_edge_cases

section "Each hook guard turns the end-to-end cases red when removed"
mkdir -p "$MUT_ROOT/hooks"
ln -sfn "$REPO_ROOT/configs/scripts" "$MUT_ROOT/scripts"
hook_mutation() {  # hook_mutation <red|green> <name> <exact anchor> <replacement>
  local want="$1" name="$2" failed
  if ! python3 - "$REAL_HOOK" "$MUT_ROOT/hooks/memory-staleness.sh" "$3" "$4" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
if src.count(sys.argv[3]) != 1:
    sys.exit(3)
open(sys.argv[2], "w", encoding="utf-8").write(src.replace(sys.argv[3], sys.argv[4], 1))
PY
  then
    fail "hook mutation '$name': anchor does not occur exactly once"
    return 0
  fi
  failed=$(HOOK="$MUT_ROOT/hooks/memory-staleness.sh"; TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
           hook_guard_cases >/dev/null 2>&1; echo "$TESTS_FAILED")
  if [[ "$want" == red && "$failed" -gt 0 ]]; then
    pass "removing $name turns the hook cases red ($failed failed)"
  elif [[ "$want" == green && "$failed" -eq 0 ]]; then
    pass "unchanged hook control stays green: $name"
  else
    fail "hook mutation '$name' (want $want)" "$failed hook case(s) failed"
  fi
}

hook_mutation green "an unchanged comment control" \
  '# deliberately read-only: it lives in the multi-host sync store.' \
  '# deliberately read-only:  it lives in the multi-host sync store.'
hook_mutation red "stdin reading" 'INPUT=$(cat 2>/dev/null || true)' 'INPUT=""'
hook_mutation red "required hook-input fields" \
  '[ -n "$TRANSCRIPT_PATH" ] && [ -n "$CWD" ] || exit 0' ':'
hook_mutation red "the missing-memory-directory guard" '[ -d "$MEMORY_DIR" ] || exit 0' ':'
hook_mutation red "transcript_path memory derivation" \
  'TRANSCRIPT_DIR=$(dirname "$TRANSCRIPT_PATH" 2>/dev/null) || exit 0' \
  'TRANSCRIPT_DIR="/nonexistent"'
hook_mutation red "cwd project selection" 'PROJECT_DIR="$CWD"' 'PROJECT_DIR="/nonexistent"'
hook_mutation red "the sibling script fallback" 'if [ ! -f "$SCRIPT" ]; then' 'if false; then'
hook_mutation red "checker failure suppression" \
  'OUTPUT=$(python3 "$SCRIPT" "$MEMORY_DIR" "$PROJECT_DIR" 2>/dev/null) || exit 0' \
  'OUTPUT=$(python3 "$SCRIPT" "$MEMORY_DIR" "$PROJECT_DIR" 2>/dev/null)'
hook_mutation red "silent-empty output" '[ -n "$OUTPUT" ] || exit 0' ':'
hook_mutation red "the ten-line cap" 'printf '"'"'%s\n'"'"' "$OUTPUT" | head -n 10' \
  'printf '"'"'%s\n'"'"' "$OUTPUT" | cat'
hook_mutation red "the omitted-line count" 'if [ "$TOTAL" -gt 10 ]; then' 'if false; then'

printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
if [[ "$TESTS_FAILED" -eq 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}FAILED${NC} (%d/%d passed, %d failed)\n" "$TESTS_PASSED" "$TESTS_RUN" "$TESTS_FAILED"
fi
printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
[[ "$TESTS_FAILED" -eq 0 ]]
