#!/usr/bin/env bash
# test-radar-cron.sh — the weekly radar wrapper keeps its edits to itself.
#
# Until 2026-10-20 the unattended sweep ran from cron's cwd ($HOME) and edited
# the kit checkout in place: the 10-12 run's edits sat on fix/warm-pace for four
# days, the 10-19 run's on main, and neither was verified or committed by the
# run that wrote them. radar-cron.sh now gives the agent its own worktree on a
# radar/<date> branch, verifies what it changed (bash -n; the suites that name a
# changed file, in a bubblewrap sandbox), commits to that local branch, removes
# the worktree, and never pushes. After the sweep it runs keep-sessions.py
# --apply, whose failure or hang is logged and never fails the run (§7).
#
# A stub stands in for claude: it records its cwd and edits files in it, the
# way the agent does. Nothing here reaches the network or a model.
#
# Usage: bash tests/test-radar-cron.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON="$REPO_ROOT/configs/scripts/radar-cron.sh"
SESSION_HOOK="$REPO_ROOT/configs/hooks/session-context.sh"

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0; TESTS_SKIPPED=0
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }
pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} %s\n" "$1"; }
fail() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1)); printf "  ${RED}✗${NC} %s\n      %s\n" "$1" "${2:-}"; }
skip() { TESTS_SKIPPED=$((TESTS_SKIPPED + 1)); printf "  ${YELLOW}-${NC} SKIP %s (%s)\n" "$1" "$2"; }
check() { if eval "$2"; then pass "$1"; else fail "$1" "${3:-condition: $2}"; fi; }

T=$(mktemp -d)
trap '[[ -n "${KEEP_T:-}" ]] || rm -rf "$T"' EXIT
export HOME="$T/home"
mkdir -p "$HOME/.claude/research"

# ─── Fixture: a kit repo with an origin, a live checkout someone is using ──
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/kit" 2>/dev/null
git -C "$T/kit" config user.email t@example.com
git -C "$T/kit" config user.name t
git -C "$T/kit" checkout -q -b main
mkdir -p "$T/kit/configs/hooks" "$T/kit/tests"
printf '#!/usr/bin/env bash\necho foo\n' > "$T/kit/configs/hooks/foo.sh"
# A suite that names foo.sh. It also tries to write OUTSIDE the worktree; in
# the sandbox that write lands in a private /tmp and the real file never appears.
cat > "$T/kit/tests/test-foo.sh" <<EOF
#!/usr/bin/env bash
bash -n configs/hooks/foo.sh || exit 1
echo escaped > "$T/escape-marker" 2>/dev/null
exit 0
EOF
printf '.radar-staged/\n' > "$T/kit/.gitignore"
git -C "$T/kit" add -A && git -C "$T/kit" commit -qm base && git -C "$T/kit" push -q origin main
# Someone is mid-task in the live checkout: a feature branch, an uncommitted edit.
git -C "$T/kit" checkout -q -b someone/working
echo "# someone's uncommitted line" >> "$T/kit/configs/hooks/foo.sh"
printf '%s\n' "$T/kit" > "$HOME/.claude/.kit-source-dir"

# ─── Stub agent ──────────────────────────────────────────────────────
cat > "$T/claude" <<'EOF'
#!/usr/bin/env bash
pwd -P >> "$STUB_LOG"
d="${CLADE_RADAR_DATE}"
stage=".radar-staged"; [[ -d "$stage" ]] || stage="."
# What Lane D handed over: the prompt, and the report as it stood when the agent ran.
printf '%s\n' "$1" > "$STUB_LOG.prompt"
rm -f "$STUB_LOG.friction"
[[ -s "$stage/friction-$d.txt" ]] && cp "$stage/friction-$d.txt" "$STUB_LOG.friction"
printf '# digest %s\n' "$d" > "$stage/radar-$d.md"
printf 'new-concept (%s)\n' "$d" > "$stage/known-concepts-append-$d.md"
case "${STUB_MODE:-edit}" in
  edit)  printf '#!/usr/bin/env bash\necho foo-improved\n' > configs/hooks/foo.sh
         printf 'note\n' > configs/hooks/new-note.md ;;
  badsh) printf '#!/usr/bin/env bash\nif then fi (\n' > configs/hooks/foo.sh ;;
  none)  : ;;
esac
exit 0
EOF
chmod +x "$T/claude"

run_cron() {  # run_cron <date> <mode>
  # An empty CLAUDE_CONFIG_DIR means ~/.claude: Lane D's scan must not reach the
  # transcripts of the session running this suite.
  CLAUDE_CONFIG_DIR= CLADE_CLAUDE_BIN="$T/claude" CLADE_RADAR_DATE="$1" STUB_MODE="$2" STUB_LOG="$T/stub.log" \
    CLADE_RADAR_LOCK="$T/radar.lock" CLADE_RADAR_WORKTREES="$T/wts" CLADE_RUNTIME_DIR="${CLADE_RUNTIME_DIR:-$T/runtime}" \
    bash "$CRON" >/dev/null 2>&1
}

