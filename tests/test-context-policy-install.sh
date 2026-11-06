#!/usr/bin/env bash
# test-context-policy-install.sh — the opt-in context policy, end to end.
#
# configs/scripts/context-policy.py (and install.sh §8d, which calls it) writes
# ONE key, top-level `autoCompactWindow`, into a THROWAWAY $HOME under /tmp, and
# only while the sidecar .clade-context-state.json proves the value is Clade's.
# Fake `claude` binaries on PATH print chosen versions, so nothing here depends
# on which Claude Code this machine has. Pinned below:
#
#   opt-in writes; the default writes nothing and never runs `claude`; a second
#   run rewrites no file (bytes, inode and mtime); a user value wins and a user
#   edit transfers ownership; a user deletion — of Clade's value or of one the
#   user took over — is never re-added until --context-policy; opt-out retracts
#   only a Clade-owned value; a malformed sidecar owns nothing; a policy change
#   updates an owned value; retire and the version floor retract; an unreadable
#   version writes and removes nothing; claude is found in ~/.local/bin without
#   PATH, read with stdin closed and a 10 s timeout; a concurrent write is
#   re-applied, not lost; every skip_when condition, an unreadable managed file
#   and a managed-settings.d drop-in (or one that cannot be listed) step aside;
#   a window Anthropic tunes server-side, cached in either form in .claude.json
#   (beside ~/.claude, in $CLAUDE_CONFIG_DIR, or the legacy .config.json),
#   retracts Clade's value and blocks a new one, while a null, empty or invalid
#   cache is no signal; a newer Claude Code gets a notice and the value; a
#   symlinked settings.json stays a symlink with every other key, its order and
#   its mode kept; `status` reports owner, shadowing (a server window too), the
#   real compaction point and Codex/Kimi (their clamps included, or the
#   Python 3.11+ notice) without writing; ~/.codex and
#   ~/.kimi-code end byte-identical to an install.sh without §8d; a failing §8d
#   warns and install.sh goes on; uninstall.sh retracts only Clade's value; no
#   python3 prints a skip line.
#
# The last suite removes each guard from a COPY of the script in turn and
# requires this suite to go red, beside a no-op control that must stay green.
#
# Usage: bash tests/test-context-policy-install.sh
#   CP_SCRIPT=PATH  test this copy of context-policy.py instead of the repo's
#   CP_MUTANT=1     stop at the first failure; skip install.sh runs and mutations

set -uo pipefail

# ─── Harness ──────────────────────────────────────────────────────────

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CP_SCRIPT="${CP_SCRIPT:-$REPO_ROOT/configs/scripts/context-policy.py}"
CP_MUTANT="${CP_MUTANT:-}"
SHIPPED_POLICY="$REPO_ROOT/configs/context-policy.json"

# A check on a case whose apply exited non-zero is not evidence: an absent key
# looks the same whether the policy stepped aside or the script never ran (it
# is how every negative check here would pass against a tree without it).
pass() {
  if [[ -n "${CASE:-}" && -e "${CASE:-}/.apply-failed" ]]; then
    fail "$1" "an apply in this case exited non-zero, so this check proves nothing"
    return 0
  fi
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  [[ -n "$CP_MUTANT" ]] && exit 1
  return 0
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

# check NAME ACTUAL EXPECTED
check() {
  if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1" "got '$2', want '$3'"; fi
}

for tool in jq python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "FATAL: $tool is required"; exit 1; }
done
# The interpreter by absolute path: every apply below runs with a PATH that
# holds only a fake claude, and a pyenv shim would need PATH to find itself.
PY="$(python3 -c 'import sys; print(sys.executable)')"
# `status` reads ~/.codex and ~/.kimi-code config.toml with tomllib (3.11+); on
# an older python3 it prints a "needs Python 3.11+" line instead, and the status
# checks expect that line there.
HAVE_TOMLLIB=""
"$PY" -c 'import tomllib' 2>/dev/null && HAVE_TOMLLIB=1

# ─── Sandbox setup ───────────────────────────────────────────────────

REAL_HOME="$HOME"
SANDBOX="$(mktemp -d /tmp/clade-ctxpol-test-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-ctxpol-test-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' is not under /tmp — aborting before any write"; exit 1 ;;
esac
export HOME="$SANDBOX/home"
mkdir -p "$HOME"
if [[ "$HOME" == "$REAL_HOME" ]]; then
  echo "FATAL: fake HOME equals real HOME — aborting"
  exit 1
fi
cleanup() {
  [[ -n "${SLOW_PID:-}" ]] && kill "$SLOW_PID" 2>/dev/null
  chmod 755 "$SANDBOX/unlist/managed-settings.d" 2>/dev/null  # mode 000 below; rm -rf cannot list it
  rm -rf "$SANDBOX"
}
trap cleanup EXIT
# `status` reads a project's .claude/settings.json from the current directory;
# the developer's checkout must not be that project.
cd "$SANDBOX" || exit 1

# Any of these in the developer's own environment would make every write step aside
# (CLAUDE_CONFIG_DIR: a real profile's .claude.json caching a server-side window).
unset CLAUDE_CODE_AUTO_COMPACT_WINDOW CLAUDE_AUTOCOMPACT_PCT_OVERRIDE DISABLE_COMPACT \
      DISABLE_AUTO_COMPACT CLADE_CONTEXT_POLICY CLAUDE_CONFIG_DIR

KEY=autoCompactWindow
STATE=.clade-context-state.json

# mkclaude NAME EXIT LINE... — a fake `claude` in $SANDBOX/bin/NAME that prints
# each LINE and exits EXIT, and appends to a `ran` marker so a test can prove
# whether it was executed at all. Builtins only: PATH holds nothing else.
mkclaude() {
  local d="$SANDBOX/bin/$1" code="$2" l
  shift 2
  mkdir -p "$d"
  {
    echo '#!/bin/sh'
    echo "echo x >> '$d/ran'"
    for l in "$@"; do echo "echo '$l'"; done
    echo "exit $code"
  } > "$d/claude"
  chmod +x "$d/claude"
}
mkclaude v283 0 "2.1.283 (Claude Code)"
mkclaude v200 0 "2.1.200 (Claude Code)"
mkclaude v300 0 "2.1.300 (Claude Code)"
mkclaude v318 0 "2.1.318 (Claude Code)"
mkclaude banner 0 "Loading your shell banner..." "2.1.283 (Claude Code)"
# A version-shaped line from something else, above the floor: only the
# "(Claude Code)" anchor keeps it from being read as Claude Code 3.4.5.
mkclaude garbage 0 "3.4.5 (another tool)"
mkclaude badexit 1 "2.1.283 (Claude Code)"
mkclaude gone 127
mkdir -p "$SANDBOX/bin/none"
# A native install: `claude` is a link into .../versions/X.Y.Z, a binary whose
# --version output this test makes unreadable, so only the realpath can tell.
mkdir -p "$SANDBOX/bin/linked" "$SANDBOX/share/versions"
printf '#!/bin/sh\nexit 127\n' > "$SANDBOX/share/versions/2.1.283"
chmod +x "$SANDBOX/share/versions/2.1.283"
ln -s "$SANDBOX/share/versions/2.1.283" "$SANDBOX/bin/linked/claude"
# mkscript NAME BODY — a fake claude whose body is raw sh (sleep by absolute path:
# PATH holds only the fake). stdin: reads stdin to EOF first, so it answers at
# once only when apply closes stdin. slow: answers after 90 s, far past the 10 s
# timeout, so a bound with room for a loaded host's own overhead still tells
# "gave up at the timeout" from "waited for the answer". racer: rewrites the
# race case's settings.json while it is asked.
SLEEP_BIN="$(command -v sleep)"
mkscript() { mkdir -p "$SANDBOX/bin/$1"; printf '#!/bin/sh\n%s\n' "$2" > "$SANDBOX/bin/$1/claude"; chmod +x "$SANDBOX/bin/$1/claude"; }
mkscript stdin 'while read -r line; do :; done; echo "2.1.283 (Claude Code)"'
mkscript slow "$SLEEP_BIN 90; echo '2.1.283 (Claude Code)'"
mkscript racer "echo x >> '$SANDBOX/bin/racer/ran'; printf '{\"effortLevel\": \"high\"}\\n' > '$SANDBOX/cases/race/settings.json'; echo '2.1.283 (Claude Code)'"

