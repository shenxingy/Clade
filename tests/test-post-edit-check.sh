#!/usr/bin/env bash
# test-post-edit-check.sh — post-edit-check.sh tests, split out of tests/test-hooks.sh when the combined file
# crossed the 1500-line rule (2026-11-04).
#
#   post-edit-check.sh      findings -> stderr + exit 2; clean -> silent exit 0; outside/vanished paths; the
#                           per-file mypy scope (own errors only, missing stubs, project config), errors already
#                           in the file's HEAD version, a crashed checker, nested worktrees; the commit reminder
#
# Every path is redirected to throwaway dirs under /tmp; the real ~/.claude is never touched. No API calls.
#
# Usage:
#   bash tests/test-post-edit-check.sh        # Run all tests
#   bash tests/test-post-edit-check.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POST_EDIT_HOOK="$REPO_ROOT/configs/hooks/post-edit-check.sh"

# ─── Test framework (mirrors tests/test-hooks.sh) ───────
TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
VERBOSE="${1:-}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_eq() {
  local got="$1" want="$2" msg="$3"
  if [[ "$got" == "$want" ]]; then pass "$msg"
  else fail "$msg" "got '$got', want '$want'"; fi
}
assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  if grep -qF "$needle" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  fi
}
assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  if grep -qF "$needle" <<< "$haystack"; then
    fail "$msg" "output unexpectedly contains '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  else pass "$msg"; fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d /tmp/clade-hooks-test-XXXXXX)"
case "$TMP_ROOT" in
  /tmp/clade-hooks-test-*) : ;;
  *) echo "FATAL: sandbox '$TMP_ROOT' is not under /tmp — aborting"; exit 1 ;;
esac
trap 'rm -rf "$TMP_ROOT"' EXIT
# The sandbox HOME isolates ~/.claude, but a type checker installed with `pip --user` lives under the
# real HOME's ~/.local: without its user base, mypy crashed on import (ModuleNotFoundError), and the
# post-edit positive control below passed on the crash's non-zero exit (2026-11-04).
export PYTHONUSERBASE="${PYTHONUSERBASE:-$HOME/.local}"
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME/.claude"
# The repeat window (lib/typecheck.sh) would silence a case that re-reports an error an earlier case already
# reported for the same file; every case below runs without it except the one that tests it.
export POST_EDIT_REPEAT_WINDOW=0


# ─── 2. post-edit-check.sh ───────────────────────────────────────────

section "post-edit-check.sh — asyncRewake exit-2 delivery"

PROJ="$TMP_ROOT/proj"
mkdir -p "$PROJ"
git -C "$PROJ" init -q 2>/dev/null
git -C "$PROJ" config user.email "test@example.com"
git -C "$PROJ" config user.name "Test"
printf 'one\n' > "$PROJ/a.txt"; printf 'two\n' > "$PROJ/b.txt"; printf 'three\n' > "$PROJ/c.txt"
git -C "$PROJ" add -A >/dev/null 2>&1
git -C "$PROJ" commit -qm "base" >/dev/null 2>&1

run_post_edit() {  # <file_path> → sets RC / STDOUT_F / STDERR_F
  STDOUT_F="$TMP_ROOT/pe.out"; STDERR_F="$TMP_ROOT/pe.err"
  printf '{"tool_input":{"file_path":"%s"}}' "$1" \
    | CLAUDE_PROJECT_DIR="$PROJ" bash "$POST_EDIT_HOOK" \
      >"$STDOUT_F" 2>"$STDERR_F"
  RC=$?
}

# --- clean tree, unchecked file type: silent success, must NOT wake Claude ---
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "0" "clean check exits 0"
assert_eq "$(cat "$STDOUT_F")" "" "clean check writes nothing to stdout"
assert_eq "$(cat "$STDERR_F")" "" "clean check writes nothing to stderr (no wake)"

