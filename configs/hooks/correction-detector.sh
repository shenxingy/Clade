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

jq -n --arg ctx "$CONTEXT" \
  '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":$ctx}}'

exit 0