# mkpolicy NAME JQ_FILTER — the shipped policy, off by default, with managed
# settings pointed into the sandbox so a real /etc file cannot leak in.
mkpolicy() {
  jq --arg m "$SANDBOX/managed-$1.json" \
    ".claude_code.$KEY.enabled_by_default = false
     | .claude_code.$KEY.skip_when.managed_settings = [\$m] | $2" \
    "$SHIPPED_POLICY" > "$SANDBOX/policy-$1.json"
}
mkpolicy base '.'
mkpolicy p300 ".claude_code.$KEY.value = 300000"
mkpolicy retire ".claude_code.$KEY.retire_from_cc_version = \"2.1.300\""
mkpolicy managed '.'
printf '{"%s": 600000}\n' "$KEY" > "$SANDBOX/managed-managed.json"
mkpolicy badjson '.'
printf '{ this is not json\n' > "$SANDBOX/managed-badjson.json"
mkpolicy noread '.'
printf '{}\n' > "$SANDBOX/managed-noread.json"
chmod 000 "$SANDBOX/managed-noread.json"
# Drop-ins live beside the managed file, so each gets its own directory: one
# that shadows, and one whose only entries are a dot-file and a non-.json file,
# both of which Claude Code skips.
mkdropin() {  # mkdropin NAME FILE — policy-NAME.json with managed settings in $SANDBOX/NAME/
  mkdir -p "$SANDBOX/$1/managed-settings.d"
  printf '{"env": {"DISABLE_COMPACT": "1"}}\n' > "$SANDBOX/$1/managed-settings.d/$2"
  jq --arg m "$SANDBOX/$1/managed-settings.json" \
    ".claude_code.$KEY.enabled_by_default = false | .claude_code.$KEY.skip_when.managed_settings = [\$m]" \
    "$SHIPPED_POLICY" > "$SANDBOX/policy-$1.json"
}
mkdropin dropin 10-admin.json
mkdropin dropinskip .hidden.json
printf '{"env": {"DISABLE_COMPACT": "1"}}\n' > "$SANDBOX/dropinskip/managed-settings.d/notes.txt"
# A drop-in directory that exists and cannot be listed may hold anything.
mkdropin unlist 10-admin.json
chmod 000 "$SANDBOX/unlist/managed-settings.d"