# ─── 1. edits land on the run's own branch, not in the live checkout ──
section "the sweep edits its own worktree, never the open checkout"
: > "$T/stub.log"
run_cron 2026-01-05 edit
check "the agent ran inside the run's worktree" \
  '[[ "$(tail -n1 "$T/stub.log")" == "$(cd "$T" && pwd -P)/wts/radar-2026-01-05" ]]' "cwd was: $(tail -n1 "$T/stub.log")"
check "branch radar/2026-01-05 exists" \
  'git -C "$T/kit" rev-parse -q --verify refs/heads/radar/2026-01-05 >/dev/null'
check "it carries exactly one commit on top of origin/main" \
  '[[ "$(git -C "$T/kit" rev-list --count origin/main..radar/2026-01-05)" == 1 ]]'
check "the commit holds the agent's edits" \
  'git -C "$T/kit" show --name-only --format= radar/2026-01-05 | grep -qx configs/hooks/new-note.md'
check "the live checkout is still on someone's branch" \
  '[[ "$(git -C "$T/kit" rev-parse --abbrev-ref HEAD)" == someone/working ]]'
check "and still holds someone's uncommitted line, untouched by the agent" \
  'grep -q "someone.s uncommitted line" "$T/kit/configs/hooks/foo.sh" && ! grep -q foo-improved "$T/kit/configs/hooks/foo.sh"'
check "the staged digest was folded into the research dir" \
  '[[ -f "$HOME/.claude/research/radar-2026-01-05.md" ]]'
check "the staged ledger lines were appended" \
  'grep -q "new-concept (2026-01-05)" "$HOME/.claude/research/known-concepts.md"'
check "the worktree is removed after committing" \
  '[[ ! -d "$T/wts/radar-2026-01-05" ]] && ! git -C "$T/kit" worktree list | grep -q radar-2026-01-05'
check "nothing was pushed" \
  '! git -C "$T/origin.git" rev-parse -q --verify refs/heads/radar/2026-01-05 >/dev/null'

MSG=$(git -C "$T/kit" log -1 --format=%B radar/2026-01-05)
check "the commit says it is unreviewed" '[[ "$MSG" == *UNREVIEWED* ]]'
check "bash -n ran on the changed shell file" '[[ "$MSG" == *"bash -n configs/hooks/foo.sh: ok"* ]]'

# ─── 2. the suites run sandboxed, or the record says they did not ─────
section "suites that name a changed file run in a sandbox"
if command -v bwrap >/dev/null 2>&1 && bwrap --ro-bind / / --unshare-net true >/dev/null 2>&1; then
  check "the suite naming foo.sh ran, with no network" \
    '[[ "$MSG" == *"tests/test-foo.sh (sandbox, no network): pass"* ]]'
  check "a suite's write outside the worktree never reached the host" \
    '[[ ! -e "$T/escape-marker" ]]' "the sandboxed suite wrote $T/escape-marker on the host"
else
  check "without bwrap the record says the suites were NOT run" \
    '[[ "$MSG" == *"suites NOT run"* ]]'
  skip "sandbox write isolation" "no usable bwrap on this host"
fi

# ─── 3. a run with nothing to commit leaves nothing behind ────────────
section "no code edits, no branch"
run_cron 2026-01-05 none
check "a second run that day got its own branch name, then dropped it" \
  '! git -C "$T/kit" rev-parse -q --verify refs/heads/radar/2026-01-05-2 >/dev/null'
check "its worktree is gone" '[[ ! -d "$T/wts/radar-2026-01-05-2" ]]'
check "the first run's branch is untouched" \
  'git -C "$T/kit" rev-parse -q --verify refs/heads/radar/2026-01-05 >/dev/null'
check "the log says why nothing was committed" \
  'grep -q "NO CODE EDITS" "$HOME/.claude/research/radar-cron.log"'

# ─── 4. a broken edit is committed with the failure on record ─────────
section "a parse failure is recorded, not hidden"
run_cron 2026-01-12 badsh
MSG2=$(git -C "$T/kit" log -1 --format=%B radar/2026-01-12 2>/dev/null)
check "bash -n FAIL is in the commit message" '[[ "$MSG2" == *"bash -n configs/hooks/foo.sh: FAIL"* ]]'
check "and counted in the summary line" '[[ "$MSG2" == *"1 parse failure(s)"* ]]'

# ─── 5. no kit repository: a digest-only run that can edit nothing ────
section "without a kit repository the sweep edits nothing"
mv "$HOME/.claude/.kit-source-dir" "$T/kit-source-dir.bak"
: > "$T/stub.log"
run_cron 2026-01-19 edit
check "the agent ran in a scratch directory, not a checkout" \
  '[[ "$(tail -n1 "$T/stub.log")" != "$(cd "$T/kit" && pwd -P)"* ]]'
check "its digest was still folded" '[[ -f "$HOME/.claude/research/radar-2026-01-19.md" ]]'
mv "$T/kit-source-dir.bak" "$HOME/.claude/.kit-source-dir"

