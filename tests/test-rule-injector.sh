#!/usr/bin/env bash
# test-rule-injector.sh — Tests for configs/hooks/rule-injector.sh
#   (PostToolUse Edit|Write AND Bash: path-scoped rule injection from
#   .claude/rules/)
#
# Pipes fixture hook-input JSON through the hook against throwaway project +
# HOME dirs under /tmp; never touches the real ~/.claude. Covers: project and
# global match, comma + YAML-list `paths:` forms, basename globs, globstar
# semantics ('*' must not cross '/'), once-per-session dedup, missing rules
# dir, malformed frontmatter, and missing input fields. Bash access: path
# tokens of .tool_input.command (existing files only, glob tokens skipped,
# relative tokens against .cwd, the 40-file cap), nested <dir>/.claude/rules
# with globs relative to <dir>, per-subagent dedup keyed on agent_id, the
# settings-hooks.json wiring, and a timing bound inside the 5 s hook timeout.
# Also: a leading `cd DIR` in the command, the 10,000-character
# additionalContext cap (held-back rules are not marked delivered), unreadable
# rule files, third-party trees (judged on the path as written AND on the
# physical path, so a symlink into node_modules or out of the project — even
# into a sibling sharing the root's name — is not scanned, while a project
# rooted inside node_modules keeps its own rules),
# claudeMdExcludes, identical rule text from two copies, and NUL / path
# characters in the hook-input ids.
# Every Bash-path case asserts on the emitted additionalContext.
#
# The last suite removes each guard of the hook in turn and requires this
# suite to go red — the mutation check, kept here so CI re-runs it. A mutation
# whose anchor no longer matches the hook is a failure, not a skip.
#
# Usage:
#   bash tests/test-rule-injector.sh        # Run all tests
#   bash tests/test-rule-injector.sh -v     # Verbose mode
# Internal (the mutation suite sets these for each mutant run):
#   RI_HOOK / RI_SETTINGS   test these files instead of the repository's
#   RI_MUTANT=1             stop at the first failure; skip timing + mutations

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="${RI_HOOK:-$REPO_ROOT/configs/hooks/rule-injector.sh}"
SETTINGS="${RI_SETTINGS:-$REPO_ROOT/configs/settings-hooks.json}"
RI_MUTANT="${RI_MUTANT:-}"

# ─── Test framework (mirrors tests/test-audit.sh) ────────────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() {
  TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  # A mutant run only has to show that SOMETHING noticed.
  [[ -n "$RI_MUTANT" ]] && exit 1
  return 0
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -5 <<< "$haystack")"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    fail "$msg" "output unexpectedly contains '$needle'"
  else
    pass "$msg"
  fi
}

assert_empty() {
  local out="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -z "$out" ]]; then
    pass "$msg"
  else
    fail "$msg" "expected no output, got: $(head -2 <<< "$out")"
  fi
}

assert_rc_zero() {
  local rc="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$rc" -eq 0 ]]; then
    pass "$msg"
  else
    fail "$msg" "exit code $rc"
  fi
}

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-rule-injector-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-rule-injector-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT

PROJ="$SANDBOX/proj"
FAKE_HOME="$SANDBOX/home"
mkdir -p "$PROJ/.claude/rules" "$FAKE_HOME/.claude/rules"

# Fixture rule files ──────────────────────────────────────────────────

# Project rule, inline comma-separated paths (incl. quoted bare glob)
cat > "$PROJ/.claude/rules/python-style.md" <<'EOF'
---
paths: orchestrator/**/*.py, "tests/*.py"
---
PYTHON-RULE-BODY: type hints on all new functions.
EOF

# Project rule, narrow single-star glob (must NOT match nested dirs)
cat > "$PROJ/.claude/rules/narrow.md" <<'EOF'
---
paths: orchestrator/*.py
---
NARROW-RULE-BODY
EOF

# Project file WITHOUT paths frontmatter — must always be ignored
cat > "$PROJ/.claude/rules/no-frontmatter.md" <<'EOF'
NO-FRONTMATTER-BODY: this file is not path-scoped and must never inject.
EOF

# Project file with unclosed frontmatter — malformed, must never inject
cat > "$PROJ/.claude/rules/malformed.md" <<'EOF'
---
paths: **/*.py
MALFORMED-BODY: frontmatter never closed.
EOF

# Global rule, YAML-list paths with a basename glob
cat > "$FAKE_HOME/.claude/rules/css-rules.md" <<'EOF'
---
paths:
  - "*.css"
  - "*.scss"
---
CSS-RULE-BODY: never overflow:hidden on popover containers.
EOF

# Hook-input fixture: $1=session_id $2=file_path
fixture() {
  printf '{"session_id":"%s","tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$1" "$2"
}

# Run the hook with sandboxed HOME + project
run_hook() {
  HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK"
}

# Project rule for the Bash cases: a slash glob that reaches any test_ file
cat > "$PROJ/.claude/rules/test-files.md" <<'EOF'
---
paths: **/test_*
---
TEST-FILES-RULE-BODY: a test must fail against the old code.
EOF

# Bash hook-input fixture: $1=session_id $2=command $3=cwd ("" = omit)
# $4=agent_id ("" = omit, i.e. the main thread). Built with jq so quotes,
# newlines and heredocs in the command are escaped correctly.
bash_fixture() {
  jq -nc --arg s "$1" --arg c "$2" --arg cwd "$3" --arg a "${4:-}" '
    {session_id: $s, tool_name: "Bash", tool_input: {command: $c}}
    + (if $cwd != "" then {cwd: $cwd} else {} end)
    + (if $a != "" then {agent_id: $a} else {} end)'
}

# The far side: what the hook hands Claude, not whether it printed something.
ctx_of() {
  jq -r '.hookSpecificOutput.additionalContext // empty' <<< "$1" 2>/dev/null
}

# ─── Suite 1: Matching ───────────────────────────────────────────────

section "Glob matching"

OUT=$(fixture s-match "$PROJ/orchestrator/sub/worker.py" | run_hook)
assert_contains "$OUT" "PYTHON-RULE-BODY" "** glob matches nested project file"
assert_contains "$OUT" "hookSpecificOutput" "output is hookSpecificOutput JSON"
assert_contains "$OUT" "additionalContext" "rule body emitted via additionalContext"
assert_not_contains "$OUT" "NARROW-RULE-BODY" "single * does not cross '/' (orchestrator/*.py vs nested file)"
assert_not_contains "$OUT" "CSS-RULE-BODY" "non-matching global rule not injected"
assert_not_contains "$OUT" "NO-FRONTMATTER-BODY" "file without paths frontmatter ignored"
assert_not_contains "$OUT" "MALFORMED-BODY" "unclosed frontmatter never injects"

TESTS_RUN=$((TESTS_RUN + 1))
if command -v jq >/dev/null 2>&1 && jq -e '.hookSpecificOutput.additionalContext' <<< "$OUT" >/dev/null 2>&1; then
  pass "output parses as JSON with .hookSpecificOutput.additionalContext"
else
  fail "output parses as JSON with .hookSpecificOutput.additionalContext"
fi

OUT=$(fixture s-narrow "$PROJ/orchestrator/worker.py" | run_hook)
assert_contains "$OUT" "NARROW-RULE-BODY" "single * matches file directly in the dir"
assert_contains "$OUT" "PYTHON-RULE-BODY" "multiple matching rules injected together"

OUT=$(fixture s-css "$PROJ/web/src/app.css" | run_hook)
assert_contains "$OUT" "CSS-RULE-BODY" "global bare glob (*.css) matches by basename anywhere"
assert_contains "$OUT" "(global)" "global rule labeled with its scope"