# --- a couple of dirty files must NOT wake Claude on the default threshold ---
# Every exit 2 interrupts the turn, and ordinary work sits above 2 uncommitted
# files almost permanently; a per-edit wake would train Claude to ignore the
# channel. Guards the default, so lowering it back is a visible test failure.
printf 'one changed\n' > "$PROJ/a.txt"
printf 'two changed\n' > "$PROJ/b.txt"
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "0" "2 dirty files stay below the default threshold (no wake)"
assert_eq "$(cat "$STDERR_F")" "" "sub-threshold dirty tree writes nothing to stderr"

# --- a path OUTSIDE the project is not this hook's business ---------
#
# The hook type-checked whatever `file_path` named and then ran the checker
# with the PROJECT as cwd, so a scratch probe written to /tmp that imports a
# repository module always failed on the import and woke the session with a
# finding about a file the project does not contain. Observed three times in
# one session on 2026-09-08, each one an interruption carrying nothing.
#
# It is the same shape as the guardian defect fixed the day before: the input
# was matched, never classified. A finding is only a finding about a file the
# project owns.
OUTSIDE="$TMP_ROOT/outside.py"
printf 'import definitely_not_a_real_module\n' > "$OUTSIDE"
run_post_edit "$OUTSIDE"
assert_eq "$RC" "0" "a file outside the project exits 0"
assert_eq "$(cat "$STDERR_F")" "" "a file outside the project never wakes Claude"

# --- a path that does not exist is a tool error, not a finding -------
# `mypy: can't read file ... No such file or directory` was being reported as
# "Type-check errors after editing", which is a false statement about the code.
GONE="$PROJ/deleted_right_after_the_write.py"
run_post_edit "$GONE"
assert_eq "$RC" "0" "a vanished file exits 0"
assert_eq "$(cat "$STDERR_F")" "" "a vanished file never wakes Claude"

# --- the containment check must not swallow a real finding -----------
# The point of the hook survives: a broken file INSIDE the project still wakes.
if command -v mypy >/dev/null 2>&1 || command -v pyright >/dev/null 2>&1; then
  BROKEN="$PROJ/broken.py"
  printf 'def f(x: int) -> str:\n    return x\n' > "$BROKEN"
  run_post_edit "$BROKEN"
  assert_eq "$RC" "2" "a type error inside the project still wakes Claude"
  assert_contains "$(cat "$STDERR_F")" "broken.py" "the finding names the file"
  # A diagnostic on the broken line, not a crashed checker: a crash also exits non-zero and names the
  # file in the heading, so only "broken.py:2" proves the checker ran.
  assert_contains "$(cat "$STDERR_F")" "broken.py:2" "the finding is a diagnostic on the broken line"
  rm -f "$BROKEN"
else
  echo "  (skipped: no mypy or pyright on PATH — the positive control needs one)"
fi

# --- mypy reports only the edited file's own errors (2026-11-04) -----------
# A bare `mypy FILE` followed the imports into a sibling module and reported its errors, and every
# missing third-party stub, as findings about the edited file. These cases need mypy itself (pyright,
# preferred when present, has its own import rules), and a project without its own mypy config.
if command -v mypy >/dev/null 2>&1 && ! command -v pyright >/dev/null 2>&1; then
  # Untracked files only: the uncommitted-file cases below count the tracked edits already in $PROJ.
  printf 'def g(x: int) -> str:\n    return x\n' > "$PROJ/sibling_bad.py"
  printf 'import sibling_bad\n\ndef h() -> int:\n    return 1\n' > "$PROJ/uses_sibling.py"
  run_post_edit "$PROJ/uses_sibling.py"
  assert_eq "$RC" "0" "a clean file is not blamed for an imported module's errors"
  assert_eq "$(cat "$STDERR_F")" "" "an imported module's errors never wake Claude"
  printf 'import definitely_not_a_real_module_xyz\n\ndef k() -> int:\n    return 2\n' > "$PROJ/uses_missing.py"
  run_post_edit "$PROJ/uses_missing.py"
  assert_eq "$RC" "0" "a missing third-party module is not a finding without a project mypy config"
  printf 'import definitely_not_a_real_module_xyz\n\ndef m(x: int) -> str:\n    return x\n' > "$PROJ/uses_missing_bad.py"
  run_post_edit "$PROJ/uses_missing_bad.py"
  assert_eq "$RC" "2" "a real error in the edited file still wakes beside a missing import"
  assert_contains "$(cat "$STDERR_F")" "uses_missing_bad.py:4" "that finding is the edited file's line 4"
  printf '[mypy]\n' > "$PROJ/mypy.ini"
  run_post_edit "$PROJ/uses_missing.py"
  assert_eq "$RC" "2" "with the project's own mypy config, its rules on missing imports decide"
  assert_contains "$(cat "$STDERR_F")" "uses_missing.py:1" "that finding is the missing import on line 1"
  rm -f "$PROJ/mypy.ini" "$PROJ/sibling_bad.py" "$PROJ/uses_sibling.py" "$PROJ/uses_missing.py" "$PROJ/uses_missing_bad.py"