# ─── 6. sessions in the kit see the branches waiting for review ───────
section "session-context lists radar branches in the kit repository"
SC_OUT=$(cd "$T/kit" && printf '{"session_id":"t"}' | CLAUDE_PROJECT_DIR="$T/kit" bash "$SESSION_HOOK" 2>/dev/null)
check "a session in the kit names radar/2026-01-05" '[[ "$SC_OUT" == *"radar/2026-01-05"* ]]' "output: ${SC_OUT:0:300}"
RADAR_SUBJECT=$(git -C "$T/kit" log -1 --format=%s radar/2026-01-05)
RADAR_ORIGINAL_LINE="  radar/2026-01-05 — $RADAR_SUBJECT"
SC_NO_STATE=$(cd "$T/kit" && printf '{"session_id":"t"}' | CLADE_RADAR_BRANCH_STATE="$T/no-such-state" CLAUDE_PROJECT_DIR="$T/kit" bash "$SESSION_HOOK" 2>/dev/null)
SC_NO_STATE_CONTEXT=$(jq -r '.hookSpecificOutput.additionalContext // empty' <<< "$SC_NO_STATE")
SC_NO_STATE_LINE=$(printf '%b\n' "$SC_NO_STATE_CONTEXT" | grep -F "  radar/2026-01-05 ")
check "without a state file the original branch-and-subject line is exact" \
  '[[ "$SC_NO_STATE_LINE" == "$RADAR_ORIGINAL_LINE" ]]' "got: $SC_NO_STATE_LINE; want: $RADAR_ORIGINAL_LINE"
mkdir -p "$T/other" && git -C "$T/other" init -q
SC_OTHER=$(cd "$T/other" && printf '{"session_id":"t"}' | CLAUDE_PROJECT_DIR="$T/other" bash "$SESSION_HOOK" 2>/dev/null)
check "a session in another repository does not" '[[ "$SC_OTHER" != *"radar/2026-01-05"* ]]'

# ─── 7. Lane D: the wrapper runs what the agent cannot ───────────────
section "Lane D's verdict ranking is made before the sweep and named in the prompt"
check "with no transcripts, the prompt says Lane D was NOT MEASURED" \
  'grep -q "Lane D was NOT MEASURED" "$T/stub.log.prompt"' "prompt: $(head -c 400 "$T/stub.log.prompt" 2>/dev/null)"
NOW_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$HOME/.claude/projects/-p"
cat > "$HOME/.claude/projects/-p/s1.jsonl" <<EOF
{"type":"assistant","timestamp":"$NOW_TS","message":{"content":[{"type":"tool_use","id":"toolu_1","name":"Bash","input":{"command":"sleep 60"}}]}}
{"type":"user","timestamp":"$NOW_TS","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_1","content":"<tool_use_error>Blocked: sleep 60","is_error":true}]},"toolUseResult":"Error: Blocked"}
EOF
run_cron 2026-01-26 none
check "the report was in the agent's staging dir when it ran" \
  'grep -q "is_error · Bash:sleep" "$T/stub.log.friction"' "report: $(head -c 400 "$T/stub.log.friction" 2>/dev/null)"
check "and the prompt names it, with no NOT MEASURED" \
  'grep -q "friction-2026-01-26.txt" "$T/stub.log.prompt" && ! grep -q "NOT MEASURED" "$T/stub.log.prompt"'
# Monday 08:07 is hours into the ISO week: the current week alone would be a
# near-empty held-out column, which SKILL.md tells the grader reads as a burst.
check "the report holds out two ISO weeks, not the hours of the current one" \
  'grep -Eq "held out: [0-9]{4}-W[0-9]{2}, [0-9]{4}-W[0-9]{2} \(" "$T/stub.log.friction"' \
  "report: $(grep -m1 "held out" "$T/stub.log.friction" 2>/dev/null)"

# ─── 8. the weekly run keeps corrected sessions, and never fails for it ──
# keep-sessions.py runs LAST, after the sweep, with --apply. A failure or a hang
# is logged and changes neither the sweep nor the wrapper's exit status.
section "keep-sessions runs after the sweep and cannot fail it"
KS_SID="0f0f0f0f-1111-2222-3333-444444444444"
KS_TRANSCRIPT="$HOME/.claude/projects/-kit/$KS_SID.jsonl"
mkdir -p "$(dirname "$KS_TRANSCRIPT")" "$HOME/.claude/corrections"
printf '{"type":"user","sessionId":"%s","message":{"content":"no, use the other one"}}\n' "$KS_SID" > "$KS_TRANSCRIPT"
printf '{"timestamp":"2026-01-26T08:07:00Z","prompt":"no","project":"%s","type":"explicit","session_id":"%s","transcript_path":"%s"}\n' \
  "$T/kit" "$KS_SID" "$KS_TRANSCRIPT" > "$HOME/.claude/corrections/history.jsonl"