# newcase NAME [SETTINGS_JSON] — a fresh claude dir; settings omitted = no file
newcase() {
  CASE="$SANDBOX/cases/$1"
  mkdir -p "$CASE"
  [[ $# -ge 2 ]] && printf '%s\n' "$2" > "$CASE/settings.json"
  return 0
}

# apply BIN POLICY [args...] — runs against $CASE; output in $CASE/apply.log.
# install.sh treats a non-zero exit as a failed step, so any is a failure here.
apply() {
  local bin="$1" pol="$2" rc
  shift 2
  PATH="$SANDBOX/bin/$bin" "$PY" "$CP_SCRIPT" apply --claude-dir "$CASE" \
    --policy "$SANDBOX/policy-$pol.json" "$@" > "$CASE/apply.log" 2>&1
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    touch "$CASE/.apply-failed"
    fail "apply exits 0 ($(basename "$CASE"), $bin, $*)" "rc=$rc: $(tail -3 "$CASE/apply.log")"
  fi
  return 0
}

val() {
  [[ -f "$CASE/settings.json" ]] || { echo NOFILE; return; }
  jq -r "if has(\"$KEY\") then (.$KEY | tostring) else \"ABSENT\" end" "$CASE/settings.json" 2>/dev/null \
    || echo UNPARSEABLE
}
state() { jq -r "$1" "$CASE/$STATE" 2>/dev/null || echo NOSTATE; }
sha() { cat "$@" 2>/dev/null | { sha256sum 2>/dev/null || shasum -a 256; } | cut -c1-64; }
logged() { grep -qF -- "$1" "$CASE/apply.log"; }
set_value() { jq ".$KEY = $1" "$CASE/settings.json" > "$CASE/s.tmp" && mv "$CASE/s.tmp" "$CASE/settings.json"; }

echo "Sandbox: $SANDBOX"
echo "Script:  $CP_SCRIPT"

# The timeout case needs 10 s of wall time, so it starts here in the background
# and is collected at the end of suite 8, behind every other case.
mkdir -p "$SANDBOX/cases/slow"
printf '{}\n' > "$SANDBOX/cases/slow/settings.json"
SLOW_T0=$(date +%s)
PATH="$SANDBOX/bin/slow" "$PY" "$CP_SCRIPT" apply --claude-dir "$SANDBOX/cases/slow" \
  --policy "$SANDBOX/policy-base.json" --opt-in </dev/null > "$SANDBOX/cases/slow/apply.log" 2>&1 &
SLOW_PID=$!

# ─── Suite 1: opt-in, default, idempotency ───────────────────────────

section "Opt-in writes; the default writes nothing; a re-run changes no byte"

newcase optin '{"x": 1}'
apply v283 base --opt-in
check "opt-in on 2.1.283 writes $KEY = 350000" "$(val)" "350000"
check "the sidecar records what Clade wrote, on which version, and the choice" \
  "$(state '[.choice, .claude_code.autoCompactWindow.wrote, .claude_code.autoCompactWindow.cc_version] | join(",")')" \
  "in,350000,2.1.283"
before="$(sha "$CASE/settings.json" "$CASE/$STATE")"
# Identical bytes do not prove nothing was written: a rewrite keeps the hash but
# replaces the inode and the mtime (breaking hard links, waking file watchers).
inode() { ls -i "$1" | awk '{print $1}'; }
touch -t 202001010000 "$SANDBOX/old-stamp" "$CASE/settings.json" "$CASE/$STATE"
inodes_before="$(inode "$CASE/settings.json") $(inode "$CASE/$STATE")"
apply v283 base
check "a second run (no flag: the choice persisted) leaves settings.json and the sidecar byte-identical" \
  "$(sha "$CASE/settings.json" "$CASE/$STATE")|$(val)" "$before|350000"
rewritten=""
for f in settings.json "$STATE"; do [[ "$CASE/$f" -nt "$SANDBOX/old-stamp" ]] && rewritten="$rewritten $f"; done
check "and rewrites neither file: same inodes, mtimes untouched" \
  "$(inode "$CASE/settings.json") $(inode "$CASE/$STATE")|${rewritten:-none}" "$inodes_before|none"

newcase default '{"x":1}'
rm -f "$SANDBOX/bin/v283/ran"
apply v283 base
if [[ "$(val)" == "ABSENT" && ! -e "$CASE/$STATE" ]] && logged "./install.sh --context-policy" \
   && [[ ! -e "$SANDBOX/bin/v283/ran" ]]; then
  pass "not opted in: no key, no sidecar, never runs claude, and the log names the opt-in flag"
else
  fail "not opted in: no key, no sidecar, never runs claude, and the log names the opt-in flag" \
    "value=$(val) sidecar=$([[ -e "$CASE/$STATE" ]] && echo yes || echo no) ran=$([[ -e "$SANDBOX/bin/v283/ran" ]] && echo yes || echo no) log=$(cat "$CASE/apply.log")"
fi
check "a no-op run does not even reformat settings.json" "$(cat "$CASE/settings.json")" '{"x":1}'

# ─── Suite 2: the user's value is the user's ─────────────────────────

section "A user value wins, an edit transfers ownership, a deletion is never re-added"

newcase uservalue '{"autoCompactWindow":500000}'
before="$(sha "$CASE/settings.json")"
apply v283 base --opt-in
check "a value the user set first is left alone, byte for byte" "$(sha "$CASE/settings.json")|$(val)" "$before|500000"
check "and Clade records no ownership of it" "$(state '.claude_code.autoCompactWindow.wrote')" "null"

newcase useredit '{}'
apply v283 base --opt-in
set_value 400000
apply v283 base
check "a user edit after Clade wrote is kept" "$(val)" "400000"
check "and ownership transfers to the user" "$(state '.claude_code.autoCompactWindow.wrote')" "null"
apply v283 p300
check "a later policy value does not overwrite the user's edit" "$(val)" "400000"
apply v283 base --opt-out
check "opt-out does not remove the user's edit" "$(val)" "400000"

newcase userfloat '{}'
apply v283 base --opt-in
# 350000.0 == 350000 in Python, so only an exact-int test sees the user's edit.
# Written raw: jq would normalise the literal back to 350000.
printf '{"%s": 350000.0}\n' "$KEY" > "$CASE/settings.json"
apply v283 base --opt-out
check "ownership is exact int equality: 350000.0 written by the user stays through opt-out" \
  "$(grep -c '350000\.0' "$CASE/settings.json")" "1"

newcase userdelete '{}'
apply v283 base --opt-in
jq "del(.$KEY)" "$CASE/settings.json" > "$CASE/s.tmp" && mv "$CASE/s.tmp" "$CASE/settings.json"
apply v283 base
check "a key the user deleted is not re-added" "$(val)" "ABSENT"
check "the sidecar records user_removed" "$(state '.claude_code.autoCompactWindow.user_removed')" "true"
apply v283 base
check "nor on the run after that" "$(val)" "ABSENT"
apply v283 base --opt-in
check "--opt-in (./install.sh --context-policy) re-adds it" \
  "$(val)|$(state '.claude_code.autoCompactWindow.user_removed')" "350000|false"

# A value the user took over stays theirs when they delete it: on 2.1.283
# `/autocompact N` then `/autocompact auto` is exactly this sequence.
newcase takeover '{}'
apply v283 base --opt-in
set_value 500000
apply v283 base
check "a user edit marks the key as the user's in the sidecar" "$(state '.claude_code.autoCompactWindow.user_owned')" "true"
jq "del(.$KEY)" "$CASE/settings.json" > "$CASE/s.tmp" && mv "$CASE/s.tmp" "$CASE/settings.json"
apply v283 base
check "a value the user took over and then deleted is not re-added" \
  "$(val)|$(state '.claude_code.autoCompactWindow.user_removed')" "ABSENT|true"
newcase ownvalue '{"autoCompactWindow":500000}'
apply v283 base --opt-in
printf '{}\n' > "$CASE/settings.json"
apply v283 base
check "the user's own value, there before opt-in and deleted after it, is not replaced" "$(val)" "ABSENT"
apply v283 base --opt-in
check "until --opt-in, which writes it" "$(val)" "350000"

# The takeover is recorded even while the policy is off for this host: a
# maintainer flipping enabled_by_default (TODO.md, PR 3) and back must not
# refill a key the user took over and then deleted in between.
mkpolicy on ".claude_code.$KEY.enabled_by_default = true"
newcase flip '{}'
apply v283 on
set_value 500000
apply v283 base
jq "del(.$KEY)" "$CASE/settings.json" > "$CASE/s.tmp" && mv "$CASE/s.tmp" "$CASE/settings.json"
apply v283 base
apply v283 on
check "a key the user took over while the policy was off, then deleted, stays absent when it is on again" "$(val)" "ABSENT"

# ─── Suite 3: opt-out, policy update, retire, version floor ──────────

section "Opt-out, a policy change, retirement and the version floor touch only Clade's value"

newcase optout '{}'
apply v283 base --opt-in
apply v283 base --opt-out
check "opt-out removes a Clade-owned value" "$(val)" "ABSENT"
check "and records the choice" "$(state '.choice')" "out"
apply v283 base
check "a plain re-run keeps it out" "$(val)" "ABSENT"
newcase optoutuser '{"autoCompactWindow":500000}'
apply v283 base --opt-out
check "opt-out leaves a user value alone" "$(val)" "500000"

newcase update '{}'
apply v283 base --opt-in
apply v283 p300
check "a policy value change updates a value Clade still owns" \
  "$(val)|$(state '.claude_code.autoCompactWindow.wrote')" "300000|300000"

newcase retire '{}'
apply v283 base --opt-in
apply v318 retire
check "retire_from_cc_version reached: the Clade-owned value is withdrawn" "$(val)" "ABSENT"
newcase retireedge '{}'
apply v283 base --opt-in
apply v300 retire
check "retire applies AT retire_from_cc_version, not only above it" "$(val)" "ABSENT"
newcase retireuser '{"autoCompactWindow":500000}'
apply v318 retire --opt-in
check "retirement leaves a user value alone" "$(val)" "500000"
newcase retirefresh '{}'
apply v318 retire --opt-in
check "an opt-in at or above retire_from_cc_version, with nothing Clade-owned, writes nothing and says why" \
  "$(val)|$(grep -c 'nothing written: retired from Claude Code 2.1.300' "$CASE/apply.log")" "ABSENT|1"

newcase floor '{}'
apply v200 base --opt-in
check "below min_cc_version (2.1.200 < 2.1.236) nothing is written" "$(val)" "ABSENT"
if logged "below the verified floor 2.1.236"; then pass "and the log names the floor"; else fail "and the log names the floor" "$(cat "$CASE/apply.log")"; fi
newcase floorowned '{}'
apply v283 base --opt-in
apply v200 base
check "an owned value is withdrawn on a Claude Code below the floor" "$(val)" "ABSENT"

# A malformed sidecar owns nothing: each of these claims wrote=350000, and an
# opt-out that believed it would delete the user's identical value.
slot_ok='"cc_version":"2.1.283","user_removed":false,"user_owned":false'
for spec in "invalid JSON|{\"schema\":" \
            "a wrong schema|{\"schema\":\"something-else/v9\",\"choice\":\"in\",\"claude_code\":{\"$KEY\":{\"wrote\":350000,$slot_ok}}}" \
            "a quoted wrote|{\"schema\":\"clade.context-state/v1\",\"choice\":\"in\",\"claude_code\":{\"$KEY\":{\"wrote\":\"350000\",$slot_ok}}}" \
            "a non-boolean flag|{\"schema\":\"clade.context-state/v1\",\"choice\":\"in\",\"claude_code\":{\"$KEY\":{\"wrote\":350000,\"cc_version\":\"2.1.283\",\"user_removed\":\"no\",\"user_owned\":false}}}"; do
  newcase "sidecar-${spec%%|*}" '{"autoCompactWindow":350000}'
  printf '%s\n' "${spec#*|}" > "$CASE/$STATE"
  apply v283 base --opt-out
  if [[ "$(val)" == "350000" ]] && logged "sidecar unreadable or malformed"; then
    pass "a sidecar with ${spec%%|*} owns nothing: opt-out keeps the value and says why"
  else
    fail "a sidecar with ${spec%%|*} owns nothing: opt-out keeps the value and says why" "value=$(val) log=$(cat "$CASE/apply.log")"
  fi
done

# settings.json that is not a JSON object is left exactly as it was, and the
# exit status says so (install.sh turns it into a WARNING and goes on).
for spec in "an array|[1,2]" "truncated JSON|{\"a\":1,"; do
  newcase "notobject-${spec%%|*}"
  printf '%s\n' "${spec#*|}" > "$CASE/settings.json"
  before="$(sha "$CASE/settings.json")"
  PATH="$SANDBOX/bin/v283" "$PY" "$CP_SCRIPT" apply --claude-dir "$CASE" --policy "$SANDBOX/policy-base.json" \
    --opt-in > "$CASE/apply.log" 2>&1
  check "settings.json holding ${spec%%|*}: apply exits 1 and changes no byte" \
    "$?|$(sha "$CASE/settings.json")|$(grep -c 'settings.json unreadable' "$CASE/apply.log")" "1|$before|1"
done

# `uninstall` (uninstall.sh): retract like --opt-out, then drop the sidecar —
# unless a value is still Clade's because the version could not be read.
uninstall() {  # uninstall BIN
  PATH="$SANDBOX/bin/$1" "$PY" "$CP_SCRIPT" uninstall --claude-dir "$CASE" \
    --policy "$SANDBOX/policy-base.json" > "$CASE/apply.log" 2>&1
}
newcase uninst '{}'
apply v283 base --opt-in
uninstall v283
check "uninstall retracts a Clade-owned value and removes the sidecar" \
  "$?|$(val)|$([[ -e "$CASE/$STATE" ]] && echo sidecar || echo none)" "0|ABSENT|none"
newcase uninstuser '{}'
apply v283 base --opt-in
set_value 500000
uninstall v283
check "uninstall keeps a user value and removes the sidecar" \
  "$?|$(val)|$([[ -e "$CASE/$STATE" ]] && echo sidecar || echo none)" "0|500000|none"
newcase uninstgone '{}'
apply v283 base --opt-in
uninstall gone
if [[ "$(val)" == "350000" && -e "$CASE/$STATE" ]] && logged "kept $STATE"; then
  pass "uninstall with an unreadable version keeps the value AND the sidecar that proves it is Clade's"
else
  fail "uninstall with an unreadable version keeps the value AND the sidecar that proves it is Clade's" \
    "value=$(val) log=$(cat "$CASE/apply.log")"
fi
newcase uninstnever '{"autoCompactWindow":500000}'
rm -f "$SANDBOX/bin/v283/ran"
uninstall v283
check "uninstall where Clade never applied: no sidecar written, claude never run, and it says so" \
  "$?|$(val)|$([[ -e "$CASE/$STATE" ]] && echo sidecar || echo none)|$([[ -e "$SANDBOX/bin/v283/ran" ]] && echo ran || echo idle)|$(grep -c 'never applied here' "$CASE/apply.log")" \
  "0|500000|none|idle|1"

# ─── Suite 4: version detection fails closed ─────────────────────────

section "An unreadable Claude Code version writes nothing and removes nothing"

for bin in gone garbage none badexit; do
  newcase "unread-$bin" '{}'
  apply "$bin" base --opt-in
  check "unreadable version ($bin): nothing written" "$(val)" "ABSENT"
done
newcase unreadowned '{}'
apply v283 base --opt-in
apply gone base --opt-out
check "unreadable version: a Clade-owned value is not removed even on opt-out" "$(val)" "350000"
apply v283 base
check "and the persisted opt-out applies once the version is readable again" "$(val)" "ABSENT"
newcase banner '{}'
apply banner base --opt-in
check "every output line is scanned: a banner before the version line is skipped" "$(val)" "350000"
newcase linked '{}'
apply linked base --opt-in
check "fallback: a claude linked into .../versions/2.1.283 is read from its realpath" \
  "$(val)|$(state '.claude_code.autoCompactWindow.cc_version')" "350000|2.1.283"

# `ssh host ./install.sh` (fleet-install.sh) runs a shell that never sources the
# rc file putting ~/.local/bin on PATH, so the installers' locations are tried
# by path. PATH here holds no claude at all.
for loc in .local/bin .claude/local; do
  newcase "home-${loc//\//-}" '{}'
  mkdir -p "$CASE/home/$loc"
  cp "$SANDBOX/bin/v283/claude" "$CASE/home/$loc/claude"
  HOME="$CASE/home" PATH="$SANDBOX/bin/none" "$PY" "$CP_SCRIPT" apply --claude-dir "$CASE" \
    --policy "$SANDBOX/policy-base.json" --opt-in > "$CASE/apply.log" 2>&1
  check "claude in ~/$loc, not on PATH, is still found" "$?|$(val)" "0|350000"
done

# stdin is closed for `claude --version`: a wrapper that reads stdin would
# otherwise wait on whatever install.sh was given — here a pipe held open 15 s.
newcase stdin '{}'
t0=$(date +%s)
PATH="$SANDBOX/bin/stdin" "$PY" "$CP_SCRIPT" apply --claude-dir "$CASE" --policy "$SANDBOX/policy-base.json" \
  --opt-in < <("$SLEEP_BIN" 15) > "$CASE/apply.log" 2>&1
check "a claude that reads stdin answers at once: stdin is closed, not inherited" \
  "$?|$(val)|$(( $(date +%s) - t0 < 8 ))" "0|350000|1"

# A live session writes settings.json (/effort, /autocompact) between apply's
# read and its write: the change is re-read and kept, and claude runs once.
newcase race '{}'
apply racer base --opt-in
check "a concurrent write to settings.json is re-applied, not lost" \
  "$(jq -c "{effortLevel, $KEY}" "$CASE/settings.json" 2>/dev/null)|$(wc -l < "$SANDBOX/bin/racer/ran" | tr -d ' ')" \
  "{\"effortLevel\":\"high\",\"$KEY\":350000}|1"

newcase newer '{}'
apply v318 base --opt-in
check "newer than verified_through (2.1.318 > 2.1.283): the value is still written" "$(val)" "350000"
if logged "verified through Claude Code 2.1.283; you run 2.1.318" && logged "https://code.claude.com/docs/en/model-config"; then
  pass "and a notice names both versions and the docs URL"
else
  fail "and a notice names both versions and the docs URL" "$(cat "$CASE/apply.log")"
fi

# ─── Suite 5: skip_when ──────────────────────────────────────────────

section "Every more specific mechanism makes Clade step aside"

skip_case() {  # skip_case NAME SETTINGS_JSON [ENV=VALUE] [POLICY]
  newcase "skip-$1" "$2"
  if [[ -n "${3:-}" ]]; then
    env "$3" PATH="$SANDBOX/bin/v283" "$PY" "$CP_SCRIPT" apply --claude-dir "$CASE" \
      --policy "$SANDBOX/policy-${4:-base}.json" --opt-in > "$CASE/apply.log" 2>&1 \
      || { touch "$CASE/.apply-failed"; fail "apply exits 0 (skip-$1)" "$(tail -3 "$CASE/apply.log")"; }
  else
    apply v283 "${4:-base}" --opt-in
  fi
  if [[ "$(val)" == "ABSENT" ]] && logged "steps aside for"; then
    pass "skip_when: $1 — nothing written"
  else
    fail "skip_when: $1 — nothing written" "value=$(val) log=$(cat "$CASE/apply.log")"
  fi
}
skip_case "settings env CLAUDE_CODE_AUTO_COMPACT_WINDOW" '{"env":{"CLAUDE_CODE_AUTO_COMPACT_WINDOW":"400000"}}'
skip_case "process env CLAUDE_CODE_AUTO_COMPACT_WINDOW" '{}' "CLAUDE_CODE_AUTO_COMPACT_WINDOW=400000"
skip_case "settings env DISABLE_COMPACT" '{"env":{"DISABLE_COMPACT":"1"}}'
skip_case "settings env DISABLE_AUTO_COMPACT" '{"env":{"DISABLE_AUTO_COMPACT":"1"}}'
skip_case "process env DISABLE_AUTO_COMPACT" '{}' "DISABLE_AUTO_COMPACT=1"
skip_case "settings env CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" '{"env":{"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE":"50"}}'
skip_case "autoCompactEnabled false" '{"autoCompactEnabled":false}'
skip_case "modelSettings.*.autoCompactWindow" '{"modelSettings":{"claude-opus-5-5":{"autoCompactWindow":500000}}}'
skip_case "managed settings" '{}' "" managed
skip_case "managed settings that are not JSON (fail closed)" '{}' "" badjson
if [[ "$(id -u)" -ne 0 ]]; then
  skip_case "managed settings that cannot be read (mode 000; fail closed)" '{}' "" noread
else
  echo "  - skipped: mode-000 managed settings (root reads any file)"
fi
skip_case "a managed-settings.d/*.json drop-in" '{}' "" dropin
if [[ "$(id -u)" -ne 0 ]]; then
  skip_case "a managed-settings.d that cannot be listed (mode 000; fail closed)" '{}' "" unlist
else
  echo "  - skipped: a managed-settings.d that cannot be listed (root lists any directory)"
fi

newcase dropinskip '{}'
apply v283 dropinskip --opt-in
check "control: a dot-file and a non-.json file in managed-settings.d are skipped, as Claude Code skips them" \
  "$(val)" "350000"

newcase skipcontrol '{"autoCompactEnabled":true,"modelSettings":{"claude-opus-5-5":{"effortLevel":"medium"}},"env":{"A":"1"}}'
apply v283 base --opt-in
check "control: autoCompactEnabled true and a modelSettings entry without the key do not step aside" "$(val)" "350000"

# ─── Suite 5b: a window Anthropic tunes server-side ──────────────────
#
# The settings key outranks a server-side window (2.1.283 resolver: env, this
# key, then the rowan_thicket client data and autoCompactWindowsCache), so
# while Claude Code's global config caches one, Clade retracts its own value
# and writes none. The forms below are the ones the 2.1.283 binary reads.

section "A window Anthropic tunes server-side: Clade retracts its value and writes none"

ACWC='{"autoCompactWindowsCache":{"claude-opus-5-5":400000}}'
ACWC_OBJ='{"autoCompactWindowsCache":{"claude-opus-5-5":{"default":400000,"surfaces":{"cli":450000}}}}'
ROWAN='{"clientDataCacheSlots":{"bi1-a":{"data":{"cedar_basin":1}},"bi1-b":{"data":{"rowan_thicket":{"claude-opus-5-5":{"default":400000}}}}}}'
LEGACY_CD='{"clientDataCache":{"rowan_thicket":{"claude-opus-5-5":400000}}}'

server_case() {  # server_case NAME FILE GLOBAL_JSON LOGGED WHAT — opt-in with GLOBAL_JSON in $CASE/FILE writes nothing
  newcase "server-$1" '{}'
  printf '%s\n' "$3" > "$CASE/$2"
  apply v283 base --opt-in
  if [[ "$(val)" == "ABSENT" ]] && logged "nothing written: Anthropic tunes the window server-side" && logged "$4"; then
    pass "server-side window, $5: opt-in writes nothing and names it"
  else
    fail "server-side window, $5: opt-in writes nothing and names it" "value=$(val) log=$(cat "$CASE/apply.log")"
  fi
}
server_case acwc .claude.json "$ACWC" "/.claude.json autoCompactWindowsCache" "autoCompactWindowsCache (a number per model)"
server_case acwcobj .claude.json "$ACWC_OBJ" "autoCompactWindowsCache" "autoCompactWindowsCache ({default, surfaces} per model)"
server_case rowan .claude.json "$ROWAN" "clientDataCacheSlots rowan_thicket" "rowan_thicket in one of several clientDataCacheSlots"
server_case legacycd .claude.json "$LEGACY_CD" "clientDataCache rowan_thicket" "rowan_thicket in the legacy clientDataCache"
server_case configjson .config.json "$ACWC" "/.config.json autoCompactWindowsCache" "in the legacy .config.json 2.1.283 reads first"

newcase server-retract '{}'
apply v283 base --opt-in
printf '%s\n' "$ACWC" > "$CASE/.claude.json"
apply v283 base
check "a Clade-owned value is retracted once a server window is cached, and says why" \
  "$(val)|$(state '.claude_code.autoCompactWindow.wrote')|$(grep -c 'Removed autoCompactWindow (Clade-owned): Anthropic tunes the window server-side' "$CASE/apply.log")" \
  "ABSENT|null|1"
printf '{"autoCompactWindowsCache": null}\n' > "$CASE/.claude.json"
apply v283 base
check "and written again once the cache is null: the opt-in persisted and the user removed nothing" "$(val)" "350000"

newcase server-user '{"autoCompactWindow":500000}'
printf '%s\n' "$ACWC" > "$CASE/.claude.json"
apply v283 base --opt-in
check "a user value is left alone while a server window is cached" "$(val)" "500000"

# The default layout: claude dir ~/.claude, Claude Code's global config ~/.claude.json beside it.
newcase "dothome/.claude" '{}'
printf '%s\n' "$ACWC" > "$SANDBOX/cases/dothome/.claude.json"
apply v283 base --opt-in
check "claude dir named .claude: the .claude.json beside it (~/.claude.json) is read" "$(val)" "ABSENT"
newcase "plainhome/claude" '{}'
printf '%s\n' "$ACWC" > "$SANDBOX/cases/plainhome/.claude.json"
apply v283 base --opt-in
check "control: a claude dir NOT named .claude does not read its parent's .claude.json" "$(val)" "350000"

mkdir -p "$SANDBOX/configdir"
printf '%s\n' "$ACWC" > "$SANDBOX/configdir/.claude.json"
newcase server-configdir '{}'
CLAUDE_CONFIG_DIR="$SANDBOX/configdir" apply v283 base --opt-in
check "\$CLAUDE_CONFIG_DIR/.claude.json is read" "$(val)" "ABSENT"

# Claude Code rewrites .claude.json constantly: a torn read is no signal, and
# neither is a cache that is null (as on aries today) or empty.
for spec in "invalid JSON (a rewrite read mid-write)|{\"autoCompactWindowsCache\": {\"claude-opus-5-5\": 4" \
            "a JSON array|[1, 2]" \
            "null caches|{\"autoCompactWindowsCache\": null, \"clientDataCacheSlots\": {\"bi1-a\": {\"data\": {\"rowan_thicket\": null}}}, \"clientDataCache\": null}" \
            "empty caches|{\"autoCompactWindowsCache\": {}, \"clientDataCacheSlots\": {\"bi1-a\": {\"data\": {\"rowan_thicket\": {}}}}, \"clientDataCache\": {\"rowan_thicket\": {}}}"; do
  newcase "server-none-${spec%%|*}" '{}'
  printf '%s\n' "${spec#*|}" > "$CASE/.claude.json"
  apply v283 base --opt-in
  check "control: .claude.json holding ${spec%%|*} is no signal: apply exits 0 and writes the value" "$(val)" "350000"
done

# ─── Suite 6: the write itself ───────────────────────────────────────

section "A symlinked settings.json stays a symlink; every other key, its order and mode are kept"

newcase symlink
cat > "$CASE/real.json" <<'JSON'
{"z": 1, "env": {"TG_CHAT_ID": "1"}, "hooks": {"Stop": []}, "permissions": {"deny": ["Read(~/.ssh/**)"]},
 "modelSettings": {"claude-opus-5-5": {"effortLevel": "medium"}}, "a": [1, 2]}
JSON
chmod 644 "$CASE/real.json"
ln -s "$CASE/real.json" "$CASE/settings.json"
others_before="$(jq -cS "del(.$KEY)" "$CASE/real.json")"
order_before="$(jq -c 'keys_unsorted' "$CASE/real.json")"
apply v283 base --opt-in
check "the key landed in the link target" "$(val)" "350000"
if [[ -L "$CASE/settings.json" ]]; then pass "settings.json is still a symlink"; else fail "settings.json is still a symlink"; fi
check "every other key keeps its value" "$(jq -cS "del(.$KEY)" "$CASE/real.json")" "$others_before"
check "every other key keeps its order (the new key is appended)" \
  "$(jq -c 'keys_unsorted' "$CASE/real.json")" "$(jq -c ". + [\"$KEY\"]" <<<"$order_before")"
mode="$(stat -c %a "$CASE/real.json" 2>/dev/null || stat -f %Lp "$CASE/real.json")"
check "the file mode is kept (644)" "$mode" "644"

newcase nofile
apply v283 base --opt-in
check "no settings.json yet: it is created holding the key, mode 600" \
  "$(val)|$(stat -c %a "$CASE/settings.json" 2>/dev/null || stat -f %Lp "$CASE/settings.json")" "350000|600"

# ─── Suite 7: status ─────────────────────────────────────────────────

section "status reports owner, shadowing, versions and Codex/Kimi without writing"

mkdir -p "$HOME/.codex" "$HOME/.kimi-code"
printf 'model = "gpt-6-astra"\n\n[profiles.fast]\nmodel = "x"\n' > "$HOME/.codex/config.toml"
printf 'default_model = "kimi-code/k3"\n\n[models."kimi-code/k3"]\nmax_context_size = 1048576\n\n[providers.moonshot]\napi_key = "sk-NEVER-PRINTED"\n' \
  > "$HOME/.kimi-code/config.toml"
vendor_before="$(sha "$HOME/.codex/config.toml" "$HOME/.kimi-code/config.toml")"

status() { PATH="$SANDBOX/bin/$1" "$PY" "$CP_SCRIPT" status --claude-dir "$CASE" --policy "$SANDBOX/policy-base.json" "${@:2}" 2>&1; }
CASE="$SANDBOX/cases/optin"
before="$(sha "$CASE/settings.json" "$CASE/$STATE")"
out_json="$(status v283 --json)"
check "status --json: a Clade-written value is owned by clade" "$(jq -r ".$KEY.owner" <<<"$out_json" 2>/dev/null)" "clade"
check "status --json: the 1M-model trigger is 350000 - 20000 - 13000" "$(jq -r '.trigger_1m_model' <<<"$out_json" 2>/dev/null)" "317000"
CASE="$SANDBOX/cases/uservalue"
check "status --json: a user value is owned by the user" "$(status v283 --json | jq -r ".$KEY.owner" 2>/dev/null)" "user"
CASE="$SANDBOX/cases/skip-settings env CLAUDE_CODE_AUTO_COMPACT_WINDOW"
check "status --json: shadowing is reported, and no compaction point is claimed under it" \
  "$(status v283 --json | jq -r '[.shadowed_by[0], .trigger_1m_model] | map(tostring) | join("|")' 2>/dev/null)" \
  "settings.json env.CLAUDE_CODE_AUTO_COMPACT_WINDOW|null"
newcase status-range '{"autoCompactWindow":50000}'
check "status --json: a value Claude Code drops (50000 < 100000) reports the default point, 967000" \
  "$(status v283 --json | jq -r '.trigger_1m_model' 2>/dev/null)" "967000"
# Run from $HOME, .claude/settings.json is the user file itself, not a project's.
mkdir -p "$SANDBOX/cases/homecwd/.claude" "$SANDBOX/cases/proj/.claude"
printf '{"%s": 350000}\n' "$KEY" | tee "$SANDBOX/cases/homecwd/.claude/settings.json" \
  > "$SANDBOX/cases/proj/.claude/settings.json"
CASE="$SANDBOX/cases/homecwd/.claude"
check "status run from \$HOME does not report the user settings.json as a project setting" \
  "$(cd "$SANDBOX/cases/homecwd" && status v283 --json | jq -r '.shadowed_by | length' 2>/dev/null)" "0"
check "control: run from a project whose .claude/settings.json sets the key, status reports it" \
  "$(cd "$SANDBOX/cases/proj" && status v283 --json | jq -r '.shadowed_by[0] | startswith("project ")' 2>/dev/null)" "true"
CASE="$SANDBOX/cases/optin"
out="$(status v318)"
if grep -qF "NOTICE: you run 2.1.318, newer than the verified 2.1.283" <<<"$out" \
   && grep -qF "https://code.claude.com/docs/en/model-config" <<<"$out"; then
  pass "status on a newer Claude Code says to re-verify and names the docs URL (as text)"
else
  fail "status on a newer Claude Code says to re-verify and names the docs URL (as text)" "$out"
fi
if [[ -n "$HAVE_TOMLLIB" ]]; then
  if grep -qF "Codex (report-only, derived on codex 0.166.0): model gpt-6-astra compacts near 244,800" <<<"$out" \
     && grep -qF "Kimi (report-only, derived on kimi 2.2.0): kimi-code/k3 compacts near 891,290" <<<"$out" \
     && ! grep -qF "sk-NEVER-PRINTED" <<<"$out"; then
    pass "status reports Codex and Kimi compaction points with the version each was derived on, and no secret"
  else
    fail "status reports Codex and Kimi compaction points with the version each was derived on, and no secret" "$out"
  fi
  # The clamps: Codex's model_auto_compact_token_limit caps the 90% point, and
  # Kimi's reserved_context_size caps the ratio trigger at window - reserved.
  CLAMP_HOME="$SANDBOX/clamphome"
  mkdir -p "$CLAMP_HOME/.codex" "$CLAMP_HOME/.kimi-code"
  printf 'model = "gpt-6-astra"\nmodel_auto_compact_token_limit = 200000\n' > "$CLAMP_HOME/.codex/config.toml"
  printf 'default_model = "kimi-code/k3"\n\n[loop_control]\nreserved_context_size = 400000\n\n[models."kimi-code/k3"]\nmax_context_size = 1048576\n' \
    > "$CLAMP_HOME/.kimi-code/config.toml"
  out_clamp="$(HOME="$CLAMP_HOME" status v283)"
  if grep -qF "model gpt-6-astra compacts near 200,000 (90% of 272,000; model_auto_compact_token_limit 200000)" <<<"$out_clamp"; then
    pass "status: Codex's model_auto_compact_token_limit (200000) caps the 90% point (244,800)"
  else
    fail "status: Codex's model_auto_compact_token_limit (200000) caps the 90% point (244,800)" "$out_clamp"
  fi
  if grep -qF "kimi-code/k3 compacts near 648,576 (window 1,048,576, ratio 0.85, reserved 400,000)" <<<"$out_clamp"; then
    pass "status: Kimi's reserved_context_size (400000) caps the ratio trigger at window - reserved (648,576)"
  else
    fail "status: Kimi's reserved_context_size (400000) caps the ratio trigger at window - reserved (648,576)" "$out_clamp"
  fi
else
  echo "  - SKIP: $PY has no tomllib (Python < 3.11): Codex/Kimi compaction points and their clamps are not computed;"
  echo "    checking the 'needs Python 3.11+ (tomllib)' line status prints instead"
  if grep -qF "Codex (report-only, derived on codex 0.166.0): config.toml needs Python 3.11+ (tomllib)" <<<"$out" \
     && grep -qF "Kimi (report-only, derived on kimi 2.2.0): config.toml needs Python 3.11+ (tomllib)" <<<"$out" \
     && ! grep -qF "sk-NEVER-PRINTED" <<<"$out"; then
    pass "status without tomllib says Codex and Kimi need Python 3.11+, and prints no secret"
  else
    fail "status without tomllib says Codex and Kimi need Python 3.11+, and prints no secret" "$out"
  fi
fi
# A server-side window cached in .claude.json decides the compaction point, not the key.
CASE="$SANDBOX/cases/server-acwc"
check "status --json: a cached server window is listed under shadowed_by, and no compaction point is claimed" \
  "$(status v283 --json | jq -r '[(.shadowed_by | map(select(contains("cases/server-acwc/.claude.json autoCompactWindowsCache"))) | length), .trigger_1m_model] | map(tostring) | join("|")' 2>/dev/null)" \
  "1|null"
if status v283 | grep -F "shadowed by: a server-side window cached in " | grep -qF "cases/server-acwc/.claude.json autoCompactWindowsCache"; then
  pass "status (text) names the server-side window and the file that caches it"
else
  fail "status (text) names the server-side window and the file that caches it" "$(status v283)"
fi
CASE="$SANDBOX/cases/server-none-null caches"
check "control: status with null caches lists no shadow and computes the point (317000)" \
  "$(status v283 --json | jq -r '[(.shadowed_by | length), .trigger_1m_model] | map(tostring) | join("|")' 2>/dev/null)" "0|317000"
CASE="$SANDBOX/cases/optin"
status v283 >/dev/null
check "status exits 0 and writes nothing: settings.json, sidecar, ~/.codex and ~/.kimi-code unchanged" \
  "$?|$(sha "$CASE/settings.json" "$CASE/$STATE")|$(sha "$HOME/.codex/config.toml" "$HOME/.kimi-code/config.toml")" \
  "0|$before|$vendor_before"

# ─── Suite 8: the policy file gate ───────────────────────────────────

section "--check validates the policy file"

CASE=""
if "$PY" "$CP_SCRIPT" --check --policy "$SHIPPED_POLICY" 2>&1 | grep -qF "context-policy.json: valid"; then
  pass "the shipped configs/context-policy.json passes --check"
else
  fail "the shipped configs/context-policy.json passes --check"
fi
for bad in ".claude_code.$KEY.value = 99999" ".claude_code.$KEY.value = 1000001" \
           ".claude_code.$KEY.min_cc_version = \"2.1\"" ".codex.mode = \"insert-if-absent\"" \
           ".claude_code.$KEY.retire_from_cc_version = \"2.1.100\"" "del(.claude_code.$KEY.measurement)" \
           ".claude_code.$KEY.enabled_by_default = \"yes\"" "del(.claude_code.$KEY.skip_when.env)" \
           ".kimi.verified_kimi_version = \"2.2\""; do
  jq "$bad" "$SHIPPED_POLICY" > "$SANDBOX/bad-policy.json"
  out="$("$PY" "$CP_SCRIPT" --check --policy "$SANDBOX/bad-policy.json" 2>&1)"
  rc=$?
  if [[ "$rc" -eq 1 ]] && grep -qF "context-policy --check: $SANDBOX/bad-policy.json:" <<<"$out"; then
    pass "--check rejects, naming the file: $bad"
  else
    fail "--check rejects, naming the file: $bad" "rc=$rc: $out"
  fi
done

# ─── Suite 8b: the timeout case started before suite 1 ───────────────

section "A claude --version that hangs is abandoned after 10 s"

CASE="$SANDBOX/cases/slow"
wait "$SLOW_PID"
slow_rc=$?
slow_secs=$(( $(date +%s) - SLOW_T0 ))
SLOW_PID=""
# The bound measures the wait, not the host: apply's own work around the 10 s
# timeout took 28 s on a host at load ~80 (2026-11-06), and the old bound of
# 19 s, 1 s under a 20 s answer, failed there twice in a passing run. Content
# alone already tells the two apart (an answer read in time is a readable
# version, and the value is written); the bound stays as a second check.
if [[ "$slow_rc" -eq 0 && "$(val)" == "ABSENT" && "$slow_secs" -lt 80 ]] && logged "Skipped (Claude Code version unreadable)"; then
  pass "a claude that answers only after 90 s: given up at the timeout (${slow_secs}s), nothing written, says why"
else
  fail "a claude that answers only after 90 s: given up at the timeout, nothing written, says why" \
    "rc=$slow_rc value=$(val) after ${slow_secs}s log=$(cat "$CASE/apply.log")"
fi

# ─── Suite 9: through install.sh ─────────────────────────────────────

if [[ -z "$CP_MUTANT" ]]; then
section "install.sh §8d: opt-in, persistence, opt-out, Codex/Kimi untouched, a failing §8d, uninstall.sh, no python3"

# A throwaway copy of the working tree, the way tests/test-install.sh runs it.
SRC="$SANDBOX/repo"
mkdir -p "$SRC"
tar -C "$REPO_ROOT" --exclude='.git' --exclude='orchestrator/.venv' --exclude='node_modules' \
  --exclude='__pycache__' -cf - . | tar -xf - -C "$SRC"
# The copy's policy points managed settings into the sandbox: a real
# /etc/claude-code/managed-settings.json on this machine would otherwise make
# every write case rightly step aside, and the run would prove nothing.
jq --arg m "$SANDBOX/managed-install/managed-settings.json" \
  ".claude_code.$KEY.skip_when.managed_settings = [\$m]" "$SHIPPED_POLICY" > "$SRC/configs/context-policy.json"
if "$PY" "$SRC/configs/scripts/context-policy.py" --check --policy "$SRC/configs/context-policy.json" >/dev/null 2>&1; then
  pass "the sandboxed copy of the policy still passes --check"
else
  fail "the sandboxed copy of the policy still passes --check"
fi
touch "$HOME/.bashrc"
ORIG_PATH="$PATH"
run_install() {  # run_install BIN [args...] — runs install.sh with $SANDBOX/bin/BIN first on PATH
  local bin="$1"
  shift
  PATH="$SANDBOX/bin/$bin:$ORIG_PATH" bash "${INSTALL_SH:-$SRC/install.sh}" "$@" </dev/null > "$SANDBOX/install.log" 2>&1
}
CASE="$HOME/.claude"
rm -f "$SANDBOX/bin/v283/ran"

# Nothing in install.sh writes ~/.codex/config.toml, so it must match the file
# as it was before ANY install. The Kimi bridge (§11c) does edit
# ~/.kimi-code/config.toml on a first install, so its reference is what an
# install.sh with §8d cut out makes of the same pristine file.
codex_pristine="$(sha "$HOME/.codex/config.toml")"
cp "$HOME/.kimi-code/config.toml" "$SANDBOX/kimi-pristine.toml"
awk '/^# ─── 8d\. /{cut=1} /^# ─── 9\. /{cut=0} !cut' "$SRC/install.sh" > "$SRC/install-no8d.sh"
if grep -qF "Context policy (autoCompactWindow)" "$SRC/install-no8d.sh" || ! grep -qF "Configuring shell aliases" "$SRC/install-no8d.sh"; then
  fail "install.sh with §8d cut out: the cut found its two section markers" "$(grep -n '^# ─── \(8d\|9\)\.' "$SRC/install.sh")"
fi
INSTALL_SH="$SRC/install-no8d.sh" run_install v283
kimi_ref="$(sha "$HOME/.kimi-code/config.toml")"
cp "$SANDBOX/kimi-pristine.toml" "$HOME/.kimi-code/config.toml"
vendors_ok() { [[ "$(sha "$HOME/.codex/config.toml")|$(sha "$HOME/.kimi-code/config.toml")" == "$codex_pristine|$kimi_ref" ]]; }

if run_install v283 && grep -qF "Context policy (autoCompactWindow)..." "$SANDBOX/install.log"; then
  pass "plain install.sh exits 0 and runs §8d"
else
  fail "plain install.sh exits 0 and runs §8d" "$(tail -20 "$SANDBOX/install.log")"
fi
if [[ "$(val)" == "ABSENT" && ! -e "$CASE/$STATE" ]] && grep -qF "off by default; opt in: ./install.sh --context-policy" "$SANDBOX/install.log" \
   && cmp -s "$SRC/configs/context-policy.json" "$CASE/context-policy.json" && [[ -f "$CASE/scripts/context-policy.py" ]] \
   && [[ -f "$CASE/scripts/context_policy_selftest.py" ]]; then
  pass "a plain install (the shipped policy is off by default) writes no key and no sidecar, deploys the policy and scripts, names the opt-in"
else
  fail "a plain install (the shipped policy is off by default) writes no key and no sidecar, deploys the policy and scripts, names the opt-in" \
    "value=$(val) log: $(grep -i 'context policy' "$SANDBOX/install.log")"
fi
if vendors_ok; then
  pass "a first install leaves ~/.codex/config.toml as it was and ~/.kimi-code/config.toml as install.sh without §8d leaves it"
else
  fail "a first install leaves ~/.codex/config.toml as it was and ~/.kimi-code/config.toml as install.sh without §8d leaves it" \
    "$(diff "$SANDBOX/kimi-pristine.toml" "$HOME/.kimi-code/config.toml" | head -5)"
fi

run_install v283 --context-policy
check "install.sh --context-policy writes 350000 and persists the opt-in" "$(val)|$(state '.choice')" "350000|in"
before="$(sha "$CASE/$STATE")"
run_install v283
check "a later plain install.sh (fleet-install runs it with no arguments) keeps it, sidecar unchanged" \
  "$(val)|$(sha "$CASE/$STATE")" "350000|$before"
CLADE_CONTEXT_POLICY=off run_install v283
check "CLADE_CONTEXT_POLICY=off removes the Clade-owned value" "$(val)|$(state '.choice')" "ABSENT|out"
run_install v283
check "and the opt-out persists through a plain install" "$(val)|$(state '.choice')" "ABSENT|out"
CLADE_CONTEXT_POLICY=on run_install v283
check "CLADE_CONTEXT_POLICY=on writes it back" "$(val)" "350000"
CLADE_CONTEXT_POLICY=on run_install v283 --no-context-policy
check "a --no-context-policy flag wins over CLADE_CONTEXT_POLICY=on" "$(val)|$(state '.choice')" "ABSENT|out"
run_install gone --context-policy
check "install.sh with an unreadable claude: exits 0, writes nothing and says why" \
  "$?|$(val)|$(grep -c 'Skipped (Claude Code version unreadable)' "$SANDBOX/install.log")" "0|ABSENT|1"
run_install v283 --context-policy
PATH="$SANDBOX/bin/v283" "$PY" "$CASE/scripts/context-policy.py" status >/dev/null 2>&1
if vendors_ok && [[ "$(val)" == "350000" ]]; then
  pass "after every install and a status, ~/.codex and ~/.kimi-code config.toml still match their references (value 350000)"
else
  fail "after every install and a status, ~/.codex and ~/.kimi-code config.toml still match their references" "value=$(val)"
fi

# The default layout end to end: install.sh's ~/.claude, and Claude Code's
# global config at ~/.claude.json beside it, caching a server-side window.
printf '%s\n' "$ACWC" > "$HOME/.claude.json"
run_install v283
if [[ "$(val)" == "ABSENT" ]] \
   && grep -qF "Removed autoCompactWindow (Clade-owned): Anthropic tunes the window server-side" "$SANDBOX/install.log"; then
  pass "a plain install.sh retracts the Clade-owned value while ~/.claude.json caches a server-side window"
else
  fail "a plain install.sh retracts the Clade-owned value while ~/.claude.json caches a server-side window" \
    "value=$(val) $(grep -i 'context policy' "$SANDBOX/install.log")"
fi
printf '{"autoCompactWindowsCache": null}\n' > "$HOME/.claude.json"
run_install v283
check "and writes it back once that cache is null" "$(val)" "350000"
rm -f "$HOME/.claude.json"

# A failing §8d is a WARNING: install.sh runs under `set -e`, and without the
# `|| echo` guard it would stop before the shell aliases (§9) and everything after.
cp "$SRC/configs/context-policy.json" "$SANDBOX/policy-good.json"
jq ".claude_code.$KEY.value = 99999" "$SANDBOX/policy-good.json" > "$SRC/configs/context-policy.json"
run_install v283
warn_line=$(grep -n "WARNING: context policy step failed" "$SANDBOX/install.log" | head -1 | cut -d: -f1)
alias_line=$(grep -n "Configuring shell aliases" "$SANDBOX/install.log" | head -1 | cut -d: -f1)
if [[ -n "$warn_line" && -n "$alias_line" && "$warn_line" -lt "$alias_line" && "$(val)" == "350000" ]] \
   && grep -qF "Installation complete" "$SANDBOX/install.log"; then
  pass "a §8d that fails (here: a policy file --check refuses) prints a WARNING, changes nothing, and install.sh carries on to the end"
else
  fail "a §8d that fails prints a WARNING, changes nothing, and install.sh carries on to the end" \
    "warn@${warn_line:-none} aliases@${alias_line:-none} value=$(val): $(tail -5 "$SANDBOX/install.log")"
fi
cp "$SANDBOX/policy-good.json" "$SRC/configs/context-policy.json"

NO_PY_BIN="$SANDBOX/bin/nopython"
mkdir -p "$NO_PY_BIN"
for shim in python3 python; do
  printf '#!/bin/sh\necho "%s: command not found" >&2\nexit 1\n' "$shim" > "$NO_PY_BIN/$shim"
  chmod +x "$NO_PY_BIN/$shim"
done
cp "$SANDBOX/bin/v283/claude" "$NO_PY_BIN/claude"
if run_install nopython --context-policy && grep -qF "Skipped: context policy (no python3)" "$SANDBOX/install.log"; then
  pass "with no python3 install.sh exits 0 and prints the skip line"
else
  fail "with no python3 install.sh exits 0 and prints the skip line" "$(grep -i 'context policy' "$SANDBOX/install.log")"
fi

# uninstall.sh retracts only a Clade-owned value, before it deletes the script
# that can tell; a value still Clade's (version unreadable) keeps its sidecar.
run_uninstall() { PATH="$SANDBOX/bin/$1:$ORIG_PATH" bash "$SRC/uninstall.sh" </dev/null > "$SANDBOX/uninstall.log" 2>&1; }
gone_files() {
  local f out=""
  for f in "$STATE" context-policy.json scripts/context-policy.py; do [[ -e "$CASE/$f" ]] && out="$out $f"; done
  echo "${out:- none}"
}
run_install v283 --context-policy
run_uninstall v283
check "uninstall.sh removes the Clade-owned value, the sidecar, the policy copy and the script" \
  "$?|$(val)|$(gone_files)" "0|ABSENT| none"
run_install v283 --context-policy
set_value 500000
run_uninstall v283
check "uninstall.sh leaves a value the user set" "$?|$(val)|$(gone_files)" "0|500000| none"
printf '{}\n' > "$CASE/settings.json"
run_install v283 --context-policy
run_uninstall gone
if [[ "$(val)" == "350000" && -e "$CASE/$STATE" ]] && grep -qF "kept $STATE" "$SANDBOX/uninstall.log"; then
  pass "uninstall.sh with an unreadable claude keeps the value and the sidecar, and says how to remove it"
else
  fail "uninstall.sh with an unreadable claude keeps the value and the sidecar, and says how to remove it" \
    "value=$(val) $(grep -i 'context' "$SANDBOX/uninstall.log")"
fi
fi

# ─── Suite 10: every guard is observed ───────────────────────────────
#
# Remove one guard from a COPY of the script, re-run this suite against it with
# CP_MUTANT=1 (stop at the first failure, no install.sh runs), and require red.
# The no-op control must stay green, or the suite is red for some other reason.

if [[ -z "$CP_MUTANT" && -f "$CP_SCRIPT" ]]; then
section "Guard mutations: removing any guard turns this suite red"

MUT_DIR="$SANDBOX/mutants"
mkdir -p "$MUT_DIR"
NMUT=0
MUT_NAMES=(); MUT_EXPECT=()
mutation() {  # mutation green|red NAME ANCHOR REPLACEMENT
  local out="$MUT_DIR/m$NMUT.py"
  if ! "$PY" - "$CP_SCRIPT" "$out" "$3" "$4" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
if src.count(sys.argv[3]) != 1:
    sys.exit(3)
open(sys.argv[2], "w", encoding="utf-8").write(src.replace(sys.argv[3], sys.argv[4]))
PY
  then
    fail "mutation '$2': its anchor no longer matches the script exactly once"
    return 0
  fi
  MUT_NAMES[NMUT]="$2"; MUT_EXPECT[NMUT]="$1"
  NMUT=$((NMUT + 1))
}

mutation green "no-op control (a comment reworded)" \
  '# 1. Re-derive ownership from what the file holds NOW' '# 1. Re-derive the ownership from what the file holds NOW'
mutation red "the version floor" \
  '    too_old = version < lo' '    too_old = False'
mutation red "ownership by equality (a user edit transfers ownership)" \
  '    elif st["wrote"] is not None and not same_int(cur, st["wrote"]):' '    elif False:'
mutation red "exact int equality" \
  '    return is_int(cur) and is_int(wrote) and cur == wrote' '    return cur == wrote'
mutation red "user_removed (a deleted key is never re-added)" \
  '    if why or st["user_removed"]:' '    if why:'
mutation red "opt-in clears user_removed" \
  'st["choice"], st["user_removed"] = "in", False' 'st["choice"] = "in"'
mutation red "user_owned: deleting a value the user owns is recorded" \
  '    if (st["wrote"] is not None or st["user_owned"]) and cur is None:' '    if st["wrote"] is not None and cur is None:'
mutation red "user_owned: a user edit of Clade's value marks it the user's" \
  '        st["wrote"], st["user_owned"] = None, True' '        st["wrote"] = None'
mutation red "user_owned: a value there before opt-in is the user's" \
  '    st["user_owned"] = st["user_owned"] or (enabled and cur is not None and not owned)' '    pass'
mutation red "skip_when: settings env" \
  'found += [f"{name} env.{k}" for k in skip["env"] if k in senv]' 'found += []'
mutation red "skip_when: process env" \
  'found += [f"process env {k}" for k in skip["env"] if k in env]' 'found += []'
mutation red "skip_when: a setting that is false" \
  'found += [f"{name} {k}: false" for k in skip["settings_false"] if src.get(k) is False]' 'found += []'
mutation red "skip_when: modelSettings.*.autoCompactWindow" \
  '.items() if mkey in obj(v)]' '.items() if False]'
mutation red "skip_when: managed settings are read at all" \
  '            out.append((p, data if isinstance(data, dict) else None))' '            pass'
mutation red "skip_when: managed settings that set autoCompactWindow" \
  '        if name != "settings.json" and KEY in src:' '        if False:'
mutation red "fail closed: an unparseable managed file counts as setting everything" \
  'isinstance(data, dict) else None' 'isinstance(data, dict) else {}'
mutation red "fail closed: an unreadable managed file is a reason to step aside" \
  'found.append(f"{name} (unreadable, so it may set anything)")' 'pass'
mutation red "managed-settings.d drop-ins are read" \
  'files += [p, *(os.path.join(drop, n) for n in names)]' 'files += [p]'
mutation red "managed-settings.d skips dot-files and non-.json files" \
  'if n.endswith(".json") and not n.startswith(".")' 'if True'
mutation red "the retire comparison (at, not only above)" \
  'retired = retire is not None and version >= retire' 'retired = retire is not None and version > retire'
mutation red "the retract step" \
  '    if owned and why:' '    if False:'
mutation red "the update of an owned value" \
  '    if cur is None or (owned and cur != value):' '    if cur is None:'
mutation red "never running claude when there is nothing to do" \
  '    if not enabled and not owned:' '    if False:'
mutation red "the version regex (only a Claude Code line)" \
  'VERSION_LINE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\b.*\(Claude Code\)")' 'VERSION_LINE = re.compile(r"(\d+)\.(\d+)\.(\d+)")'
mutation red "scanning every line of claude --version" \
  'for line in proc.stdout.splitlines() if' 'for line in proc.stdout.splitlines()[:1] if'
mutation red "trusting --version output only on exit 0" \
  'if proc.returncode == 0 else []:' 'if True else []:'
mutation red "the realpath fallback" \
  'found = VERSION_PATH.search(os.path.realpath(exe))' 'found = VERSION_PATH.search(exe)'
mutation red "finding claude outside PATH (~/.local/bin, ~/.claude/local)" \
  '(shutil.which("claude"), Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude")' '(shutil.which("claude"),)'
mutation red "finding claude in ~/.claude/local" \
  ', Path.home() / ".claude/local/claude")' ')'
mutation red "closing stdin for claude --version" \
  'stdin=subprocess.DEVNULL)' ')'
mutation red "the 10 s timeout on claude --version" \
  'text=True, timeout=10,' 'text=True,'
mutation red "re-applying after a concurrent write" \
  '        if mtime_ns(settings_path) != stamp:' '        if False:'
mutation red "writing through the symlink to the real file" \
  '    real = Path(os.path.realpath(path))' '    real = Path(path)'
mutation red "keeping the file mode" \
  '        os.chmod(tmp, mode)' '        pass'
mutation red "a new settings.json is private (600)" \
  'else 0o600' 'else 0o666'
mutation red "rejecting a settings.json that is not an object" \
  'raise ValueError("not a JSON object")' 'data = {}'
mutation red "writing nothing when nothing changed" \
  '        if new == settings:' '        if False:'
mutation red "not rewriting an unchanged Clade-owned value" \
  '        if new == settings:' '        if new == settings and not state["wrote"]:'
mutation red "not rewriting an unchanged sidecar" \
  'if text != previous and (' 'if ('
mutation red "no sidecar for a default install" \
  '(previous is not None or new_state != FRESH)' '(True)'
mutation red "a sidecar with another schema owns nothing" \
  'valid = raw["schema"] == STATE_SCHEMA and st["choice"] in (None, "in", "out")' 'valid = True'
mutation red "a sidecar whose wrote is not an int owns nothing" \
  'valid = valid and (st["wrote"] is None or is_int(st["wrote"]))' 'valid = valid'
mutation red "a sidecar whose flags are not booleans owns nothing" \
  'valid = valid and all(isinstance(st[k], bool) for k in FLAGS)' 'valid = valid'
mutation red "--check: enabled_by_default is a bool" \
  '    if not isinstance(e.get("enabled_by_default"), bool):' '    if False:'
mutation red "--check: the skip_when shape" \
  '    if not (isinstance(skip.get("model_settings_key"), str)' '    if False and (isinstance(skip.get("model_settings_key"), str)'
mutation red "--check: Codex/Kimi versions are X.Y.Z" \
  '        elif parse_version(block.get(vkey)) is None:' '        elif False:'
mutation red "status: a value Claude Code drops is not a compaction point" \
  'window = cur if is_int(cur) and VALUE_MIN <= cur <= VALUE_MAX else VALUE_MAX' 'window = cur if is_int(cur) else VALUE_MAX'
mutation red "status: no compaction point under a shadow" \
  'trigger = None if shadow else window - OUTPUT_RESERVE - SUMMARY_BUFFER' 'trigger = window - OUTPUT_RESERVE - SUMMARY_BUFFER'
mutation red "status: the user settings file is not a project file" \
  'if p.is_file() and os.path.realpath(p) != user_file' 'if p.is_file()'
mutation red "uninstall keeps the sidecar of a value it could not retract" \
  '    if rc == 0 and wrote is None:' '    if rc == 0:'
mutation red "uninstall does nothing where Clade never applied" \
  '    if not state_path.exists():' '    if False:'
mutation red "a managed-settings.d that cannot be listed shadows" \
  'files += [p, drop]' 'files.append(p)'
mutation red "retirement also blocks a fresh opt-in, not only an owned value" \
  'f"retired from Claude Code {fmt(retire)}" if retired' 'f"retired from Claude Code {fmt(retire)}" if retired and owned'
mutation red "server tuning: autoCompactWindowsCache is a signal" \
  '        if obj(cfg.get("autoCompactWindowsCache")):' '        if False:'
mutation red "server tuning: only a non-empty cache counts, not a null one" \
  '        if obj(cfg.get("autoCompactWindowsCache")):' '        if "autoCompactWindowsCache" in cfg:'
mutation red "server tuning: rowan_thicket in any clientDataCacheSlots slot" \
  '        if any(obj(obj(data).get("rowan_thicket")) for data in slots):' '        if False:'
mutation red "server tuning: rowan_thicket in the legacy clientDataCache" \
  '        if obj(obj(cfg.get("clientDataCache")).get("rowan_thicket")):' '        if False:'
mutation red "server tuning: the .claude.json beside a dir named .claude" \
  '        candidates.append(claude_dir.parent / ".claude.json")' '        pass'
mutation red "server tuning: only a dir named .claude reads its parent's file" \
  '    if claude_dir.name == ".claude":' '    if True:'
mutation red "server tuning: \$CLAUDE_CONFIG_DIR/.claude.json" \
  '        dirs.append(Path(os.environ["CLAUDE_CONFIG_DIR"]))' '        pass'
mutation red "server tuning: the legacy .config.json" \
  'for name in (".claude.json", ".config.json")]' 'for name in (".claude.json",)]'
mutation red "server tuning: an invalid .claude.json is no signal" \
  '        except (OSError, ValueError):  # absent, unreadable' '        except OSError:  # absent, unreadable'
mutation red "server tuning is a reason to retract and to write nothing" \
  "else f\"Anthropic tunes the window server-side ({', '.join(server)})\" if server else \"\")" \
  "else f\"Anthropic tunes the window server-side ({', '.join(server)})\" if False else \"\")"
mutation red "apply reads server tuning (the call site)" \
  '                                       server_tuning(claude_dir))' '                                       [])'
mutation red "status lists server tuning as a shadow" \
  '               for s in server_tuning(claude_dir)]' '               for s in []]'
if [[ -n "$HAVE_TOMLLIB" ]]; then  # without tomllib status computes neither line, so nothing could see these
  mutation red "status: Codex's model_auto_compact_token_limit caps the point" \
    '    point = min(point, limit) if is_int(limit) else point' '    point = point'
  mutation red "status: Kimi's reserved_context_size caps the trigger" \
    '    trigger = min(round(size * ratio), size - reserved if 0 < reserved < size else size)' \
    '    trigger = round(size * ratio)'
fi

# Bounded parallelism; bash 3.2 has no `wait -n`, so wait oldest-first.
CP_JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
[[ "$CP_JOBS" =~ ^[0-9]+$ && "$CP_JOBS" -ge 1 ]] || CP_JOBS=2
[[ "$CP_JOBS" -gt 12 ]] && CP_JOBS=12
CP_SELF="$REPO_ROOT/tests/test-context-policy-install.sh"
MUT_PIDS=(); MUT_RCS=()
next=0; i=0
while [[ "$i" -lt "$NMUT" ]]; do
  if [[ $((i - next)) -ge "$CP_JOBS" ]]; then
    wait "${MUT_PIDS[$next]}"; MUT_RCS[next]=$?
    next=$((next + 1))
  fi
  CP_MUTANT=1 CP_SCRIPT="$MUT_DIR/m$i.py" bash "$CP_SELF" > "$MUT_DIR/m$i.log" 2>&1 &
  MUT_PIDS[i]=$!
  i=$((i + 1))
done
while [[ "$next" -lt "$NMUT" ]]; do
  wait "${MUT_PIDS[$next]}"; MUT_RCS[next]=$?
  next=$((next + 1))
done

i=0
while [[ "$i" -lt "$NMUT" ]]; do
  rc="${MUT_RCS[$i]}"
  first=$(grep -m1 '✗' "$MUT_DIR/m$i.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
  if [[ "${MUT_EXPECT[$i]}" == "green" ]]; then
    if [[ "$rc" -eq 0 ]]; then pass "control: ${MUT_NAMES[$i]} leaves the suite green"
    else fail "control: ${MUT_NAMES[$i]} leaves the suite green" "rc=$rc, first failure: $first"; fi
  elif [[ "$rc" -ne 0 ]]; then
    pass "without ${MUT_NAMES[$i]}: red — ${first:-rc=$rc}"
  else
    fail "without ${MUT_NAMES[$i]}: the suite stayed GREEN" "this guard is claimed and not checked"
  fi
  i=$((i + 1))
done
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
  exit 0
else
  echo -e "  ${RED}FAILED${NC} ($TESTS_FAILED of $TESTS_RUN)"
  exit 1
fi
