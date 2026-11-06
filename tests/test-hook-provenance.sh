#!/usr/bin/env bash
# test-hook-provenance.sh — every configs/hooks/*.sh names the incident it
# exists for and the condition under which it may retire. Split out of
# tests/test-hooks.sh, which this section would have pushed past the
# 1500-line rule a third time.
#
#   every configs/hooks/*.sh  one `# exists-for: … · retire-when: …` line near
#                             the top, cross-checked against the wiring in
#                             configs/settings-hooks.json
#   placeholders              the `<…>` of the docs and the `{…}` the
#                             /generate-hook template emits are both refused
#   zero-fires wordings       a table of natural phrasings ("unused for N
#                             days", "has not fired", "0 hits", …) that must be
#                             refused without an ablation, and near-misses
#                             that must not be
#   mutations                 each changes one copy of the hooks dir and must
#                             turn the check red
#
# Every path is redirected to a throwaway dir under /tmp. No API calls.
#
# Usage:
#   bash tests/test-hook-provenance.sh        # Run all tests
#   bash tests/test-hook-provenance.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$REPO_ROOT/configs/settings-hooks.json"
GEN_HOOK_PROMPT="$REPO_ROOT/configs/skills/generate-hook/prompt.md"

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

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d /tmp/clade-hook-provenance-test-XXXXXX)"
case "$TMP_ROOT" in
  /tmp/clade-hook-provenance-test-*) : ;;
  *) echo "FATAL: sandbox '$TMP_ROOT' is not under /tmp — aborting"; exit 1 ;;
esac
trap 'rm -rf "$TMP_ROOT"' EXIT

# ─── every hook names what it exists for and when it may retire ──────
#
# "Give every control an expiry condition, and write down the incident it
# exists for" (Zaninotto, Marmelab, 2026-09-24). On 2026-11-05 a rough grep
# found 18 of 35 hook headers naming no incident, and none saying when the hook
# could go. Each configs/hooks/*.sh (lib/ excluded) now carries exactly one
# line within its first 10:
#   # exists-for: <incident or need, date, commit/PR> · retire-when: <condition>
# A hook whose history records no incident says "no incident recorded (added
# <date> in <sha>)" rather than inventing one. A retire-when that rests on zero
# fires must name an ablation: a preventive guard that never fires may be
# working, so silence alone only flags it for review.
#
# hp_problems prints one line per problem; no output means clean. The count
# guard is the cross-check against settings-hooks.json: an empty or misdirected
# glob would otherwise check nothing and print nothing, which reads as clean.
# Every short sha must resolve to a commit, so a reference cannot be made up;
# that part needs history and is skipped (and says so) in a shallow clone.
# A #PR number is checked for form only: a new hook can cite its own open PR.

section "hooks — every hook names what it exists for and when it may retire"

HP_SEP=' · retire-when: '
HP_RESOLVE=0
if [[ "$(git -C "$REPO_ROOT" rev-parse --is-shallow-repository 2>/dev/null)" == "false" ]]; then
  HP_RESOLVE=1
fi

# A placeholder left in the line. `<incident…>`, `<condition>`, `<date>` and
# `<sha>` are the forms CLAUDE.md and this header use; `{…}` is what the
# /generate-hook template emits (`{the commit sha or #PR}`, `{condition}`).
# A `${VAR}` is a shell variable, not a placeholder, so a `{` after `$` passes.
HP_PLACEHOLDER='<(incident|condition|date|sha)|(^|[^A-Za-z])TBD([^A-Za-z]|$)|\?\?\?|(^|[^$])[{][^{}]*[}]'