KS_KEPT="$HOME/.local/share/clade/sessions/$KS_SID"
LOG_FILE="$HOME/.claude/research/radar-cron.log"
run_cron 2026-01-26 none; KS_RC=$?
check "the corrected session was kept" '[[ -f "$KS_KEPT/transcript.jsonl.gz" && -f "$KS_KEPT/manifest.json" ]]'
check "the log carries its one-line summary" 'grep -q "KEEP-SESSIONS keep-sessions: kept 1 session (1 new" "$LOG_FILE"' \
  "log tail: $(tail -n 3 "$LOG_FILE")"
check "it ran after the sweep finished" \
  '[[ $(grep -n "KEEP-SESSIONS keep-sessions: kept" "$LOG_FILE" | tail -n1 | cut -d: -f1) -gt $(grep -n "] DONE$" "$LOG_FILE" | tail -n1 | cut -d: -f1) ]]'
check "the wrapper exits 0" '[[ $KS_RC -eq 0 ]]' "exit $KS_RC"

printf 'import sys\nprint("boom: could not keep")\nsys.exit(3)\n' > "$T/failing-keep.py"
: > "$T/stub.log"
CLADE_KEEP_SESSIONS="$T/failing-keep.py" run_cron 2026-02-02 none; KS_RC=$?
check "a failing keep-sessions is logged with its exit code" 'grep -q "KEEP-SESSIONS FAILED rc=3 (the sweep is unaffected): boom" "$LOG_FILE"'
check "the sweep still ran" '[[ -s "$T/stub.log" ]] && [[ -f "$HOME/.claude/research/radar-2026-02-02.md" ]]'
check "and the wrapper still exits 0" '[[ $KS_RC -eq 0 ]]' "exit $KS_RC"

if command -v timeout >/dev/null 2>&1; then
  printf 'import time\ntime.sleep(30)\n' > "$T/hanging-keep.py"
  KS_START=$(date +%s)
  CLADE_KEEP_SESSIONS="$T/hanging-keep.py" CLADE_KEEP_SESSIONS_TIMEOUT=1 run_cron 2026-02-09 none; KS_RC=$?
  check "a hanging keep-sessions is cut off by the timeout" '[[ $(( $(date +%s) - KS_START )) -lt 25 ]]'
  check "and logged as rc=124" 'grep -q "KEEP-SESSIONS FAILED rc=124" "$LOG_FILE"'
  check "and the wrapper still exits 0" '[[ $KS_RC -eq 0 ]]' "exit $KS_RC"
else
  skip "a hanging keep-sessions is cut off" "no timeout(1) on this host"
fi

# ─── 9. old radar branches are rebased or reported before the next run ──
section "radar branch upkeep preserves local work and records review debt"
UPKEEP_REPO="$T/upkeep"
UPKEEP_STATE="$HOME/.claude/research/radar-branch-state.tsv"
git init -q -b main "$UPKEEP_REPO"
git -C "$UPKEEP_REPO" config user.email t@example.com
git -C "$UPKEEP_REPO" config user.name t
printf 'base\n' > "$UPKEEP_REPO/shared.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm base
git -C "$UPKEEP_REPO" branch radar/merged main
MERGED_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/merged)

git -C "$UPKEEP_REPO" checkout -qb radar/behind
printf 'behind work\n' > "$UPKEEP_REPO/behind.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm behind
BEHIND_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/behind)

git -C "$UPKEEP_REPO" checkout -q main
git -C "$UPKEEP_REPO" checkout -qb radar/conflict
printf 'radar version\n' > "$UPKEEP_REPO/shared.txt"
GIT_AUTHOR_DATE=2020-01-01T00:00:00Z GIT_COMMITTER_DATE=2020-01-01T00:00:00Z \
  git -C "$UPKEEP_REPO" commit -qam conflict
CONFLICT_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/conflict)

# The final tree merges cleanly (shared.txt is back at base), but replaying the
# intermediate commit onto main stops. The wrapper must abort that rebase.
git -C "$UPKEEP_REPO" checkout -q main
git -C "$UPKEEP_REPO" checkout -qb radar/rebase-conflict
printf 'intermediate conflict\n' > "$UPKEEP_REPO/shared.txt"
printf 'step one\n' > "$UPKEEP_REPO/step-one.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm rebase-step-one
printf 'base\n' > "$UPKEEP_REPO/shared.txt"
printf 'step two\n' > "$UPKEEP_REPO/step-two.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm rebase-step-two
REBASE_CONFLICT_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/rebase-conflict)

git -C "$UPKEEP_REPO" checkout -q main
printf 'main version\n' > "$UPKEEP_REPO/shared.txt"
printf 'main advanced\n' > "$UPKEEP_REPO/main.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm main-advanced
git -C "$UPKEEP_REPO" checkout -qb radar/clean main
printf 'clean ahead work\n' > "$UPKEEP_REPO/clean.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm clean
CLEAN_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/clean)
git -C "$UPKEEP_REPO" checkout -q main

