#!/usr/bin/env bash
# session-context.sh — Auto-load project context at session start
# Triggered by SessionStart

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# Cross-platform sha256 (Linux: sha256sum, macOS: shasum -a 256)
if command -v sha256sum &>/dev/null; then
  _SHA256=(sha256sum)
else
  _SHA256=(shasum -a 256)
fi

# Cross-platform timeout. macOS ships no coreutils `timeout` (gtimeout via brew).
# With NEITHER, SKIP the probe rather than run it unbounded: this is a sync
# SessionStart hook, and an unbounded `gh api` on a dead network would block the
# session start. A missing fingerprint field is the cheaper failure.
# (Commit 2a6b32e's message claimed a timeout fallback in this file; its diff
# only ever added the _SHA256 array above.)
_timeout() {
  if command -v timeout >/dev/null 2>&1; then timeout "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$@"
  else return 0; fi
}

# ─── Context budget ──────────────────────────────────────────────────
# Measured 2026-09-02: a real SessionStart injection was 24,057 chars, 82.7% of
# it the correction-rules block — ~6k tokens before the first user message.
# The 20KB skill catalog deleted in 8406ed4 pushed total hook output past the
# harness inline limit (30.8KB observed) and the WHOLE additionalContext was
# silently persisted to a file instead of entering context. Nothing has measured
# this since, and rules.md grows on every /audit run.
CTX_RULES_BUDGET="${CLADE_RULES_BUDGET_BYTES:-4000}"
CTX_FILE_BUDGET="${CLADE_CTX_FILE_BUDGET_BYTES:-3000}"
CTX_TOTAL_CEILING="${CLADE_CTX_CEILING_BYTES:-12000}"

# _capped_read <file> <budget> — echo at most <budget> bytes of <file>, with an
# explicit marker when the file was longer. Every input this hook injects used
# to be an unbounded `cat`.
_capped_read() {
  local f="$1" budget="$2" size
  head -c "$budget" "$f" 2>/dev/null
  size=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
  [[ "${size:-0}" -gt "$budget" ]] \
    && printf '\n… [truncated: %s of %s bytes shown]' "$budget" "$size"
}

# _rules_tail <file> <budget> — echo `__DROPPED__ <n>` followed by the newest
# WHOLE lines of <file> that fit in <budget> bytes. Whole lines, never a byte
# cut: one line is one self-contained rule, and a rule cut mid-sentence is
# worse than an absent one. Pure POSIX awk — no gawk 3-arg match(), no GNU-only
# flags.
#
# The count rides on stdout rather than a global because every caller reads this
# through `$(...)`, and a command substitution runs in a SUBSHELL — a global set
# inside it never reaches the caller. Use _rules_count/_rules_body to split.
_rules_tail() {
  local f="$1" budget="$2"
  [[ -f "$f" ]] || { printf '__DROPPED__ 0'; return 0; }
  awk -v b="$budget" '
    { n++; l[n] = $0; s[n] = length($0) + 1 }
    END {
      t = 0; start = n + 1
      for (i = n; i >= 1; i--) { if (t + s[i] > b) break; t += s[i]; start = i }
      print "__DROPPED__ " (start - 1)
      for (i = start; i <= n; i++) print l[i]
    }' "$f" 2>/dev/null
}

# _rules_count <_rules_tail output> — echo the dropped-line count (0 on garbage).
_rules_count() {
  local n
  n=$(printf '%s\n' "$1" | head -1 | awk '{print $2}')
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  printf '%s' "$n"
}

# _rules_body <_rules_tail output> — echo the kept rules, sentinel stripped.
_rules_body() { printf '%s' "$(printf '%s\n' "$1" | tail -n +2)"; }

# Only run for git repos
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
  exit 0
fi

CONTEXT=""