else
  echo "  (skipped: the import-scope cases need mypy without pyright on PATH)"
fi

# --- an error the file already had at HEAD is not a finding about this edit (2026-11-04) ---------
# An agent editing a legacy file was woken after every edit by a `fcntl = None` fallback it never touched.
if command -v mypy >/dev/null 2>&1 && ! command -v pyright >/dev/null 2>&1; then
  printf 'import types\n\nmod: types.ModuleType = None\n' > "$PROJ/legacy_mod.py"
  git -C "$PROJ" add legacy_mod.py && git -C "$PROJ" commit -qm "legacy file with an old error" >/dev/null
  printf 'import types\n\nmod: types.ModuleType = None\n\ndef added() -> int:\n    return 1\n' > "$PROJ/legacy_mod.py"
  run_post_edit "$PROJ/legacy_mod.py"
  assert_eq "$RC" "0" "an error already in the file's HEAD version does not wake Claude"
  printf 'import types\n\nmod: types.ModuleType = None\n\ndef added() -> str:\n    return 1\n' > "$PROJ/legacy_mod.py"
  run_post_edit "$PROJ/legacy_mod.py"
  assert_eq "$RC" "2" "a new error in a legacy file still wakes Claude"
  assert_contains "$(cat "$STDERR_F")" "legacy_mod.py:6" "the finding is the new error's line"
  if grep -q "legacy_mod.py:3" "$STDERR_F"; then
    fail "the old HEAD error is not repeated" "stderr still lists legacy_mod.py:3"
  else
    pass "the old HEAD error is not repeated"
  fi
  git -C "$PROJ" checkout -- legacy_mod.py
  # A package module with a relative import: its HEAD copy must be checked AS that module (--shadow-file). A copy in a
  # temp dir could not resolve `from . import`, mypy stopped early, and every old error read as new (2026-11-04).
  mkdir -p "$PROJ/pkgrel"
  printf '' > "$PROJ/pkgrel/__init__.py"
  printf 'def h() -> int:\n    return 1\n' > "$PROJ/pkgrel/helper.py"
  printf 'from . import helper\n\nOLD: int = "x"\n' > "$PROJ/pkgrel/mod.py"
  git -C "$PROJ" add pkgrel && git -C "$PROJ" commit -qm "pkgrel with an old error" >/dev/null
  printf 'from . import helper\n\nOLD: int = "x"\n\n\ndef added() -> int:\n    return helper.h()\n' > "$PROJ/pkgrel/mod.py"
  run_post_edit "$PROJ/pkgrel/mod.py"
  assert_eq "$RC" "0" "a package module's old error is not new after an edit (relative import resolved)"
  git -C "$PROJ" checkout -- pkgrel/mod.py
  # mypy stops on a module clash before checking anything when a test imports a sibling both by bare name and through
  # its directory ("Source file found twice under different module names", docforensics tests, 2026-11-04). A clash
  # the HEAD version already has is the layout's, not the edit's: silent. A clash the edit introduces is reported.
  mkdir -p "$PROJ/clash"
  printf 'X: int = 1\n' > "$PROJ/clash/test_b.py"
  printf 'from test_b import X\nimport clash.test_b\n\nY = X\n' > "$PROJ/clash/test_a.py"
  printf 'from test_b import X\n\nZ = X\n' > "$PROJ/clash/test_c.py"
  git -C "$PROJ" add clash && git -C "$PROJ" commit -qm "clash fixture" >/dev/null
  printf 'from test_b import X\nimport clash.test_b\n\nY = X\n\n\ndef more() -> int:\n    return Y\n' > "$PROJ/clash/test_a.py"
  run_post_edit "$PROJ/clash/test_a.py"
  assert_eq "$RC" "0" "a module clash the HEAD version already has is not reported after an edit"
  git -C "$PROJ" checkout -- clash/test_a.py
  printf 'from test_b import X\nimport clash.test_b\n\nZ = X\n' > "$PROJ/clash/test_c.py"
  run_post_edit "$PROJ/clash/test_c.py"
  assert_eq "$RC" "2" "a module clash the edit introduces is still reported"
  git -C "$PROJ" checkout -- clash/test_c.py
  # A crashed checker has no error line to compare: it must still wake Claude, never be filtered to silence.
  CRASH_BIN="$TMP_ROOT/crash-mypy-bin"; mkdir -p "$CRASH_BIN"
  printf '#!/bin/sh\necho "Traceback (most recent call last):"\necho "RuntimeError: fake mypy crash"\nexit 2\n' > "$CRASH_BIN/mypy"
  chmod +x "$CRASH_BIN/mypy"
  OLD_PATH="$PATH"; export PATH="$CRASH_BIN:$PATH"
  run_post_edit "$PROJ/legacy_mod.py"
  export PATH="$OLD_PATH"
  assert_eq "$RC" "2" "a crashed checker on a tracked file still wakes Claude"
  assert_contains "$(cat "$STDERR_F")" "fake mypy crash" "the crash text reaches Claude unfiltered"
  printf 'def fresh(x: int) -> str:\n    return x\n' > "$PROJ/fresh_new.py"
  run_post_edit "$PROJ/fresh_new.py"
  assert_eq "$RC" "2" "a file git does not know yet reports every error"
  rm -f "$PROJ/fresh_new.py"
