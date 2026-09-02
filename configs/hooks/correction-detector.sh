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

# Prompts starting with markup are harness-injected (<task-notification>) or
# pasted HTML dumps — not user corrections; they pollute the rule pipeline
if [[ "$PROMPT" == \<* ]]; then
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

# ─── Redact secrets BEFORE any disk write ─────────────────────────────
# Everything below persists the prompt: history.jsonl and, further down,
# cross-project-rules.jsonl. On installs where ~/.claude/corrections is a
# symlink into a shared mount those files are group-readable at 0664, so a
# credential pasted into a correction ("no, that's wrong, the key is …") used
# to land there verbatim and stay. The MODEL still sees the prompt unmasked —
# it is the user's own message, already in the transcript — only the persisted
# copy is masked.
#
# Placed AFTER the correction gate on purpose: this is a sync UserPromptSubmit
# hook, and spawning python3 on every prompt (~31ms) would tax the common path
# that exits above without writing anything.
#
# Redact THEN bound (cp_bound_prompt runs later, on PROMPT_SAFE): clipping
# first can cut a token below its length threshold — `sk-` plus 15 of 20
# required chars stops matching — and persist a partial credential.
#
# The helpers live here rather than in lib/correction-pair.sh so a missing or
# stale lib cannot silently restore the unmasked write path.

# Fallback DETECTION ERE (POSIX, no \b — mirrors configs/scripts/checks.sh
# SECRET_ERE plus the sk-/sk_ shapes redact.py knows). Open-ended {N,} counts
# so a longer token still matches. Used only when python3 or redact.py is
# unavailable.
CD_SECRET_ERE='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16,}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}|sk-ant-[A-Za-z0-9_-]{40,}|sk-(proj-)?[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35,}|xox[baprs]-[A-Za-z0-9-]{10,}|(sk|rk|ak)_[A-Za-z0-9]{32,}'

# Sibling copy first. The same relative path resolves in BOTH layouts:
# in-repo configs/hooks/../scripts, installed ~/.claude/hooks/../scripts.
_cd_redact_py() {
  local sib
  sib="$(cd "$(dirname "$0")/../scripts" 2>/dev/null && pwd)"
  if [[ -n "$sib" && -f "$sib/redact.py" ]]; then
    printf '%s' "$sib/redact.py"
  elif [[ -f "$HOME/.claude/scripts/redact.py" ]]; then
    printf '%s' "$HOME/.claude/scripts/redact.py"
  fi
}

# _cd_redact_prompt <text> — echo text with credentials masked. Never fails
# open: a redact.py that raises on import (a malformed pattern does) exits
# non-zero, so control falls through to the degraded path below rather than
# returning the raw text.
_cd_redact_prompt() {
  local text="$1" py masked rc
  py="$(_cd_redact_py)"
  if [[ -n "$py" ]] && command -v python3 >/dev/null 2>&1; then
    if masked=$(printf '%s' "$text" | python3 "$py" 2>/dev/null); then
      printf '%s' "$masked"
      return 0
    fi
  fi
  # Degraded path: DETECT and withhold, never substitute. A sed replacement
  # with these patterns would mask only the matched prefix and leave the rest
  # of the token on disk — `sk_` + 48 hex loses 32 chars and keeps 16 — and a
  # partial credential is still a credential. It also cannot reach a PEM body,
  # which sed sees one line at a time. Dropping the text of one correction is
  # cheaper than persisting any part of a key.
  printf '%s' "$text" | grep -qE -e "$CD_SECRET_ERE" 2>/dev/null
  rc=$?
  if [[ $rc -eq 0 ]]; then
    printf '[prompt withheld: secret detected, redactor unavailable]'
  elif [[ $rc -ge 2 ]]; then
    printf '[prompt withheld: redactor unavailable]'   # grep itself errored
  else
    printf '%s' "$text"
  fi
}

PROMPT_SAFE="$(_cd_redact_prompt "$PROMPT")"
# Fail closed. If the redactor produced nothing at all, the record keeps its
# timestamp/project/type (the counting signal) but no text — never the raw
# prompt, which is exactly the leak this block exists to stop.
[[ -z "$PROMPT_SAFE" ]] && PROMPT_SAFE="[prompt withheld: redactor unavailable]"

# Log to correction history
CORRECTIONS_DIR="$HOME/.claude/corrections"
mkdir -p "$CORRECTIONS_DIR"

HISTORY_FILE="$CORRECTIONS_DIR/history.jsonl"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
PROJECT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Sourced here rather than at first use further down: this append needs the
# atomic-write helper, and an unlocked >> of an oversized record is what
# truncated the history for every reader.
source "$LIBDIR/correction-pair.sh" 2>/dev/null || true