run_upkeep() {  # run_upkeep <date>; UPKEEP_RUNTIME can force no fallback root
  CLADE_RADAR_REPO="$UPKEEP_REPO" CLADE_KEEP_SESSIONS="$T/no-keep.py" \
    CLADE_RUNTIME_DIR="${UPKEEP_RUNTIME:-$T/upkeep-runtime}" run_cron "$1" none
}
upkeep_field() {  # upkeep_field <branch> <TSV column>
  awk -F '\t' -v b="$1" -v f="$2" '$1 == b { print $f; exit }' "$UPKEEP_STATE" 2>/dev/null
}

REAL_GIT=$(command -v git)
mkdir -p "$T/log-git"
cat > "$T/log-git/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GIT_TRACE_LOG"
exec "$REAL_GIT" "$@"
EOF
chmod +x "$T/log-git/git"
PATH="$T/log-git:$PATH" REAL_GIT="$REAL_GIT" GIT_TRACE_LOG="$T/upkeep-git.log" run_upkeep 2026-03-02
check "a clean behind branch has a new tip" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/behind)" != "$BEHIND_TIP" ]]'
check "the rebased branch descends from main" \
  'git -C "$UPKEEP_REPO" merge-base --is-ancestor main radar/behind'
check "rebase preserves the branch content and gains main's content" \
  '[[ "$(git -C "$UPKEEP_REPO" show radar/behind:behind.txt)" == "behind work" ]] && [[ "$(git -C "$UPKEEP_REPO" show radar/behind:main.txt)" == "main advanced" ]]'
check "a conflicting branch is left at its exact old tip" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/conflict)" == "$CONFLICT_TIP" ]]'
check "the conflict state records first-seen date and path" \
  '[[ "$(upkeep_field radar/conflict 2)" == conflict ]] && [[ "$(upkeep_field radar/conflict 3)" == 2026-03-02 ]] && [[ "$(upkeep_field radar/conflict 4)" == *shared.txt* ]]'
check "a conflicting branch older than four weeks is only a deletion candidate" \
  '[[ "$(upkeep_field radar/conflict 5)" == 1 ]] && git -C "$UPKEEP_REPO" rev-parse -q --verify refs/heads/radar/conflict >/dev/null'
check "a young conflicting branch is not a deletion candidate" \
  '[[ "$(upkeep_field radar/rebase-conflict 5)" == 0 ]]'
check "a branch already merged into main is untouched and absent from state" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/merged)" == "$MERGED_TIP" ]] && [[ -z "$(upkeep_field radar/merged 1)" ]]'
check "an ahead-only clean branch is untouched and recorded clean" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/clean)" == "$CLEAN_TIP" ]] && [[ "$(upkeep_field radar/clean 2)" == clean ]]'
check "a stopped rebase is aborted and leaves the branch untouched" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/rebase-conflict)" == "$REBASE_CONFLICT_TIP" ]] && grep -q "rebase --abort" "$T/upkeep-git.log"'
check "a stopped rebase is reported with its conflict path" \
  '[[ "$(upkeep_field radar/rebase-conflict 2)" == conflict ]] && [[ "$(upkeep_field radar/rebase-conflict 4)" == *shared.txt* ]]'
check "branch upkeep leaves no throwaway worktree registered" \
  '[[ "$(git -C "$UPKEEP_REPO" worktree list --porcelain | grep -c "^worktree ")" == 1 ]]'

printf '%s\n' "$UPKEEP_REPO" > "$HOME/.claude/.kit-source-dir"
SC_UPKEEP=$(cd "$UPKEEP_REPO" && printf '{"session_id":"t"}' | CLAUDE_PROJECT_DIR="$UPKEEP_REPO" bash "$SESSION_HOOK" 2>/dev/null)
printf '%s\n' "$T/kit" > "$HOME/.claude/.kit-source-dir"
SC_UPKEEP_CONTEXT=$(jq -r '.hookSpecificOutput.additionalContext // empty' <<< "$SC_UPKEEP")
SC_CONFLICT_LINE=$(printf '%b\n' "$SC_UPKEEP_CONTEXT" | grep -F "  radar/conflict ")
SC_REBASE_CONFLICT_LINE=$(printf '%b\n' "$SC_UPKEEP_CONTEXT" | grep -F "  radar/rebase-conflict ")
SC_MERGED_LINE=$(printf '%b\n' "$SC_UPKEEP_CONTEXT" | grep -F "  radar/merged ")
SC_CLEAN_LINE=$(printf '%b\n' "$SC_UPKEEP_CONTEXT" | grep -F "  radar/clean ")
check "session-context reports conflict paths and first-seen date" \
  '[[ "$SC_CONFLICT_LINE" == *"conflicts with main in shared.txt since 2026-03-02"* ]]' \
  "line: $SC_CONFLICT_LINE"
check "session-context marks the old conflict's own line as a deletion candidate" \
  '[[ "$SC_CONFLICT_LINE" == *"deletion candidate"* ]]'
check "the young conflict's own line has no deletion-candidate annotation" \
  '[[ "$SC_REBASE_CONFLICT_LINE" == *"conflicts with main"* ]] && [[ "$SC_REBASE_CONFLICT_LINE" != *"deletion candidate"* ]]'