OUT=$(fixture s-quoted "$PROJ/tests/test_x.py" | run_hook)
assert_contains "$OUT" "PYTHON-RULE-BODY" "quoted comma-list glob (tests/*.py) matches"

# ─── Suite 2: No match / failure paths ───────────────────────────────

section "No-match and failure paths"

OUT=$(fixture s-nomatch "$PROJ/README.md" | run_hook); RC=$?
assert_empty "$OUT" "non-matching file produces no output"
assert_rc_zero "$RC" "non-matching file exits 0"

OUT=$(printf '{"session_id":"s-nofp","tool_name":"Edit","tool_input":{}}' | run_hook); RC=$?
assert_empty "$OUT" "missing tool_input.file_path produces no output"
assert_rc_zero "$RC" "missing file_path exits 0"

OUT=$(printf 'not json at all' | run_hook); RC=$?
assert_empty "$OUT" "garbage stdin produces no output"
assert_rc_zero "$RC" "garbage stdin exits 0"

# Missing rules dirs entirely (fresh project, fresh HOME)
EMPTY_PROJ="$SANDBOX/empty-proj"
EMPTY_HOME="$SANDBOX/empty-home"
mkdir -p "$EMPTY_PROJ" "$EMPTY_HOME"
OUT=$(fixture s-norules "$EMPTY_PROJ/main.py" \
  | HOME="$EMPTY_HOME" CLAUDE_PROJECT_DIR="$EMPTY_PROJ" bash "$HOOK"); RC=$?
assert_empty "$OUT" "missing rules dirs produce no output"
assert_rc_zero "$RC" "missing rules dirs exit 0"

# ─── Suite 3: Once-per-session dedup ─────────────────────────────────

section "Once-per-session dedup"

OUT1=$(fixture s-dedup "$PROJ/orchestrator/sub/worker.py" | run_hook)
assert_contains "$OUT1" "PYTHON-RULE-BODY" "first edit in session injects the rule"

OUT2=$(fixture s-dedup "$PROJ/orchestrator/sub/other.py" | run_hook); RC=$?
assert_not_contains "$OUT2" "PYTHON-RULE-BODY" "second matching edit in SAME session does not re-inject"
assert_rc_zero "$RC" "deduped invocation exits 0"

OUT3=$(fixture s-dedup2 "$PROJ/orchestrator/sub/worker.py" | run_hook)
assert_contains "$OUT3" "PYTHON-RULE-BODY" "new session id re-injects the rule"

TESTS_RUN=$((TESTS_RUN + 1))
if [[ -f "$PROJ/.claude/sessions/s-dedup.rules-injected" ]]; then
  pass "sentinel file written under .claude/sessions/<sid>.rules-injected"
else
  fail "sentinel file written under .claude/sessions/<sid>.rules-injected"
fi

# Dedup is per rule file: css rule still injects in a session that already
# consumed the python rule
OUT4=$(fixture s-dedup "$PROJ/web/app.css" | run_hook)
assert_contains "$OUT4" "CSS-RULE-BODY" "dedup is per rule file, not per session globally"

# ─── Suite 4: Bash command access ────────────────────────────────────
#
# Most file access goes through Bash (measured 2026-10-18: 6,890 shell reads
# vs 484 Read calls, 2,738 shell writes vs 373 Edit/Write over 40 sessions),
# so the hook reads path tokens out of .tool_input.command.

section "Bash: path tokens from the command"

mkdir -p "$PROJ/tests"
: > "$PROJ/tests/test_x.py"