# ─── zero-fires: does a retire-when rest on the control having gone quiet? ──
#
# A regex cannot read intent, so this matches wordings, not meaning. The
# wordings come from four shapes, each with fixtures below:
#   1. a negation before an act, up to two words apart: "zero fires", "not
#      fired", "has not once fired", "no recorded denials", "never triggered",
#      "0 hits", "stops firing", "zero-fire". Words are split on spaces only, so
#      "stops writing context-warning-<task>.md" is not "stops … warning"
#   2. an act counted at zero: "fires 0 times", "fire count stays at zero"
#   3. a last-seen age: "last fired over 60 days ago", "last-used"
#   4. an idle word with a window or a verb: "unused for 90 days", "a quiet
#      log", "goes silent", "is idle", or the bare "untriggered"/"unfired"
# Near-misses that must not match are in the same table: "no install sets X",
# "stop reading the shadow", "an idle session", "unused imports".
HP_ZF_NEG='zero|no|none|nothing|nobody|never|not|without|0|hasnt|hadnt|havent|didnt|doesnt|dont|isnt|arent|wasnt|werent|wont|stops?|stopped|ceases?|ceased'
HP_ZF_ACT='fires?|fired|firing|hits?|triggers?|triggered|triggering|deny|denies|denied|denials?|invocations?|invoked?|invokes|invoking|activations?|activated|blocks?|blocked|blocking|matches|matched|catches|caught|alerts?|alerted|warns?|warned|warnings?|used'
HP_ZF_IDLE='unused|idle|silent|quiet|inactive'

hp_zero_fires() {  # <retire-when text>; exit 0 when it rests on zero fires
  local t
  # Apostrophes go, straight and typographic, so "hasn't" and "hasn’t" both read "hasnt".
  # shellcheck disable=SC1112  # the ’ is the character being deleted, not a quote
  t=$(printf '%s' "$1" | tr 'A-Z' 'a-z' | sed -e "s/'//g" -e 's/’//g')
  grep -qE "(^|[^a-z0-9])($HP_ZF_NEG)(-|([ ]+[a-z0-9#./_-]+){0,2}[ ]+)($HP_ZF_ACT)([^a-z]|$)" <<< "$t" && return 0
  grep -qE "(^|[^a-z])($HP_ZF_ACT)([ -]+(count|counts|rate|total|number))?[ :=]+((is|are|was|were|stays?|stayed|remains?|remained|drops?|dropped|falls?|fell|reach|reaches|reached)[ ]+)?((at|to|of)[ ]+)?(0|zero|none|nil)([^0-9a-z.]|$)" <<< "$t" && return 0
  grep -qE "(^|[^a-z])last[ -]+($HP_ZF_ACT|fire|seen)([^a-z]|$)" <<< "$t" && return 0
  grep -qE "(^|[^a-z])($HP_ZF_IDLE)([ -]+(for|in|over|across|since|during|throughout|log|logs|ledger|period|window)([^a-z]|$)|[ ]*([,;.]|$))" <<< "$t" && return 0
  grep -qE "(^|[^a-z])(goes|go|went|gone|stays?|stayed|falls?|fell|fallen|remains?|remained|is|are|was|were|been|be|sits?|sat)[ -]+($HP_ZF_IDLE)([^a-z]|$)" <<< "$t" && return 0
  grep -qE "(^|[^a-z])(untriggered|unfired)([^a-z]|$)" <<< "$t"
}