else
  echo "  (skipped: the HEAD-baseline cases need mypy without pyright on PATH)"
fi

# --- only the edited file's own lines count; other files' errors are not this edit's (2026-11-04) ----------
# mypy reported an imported module's errors even with --follow-imports=silent: editing tests/test_gc_tuning.py woke
# a session about docforensics/gc_tuning.py. A fake mypy pins the shape: errors in two files.
if ! command -v pyright >/dev/null 2>&1; then
  OF_BIN="$TMP_ROOT/twofile-mypy-bin"; mkdir -p "$OF_BIN"
  cat > "$OF_BIN/mypy" <<'SH'
#!/bin/sh
for a in "$@"; do f="$a"; done
echo "other_mod.py:3: error: an error in another module  [assignment]"
[ -n "${OF_MINE:-}" ] && echo "$(basename "$f"):2: error: the edited file's own error  [return-value]"
echo "Found 2 errors in 2 files (checked 1 source file)"
exit 1
SH
  chmod +x "$OF_BIN/mypy"
  printf 'x = 1\n' > "$PROJ/edited_of.py"
  OLD_PATH="$PATH"; export PATH="$OF_BIN:$PATH"
  run_post_edit "$PROJ/edited_of.py"
  assert_eq "$RC" "0" "an error only in another file does not wake Claude"
  export OF_MINE=1
  run_post_edit "$PROJ/edited_of.py"
  unset OF_MINE; export PATH="$OLD_PATH"
  assert_eq "$RC" "2" "the edited file's own error still wakes Claude beside another file's"
  assert_contains "$(cat "$STDERR_F")" "the edited file's own error" "the finding is the edited file's error"
  assert_not_contains "$(cat "$STDERR_F")" "an error in another module" "another file's error is not shown"
  assert_contains "$(cat "$STDERR_F")" "1 in other files not shown" "the summary says another file's error was left out"
  rm -f "$PROJ/edited_of.py"
