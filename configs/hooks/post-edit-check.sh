#!/usr/bin/env bash
# post-edit-check.sh — Auto type-check / lint after file edits.
# Triggered by PostToolUse on Edit|Write, wired asyncRewake (which implies async).
#
# Supported: TypeScript, Python, Rust, Go, Swift, Kotlin/Java, LaTeX
#
# Delivery contract (asyncRewake, Claude Code >=2.1): the check can take up to
# 180s so it must not block the turn, but a background hook has no channel back
# into the turn either — its stdout is discarded, which is why the old
# {"systemMessage": ...} output never reached anyone. asyncRewake bridges both:
# the hook runs in the background and, ONLY on exit code 2, Claude is woken with
# the hook's stderr as a system reminder.
#
# So: findings → stderr + exit 2. Clean → no output, exit 0 (never wake Claude).

LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/typecheck.sh"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# Both findings accumulate into one message: asyncRewake fires a single wake per
# run, so emitting them separately would silently drop whichever came second.
FINDINGS=""

add_finding() {
  FINDINGS="${FINDINGS:+$FINDINGS

}$1"
}

# ─── Type check ───
RESULT=$(run_typecheck_for_file "$FILE_PATH" 2>&1)
EXIT_CODE=$?

if [[ $EXIT_CODE -ne 0 ]] && [[ -n "$RESULT" ]]; then
  add_finding "Type-check errors after editing $FILE_PATH:
$RESULT"
fi

# ─── Commit reminder ───
UNCOMMITTED_COUNT=$(git diff --name-only HEAD 2>/dev/null | wc -l | xargs)
# Outside a git repo `git diff` prints nothing, so wc yields 0 — but default
# anyway: an empty operand makes the [[ -ge ]] below a syntax error, not a skip.
UNCOMMITTED_COUNT=${UNCOMMITTED_COUNT:-0}
# Threshold 2 was survivable when this finding went out as a systemMessage that
# nobody received. On the asyncRewake path every finding INTERRUPTS the turn, and
# ordinary work sits above 2 uncommitted files almost permanently — that would
# wake Claude on literally every edit and train it to ignore the channel. The
# nudge only earns an interruption once the working tree is genuinely sprawling;
# routine "commit small and often" pressure belongs to stop-check.sh, which
# already gates on uncommitted work at Stop with session-scoped attribution.
COMMIT_REMINDER_THRESHOLD=${COMMIT_REMINDER_THRESHOLD:-15}

if [[ "$UNCOMMITTED_COUNT" -ge "$COMMIT_REMINDER_THRESHOLD" ]] && [[ "$UNCOMMITTED_COUNT" -gt 0 ]]; then
  add_finding "⚠ $UNCOMMITTED_COUNT files edited without commit — run: committer \"type: desc\" file1 file2"
fi

# Clean check: stay silent and exit 0 so asyncRewake does not wake Claude.
[[ -z "$FINDINGS" ]] && exit 0

printf '%s\n' "$FINDINGS" >&2
exit 2
