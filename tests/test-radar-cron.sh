#!/usr/bin/env bash
# test-radar-cron.sh — the weekly radar wrapper keeps its edits to itself.
#
# Until 2026-10-20 the unattended sweep ran from cron's cwd ($HOME) and edited
# the kit checkout in place: the 10-12 run's edits sat on fix/warm-pace for four
# days, the 10-19 run's on main, and neither was verified or committed by the
# run that wrote them. radar-cron.sh now gives the agent its own worktree on a
# radar/<date> branch, verifies what it changed (bash -n; the suites that name a
# changed file, in a bubblewrap sandbox), commits to that local branch, removes
# the worktree, and never pushes.
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
  CLADE_CLAUDE_BIN="$T/claude" CLADE_RADAR_DATE="$1" STUB_MODE="$2" STUB_LOG="$T/stub.log" \
    CLADE_RADAR_LOCK="$T/radar.lock" CLADE_RADAR_WORKTREES="$T/wts" \
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
mkdir -p "$T/other" && git -C "$T/other" init -q
SC_OTHER=$(cd "$T/other" && printf '{"session_id":"t"}' | CLAUDE_PROJECT_DIR="$T/other" bash "$SESSION_HOOK" 2>/dev/null)
check "a session in another repository does not" '[[ "$SC_OTHER" != *"radar/2026-01-05"* ]]'

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