hp_problems() {  # <hooks dir> <settings-hooks.json>
  local dir="$1" settings="$2" f name n line ef rw tok checked=0 wired w
  for f in "$dir"/*.sh; do
    [[ -f "$f" ]] || continue
    checked=$((checked + 1)); name=$(basename "$f")
    n=$(grep -c '^# exists-for: ' "$f")
    if [[ "$n" != 1 ]]; then echo "$name: ${n:-no} exists-for lines, want exactly 1"; continue; fi
    line=$(head -n 10 "$f" | grep '^# exists-for: ')
    if [[ -z "$line" ]]; then echo "$name: the exists-for line is not within the first 10 lines"; continue; fi
    case "$line" in
      *"$HP_SEP"*"$HP_SEP"*) echo "$name: more than one retire-when clause"; continue ;;
      *"$HP_SEP"*) ;;
      *) echo "$name: no '$HP_SEP' clause after exists-for"; continue ;;
    esac
    ef=${line#"# exists-for: "}; ef=${ef%%"$HP_SEP"*}
    rw=${line#*"$HP_SEP"}
    if grep -qE "$HP_PLACEHOLDER" <<< "$line"; then
      echo "$name: a template placeholder is still in the line"; continue
    fi
    [[ ${#ef} -ge 20 ]] || { echo "$name: exists-for is too short to say anything"; continue; }
    [[ ${#rw} -ge 15 ]] || { echo "$name: retire-when is too short to be a condition"; continue; }
    grep -qE '(^|[^0-9])20[0-9]{2}-[01][0-9]-[0-3][0-9]([^0-9]|$)' <<< "$ef" \
      || { echo "$name: exists-for names no YYYY-MM-DD date"; continue; }
    local shas
    shas=$(grep -oE '[0-9A-Za-z_]+' <<< "$ef" | grep -xE '[0-9a-f]{7,40}')
    if [[ -z "$shas" ]] && ! grep -qE '#[0-9]+' <<< "$ef"; then
      echo "$name: exists-for names no commit sha or #PR"; continue
    fi
    if [[ "$HP_RESOLVE" == 1 ]]; then
      for tok in $shas; do
        git -C "$REPO_ROOT" cat-file -e "${tok}^{commit}" 2>/dev/null \
          || echo "$name: $tok does not resolve to a commit"
      done
    fi
    if hp_zero_fires "$rw" && ! grep -qi 'ablation' <<< "$rw"; then
      echo "$name: retire-when rests on zero fires without an ablation"
    fi
  done
  [[ "$checked" -gt 0 ]] || echo "no hook files under $dir: nothing was checked"
  wired=$(jq -r '.. | .command? // empty' "$settings" 2>/dev/null \
            | grep -oE 'hooks/[A-Za-z0-9_.-]+\.sh' | sed 's#^hooks/##' | sort -u)
  [[ -n "$wired" ]] || echo "no hook is wired in $settings: the cross-check has nothing to anchor on"
  for w in $wired; do
    [[ -f "$dir/$w" ]] || echo "$w: wired in settings-hooks.json but not checked"
  done
}

HP_N=$(ls "$REPO_ROOT"/configs/hooks/*.sh 2>/dev/null | wc -l | tr -d ' ')
HP_WIRED=$(jq -r '.. | .command? // empty' "$SETTINGS" | grep -oE 'hooks/[A-Za-z0-9_.-]+\.sh' | sort -u | wc -l | tr -d ' ')
HP_OUT=$(hp_problems "$REPO_ROOT/configs/hooks" "$SETTINGS")
if [[ -z "$HP_OUT" ]]; then
  pass "all $HP_N hooks carry one well-formed exists-for/retire-when line ($HP_WIRED wired in settings-hooks.json, all checked)"
else
  fail "every hook carries one well-formed exists-for/retire-when line" \
       "$(printf '%s' "$HP_OUT" | head -8 | tr '\n' ';')"
  [[ "$VERBOSE" == "-v" ]] && printf '    %s\n' "$HP_OUT"
fi
if [[ "$HP_RESOLVE" == 1 ]]; then
  pass "every cited sha resolves to a commit in this repository"
else
  echo -e "  ${YELLOW}–${NC} sha resolution skipped: shallow clone or no git history (format still checked)"
fi

# ─── mutations ───────────────────────────────────────────────────────
#
# Each changes one copy of the hooks dir so that exactly one guard above should
# object, and requires the output to name the problem. A mutation that leaves
# the file unchanged proves nothing, so that fails too.
section "hooks — mutations that must turn the provenance check red"

HP_MUT="$TMP_ROOT/hp-mut"
HP_VICTIM="pre-tool-guardian.sh"      # a preventive guard: the case that matters
hp_copy() { rm -rf "$HP_MUT"; mkdir -p "$HP_MUT"; cp "$REPO_ROOT"/configs/hooks/*.sh "$HP_MUT/"; }
hp_rewrite() {  # <awk program> [awk -v assignment] — applied to the victim in the copy
  if [[ -n "${2:-}" ]]; then awk -v "$2" "$1" "$REPO_ROOT/configs/hooks/$HP_VICTIM" > "$HP_MUT/$HP_VICTIM"
  else awk "$1" "$REPO_ROOT/configs/hooks/$HP_VICTIM" > "$HP_MUT/$HP_VICTIM"; fi
}
hp_expect_red() {  # <label> <text the output must contain> [settings]
  local out
  if cmp -s "$HP_MUT/$HP_VICTIM" "$REPO_ROOT/configs/hooks/$HP_VICTIM" && [[ -f "$HP_MUT/$HP_VICTIM" ]] && [[ -z "${3:-}" ]]; then
    fail "mutation: $1" "the mutation did not change $HP_VICTIM, so it tests nothing"; return
  fi
  out=$(hp_problems "$HP_MUT" "${3:-$SETTINGS}")
  if grep -qF "$2" <<< "$out"; then pass "mutation: $1 → red"
  else fail "mutation: $1 → red" "checker stayed green on it: [$(printf '%s' "$out" | head -3 | tr '\n' ';')]"; fi
}

hp_copy
HP_CTRL=$(hp_problems "$HP_MUT" "$SETTINGS")
if [[ -z "$HP_CTRL" ]]; then pass "control: an unchanged copy of the hooks dir stays green"
else fail "control: an unchanged copy of the hooks dir stays green" "$(printf '%s' "$HP_CTRL" | head -3 | tr '\n' ';')"; fi

hp_copy; grep -v '^# exists-for: ' "$REPO_ROOT/configs/hooks/$HP_VICTIM" > "$HP_MUT/$HP_VICTIM"
hp_expect_red "strip the header from $HP_VICTIM" "$HP_VICTIM: 0 exists-for lines"

hp_copy; hp_rewrite '{ print } /^# exists-for: / { print }'
hp_expect_red "duplicate the header" "$HP_VICTIM: 2 exists-for lines"

hp_copy; hp_rewrite '/^# exists-for: / { held = $0; next } { print } NR == 12 { print held }'
hp_expect_red "move the header below line 10" "not within the first 10 lines"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print substr($0, 1, i - 1) " - retire-when: " substr($0, i + length(" · retire-when: ")); next } { print }'
hp_expect_red "break the retire-when separator" "no '$HP_SEP' clause"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print "# exists-for: an incident nobody wrote down" substr($0, i); next } { print }'
hp_expect_red "drop the date and the commit from exists-for" "names no YYYY-MM-DD date"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print "# exists-for: an incident nobody wrote down, 2026-01-01" substr($0, i); next } { print }'
hp_expect_red "drop only the commit from exists-for" "names no commit sha or #PR"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print substr($0, 1, i - 1) " · retire-when: zero fires in 60 days"; next } { print }'
hp_expect_red "retire a preventive guard on zero fires" "rests on zero fires without an ablation"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print "# exists-for: 2026-01-01 #1" substr($0, i); next } { print }'
hp_expect_red "shrink exists-for to a bare date and number" "exists-for is too short"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print substr($0, 1, i - 1) " · retire-when: later"; next } { print }'
hp_expect_red "shrink retire-when to one word" "retire-when is too short"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print substr($0, 1, i - 1) " · retire-when: <condition>"; next } { print }'
hp_expect_red "leave the <condition> placeholder in" "template placeholder"

# The /generate-hook template's own line, read from the skill rather than
# retyped here, so a template edit cannot leave the check behind. The two
# partial fills below passed every other guard before `{…}` was refused.
HP_TEMPLATE_LINE=$(grep -m1 '^# exists-for: ' "$GEN_HOOK_PROMPT")
if [[ -z "$HP_TEMPLATE_LINE" ]]; then
  fail "the /generate-hook template emits an exists-for line" "no '# exists-for: ' line in $GEN_HOOK_PROMPT"
else
  hp_copy; hp_rewrite '/^# exists-for: / { print tpl; next } { print }' "tpl=$HP_TEMPLATE_LINE"
  hp_expect_red "paste the /generate-hook template line unfilled" "template placeholder"
fi

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print substr($0, 1, i - 1) " · retire-when: {the condition under which this hook may go}"; next } { print }'
hp_expect_red "fill exists-for but leave the {…} retire-when" "template placeholder"

hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print "# exists-for: {the incident the rule records}, 2026-02-23, e434b46" substr($0, i); next } { print }'
hp_expect_red "fill the date and sha but leave the {…} incident" "template placeholder"

if [[ "$HP_RESOLVE" == 1 ]]; then
  hp_copy; hp_rewrite '/^# exists-for: / { i = index($0, " · retire-when: "); print "# exists-for: no incident recorded (added 2026-02-23 in 0000000)" substr($0, i); next } { print }'
  hp_expect_red "cite a commit that does not exist" "0000000 does not resolve to a commit"
fi

hp_copy; rm -f "$HP_MUT"/*.sh
hp_expect_red "an empty hooks dir (the vacuous pass)" "nothing was checked"
hp_expect_red "an empty hooks dir leaves every wired hook unchecked" "wired in settings-hooks.json but not checked"

hp_copy; printf '{}\n' > "$TMP_ROOT/hp-empty-settings.json"
hp_expect_red "settings with no wiring to anchor the count" "nothing to anchor on" "$TMP_ROOT/hp-empty-settings.json"

# ─── retire-when wordings ────────────────────────────────────────────
#
# Each row replaces the victim's retire-when and runs the whole checker on a
# one-hook dir wired by a one-hook settings file, so the verdict comes through
# hp_problems, not through hp_zero_fires alone. `red` rows must be refused as
# zero fires; `green` rows must pass the checker entirely. Every row is at least
# 15 characters, so the length guard never decides one.
section "hooks — retire-when wordings: zero fires refused, near-misses allowed"

HP_ONE="$TMP_ROOT/hp-one"; mkdir -p "$HP_ONE"
HP_ONE_SETTINGS="$TMP_ROOT/hp-one-settings.json"
printf '{"hooks":{"PreToolUse":[{"hooks":[{"type":"command","command":"bash ~/.claude/hooks/%s"}]}]}}\n' \
  "$HP_VICTIM" > "$HP_ONE_SETTINGS"
HP_RED=0; HP_GREEN=0
while IFS='|' read -r want rw; do
  [[ -n "$want" ]] || continue
  awk -v rw="$rw" '/^# exists-for: / { i = index($0, " · retire-when: "); print substr($0, 1, i - 1) " · retire-when: " rw; next } { print }' \
    "$REPO_ROOT/configs/hooks/$HP_VICTIM" > "$HP_ONE/$HP_VICTIM"
  out=$(hp_problems "$HP_ONE" "$HP_ONE_SETTINGS")
  if [[ "$want" == red ]]; then
    HP_RED=$((HP_RED + 1))
    if grep -qF "rests on zero fires without an ablation" <<< "$out"; then pass "refused as zero fires: \"$rw\""
    else fail "refused as zero fires: \"$rw\"" "checker said: [$(printf '%s' "$out" | head -2 | tr '\n' ';')]"; fi
  else
    HP_GREEN=$((HP_GREEN + 1))
    if [[ -z "$out" ]]; then pass "allowed: \"$rw\""
    else fail "allowed: \"$rw\"" "checker said: [$(printf '%s' "$out" | head -2 | tr '\n' ';')]"; fi
  fi
done <<'EOF'
red|zero fires in 60 days
red|it has not fired in 90 days
red|it hasn't fired since the last release
red|not once fired in a quarter
red|no denials in 60 days of harness-usage.py
red|no recorded denials over a quarter
red|it was never triggered in 60 days
red|0 hits in 60 days of transcripts
red|it stops firing for a quarter
red|harness-usage.py shows no invocations in 60 days
red|it never blocks a command in 90 days
red|fires 0 times over 60 days
red|its fire count stays at zero for a quarter
red|it last fired more than 60 days ago
red|last-fired is older than 60 days
red|unused for 90 days
red|it sits unused across a release cycle
red|it is unused by every session in a quarter
red|a quiet log for 60 days
red|it goes silent for a quarter
red|harness-usage.py reports it untriggered
red|zero fires in 60 days, flagged for owner review
green|zero fires in 60 days and an ablation shows no harm without it
green|no install sets TG_BOT_TOKEN and TG_CHAT_ID, or Claude Code's own notifications reach the phone
green|stop-check.sh retires; it is the only reader of the baseline
green|routes/tasks.py stops writing worker inboxes
green|orchestrator/worker.py stops writing .claude/context-warning-<task>.md
green|both hooks stop reading the shadow (lib/correction-pair.sh)
green|radar no longer read its records, or the correction channel is retired
green|its systemMessage reaches nobody (Intentional No-ops), so retire it
green|Claude Code wakes an idle session itself
green|ruff removes unused imports itself, so the hint adds nothing
green|the native loader covers the reads and writes it catches
green|no runner sets ${CLADE_WORKER_SHADOW_DIR} any more
EOF
if [[ "$HP_RED" -gt 0 && "$HP_GREEN" -gt 0 ]]; then
  pass "the wording table ran $HP_RED zero-fires rows and $HP_GREEN near-miss rows"
else
  fail "the wording table ran rows of both kinds" "red=$HP_RED green=$HP_GREEN"
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
