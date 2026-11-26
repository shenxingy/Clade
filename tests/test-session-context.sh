#!/usr/bin/env bash
# test-session-context.sh — SessionStart context-budget tests, split out of
# tests/test-hooks.sh when the combined file crossed the 1500-line rule.
#
#   session-context.sh      SessionStart context BUDGET: rules tail, whole
#                           lines, drop notice, file caps, ceiling warning,
#                           conversation-mode projects
#
# Every path is redirected to throwaway dirs under /tmp; the real ~/.claude is
# never touched. No API calls.
#
# Usage:
#   bash tests/test-session-context.sh        # Run all tests
#   bash tests/test-session-context.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_CONTEXT="$REPO_ROOT/configs/hooks/session-context.sh"

# ─── Test framework (mirrors tests/test-hooks.sh) ────────────────────
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
# assert_line <haystack> <line> <msg> — one line of the payload is exactly <line>:
# the title, and nothing after it on that line.
assert_line() {
  local haystack="$1" line="$2" msg="$3"
  if grep -qxF -- "$line" <<< "$haystack"; then pass "$msg"
  else fail "$msg" "no line equal to '$line'"; fi
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
TMP_ROOT="$(mktemp -d /tmp/clade-session-context-test-XXXXXX)"
case "$TMP_ROOT" in
  /tmp/clade-session-context-test-*) : ;;
  *) echo "FATAL: sandbox '$TMP_ROOT' is not under /tmp — aborting"; exit 1 ;;
esac
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME/.claude"

# ─── session-context.sh — SessionStart context budget ────────────────
# A real 2026-09-02 injection measured 24,057 chars, 82.7% of it the
# correction-rules block (`tail -25` of a file with no byte cap). The 20KB
# skill catalog deleted in 8406ed4 pushed hook output past the harness inline
# limit (30.8KB) and the WHOLE additionalContext was silently written to a file
# instead of entering context. These assertions are what keeps that measured.

section "session-context.sh — context budget"

BUDGET_HOME="$TMP_ROOT/budget-home"
mkdir -p "$BUDGET_HOME/.claude/corrections"
# Freeze the audit clock: run_auto_audit rewrites rules.md when .last-audit is
# stale, which would make every assertion below depend on wall time.
touch "$BUDGET_HOME/.claude/corrections/.last-audit"
GRULES="$BUDGET_HOME/.claude/corrections/rules.md"

BPROJ="$TMP_ROOT/budget-proj"
mkdir -p "$BPROJ"
git -C "$BPROJ" init -q -b main . >/dev/null 2>&1
git -C "$BPROJ" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init >/dev/null 2>&1

ctx() {  # extra env as KEY=VAL args
  echo '{}' | env "$@" HOME="$BUDGET_HOME" CLAUDE_PROJECT_DIR="$BPROJ" \
    bash "$SESSION_CONTEXT" | jq -r '.hookSpecificOutput.additionalContext // empty'
}

# 200 rules × ~500 bytes ≈ 100KB. Each ends in a unique sentinel so a
# mid-sentence cut is detectable.
: > "$GRULES"
for i in $(seq -w 1 200); do
  printf -- '- [2026-09-01] domain-%s (edge-case): %s #RULE-%s-END\n' \
    "$i" "$(head -c 440 < /dev/zero | tr '\0' 'x')" "$i" >> "$GRULES"
done

OUT=$(ctx CLADE_X=1)
assert_eq "$?" "0" "session-context exits 0 with a 100KB rules file"