CTX=$(ctx_of "$(bash_fixture b-cat "cat $PROJ/tests/test_x.py" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "cat of a matching file (absolute path) injects"
assert_contains "$CTX" "matched tests/test_x.py" "label names the project-relative file that matched"

CTX=$(ctx_of "$(bash_fixture b-sed "sed -i 's/old/new/' tests/test_x.py" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "sed -i … tests/test_x.py injects a **/test_* rule"

OUT=$(bash_fixture b-missing "cat tests/test_missing.py" "$PROJ" | run_hook); RC=$?
assert_empty "$OUT" "a command naming a non-existent path injects nothing"
assert_rc_zero "$RC" "non-existent path exits 0"

# Relative tokens resolve against the hook input's .cwd, not the project root:
# test_x.py exists only under tests/.
CTX=$(ctx_of "$(bash_fixture b-cwd "head -20 test_x.py" "$PROJ/tests" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "relative token resolved against .cwd injects"
OUT=$(bash_fixture b-cwd-neg "head -20 test_x.py" "$PROJ" | run_hook)
assert_empty "$OUT" "control: same relative token from the project root injects nothing"
CTX=$(ctx_of "$(bash_fixture b-nocwd "cat tests/test_x.py" "" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "missing .cwd falls back to CLAUDE_PROJECT_DIR"

# '.' and '..' collapse before matching: tests/*.py is anchored at the project
# root, so an uncollapsed ./tests/../tests/test_x.py would never match it.
CTX=$(ctx_of "$(bash_fixture b-norm "cat ./tests/../tests/test_x.py" "$PROJ" | run_hook)")
assert_contains "$CTX" "PYTHON-RULE-BODY" "./ and ../ segments collapse before root-anchored globs match"
assert_contains "$CTX" "matched tests/test_x.py" "label shows the collapsed project-relative path"

# --flag=path: '=' separates the token
CTX=$(ctx_of "$(bash_fixture b-eq "python3 tool.py --input=tests/test_x.py" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "a --flag=path token is split on '='"

# A heredoc write: the file exists by the time PostToolUse fires.
printf 'print(1)\n' > "$PROJ/tests/test_new.py"
CTX=$(ctx_of "$(bash_fixture b-heredoc "cat > tests/test_new.py <<'EOF'
print(1)
EOF" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "heredoc write to a matching file injects"

# Glob tokens are never treated as paths, even when a file of that literal
# name exists — the hook does not expand anything. One case per character, so
# dropping any one of them from the skip turns this red.
RI_N=0
for ch in '*' '?' '[' ']' '{' '}' '$'; do
  RI_N=$((RI_N + 1))
  lit="$PROJ/tests/test_${ch}.py"
  : > "$lit"
  OUT=$(bash_fixture "b-glob-$RI_N" "cat 'tests/test_${ch}.py'" "$PROJ" | run_hook)
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -f "$lit" && -z "$OUT" ]]; then
    pass "a token carrying '$ch' is skipped (the literal file exists, nothing injected)"
  else
    fail "a token carrying '$ch' is skipped" "out=[${OUT:0:120}]"
  fi
  rm -f "$lit"
done

# ~/ resolves against $HOME; global basename glob matches.
mkdir -p "$FAKE_HOME/notes"
: > "$FAKE_HOME/notes/theme.css"
CTX=$(ctx_of "$(bash_fixture b-home "cat ~/notes/theme.css" "$PROJ" | run_hook)")
assert_contains "$CTX" "CSS-RULE-BODY" "a tilde-slash token resolves against HOME"

# At most 40 existing files are matched per command.
mkdir -p "$PROJ/bulk"
BULK=""
for n in $(seq 1 45); do : > "$PROJ/bulk/f$n.txt"; BULK="$BULK bulk/f$n.txt"; done
OUT=$(bash_fixture b-cap "ls$BULK tests/test_x.py" "$PROJ" | run_hook)
assert_empty "$OUT" "a match after the 40-file cap is not examined"
CTX=$(ctx_of "$(bash_fixture b-cap-ctl "ls tests/test_x.py$BULK" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "control: the same match inside the cap injects"

# A rule file saved with CRLF line endings still parses (globs trimmed of \r).
CRLF_PROJ="$SANDBOX/crlf-proj"
mkdir -p "$CRLF_PROJ/.claude/rules" "$CRLF_PROJ/docs"
: > "$CRLF_PROJ/docs/guide.md"
printf -- '---\r\npaths: docs/*.md\r\n---\r\nCRLF-RULE-BODY\r\n' > "$CRLF_PROJ/.claude/rules/crlf.md"
CTX=$(ctx_of "$(bash_fixture b-crlf "cat docs/guide.md" "$CRLF_PROJ" \
  | HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$CRLF_PROJ" bash "$HOOK")")
assert_contains "$CTX" "CRLF-RULE-BODY" "a CRLF rule file's globs are trimmed of CR and match"

# Path-like = has a '/' or a .ext. A bare word that happens to name a file is
# not a path: `echo notes` must not count as touching ./notes.
cat > "$PROJ/.claude/rules/bare-name.md" <<'EOF'
---
paths: notes
---
BARE-NAME-BODY
EOF
: > "$PROJ/notes"
OUT=$(bash_fixture b-bare "echo notes" "$PROJ" | run_hook)
assert_not_contains "$(ctx_of "$OUT")" "BARE-NAME-BODY" "a bare word naming a file is not a path token"
CTX=$(ctx_of "$(bash_fixture b-bare-ctl "cat ./notes" "$PROJ" | run_hook)")
assert_contains "$CTX" "BARE-NAME-BODY" "control: ./notes is a path token and injects"

# At most 400 path-like tokens are examined: a match after 400 tokens that
# name nothing is never reached (separate from the 40-file cap).
RI_MANY=""
for n in $(seq 1 400); do RI_MANY="$RI_MANY nx/f$n.txt"; done
OUT=$(bash_fixture b-tok "cat$RI_MANY tests/test_x.py" "$PROJ" | run_hook)
assert_empty "$OUT" "a match after the 400-token bound is not examined"
CTX=$(ctx_of "$(bash_fixture b-tok-ctl "cat tests/test_x.py$RI_MANY" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "control: the same match inside the token bound injects"

# A NUL inside the command must not shift the NUL-separated fields: before the
# fix, the command text chose the session id and with it the sentinel path.
OUT=$(printf '{"session_id":"s-nul","cwd":"%s","tool_input":{"command":"cat %s/tests/test_x.py\\u0000../../forged-nul/pwn\\u0000/\\u0000"}}' \
  "$PROJ" "$PROJ" | run_hook)
assert_contains "$(ctx_of "$OUT")" "TEST-FILES-RULE-BODY" "a command holding NUL bytes still injects"
RI_FORGED=$(find "$SANDBOX" -name '*forged-nul*' 2>/dev/null | head -1)
TESTS_RUN=$((TESTS_RUN + 1))
if [[ -f "$PROJ/.claude/sessions/s-nul.rules-injected" && -z "$RI_FORGED" ]]; then
  pass "a NUL in the command cannot choose the session id or the sentinel path"
else
  fail "a NUL in the command cannot choose the session id or the sentinel path" "forged=[$RI_FORGED]"
fi

# session_id becomes part of a filename too.
bash_fixture "../../sid-escape" "cat tests/test_x.py" "$PROJ" | run_hook >/dev/null
RI_SID_IN=""
for sf in "$PROJ"/.claude/sessions/*sid-escape.rules-injected; do
  [[ -f "$sf" ]] && RI_SID_IN=1
done
TESTS_RUN=$((TESTS_RUN + 1))
if [[ ! -e "$PROJ/sid-escape.rules-injected" && -n "$RI_SID_IN" ]]; then
  pass "session_id with '/' is sanitized into the sessions dir"
else
  fail "session_id with '/' is sanitized into the sessions dir" \
       "$(ls "$PROJ" "$PROJ/.claude/sessions" 2>/dev/null | tr '\n' ' ')"
fi

# One awk reads every rule file, and mawk / BSD awk stop at the first file they
# cannot open — so an unreadable rule must be dropped before, or it silences
# the rules on both sides of it.
UNR="$SANDBOX/unreadable-proj"
mkdir -p "$UNR/.claude/rules" "$UNR/tests"
: > "$UNR/tests/test_x.py"
for r in a m z; do
  printf -- '---\npaths: **/test_*\n---\nUNR-RULE-%s\n' "$r" > "$UNR/.claude/rules/$r.md"
done
chmod 000 "$UNR/.claude/rules/m.md"
if [[ "$(id -u)" -eq 0 || -r "$UNR/.claude/rules/m.md" ]]; then
  echo "  - skipped: unreadable-rule case (this user can read a mode-000 file)"
else
  CTX=$(ctx_of "$(bash_fixture u-sess "cat tests/test_x.py" "$UNR" \
    | HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$UNR" bash "$HOOK")")
  assert_contains "$CTX" "UNR-RULE-a" "an unreadable rule file does not silence the rule before it"
  assert_contains "$CTX" "UNR-RULE-z" "an unreadable rule file does not silence the rule after it"
fi
chmod 644 "$UNR/.claude/rules/m.md"

# Once per session per rule FILE: editing a delivered rule does not re-inject
# it in the same session (compaction re-arms it via post-compact-reinject.sh).
EDR="$SANDBOX/edited-proj"
mkdir -p "$EDR/.claude/rules" "$EDR/tests"
: > "$EDR/tests/test_x.py"
printf -- '---\npaths: **/test_*\n---\nEDITED-RULE-V1\n' > "$EDR/.claude/rules/e.md"
run_edr() { HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$EDR" bash "$HOOK"; }
CTX=$(ctx_of "$(bash_fixture e-sess "cat tests/test_x.py" "$EDR" | run_edr)")
assert_contains "$CTX" "EDITED-RULE-V1" "first touch delivers the rule file"
printf -- '---\npaths: **/test_*\n---\nEDITED-RULE-V2\n' > "$EDR/.claude/rules/e.md"
OUT=$(bash_fixture e-sess "cat tests/test_x.py" "$EDR" | run_edr)
assert_empty "$OUT" "an edited rule file is not re-injected in the same session"

# ─── Suite 4b: cd inside the command ─────────────────────────────────
#
# 2,033 of 5,083 read-shaped Bash calls in 40 transcripts began with a cd, and
# after a cd that leaves the project the recorded cwd stays put — so a relative
# token after a cd resolves against the cd target, not against .cwd.

section "Bash: a leading cd moves where relative tokens resolve"

OTHER="$SANDBOX/other"
mkdir -p "$OTHER/tests"
OUT=$(bash_fixture c-abs-out "cd $OTHER && cat tests/test_x.py" "$PROJ" | run_hook)
assert_empty "$OUT" "cd to another dir: the project's same-named file is not matched"
OUT=$(bash_fixture c-pushd "pushd $OTHER >/dev/null; cat tests/test_x.py" "$PROJ" | run_hook)
assert_empty "$OUT" "pushd moves the base like cd"
CTX=$(ctx_of "$(bash_fixture c-abs-in "cd $PROJ/tests && head -5 test_x.py" "$OTHER" | run_hook)")
assert_contains "$CTX" "matched tests/test_x.py" "absolute cd into the project resolves the token there"
CTX=$(ctx_of "$(bash_fixture c-rel "cd tests && cat test_x.py" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "relative cd resolves against .cwd, then the token against it"
CTX=$(ctx_of "$(bash_fixture c-rel-followed "cd tests && cat test_x.py" "$PROJ/tests" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "relative cd that .cwd already followed is not applied twice"
OUT=$(bash_fixture c-var 'cd "$WORKDIR" && cat tests/test_x.py' "$PROJ" | run_hook)
assert_empty "$OUT" "cd to an unexpanded variable: relative tokens after it are skipped"
OUT=$(bash_fixture c-dash "cd - && cat tests/test_x.py" "$PROJ" | run_hook)
assert_empty "$OUT" "cd - : relative tokens after it are skipped"
CTX=$(ctx_of "$(bash_fixture c-var-abs "cd \"\$WORKDIR\" && cat $PROJ/tests/test_x.py" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "absolute tokens after an unknown cd still resolve"

# ─── Suite 5: Nested .claude/rules ───────────────────────────────────
#
# Claude Code honours apps/<app>/.claude/rules with globs relative to the
# directory holding that .claude/ (verified 2026-10-18). A session started at
# the monorepo root must still get them.

section "Nested .claude/rules (monorepo)"

MONO="$SANDBOX/mono"
mkdir -p "$MONO/.claude" "$MONO/apps/sub/.claude/rules" "$MONO/apps/.claude/rules" \
         "$MONO/apps/sub/src/a" "$MONO/src/a"
: > "$MONO/apps/sub/src/a/b.ts"
: > "$MONO/src/a/b.ts"
cat > "$MONO/apps/sub/.claude/rules/sub-ts.md" <<'EOF'
---
paths: src/**/*.ts
---
NESTED-TS-BODY
EOF
# Root-relative glob in a nested dir: must NOT match (globs are relative to apps/sub)
cat > "$MONO/apps/sub/.claude/rules/wrong-base.md" <<'EOF'
---
paths: apps/sub/src/**/*.ts
---
WRONG-BASE-BODY
EOF
# One level up: the walk continues past the first rules dir it finds
cat > "$MONO/apps/.claude/rules/apps-level.md" <<'EOF'
---
paths: sub/src/**
---
APPS-LEVEL-BODY
EOF

run_mono() { HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$MONO" bash "$HOOK"; }

CTX=$(ctx_of "$(bash_fixture n-bash "cat apps/sub/src/a/b.ts" "$MONO" | run_mono)")
assert_contains "$CTX" "NESTED-TS-BODY" "nested rule injects when the session root is the repo root"
assert_contains "$CTX" "(nested: apps/sub)" "nested rule labelled with its directory"
assert_contains "$CTX" "APPS-LEVEL-BODY" "every rules dir between the file and the root is scanned"
assert_not_contains "$CTX" "WRONG-BASE-BODY" "nested globs are relative to apps/sub, not the repo root"

OUT=$(bash_fixture n-outside "cat src/a/b.ts" "$MONO" | run_mono)
assert_not_contains "$(ctx_of "$OUT")" "NESTED-TS-BODY" "a file outside apps/sub never gets apps/sub's rules"

CTX=$(ctx_of "$(fixture n-edit "$MONO/apps/sub/src/a/b.ts" | run_mono)")
assert_contains "$CTX" "NESTED-TS-BODY" "Edit/Write path also reaches nested rules"

# Only files under <dir> can match <dir>'s rules. The fixture must LOAD
# apps/sub's rules (by naming a file under it) and then name a file outside it
# that a bare-name glob would match — `cat src/a/b.ts` alone never reaches
# apps/sub/.claude/rules, so it could not see this guard.
cat > "$MONO/apps/sub/.claude/rules/sub-bare-ts.md" <<'EOF'
---
paths: *.ts
---
NESTED-BARE-TS-BODY
EOF
: > "$MONO/apps/sub/README.md"
OUT=$(bash_fixture n-scope "cat apps/sub/README.md src/a/b.ts" "$MONO" | run_mono)
assert_not_contains "$(ctx_of "$OUT")" "NESTED-BARE-TS-BODY" \
  "apps/sub's rules loaded, but a file outside apps/sub does not match them"
CTX=$(ctx_of "$(bash_fixture n-scope-ctl "cat apps/sub/README.md apps/sub/src/a/b.ts" "$MONO" | run_mono)")
assert_contains "$CTX" "NESTED-BARE-TS-BODY" "control: the same glob matches a file under apps/sub"

# Two files under one nested dir: its rules are scanned once, injected once,
# and the sentinel records each rule file once.
: > "$MONO/apps/sub/src/a/c.ts"
CTX=$(ctx_of "$(bash_fixture n-twice "cat apps/sub/src/a/b.ts apps/sub/src/a/c.ts" "$MONO" | run_mono)")
TESTS_RUN=$((TESTS_RUN + 1))
RI_C=$(grep -c "NESTED-TS-BODY" <<< "$CTX")
RI_S=$(grep -cxF "$MONO/apps/sub/.claude/rules/sub-ts.md" "$MONO/.claude/sessions/n-twice.rules-injected" 2>/dev/null)
if [[ "$RI_C" == "1" && "$RI_S" == "1" ]]; then
  pass "two files in one nested dir: the rule is injected and recorded once"
else
  fail "two files in one nested dir: the rule is injected and recorded once" "body x$RI_C, sentinel x$RI_S"
fi

# The walk stops at the project root: a .claude/rules ABOVE the project is
# not a nested dir of this project.
OUTER="$SANDBOX/outer"
mkdir -p "$OUTER/.claude/rules" "$OUTER/proj/tests"
: > "$OUTER/proj/tests/test_y.py"
printf -- '---\npaths: **/test_*\n---\nOUTER-RULE-BODY\n' > "$OUTER/.claude/rules/outer.md"
OUT=$(bash_fixture n-outer "cat tests/test_y.py" "$OUTER/proj" \
  | HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$OUTER/proj" bash "$HOOK")
assert_not_contains "$(ctx_of "$OUT")" "OUTER-RULE-BODY" "the nested walk never climbs above the project root"

# Third-party trees: a Bash token can merely MENTION a path, and a package's
# own .claude/rules are not this project's.
for v in node_modules vendor third_party site-packages .git; do
  mkdir -p "$MONO/$v/pkg/.claude/rules" "$MONO/$v/pkg/lib"
  : > "$MONO/$v/pkg/lib/index.js"
  printf -- '---\npaths: **\n---\nVENDORED-BODY-%s\n' "$v" > "$MONO/$v/pkg/.claude/rules/x.md"
  OUT=$(bash_fixture "n-vend-$v" "echo 'see $v/pkg/lib/index.js for details'" "$MONO" | run_mono)
  assert_not_contains "$(ctx_of "$OUT")" "VENDORED-BODY-$v" "rules inside $v/ are never injected"
done

# ...including when the path as written never names one. A dir is judged on
# its PHYSICAL path too: linked/ -> node_modules/pkg is the package's tree.
# Found 2026-10-23 — the written path alone injected VENDORED-BODY-node_modules.
ln -s node_modules/pkg "$MONO/linked"
OUT=$(bash_fixture n-link-vend "cat linked/lib/index.js" "$MONO" | run_mono)
assert_empty "$OUT" "a symlink into node_modules/ injects nothing (judged on the physical path)"

# A dir whose physical path lies outside the project is not this project's.
# Named mono-ext on purpose: it shares the root's name as a string prefix, so
# "inside" must mean below a path separator, not a string-prefix match.
EXT="$MONO-ext"
mkdir -p "$EXT/.claude/rules" "$EXT/lib"
: > "$EXT/lib/x.js"
printf -- '---\npaths: **\n---\nOUTSIDE-ROOT-BODY\n' > "$EXT/.claude/rules/x.md"
ln -s "$EXT" "$MONO/ext"
OUT=$(bash_fixture n-link-out "cat ext/lib/x.js" "$MONO" | run_mono)
assert_empty "$OUT" "a symlink to a dir outside the project is not scanned for nested rules"

# Control: a symlink to an ordinary in-project dir still loads that dir's rules.
ln -s apps/sub "$MONO/alias"
CTX=$(ctx_of "$(bash_fixture n-link-ok "cat alias/src/a/b.ts" "$MONO" | run_mono)")
assert_contains "$CTX" "NESTED-TS-BODY" "control: a symlink to an in-project dir still loads its nested rules"
assert_contains "$CTX" "(nested: alias)" "control: labelled with the path as written"

# The written name still counts on its own: a node_modules that is itself a
# symlink into an in-project store is physically store/web-nm/pkg, which names
# no third-party tree — and it is still the packages' tree.
mkdir -p "$MONO/apps/web" "$MONO/store/web-nm/pkg/.claude/rules" "$MONO/store/web-nm/pkg/lib"
: > "$MONO/store/web-nm/pkg/lib/i.js"
printf -- '---\npaths: **\n---\nSTORE-PKG-BODY\n' > "$MONO/store/web-nm/pkg/.claude/rules/x.md"
ln -s ../../store/web-nm "$MONO/apps/web/node_modules"
OUT=$(bash_fixture n-link-store "cat apps/web/node_modules/pkg/lib/i.js" "$MONO" | run_mono)
assert_empty "$OUT" "a node_modules symlinked to an in-project store is still skipped by its name"

# Both judgements are measured BELOW the project root: a project whose root
# itself sits inside node_modules is the package, and its rules are its own.
NMROOT="$SANDBOX/host/node_modules/pkg"
mkdir -p "$NMROOT/.claude" "$NMROOT/apps/x/.claude/rules" "$NMROOT/apps/x/src"
: > "$NMROOT/apps/x/src/f.js"
printf -- '---\npaths: src/**\n---\nPKG-AS-PROJECT-BODY\n' > "$NMROOT/apps/x/.claude/rules/r.md"
CTX=$(ctx_of "$(bash_fixture n-nmroot "cat apps/x/src/f.js" "$NMROOT" \
  | HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$NMROOT" bash "$HOOK")")
assert_contains "$CTX" "PKG-AS-PROJECT-BODY" \
  "a project whose root sits inside node_modules still scans its own nested rules"

# Physical against physical: a project reached through a symlinked root (or
# macOS's /tmp -> /private/tmp) still gets its nested rules.
ln -s "$MONO" "$SANDBOX/mono-link"
CTX=$(ctx_of "$(bash_fixture n-rootlink "cat apps/sub/src/a/b.ts" "$SANDBOX/mono-link" \
  | HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$SANDBOX/mono-link" bash "$HOOK")")
assert_contains "$CTX" "NESTED-TS-BODY" "a project opened through a symlinked root still gets its nested rules"

# claudeMdExcludes: absolute-path globs from the user, project and local
# settings layers. A matching rules file never injects; others still do.
for x in excl-local excl-proj excl-user; do
  mkdir -p "$MONO/apps/$x/.claude/rules"
  : > "$MONO/apps/$x/f.txt"
  printf -- '---\npaths: **\n---\nEXCLUDED-BODY-%s\n' "$x" > "$MONO/apps/$x/.claude/rules/r.md"
done
XHOME="$SANDBOX/xhome"
mkdir -p "$XHOME/.claude"
printf '{"claudeMdExcludes":["**/apps/excl-local/.claude/rules/**"]}\n' > "$MONO/.claude/settings.local.json"
printf '{"claudeMdExcludes":["**/apps/excl-proj/**"]}\n' > "$MONO/.claude/settings.json"
printf '{"claudeMdExcludes":["%s/apps/excl-user/.claude/rules/r.md"]}\n' "$MONO" > "$XHOME/.claude/settings.json"
CTX=$(ctx_of "$(bash_fixture n-excl \
  "cat apps/excl-local/f.txt apps/excl-proj/f.txt apps/excl-user/f.txt apps/sub/src/a/b.ts" "$MONO" \
  | HOME="$XHOME" CLAUDE_PROJECT_DIR="$MONO" bash "$HOOK")")
for x in excl-local excl-proj excl-user; do
  assert_not_contains "$CTX" "EXCLUDED-BODY-$x" "claudeMdExcludes ($x layer) skips the rules file"
done
assert_contains "$CTX" "NESTED-TS-BODY" "control: a rules file no exclude names still injects"
rm -f "$MONO/.claude/settings.local.json" "$MONO/.claude/settings.json"

# ─── Suite 5b: Identical rule text from two copies ───────────────────
#
# A worktree's checked-out copy of a root rule (or a rule kept both global and
# project) is the same text: inject it once, this call or a later one.

section "Identical rule text is injected once"

DUP="$SANDBOX/dup"
mkdir -p "$DUP/.claude/rules" "$DUP/sub/.claude/rules" "$DUP/sub/tests" "$DUP/tests"
: > "$DUP/sub/tests/test_a.py"
: > "$DUP/tests/test_b.py"
printf -- '---\npaths: **/test_*\n---\nDUP-BODY\n' > "$DUP/.claude/rules/t.md"
cp "$DUP/.claude/rules/t.md" "$DUP/sub/.claude/rules/t.md"
run_dup() { HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$DUP" bash "$HOOK"; }
CTX=$(ctx_of "$(bash_fixture d-one "sed -n 1,5p sub/tests/test_a.py" "$DUP" | run_dup)")
TESTS_RUN=$((TESTS_RUN + 1))
RI_C=$(grep -c "DUP-BODY" <<< "$CTX")
if [[ "$RI_C" == "1" ]]; then
  pass "root rule and its nested copy, same call: the text appears once"
else
  fail "root rule and its nested copy, same call: the text appears once" "appeared $RI_C times"
fi
CTX=$(ctx_of "$(bash_fixture d-two "cat tests/test_b.py" "$DUP" | run_dup)")
assert_contains "$CTX" "DUP-BODY" "a later session: the root rule injects"
OUT=$(bash_fixture d-two "cat sub/tests/test_a.py" "$DUP" | run_dup)
assert_empty "$OUT" "the nested copy of text already delivered injects nothing on a later call"

# ─── Suite 5c: additionalContext size cap ────────────────────────────
#
# Claude Code caps additionalContext at 10,000 characters; past that Claude
# sees a 2,000-character preview and is not asked to read the rest. A rule
# left out for size must not be recorded as delivered.

section "additionalContext stays under the 10,000-character cap"

BIG="$SANDBOX/big"
mkdir -p "$BIG/.claude/rules" "$BIG/tests"
: > "$BIG/tests/test_x.py"
for r in 1 2 3 4 5; do
  {
    printf -- '---\npaths: **/test_*\n---\nBIG-BODY-%s\n' "$r"
    for l in $(seq 1 29); do
      printf '%s\n' "filler line $l of rule $r .................................................................................."
    done
  } > "$BIG/.claude/rules/r$r.md"
done
run_big() { HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$BIG" bash "$HOOK"; }
ctx_bytes() { printf '%s' "$1" | LC_ALL=C wc -c | tr -d ' '; }

CTX=$(ctx_of "$(bash_fixture s-big "cat tests/test_x.py" "$BIG" | run_big)")
TESTS_RUN=$((TESTS_RUN + 1))
RI_B=$(ctx_bytes "$CTX")
if [[ "$RI_B" -gt 0 && "$RI_B" -lt 10000 ]]; then
  pass "five ~3 KB matching rules: additionalContext is $RI_B bytes (< 10,000)"
else
  fail "five ~3 KB matching rules: additionalContext under 10,000" "$RI_B bytes"
fi
assert_contains "$CTX" "BIG-BODY-1" "the first rules that fit are injected"
assert_not_contains "$CTX" "BIG-BODY-5" "a rule past the budget is held back"
assert_contains "$CTX" "held back: 3 more matched" "the output says how many were held back"
CTX=$(ctx_of "$(bash_fixture s-big "cat tests/test_x.py" "$BIG" | run_big)")
assert_contains "$CTX" "BIG-BODY-3" "a held-back rule arrives on the next matching call"
assert_not_contains "$CTX" "BIG-BODY-1" "a delivered rule does not come back"
CTX=$(ctx_of "$(bash_fixture s-big "cat tests/test_x.py" "$BIG" | run_big)")
assert_contains "$CTX" "BIG-BODY-5" "the last held-back rule arrives on the call after"

# The held-back note names the rules, but its list is bounded too.
BIG2="$SANDBOX/big2"
mkdir -p "$BIG2/.claude/rules" "$BIG2/tests"
: > "$BIG2/tests/test_x.py"
for r in $(seq 10 49); do
  { printf -- '---\npaths: **/test_*\n---\nBIG2-BODY-%s\n' "$r"; tail -n +5 "$BIG/.claude/rules/r1.md"; } \
    > "$BIG2/.claude/rules/a-rather-long-rule-file-name-number-$r.md"
done
CTX=$(ctx_of "$(bash_fixture s-big2 "cat tests/test_x.py" "$BIG2" \
  | HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$BIG2" bash "$HOOK")")
RI_NOTE=$(grep -F "held back: 38 more" <<< "$CTX")
TESTS_RUN=$((TESTS_RUN + 1))
RI_NB=$(ctx_bytes "$RI_NOTE")
if [[ -n "$RI_NOTE" && "$RI_NB" -lt 800 && "$(ctx_bytes "$CTX")" -lt 10000 ]]; then
  pass "38 held-back rules: the note's name list is cut short ($RI_NB bytes)"
else
  fail "38 held-back rules: the note's name list is cut short" "note $RI_NB bytes, ctx $(ctx_bytes "$CTX") bytes"
fi

# ─── Suite 6: Subagent dedup (agent_id) ──────────────────────────────
#
# Subagents carry the parent's session_id. A session-only sentinel meant no
# subagent ever got a rule the main thread had already received.

section "Subagent dedup keyed on agent_id"

CTX=$(ctx_of "$(bash_fixture a-sess "cat tests/test_x.py" "$PROJ" | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "main thread: first touch injects"
CTX=$(ctx_of "$(bash_fixture a-sess "cat tests/test_x.py" "$PROJ" | run_hook)")
assert_not_contains "$CTX" "TEST-FILES-RULE-BODY" "main thread: second touch does not re-inject"

CTX=$(ctx_of "$(bash_fixture a-sess "cat tests/test_x.py" "$PROJ" agent-1 | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "subagent with agent_id gets the rule again"
CTX=$(ctx_of "$(bash_fixture a-sess "cat tests/test_x.py" "$PROJ" agent-1 | run_hook)")
assert_not_contains "$CTX" "TEST-FILES-RULE-BODY" "same subagent twice gets it once"
CTX=$(ctx_of "$(bash_fixture a-sess "cat tests/test_x.py" "$PROJ" agent-2 | run_hook)")
assert_contains "$CTX" "TEST-FILES-RULE-BODY" "a second subagent gets its own injection"
CTX=$(ctx_of "$(bash_fixture a-sess "cat tests/test_x.py" "$PROJ" | run_hook)")
assert_not_contains "$CTX" "TEST-FILES-RULE-BODY" "subagent injections do not re-arm the main thread"

TESTS_RUN=$((TESTS_RUN + 1))
if [[ -f "$PROJ/.claude/sessions/a-sess.rules-injected" \
      && -f "$PROJ/.claude/sessions/a-sess.agent-agent-1.rules-injected" ]]; then
  pass "main sentinel name unchanged; subagent sentinel carries agent_id"
else
  fail "main sentinel name unchanged; subagent sentinel carries agent_id" \
       "$(ls "$PROJ/.claude/sessions" | tr '\n' ' ')"
fi

# agent_id is used in a filename: it must not escape the sessions dir.
bash_fixture a-sess "cat tests/test_x.py" "$PROJ" "../../escape" | run_hook >/dev/null
RI_ESC_IN=""
for sf in "$PROJ"/.claude/sessions/a-sess.agent-*escape.rules-injected; do
  [[ -f "$sf" ]] && RI_ESC_IN=1
done
TESTS_RUN=$((TESTS_RUN + 1))
if [[ ! -e "$PROJ/escape.rules-injected" && ! -e "$PROJ/.claude/escape.rules-injected" \
      && -n "$RI_ESC_IN" ]]; then
  pass "agent_id with '/' is sanitized into the sessions dir"
else
  fail "agent_id with '/' is sanitized into the sessions dir" \
       "$(ls "$PROJ/.claude/sessions" | tr '\n' ' ')"
fi

# ─── Suite 7: Wiring ─────────────────────────────────────────────────

section "settings-hooks.json wiring"

RI_BASH_BLOCKS=$(jq '[.hooks.PostToolUse[] | select(.matcher == "Bash")] | length' "$SETTINGS" 2>/dev/null)
TESTS_RUN=$((TESTS_RUN + 1))
if [[ "$RI_BASH_BLOCKS" == "1" ]]; then
  pass "PostToolUse has exactly one Bash matcher block"
else
  fail "PostToolUse has exactly one Bash matcher block" "found ${RI_BASH_BLOCKS:-none}"
fi
# Sync on both matchers (additionalContext needs sync). A statusMessage on the
# Edit|Write entry, like its siblings there; NONE on the Bash entry, which fires
# on every shell call — like failure-detector, the other sync Bash hook.
for m in "Bash" "Edit|Write"; do
  if [[ "$m" == "Bash" ]]; then want_status=false; else want_status=true; fi
  TESTS_RUN=$((TESTS_RUN + 1))
  if jq -e --arg m "$m" --argjson ws "$want_status" '.hooks.PostToolUse[] | select(.matcher == $m) | .hooks[]
        | select(.id == "rule-injector")
        | (.command | test("rule-injector\\.sh")) and (has("async") | not)
          and (((.statusMessage // "") != "") == $ws)' "$SETTINGS" >/dev/null 2>&1; then
    pass "rule-injector wired sync on PostToolUse '$m' (statusMessage: $want_status)"
  else
    fail "rule-injector wired sync on PostToolUse '$m' (statusMessage: $want_status)"
  fi
done

# ─── Suite 8: Timing ─────────────────────────────────────────────────
#
# Runs on every Bash call with a 5 s timeout. Worst case for the matcher: 30
# rule files × 15 globs, 40 existing files, and nothing matching until the
# very last glob of the very last rule file.

if [[ -z "$RI_MUTANT" ]]; then
section "Timing inside the 5 s hook timeout"

PERF="$SANDBOX/perf"
mkdir -p "$PERF/.claude/rules" "$PERF/src"
PERF_CMD="cat"
for n in $(seq 1 40); do : > "$PERF/src/file$n.dat"; PERF_CMD="$PERF_CMD src/file$n.dat"; done
for r in $(seq 1 30); do
  {
    echo "---"
    echo "paths:"
    for g in $(seq 1 14); do echo "  - \"lib$r/**/mod$g/*.ext$g\""; done
    if [[ "$r" -eq 30 ]]; then echo '  - "src/file40.dat"'; else echo "  - \"*.nomatch$r\""; fi
    echo "---"
    echo "PERF-RULE-$r"
  } > "$PERF/.claude/rules/r$r.md"
done
TIMEFORMAT='%R'
PERF_T=$( { time bash_fixture p-sess "$PERF_CMD" "$PERF" \
  | HOME="$FAKE_HOME" CLAUDE_PROJECT_DIR="$PERF" bash "$HOOK" > "$SANDBOX/perf.out"; } 2>&1 )
CTX=$(ctx_of "$(cat "$SANDBOX/perf.out")")
assert_contains "$CTX" "PERF-RULE-30" "the 40th file matches the last glob of the 30th rule file"
TESTS_RUN=$((TESTS_RUN + 1))
if awk -v t="$PERF_T" 'BEGIN { exit !(t + 0 < 5.0) }'; then
  pass "30 rules × 15 globs × 40 files finishes in ${PERF_T}s (< 5 s timeout)"
else
  fail "30 rules × 15 globs × 40 files finishes inside the 5 s timeout" "took ${PERF_T}s"
fi
fi

# ─── Suite 9: Mutations ──────────────────────────────────────────────
#
# A clean run and a run with a guard missing print the same "ALL PASSED"
# unless something removes the guard and looks. Each entry below edits ONE
# guard out of a copy of the hook (or settings-hooks.json), runs this suite
# against the copy, and requires it to go red. The first entry is the negative
# control: a no-op edit must leave the suite green, or a red result proves
# nothing. Mutant runs stop at their first failure and run in parallel.

if [[ -z "$RI_MUTANT" ]]; then
section "Mutations: removing each guard turns this suite red"

MUT_DIR="$SANDBOX/mutants"
mkdir -p "$MUT_DIR"
MUT_NAMES=(); MUT_FILES=(); MUT_TARGETS=(); MUT_EXPECT=()
NMUT=0

# Can this user be denied a mode-000 file? (Not as root.)
RI_PROBE="$SANDBOX/probe-unreadable"
: > "$RI_PROBE"; chmod 000 "$RI_PROBE"
RI_CAN_DENY=1
[[ -r "$RI_PROBE" ]] && RI_CAN_DENY=""
chmod 644 "$RI_PROBE"

# mutation EXPECT TARGET NAME ANCHOR REPLACEMENT [ANCHOR REPLACEMENT ...] —
# literal text, no regex. Extra pairs apply in order to the same copy, for a
# property two guards hold between them.
mutation() {
  local expect="$1" target="$2" name="$3" src out
  case "$target" in
    hook) src="$HOOK" ;;
    *) src="$SETTINGS" ;;
  esac
  out="$MUT_DIR/m$NMUT.$target"
  shift 3
  if [[ "$#" -eq 0 || $(($# % 2)) -ne 0 ]]; then
    TESTS_RUN=$((TESTS_RUN + 1))
    fail "mutation '$name': needs ANCHOR REPLACEMENT pairs, got $# argument(s)"
    return 0
  fi
  cp "$src" "$out"
  while [[ "$#" -ge 2 ]]; do
    if ! RI_A="$1" RI_R="$2" awk '
        { buf = buf (NR > 1 ? "\n" : "") $0 }
        END {
          a = ENVIRON["RI_A"]; r = ENVIRON["RI_R"]; s = buf; out = ""; n = 0
          while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++ }
          if (n != 1) exit 3
          printf "%s\n", out s
        }' "$out" > "$out.next"; then
      TESTS_RUN=$((TESTS_RUN + 1))
      fail "mutation '$name': its anchor no longer matches the $target exactly once"
      return 0
    fi
    mv "$out.next" "$out"
    shift 2
  done
  MUT_NAMES[NMUT]="$name"; MUT_FILES[NMUT]="$out"
  MUT_TARGETS[NMUT]="$target"; MUT_EXPECT[NMUT]="$expect"
  NMUT=$((NMUT + 1))
}

mutation green hook "no-op control (a comment reworded)" \
  '# Byte length of $1' '# Byte length of  $1'

mutation red hook "the Bash branch itself" \
  'done < <(command_tokens)' 'done < /dev/null'
mutation red hook "the Edit/Write path" \
  'resolve_token "$FILE_PATH" && add_candidate "$NORM"' ':'
mutation red hook "the existence filter on Bash tokens" \
  '    [ -f "$NORM" ] || continue' '    :'
mutation red hook "the glob-metacharacter skip" \
  'if (index(w, "*") || index(w, "?") || index(w, "[") || index(w, "]") || index(w, "{") || index(w, "}")) continue' \
  'if (0) continue'
mutation red hook "the glob skip for every character but *" \
  ' || index(w, "?") || index(w, "[") || index(w, "]") || index(w, "{") || index(w, "}")' ''
mutation red hook "the unexpanded-variable skip" \
  'if (index(w, "$")) continue' 'if (0) continue'
mutation red hook "the path-like filter" \
  'if (!index(w, "/") && w !~ /\.[A-Za-z0-9_+-]+$/) continue' 'if (0) continue'
mutation red hook "the 400-token bound" \
  'print w
          if (++c >= max) exit' 'print w'
mutation red hook "the 40-file cap" \
  'MAX_FILES=40 ' 'MAX_FILES=4000 '
mutation red hook "relative tokens resolve against .cwd" \
  'REL_BASE="${HOOK_CWD:-$PROJECT_DIR}"' 'REL_BASE="$PROJECT_DIR"'
mutation red hook "the fallback to the project when .cwd is missing" \
  'REL_BASE="${HOOK_CWD:-$PROJECT_DIR}"' 'REL_BASE="${HOOK_CWD}"'
# shellcheck disable=SC2088  # the mutation's name, not a path
mutation red hook "~/ resolves against HOME" \
  '"~/"*) [ -n "${HOME:-}" ] || return 1; normalize_path "$HOME/${1#"~/"}" ;;' '"~/"*) return 1 ;;'
mutation red hook "./ and ../ collapse" \
  '*/./*|*/../*|*/.|*/..|*//*) ;;' 'never-matches) ;;'
mutation red hook "'=' separates a token" \
  '=,]+"' ',]+"'
mutation red hook "glob trim strips CR" \
  'function addglob(v,   e) {
      sub(/^[[:space:]]+/, "", v); sub(/[[:space:]]+$/, "", v)' \
  'function addglob(v,   e) {
      sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v)'
mutation red hook "cd recognised at a segment start" \
  'if (k <= n && (t[k] == "cd" || t[k] == "pushd")) {' 'if (0) {'
mutation red hook "pushd recognised like cd" \
  't[k] == "cd" || t[k] == "pushd"' 't[k] == "cd"'
mutation red hook "a cd moves the base" \
  '"cd$TAB"*) set_cd_base "${tok#"cd$TAB"}"; continue ;;' '"cd$TAB"*) continue ;;'
mutation red hook "a relative cd applies only when it exists under the base" \
  '*) [ -d "$NORM" ] && BASE="$NORM" ;;' '*) BASE="$NORM" ;;'
mutation red hook "an unknown cd target clears the base" \
  '-|*[][*?{}]*|*\$*) BASE=""; return 0 ;;' '-|*[][*?{}]*|*\$*) return 0 ;;'
mutation red hook "a NUL inside a field" \
  ' | split("\u0000") | join(" ")' ''
mutation red hook "session_id sanitization" \
  'SESSION_ID="${SESSION_ID//[^A-Za-z0-9_-]/_}"' ':'
mutation red hook "agent_id in the sentinel name" \
  'SENT_KEY="$SENT_KEY.agent-${AGENT_ID//[^A-Za-z0-9_-]/_}"' ':'
mutation red hook "agent_id sanitization" \
  '.agent-${AGENT_ID//[^A-Za-z0-9_-]/_}' '.agent-${AGENT_ID}'
mutation red hook "once per session per rule file" \
  'case "$SENT" in *"$NL$f$NL"*) continue ;; esac' ':'
mutation red hook "the nested-dir walk" \
  '    if [ -d "$rd" ]; then' '    if false; then'
mutation red hook "third-party trees skipped by the path as written" \
  'if ! is_vendored "${d#"$PROJECT_DIR"/}" && physically_ours "$d"; then' \
  'if physically_ours "$d"; then'
mutation red hook "third-party trees skipped by the physical path" \
  '  ! is_vendored "${p#"$PHYS_ROOT"/}"' '  :'
mutation red hook "a dir physically outside the project is not scanned" \
  'case "$p" in "$PHYS_ROOT"/*) : ;; *) return 1 ;; esac' ':'
mutation red hook "the physical bound needs a path separator" \
  'case "$p" in "$PHYS_ROOT"/*)' 'case "$p" in "$PHYS_ROOT"*)'
mutation red hook "the written path is judged below the project root" \
  'is_vendored "${d#"$PROJECT_DIR"/}"' 'is_vendored "$d"'
mutation red hook "the physical path is judged below the physical root" \
  '! is_vendored "${p#"$PHYS_ROOT"/}"' '! is_vendored "$p"'
mutation red hook "the root is resolved physically too" \
  'PHYS_ROOT=$(cd "$PROJECT_DIR" 2>/dev/null && pwd -P)' 'PHYS_ROOT=$PROJECT_DIR'
# Two guards hold "never above the root" since the physical check: the walk's
# lexical stop, and the physical-root bound that rejects whatever lies outside.
# Either alone keeps n-outer green, so this mutant removes both. What the lexical
# stop adds alone is cost — no subshell for a rules dir above the root — which
# no assertion here can see.
mutation red hook "the walk stops at the project root (lexical stop + physical bound)" \
  'case "$d" in "$PROJECT_DIR"/*) : ;; *) break ;; esac' 'case "$d" in /?*) : ;; *) break ;; esac' \
  'case "$p" in "$PHYS_ROOT"/*) : ;; *) return 1 ;; esac' ':'
mutation red hook "each rules dir is scanned once" \
  '        *"$NL$rd$NL"*) : ;;' '        never-matches) : ;;'
mutation red hook "only files under <dir> match its rules" \
  'case "$c" in "$base"/*) rel="${c#"$base"/}" ;; *) i=$((i + 1)); continue ;; esac' \
  'rel="${c#"$base"/}"'
mutation red hook "nested globs are relative to <dir>" \
  '"$base"/*) rel="${c#"$base"/}" ;;' '"$base"/*) rel="${CAND_REL[$i]}" ;;'
if [[ -n "$RI_CAN_DENY" ]]; then
  mutation red hook "unreadable rule files skipped" \
    '[ -f "$f" ] && [ -r "$f" ] || continue' '[ -f "$f" ] || continue'
else
  echo "  - skipped: mutation 'unreadable rule files skipped' (this user can read a mode-000 file)"
fi
mutation red hook "claudeMdExcludes" \
  ' && !(ex != "" && cur ~ ex)' ''
mutation red hook "the size budget" \
  'if [ -n "$CONTEXT" ] && [ $((CTX_BYTES + BLEN)) -gt "$CTX_BUDGET" ]; then' 'if false; then'
mutation red hook "held-back rules are not recorded as delivered" \
  'NHELD=$((NHELD + 1))' 'NHELD=$((NHELD + 1)); INJECTED_FILES="$INJECTED_FILES$f$NL"'
mutation red hook "the held-back note's bound" \
  'NOTE_MAX=400 ' 'NOTE_MAX=400000 '
mutation red hook "identical text is injected once" \
  '*"$NL$key$NL"*) INJECTED_FILES="$INJECTED_FILES$f$NL"; continue ;;' 'never-matches) ;;'
mutation red settings "the PostToolUse Bash wiring" \
  '"id": "rule-injector",
            "description": "Same hook as' \
  '"id": "rule-injector-off",
            "description": "Same hook as'

# Bounded parallelism; bash 3.2 has no `wait -n`, so wait oldest-first.
RI_JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
[[ "$RI_JOBS" =~ ^[0-9]+$ && "$RI_JOBS" -ge 1 ]] || RI_JOBS=2
[[ "$RI_JOBS" -gt 16 ]] && RI_JOBS=16
RI_SELF="$REPO_ROOT/tests/test-rule-injector.sh"

run_mutant() {
  local h="$HOOK" st="$SETTINGS"
  case "${MUT_TARGETS[$1]}" in
    hook) h="${MUT_FILES[$1]}" ;;
    *) st="${MUT_FILES[$1]}" ;;
  esac
  if command -v timeout >/dev/null 2>&1; then
    RI_MUTANT=1 RI_HOOK="$h" RI_SETTINGS="$st" timeout 120 bash "$RI_SELF" > "$MUT_DIR/m$1.log" 2>&1
  else
    RI_MUTANT=1 RI_HOOK="$h" RI_SETTINGS="$st" bash "$RI_SELF" > "$MUT_DIR/m$1.log" 2>&1
  fi
}

MUT_PIDS=(); MUT_RCS=()
RI_NEXT=0
RI_I=0
while [[ "$RI_I" -lt "$NMUT" ]]; do
  if [[ $((RI_I - RI_NEXT)) -ge "$RI_JOBS" ]]; then
    wait "${MUT_PIDS[$RI_NEXT]}"; MUT_RCS[RI_NEXT]=$?
    RI_NEXT=$((RI_NEXT + 1))
  fi
  run_mutant "$RI_I" &
  MUT_PIDS[RI_I]=$!
  RI_I=$((RI_I + 1))
done
while [[ "$RI_NEXT" -lt "$NMUT" ]]; do
  wait "${MUT_PIDS[$RI_NEXT]}"; MUT_RCS[RI_NEXT]=$?
  RI_NEXT=$((RI_NEXT + 1))
done

RI_I=0
while [[ "$RI_I" -lt "$NMUT" ]]; do
  RI_RC="${MUT_RCS[$RI_I]}"
  RI_FIRST=$(grep -m1 '✗' "$MUT_DIR/m$RI_I.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "${MUT_EXPECT[$RI_I]}" == "green" ]]; then
    if [[ "$RI_RC" -eq 0 ]]; then
      pass "control: ${MUT_NAMES[$RI_I]} leaves the suite green"
    else
      fail "control: ${MUT_NAMES[$RI_I]} leaves the suite green" "rc=$RI_RC, first failure: $RI_FIRST"
    fi
  elif [[ "$RI_RC" -ne 0 ]]; then
    pass "without ${MUT_NAMES[$RI_I]}: red — ${RI_FIRST:-rc=$RI_RC}"
  else
    fail "without ${MUT_NAMES[$RI_I]}: the suite stayed GREEN" "this guard is claimed and not checked"
  fi
  RI_I=$((RI_I + 1))
done
fi

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
