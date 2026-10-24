#!/usr/bin/env bash
# workflow-preflight.sh — check a Workflow launch before its agents run
#
# Triggered: PreToolUse (matcher: Workflow)
# Purpose:   hand the launch to configs/scripts/check-workflow-script.py --hook,
#            which reads the PreToolUse JSON on stdin and answers in Claude
#            Code's schema:
#   deny  {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#           "permissionDecision":"deny","permissionDecisionReason":"..."}}
#         — args carry a placeholder ("__FILL__", {"__see": …}, "(see …)")
#   warn  {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#           "additionalContext":"..."}}  (no permissionDecision: the launch
#         proceeds) — a stringified prior result cut silently inside a prompt,
#         args passed as a JSON-encoded string, or a fresh quota reading at
#         >= 90% (7-day) / >= 85% (5-hour)
#   allow exit 0 with no output
#
# Why a hook and not only guidance: 10 of 324 launches on the author's
# machine carried a placeholder where the data should be, repeated in 5
# sessions — one session made the same mistake three times after naming it —
# and one such run went to "completed" on the placeholder with an empty
# result. The rule was known; it did not hold. Measured over every Workflow
# launch in that machine's transcripts (369): the deny fires on 9 of those 10
# runs, on one more placeholder launch made after the audit, and on none of
# the rest. The tenth was a real empty list, which only an expected count in
# args can catch.
#
# Fail-open by design, every way it can fail: no python3, no checker, a
# checker that crashes or hangs — the launch goes ahead unchecked rather than
# being blocked by a broken preflight. The checker bounds its script and quota
# stages with an in-process deadline (10 s, CLADE_PREFLIGHT_DEADLINE) that is
# armed only after the args check, so it can cut those stages short but never
# cost a deny already found; `timeout`, where it exists, bounds the
# interpreter; settings-hooks.json bounds the whole hook at 15 s.
#
# CLADE_PREFLIGHT_SCRIPT overrides the checker path (tests point it at a no-op
# to show the suite goes red without the real one); CLADE_PREFLIGHT_TIMEOUT
# overrides the interpreter bound. tests/test-workflow-preflight.sh removes
# each guard below in turn and requires its wrapper cases to go red.

set -u

# Every early exit drains stdin first, so Claude Code never writes the hook
# input into a closed pipe.
_wp_skip() { cat >/dev/null 2>&1; exit 0; }

command -v python3 >/dev/null 2>&1 || _wp_skip

CHECKER="${CLADE_PREFLIGHT_SCRIPT:-}"
if [[ -z "$CHECKER" ]]; then
  # Sibling copy first: in-repo configs/hooks/../scripts and installed
  # ~/.claude/hooks/../scripts resolve the same way.
  _wp_sib="$(cd "$(dirname "$0")/../scripts" 2>/dev/null && pwd)"
  if [[ -n "$_wp_sib" && -f "$_wp_sib/check-workflow-script.py" ]]; then
    CHECKER="$_wp_sib/check-workflow-script.py"
  elif [[ -f "$HOME/.claude/scripts/check-workflow-script.py" ]]; then
    CHECKER="$HOME/.claude/scripts/check-workflow-script.py"
  fi
fi
[[ -n "$CHECKER" && -f "$CHECKER" ]] || _wp_skip

# Capability detection, not uname: GNU coreutils ships `timeout`, Homebrew's
# coreutils on macOS ships `gtimeout`, a stock Mac has neither.
# CLADE_PREFLIGHT_TIMEOUT (seconds, default 12) exists so the suite can show
# a hanging checker is cut off without spending 12 s doing it.
_WP_SECS="${CLADE_PREFLIGHT_TIMEOUT:-12}"
[[ "$_WP_SECS" =~ ^[0-9]+$ ]] || _WP_SECS=12
_WP_TIMEOUT=""
if command -v timeout >/dev/null 2>&1; then
  _WP_TIMEOUT="timeout $_WP_SECS"
elif command -v gtimeout >/dev/null 2>&1; then
  _WP_TIMEOUT="gtimeout $_WP_SECS"
fi

# stdout is the hook's answer; stderr is dropped so a traceback can never
# reach the transcript as noise. The exit status is always 0.
# shellcheck disable=SC2086  # _WP_TIMEOUT is a command prefix, split on purpose
$_WP_TIMEOUT python3 "$CHECKER" --hook 2>/dev/null
exit 0
