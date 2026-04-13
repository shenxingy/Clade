#!/usr/bin/env bash
# correction-detector.sh — Detect user corrections and build a learning history
# Triggered by UserPromptSubmit
# Reads JSON from stdin: {"prompt": "user's message", ...}
# If a correction is detected, logs it, updates stats.json, and reminds Claude to extract rules.

LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')

if [[ -z "$PROMPT" ]]; then
  exit 0
fi

# Correction patterns (Chinese + English)
# Matches: don't/别用/不要/错了/改回/wrong/revert/undo/actually...instead/should have/应该
PATTERNS=(
  '不要|别用|错了|改回|不对|别这样|重新|撤回|应该'
  '(^|[^a-zA-Z])(wrong|revert|undo|rollback|actually|instead|should have|shouldn'\''t have|go back|put back|change back|not what I)($|[^a-zA-Z])'
  '(^|[^a-zA-Z])(no,? *(use|do|make|try|put))($|[^a-zA-Z])'
)

MATCHED=false
for pattern in "${PATTERNS[@]}"; do
  if echo "$PROMPT" | grep -qiE "$pattern" 2>/dev/null; then
    MATCHED=true
    break
  fi
done

if ! $MATCHED; then
  exit 0
fi

# Log to correction history
CORRECTIONS_DIR="$HOME/.claude/corrections"
mkdir -p "$CORRECTIONS_DIR"

HISTORY_FILE="$CORRECTIONS_DIR/history.jsonl"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PROJECT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

jq -n \
  --arg ts "$TIMESTAMP" \
  --arg prompt "$PROMPT" \
  --arg project "$PROJECT" \
  --arg type "explicit" \
  '{timestamp: $ts, prompt: $prompt, project: $project, type: $type}' >> "$HISTORY_FILE"

# ─── Auto-increment domain stats ──────────────────────────────────────
STATS_FILE="$CORRECTIONS_DIR/stats.json"
# Initialize stats.json on first run
if [[ ! -f "$STATS_FILE" ]] && command -v jq &>/dev/null; then
  echo '{"frontend":0,"backend":0,"schema":0,"ml":0,"ios":0,"android":0,"systems":0,"academic":0,"unknown":0}' > "$STATS_FILE"
fi
if [[ -f "$STATS_FILE" ]] && command -v jq &>/dev/null; then
  # Detect domain from recent changes in this project (avoid subshell so DOMAIN is set in parent)
  if [[ -d "$PROJECT" ]]; then
    source "$LIBDIR/domain-detect.sh" 2>/dev/null
    pushd "$PROJECT" >/dev/null 2>&1 && detect_domain 2>/dev/null; popd >/dev/null 2>&1
  fi
  DOMAIN="${DOMAIN:-unknown}"
  # Atomically increment the counter for this domain
  TMP_STATS=$(mktemp)
  jq --arg d "$DOMAIN" '.[$d] = ((.[$d] // 0) + 1)' "$STATS_FILE" > "$TMP_STATS" 2>/dev/null \
    && mv "$TMP_STATS" "$STATS_FILE" \
    || rm -f "$TMP_STATS"
fi

# Determine target rules.md: project-local if in a real project, else global
RULES_PATH="$HOME/.claude/corrections/rules.md"
RULES_LIMIT=50
if [[ "$PROJECT" != "$HOME" ]] && [[ -f "$PROJECT/CLAUDE.md" || -d "$PROJECT/.git" ]]; then
  RULES_PATH="$PROJECT/.claude/corrections/rules.md"
  RULES_LIMIT=100
fi

# ─── Effectiveness tracking: check if existing rules should have prevented this ───
source "$LIBDIR/rule-effectiveness.sh" 2>/dev/null || true
source "$LIBDIR/rule-utils.sh" 2>/dev/null || true

# Check if a rule already exists for this domain → rule miss (only the best match)
# Only record one miss per correction to avoid inflating miss rates for busy domains
_BEST_MATCH_HASH=""
_BEST_MATCH_SCORE=0
for rf in "$HOME/.claude/corrections/rules.md" "$PROJECT/.claude/corrections/rules.md"; do
  [[ -f "$rf" ]] || continue
  parse_rules "$rf" 2>/dev/null || continue
  for (( _i=0; _i<${#RULE_DOMAINS[@]}; _i++ )); do
    if [[ "${RULE_DOMAINS[$_i]}" == "$DOMAIN" ]]; then
      # Score: count overlapping words between rule text and correction prompt
      _rule_words=$(echo "${RULE_TEXTS[$_i]}" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alpha:]' '\n' | sort -u)
      _prompt_words=$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]' | tr -cs '[:alpha:]' '\n' | sort -u)
      _overlap=$(comm -12 <(echo "$_rule_words") <(echo "$_prompt_words") 2>/dev/null | wc -l | tr -d ' ')
      if [[ "${_overlap:-0}" -gt "$_BEST_MATCH_SCORE" ]]; then
        _BEST_MATCH_SCORE="$_overlap"
        _BEST_MATCH_HASH=$(rule_hash "${RULE_TEXTS[$_i]}" 2>/dev/null)
      fi
    fi
  done
done
[[ -n "$_BEST_MATCH_HASH" ]] && record_rule_miss "$_BEST_MATCH_HASH" 2>/dev/null

# ─── Cross-project rule tracking ──────────────────────────────────────
# Log to cross-project-rules.jsonl so auto-audit can detect multi-project patterns
CROSS_FILE="$HOME/.claude/corrections/cross-project-rules.jsonl"

# Remind Claude to extract a rule with root-cause analysis
CONTEXT="A user correction was detected in the prompt above. After addressing the user's request:
1. Extract the lesson (what was wrong, what's correct)
2. Identify the root cause — which category does this fall into?
   - settings-disconnect: defined but not wired/called/loaded
   - edge-case: untested input, OS, or state (empty, first-run, null)
   - async-race: stale closure, TOCTOU, zombie process, missing lock
   - security: unsanitized input, leaked secrets, missing auth
   - deploy-gap: source ≠ deployed, config ≠ loaded, defined ≠ called
3. Append a rule to $RULES_PATH in this format:
   - [YYYY-MM-DD] <domain> (<root-cause>): <do this> instead of <not this>
   Example: - [2026-02-25] imports (settings-disconnect): Use @/ path aliases and verify tsconfig paths are set — not bare relative paths that break on move
4. In one sentence: how could you have caught this BEFORE the user pointed it out? (e.g., 'I should have checked cross-platform compat when using shell builtins')
5. Keep rules.md under $RULES_LIMIT lines — remove outdated rules if needed"

# Write cross-project marker for auto-audit aggregation
if [[ -n "$CROSS_FILE" ]] && command -v jq &>/dev/null; then
  RULE_TEXT_PREVIEW=$(echo "$PROMPT" | head -c 120)
  CROSS_HASH=$(echo -n "${DOMAIN}:${RULE_TEXT_PREVIEW}" | shasum -a 256 2>/dev/null | cut -c1-8)
  jq -nc \
    --arg ts "$TIMESTAMP" \
    --arg domain "$DOMAIN" \
    --arg text "$RULE_TEXT_PREVIEW" \
    --arg project "$PROJECT" \
    --arg hash "$CROSS_HASH" \
    '{timestamp:$ts, domain:$domain, rule_text:$text, project:$project, rule_hash:$hash}' >> "$CROSS_FILE" 2>/dev/null
fi

jq -n --arg ctx "$CONTEXT" \
  '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'

exit 0
