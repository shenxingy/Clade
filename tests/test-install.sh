#!/usr/bin/env bash
# test-install.sh — CI executes what install.sh actually ships.
#
# Runs install.sh against a THROWAWAY $HOME under /tmp (never the real home)
# from a THROWAWAY copy of the repo. Covers: clean install, source immutability,
# bytecode exclusion, idempotent re-run, executable
# hooks, generated skill catalog, Cross-Project Rules preservation across
# reinstall (regression for commit ab06c33), settings.json hook-merge
# preserving unrelated keys, and symlink resolution.
#
# Usage: bash tests/test-install.sh

set -uo pipefail

# ─── Harness ──────────────────────────────────────────────────────────

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

# ─── Sandbox setup ───────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_HOME="$HOME"

SANDBOX="$(mktemp -d /tmp/clade-install-test-XXXXXX)"

# HARD SAFETY GATE: everything below operates on $HOME — refuse to continue
# unless the sandbox (and therefore the fake HOME) is provably under /tmp.
case "$SANDBOX" in
  /tmp/clade-install-test-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' is not under /tmp — aborting before any write"; exit 1 ;;
esac

export HOME="$SANDBOX/home"
mkdir -p "$HOME"
case "$HOME" in
  /tmp/*) : ;;
  *) echo "FATAL: \$HOME '$HOME' is not under /tmp — aborting"; exit 1 ;;
esac
if [[ "$HOME" == "$REAL_HOME" ]]; then
  echo "FATAL: fake HOME equals real HOME — aborting"
  exit 1
fi

cleanup() { rm -rf "$SANDBOX"; }
trap cleanup EXIT

# Run from a throwaway copy of the repo (working tree, so uncommitted changes
# count) and seed artifacts that must never be deployed.
SRC="$SANDBOX/repo"
mkdir -p "$SRC"
tar -C "$REPO_ROOT" \
  --exclude='.git' \
  --exclude='orchestrator/.venv' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  -cf - . | tar -xf - -C "$SRC"

mkdir -p "$SRC/configs/scripts/__pycache__"
mkdir -p "$SRC/configs/skills/delivery/scripts/__pycache__"
printf 'stale bytecode\n' > "$SRC/configs/scripts/__pycache__/stale.cpython-312.pyc"
printf 'stale bytecode\n' > "$SRC/configs/skills/delivery/scripts/__pycache__/stale.cpython-312.pyc"

# A local install may diagnose stale repository facts, but must never rewrite
# the checkout. Make the copied fact intentionally stale to exercise that path.
python3 - "$SRC/docs/facts.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text())
data["facts"][0]["value"] = 0
path.write_text(json.dumps(data, indent=2) + "\n")
PY
cp "$SRC/docs/facts.json" "$SANDBOX/facts-before-install.json"

echo "Sandbox: $SANDBOX"
echo "Fake HOME: $HOME"

# A shell rc file so the alias step has something to append to
touch "$HOME/.bashrc"

# ─── Suite 1: Fresh install ───────────────────────────────────────────

section "Fresh install into empty \$HOME"

install_log="$SANDBOX/install-1.log"
if bash "$SRC/install.sh" </dev/null >"$install_log" 2>&1; then
  pass "install.sh exits 0 on fresh install"
else
  fail "install.sh exits 0 on fresh install" "see $install_log"
  tail -30 "$install_log"
fi

CLAUDE_DIR="$HOME/.claude"

[[ -d "$CLAUDE_DIR/hooks" ]] && pass "hooks dir created" || fail "hooks dir created"

hook_count=0; nonexec=0
for hook in "$CLAUDE_DIR/hooks/"*.sh; do
  [[ -f "$hook" ]] || continue
  hook_count=$((hook_count + 1))
  [[ -x "$hook" ]] || nonexec=$((nonexec + 1))
done
if [[ $hook_count -gt 0 && $nonexec -eq 0 ]]; then
  pass "all $hook_count installed hooks are executable"
else
  fail "all installed hooks are executable" "$hook_count hooks, $nonexec not executable"
fi

# Path-scoped rules: rule-injector.sh ships and its global rules dir exists
[[ -d "$CLAUDE_DIR/rules" ]] \
  && pass "global rules dir created (~/.claude/rules)" \
  || fail "global rules dir created (~/.claude/rules)"
[[ -x "$CLAUDE_DIR/hooks/rule-injector.sh" ]] \
  && pass "rule-injector.sh installed and executable" \
  || fail "rule-injector.sh installed and executable"

# Output styles: the one primitive that edits the SYSTEM prompt, so CLAUDE.md
# cannot substitute for it. Shipped but never auto-activated.
[[ -d "$CLAUDE_DIR/output-styles" ]] \
  && pass "output-styles dir created (~/.claude/output-styles)" \
  || fail "output-styles dir created (~/.claude/output-styles)"

style_count=0; style_bad=0
for style in "$CLAUDE_DIR/output-styles/"*.md; do
  [[ -f "$style" ]] || continue
  style_count=$((style_count + 1))
  # A style missing keep-coding-instructions silently DROPS Claude Code's
  # built-in engineering instructions — catastrophic for a coding toolkit.
  head -1 "$style" | grep -q '^---$' || style_bad=$((style_bad + 1))
  grep -q '^description:' "$style" || style_bad=$((style_bad + 1))
  grep -q '^keep-coding-instructions: true$' "$style" || style_bad=$((style_bad + 1))
done
if [[ $style_count -gt 0 && $style_bad -eq 0 ]]; then
  pass "all $style_count output styles have frontmatter and keep coding instructions"
else
  fail "output styles well-formed" "$style_count styles, $style_bad frontmatter problems"
fi

# Shipping a style must not silently change how every session talks.
if grep -q '"outputStyle"' "$CLAUDE_DIR/settings.json" 2>/dev/null; then
  fail "install does not activate an output style" "settings.json sets outputStyle"
else
  pass "install ships output styles without activating one"
fi

# Mid-flight worker steering: mailbox-drain.sh ships with the hook set
[[ -x "$CLAUDE_DIR/hooks/mailbox-drain.sh" ]] \
  && pass "mailbox-drain.sh installed and executable" \
  || fail "mailbox-drain.sh installed and executable"

agent_count=$(ls "$CLAUDE_DIR/agents/"*.md 2>/dev/null | wc -l | tr -d ' ')
[[ "$agent_count" -gt 0 ]] && pass "agents installed ($agent_count)" || fail "agents installed"

CODEX_DIR="$HOME/.codex"
codex_agent_count=$(ls "$CODEX_DIR/agents/"*.toml 2>/dev/null | wc -l | tr -d ' ')
[[ "$codex_agent_count" -eq 2 ]] \
  && pass "Codex cheap-tier agents installed ($codex_agent_count)" \
  || fail "Codex cheap-tier agents installed" "found $codex_agent_count, want 2"
grep -q '^## Adaptive Delegation$' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex adaptive-delegation instructions installed" \
  || fail "Codex adaptive-delegation instructions installed"
grep -q '^## Delivery Completion$' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex delivery-completion instructions installed" \
  || fail "Codex delivery-completion instructions installed"
grep -q 'Never report `DONE` while task-owned changes are uncommitted' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex dirty-DONE guard installed" \
  || fail "Codex dirty-DONE guard installed"
grep -q 'The local run is the gate; hosted CI is the receipt.' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex local-CI-first policy installed" \
  || fail "Codex local-CI-first policy installed"
grep -q 'Separate verified, unverified, and unmeasurable results.' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex evidence-first policy installed" \
  || fail "Codex evidence-first policy installed"
grep -q 'Trace settings from definition through read, callsite, and observable effect.' "$CODEX_DIR/AGENTS.md" \
  && pass "Codex settings-wiring policy installed" \
  || fail "Codex settings-wiring policy installed"

script_count=$(ls "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null | wc -l | tr -d ' ')
[[ "$script_count" -gt 0 ]] && pass "scripts installed ($script_count)" || fail "scripts installed"

if find "$CLAUDE_DIR/scripts" "$CLAUDE_DIR/skills" \
    \( -type d -name __pycache__ -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) \
    -print -quit | grep -q .; then
  fail "install excludes Python bytecode caches"
else
  pass "install excludes Python bytecode caches"
fi

if cmp -s "$SRC/docs/facts.json" "$SANDBOX/facts-before-install.json"; then
  pass "install leaves source checkout facts unchanged"
else
  fail "install leaves source checkout facts unchanged"
fi

# SessionEnd shadow cleanup ships with the hook set
[[ -x "$CLAUDE_DIR/hooks/session-end-cleanup.sh" ]] \
  && pass "session-end-cleanup.sh installed and executable" \
  || fail "session-end-cleanup.sh installed and executable"

# Subagent recursion cap — "subagents must not delegate recursively" needs a
# real control now that Claude Code 2.1.221 defaults the spawn depth to 3.
if command -v jq &>/dev/null; then
  depth=$(jq -r '.env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH // ""' \
    "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$depth" == "1" ]] \
    && pass "fresh install caps subagent spawn depth at 1" \
    || fail "fresh install caps subagent spawn depth at 1" "got '$depth'"

  # The depth merge must not have wiped the template's own env keys.
  if jq -e '.env | has("TG_BOT_TOKEN") and has("TG_CHAT_ID")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "depth merge preserves the template's env keys"
  else
    fail "depth merge preserves the template's env keys"
  fi
fi

# ─── Suite 2: Generated skill catalog ────────────────────────────────

section "Generated skill catalog (available_skills.md)"

CATALOG="$CLAUDE_DIR/available_skills.md"
if [[ -s "$CATALOG" ]]; then
  pass "available_skills.md generated and non-empty"
else
  fail "available_skills.md generated and non-empty"
fi

skill_entries=$(grep -c '^## ' "$CATALOG" 2>/dev/null || true)
skill_entries=${skill_entries:-0}
if [[ "$skill_entries" -gt 0 ]]; then
  pass "catalog lists $skill_entries skills (>0)"
else
  fail "catalog lists >0 skills"
fi

grep -q '^## commit$' "$CATALOG" \
  && pass "catalog contains the commit skill" \
  || fail "catalog contains the commit skill"

# Regression: folded `description: >` frontmatter used to surface as a bare
# '>' line in the catalog (line-based awk parser)
if grep -qx '>' "$CATALOG"; then
  fail "catalog has no mangled '>' description lines"
else
  pass "catalog has no mangled '>' description lines"
fi

# Migration (2026-07-10): the agents/ mirror was dropped — CC native skill
# discovery replaced it and the 20KB copy overflowed the hook inline limit.
# install.sh now removes any stale copy; assert the cleanup actually runs.
if [[ -e "$CLAUDE_DIR/agents/available-skills.md" ]]; then
  fail "stale agents/available-skills.md mirror removed by install"
else
  pass "stale agents/available-skills.md mirror removed by install"
fi

# ─── Suite 3: Reinstall preserves learned rules + settings ────────────

section "Reinstall preserves Cross-Project Rules and settings"

SENTINEL_RULE="learned-rule-sentinel-7f3a"
CODEX_SENTINEL="codex-user-rule-sentinel-28c1"
{
  cat "$CLAUDE_DIR/CLAUDE.md"
  echo ""
  echo "## Cross-Project Rules"
  echo "- $SENTINEL_RULE: never delete me"
} > "$CLAUDE_DIR/CLAUDE.md.new"
mv "$CLAUDE_DIR/CLAUDE.md.new" "$CLAUDE_DIR/CLAUDE.md"
printf '\n## User Rules\n- %s\n' "$CODEX_SENTINEL" >> "$CODEX_DIR/AGENTS.md"

ENV_SENTINEL="user-env-sentinel-4b9d"
if command -v jq &>/dev/null; then
  # Seed BOTH a top-level user key and a user-authored key inside `env`. The
  # depth cap lands in `env`, which — unlike `.hooks` — is user-owned territory,
  # so it must be merged into rather than replaced.
  jq --arg s "$ENV_SENTINEL" \
    '. + {model: "sentinel-model-keep"}
     | .env = ((.env // {}) + {MY_OWN_VAR: $s})' \
    "$CLAUDE_DIR/settings.json" \
    > "$CLAUDE_DIR/settings.json.new" 2>/dev/null \
    && mv "$CLAUDE_DIR/settings.json.new" "$CLAUDE_DIR/settings.json"

  # Reproduce the real upgrade state: every machine installed before the deny
  # list shipped carries settings.json with NO permissions key at all, because
  # the merge path only ever wrote .hooks and .statusLine. Seed a user-authored
  # allow + deny alongside it so the union is exercised, not just the empty case.
  jq '.permissions = {allow: ["Bash(mytool:*)"], deny: ["Read(~/my-secrets/**)"]}' \
    "$CLAUDE_DIR/settings.json" \
    > "$CLAUDE_DIR/settings.json.new" 2>/dev/null \
    && mv "$CLAUDE_DIR/settings.json.new" "$CLAUDE_DIR/settings.json"
fi

# Seed a stale pre-migration mirror so the reinstall exercises the cleanup path
echo "stale pre-2026-07-10 mirror" > "$CLAUDE_DIR/agents/available-skills.md"
mkdir -p "$CLAUDE_DIR/skills/ads/references/references" "$CLAUDE_DIR/skills/private"
echo "stale nested copy" > "$CLAUDE_DIR/skills/ads/references/references/stale.md"
printf '%s\n' '---' 'name: private' 'description: User-owned test skill.' '---' > "$CLAUDE_DIR/skills/private/SKILL.md"

# ~/.claude/output-styles/ is shared with the user's own styles, so the installer
# copies by name instead of mirroring the directory — a mirror would delete these.
mkdir -p "$CLAUDE_DIR/output-styles"
printf '%s\n' '---' 'name: My Own Style' 'description: User-authored.' '---' \
  > "$CLAUDE_DIR/output-styles/my-own.md"

install_log2="$SANDBOX/install-2.log"
if bash "$SRC/install.sh" </dev/null >"$install_log2" 2>&1; then
  pass "second install.sh run exits 0 (idempotent)"
else
  fail "second install.sh run exits 0 (idempotent)" "see $install_log2"
  tail -30 "$install_log2"
fi

if [[ -e "$CLAUDE_DIR/agents/available-skills.md" ]]; then
  fail "reinstall migrates away stale agents/available-skills.md"
else
  pass "reinstall migrates away stale agents/available-skills.md"
fi

if [[ -e "$CLAUDE_DIR/skills/ads/references/references" ]]; then
  fail "reinstall removes stale nested repo-managed skill content"
else
  pass "reinstall removes stale nested repo-managed skill content"
fi
[[ -f "$CLAUDE_DIR/skills/private/SKILL.md" ]] \
  && pass "reinstall preserves unrelated user-owned skills" \
  || fail "reinstall preserves unrelated user-owned skills"

[[ -f "$CLAUDE_DIR/output-styles/my-own.md" ]] \
  && pass "reinstall preserves user-authored output styles" \
  || fail "reinstall preserves user-authored output styles"

# Regression for ab06c33: plain cp used to clobber the learned-rules section
sentinel_count=$(grep -c "$SENTINEL_RULE" "$CLAUDE_DIR/CLAUDE.md" 2>/dev/null || true)
sentinel_count=${sentinel_count:-0}
if [[ "$sentinel_count" -eq 1 ]]; then
  pass "Cross-Project Rules survive reinstall (exactly once)"
else
  fail "Cross-Project Rules survive reinstall" "sentinel found $sentinel_count times (want 1)"
fi

grep -q "Agent Ground Rules" "$CLAUDE_DIR/CLAUDE.md" \
  && pass "Agent Ground Rules present after reinstall" \
  || fail "Agent Ground Rules present after reinstall"

codex_sentinel_count=$(grep -c "$CODEX_SENTINEL" "$CODEX_DIR/AGENTS.md" 2>/dev/null || true)
codex_block_count=$(grep -c '<!-- BEGIN CLADE ADAPTIVE DELEGATION -->' "$CODEX_DIR/AGENTS.md" 2>/dev/null || true)
codex_delivery_count=$(grep -c '^## Delivery Completion$' "$CODEX_DIR/AGENTS.md" 2>/dev/null || true)
[[ "$codex_sentinel_count" -eq 1 ]] \
  && pass "Codex user instructions survive reinstall" \
  || fail "Codex user instructions survive reinstall" "sentinel found $codex_sentinel_count times"
[[ "$codex_block_count" -eq 1 ]] \
  && pass "Codex managed instructions remain idempotent" \
  || fail "Codex managed instructions remain idempotent" "block found $codex_block_count times"
[[ "$codex_delivery_count" -eq 1 ]] \
  && pass "Codex delivery instructions remain idempotent" \
  || fail "Codex delivery instructions remain idempotent" "section found $codex_delivery_count times"

if command -v jq &>/dev/null; then
  model_val=$(jq -r '.model // ""' "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$model_val" == "sentinel-model-keep" ]] \
    && pass "settings.json merge preserves unrelated keys" \
    || fail "settings.json merge preserves unrelated keys" "model='$model_val'"

  # The deny list is the only permission control that still binds under
  # --dangerously-skip-permissions, which is how every Clade worker spawns.
  # Before 2026-08-29 the merge path never wrote .permissions, so these rules
  # reached fresh installs only and every upgraded machine ran without them.
  missing_deny=""
  while read -r rule; do
    jq -e --arg r "$rule" '.permissions.deny | index($r)' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 || missing_deny="$missing_deny $rule"
  done < <(jq -r '.permissions.deny[]' "$SRC/templates/settings.json")
  [[ -z "$missing_deny" ]] \
    && pass "reinstall merges the template deny rules into existing settings.json" \
    || fail "reinstall merges the template deny rules into existing settings.json" \
            "missing:$missing_deny"

  jq -e '.permissions.deny | index("Read(~/my-secrets/**)")' \
    "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 \
    && pass "reinstall preserves a user-authored deny rule" \
    || fail "reinstall preserves a user-authored deny rule"

  jq -e '.permissions.allow | index("Bash(mytool:*)")' \
    "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 \
    && pass "reinstall preserves a user-authored allow rule" \
    || fail "reinstall preserves a user-authored allow rule"

  # Deny-only union on purpose: silently adopting the template's allow list
  # would grant an autonomous worker capability the user never opted into.
  jq -e '.permissions.allow | index("Bash(pytest:*)")' \
    "$CLAUDE_DIR/settings.json" >/dev/null 2>&1 \
    && fail "reinstall does not silently widen the allow list" \
            "template allow rule leaked into an existing settings.json" \
    || pass "reinstall does not silently widen the allow list"

  dup_deny=$(jq -r '.permissions.deny | length as $n | (unique | length) as $u
                    | if $n == $u then "ok" else "dupes" end' \
             "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$dup_deny" == "ok" ]] \
    && pass "deny union de-duplicates across reinstalls" \
    || fail "deny union de-duplicates across reinstalls" "$dup_deny"

  hooks_type=$(jq -r '.hooks | type' "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$hooks_type" == "object" ]] \
    && pass "settings.json has hooks after merge" \
    || fail "settings.json has hooks after merge" "hooks type='$hooks_type'"

  if jq -e '[.hooks.PostToolUse[].hooks[].id] | index("rule-injector")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "rule-injector wired into PostToolUse hooks"
  else
    fail "rule-injector wired into PostToolUse hooks"
  fi

  if jq -e '[.hooks.PostToolUse[].hooks[].id] | index("mailbox-drain")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "mailbox-drain wired into PostToolUse hooks"
  else
    fail "mailbox-drain wired into PostToolUse hooks"
  fi

  if jq -e '[.hooks.SessionEnd[].hooks[].id] | index("session-end-cleanup")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "session-end-cleanup wired into SessionEnd hooks"
  else
    fail "session-end-cleanup wired into SessionEnd hooks"
  fi

  # ── Subagent depth: idempotent, and non-destructive to user env keys ──
  depth=$(jq -r '.env.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH // ""' \
    "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$depth" == "1" ]] \
    && pass "subagent depth cap survives reinstall (idempotent)" \
    || fail "subagent depth cap survives reinstall" "got '$depth'"

  env_sentinel_val=$(jq -r '.env.MY_OWN_VAR // ""' "$CLAUDE_DIR/settings.json" 2>/dev/null)
  [[ "$env_sentinel_val" == "$ENV_SENTINEL" ]] \
    && pass "depth merge preserves user-authored keys in env" \
    || fail "depth merge preserves user-authored keys in env" "got '$env_sentinel_val'"

  # A merge that replaced `env` wholesale would also have dropped these.
  if jq -e '.env | has("TG_BOT_TOKEN") and has("TG_CHAT_ID")' \
      "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    pass "reinstall preserves the template env keys alongside the cap"
  else
    fail "reinstall preserves the template env keys alongside the cap"
  fi

  # The cap is a real Claude Code control, not an invented settings key: the
  # 2.1.227 binary reads CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH from the process
  # env (settings `env` feeds it) and has no `maxSubagentDepth` key at all.
  if jq -e 'has("maxSubagentDepth")' "$CLAUDE_DIR/settings.json" >/dev/null 2>&1; then
    fail "no inert maxSubagentDepth key written" "that key does not exist in Claude Code"
  else
    pass "no inert maxSubagentDepth key written"
  fi
else
  echo "  (jq not available — skipping settings merge checks)"
fi

# ─── Suite 4: Windows/Git Bash settings commands ────────────────────

section "Windows/Git Bash fresh + existing settings"

if command -v jq &>/dev/null; then
  WINDOWS_HOME="$SANDBOX/windows-home"
  WINDOWS_BIN="$SANDBOX/windows-bin"
  mkdir -p "$WINDOWS_HOME" "$WINDOWS_BIN"
  touch "$WINDOWS_HOME/.bashrc"

  cat > "$WINDOWS_BIN/uname" <<'SH'
#!/bin/sh
printf '%s\n' 'MINGW64_NT-10.0'
SH
  cat > "$WINDOWS_BIN/cygpath" <<'SH'
#!/bin/sh
printf '%s\n' 'C:\Program Files\Git\bin\bash.exe'
SH
  cat > "$WINDOWS_BIN/bash" <<'SH'
#!/bin/sh
exec /bin/bash "$@"
SH
  chmod +x "$WINDOWS_BIN/uname" "$WINDOWS_BIN/cygpath" "$WINDOWS_BIN/bash"

  windows_install_log="$SANDBOX/install-windows-1.log"
  if HOME="$WINDOWS_HOME" PATH="$WINDOWS_BIN:$PATH" \
      /bin/bash "$SRC/install.sh" </dev/null >"$windows_install_log" 2>&1; then
    pass "Windows/Git Bash fresh install exits 0"
  else
    fail "Windows/Git Bash fresh install exits 0" "see $windows_install_log"
    tail -30 "$windows_install_log"
  fi

  WINDOWS_SETTINGS="$WINDOWS_HOME/.claude/settings.json"
  WINDOWS_PREFIX='"C:\Program Files\Git\bin\bash.exe" -c "exec '
  if jq -e --arg prefix "$WINDOWS_PREFIX" '
      [.. | objects | select(has("command")) | .command
       | startswith($prefix)] | length > 0 and all
    ' "$WINDOWS_SETTINGS" >/dev/null 2>&1; then
    pass "fresh Windows settings wrap every hook + statusLine command"
  else
    fail "fresh Windows settings wrap every hook + statusLine command"
  fi

  jq '. + {model: "windows-sentinel-keep"}' "$WINDOWS_SETTINGS" \
    > "$WINDOWS_SETTINGS.new"
  mv "$WINDOWS_SETTINGS.new" "$WINDOWS_SETTINGS"
  windows_install_log2="$SANDBOX/install-windows-2.log"
  if HOME="$WINDOWS_HOME" PATH="$WINDOWS_BIN:$PATH" \
      /bin/bash "$SRC/install.sh" </dev/null >"$windows_install_log2" 2>&1; then
    pass "Windows/Git Bash reinstall exits 0"
  else
    fail "Windows/Git Bash reinstall exits 0" "see $windows_install_log2"
    tail -30 "$windows_install_log2"
  fi

  if jq -e --arg prefix "$WINDOWS_PREFIX" '
      .model == "windows-sentinel-keep"
      and ([.. | objects | select(has("command")) | .command
            | startswith($prefix)] | length > 0 and all)
    ' "$WINDOWS_SETTINGS" >/dev/null 2>&1; then
    pass "existing Windows settings preserve user keys and wrapped commands"
  else
    fail "existing Windows settings preserve user keys and wrapped commands"
  fi
else
  echo "  (jq not available — skipping Windows settings checks)"
fi

# ─── Suite 5: Idempotency markers ────────────────────────────────────

section "Idempotency markers"

if [[ -f "$CLAUDE_DIR/.kit-checksum" ]]; then
  pass ".kit-checksum written"
  cs1=$(cat "$CLAUDE_DIR/.kit-checksum")
  bash "$SRC/install.sh" </dev/null >/dev/null 2>&1
  cs2=$(cat "$CLAUDE_DIR/.kit-checksum")
  [[ -n "$cs1" && "$cs1" == "$cs2" ]] \
    && pass ".kit-checksum stable across reinstalls" \
    || fail ".kit-checksum stable across reinstalls" "'$cs1' vs '$cs2'"
else
  fail ".kit-checksum written"
fi

[[ "$(cat "$CLAUDE_DIR/.kit-source-dir" 2>/dev/null)" == "$SRC" ]] \
  && pass ".kit-source-dir points at the install source" \
  || fail ".kit-source-dir points at the install source"

# Aliases were appended exactly once across all three install runs
alias_count=$(grep -c "dangerously-skip-permissions" "$HOME/.bashrc" 2>/dev/null || true)
alias_count=${alias_count:-0}
if [[ "$alias_count" -eq 2 ]]; then  # one claude= line + one cc= line
  pass "shell aliases appended exactly once across reinstalls"
else
  fail "shell aliases appended exactly once" "found $alias_count alias lines (want 2)"
fi

# ─── Suite 6: Symlinks resolve ───────────────────────────────────────

section "Symlinks"

for pair in "committer:committer.sh" "slt:statusline-toggle.sh"; do
  link_name="${pair%%:*}"; target_base="${pair##*:}"
  link="$HOME/.local/bin/$link_name"
  if [[ -L "$link" ]]; then
    resolved=$(readlink -f "$link" 2>/dev/null || true)
    # macOS canonicalizes /tmp to /private/tmp, so compare file identity
    # instead of path spelling after readlink -f.
    if [[ -f "$resolved" && "$resolved" -ef "$CLAUDE_DIR/scripts/$target_base" ]]; then
      pass "$link_name symlink resolves to installed $target_base"
    else
      fail "$link_name symlink resolves" "points at '$resolved'"
    fi
  else
    fail "$link_name symlink created"
  fi
done

# ─── Suite 7: Smoke-run installed copies (not the repo copies) ───────

section "Smoke-run installed scripts"

if command -v python3 &>/dev/null; then
  if python3 "$CLAUDE_DIR/scripts/skill_frontmatter.py" catalog "$CLAUDE_DIR/skills" \
      | grep -q '^## commit$'; then
    pass "installed skill_frontmatter.py catalog runs"
  else
    fail "installed skill_frontmatter.py catalog runs"
  fi

  if python3 "$CLAUDE_DIR/scripts/validate-skills.py" "$CLAUDE_DIR/skills" --quiet \
      >/dev/null 2>&1; then
    pass "installed validate-skills.py passes on installed skills"
  else
    fail "installed validate-skills.py passes on installed skills"
  fi

  # Claude Code >=2.1.80 supplies authoritative rate-limit data in the
  # status-line JSON. The installed command must prefer it over its own
  # OAuth/cache fallback so the display tracks the current API response.
  printf 'percent\n' > "$CLAUDE_DIR/.statusline-mode"
  reset_epoch=$(( $(date +%s) + 5 * 86400 ))
  statusline_out=$(printf \
    '{"cwd":"%s","rate_limits":{"seven_day":{"used_percentage":80,"resets_at":%s}}}\n' \
    "$SRC" "$reset_epoch" | bash "$CLAUDE_DIR/statusline-command.sh")
  if [[ "$statusline_out" == *"+53%"* && "$statusline_out" == *"(5d)"* ]]; then
    pass "installed status line prefers native weekly rate-limit data"
  else
    fail "installed status line prefers native weekly rate-limit data" \
      "expected native +53% (5d), got '$statusline_out'"
  fi
else
  echo "  (python3 not available — skipping installed-script smoke runs)"
fi

# committer.sh with no args must print usage and exit non-zero
if bash "$CLAUDE_DIR/scripts/committer.sh" >/dev/null 2>&1; then
  fail "installed committer.sh rejects empty invocation"
else
  pass "installed committer.sh rejects empty invocation"
fi

# ─── Suite 8: Unowned-file report ────────────────────────────────────
#
# install.sh MIRRORS skills but plain-copies hooks and scripts, so anything an
# older version deployed survives forever, invisibly. The report closes the
# visibility gap without closing the door: it must never delete, because a
# removal can be reversed (0164075 backported iloop-hook.sh after 909092f had
# deleted it) and ~/.claude is shared with whatever else the user installs.

section "Reports unowned hooks/scripts without deleting them"

# Nothing to say on a clean install — the report must not be noise.
if grep -q "that Clade does not install:" "$SANDBOX/install-1.log"; then
  fail "clean install prints no unowned-file report" \
    "heading appeared with an empty \$HOME"
else
  pass "clean install prints no unowned-file report"
fi

printf '#!/usr/bin/env bash\necho orphan\n' > "$CLAUDE_DIR/hooks/zz-orphan.sh"
printf '#!/usr/bin/env bash\necho orphan\n' > "$CLAUDE_DIR/scripts/zz-orphan.sh"
printf 'not even a shell script\n' > "$CLAUDE_DIR/scripts/zz-orphan-noext"

install_log4="$SANDBOX/install-4.log"
if bash "$SRC/install.sh" </dev/null >"$install_log4" 2>&1; then
  pass "install.sh still exits 0 when unowned files are present"
else
  fail "install.sh still exits 0 when unowned files are present" "see $install_log4"
  tail -30 "$install_log4"
fi

# The load-bearing assertion: report-only, never destructive.
if [[ -f "$CLAUDE_DIR/hooks/zz-orphan.sh" && -f "$CLAUDE_DIR/scripts/zz-orphan.sh" \
   && -f "$CLAUDE_DIR/scripts/zz-orphan-noext" ]]; then
  pass "unowned files survive the reinstall (report never deletes)"
else
  fail "unowned files survive the reinstall (report never deletes)"
fi

orphan_block=$(sed -n '/that Clade does not install:/,/Clade never removes these/p' \
  "$install_log4")

if [[ -n "$orphan_block" ]]; then
  pass "unowned-file report is printed when there is something to report"
else
  fail "unowned-file report is printed when there is something to report" \
    "see $install_log4"
fi

for expected in "hooks/zz-orphan.sh" "scripts/zz-orphan.sh" "scripts/zz-orphan-noext"; do
  if grep -qF "$expected" <<<"$orphan_block"; then
    pass "report names $expected"
  else
    fail "report names $expected"
  fi
done

# The false positive the finding that prompted this feature made about itself:
# ~/.claude/scripts/mcp_server.py is absent from configs/scripts/ but IS
# installed, from orchestrator/mcp_server.py. Deriving the expected set from
# configs/ alone reports it as an orphan.
[[ -f "$CLAUDE_DIR/scripts/mcp_server.py" ]] \
  && pass "mcp_server.py is installed outside configs/ (precondition)" \
  || fail "mcp_server.py is installed outside configs/ (precondition)"
if grep -qF "mcp_server.py" <<<"$orphan_block"; then
  fail "installed-but-not-in-configs mcp_server.py is not reported as unowned" \
    "the expected set was derived from configs/ instead of from what installs"
else
  pass "installed-but-not-in-configs mcp_server.py is not reported as unowned"
fi

# Subdirectories are not files: hooks/lib and scripts/ads must never appear.
if grep -qE "hooks/lib|scripts/(ads|blog)\\b" <<<"$orphan_block"; then
  fail "report skips subdirectories"
else
  pass "report skips subdirectories"
fi

# ─── Suite 8b: AGENTS.override.md shadows the managed block ──────────
#
# Codex resolves agent instructions first-filename-wins with NO merge:
# AGENTS.override.md is probed before AGENTS.md at home scope
# (codex-rs/codex-home/src/instructions/mod.rs:10) and at project scope
# (codex-rs/core/src/agents_md.rs:42), verified at rust-v0.153.4. So the
# careful merge above can write the Clade block into ~/.codex/AGENTS.md and
# Codex will never read a byte of it — silently, because every other signal
# says the install succeeded.
#
# Report only, exactly like the orphan sweep above: AGENTS.override.md is the
# user's own global instruction file and install.sh must neither delete nor
# move it. The merge still runs, so removing the override later works.

section "Warns when ~/.codex/AGENTS.override.md shadows the managed block"

# No override, no warning — the report must not be noise on a clean install.
if grep -q "AGENTS.override.md" "$SANDBOX/install-1.log"; then
  fail "clean install prints no override warning" \
    "warned with no AGENTS.override.md present"
else
  pass "clean install prints no override warning"
fi

CODEX_OVERRIDE="$CODEX_DIR/AGENTS.override.md"
printf '# My own global Codex instructions\n\n- keep me verbatim\n' > "$CODEX_OVERRIDE"
override_before="$(cat "$CODEX_OVERRIDE")"

install_log_override="$SANDBOX/install-override.log"
if bash "$SRC/install.sh" </dev/null >"$install_log_override" 2>&1; then
  pass "install.sh exits 0 when AGENTS.override.md is present"
else
  fail "install.sh exits 0 when AGENTS.override.md is present" \
    "see $install_log_override"
  tail -30 "$install_log_override"
fi

if grep -qF "AGENTS.override.md" "$install_log_override"; then
  pass "install warning names AGENTS.override.md"
else
  fail "install warning names AGENTS.override.md" "see $install_log_override"
fi

# Naming the file is not enough. A reader who is not told the consequence has
# no reason to act, and the whole defect is that the failure is silent.
if grep -qiE 'will not load|not be loaded|never loaded' "$install_log_override"; then
  pass "install warning states the managed block will not load"
else
  fail "install warning states the managed block will not load" \
    "see $install_log_override"
fi

# The warning has to be findable in a long install log.
if grep -qE '^(WARNING|Warning):.*AGENTS\.override\.md' "$install_log_override"; then
  pass "override warning is announced as a warning, not buried in prose"
else
  fail "override warning is announced as a warning, not buried in prose" \
    "see $install_log_override"
fi

# Load-bearing: report only. Never delete, never move, never rewrite.
if [[ -f "$CODEX_OVERRIDE" && "$(cat "$CODEX_OVERRIDE")" == "$override_before" ]]; then
  pass "AGENTS.override.md survives the install byte-for-byte"
else
  fail "AGENTS.override.md survives the install byte-for-byte" \
    "install.sh must report the shadowing, not resolve it"
fi

if compgen -G "$CODEX_DIR/AGENTS.override.md.*" >/dev/null 2>&1; then
  fail "install leaves no AGENTS.override.md backup/rename behind" \
    "$(ls "$CODEX_DIR"/AGENTS.override.md.* 2>/dev/null | tr '\n' ' ')"
else
  pass "install leaves no AGENTS.override.md backup/rename behind"
fi

# ...and the merge still happens, so deleting the override later is the fix.
override_block_count=$(grep -c '<!-- BEGIN CLADE ADAPTIVE DELEGATION -->' \
  "$CODEX_DIR/AGENTS.md" 2>/dev/null || true)
override_block_count=${override_block_count:-0}
if [[ "$override_block_count" -eq 1 ]]; then
  pass "managed block is still merged into AGENTS.md while shadowed"
else
  fail "managed block is still merged into AGENTS.md while shadowed" \
    "block found $override_block_count times (want 1)"
fi

# An empty override file does not shadow anything Codex reads as instructions,
# so warning about it would be the noise this suite's first case forbids.
: > "$CODEX_OVERRIDE"
install_log_empty="$SANDBOX/install-override-empty.log"
bash "$SRC/install.sh" </dev/null >"$install_log_empty" 2>&1 || true
if grep -q "AGENTS.override.md" "$install_log_empty"; then
  fail "an empty AGENTS.override.md draws no warning"
else
  pass "an empty AGENTS.override.md draws no warning"
fi

# `[[ -s X ]]` is true for a DIRECTORY, so a size test alone misfires on one.
# Codex resolves a candidate only when its metadata says is_file(), at both
# scopes, so a directory of that name shadows nothing and must not warn.
rm -f "$CODEX_OVERRIDE"
mkdir -p "$CODEX_OVERRIDE"
install_log_dir="$SANDBOX/install-override-dir.log"
bash "$SRC/install.sh" </dev/null >"$install_log_dir" 2>&1 || true
if grep -q "AGENTS.override.md" "$install_log_dir"; then
  fail "a directory named AGENTS.override.md draws no warning" \
    "[[ -s ]] is true for a directory; Codex resolves regular files only"
else
  pass "a directory named AGENTS.override.md draws no warning"
fi
rm -rf "$CODEX_OVERRIDE"

# ─── Suite 9: install.sh stays node-free ─────────────────────────────
#
# The web UI build belongs where the server is, not in the installer: this
# script deploys skills and hooks to ~/.claude and must work on a machine with
# no node toolchain at all.

section "install.sh needs no node toolchain"

if grep -Eqn '(^|[^[:alnum:]_./-])(npm|npx|yarn|pnpm|vite)([[:space:]]|$)' "$SRC/install.sh"; then
  fail "install.sh invokes no package manager" \
    "$(grep -Enm3 '(^|[^[:alnum:]_./-])(npm|npx|yarn|pnpm|vite)([[:space:]]|$)' "$SRC/install.sh")"
else
  pass "install.sh invokes no package manager"
fi

# Behavioural half: with npm/node/npx failing, install.sh must still succeed.
NO_NODE_BIN="$SANDBOX/no-node-bin"
mkdir -p "$NO_NODE_BIN"
for shim in npm npx node; do
  printf '#!/usr/bin/env bash\necho "%s: command not found" >&2\nexit 127\n' "$shim" \
    > "$NO_NODE_BIN/$shim"
  chmod +x "$NO_NODE_BIN/$shim"
done

install_log5="$SANDBOX/install-5.log"
if PATH="$NO_NODE_BIN:$PATH" bash "$SRC/install.sh" </dev/null >"$install_log5" 2>&1; then
  pass "install.sh exits 0 with npm/node/npx unusable"
else
  fail "install.sh exits 0 with npm/node/npx unusable" "see $install_log5"
  tail -30 "$install_log5"
fi

# ─── Suite 10: --ultracode is an opt-in that actually lands ──────────
#
# The flag writes two keys into the user's own settings.json. Every failure
# mode here is silent by construction: a merge that clobbers the file, a
# rejected size that gets written verbatim, an opt-in that is on by default, or
# a documented "turn it off with" line that does not turn it off. None of them
# raise an error, and the installer prints a success line either way.

section "--ultracode opt-in"

SETTINGS="$HOME/.claude/settings.json"

# The preceding suites all ran the installer with no flags. If the key is here
# now, the opt-in defaults to on, which is the one thing it must never do.
if [[ -f "$SETTINGS" ]] && ! jq -e 'has("ultracode")' "$SETTINGS" >/dev/null 2>&1; then
  pass "ultracode is absent after a plain install (opt-in, not default)"
else
  fail "ultracode is absent after a plain install (opt-in, not default)" \
       "settings.json: $(cat "$SETTINGS" 2>/dev/null | head -c 200)"
fi

# Seed a key the merge must preserve. `. + {...}` is a merge, but only if the
# temp-file dance around it works; a truncated write would lose this.
#
# The canary has to be a key install.sh does NOT own. The first version of this
# test used statusLine and failed — correctly, because §8 sets `.statusLine`
# outright on every run. cleanupPeriodDays appears nowhere in the installer, so
# losing it can only mean the merge clobbered the file.
jq '. + {cleanupPeriodDays: 4242}' "$SETTINGS" \
  > "$SETTINGS.seed" && mv "$SETTINGS.seed" "$SETTINGS"

uc_log="$SANDBOX/install-ultracode.log"
if bash "$SRC/install.sh" --ultracode </dev/null >"$uc_log" 2>&1; then
  pass "install.sh --ultracode exits 0"
else
  fail "install.sh --ultracode exits 0" "see $uc_log"
fi

if jq -e '.ultracode == true and .workflowSizeGuideline == "medium"' "$SETTINGS" >/dev/null 2>&1; then
  pass "--ultracode sets ultracode=true and the medium size guideline"
else
  fail "--ultracode sets ultracode=true and the medium size guideline" \
       "got: $(jq -c '{ultracode, workflowSizeGuideline}' "$SETTINGS" 2>&1)"
fi

if jq -e '.cleanupPeriodDays == 4242' "$SETTINGS" >/dev/null 2>&1; then
  pass "--ultracode merges into settings.json without dropping the user's keys"
else
  fail "--ultracode merges into settings.json without dropping the user's keys" \
       "the seeded cleanupPeriodDays key did not survive"
fi

if bash "$SRC/install.sh" --ultracode=large </dev/null >/dev/null 2>&1 \
   && jq -e '.workflowSizeGuideline == "large"' "$SETTINGS" >/dev/null 2>&1; then
  pass "--ultracode=large raises the size guideline"
else
  fail "--ultracode=large raises the size guideline" \
       "got: $(jq -r '.workflowSizeGuideline' "$SETTINGS" 2>&1)"
fi

# A rejected size must not reach the file. Writing "enormous" verbatim would be
# read by Claude Code as an unknown value, not as the medium it warned about.
uc_bad_log="$SANDBOX/install-ultracode-bad.log"
bash "$SRC/install.sh" --ultracode=enormous </dev/null >"$uc_bad_log" 2>&1
if jq -e '.workflowSizeGuideline == "medium"' "$SETTINGS" >/dev/null 2>&1 \
   && grep -q "is not small|medium|large" "$uc_bad_log"; then
  pass "--ultracode=<bogus> warns and falls back to medium instead of writing it"
else
  fail "--ultracode=<bogus> warns and falls back to medium instead of writing it" \
       "value: $(jq -r '.workflowSizeGuideline' "$SETTINGS" 2>&1)"
fi

# The installer prints a removal command. An escape hatch nobody can run is the
# same defect as no escape hatch; run the literal line it printed.
removal=$(grep -o "jq 'del(\.ultracode)' [^ ]*" "$uc_log" | head -1)
if [[ -n "$removal" ]]; then
  expanded=${removal/\~\/.claude/$HOME/.claude}
  if eval "$expanded" > "$SETTINGS.off" 2>/dev/null \
     && jq -e 'has("ultracode") | not' "$SETTINGS.off" >/dev/null 2>&1; then
    pass "the printed 'turn it off' command actually removes the key"
  else
    fail "the printed 'turn it off' command actually removes the key" "ran: $expanded"
  fi
  rm -f "$SETTINGS.off"
else
  fail "the installer prints a removal command" "no jq del line in $uc_log"
fi

# Last, because it destroys the sandbox's settings.json: the flag must degrade
# to a warning rather than a crash when there is nothing to merge into.
mv "$SETTINGS" "$SETTINGS.bak"
uc_nofile_log="$SANDBOX/install-ultracode-nofile.log"
if bash "$SRC/install.sh" --ultracode </dev/null >"$uc_nofile_log" 2>&1; then
  pass "install.sh --ultracode still exits 0 when settings.json is absent"
else
  fail "install.sh --ultracode still exits 0 when settings.json is absent" \
       "see $uc_nofile_log"
fi
mv "$SETTINGS.bak" "$SETTINGS" 2>/dev/null || true

# ─── Suite 11: Kimi Code CLI bridge (opportunistic) ───────────────────
# Kimi is a third agent runtime (npm @moonshot-ai/kimi-code, bin `kimi`).
# install.sh only touches it when ~/.kimi-code already exists — it must
# never fabricate that directory for a machine that never installed Kimi.

section "Kimi bridge: absent when ~/.kimi-code does not exist"

[[ ! -e "$HOME/.kimi-code" ]] \
  && pass "install.sh does not create ~/.kimi-code on a machine without Kimi" \
  || fail "install.sh does not create ~/.kimi-code on a machine without Kimi" \
       "found $HOME/.kimi-code after a run with no pre-existing Kimi install"

section "Kimi bridge: agents + config wiring when Kimi is present"

# Seed a config.toml shaped like Kimi's real one: a root-level scalar first,
# then table sections — this is what makes "insert before the first [table]"
# a real constraint and not a no-op. A TOML bare key after a [table] header
# belongs to THAT table, not the root; appending at EOF would silently nest
# the new keys under [services.moonshot_fetch.oauth] instead of the root.
mkdir -p "$HOME/.kimi-code"
cat > "$HOME/.kimi-code/config.toml" <<'EOF'
default_model = "kimi-code/kimi-for-coding"

[providers."managed:kimi-code"]
type = "kimi"

[services.moonshot_fetch.oauth]
storage = "file"
EOF
# Kimi writes tui.toml on its first TUI run; the stock file ends with a
# COMMENTED [status_line] example naming the very path we wire. That comment
# is the trap: a substring check reads it as "already wired" on every
# machine, so the assertions below require an ACTIVE command line.
cat > "$HOME/.kimi-code/tui.toml" <<'EOF'
theme = "auto" # "auto" | "dark" | "light" | custom theme name

[editor]
command = "" # Empty uses $VISUAL / $EDITOR

# [status_line]
# command = "~/.kimi-code/statusline.sh"
EOF

kimi_log="$SANDBOX/install-kimi.log"
if bash "$SRC/install.sh" </dev/null >"$kimi_log" 2>&1; then
  pass "install.sh exits 0 with ~/.kimi-code present"
else
  fail "install.sh exits 0 with ~/.kimi-code present" "see $kimi_log"
fi

KIMI_CFG="$HOME/.kimi-code/config.toml"

diff -q "$SRC/configs/kimi-agents/ask-claude.md" "$HOME/.kimi-code/agents/ask-claude.md" >/dev/null 2>&1 \
  && pass "ask-claude.md deployed to ~/.kimi-code/agents/ byte-for-byte" \
  || fail "ask-claude.md deployed to ~/.kimi-code/agents/ byte-for-byte"
diff -q "$SRC/configs/kimi-agents/ask-codex.md" "$HOME/.kimi-code/agents/ask-codex.md" >/dev/null 2>&1 \
  && pass "ask-codex.md deployed to ~/.kimi-code/agents/ byte-for-byte" \
  || fail "ask-codex.md deployed to ~/.kimi-code/agents/ byte-for-byte"

# The load-bearing property: the new keys land BEFORE the first [table] line,
# i.e. at TOML root scope — not appended after it into the wrong table.
first_bracket_line=$(grep -n '^\[' "$KIMI_CFG" | head -1 | cut -d: -f1)
perm_line=$(grep -n '^default_permission_mode[[:space:]]*=' "$KIMI_CFG" | head -1 | cut -d: -f1)
skills_line=$(grep -n '^extra_skill_dirs[[:space:]]*=' "$KIMI_CFG" | head -1 | cut -d: -f1)
if [[ -n "$perm_line" && -n "$first_bracket_line" && "$perm_line" -lt "$first_bracket_line" ]]; then
  pass "default_permission_mode inserted at TOML root scope (before first [table])"
else
  fail "default_permission_mode inserted at TOML root scope" \
       "perm_line=$perm_line first_bracket_line=$first_bracket_line"
fi
if [[ -n "$skills_line" && -n "$first_bracket_line" && "$skills_line" -lt "$first_bracket_line" ]]; then
  pass "extra_skill_dirs inserted at TOML root scope (before first [table])"
else
  fail "extra_skill_dirs inserted at TOML root scope" \
       "skills_line=$skills_line first_bracket_line=$first_bracket_line"
fi
grep -q '^default_permission_mode = "yolo"$' "$KIMI_CFG" \
  && pass "default_permission_mode set to yolo" \
  || fail "default_permission_mode set to yolo"
grep -qF "extra_skill_dirs = [\"$HOME/.claude/skills\"]" "$KIMI_CFG" \
  && pass "extra_skill_dirs points at this machine's ~/.claude/skills" \
  || fail "extra_skill_dirs points at this machine's ~/.claude/skills"
# Original sections must survive untouched — this is a targeted insert, not a rewrite.
grep -q '^\[providers\."managed:kimi-code"\]$' "$KIMI_CFG" \
  && pass "pre-existing [providers...] section preserved" \
  || fail "pre-existing [providers...] section preserved"

section "Kimi bridge: dangerous-command guardian hook"

# Kimi does not recognize Claude Code's {"decision":"block",...} convention
# (verified live against Kimi 2.0.0 — it silently ALLOWS the command), so
# decision-to-kimi.sh translates it into Kimi's own
# {"hookSpecificOutput":{"permissionDecision":"deny",...}} shape. Test the
# REAL shipped composition: the deployed adapter wrapping the deployed
# pre-tool-guardian.sh, exactly as install.sh wires them in config.toml.
diff -q "$SRC/configs/kimi-hooks/decision-to-kimi.sh" "$HOME/.kimi-code/hooks/decision-to-kimi.sh" >/dev/null 2>&1 \
  && pass "decision-to-kimi.sh deployed to ~/.kimi-code/hooks/ byte-for-byte" \
  || fail "decision-to-kimi.sh deployed to ~/.kimi-code/hooks/ byte-for-byte"
[[ -x "$HOME/.kimi-code/hooks/decision-to-kimi.sh" ]] \
  && pass "decision-to-kimi.sh is executable" \
  || fail "decision-to-kimi.sh is executable"

_kimi_guardian_cmd="$HOME/.kimi-code/hooks/decision-to-kimi.sh $HOME/.claude/hooks/pre-tool-guardian.sh"
grep -qF "command = \"$_kimi_guardian_cmd\"" "$KIMI_CFG" \
  && pass "[[hooks]] wires PreToolUse/Bash to the guardian adapter" \
  || fail "[[hooks]] wires PreToolUse/Bash to the guardian adapter"
grep -A3 '\[\[hooks\]\]' "$KIMI_CFG" | grep -q 'event = "PreToolUse"' \
  && pass "guardian hook declares event = PreToolUse" \
  || fail "guardian hook declares event = PreToolUse"

# Functional: a force-push to main must be denied WITH the guardian's own
# reason text, and a safe command must pass through untouched. This is the
# exact composition Kimi invokes at runtime, not just the adapter in
# isolation.
_guardian_deny=$(printf '{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}}' \
  | "$HOME/.kimi-code/hooks/decision-to-kimi.sh" "$HOME/.claude/hooks/pre-tool-guardian.sh")
if printf '%s' "$_guardian_deny" | grep -q '"permissionDecision": *"deny"' \
   && printf '%s' "$_guardian_deny" | grep -q 'Force push to main/master blocked'; then
  pass "force-push to main is denied with the guardian's own reason text"
else
  fail "force-push to main is denied with the guardian's own reason text" "$_guardian_deny"
fi
_guardian_allow=$(printf '{"tool_name":"Bash","tool_input":{"command":"echo hi"}}' \
  | "$HOME/.kimi-code/hooks/decision-to-kimi.sh" "$HOME/.claude/hooks/pre-tool-guardian.sh")
[[ -z "$_guardian_allow" ]] \
  && pass "a safe command produces no deny output (allowed)" \
  || fail "a safe command produces no deny output (allowed)" "$_guardian_allow"
unset _kimi_guardian_cmd _guardian_deny _guardian_allow

section "Kimi bridge: quota status line"

# Kimi's footer line 1 is replaced by whatever `[status_line] command` in
# tui.toml prints (300 ms deadline, first stdout line only, non-zero exit or
# empty line = built-in footer). install.sh wires the deployed launcher,
# which hands off to the kimi-usage skill helper. Test the shipped
# composition: the deployed launcher over the deployed helper, rendering
# from a cache fixture — never from the network, which the hot path must
# not touch. `[editor] command` above is the decoy: it sits in a different
# table and must be neither counted nor edited.
diff -q "$SRC/configs/kimi-hooks/statusline.sh" "$HOME/.kimi-code/hooks/statusline.sh" >/dev/null 2>&1 \
  && pass "statusline.sh deployed to ~/.kimi-code/hooks/ byte-for-byte" \
  || fail "statusline.sh deployed to ~/.kimi-code/hooks/ byte-for-byte"
[[ -x "$HOME/.kimi-code/hooks/statusline.sh" ]] \
  && pass "statusline.sh is executable" \
  || fail "statusline.sh is executable"
[[ -f "$HOME/.claude/skills/kimi-usage/scripts/kimi_usage.py" ]] \
  && pass "kimi-usage helper deployed under ~/.claude/skills/" \
  || fail "kimi-usage helper deployed under ~/.claude/skills/"

KIMI_TUI="$HOME/.kimi-code/tui.toml"
_sl_cmd_line="command = \"$HOME/.kimi-code/hooks/statusline.sh\""
_sl_active=$(awk '/^\[status_line\]/{t=1; next} /^\[/{t=0} t && /^command[[:space:]]*=/' "$KIMI_TUI")
[[ "$_sl_active" == "$_sl_cmd_line" ]] \
  && pass "tui.toml [status_line] command points at the deployed launcher" \
  || fail "tui.toml [status_line] command points at the deployed launcher" "got: $_sl_active"
grep -qF '# command = "~/.kimi-code/statusline.sh"' "$KIMI_TUI" \
  && pass "Kimi's commented [status_line] example is left untouched" \
  || fail "Kimi's commented [status_line] example is left untouched"
grep -q '^command = "" # Empty uses' "$KIMI_TUI" \
  && pass "[editor] command in the neighbouring table is untouched" \
  || fail "[editor] command in the neighbouring table is untouched"
grep -q 'Configured: tui.toml \[status_line\]' "$kimi_log" \
  && pass "install log reports the status line wiring" \
  || fail "install log reports the status line wiring" "see $kimi_log"

# Functional render through the real launcher. A fresh cache (fetched now,
# windows unexpired) means no refresh is due, so nothing is spawned. The
# month row is 60% used at 50% elapsed: delta = 60 - 47.5 = +12.5 -> "+12%",
# past the +5 threshold, so the circles theme shows its top symbol ◉.
_sl_now=$(date +%s)
python3 - "$HOME/.kimi-code/.clade-usage-cache.json" "$_sl_now" <<'PY'
import json, sys
path, now = sys.argv[1], int(sys.argv[2])
month = 30 * 86400
json.dump({
    "fetched_at": now,
    "source": "fixture",
    "rows": [
        {"id": "limit5h", "window": "5h", "period_s": 18000, "used_percent": 40.0,
         "remaining_percent": 60.0, "resets_at": now + 3 * 3600, "resets_in": "3h",
         "elapsed_percent": 40.0, "pace_delta": 2.0, "projected_percent": 100.0},
        {"id": "monthTotal", "window": "month", "period_s": month, "used_percent": 60.0,
         "remaining_percent": 40.0, "resets_at": now + month // 2, "resets_in": "15d",
         "elapsed_percent": 50.0, "pace_delta": 12.5, "projected_percent": 120.0,
         "code_percent": 10.0, "kimi_percent": 50.0},
    ],
    "extra_usage": None,
    "seen": {},
}, open(path, "w"))
PY
_sl_payload='{"model":"K2.8 Preview","cwd":"/tmp/proj","gitBranch":"feat/x","permissionMode":"auto","planMode":false,"contextTokens":10,"sessionId":"s1","version":"2.0.1"}'
_sl_out=$(printf '%s' "$_sl_payload" | "$HOME/.kimi-code/hooks/statusline.sh" 2>/dev/null; echo "rc=$?")
_sl_rc="${_sl_out##*rc=}"
_sl_line="${_sl_out%rc=*}"
[[ "$_sl_rc" == "0" ]] \
  && pass "launcher exits 0" \
  || fail "launcher exits 0" "rc=$_sl_rc"
[[ "$(printf '%s' "$_sl_line" | grep -c .)" == "1" ]] \
  && pass "launcher prints exactly one line (Kimi takes only the first)" \
  || fail "launcher prints exactly one line" "$_sl_line"
_sl_plain=$(printf '%s' "$_sl_line" | sed 's/\x1b\[[0-9;]*m//g')
printf '%s' "$_sl_plain" | grep -qE '^proj git:\(feat/x\)  ' \
  && pass "line opens with directory and branch (the Clade convention), no mode/model by default" \
  || fail "line opens with directory and branch (the Clade convention), no mode/model by default" "$_sl_plain"
printf '%s' "$_sl_plain" | grep -qE '◉ \+12% \(1[45]d\) · 5h 40% \(3h\)' \
  && pass "line carries the month pace (+12%) and the 5h burst window (40%, 3h)" \
  || fail "line carries the month pace and the 5h burst window" "$_sl_plain"
# Kimi's own `[status_line] items` list chooses the slots: with mode and
# model requested, the badge and model name come back, in that order. The
# launcher's per-session memo keys on tui.toml's mtime at one-second
# resolution, so an edit inside the same second as the last render would
# replay the old line — drop the memo, as a minute's passing would.
_sl_tui_bak="$SANDBOX/tui.toml.items-bak"
cp "$KIMI_TUI" "$_sl_tui_bak"
rm -f "$HOME/.kimi-code/.clade-usage-memo-"*
python3 - "$KIMI_TUI" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
# Anchor on the ACTIVE table header: the stock file's commented example
# (`# [status_line]`) contains the same text and must not be the one edited.
path.write_text(re.sub(r"(?m)^\[status_line\]\n", '[status_line]\nitems = ["mode","model","cwd","git","tips"]\n', path.read_text(), count=1))
PY
_sl_items=$(printf '%s' "$_sl_payload" | "$HOME/.kimi-code/hooks/statusline.sh" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g')
printf '%s' "$_sl_items" | grep -qF '[Never Ask]  K2.8 Preview  proj git:(feat/x)  ' \
  && pass "[status_line] items brings the mode badge and model back in Kimi's order" \
  || fail "[status_line] items brings the mode badge and model back in Kimi's order" "$_sl_items"
cp "$_sl_tui_bak" "$KIMI_TUI"
rm -f "$HOME/.kimi-code/.clade-usage-memo-"*
unset _sl_tui_bak _sl_items
# `style off` must yield NO line: that is the documented signal that hands
# footer line 1 back to Kimi's built-in slots (goal, tasks, tips).
printf 'off\n' > "$HOME/.kimi-code/.clade-usage-style"
_sl_off=$(printf '%s' "$_sl_payload" | "$HOME/.kimi-code/hooks/statusline.sh" 2>/dev/null)
[[ -z "$_sl_off" ]] \
  && pass "style off prints nothing (built-in footer returns)" \
  || fail "style off prints nothing (built-in footer returns)" "$_sl_off"
rm -f "$HOME/.kimi-code/.clade-usage-style"
# Missing helper: the launcher must stay silent and green, never break a footer.
mv "$HOME/.claude/skills/kimi-usage/scripts/kimi_usage.py" "$SANDBOX/kimi_usage.py.moved"
_sl_missing=$(printf '%s' "$_sl_payload" | "$HOME/.kimi-code/hooks/statusline.sh" 2>&1; echo "rc=$?")
[[ "$_sl_missing" == "rc=0" ]] \
  && pass "launcher without its helper exits 0 with no output" \
  || fail "launcher without its helper exits 0 with no output" "$_sl_missing"
mv "$SANDBOX/kimi_usage.py.moved" "$HOME/.claude/skills/kimi-usage/scripts/kimi_usage.py"
rm -f "$HOME/.kimi-code/.clade-usage-cache.json"
unset _sl_cmd_line _sl_active _sl_now _sl_payload _sl_out _sl_rc _sl_line _sl_plain _sl_off _sl_missing

section "Kimi bridge: idempotent re-run and non-destructive of a user override"

# A user (or Kimi itself) may set a different mode by hand — install.sh must
# never clobber an existing value, only fill in a missing key.
python3 - "$KIMI_CFG" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(path.read_text().replace(
    'default_permission_mode = "yolo"',
    'default_permission_mode = "manual"',
))
PY

before_lines=$(wc -l < "$KIMI_CFG")
kimi_log2="$SANDBOX/install-kimi-2.log"
bash "$SRC/install.sh" </dev/null >"$kimi_log2" 2>&1 || true
after_lines=$(wc -l < "$KIMI_CFG")

grep -q '^default_permission_mode = "manual"$' "$KIMI_CFG" \
  && pass "re-run never overwrites a user-set default_permission_mode" \
  || fail "re-run never overwrites a user-set default_permission_mode" \
       "expected manual to survive, see $KIMI_CFG"

perm_count=$(grep -cE '^default_permission_mode[[:space:]]*=' "$KIMI_CFG")
skills_count=$(grep -cE '^extra_skill_dirs[[:space:]]*=' "$KIMI_CFG")
hooks_count=$(grep -cF '[[hooks]]' "$KIMI_CFG")
if [[ "$perm_count" -eq 1 && "$skills_count" -eq 1 && "$hooks_count" -eq 1 ]]; then
  pass "re-run is idempotent (no duplicate keys or hook blocks after 2 runs)"
else
  fail "re-run is idempotent (no duplicate keys or hook blocks after 2 runs)" \
       "default_permission_mode x$perm_count, extra_skill_dirs x$skills_count, [[hooks]] x$hooks_count"
fi
if [[ "$before_lines" -eq "$after_lines" ]]; then
  pass "idempotent re-run does not grow the file"
else
  fail "idempotent re-run does not grow the file" "before=$before_lines after=$after_lines"
fi
_sl_count=$(awk '/^\[status_line\]/{t=1; next} /^\[/{t=0} t && /^command[[:space:]]*=/' "$KIMI_TUI" | wc -l | tr -d ' ')
[[ "$_sl_count" == "1" ]] \
  && pass "re-run leaves exactly one [status_line] command (no duplicate wiring)" \
  || fail "re-run leaves exactly one [status_line] command" "found $_sl_count"

# A footer the user wrote themselves is theirs: install.sh must report it
# and leave it, never swap in Clade's.
python3 - "$KIMI_TUI" "$HOME" <<'PY'
import sys
from pathlib import Path
path, home = Path(sys.argv[1]), sys.argv[2]
path.write_text(path.read_text().replace(
    f'command = "{home}/.kimi-code/hooks/statusline.sh"',
    'command = "~/my-own-hud.sh"',
))
PY
kimi_log3="$SANDBOX/install-kimi-3.log"
bash "$SRC/install.sh" </dev/null >"$kimi_log3" 2>&1 || true
grep -qF 'command = "~/my-own-hud.sh"' "$KIMI_TUI" \
  && pass "a user-authored status line command survives a re-run" \
  || fail "a user-authored status line command survives a re-run" "see $KIMI_TUI"
! grep -qF "$HOME/.kimi-code/hooks/statusline.sh" "$KIMI_TUI" \
  && pass "Clade's command is not added beside the user's" \
  || fail "Clade's command is not added beside the user's" "see $KIMI_TUI"
grep -q 'Skipped: Kimi status line' "$kimi_log3" \
  && pass "install log says the status line was skipped, and why" \
  || fail "install log says the status line was skipped, and why" "see $kimi_log3"
unset _sl_count kimi_log3 KIMI_TUI

section "Kimi bridge: gone when ~/.kimi-code is gone"

# Baseline: install.sh must never fabricate ~/.kimi-code for a machine that
# doesn't have it (already asserted above). Prove the CONVERSE mutation
# would be caught too: delete a bridge agent and confirm a re-run restores
# it (this IS an unconditional copy, unlike the config.toml patch above,
# which must never overwrite).
rm -f "$HOME/.kimi-code/agents/ask-claude.md"
bash "$SRC/install.sh" </dev/null >/dev/null 2>&1 || true
[[ -f "$HOME/.kimi-code/agents/ask-claude.md" ]] \
  && pass "a deleted bridge agent is restored on the next install" \
  || fail "a deleted bridge agent is restored on the next install"

unset KIMI_CFG first_bracket_line perm_line skills_line before_lines after_lines perm_count skills_count hooks_count

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
