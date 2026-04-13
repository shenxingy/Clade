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
if [[ -f ".claude/loop-state" ]]; then
  CONVERGED=$(grep "^CONVERGED=" .claude/loop-state | cut -d= -f2)
  ITERATION=$(grep "^ITERATION=" .claude/loop-state | cut -d= -f2)
  GOAL=$(grep "^GOAL=" .claude/loop-state | cut -d= -f2 | xargs basename 2>/dev/null)
  if [[ "$CONVERGED" == "true" ]]; then
    CONTEXT="${CONTEXT}Loop: ✓ converged (${GOAL}, iter ${ITERATION})\n"
  elif [[ "$CONVERGED" == "false" ]]; then
    CONTEXT="${CONTEXT}Loop: ⟳ running (${GOAL}, iter ${ITERATION})\n"
  fi
fi

# Next TODO item
NEXT_TODO=$(grep -m1 "^\- \[ \]" TODO.md 2>/dev/null | sed 's/- \[ \] \*\*//' | sed 's/\*\*.*//' | xargs)
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
      HANDOFF_CONTENT=$(cat "$LATEST_HANDOFF" 2>/dev/null)
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
    COMPACT_CONTENT=$(cat "$COMPACT_STATE" 2>/dev/null)
    CONTEXT="${CONTEXT}\n## Compact State (context was compacted ${CS_AGE_HOURS}h ago — resume from here)\n${COMPACT_CONTENT}\n"
  fi
fi

# ─── Self-Improvement Pipeline ────────────────────────────────────────

HOOKS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load correction rules (global + project-local)
GLOBAL_RULES="$HOME/.claude/corrections/rules.md"
PROJECT_RULES="${CLAUDE_PROJECT_DIR:-.}/.claude/corrections/rules.md"
COMBINED_RULES=""
if [[ -f "$PROJECT_RULES" && "$PROJECT_RULES" != "$GLOBAL_RULES" ]]; then
  COMBINED_RULES=$(tail -25 "$PROJECT_RULES" 2>/dev/null)
  [[ -n "$COMBINED_RULES" ]] && COMBINED_RULES="${COMBINED_RULES}\n"
fi
if [[ -f "$GLOBAL_RULES" ]]; then
  COMBINED_RULES="${COMBINED_RULES}$(tail -25 "$GLOBAL_RULES" 2>/dev/null)"
fi
if [[ -n "$COMBINED_RULES" ]]; then
  CONTEXT="${CONTEXT}\nCorrection rules (learned from past feedback):\n${COMBINED_RULES}\n"
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
CONTEXT="${CONTEXT}\nModel guide: Sonnet 4.6 is optimal for most coding (79.6% SWE-bench, 40% cheaper than Opus). Switch to Opus 4.6 only for: large refactors (10+ files), deep architectural reasoning, or outputs >64K tokens. Use Haiku 4.5 for sub-agents doing mechanical checks. If you detect the user is about to do a complex multi-file refactor on Sonnet, suggest: 'This task may benefit from Opus — run /model to switch.'\n"

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
  SKILL_ROUTE="${SKILL_ROUTE}iOS project: run xcodebuild tests after Swift changes\n"
fi

# Mobile — Android
if [[ -f "build.gradle" || -f "build.gradle.kts" || -f "settings.gradle" || -f "settings.gradle.kts" ]]; then
  SKILL_ROUTE="${SKILL_ROUTE}Android project: ./gradlew test after Kotlin/Java changes\n"
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
# Inject available skills into every session so Claude can suggest the right skill
SKILLS_DIR="$HOME/.claude/skills"
if [ -d "$SKILLS_DIR" ]; then
  skills_xml="<available_skills>\n"
  found_any=false

  for skill_dir in "$SKILLS_DIR"/*/; do
    skill_md="$skill_dir/SKILL.md"
    [ -f "$skill_md" ] || continue

    # Parse frontmatter fields
    name=$(grep '^name:' "$skill_md" 2>/dev/null | head -1 | sed 's/^name:[[:space:]]*//')
    desc=$(grep '^description:' "$skill_md" 2>/dev/null | head -1 | sed 's/^description:[[:space:]]*//')
    invocable=$(grep '^user_invocable:' "$skill_md" 2>/dev/null | head -1 | sed 's/^user_invocable:[[:space:]]*//')
    hint=$(grep '^argument-hint:' "$skill_md" 2>/dev/null | head -1 | sed 's/^argument-hint:[[:space:]]*//')
    when=$(grep '^when_to_use:' "$skill_md" 2>/dev/null | head -1 | sed 's/^when_to_use:[[:space:]]*//' | tr -d '"')

    # Only include user-invocable skills
    [ "$invocable" = "true" ] || continue
    [ -z "$name" ] && continue

    found_any=true

    # Build usage string
    if [ -n "$hint" ]; then
      usage="/$name $hint"
    else
      usage="/$name"
    fi

    # Add XML entry
    if [ -n "$when" ]; then
      skills_xml+="  <skill name=\"$name\" when_to_use=\"$when\">\n    $desc. Usage: $usage\n  </skill>\n"
    else
      skills_xml+="  <skill name=\"$name\">\n    $desc. Usage: $usage\n  </skill>\n"
    fi
  done

  skills_xml+="</available_skills>"

  if [ "$found_any" = "true" ]; then
    CONTEXT="${CONTEXT}\n## Available Skills\nUse /skill-name [args] to invoke. When user describes a need, suggest the matching skill.\n$(printf "$skills_xml")\n"
  fi
fi

if [[ -n "$CONTEXT" ]]; then
  jq -n --arg ctx "$CONTEXT" \
    '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":$ctx}}'
fi

exit 0