check "a merged branch has no upkeep annotation" \
  '[[ "$SC_MERGED_LINE" == "  radar/merged — base" ]]'
check "a clean state row has no upkeep annotation" \
  '[[ "$SC_CLEAN_LINE" == "  radar/clean — clean" ]]'
check "session-context reports the rebase date" \
  '[[ "$SC_UPKEEP" == *"radar/behind"* ]] && [[ "$SC_UPKEEP" == *"rebased onto main 2026-03-02"* ]]'

CLADE_RADAR_DELETE_AFTER_WEEKS=1000 run_upkeep 2026-03-05
check "the deletion-age threshold override leaves the old conflict too young" \
  '[[ "$(upkeep_field radar/conflict 5)" == 0 ]]'
run_upkeep 2026-03-09
check "a later run preserves the conflict's first-seen date" \
  '[[ "$(upkeep_field radar/conflict 3)" == 2026-03-02 ]]'
check "a later run preserves the last rebase report" \
  '[[ "$(upkeep_field radar/behind 2)" == rebased ]] && [[ "$(upkeep_field radar/behind 3)" == 2026-03-02 ]]'

# Simulate git < 2.38: every merge-tree --write-tree call is unsupported.
REAL_GIT=$(command -v git)
mkdir -p "$T/old-git"
cat > "$T/old-git/git" <<'EOF'
#!/usr/bin/env bash
for arg in "$@"; do
  [[ "$arg" == --write-tree ]] && exit 129
done
exec "$REAL_GIT" "$@"
EOF
chmod +x "$T/old-git/git"
git -C "$UPKEEP_REPO" checkout -qb radar/fallback main
printf 'fallback work\n' > "$UPKEEP_REPO/fallback.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm fallback
FALLBACK_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/fallback)
git -C "$UPKEEP_REPO" checkout -q main
printf 'main advances again\n' > "$UPKEEP_REPO/main-again.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm main-advanced-again
PATH="$T/old-git:$PATH" REAL_GIT="$REAL_GIT" run_upkeep 2026-03-16
check "the throwaway-worktree fallback rebases on older git" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/fallback)" != "$FALLBACK_TIP" ]] && git -C "$UPKEEP_REPO" merge-base --is-ancestor main radar/fallback && [[ "$(git -C "$UPKEEP_REPO" show radar/fallback:fallback.txt)" == "fallback work" ]]'
check "the fallback also leaves no worktree behind" \
  '[[ "$(git -C "$UPKEEP_REPO" worktree list --porcelain | grep -c "^worktree ")" == 1 ]]'

git -C "$UPKEEP_REPO" checkout -qb radar/unknown main
printf 'unknown work\n' > "$UPKEEP_REPO/unknown.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm unknown
UNKNOWN_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/unknown)
git -C "$UPKEEP_REPO" checkout -q main
printf 'main advances once more\n' > "$UPKEEP_REPO/main-once-more.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm main-advanced-once-more
UPKEEP_RUNTIME=/dev/null PATH="$T/old-git:$PATH" REAL_GIT="$REAL_GIT" run_upkeep 2026-03-23
check "with neither merge mechanism the branch is untouched and unknown" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/unknown)" == "$UNKNOWN_TIP" ]] && [[ "$(upkeep_field radar/unknown 2)" == unknown ]]'
run_upkeep 2026-03-30
check "an unknown probe does not erase the conflict's first-seen date" \
  '[[ "$(upkeep_field radar/conflict 3)" == 2026-03-02 ]]'

# A rebase refreshes committer dates but preserves author dates. Age must still
# be old when a later main change turns the rebased branch into a conflict.
git -C "$UPKEEP_REPO" checkout -q main
printf 'age base\n' > "$UPKEEP_REPO/age-shared.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm age-base
git -C "$UPKEEP_REPO" checkout -qb radar/age
printf 'age radar one\n' > "$UPKEEP_REPO/age-shared.txt"
printf 'age step one\n' > "$UPKEEP_REPO/age-one.txt"
git -C "$UPKEEP_REPO" add .
GIT_AUTHOR_DATE=2020-01-06T00:00:00Z GIT_COMMITTER_DATE=2020-01-06T00:00:00Z \
  git -C "$UPKEEP_REPO" commit -qm age-step-one
printf 'age step two\n' > "$UPKEEP_REPO/age-two.txt"
git -C "$UPKEEP_REPO" add .
GIT_AUTHOR_DATE=2020-01-06T00:00:00Z GIT_COMMITTER_DATE=2020-01-06T00:00:00Z \
  git -C "$UPKEEP_REPO" commit -qm age-step-two