# ─── Auto-pull from remote ────────────────────────────────────────────
# Only pull if: tracking branch exists, working tree is clean, and remote has new commits
# Throttle fetch to once per 5 minutes to avoid slow session startup
TRACKING=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null)
if [[ -n "$TRACKING" ]]; then
  _FETCH_TS_FILE=".git/.last-session-fetch"
  _NOW=$(date +%s)
  _LAST_FETCH=$(cat "$_FETCH_TS_FILE" 2>/dev/null || echo 0)
  if [[ $(( _NOW - _LAST_FETCH )) -gt 300 ]]; then
    git fetch --quiet 2>/dev/null
    echo "$_NOW" > "$_FETCH_TS_FILE"
  fi
  BEHIND=$(git rev-list HEAD..@{u} --count 2>/dev/null)
  DIRTY=$(git status --short 2>/dev/null)

  if [[ "${BEHIND:-0}" -gt 0 ]]; then
    if [[ -z "$DIRTY" ]]; then
      PULL_OUT=$(git pull --ff-only 2>&1)
      CONTEXT="${CONTEXT}Auto-pulled ${BEHIND} new commit(s) from ${TRACKING}:\n${PULL_OUT}\n\n"
    else
      CONTEXT="${CONTEXT}WARNING: Remote has ${BEHIND} new commit(s) but working tree is dirty — skipped auto-pull. Consider pulling manually after stashing or committing.\n\n"
    fi
  fi
fi

# Recent commits
GIT_LOG=$(git log --oneline -5 2>/dev/null)
if [[ -n "$GIT_LOG" ]]; then
  CONTEXT="Recent commits:\n${GIT_LOG}\n\n"
fi

# Loop state (if active)
# loop-runner.sh writes JSON to .claude/loop-state.json (STATE_FILE at :113).
# This read three KEY=VALUE keys out of an extensionless ".claude/loop-state"
# that no writer has ever produced, so the banner was silently empty on every
# session start. Filename, format and key names were all wrong, and `converged`
# did not exist at all until the writer started publishing it.
if [[ -f ".claude/loop-state.json" ]]; then
  LOOP_LINE=$(python3 - <<'PYEOF' 2>/dev/null
import json, os, sys
try:
    s = json.load(open(".claude/loop-state.json"))
except Exception:
    sys.exit(0)
goal = os.path.basename(s.get("goal_file") or "") or "goal"
it = s.get("iteration", "?")
if s.get("converged"):
    print(f"Loop: \u2713 converged ({goal}, iter {it})")
else:
    reason = s.get("exit_reason")
    if reason:
        print(f"Loop: \u25a0 stopped: {reason} ({goal}, iter {it})")
    else:
        print(f"Loop: \u27f3 running ({goal}, iter {it})")
PYEOF
)
  [[ -n "$LOOP_LINE" ]] && CONTEXT="${CONTEXT}${LOOP_LINE}\n"
fi