fi

# --- an unfixed error is reported once per window, not after every edit (2026-11-04) ----------------------
if command -v mypy >/dev/null 2>&1 && ! command -v pyright >/dev/null 2>&1; then
  export POST_EDIT_REPEAT_WINDOW=1800
  printf 'def r1(x: int) -> str:\n    return x\n' > "$PROJ/repeat_new.py"
  run_post_edit "$PROJ/repeat_new.py"
  assert_eq "$RC" "2" "a new error wakes Claude the first time"
  printf 'def r1(x: int) -> str:\n    return x\n\n\ndef r2() -> int:\n    return 1\n' > "$PROJ/repeat_new.py"
  run_post_edit "$PROJ/repeat_new.py"
  assert_eq "$RC" "0" "the same unfixed error does not wake Claude again within the window"
  printf 'def r1(x: int) -> str:\n    return x\n\n\ndef r2() -> int:\n    return "s"\n' > "$PROJ/repeat_new.py"
  run_post_edit "$PROJ/repeat_new.py"
  assert_eq "$RC" "2" "a different new error in the same file wakes Claude"
  export POST_EDIT_REPEAT_WINDOW=0
  run_post_edit "$PROJ/repeat_new.py"
  assert_eq "$RC" "2" "with the window off every run reports (control)"
  rm -f "$PROJ/repeat_new.py"
else
  echo "  (skipped: the repeat-window cases need mypy without pyright on PATH)"
fi

# --- a worktree nested in the project is checked from its own checkout (2026-11-04) ---
# Checked from the project root, mypy resolved the worktree's `import pkgwt` to the project's copy, so a
# function the worktree had just added read as "Module has no attribute" and woke the session about
# correct code. The package is committed in $PROJ; only the worktree's copy gains new_fn.
if command -v mypy >/dev/null 2>&1 && ! command -v pyright >/dev/null 2>&1; then
  mkdir -p "$PROJ/pkgwt"; printf 'def old_fn() -> int:\n    return 1\n' > "$PROJ/pkgwt/__init__.py"
  git -C "$PROJ" add pkgwt/__init__.py >/dev/null 2>&1; git -C "$PROJ" commit -qm "pkgwt" >/dev/null 2>&1
  WT="$PROJ/.claude/worktrees/wt1"
  git -C "$PROJ" worktree add -q -b wt1 "$WT" >/dev/null 2>&1
  printf 'def old_fn() -> int:\n    return 1\n\ndef new_fn() -> int:\n    return 2\n' > "$WT/pkgwt/__init__.py"
  mkdir -p "$WT/tests"
  printf 'import pkgwt\n\ndef t() -> int:\n    return pkgwt.new_fn()\n' > "$WT/tests/uses_new.py"
  run_post_edit "$WT/tests/uses_new.py"
  assert_eq "$RC" "0" "a worktree file using its own checkout's new function is not a finding"
  assert_eq "$(cat "$STDERR_F")" "" "the project's older copy of the package never wakes Claude"
  printf 'import pkgwt\n\ndef t() -> str:\n    return pkgwt.new_fn()\n' > "$WT/tests/uses_new_bad.py"
  run_post_edit "$WT/tests/uses_new_bad.py"
  assert_eq "$RC" "2" "a real error in a worktree file still wakes Claude"
  assert_contains "$(cat "$STDERR_F")" "uses_new_bad.py:4" "that finding is the worktree file's line 4"
  git -C "$PROJ" worktree remove --force "$WT" >/dev/null 2>&1; git -C "$PROJ" branch -qD wt1 >/dev/null 2>&1
  rm -rf "$PROJ/.claude"
  git -C "$PROJ" rm -q -r pkgwt >/dev/null 2>&1; git -C "$PROJ" commit -qm "drop pkgwt" >/dev/null 2>&1