AGE_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/age)
AGE_AUTHOR_BEFORE=$(git -C "$UPKEEP_REPO" log -1 --format=%at radar/age)
git -C "$UPKEEP_REPO" checkout -q main
printf 'clean main advance\n' > "$UPKEEP_REPO/age-main.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm age-main-clean
run_upkeep 2026-04-06
AGE_REBASED_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/age)
git -C "$UPKEEP_REPO" checkout -q main
printf 'age main conflict\n' > "$UPKEEP_REPO/age-shared.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm age-main-conflict
run_upkeep 2026-04-13
check "a rebase-refreshed committer date does not reset deletion age" \
  '[[ "$AGE_REBASED_TIP" != "$AGE_TIP" ]] && [[ "$(git -C "$UPKEEP_REPO" log -1 --format=%at radar/age)" == "$AGE_AUTHOR_BEFORE" ]] && [[ "$(git -C "$UPKEEP_REPO" log -1 --format=%ct radar/age)" != "$AGE_AUTHOR_BEFORE" ]] && [[ "$(upkeep_field radar/age 2)" == conflict ]] && [[ "$(upkeep_field radar/age 5)" == 1 ]]'

# An operational rebase failure has no unmerged paths and is not a conflict.
git -C "$UPKEEP_REPO" checkout -qb radar/rebase-error main
printf 'rebase error work\n' > "$UPKEEP_REPO/rebase-error.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm rebase-error
REBASE_ERROR_TIP=$(git -C "$UPKEEP_REPO" rev-parse radar/rebase-error)
git -C "$UPKEEP_REPO" checkout -q main
printf 'main advances cleanly\n' > "$UPKEEP_REPO/rebase-error-main.txt"
git -C "$UPKEEP_REPO" add . && git -C "$UPKEEP_REPO" commit -qm rebase-error-main
mkdir -p "$T/failing-rebase-git"
cat > "$T/failing-rebase-git/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GIT_TRACE_LOG"
rebase_seen=0
for arg in "$@"; do
  if [[ $rebase_seen -eq 1 ]]; then
    if [[ "$arg" != --abort ]]; then
      printf 'injected rebase failure\n'
      exit 1
    fi
    rebase_seen=0
  elif [[ "$arg" == rebase ]]; then
    rebase_seen=1
  fi
done
exec "$REAL_GIT" "$@"
EOF
chmod +x "$T/failing-rebase-git/git"
PATH="$T/failing-rebase-git:$PATH" REAL_GIT="$REAL_GIT" GIT_TRACE_LOG="$T/rebase-error-git.log" run_upkeep 2026-04-20
check "a rebase failure without unmerged paths is aborted and unknown" \
  '[[ "$(git -C "$UPKEEP_REPO" rev-parse radar/rebase-error)" == "$REBASE_ERROR_TIP" ]] && [[ "$(upkeep_field radar/rebase-error 2)" == unknown ]] && [[ "$(upkeep_field radar/rebase-error 4)" == *"rebase failed: injected rebase failure"* ]] && [[ "$(upkeep_field radar/rebase-error 5)" == 0 ]] && grep -q "rebase --abort" "$T/rebase-error-git.log"'

# ─── 10. tracking main is local; a pushed radar branch is shared ──────
section "radar upkeep distinguishes auto-tracking from a pushed copy"
SHARED_ORIGIN="$T/shared-origin.git"
SHARED_REPO="$T/shared"
SHARED_STATE="$HOME/.claude/research/radar-branch-state.tsv"
git init -q --bare "$SHARED_ORIGIN"
git clone -q "$SHARED_ORIGIN" "$SHARED_REPO" 2>/dev/null
git -C "$SHARED_REPO" config user.email t@example.com
git -C "$SHARED_REPO" config user.name t
git -C "$SHARED_REPO" checkout -qb main
mkdir -p "$SHARED_REPO/configs/hooks"
printf '#!/usr/bin/env bash\necho foo\n' > "$SHARED_REPO/configs/hooks/foo.sh"
printf '.radar-staged/\n' > "$SHARED_REPO/.gitignore"
git -C "$SHARED_REPO" add . && git -C "$SHARED_REPO" commit -qm base
git -C "$SHARED_REPO" push -q -u origin main
run_shared() {  # run_shared <date> <stub-mode>
  CLADE_RADAR_REPO="$SHARED_REPO" CLADE_KEEP_SESSIONS="$T/no-keep.py" \
    CLADE_RUNTIME_DIR="$T/shared-runtime" run_cron "$1" "$2"
}
shared_field() {  # shared_field <branch> <TSV column>
  awk -F '\t' -v b="$1" -v f="$2" '$1 == b { print $f; exit }' "$SHARED_STATE" 2>/dev/null
}

# This branch is created by the wrapper from origin/main and therefore has the
# same autoSetupMerge configuration as the production radar branches.
run_shared 2026-05-04 edit
PROD_BRANCH=radar/2026-05-04
PROD_TIP=$(git -C "$SHARED_REPO" rev-parse "$PROD_BRANCH")