# Next TODO item
# trim with sed, not bare xargs — xargs errors on unmatched quotes in TODO text
NEXT_TODO=$(grep -m1 "^\- \[ \]" TODO.md 2>/dev/null | sed 's/- \[ \] \*\*//' | sed 's/\*\*.*//' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
if [[ -n "$NEXT_TODO" ]]; then
  CONTEXT="${CONTEXT}\nNext TODO: ${NEXT_TODO}\n"
fi

# Uncommitted changes
GIT_STATUS=$(git status --short 2>/dev/null | head -15)
if [[ -n "$GIT_STATUS" ]]; then
  CONTEXT="${CONTEXT}Uncommitted changes:\n${GIT_STATUS}\n\n"
fi

# Current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [[ -n "$BRANCH" ]]; then
  CONTEXT="${CONTEXT}Branch: ${BRANCH}\n"
fi

# SSH server / host info
if [[ -n "$SSH_CONNECTION" ]]; then
  CLIENT_IP="${SSH_CONNECTION%% *}"
  if [[ -n "$CLIENT_IP" ]]; then
    CONTEXT="${CONTEXT}\nHost: ${HOSTNAME} (SSH from ${CLIENT_IP})\n"
  else
    CONTEXT="${CONTEXT}\nHost: ${HOSTNAME} (SSH)\n"
  fi
elif [[ -n "$HOSTNAME" ]]; then
  CONTEXT="${CONTEXT}\nHost: ${HOSTNAME} (local)\n"
fi

# ─── Environment Fingerprint ──────────────────────────────────────────
# Structured per-host facts that prevent wrong-context assumptions
# (e.g. "is Aries this machine?", "what's already running locally?").
# Cached for 1h since most checks are stable per session-day.
FP_CACHE_FILE="$HOME/.claude/.env-fingerprint"
FP_TTL=3600
_NOW=$(date +%s)
FP_MTIME=$(stat -c %Y "$FP_CACHE_FILE" 2>/dev/null || stat -f %m "$FP_CACHE_FILE" 2>/dev/null || echo 0)
if [[ $(( _NOW - FP_MTIME )) -gt $FP_TTL || ! -s "$FP_CACHE_FILE" ]]; then
  {
    # Tailscale IP (so the agent can match user-mentioned LAN IPs to this box)
    if command -v tailscale &>/dev/null; then
      TS_IP=$(_timeout 2 tailscale ip -4 2>/dev/null | head -1)
      [[ -n "$TS_IP" ]] && echo "Tailscale IP: $TS_IP"
    fi
    # Sibling projects on this host (so "the faker-100 brand" registers as local)
    if [[ -d "$HOME/projects" ]]; then
      SIBS=$(ls -d "$HOME/projects/"*/ 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
      [[ -n "$SIBS" ]] && echo "Sibling projects on this host: $SIBS"
    fi
    # Listening dev ports (so "localhost:3000" claims can be verified)
    if command -v ss &>/dev/null; then
      LISTENING=$(ss -tln 2>/dev/null | awk 'NR>1 {print $4}' | grep -oE ':[0-9]+$' | tr -d ':' | sort -un | grep -E '^(3000|3001|4000|5000|5173|5432|6379|8000|8080|8888|9000)$' | tr '\n' ' ' | sed 's/ $//')
      [[ -n "$LISTENING" ]] && echo "Listening dev ports: $LISTENING"
    fi
    # Auth identities (so the agent doesn't guess which account is active)
    if command -v gh &>/dev/null; then
      GH_USER=$(_timeout 2 gh api user --jq .login 2>/dev/null)
      [[ -n "$GH_USER" ]] && echo "gh auth: $GH_USER"
    fi
    if command -v gcloud &>/dev/null; then
      GCLOUD_ACCT=$(_timeout 2 gcloud config get-value account 2>/dev/null | grep -v '^(unset)$')
      [[ -n "$GCLOUD_ACCT" ]] && echo "gcloud: $GCLOUD_ACCT"
    fi
  } > "$FP_CACHE_FILE" 2>/dev/null
fi
if [[ -s "$FP_CACHE_FILE" ]]; then
  FP_CONTENT=$(_capped_read "$FP_CACHE_FILE" 1500)
  CONTEXT="${CONTEXT}\n## Environment Fingerprint (this host)\n${FP_CONTENT}\nIf the user names a machine, cross-reference Host:/Tailscale IP/sibling projects above before assuming it's remote.\n"
fi

# Project Profile (project-specific topology and verification commands)
PROJECT_PROFILE="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/PROJECT_PROFILE.md"
if [[ -f "$PROJECT_PROFILE" ]]; then
  PROFILE_CONTENT=$(_capped_read "$PROJECT_PROFILE" "$CTX_FILE_BUDGET")
  CONTEXT="${CONTEXT}\n## Project Profile\n${PROFILE_CONTENT}\n"
fi

# Running docker containers — filtered to current project only
if command -v docker &>/dev/null; then
  # Determine project slug: try docker compose name, fall back to dirname
  _PROJECT_SLUG=""
  if [[ -f "docker-compose.yml" || -f "docker-compose.yaml" || -f "compose.yml" || -f "compose.yaml" ]]; then
    _COMPOSE_NAME=$(docker compose config --format json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('name',''))" 2>/dev/null)
    if [[ -n "$_COMPOSE_NAME" ]]; then
      _PROJECT_SLUG="$_COMPOSE_NAME"
    fi
  fi
  # Fall back to normalized dirname (underscores → hyphens, lowercase)
  if [[ -z "$_PROJECT_SLUG" ]]; then
    _PROJECT_SLUG=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
  fi

  # Filter containers by project slug (name contains slug)
  DOCKER=$(docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null \
    | grep -i "$_PROJECT_SLUG" | head -8)
  if [[ -n "$DOCKER" ]]; then
    CONTEXT="${CONTEXT}\nRunning containers (${_PROJECT_SLUG}):\n${DOCKER}"
  fi
fi

# Auto-load latest handoff file (< 24h old)
HANDOFF_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude"
if [[ -d "$HANDOFF_DIR" ]]; then
  LATEST_HANDOFF=$(ls -t "$HANDOFF_DIR"/handoff-*.md 2>/dev/null | head -1)
  if [[ -n "$LATEST_HANDOFF" && -f "$LATEST_HANDOFF" ]]; then
    FILE_MTIME=$(stat -c %Y "$LATEST_HANDOFF" 2>/dev/null || stat -f %m "$LATEST_HANDOFF" 2>/dev/null || echo 0)
    NOW=$(date +%s)
    AGE_HOURS=$(( (NOW - FILE_MTIME) / 3600 ))
    if [[ $AGE_HOURS -lt 24 ]]; then
      HANDOFF_CONTENT=$(_capped_read "$LATEST_HANDOFF" "$CTX_FILE_BUDGET")
      CONTEXT="${CONTEXT}\n## Handoff from previous session (${AGE_HOURS}h ago)\n${HANDOFF_CONTENT}\n⚠️ IMPORTANT: Before doing anything else, run \`/pickup\` to restore the exact session state. Do NOT start new work until pickup completes.\n"
    fi
  fi
fi

# Auto-load compact-state (saved before context compaction, < 2h old)
COMPACT_STATE="${HANDOFF_DIR}/compact-state.md"
if [[ -f "$COMPACT_STATE" ]]; then
  CS_MTIME=$(stat -c %Y "$COMPACT_STATE" 2>/dev/null || stat -f %m "$COMPACT_STATE" 2>/dev/null || echo 0)
  CS_AGE_HOURS=$(( ($(date +%s) - CS_MTIME) / 3600 ))
  if [[ $CS_AGE_HOURS -lt 2 ]]; then
    COMPACT_CONTENT=$(_capped_read "$COMPACT_STATE" "$CTX_FILE_BUDGET")
    CONTEXT="${CONTEXT}\n## Compact State (context was compacted ${CS_AGE_HOURS}h ago — resume from here)\n${COMPACT_CONTENT}\n"
  fi
fi

# ─── Self-Improvement Pipeline ────────────────────────────────────────

HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load correction rules (global + project-local)
GLOBAL_RULES="$HOME/.claude/corrections/rules.md"
PROJECT_RULES="${CLAUDE_PROJECT_DIR:-.}/.claude/corrections/rules.md"
# BYTE-BUDGETED, not `tail -25`. Project rules get first claim on half the
# budget (they are the most specific); global rules take what remains. The
# dropped-line notice is what makes the tax visible instead of silent, and it
# points at the tool that fixes the cause — /audit archives rules 60+ days old.
COMBINED_RULES=""
RULES_DROPPED_TOTAL=0
if [[ -f "$PROJECT_RULES" && "$PROJECT_RULES" != "$GLOBAL_RULES" ]]; then
  _RAW=$(_rules_tail "$PROJECT_RULES" "$(( CTX_RULES_BUDGET / 2 ))")
  RULES_DROPPED_TOTAL=$(( RULES_DROPPED_TOTAL + $(_rules_count "$_RAW") ))
  _P=$(_rules_body "$_RAW")
  [[ -n "$_P" ]] && COMBINED_RULES="${_P}\n"
fi
if [[ -f "$GLOBAL_RULES" ]]; then
  _REMAIN=$(( CTX_RULES_BUDGET - ${#COMBINED_RULES} ))
  [[ $_REMAIN -lt 500 ]] && _REMAIN=500
  _RAW=$(_rules_tail "$GLOBAL_RULES" "$_REMAIN")
  RULES_DROPPED_TOTAL=$(( RULES_DROPPED_TOTAL + $(_rules_count "$_RAW") ))
  COMBINED_RULES="${COMBINED_RULES}$(_rules_body "$_RAW")"
fi
if [[ -n "$COMBINED_RULES" ]]; then
  CONTEXT="${CONTEXT}\nCorrection rules (learned from past feedback):\n${COMBINED_RULES}"
  if [[ $RULES_DROPPED_TOTAL -gt 0 ]]; then
    CONTEXT="${CONTEXT}\n(${RULES_DROPPED_TOTAL} older rules not shown — run /audit to promote or archive them.)"
  fi
  CONTEXT="${CONTEXT}\n"
fi

# Learning → Rule promotion (convert high-confidence learnings to rules)
if [[ -f "$HOOKS_DIR/learning-to-rule.sh" ]]; then
  source "$HOOKS_DIR/learning-to-rule.sh" 2>/dev/null
  run_learning_promotion "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null
  if [[ -n "${LEARNING_SUMMARY:-}" ]]; then
    CONTEXT="${CONTEXT}\n${LEARNING_SUMMARY}\n"
  fi
fi

# Auto-audit (promote mature rules, archive stale ones, cross-project aggregation)
# Global and project-local audits check their own .last-audit independently
if [[ -f "$HOOKS_DIR/auto-audit.sh" ]]; then
  source "$HOOKS_DIR/auto-audit.sh" 2>/dev/null

  # Global auto-audit (checks its own .last-audit internally)
  run_auto_audit "global" 2>/dev/null
  if [[ -n "${AUDIT_SUMMARY:-}" ]]; then
    CONTEXT="${CONTEXT}\n${AUDIT_SUMMARY}\n"
  fi

  # Project-local auto-audit (independent timing from global)
  AUDIT_SUMMARY=""
  if [[ -d "${CLAUDE_PROJECT_DIR:-.}/.claude/corrections" ]]; then
    run_auto_audit "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null
    if [[ -n "${AUDIT_SUMMARY:-}" ]]; then
      CONTEXT="${CONTEXT}\n${AUDIT_SUMMARY}\n"
    fi
  fi
else
  # Fallback: show nudge if auto-audit.sh not available
  LAST_AUDIT_FILE="$HOME/.claude/corrections/.last-audit"
  if [[ -f "$LAST_AUDIT_FILE" ]]; then
    AUDIT_MTIME=$(stat -c %Y "$LAST_AUDIT_FILE" 2>/dev/null || stat -f %m "$LAST_AUDIT_FILE" 2>/dev/null || echo 0)
    AUDIT_AGE_DAYS=$(( ($(date +%s) - AUDIT_MTIME) / 86400 ))
  else
    AUDIT_AGE_DAYS=999
  fi
  if [[ $AUDIT_AGE_DAYS -ge 7 ]]; then
    CONTEXT="${CONTEXT}\nAudit reminder: rules haven't been audited in ${AUDIT_AGE_DAYS}+ days. Run /audit.\n"
  fi
fi

# Contradiction detection
if [[ -f "$HOOKS_DIR/lib/contradiction-detect.sh" ]]; then
  source "$HOOKS_DIR/lib/contradiction-detect.sh" 2>/dev/null
  for rf in "$GLOBAL_RULES" "$PROJECT_RULES"; do
    [[ -f "$rf" ]] || continue
    detect_contradictions "$rf" 2>/dev/null
    if [[ ${#CONTRADICTIONS[@]} -gt 0 ]]; then
      CONTEXT="${CONTEXT}\n⚠ Contradicting rules detected:"
      for c in "${CONTRADICTIONS[@]}"; do
        CONTEXT="${CONTEXT}\n  - ${c}"
      done
      CONTEXT="${CONTEXT}\nRun /audit to resolve.\n"
    fi
  done
fi

# Language constraint
CONTEXT="${CONTEXT}\nIMPORTANT: Always respond in the same language the user writes in. If the user writes Chinese, respond in Chinese. If English, respond in English. NEVER respond in Korean under any circumstances.\n"

# Model selection guidance
# Named generations, not benchmark scores: the previous text quoted SWE-bench
# figures for Sonnet 4.6 / Opus 4.6 and was still injected into every session
# after the aliases moved to Opus 5 / Sonnet 5. The cost ratio below IS
# checkable — $3/$15 vs $5/$25 per MTok, i.e. 60% — so it stays; the scores
# do not, because no verified figure for the current generation was to hand.
CONTEXT="${CONTEXT}\nModel guide: Sonnet is the default for most coding and costs 60% of Opus per token. Switch to Opus for: large refactors (10+ files), deep architectural reasoning, or outputs >64K tokens. Use Haiku for sub-agents doing mechanical checks. If you detect the user is about to do a complex multi-file refactor on Sonnet, suggest: 'This task may benefit from Opus — run /model to switch.'\n"

# Close the loop principle
CONTEXT="${CONTEXT}\nClose the loop: After completing any task, run the relevant verify command (compile/test/lint) and show its output — don't claim success without evidence. When fixing X, also check if related Y and Z are affected.\n"

# Stale kit detection
KIT_SOURCE_FILE="$HOME/.claude/.kit-source-dir"
KIT_CHECKSUM_FILE="$HOME/.claude/.kit-checksum"
if [[ -f "$KIT_SOURCE_FILE" && -f "$KIT_CHECKSUM_FILE" ]]; then
  _KIT_DIR=$(cat "$KIT_SOURCE_FILE")
  if [[ -d "$_KIT_DIR/configs" ]]; then
    _CURRENT=$(find "$_KIT_DIR/configs" -type f | LC_ALL=C sort | xargs "${_SHA256[@]}" 2>/dev/null | "${_SHA256[@]}" | cut -d' ' -f1)
    _INSTALLED=$(cat "$KIT_CHECKSUM_FILE")
    if [[ "$_CURRENT" != "$_INSTALLED" ]]; then
      CONTEXT="${CONTEXT}\n⚠ STALE KIT: configs/ changed since last install.sh — run: cd $_KIT_DIR && ./install.sh\n"
    fi
  fi
fi

# Revert rate check
REVERT_COUNT=$(git log --oneline --since="7 days ago" --grep="^Revert" 2>/dev/null | wc -l | tr -d ' ')
TOTAL_COUNT=$(git log --oneline --since="7 days ago" 2>/dev/null | wc -l | tr -d ' ')
if [[ "${TOTAL_COUNT:-0}" -gt 10 && "${REVERT_COUNT:-0}" -gt 0 ]]; then
  REVERT_RATE=$(( REVERT_COUNT * 100 / TOTAL_COUNT ))
  if [[ "$REVERT_RATE" -gt 10 ]]; then
    CONTEXT="${CONTEXT}\n⚠ High revert rate this week: ${REVERT_COUNT}/${TOTAL_COUNT} commits (${REVERT_RATE}%)\n"
  fi
fi

# ─── Context-Aware Skill Routing ──────────────────────────────────────
# Detect project context and suggest the most relevant skills upfront
SKILL_ROUTE=""

# Blog/content project
if [[ -d "blog" || -d "posts" || -d "articles" ]]; then
  SKILL_ROUTE="${SKILL_ROUTE}Blog project: /blog-seo-check + /blog geo after writing, /review includes SEO+GEO audit\n"
fi

# Web project with publish URL (only if web framework detected)
if grep -qiE '## (Publish|Live|Site) URL' CLAUDE.md 2>/dev/null \
   && { [[ -f "package.json" ]] || [[ -f "vercel.json" ]] || [[ -f "netlify.toml" ]] || compgen -G "*.html" >/dev/null 2>&1; }; then
  SKILL_ROUTE="${SKILL_ROUTE}Published web site: /review includes full SEO + GEO audit\n"
fi

# Design system present (token sheet, skill-repo, or full spec)
if [[ -f ".design-system.md" || -f "design-system/SKILL.md" || -f "DESIGN.md" ]]; then
  SKILL_ROUTE="${SKILL_ROUTE}Design system detected: /frontend-design enforces its hard rules + review checklist for any UI work\n"
fi

# Auth/security code detected
if grep -rqlE '(jwt|oauth|bcrypt|argon2|@login_required|@requires_auth|passport\.)' . --include='*.py' --include='*.ts' --include='*.js' --include='*.go' --include='*.rs' --include='*.rb' 2>/dev/null | head -1 &>/dev/null; then
  SKILL_ROUTE="${SKILL_ROUTE}Auth code detected: /cso for security audit after auth changes\n"
fi

# Infrastructure / CI
if [[ -f "Dockerfile" || -f "docker-compose.yml" || -f "docker-compose.yaml" || -d ".github/workflows" || -f ".gitlab-ci.yml" ]]; then
  SKILL_ROUTE="${SKILL_ROUTE}CI/Docker: /verify after infra changes\n"
fi

# Mobile — iOS
if compgen -G "*.xcodeproj" >/dev/null 2>&1 || [[ -f "Podfile" ]]; then
  SKILL_ROUTE="${SKILL_ROUTE}Apple UI project: /frontend-design runs the platform-aware interface pipeline; run xcodebuild tests after Swift changes\n"
fi

# Mobile — Android
if [[ -f "build.gradle" || -f "build.gradle.kts" || -f "settings.gradle" || -f "settings.gradle.kts" ]]; then
  SKILL_ROUTE="${SKILL_ROUTE}Android UI project: /frontend-design runs the platform-aware interface pipeline; run ./gradlew test after Kotlin/Java changes\n"
fi

# Cross-platform and Windows desktop interface shells
if [[ -d "src-tauri" ]] || grep -qE '"(electron|@tauri-apps/api|react-native)"' package.json 2>/dev/null \
   || { [[ -f "pubspec.yaml" ]] && grep -qE '^[[:space:]]*flutter:' pubspec.yaml 2>/dev/null; }; then
  SKILL_ROUTE="${SKILL_ROUTE}Cross-platform UI project: /frontend-design selects the real target adapters and preview lane\n"
fi
if compgen -G "*.sln" >/dev/null 2>&1 || compgen -G "*.csproj" >/dev/null 2>&1 \
   || compgen -G "*.xaml" >/dev/null 2>&1; then
  SKILL_ROUTE="${SKILL_ROUTE}Windows UI project: /frontend-design runs the Fluent/native interface pipeline\n"
fi

# ML/AI
if grep -rqlE '(import torch|import tensorflow|from transformers|import sklearn|import jax)' . --include='*.py' 2>/dev/null | head -1 &>/dev/null; then
  SKILL_ROUTE="${SKILL_ROUTE}ML/AI project: /verify after model changes, check GPU with nvidia-smi\n"
fi

# LaTeX / academic
if compgen -G "*.tex" >/dev/null 2>&1; then
  SKILL_ROUTE="${SKILL_ROUTE}LaTeX project: latexmk to rebuild, chktex for lint\n"
fi

# Generic: any project with tests
if [[ -f "pyproject.toml" || -f "requirements.txt" || -f "package.json" || -f "Cargo.toml" || -f "go.mod" || -f "Gemfile" ]]; then
  SKILL_ROUTE="${SKILL_ROUTE}Use /verify after code changes, /review for comprehensive testing\n"
fi

if [[ -n "$SKILL_ROUTE" ]]; then
  CONTEXT="${CONTEXT}\nRecommended workflow:\n${SKILL_ROUTE}"
fi

# ─── Skills Directory ───────────────────────────────────────────
# (removed 2026-07-10) The <available_skills> XML injection duplicated Claude
# Code's native skill discovery, which already surfaces name + description +
# when_to_use for every ~/.claude/skills/*/SKILL.md in the system prompt.
# Worse, the ~20KB block pushed total hook output past the harness inline
# limit (30.8KB observed), so the whole additionalContext was persisted to a
# file instead of entering context — the injection was dead weight that also
# knocked out the useful sections above. Routing hints stay; catalog goes.

# Warn, never truncate: the guidance blocks are appended LAST, so cutting the
# assembled payload would silently drop exactly the sections this budget exists
# to protect. A visible line beats a silent overflow.
if [[ ${#CONTEXT} -gt $CTX_TOTAL_CEILING ]]; then
  CONTEXT="${CONTEXT}\n(session-context: ${#CONTEXT} chars injected, over the ${CTX_TOTAL_CEILING} budget — a section has grown; see CLAUDE.md.)\n"
fi

if [[ -n "$CONTEXT" ]]; then
  jq -n --arg ctx "$CONTEXT" \
    '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'
fi

exit 0