if declare -f cp_append_history >/dev/null 2>&1; then
  cp_append_history "$HISTORY_FILE" \
    --arg ts "$TIMESTAMP" \
    --arg prompt "$(cp_bound_prompt "$PROMPT_SAFE")" \
    --arg project "$PROJECT" \
    --arg type "explicit" \
    '{timestamp: $ts, prompt: $prompt, project: $project, type: $type}'
else
  jq -nc \
    --arg ts "$TIMESTAMP" \
    --arg prompt "$PROMPT_SAFE" \
    --arg project "$PROJECT" \
    --arg type "explicit" \
    '{timestamp: $ts, prompt: $prompt, project: $project, type: $type}' >> "$HISTORY_FILE"
fi

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
   Defect classes (what is wrong with the code):
   - settings-disconnect: defined but not wired/called/loaded
   - edge-case: untested input, OS, or state (empty, first-run, null)
   - async-race: stale closure, TOCTOU, zombie process, missing lock
   - security: unsanitized input, leaked secrets, missing auth
   - deploy-gap: source ≠ deployed, config ≠ loaded, defined ≠ called
   Collaboration classes (what broke between you and the developer):
   - inaccurate-self-reporting: claimed done/passing/verified from partial or
     unchecked evidence — a truncated log, a suite not run, an unread output
   - constraint-violation: ignored an instruction that was actually given —
     asked to confirm first, to stay in scope, to not touch something
   - premature-action: acted before gathering enough project state
   - scope-overreach: turned a bounded request into a broader intervention
3. Append a rule to $RULES_PATH in this format:
   - [YYYY-MM-DD] <domain> (<root-cause>): <do this> instead of <not this>
   Example: - [2026-02-25] imports (settings-disconnect): Use @/ path aliases and verify tsconfig paths are set — not bare relative paths that break on move
4. In one sentence: how could you have caught this BEFORE the user pointed it out? (e.g., 'I should have checked cross-platform compat when using shell builtins')
5. Keep rules.md under $RULES_LIMIT RULE lines — retire the least useful rules
   when over. The header block at the top of the file (the format spec and the
   root-cause list) is NOT a rule and does NOT count toward the limit — never
   delete it. It was trimmed away once, and it is the only in-file statement of
   the format that auto-audit.sh requires before it will promote anything."

# ─── Concrete signal: the actual change that was rejected (the labeled pair) ──
# Gate: we only reach here on an EXPLICIT correction. Silent reverts/edits stay
# data-only in their async hooks; here we ground the rule in the real files behind
# "that's wrong" (from revert-detector's reverted_files + the edit-shadow log),
# not only the user's words. Empty → nothing appended (no noise).
source "$LIBDIR/correction-pair.sh" 2>/dev/null || true
if command -v jq &>/dev/null; then
  _recent_files=""
  declare -f cp_recent_files >/dev/null 2>&1 && _recent_files=$(cp_recent_files "$(cp_session_key "$INPUT")" 8)
  _reverted=""
  [[ -f "$HISTORY_FILE" ]] && _reverted=$(tail -n 200 "$HISTORY_FILE" 2>/dev/null \
    | jq -r --arg proj "$PROJECT" 'select(.type=="implicit-revert" and .project==$proj) | (.reverted_files // [])[], (.session_files // [])[]' 2>/dev/null)
  _combined=$(printf '%s\n%s\n' "$_reverted" "$_recent_files" | awk 'NF' | sort -u | head -10)
  if [[ -n "$_combined" ]]; then
    _bullets=$(while IFS= read -r _p; do [[ -n "$_p" ]] && printf '  - %s\n' "$_p"; done <<< "$_combined")
    CONTEXT="${CONTEXT}

Concrete signal — files behind this correction (base the rule on the real diff, not only the words):
${_bullets}Inspect what was rejected with: git diff -- <file> (or git log -p -1 -- <file>). The lesson is the (what-Claude-did → what's-correct) delta on these files."
  fi
fi

# Write cross-project marker for auto-audit aggregation
if [[ -n "$CROSS_FILE" ]] && command -v jq &>/dev/null; then
  RULE_TEXT_PREVIEW=$(echo "$PROMPT_SAFE" | head -c 120)
  CROSS_HASH=$(echo -n "${DOMAIN}:${RULE_TEXT_PREVIEW}" | { command -v sha256sum >/dev/null 2>&1 && sha256sum || shasum -a 256; } 2>/dev/null | cut -c1-8)
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