# BUDGET HOLDS — without the fix this is ~24,000 and the assertion fails by an
# order of magnitude.
if [[ ${#OUT} -lt 12000 ]]; then
  pass "a 100KB rules.md yields an injection under 12,000 chars (${#OUT})"
else
  fail "a 100KB rules.md yields an injection under 12,000 chars" "got ${#OUT}"
fi

# WHOLE LINES ONLY: every rule that starts also ends. A byte cut would leave a
# started rule with no sentinel.
starts=$(grep -o -- '- \[2026-09-01\] domain-[0-9]*' <<< "$OUT" | wc -l | tr -d ' ')
ends=$(grep -o '#RULE-[0-9]*-END' <<< "$OUT" | wc -l | tr -d ' ')
assert_eq "$ends" "$starts" "every emitted rule is a whole line (no mid-rule byte cut)"
[[ "$ends" -gt 0 ]] \
  && pass "the budget keeps at least one rule ($ends kept)" \
  || fail "the budget keeps at least one rule" "kept none"

# NEWEST KEPT: recency is the whole point of a tail.
assert_contains "$OUT" "#RULE-200-END" "the newest rule survives the budget"
if grep -q '#RULE-001-END' <<< "$OUT"; then
  fail "the oldest rule is dropped" "RULE-001 is still injected"
else
  pass "the oldest rule is dropped"
fi

# DROP NOTICE, with the count and the tool that fixes the cause.
notice=$(grep -oE '\([0-9]+ older rules not shown[^)]*\)' <<< "$OUT" | head -1)
if [[ -n "$notice" ]]; then
  pass "the dropped rules are reported, not silently discarded"
else
  fail "the dropped rules are reported, not silently discarded" "no notice in output"
fi
assert_contains "$notice" "/audit" "the drop notice names the tool that fixes the cause"
dropped=$(sed -E 's/^\(([0-9]+).*/\1/' <<< "$notice")
assert_eq "$dropped" "$(( 200 - ends ))" "the reported drop count matches what was withheld"

# ENV OVERRIDE is wired (settings/wiring is the failure pattern this repo keeps hitting).
OUT_SMALL=$(ctx CLADE_RULES_BUDGET_BYTES=800)
small_ends=$(grep -o '#RULE-[0-9]*-END' <<< "$OUT_SMALL" | wc -l | tr -d ' ')
if [[ "$small_ends" -lt "$ends" && "$small_ends" -gt 0 ]]; then
  pass "CLADE_RULES_BUDGET_BYTES=800 shrinks the block ($ends → $small_ends rules)"
else
  fail "CLADE_RULES_BUDGET_BYTES=800 shrinks the block" "$ends → $small_ends"
fi

# NO NOTICE WHEN IT FITS, and every rule is verbatim.
: > "$GRULES"
for i in 1 2 3; do
  printf -- '- [2026-09-01] tiny-%s (edge-case): short rule %s #RULE-00%s-END\n' "$i" "$i" "$i" >> "$GRULES"
done
OUT=$(ctx CLADE_X=1)
if grep -q 'older rules not shown' <<< "$OUT"; then
  fail "no drop notice when everything fits" "notice present with only 3 rules"
else
  pass "no drop notice when everything fits"
fi
for i in 1 2 3; do
  assert_contains "$OUT" "#RULE-00$i-END" "small rules.md is injected in full (rule $i)"
done

# BOTH SOURCES REPRESENTED: the project file must not starve the global one.
mkdir -p "$BPROJ/.claude/corrections"
touch "$BPROJ/.claude/corrections/.last-audit"
: > "$GRULES"
: > "$BPROJ/.claude/corrections/rules.md"
for i in $(seq -w 1 60); do
  printf -- '- [2026-09-01] g-%s (edge-case): %s #RULE-%s-END\n' \
    "$i" "$(head -c 440 < /dev/zero | tr '\0' 'g')" "$i" >> "$GRULES"
  printf -- '- [2026-09-01] p-%s (edge-case): %s #PROJ-%s-END\n' \
    "$i" "$(head -c 440 < /dev/zero | tr '\0' 'p')" "$i" >> "$BPROJ/.claude/corrections/rules.md"
done
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "#PROJ-60-END" "the newest project rule is injected"
assert_contains "$OUT" "#RULE-60-END" "the global file is not starved to zero by the project half"

# HANDOFF CAP: an unbounded handoff was the next overflow waiting to happen.
# The /pickup imperative is appended AFTER the body, so it must survive.
mkdir -p "$BPROJ/.claude"
head -c 40000 < /dev/zero | tr '\0' 'y' > "$BPROJ/.claude/handoff-2026-09-02.md"
printf '\nHANDOFF-TAIL-SENTINEL\n' >> "$BPROJ/.claude/handoff-2026-09-02.md"
OUT=$(ctx CLADE_X=1)
if [[ ${#OUT} -lt 12000 ]]; then
  pass "a 40KB handoff stays inside the ceiling (${#OUT} chars)"
else
  fail "a 40KB handoff stays inside the ceiling" "got ${#OUT}"
fi
assert_contains "$OUT" "/pickup" "the /pickup imperative survives handoff truncation"
assert_contains "$OUT" "truncated:" "truncation is marked, not silent"
if grep -q 'HANDOFF-TAIL-SENTINEL' <<< "$OUT"; then
  fail "the handoff body is actually capped" "the 40KB tail was injected in full"
else
  pass "the handoff body is actually capped"
fi
rm -f "$BPROJ/.claude/handoff-2026-09-02.md"

# COMPACT SNAPSHOT: one that records no task is orientation, not "resume from
# here". 25 of 25 field snapshots (2026-09-18 → 10-26) recorded none, so a new
# session within 2h of another's compaction was told to resume a TODO backlog.
printf '# Pre-compact State: x\n\n## Current Task\n(none recorded — this snapshot carries no task)\n\n## Open TODO Items (backlog, not the current task)\n- [ ] COMPACT-BACKLOG-SENTINEL\n' \
  > "$BPROJ/.claude/compact-state.md"
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "COMPACT-BACKLOG-SENTINEL" "a fresh compact snapshot is still loaded"
assert_contains "$OUT" "it records no task" "a snapshot with no recorded task is framed as orientation"
assert_not_contains "$OUT" "resume from here" "and is not framed as work to resume"
printf '# Pre-compact State: x\n\n## Current Task\nShip GOAL-42\n' > "$BPROJ/.claude/compact-state.md"
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "resume from here" "control: a snapshot that records a task still says resume"
rm -f "$BPROJ/.claude/compact-state.md"

# CEILING WARNING: warn, never truncate — the guidance blocks are appended last.
OUT=$(ctx CLADE_CTX_CEILING_BYTES=100)
assert_contains "$OUT" "over the 100 budget" "an over-ceiling payload says so"
assert_contains "$OUT" "Close the loop" "the ceiling warning does not truncate the trailing sections"
# First, not last: past 10,000 characters Claude Code shows a 2,000-character
# preview, and a notice at the end was the first thing it dropped.
assert_contains "$(head -1 <<< "$OUT")" "(session-context:" "the over-ceiling notice is the first line"

# CONVERSATION MODE: a repository that is a conversation, not a codebase,
# declares it with .claude/conversation-mode. It keeps its own lessons and the
# language rule and loses the engineering scaffolding, other projects' rules and
# automatic promotion. Measured on one such repository before the marker
# existed: 103 promoted rules (90,172 chars) loaded into every chat.
section "session-context.sh — conversation-mode projects"
printf -- '- [2026-09-01] g-1 (edge-case): a global engineering rule #GLOBAL-RULE-END\n' > "$GRULES"
# Ten rules: run_auto_audit does nothing below ten (auto-audit.sh, count_rules).
: > "$BPROJ/.claude/corrections/rules.md"
for i in $(seq -w 1 10); do
  printf -- '- [2020-01-01] p-old-%s (deploy-gap): an old project lesson #PROJECT-RULE-END\n' "$i" \
    >> "$BPROJ/.claude/corrections/rules.md"
done
rm -f "$BPROJ/.claude/corrections/.last-audit"   # the project audit is due
printf '# proj\n' > "$BPROJ/CLAUDE.md"
printf 'Tailscale IP: 100.64.0.99\n' > "$BUDGET_HOME/.claude/.env-fingerprint"   # fresh cache
touch "$BPROJ/.claude/conversation-mode"
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "#PROJECT-RULE-END" "conversation mode keeps the project's own lessons"
assert_contains "$OUT" "same language the user writes in" "conversation mode keeps the language rule"
if grep -qxF "$BPROJ" "$BUDGET_HOME/.claude/private-projects" 2>/dev/null; then
  pass "conversation mode registers the project as private for sync-push"
else
  fail "conversation mode registers the project as private for sync-push" "not in ~/.claude/private-projects"
fi
for absent in "#GLOBAL-RULE-END" "Model guide" "Close the loop" "Recommended workflow" "Environment Fingerprint"; do
  if grep -qF "$absent" <<< "$OUT"; then
    fail "conversation mode leaves out: $absent" "still injected"
  else
    pass "conversation mode leaves out: $absent"
  fi
done
if grep -q 'Auto-Promoted Rules' "$BPROJ/CLAUDE.md"; then
  fail "conversation mode does not promote project rules into CLAUDE.md" "CLAUDE.md gained the block"
else
  pass "conversation mode does not promote project rules into CLAUDE.md"
fi
# Control: the same tree without the marker gets all of it back, so the
# assertions above cannot pass because the sections were simply absent.
rm -f "$BPROJ/.claude/conversation-mode"
OUT=$(ctx CLADE_X=1)
assert_contains "$OUT" "#GLOBAL-RULE-END" "control: without the marker, other projects' rules are injected"
assert_contains "$OUT" "Close the loop" "control: without the marker, the engineering guidance is back"
assert_contains "$OUT" "Environment Fingerprint" "control: without the marker, the host fingerprint is back"
grep -q 'Auto-Promoted Rules' "$BPROJ/CLAUDE.md" \
  && pass "control: without the marker, the due project audit promotes the rule" \
  || fail "control: without the marker, the due project audit promotes the rule" "no promotion happened"
rm -f "$BUDGET_HOME/.claude/.env-fingerprint"

# ─── Next TODO selection ─────────────────────────────────────────────
# The hook is global, so fixtures include both this repository's emoji markers
# and the plain TODO.md files used by other projects. Conversation mode keeps
# these runs offline without changing the TODO selection path.
section "session-context.sh — Next TODO selection"

TODO_HOME="$TMP_ROOT/todo-home"
TODO_PROJ="$TMP_ROOT/todo-proj"
mkdir -p "$TODO_HOME/.claude" "$TODO_PROJ/.claude"
touch "$TODO_PROJ/.claude/conversation-mode"
git -C "$TODO_PROJ" init -q -b main . >/dev/null 2>&1
git -C "$TODO_PROJ" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init >/dev/null 2>&1

todo_ctx() {
  echo '{}' | env HOME="$TODO_HOME" CLAUDE_PROJECT_DIR="$TODO_PROJ" \
    bash "$SESSION_CONTEXT" | jq -r '.hookSpecificOutput.additionalContext // empty'
}

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] Unmarked item comes first
- [ ] 🟠 Orange item outranks it
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🟠 Orange item outranks it" \
  "an orange item after an unmarked item wins"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🟠 Orange item comes first
- [ ] 🔴 Red item wins from later in the file
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🔴 Red item wins from later in the file" \
  "red beats orange regardless of file order"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔵 Blue item comes first
- [ ] 🟡 Yellow item outranks it
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🟡 Yellow item outranks it" \
  "yellow beats blue regardless of file order"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] Unmarked item comes first
- [ ] 🔵 Blue item outranks it
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🔵 Blue item outranks it" \
  "a blue item after an unmarked item wins"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 First red item stays selected
- [ ] 🔴 Second red item does not replace it
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🔴 First red item stays selected" \
  "file order breaks ties within a priority tier"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Needs ThE OwNeR — reconciled today
- [ ] 🔴 Owner-section red item is skipped
### Nested details
- [ ] 🟠 Nested owner-section orange item is skipped
## Agent work
- [ ] 🟡 Agent yellow item is eligible
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🟡 Agent yellow item is eligible" \
  "a level-two owner section skips even red items until its section ends"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Backlog
### Owner decisions
- [ ] 🔴 Level-three owner-section red item is skipped
#### Nested details
- [ ] 🟠 Deeply nested owner-section orange item is skipped
### Agent work
- [ ] 🔵 Agent blue item after the owner section is eligible
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🔵 Agent blue item after the owner section is eligible" \
  "a level-three owner section ends at the next same-level heading"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Backlog
### Owner decisions
- [ ] 🔴 Level-three owner-section red item is skipped
## Agent work
- [ ] 🟠 Agent orange item after the higher-level heading is eligible
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🟠 Agent orange item after the higher-level heading is eligible" \
  "an owner section also ends at a higher-level heading"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 Inline item (Needs The Owner) is skipped
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an inline needs-the-owner item is skipped case-insensitively"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 This is an OWNER DECISION, not agent work
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an inline owner-decision item is skipped case-insensitively"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 Owner: make this choice yourself
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an inline Owner-colon item is skipped"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Needs the owner
- [ ] Owner item must not win the fallback
## Agent work
- [ ] First unmarked agent item's unmatched quote stays safe
- [ ] Second unmarked agent item
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] First unmarked agent item's unmatched quote stays safe" \
  "without markers the first open item outside owner sections wins"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [x] Completed item
EOF
OUT=$(todo_ctx)
assert_not_contains "$OUT" "Next TODO:" "no open items produce no Next TODO line"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Needs the owner
- [ ] 🔴 Owner red item is the only open item
EOF
OUT=$(todo_ctx)
assert_not_contains "$OUT" "Next TODO:" "only owner-only open items produce no Next TODO line"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
  - [ ] 🔴 Indented item retains the old top-level-only exclusion
- [ ] Unmarked top-level item
EOF
OUT=$(todo_ctx)
assert_contains "$OUT" "Next TODO: - [ ] Unmarked top-level item" \
  "indented checkboxes remain outside the top-level-only matcher"

for spec in \
  '🔴|Red marked bold title' \
  '🟠|Orange marked bold title' \
  '🟡|Yellow marked bold title' \
  '🔵|Blue marked bold title'
do
  marker=${spec%%|*}
  title=${spec#*|}
  printf -- '- [ ] %s **%s** marked-bold-body\n' "$marker" "$title" > "$TODO_PROJ/TODO.md"
  OUT=$(todo_ctx)
  assert_line "$OUT" "Next TODO: $marker $title" \
    "a $marker marked bold item prints its title"
  assert_not_contains "$OUT" "marked-bold-body" \
    "a $marker marked bold item omits the body after its title"
done

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 **Don't break on a quote** quote-body
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: 🔴 Don't break on a quote" \
  "a marked bold title preserves an unmatched quote"
assert_not_contains "$OUT" "quote-body" "a quoted marked bold item omits its body"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] **Old style title** old-style-body
EOF
OUT=$(todo_ctx)
# Control: this unmarked old-style shape prints the same line on HEAD too.
assert_line "$OUT" "Next TODO: Old style title" \
  "control: an unmarked bold title keeps its old rendering"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] ** Spaced bold title ** spaced-body
EOF
OUT=$(todo_ctx)
# Control: passes on origin/main too, where a sed trimmed; it pins the awk trim of both ends.
assert_line "$OUT" "Next TODO: Spaced bold title" \
  "control: the printed title is trimmed at both ends"

# ─── Next TODO: fenced blocks are code, not structure (#204 residue) ──
# A column-0 `#` inside a fence was read as a heading, so a shell comment in a
# code sample ended an owner section and its items became eligible. Each spec is
# open|inner|close; the inner line must not close the fence (another fence
# character, a shorter run, a run with an info string after it, or a run indented
# four columns, which outside a list item is an indented code line).
for spec in \
  '```bash||```' \
  '~~~|```|~~~' \
  '````markdown|```|````' \
  '```|```bash|```' \
  '```markdown|    ```|```'
do
  IFS='|' read -r f_open f_inner f_close <<< "$spec"
  {
    printf '%s\n' '## Needs the owner' '- [ ] 🔴 Owner red item before the fence is skipped' "$f_open"
    [[ -n "$f_inner" ]] && printf '%s\n' "$f_inner"
    printf '%s\n' '# a column-0 comment inside the fence' "$f_close" \
      '- [ ] 🔴 Owner red item after the fence is skipped' \
      '## Agent work' '- [ ] 🟠 Agent orange item is eligible'
  } > "$TODO_PROJ/TODO.md"
  OUT=$(todo_ctx)
  assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
    "a column-0 # inside a fence (open '$f_open', inner '$f_inner') keeps the owner section open"
done

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Agent work
~~~markdown
## Owner decisions
~~~
- [ ] 🔴 Agent red item after the fence is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🔴 Agent red item after the fence is eligible" \
  "a fenced owner heading does not open an owner section"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
```markdown
- [ ] 🔴 Example item inside a fence is not a task
```
- [ ] 🔵 Real blue item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🔵 Real blue item is eligible" \
  "a checkbox inside a fence is not an open item"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
```inline``` code at the start of a line opens no fence
- [ ] 🔴 Red item after the inline code is eligible
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins that fence tracking cannot swallow the file.
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item after the inline code is eligible" \
  "control: a backtick run with a backtick after it is inline code, not a fence"

# ─── Next TODO: the owner check reads the whole item (#204 residue) ───
# An item is its `- [ ]` line plus every indented or blank line after it, up to
# the next column-0 line. The check read only the first line, so a TODO.md
# wrapped at 80 columns hid any owner phrase that landed on line two.
cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 **Pick the storage backend**
  Owner: choose between SQLite and Postgres.
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an owner phrase on an item's continuation line skips the item"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 **Retire the dormant GUI** — this needs
  the owner to sign off first.
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an owner phrase wrapped across the line break skips the item"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 **Item with a second paragraph**

  Needs the owner: a pricing call.
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an owner phrase after a blank line inside the item skips the item"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 **Item with a code sample**
  ```bash
  # an indented comment inside the item's own fence
  ```
  Owner: decide this first.
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an owner phrase after the item's own closed fence skips the item"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 **Add an owner field to the manifest**
  ```yaml

  owner: alice
  ```
- [ ] 🟠 Orange item
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too (it read one line); it pins that an item's own fence is
# code, and that a blank line inside it neither closes the fence nor ends the item.
assert_line "$OUT" "Next TODO: 🔴 Add an owner field to the manifest" \
  "an owner phrase inside the item's own fence is code, not an owner marker"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 **Add an owner field to each step**
  - [ ] Write the manifest
    ~~~yaml
    owner: alice
    ~~~
- [ ] 🟠 Orange item
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins that inside a list item (here a nested one)
# a fence indented four columns is still a fence, not an indented code line, and
# that a fence inside an item opens at all. A tilde fence on purpose: read as item
# text, a ``` fence pairs up like code spans and the span removal would hide it.
assert_line "$OUT" "Next TODO: 🔴 Add an owner field to each step" \
  "a nested item's fence indented four columns is code, not an owner marker"

# An inline code span is code too, so a field name in backticks is not an owner
# phrase. Text outside the span is still read, and so is everything after a lone
# backtick, which opens no span.
cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 Red item that adds a field
  named `metadata.owner: str` to the schema
- [ ] 🟠 Orange item
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item that adds a field" \
  "an owner phrase inside an inline code span does not skip the item"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 Rename the `owner` column; one lone ` backtick, and
  Owner: decide the new name
- [ ] 🟠 Orange item
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins that only a closed span is removed.
assert_line "$OUT" "Next TODO: - [ ] 🟠 Orange item" \
  "control: an owner phrase after a lone backtick still skips the item"

# A fence opened inside a list item ends when the item does: at the next column-0
# line, or at a fence line indented less than the item's content (the section
# after these). CommonMark; markdown-it agrees on every fixture below. Kept open,
# one unclosed sample hid every later item and heading until EOF.
cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🟡 **Fix the parser** for lines that open with
  ``` three backticks and never close them
- [ ] 🔴 Red item later in the file
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item later in the file" \
  "an unclosed fence inside an item ends with the item"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Needs the owner
- [ ] 🔴 Owner item with an unclosed sample
  ```bash
## Agent work
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an unclosed fence inside a skipped owner item ends with it, so the next heading is read"

for opener in '- [x] Done item' '1. Numbered step' '* Plain bullet' '+ Plus bullet' '1) Paren step'; do
  printf '%s\n' "$opener with an unclosed sample" '   ```bash' '- [ ] 🔴 Red item after it' \
    > "$TODO_PROJ/TODO.md"
  OUT=$(todo_ctx)
  assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item after it" \
    "an unclosed fence inside a '$opener' list item ends with that item"
done

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🟡 Yellow item
  ```bash
  code
```
- [ ] 🔴 Red item inside the fence the column-0 run opens
EOF
OUT=$(todo_ctx)
# The column-0 run ends the item, so it opens a top-level fence, not closes this one.
assert_line "$OUT" "Next TODO: - [ ] 🟡 Yellow item" \
  "a column-0 fence run after an item's fence ends the item and opens a new fence"

# Once the item has ended, a run indented four columns (four spaces or a tab) is
# an indented code line, not a fence: it opens nothing that could hide the rest.
fence_run='```'
for indent in '    ' $'\t'; do
  label='four spaces'; [[ "$indent" == $'\t' ]] && label='a tab'
  printf '%s\n' '- [ ] 🟡 Yellow item with an indented sample' "$indent${fence_run}bash" \
    '# a column-0 comment ends the item and its fence' "$indent$fence_run" \
    '- [ ] 🔴 Red item after an indented code line' > "$TODO_PROJ/TODO.md"
  OUT=$(todo_ctx)
  assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item after an indented code line" \
    "a fence run indented by $label in no list item opens no fence"
done

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Needs the owner
  ```bash
# a column-0 comment in an indented fence that is in no list item
  ```
- [ ] 🔴 Owner red item after the fence is skipped
## Agent work
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "an indented fence outside a list item is top-level: a column-0 line does not end it"

# ─── Next TODO: a fence left of an item's content is not the item's ──
# An item's content starts after its marker and the whitespace that follows
# (column 2 under "- ", 3 under "1. "; a tab reaches the next multiple of 4). A
# fence run indented less than that is not in the item, because CommonMark never
# continues an item lazily with a fence: the item ends there and the run opens a
# top-level fence, which a column-0 line does not end. Read as the item's fence,
# the column-0 `#` below ended it and was read as a heading, so the owner section
# ended early (or, with the closer then opening a new fence, nothing printed).
cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Needs the owner
1. Run the migration:
  ```bash
# column-0 comment inside the fence
  ```
2. Then check it:
  ```bash
  make check
  ```
- [ ] 🔴 Owner red item is skipped
## Agent work
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "a fence two columns in under a '1.' step is top-level, so its column-0 # keeps the owner section"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
## Needs the owner
- [ ] 🔴 Owner red item
 ```bash
# column-0 comment inside the fence
 ```
## Agent work
- [ ] 🟠 Agent orange item is eligible
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🟠 Agent orange item is eligible" \
  "a fence one column in under a '- [ ]' item is top-level, so its own closer closes it"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
1. Run this
  ```bash
# comment
  ```
- [ ] 🔴 Red item after a numbered step
EOF
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item after a numbered step" \
  "a fence left of a numbered step's content closes at its own closer"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🟡 Yellow item
  ```
  code
 ```
- [ ] 🔴 Red item inside the fence the under-indented run opens
EOF
OUT=$(todo_ctx)
# Inside the item's own fence too: the run left of the content ends the item and
# its fence, then opens a top-level fence (markdown-it parses it the same way).
assert_line "$OUT" "Next TODO: - [ ] 🟡 Yellow item" \
  "a fence run left of the content inside the item's fence ends the item and opens a new fence"

printf '%s\n' $'-\tStep with a tab after its marker' '  ```bash' '# comment' '  ```' \
  '- [ ] 🔴 Red item after it' > "$TODO_PROJ/TODO.md"
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item after it" \
  "a tab after the marker puts the content at column 4, so a fence two columns in is top-level"

printf '%s\n' '- [ ] 🟡 Yellow item' $'\t```' '- [ ] 🔴 Red item after it' > "$TODO_PROJ/TODO.md"
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins that a leading tab reaches column 4, past the content.
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item after it" \
  "a tab-indented fence inside an item is the item's and ends with it"

printf '%s\n' '100. Step with a three-digit number' '    ```bash' '- [ ] 🔴 Red item after it' \
  > "$TODO_PROJ/TODO.md"
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins that a run left of the content and four
# columns in ends the item and, in no item, opens nothing.
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item after it" \
  "a run four columns in, left of a '100.' step's content, opens no fence"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔴 Agent red item is eligible
- [ ] 🟠 Owner: the next item's phrase is not this item's
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins the item boundary the fix introduces.
assert_line "$OUT" "Next TODO: - [ ] 🔴 Agent red item is eligible" \
  "control: an item ends at the next column-0 line"

# Only the owner check reads the whole item. The tier, the pick and the fallback
# read its first line, so a body that mentions a marker cannot promote it and a
# wrapped body is not appended to the printed line. Every eligible item above is
# one line long, so none of these three uses was pinned. Unbolded titles on
# purpose: the "**" trim would cut an appended body off a bold one.
cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🔵 Blue item whose body
  mentions a 🔴 marker in passing
- [ ] 🟠 Orange item
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too (it read one line); it pins that the whole item stays out of the tier.
assert_line "$OUT" "Next TODO: - [ ] 🟠 Orange item" \
  "an item's tier comes from its first line, not a marker in its body"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] 🟠 Orange item whose body
  wraps onto a second line
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins that the pick prints the first line only.
assert_line "$OUT" "Next TODO: - [ ] 🟠 Orange item whose body" \
  "a picked item that wraps prints its first line only"

cat > "$TODO_PROJ/TODO.md" <<'EOF'
- [ ] Unmarked item whose body
  wraps onto a second line
EOF
OUT=$(todo_ctx)
# Control: passes on HEAD too; it pins that the fallback prints the first line only.
assert_line "$OUT" "Next TODO: - [ ] Unmarked item whose body" \
  "an unmarked fallback that wraps prints its first line only"

# ─── Next TODO: one marker list (#204 residue) ────────────────────────
# The four markers were written twice, in the awk tiers and again in a sed that
# trims the title, so a marker added to one was half-supported. Prepend a new
# marker to the single definition in a copy of the hook: it must outrank 🔴 and
# have its title trimmed, i.e. both uses read the one list.
DRIFT_HOOKS="$TMP_ROOT/drift-hooks"
cp -R "$REPO_ROOT/configs/hooks" "$DRIFT_HOOKS"
sed "s/^TODO_PRIORITY_MARKERS='/TODO_PRIORITY_MARKERS='🟣 /" \
  "$SESSION_CONTEXT" > "$DRIFT_HOOKS/session-context.sh"
if cmp -s "$SESSION_CONTEXT" "$DRIFT_HOOKS/session-context.sh"; then
  fail "fixture: the marker definition is one TODO_PRIORITY_MARKERS line" \
    "no line starts with TODO_PRIORITY_MARKERS=' — the anchor is gone"
else
  printf '%s\n' '- [ ] 🔴 **Red title** red-body' '- [ ] 🟣 **Purple title** purple-body' \
    > "$TODO_PROJ/TODO.md"
  OUT=$(echo '{}' | env HOME="$TODO_HOME" CLAUDE_PROJECT_DIR="$TODO_PROJ" \
    bash "$DRIFT_HOOKS/session-context.sh" | jq -r '.hookSpecificOutput.additionalContext // empty')
  assert_line "$OUT" "Next TODO: 🟣 Purple title" \
    "a marker added to the one definition sets both its tier and its title trim"
fi
for marker in 🔴 🟠 🟡 🔵; do
  assert_eq "$(grep -c -- "$marker" "$SESSION_CONTEXT")" "1" \
    "the $marker marker is written on one line of the hook"
done

# The owner phrases are one definition too. Add a phrase to TODO_OWNER_PHRASES in
# a copy of the hook: an item carrying it must then be skipped, which it is not
# by the shipped list (the control below), so the match reads the definition.
printf '%s\n' '- [ ] 🔴 Red item waiting on legal' '- [ ] 🟠 Orange item' > "$TODO_PROJ/TODO.md"
OUT=$(todo_ctx)
assert_line "$OUT" "Next TODO: - [ ] 🔴 Red item waiting on legal" \
  "control: the shipped owner phrases do not match 'waiting on legal'"
sed "s/^TODO_OWNER_PHRASES='/TODO_OWNER_PHRASES='waiting on legal|/" \
  "$SESSION_CONTEXT" > "$DRIFT_HOOKS/session-context.sh"
if cmp -s "$SESSION_CONTEXT" "$DRIFT_HOOKS/session-context.sh"; then
  fail "fixture: the owner phrases are one TODO_OWNER_PHRASES line" \
    "no line starts with TODO_OWNER_PHRASES=' — the anchor is gone"
else
  OUT=$(echo '{}' | env HOME="$TODO_HOME" CLAUDE_PROJECT_DIR="$TODO_PROJ" \
    bash "$DRIFT_HOOKS/session-context.sh" | jq -r '.hookSpecificOutput.additionalContext // empty')
  assert_line "$OUT" "Next TODO: - [ ] 🟠 Orange item" \
    "an owner phrase added to the one definition skips the item that carries it"
fi
for phrase in 'needs the owner' 'owner decision' 'owner:'; do
  assert_eq "$(grep -c -- "$phrase" "$SESSION_CONTEXT")" "1" \
    "the owner phrase '$phrase' is written on one line of the hook"
done

# ─── What the model reads: line breaks and the auto-pull notice ──────
# Every assertion above is a substring match, which passes whether sections are
# separated by a newline or by the two characters backslash and n — the shape
# 131 of 155 real SessionStart payloads had (2026-11-02). And the auto-pull
# notice was overwritten by the "Recent commits" assignment in every repository
# with a commit, so no test that used a repo with commits could have seen it.
# Both cases below fail against the pre-2026-11-02 hook.
section "session-context.sh — what the model reads"
PULL_REMOTE="$TMP_ROOT/pull-remote.git"
PULL_UP="$TMP_ROOT/pull-upstream"
PULL_PROJ="$TMP_ROOT/pull-proj"
gitq() { git -c user.email=t@t -c user.name=t -c init.defaultBranch=main "$@" >/dev/null 2>&1; }
gitq init -q --bare "$PULL_REMOTE"
gitq init -q "$PULL_UP"
gitq -C "$PULL_UP" commit -q --allow-empty -m "first upstream commit"
gitq -C "$PULL_UP" push -q "$PULL_REMOTE" HEAD:refs/heads/main
gitq clone -q -b main "$PULL_REMOTE" "$PULL_PROJ"
gitq -C "$PULL_UP" commit -q --allow-empty -m "PULLED-COMMIT-SENTINEL"
gitq -C "$PULL_UP" push -q "$PULL_REMOTE" HEAD:refs/heads/main

if [[ "$(git -C "$PULL_PROJ" rev-parse --abbrev-ref '@{u}' 2>/dev/null)" != "origin/main" ]]; then
  fail "fixture: a clean clone tracking a remote one commit ahead" "no upstream — setup failed, cases below skipped"
else
  printf 'Tailscale IP: 100.64.0.99\n' > "$BUDGET_HOME/.claude/.env-fingerprint"   # fresh cache, no host probes
  OUT=$(echo '{}' | env HOME="$BUDGET_HOME" CLAUDE_PROJECT_DIR="$PULL_PROJ" \
    bash "$SESSION_CONTEXT" | jq -r '.hookSpecificOutput.additionalContext // empty')
  rm -f "$BUDGET_HOME/.claude/.env-fingerprint"
  assert_contains "$OUT" "Auto-pulled 1 new commit(s) from origin/main" \
    "the auto-pull notice survives the Recent commits section"
  assert_contains "$OUT" "PULLED-COMMIT-SENTINEL" "the pulled commit is listed"
  if grep -qF '\n' <<< "$OUT"; then
    fail "sections are separated by real line breaks" \
      "$(grep -oF '\n' <<< "$OUT" | wc -l | tr -d ' ') literal backslash-n sequences delivered"
  else
    pass "sections are separated by real line breaks (no literal backslash-n)"
  fi
  if grep -qx 'Recent commits:' <<< "$OUT"; then
    pass "a section header occupies its own line"
  else
    fail "a section header occupies its own line" "no line equal to 'Recent commits:'"
  fi
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