else
  echo "  (skipped: the worktree case needs mypy without pyright on PATH)"
fi

# --- uncommitted files at/over the threshold: finding reaches stderr, exit 2 ---
# Pin the threshold explicitly: this asserts the delivery contract, not the
# default's value, which the assertions above own.
COMMIT_REMINDER_THRESHOLD=2
export COMMIT_REMINDER_THRESHOLD
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "2" "uncommitted-file finding exits 2 (asyncRewake wake signal)"
assert_contains "$(cat "$STDERR_F")" "files edited without commit" \
  "uncommitted-file finding is written to stderr"
assert_contains "$(cat "$STDERR_F")" "committer" \
  "uncommitted-file finding keeps the actionable committer hint"
assert_eq "$(cat "$STDOUT_F")" "" "findings do not go to stdout"

# Regression: the finding must be plain text on stderr, not the old
# {"systemMessage": ...} JSON that a background hook threw away.
if grep -q 'systemMessage' "$STDERR_F"; then
  fail "no longer emits the discarded systemMessage envelope" "stderr still has systemMessage"
else
  pass "no longer emits the discarded systemMessage envelope"
fi
unset COMMIT_REMINDER_THRESHOLD

# --- below the threshold: one dirty file → silent ---
git -C "$PROJ" checkout -- . >/dev/null 2>&1
printf 'only one changed\n' > "$PROJ/a.txt"
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "0" "one dirty file stays under the threshold and exits 0"
assert_eq "$(cat "$STDERR_F")" "" "under-threshold run stays silent"

# --- threshold is overridable ---
COMMIT_REMINDER_THRESHOLD=1
export COMMIT_REMINDER_THRESHOLD
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "2" "COMMIT_REMINDER_THRESHOLD=1 makes one dirty file a finding"
unset COMMIT_REMINDER_THRESHOLD

# --- both findings survive into a single wake ---
# A .py file with a syntax error trips the type check; keeping the tree dirty
# trips the commit reminder. asyncRewake fires once, so one message must carry
# both — emitting them separately dropped whichever came second.
# Threshold pinned low so the fixture only needs a couple of dirty files; the
# default's value is asserted separately above.
if command -v ruff >/dev/null 2>&1 || command -v pyright >/dev/null 2>&1 || command -v mypy >/dev/null 2>&1; then
  COMMIT_REMINDER_THRESHOLD=2
  export COMMIT_REMINDER_THRESHOLD
  printf 'def broken(:\n' > "$PROJ/broken.py"
  printf 'still dirty\n' > "$PROJ/b.txt"
  run_post_edit "$PROJ/broken.py"
  assert_eq "$RC" "2" "type-check failure exits 2"
  err="$(cat "$STDERR_F")"
  if grep -qF "broken.py" <<< "$err" && grep -qF "files edited without commit" <<< "$err"; then
    pass "type-check and commit findings arrive together in one wake"
  else
    fail "type-check and commit findings arrive together in one wake" \
      "stderr: $(head -5 <<< "$err")"
  fi
  rm -f "$PROJ/broken.py"
  unset COMMIT_REMINDER_THRESHOLD
else
  echo "  (no python type-checker available — skipping combined-findings case)"
fi

# --- no file_path: no-op ---
out=$(printf '{}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$POST_EDIT_HOOK" 2>&1)
assert_eq "$?" "0" "exits 0 when tool_input.file_path is absent"
assert_eq "$out" "" "silent when tool_input.file_path is absent"

git -C "$PROJ" checkout -- . >/dev/null 2>&1

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit "$TESTS_FAILED"