# The non-main upstream is the only guard for this branch: its second commit
# has never been pushed, so no remote-tracking ref contains its current tip.
git -C "$SHARED_REPO" checkout -qb radar/pushed main
printf 'pushed commit\n' > "$SHARED_REPO/pushed.txt"
git -C "$SHARED_REPO" add . && git -C "$SHARED_REPO" commit -qm pushed
git -C "$SHARED_REPO" push -q -u origin radar/pushed
printf 'local-only commit\n' > "$SHARED_REPO/pushed-local.txt"
git -C "$SHARED_REPO" add . && git -C "$SHARED_REPO" commit -qm pushed-local
PUSHED_TIP=$(git -C "$SHARED_REPO" rev-parse radar/pushed)

# This copy is genuinely on the remote, but has no upstream configuration.
git -C "$SHARED_REPO" checkout -q main
git -C "$SHARED_REPO" checkout -qb radar/pushed-no-upstream
printf 'pushed without upstream\n' > "$SHARED_REPO/pushed-no-upstream.txt"
git -C "$SHARED_REPO" add . && git -C "$SHARED_REPO" commit -qm pushed-no-upstream
git -C "$SHARED_REPO" push -q origin radar/pushed-no-upstream
NO_UPSTREAM_TIP=$(git -C "$SHARED_REPO" rev-parse radar/pushed-no-upstream)
git -C "$SHARED_REPO" checkout -q main

# Advance main from another clone, without touching any radar branch's files.
git clone -q --branch main "$SHARED_ORIGIN" "$T/shared-pusher"
git -C "$T/shared-pusher" config user.email t@example.com
git -C "$T/shared-pusher" config user.name t
printf 'unrelated main advance\n' > "$T/shared-pusher/main-update.txt"
git -C "$T/shared-pusher" add . && git -C "$T/shared-pusher" commit -qm main-update
git -C "$T/shared-pusher" push -q origin main
git -C "$SHARED_REPO" fetch -q origin
run_shared 2026-05-11 none

check "a cron-created branch tracking only origin/main is rebased" \
  '[[ "$(git -C "$SHARED_REPO" config --get branch.$PROD_BRANCH.remote)" == origin ]] && [[ "$(git -C "$SHARED_REPO" config --get branch.$PROD_BRANCH.merge)" == refs/heads/main ]] && [[ "$(git -C "$SHARED_REPO" rev-parse "$PROD_BRANCH")" != "$PROD_TIP" ]] && git -C "$SHARED_REPO" merge-base --is-ancestor origin/main "$PROD_BRANCH" && [[ "$(git -C "$SHARED_REPO" show "$PROD_BRANCH":configs/hooks/new-note.md)" == note ]] && [[ "$(shared_field "$PROD_BRANCH" 2)" == rebased ]]'
check "a non-main upstream is never rewritten even when its tip is unpushed" \
  '[[ -z "$(git -C "$SHARED_REPO" for-each-ref --contains refs/heads/radar/pushed --format="%(refname)" refs/remotes/)" ]] && [[ "$(git -C "$SHARED_REPO" rev-parse radar/pushed)" == "$PUSHED_TIP" ]] && [[ "$(shared_field radar/pushed 2)" == upstream ]]'
check "a pushed tip without upstream configuration is never rewritten" \
  '[[ -n "$(git -C "$SHARED_REPO" for-each-ref --contains refs/heads/radar/pushed-no-upstream --format="%(refname)" refs/remotes/)" ]] && [[ -z "$(git -C "$SHARED_REPO" config --get branch.radar/pushed-no-upstream.remote)" ]] && [[ -z "$(git -C "$SHARED_REPO" config --get branch.radar/pushed-no-upstream.merge)" ]] && [[ "$(git -C "$SHARED_REPO" rev-parse radar/pushed-no-upstream)" == "$NO_UPSTREAM_TIP" ]] && [[ "$(shared_field radar/pushed-no-upstream 2)" == upstream ]]'

printf '%s\n' "$SHARED_REPO" > "$HOME/.claude/.kit-source-dir"
SC_SHARED=$(cd "$SHARED_REPO" && printf '{"session_id":"t"}' | CLAUDE_PROJECT_DIR="$SHARED_REPO" bash "$SESSION_HOOK" 2>/dev/null)
printf '%s\n' "$T/kit" > "$HOME/.claude/.kit-source-dir"
SC_SHARED_CONTEXT=$(jq -r '.hookSpecificOutput.additionalContext // empty' <<< "$SC_SHARED")
SC_PROD_LINE=$(printf '%b\n' "$SC_SHARED_CONTEXT" | grep -F "  $PROD_BRANCH ")
check "the cron-created branch's session line reports rebase, not upstream" \
  '[[ "$SC_PROD_LINE" == *"rebased onto main 2026-05-11"* ]] && [[ "$SC_PROD_LINE" != *"has upstream"* ]]'

# ─── Summary ─────────────────────────────────────────────────────────
printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
if [[ "$TESTS_FAILED" -eq 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}FAILED${NC} (%d/%d passed, %d failed)" "$TESTS_PASSED" "$TESTS_RUN" "$TESTS_FAILED"
fi
[[ "$TESTS_SKIPPED" -gt 0 ]] && printf ", %d skipped" "$TESTS_SKIPPED"
printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
[[ "$TESTS_FAILED" -eq 0 ]]
